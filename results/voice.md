# Voice and approval

`blinkflow/voice.py`: the person holds **F9** (anywhere on the desktop; the sidecar records the microphone
while it is down) and says in English what they saw. The moment is **the key press on BlinkFlow's clock
minus the time said in the sentence**: the key carries the clock, the words carry the delay, so how long
the person takes to speak does not matter. Muse Voice Transcribe (`muse-voice-transcribe-1.0`,
`PUSH_TO_TALK`) writes the sentence down; Muse Glimmer, locally, reads from it how long ago, what happened
and what was touched (JSON schema; Muse Spark if Glimmer's answer cannot be used). The buffer from 5 s
before that moment to 3 s after it (never past the press + 1 s) goes to `blinkflow.see`, whose namer gets
the sentence as a hint; SAM 3.1 confirms with the watcher's rules (what the proof calls a contact or a
fall, and a robot that moved). Then the existing loop, with its evidence reused. Typing is the fallback
(`--type`: Enter is the key press, then the sentence).

`blinkflow/fix.py` now asks twice: after the diagnosis it prints the cause in two plain sentences and
asks **Fix it? [y/n]** before Muse Code writes (again before each retry); after the proof it asks
**Keep the fix? [y/n]**, and `n` is `git reset --hard` to the base commit. `--auto` asks no one; the bug
suite, the profile tool and the watcher pass it, so the quick loop, the watcher and the proof run as before.

## Without a microphone: 5 sentences from a TTS

`tools/voice_suite.py tts` (scorer side: it knows the truth, BlinkFlow gets only the clip, the moment the
key goes down and the sound). Five English sentences spoken by espeak-ng (5 voices; a system package, no
voice files in this repo), each sent through `blinkflow.voice clip` as if from the key: the clip plays on
the wall clock as the buffer, the key goes down a person's delay after the true contact (chosen off the
number said by 0.4-0.8 s, both ways) and stays down for the sentence. Truth: the simulator's and the twin's
contact logs (`tools/score_contact.py`), never read by BlinkFlow. Oct 27, run `voice/tts/20261027-170606`.

| # | said (Muse Voice Transcribe) | true contact (s) | key after it (s) | said ago (s) | moment said - true (s) | window (s) | SAM 3.1 saw | seen - true (s) | names | hear + read (s) | see (s) | $ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | three seconds ago the duck's right leg hit the purple box. | 12.27 | +3.40 | 3 | **+0.40** | 7.7-15.7 | contact | +0.125 | white robot / purple box | 2.5 + 1.1 | 21 | 0.104 |
| 2 | just how the robot bumped into the purple box.! | 11.48 | +0.80 | 0 | **+0.80** | 7.3-13.3 | contact | -0.325 | white robot / purple box | 1.9 + 0.9 | 19 | 0.072 |
| 3 | about five seconds ago it walked into the box. | 11.71 | +4.30 | 5 | **-0.70** | 6.0-14.0 | contact | +0.848 | white robot / purple box | 2.3 + 0.8 | 21 | 0.079 |
| 4 | Two seconds seconds ago it's foot clipped the purple box. | 12.38 | +2.60 | 2 | **+0.60** | 8.0-16.0 | contact | -0.015 | white robot / purple box | 1.8 + 1.0 | 15 | 0.104 |
| 5 | The robot kicked kicked the little cube, maybe four seconds ago. | 10.56 | +3.20 | 4 | **-0.80** | 4.8-12.8 | contact | +0.580 | white robot / orange cube | 1.9 + 1.0 | 15 | 0.104 |

Clips 1-3 are live runs of the purple box (live-check), 4 and 5 twin renders (b11 box, b1 low cube).

- **5/5 heard, read and seen.** Glimmer read the delay exactly every time (also from "just how", Muse
  Voice's version of espeak's "just now"), and the true contact fell inside the window every time.
- The moment's error here is exactly the gap between the number said and the key's real delay, which the
  test chose (0.4-0.8 s). So this table shows that the chain adds no error of its own: transcription,
  reading and clock together add 0.00 s. How far a real person's words land is what the mic test measures.
- Doubled words ("seconds seconds", "kicked kicked") and "it's foot" came back from Muse Voice on espeak's
  robotic speech; none changed the reading.
- SAM 3.1's first contact is -0.33..+0.85 s from the truth: see's own accuracy on these clips (the
  watcher measured +0.53, -0.36 and -0.44 s on 1, 2 and 5), not the voice's.
- From the key's release: transcription 1.8-2.5 s and reading 0.8-1.1 s, then see 15-21 s. Muse Voice
  costs $0.0002 a sentence; SAM $0.07-0.10 a window; $0.46 for the five.

## The questions, through a terminal

`tools/voice_suite.py gate`: sentence 4 through the whole loop on a git clone of b11's target as drawn,
in a pseudo-terminal (`script`), answering `y` to "Fix it?" and `n` to "Keep the fix?". Printed before
the first question:

> Cause: The robot saw the box while it was still diagonally ahead, but forgot that side obstacle almost
> immediately once it moved alongside the body and out of the forward view. It therefore kept walking
> straight for more than a second while its side closed the remaining distance and touched the box.
> (brain.toml, lines 29-29; confidence 0.68)

Muse Code raised `side_memory_seconds` (the mutated line), the replay showed no contact (fixed and verified in
attempt 1, 136 s for the loop), the answer was `n`, and the target came back to its first commit with a
clean tree. The report says "Fixed and verified in attempt 1 of 1, then rolled back" and lists both
answers; its model manifest includes the transcription and Glimmer's reading. Cost $1.09.

Found on the way: ffmpeg reads its stdin for commands, and the replay before any change renders (with
ffmpeg) while "Fix it?" waits, so keys typed at that moment could be swallowed. The first run of this
test hung at the question exactly that way. When BlinkFlow asks, it now keeps the terminal for the answers
and gives every child process `/dev/null` as stdin.

## Push-to-talk on Windows

The sidecar (`--listen`) opens the microphone with ffmpeg dshow and keeps only the last 0.5 s in memory
while the key is up; nothing is written to disk. Holding the key records from 0.3 s before the press to
0.3 s after the release, served at `/listen` (long poll, press and release on the Windows clock, turned
into BlinkFlow's) and `/utterance/<id>` (WAV, mono 16-bit 24 kHz). Checked with F9 pressed by a script for
1.5 s: one utterance, 2.10 s of audio. This PC has only a virtual microphone (Steam Streaming Microphone),
so the audio was silence, Muse Voice returned an empty transcript, and BlinkFlow says it heard nothing.

## With a real voice (to run)

```bash
python -m blinkflow.voice_test --mic --runs 3
python3 tools/voice_suite.py table ~/blinkflow-runs/voice/mic/<stamp>
```

Each run starts the simulator on the purple-box scenario (25 s); hold F9 when the robot touches the box and
say what you saw and when. `--loop` also starts the loop and asks at the terminal; `--mic-name` picks the
microphone (default: the first one that is not virtual). Not run yet.

## Limits

- The TTS test measures the chain, not a person: the key's delays were chosen, and espeak speaks slowly
  and clearly. Human error in "three seconds ago" is the open question, and the window (5 s before,
  3 s after) was chosen without data on it.
- Only contacts were spoken about; a fall goes through the same path (Glimmer read "fell into the yellow
  pit a couple of seconds ago" as a fall, 2 s) but was not run through SAM here.
- One sentence per key press, English only (`languageBias: English`).
