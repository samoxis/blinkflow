# BlinkFlow on QNX

The robot's brain runs on **QNX 8.0**; the simulator, the camera and BlinkFlow stay on the
developer's machine. BlinkFlow becomes a host tool for robot software that runs on QNX: it deploys the
brain to the target, drives the simulated robot from it, records what the brain decided, and checks
that a recording gives the same decisions on QNX as on the machine where the fix was made.

Built from Nov 18, 2026, on top of BlinkFlow (Meta hackathon entry, Oct 26 – Nov 4). New code:
`blinkflow/qnx/` (bridge, target, probe, vm, CLI), the `--target qnx` option in `blinkflow/sim.py` and
`blinkflow/watch.py`, and `tests/test_qnx_*.py`.

## What it does

| Command | What happens |
|---|---|
| `python3 -m blinkflow.qnx vm build` / `up` / `down` | builds a QNX 8.0 x86_64 image with Python and SSH (`mkqnximage`) and runs it under QEMU/KVM, no root needed |
| `python3 -m blinkflow.qnx info` | what the target is (uname, Python) |
| `python3 -m blinkflow.qnx walk --seconds 20` | headless simulator on the host, the brain on QNX at priority 30 (`on -p 30`), its record fetched back |
| `python3 -m blinkflow.qnx replay RUN.jsonl.gz --brain DIR` | the same brain replays the same recording on QNX and on the host; every answer is compared |
| `python3 -m blinkflow.sim --target qnx` | the filmed scenario (Viser window, capture sidecar) with the brain on QNX |
| `python3 -m blinkflow.watch live --target qnx --loop` | the whole BlinkFlow loop (watch, SAM 3.1 evidence, Muse Wonder diagnosis, Muse Code fix, replay proof) with the brain on QNX |

### How the brain reaches the simulator

The brain talks NDJSON JSON-RPC to two UNIX sockets (`robotd`, `tofd`). `blinkflow/qnx/bridge.py`
carries them over TCP without parsing a byte: on the host, `expose` maps 127.0.0.1:7701/7702 to the
simulator's sockets; on QNX, `offer` creates `/tmp/robotd.sock` and `/tmp/tof.sock` that dial the host
(10.0.2.2 under QEMU user networking). The brain runs unchanged. One file, standard library only;
it is copied to the target with the brain.

### Clocks

The brain stamps its record with its own monotonic clock, which on QNX is not the host's. Before a
launch, BlinkFlow measures the offset between the host's epoch and the target's monotonic clock over
one SSH session (fastest of 15 echoes, error under half its round trip), so the brain's first tick
lands on the host clock that the video and SAM 3.1's contact time use.

### The cross-target check

`replay` deploys a brain, feeds a recording through it on QNX and on the host
(`blinkflow/qnx/probe.py`, the brain's own `record.read` + `Brain.tick`), fingerprints every answer
(command kind, vx, vyaw and state, exact `repr`) and gives one verdict:

- **identical**: every answer equal, bit for bit;
- **same decisions**: every command kind and state equal; the numbers differ, by at most `max_abs`;
- **different decisions**: a command kind or a state differs (exit code 1).

## The whole loop with the brain on QNX (Nov 18, 2026)

`python3 -m blinkflow.watch live --target qnx --loop` on a copy of the buggy brain (`~/duck-target` at `b2fe90a`, branch `qnx-incident` in `~/duck-target-qnx`):

1. **Watch.** The brain runs on QNX and drives the filmed simulator. Muse Glimmer (local) raises a hand twice; SAM 3.1 confirms a contact between the *white robot* and the *purple box* at 12.175 s brain time ($0.15 of SAM).
2. **Diagnose.** Muse Wonder on the key frames, the brain's log from QNX and the code. The first diagnosis named `heading.yaw_sign` (confidence 0.72). Muse Code flipped it in all three attempts, the robot left the camera in the twin's replay, and BlinkFlow refused to call that fixed (verdict invalid: robot found in 0 frames). A second diagnosis on the same SAM evidence named `obstacle.side_memory_seconds = 0.0`.
3. **Fix and prove.** Muse Code changed that one line. The twin's replay of the same scene: contact 1 → 0, closest 106 px; control in every other scene clean. Kept as commit `cc31fc1`.
4. **Back on QNX.** The fixed brain deployed to QNX, the filmed scene again for 20 s: SAM 3.1 finds no contact (closest 28 px, at 15.8 s). `replay` of the QNX incident recording (389 ticks): the buggy brain reproduces it (0 differing) and the fixed brain answers differently from 1.734 s on (355 of 389 commands); QNX vs host **identical** for both.

Paid model calls for the whole session: about $2.40 (SAM 3.1, Muse Wonder, Muse Code contributor lane), including the failed first loop.

One fix outside the loop was needed: `muse` had updated itself to 1.4.23 during the session and `muse-code-sdk` 1.4.14 refused the host (`MuseHostMismatchError`); `requirements.txt` now pins the SDK and MSP at 1.4.23.

## Measured on Nov 18, 2026 (QEMU/KVM VM, QNX 8.0.0, Python 3.13.7 on the target, 3.12.3 on the host)

- `walk`: 15 s of the demo scene driven from QNX, 295 brain ticks recorded and fetched back.
- `sim --target qnx`, filmed: the buggy brain (`~/duck-target` at `b2fe90a`) on QNX for 14 s, 275 ticks, 480 frames captured; the robot walks along the purple box and its right leg reaches it at the end, as with the brain on the host. Seen on the frames; SAM 3.1 measured the same scene in the whole-loop run above (contact at 12.175 s).
- `replay` of the purple-box incident recording (`examples/purple-box-sil/run.jsonl.gz`, 289 ticks, live simulator):
  - with the brain that made it (`brain-before`): 0 commands differ from the recording on QNX or on the host; **identical**, same SHA-256 on both;
  - with the fixed brain (`brain-after`): 235 commands differ from the recording on both, first at 2.506 s; QNX vs host **same decisions**: 5 ticks apart (from tick 97), at most 1.1e-16 (one unit in the last place), no command kind or state different.

The one-ULP gap is real and is what this check is for: the same Python source does not promise the
same last bit on another OS and interpreter. Whether it comes from the C maths library or from the
Python version is not separated here (the host has no Python 3.13 installed).

## Set up (about 30 minutes, once)

1. **QNX SDP 8.0** with a free non-commercial licence: create a myQNX account, request the licence,
   deploy it to your account in the License Manager, install the QNX Software Center, activate the key
   there and install *QNX Software Development Platform 8.0* (we used `~/qnx800`). Nothing from the SDP
   is in this repository.
2. QEMU with KVM (`sudo apt install qemu-system-x86`, your user in the `kvm` group) and an SSH key
   (`~/.ssh/id_ed25519.pub`).
3. The image and the VM:

   ```bash
   python3 -m blinkflow.qnx vm build      # into ~/qnx-vm (BLINKFLOW_QNX_VM), SDP from ~/qnx800 (QNX_SDP)
   python3 -m blinkflow.qnx vm up         # SSH on 127.0.0.1:2222 (BLINKFLOW_QNX_PORT)
   python3 -m blinkflow.qnx info
   ```

4. The check on the bundled incident, no simulator, no key:

   ```bash
   python3 -m blinkflow.qnx replay examples/purple-box-sil/run.jsonl.gz --brain examples/purple-box-sil/brain-before
   python3 -m blinkflow.qnx replay examples/purple-box-sil/run.jsonl.gz --brain examples/purple-box-sil/brain-after
   ```

5. With the Microduck simulator installed (see [RUNNING.md](RUNNING.md)): `python3 -m blinkflow.qnx walk`.

A board instead of the VM: set `BLINKFLOW_QNX_HOST`, `BLINKFLOW_QNX_PORT`,
`BLINKFLOW_QNX_GATEWAY` (the host's address as the board sees it) and `BLINKFLOW_QNX_BIND` (the host
address the bridge listens on, one the board can reach; default 127.0.0.1, enough for the VM), with
Python 3.11+ and SSH on the board. Not yet tried on a board.

Tests (host only): `python3 -m unittest tests.test_qnx_bridge tests.test_qnx_probe tests.test_qnx_target -v`.

## Limits

- Tested on a QEMU/KVM virtual machine, not on a board.
- The brain is Python; it runs on QNX's Python unchanged. No timing or latency results are claimed.
- The bridge is unauthenticated plain TCP; `expose` binds 127.0.0.1 by default and must stay on a
  private link.
- The model steps (SAM 3.1, Muse Wonder, Muse Code) run on the host through the Meta Model API, as in
  BlinkFlow; the brain on QNX is the system under test.
