# The pixel rule, before and after the ledge false alarm

Every saved look (SAM 3.1 replies + shot) measured again from its saved replies, no new model calls,
with the rule before (commit 7c811e2) and after this change, against ground truth the agent never reads
(the twin's contacts.csv / truth.json, the simulator's contacts-*.csv). `python3 tools/control_check.py run LABEL`, then `table before after`.

The change: "down" read from an object's two faces may lean at most 60 degrees from the picture's vertical,
either way (a pit's inner wall shows above its rim). A tall block seen from its corner gave a side face
95 degrees beside its top, so its "base" was its side, and the robot walking past was a contact.

| looks | n | true incidents | caught before → after | false alarms before → after | missed before → after |
|---|---|---|---|---|---|
| blind suite | 18 | 12 | 12 → 12 | 0 → 0 | 0 → 0 |
| fix control (pixels) | 4 | 0 | 0 → 0 | 1 → 0 | 0 → 0 |
| layered suite | 24 | 16 | 16 → 16 | 0 → 0 | 0 → 0 |
| other | 9 | 7 | 7 → 7 | 0 → 0 | 0 → 0 |
| quick loop | 12 | 8 | 8 → 8 | 0 → 0 | 0 → 0 |
| voice | 8 | 6 | 6 → 6 | 0 → 0 | 0 → 0 |
| watcher suite | 17 | 15 | 11 → 11 | 0 → 0 | 4 → 4 |
| all | 92 | 64 | 60 → 60 | 1 → 0 | 4 → 4 |

| look | names | truth | before | after |
|---|---|---|---|---|
| voice/console-20261027-181434/fix/attempt-1/control/ledge/evidence | white robot · gray block | none | false alarm 18.11 s (base) | quiet |


82 more looks could not be measured: their twin folders or snapshots were cleaned up, or they have no ground truth; they count in neither column.
