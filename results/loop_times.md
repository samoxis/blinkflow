# The purple-box loop: seen -> fixed and verified, twelve full loops

Ten full loops on the live purple-box incident since the quick loop (`results/quick_loop.md`, opt-3, commit
07fd1de), read from each run's `fix.json` and `models.json` (`~/blinkflow-runs/<run>/fix/`). Three more are
kept elsewhere: gate-1 in `docs/SAFETY.md`, contrib-1 in `DEVLOG.md` (Oct 28, 11:30) and the fresh-setup run
(`voice/20261028-192828`) in `results/fresh_setup.md`. Machine time on
BlinkFlow's clock: the seconds a person takes to answer "Fix it?" are not counted. All fixed in attempt 1.
Since Oct 31 the clock stops only after the control (the four other scenes replayed with the change and
clean), so the last two rows include it; the column after it gives them without the control, comparable
with the ten before.

| run | how the incident came in | seen -> fixed and verified (s) | without the control (s) | see (s) | understand (s) | Muse Wonder s / output tokens | Muse Code (s) | replay after (s) | SAM 3.1 calls from the cache | model cost |
|---|---|---|---|---|---|---|---|---|---|---|
| `quick/opt-3` | recorded live clip, `profile_loop` | **137.1** | = | 20.8 | 63.6 | 54.9 / 4680 | 18.9 | 33.8 | 0/32 | $0.88 |
| `voice/tts/20261027-170606/gate` | TTS sentence, terminal | **135.8** | = | 0.0 | 66.9 | 58.6 / 6136 | 28.0 | 38.9 | 0/42 | $1.09 |
| `watch/live-5` | watcher, live simulator | **171.6** | = | 0.0 | 106.1 | 96.5 / 6058 | 19.3 | 34.0 | 0/36 | $1.06 |
| `voice/console-20261027-181434` | typed sentence, console | **166.8** | = | 0.0 | 73.5 | 62.3 / 8357 | 19.4 | 40.1 | 0/38 | $1.18 |
| `voice/console-20261027-201137` | typed sentence, console | **154.2** | = | 0.0 | 66.8 | 56.7 / 6647 | 18.7 | 37.4 | 0/60 | $1.71 |
| `voice/console-20261027-204427` | typed sentence, console | **166.4** | = | 0.0 | 73.5 | 63.8 / 8349 | 25.9 | 38.6 | 0/60 | $1.65 |
| `quick/cache-1` | recorded live clip, `profile_loop` | **177.3** | = | 38.6 | 72.8 | 64.9 / 6582 | 32.6 | 33.2 | 6/32 | $0.93 |
| `quick/cache-2` | the same again (SAM 3.1 from the cache) | **191.0** | = | 15.6 | 73.4 | 64.2 / 6063 | 71.5 | 30.6 | 32/32 | $0.34 |
| `voice/20261028-212723` | live simulator, typed sentence, terminal (scripted; `examples/purple-box/` until Oct 29) | **196.7** | = | 32.9 | 77.5 | 66.6 / 6701 | 42.2 | 39.9 | 22/56 | $0.99 |
| `voice/20261029-170922` | live simulator, spoken sentence (Ray-Ban Meta glasses, F9), answered by the person (`examples/purple-box/` until Oct 31) | **234.0** | = | 31.6 | 129.8 | 120.2 / 9102 | 37.0 | 33.4 | 50/56 | $0.50 |
| `voice/20261031-235414` | live simulator, spoken sentence (Ray-Ban Meta glasses, tap-to-talk), answered by the person in the console; the run the film shows | **386.6** | 158.3 | 31.4 | 73.6 | 62.7 / 7708 | 41.6 | 36.6 | 50/58 | $0.38 |
| `voice/20261101-093835` | the Oct 31 run's clip, sound and key press again (`voice clip`, `--auto`); `examples/purple-box/` | **368.0** | 147.8 | 27.8 | 71.3 | 61.2 / 6954 | 37.8 | 35.9 | 22/52 | $0.95 |

**135.8-234.0 s over the first 10 runs, median 169.2 s; 147.8 and 158.3 s for the last two without the control,
368.0 and 386.6 s with it (the control is 192-200 s of the loop: four twin renders and SAM 3.1).** What moves it:
Muse Wonder (its answer runs 4.7k-9.1k output tokens at ~85 tokens/s) and Muse Code (cache-2 also wrote a
regression test, 71.5 s). The console runs and the last run also measure the four other scenes on pixels after the fix (the cost includes it):

| run | box (the incident) | low_cube | ledge | corner | doorway | clean / measured |
|---|---|---|---|---|---|---|
| `voice/console-20261027-181434` | 0 contacts | clean | contact 18.11 s (a false alarm: the rule was corrected after, `control.md`) | clean | clean | 4/5 then, 5/5 re-measured |
| `voice/console-20261027-201137` | 0 contacts | clean | not measured: SAM 3.1 found no "white block" | clean | clean | 4/4, 4/5 measured |
| `voice/console-20261027-204427` | 0 contacts | clean | clean (closest gap 0 px whole mask, base apart) | clean | clean | **5/5, all measured** |
| `voice/20261028-212723` | 0 contacts | clean | clean (closest gap 0 px) | clean | clean | **5/5, all measured** |
| `voice/20261029-170922` | 0 contacts (closest 106 px) | clean | clean (closest gap 0 px) | clean | clean | **5/5, all measured** |
| `voice/20261031-235414` | 0 contacts (closest 106 px) | "clean": its "brown step" was seen in no frame, no verdict under today's rule | clean ("gray block", closest 0 px on screen, the feet 110 px above its base) | clean (50 px) | clean ("white rectangle", 36 px) | 5/5 then; 4/5 measured |
| `voice/20261101-093835` | 0 contacts (closest 107 px) | clean (orange cube, 139 px) | clean (yellow floor, 157 px) | clean (red barrier, 50 px) | clean (blue block, 14 px) | **5/5, all measured** |

Until Oct 31 the control followed objects Glimmer named in each scene; since Nov 1, each scene's own obstacle
(`blinkflow/scenes/obstacles.json`), and an obstacle seen in no frame is no verdict, not clean. The twin's own
log (scorer only) has no touch in any of these scenes.

Left out: `voice/console-20261027-203114`, stopped before any change (Muse Code's host had moved to 1.4.14
under SDK 1.4.13; DEVLOG Oct 27 21:35).

cache-1 and cache-2 are the same loop on the same recorded clip, one after the other (Oct 27, 21:54 and 21:57).
The second took every SAM 3.1 reply from the cache: the same video bytes, concept and parameters (the twin is
deterministic). Model cost $0.93 -> $0.34. The first already took 6 of its 32 from the cache: the replay after
the fix is byte-identical to the replay before it until the box is beside the robot. Both models.json files
are in [`examples/purple-box/`](https://github.com/samoxis/blinkflow/tree/49a9695/examples/purple-box) as it was at 49a9695 (`models-first-run.json`, `models.json`), every cached
call with its hash. `examples/purple-box/` held `voice/20261028-212723` at [e9b88d8](https://github.com/samoxis/blinkflow/tree/e9b88d8/examples/purple-box)
(Oct 28, 21:27: the sentence typed and both questions answered yes at the terminal by a script, 2.0 s after each).
It held `voice/20261029-170922` (Oct 29, 17:09) next: the sentence spoken through the Ray-Ban Meta glasses'
microphone with F9 held, "Fix it?" answered in the console after 7.5 s and "Keep the fix?" in the terminal after
12.6 s; 234.0 s, the slowest of the first ten (Muse Wonder wrote 9102 tokens in 120.2 s), $0.50 with 50 of 56
SAM 3.1 replies cached. Then `voice/20261031-235414` (Oct 31, 23:54), the run the film shows: a tap on the
glasses' arm, both answers yes in the console after 3.3 s and 4.0 s, 386.6 s with the control, $0.38 with 50 of
58 replies cached ([kept at 9a585ea](https://github.com/samoxis/blinkflow/tree/9a585ea/examples/purple-box)).
It now holds `voice/20261101-093835` (Nov 1, 09:38): the same clip, sound and key press run again after the
control's rule changed, both questions answered by `--auto`; 368.0 s, $0.95, only 22 of 52 replies cached (the
replays were encoded again, so their bytes, and their cache keys, changed).
