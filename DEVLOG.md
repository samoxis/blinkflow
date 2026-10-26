# Build log

All times UK.

## Mon Oct 26
- 16:00 Kickoff. Building period starts after the session.
- 16:50 Repo created from scratch: README, CLAUDE.md, this log, licence.
- 17:41 Capture buffer works: Windows sidecar keeps the last 60 s of the Viser window (ddagrab -> NVENC, 1 s segments, cursor at 60 Hz) and serves snapshots to WSL with frame times on the WSL clock. Purple-box incident filmed. Repeatability test fails on the simulator side: 5 identical runs of duck-target, contact in 3 (10.82 s, 11.68 s, 11.74 s after the brain starts), brain commands already differ at 1.61 s. Muse Glimmer beside the running sim: 20.65 GB VRAM peak, ~5 s per frame.
- 18:20 Deterministic twin works: MuJoCo world, ToF and walking policies imported from microduck_rl, robotd's walk/stand controller re-stated in Python, the brain ticked on simulated time (5 ms grid). Two runs give byte-identical brain logs and the same first contact (ankle_right, 11.47 s after the brain starts; the live sim gave 10.82-11.74 s in 3 of 5 runs). The v0.3 brain never touches the box. 15 s of scenario takes 0.8 s, or ~60 s with the incident shot rendered.
