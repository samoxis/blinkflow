# Muse Code alone: the person's sentence and the target, no frames, no SAM 3.1, no Muse Wonder.
# The same model, the same gate (fix.muse_code), at most 3 attempts; each change judged as BlinkFlow judges
# its own: the replay of the example's scene in the twin, then the control in every other scene, from pixels.
# Between attempts Muse Code hears only what a person watching would say: still hit it, or other scenes broke.
#   python3 tools/ablation.py OUT [--sentence "..."] [--base b2fe90a]
# The target is put on --base for the run and goes back to the commit it was on.
import argparse, json, pathlib, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from blinkflow import TARGET, events, fix, models, prove

REPO = pathlib.Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "examples/purple-box"
KEY = "side_memory_seconds"

PROMPT = """You are fixing the brain of a small two-legged walking robot; this workspace is its code. A person \
watching it in a simulator said: "{sentence}"

Make the smallest change to this workspace that removes the cause. Rules:
- Edit only files inside this workspace. Do not commit or otherwise touch git.
- Do not read anything outside this workspace.
- Keep the robot's behaviour otherwise the same: do not lower its speeds, stop it from walking, or loosen \
its safety settings.
- You cannot run the simulator. When you finish, the same scene is replayed in a deterministic twin and \
watched again.
- Quick local checks are fine, e.g. `python3 -m py_compile <file>`, or parsing brain.toml with tomllib.
- Finish with two or three plain sentences in English: what you changed and why."""


def cost_of(folder):
    """SAM 3.1 and the other models' calls under `folder` (each evidence dir writes its models.json)."""
    return sum(c.get("cost_usd") or 0 for m in pathlib.Path(folder).rglob("models.json")
               for c in json.loads(m.read_text()).get("calls", []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--sentence", default="a couple of seconds ago the robot hit the purple box")
    ap.add_argument("--base", default="b2fe90a")
    ap.add_argument("--attempts", type=int, default=3)
    a = ap.parse_args()
    run = pathlib.Path(a.out).expanduser()
    run.mkdir(parents=True)
    snapshot = (EXAMPLE / "window/snapshot.json").resolve()
    before = json.loads((EXAMPLE / "fix/before/verdict.json").read_text())   # the replay with no change: 1 contact
    ev = json.loads((EXAMPLE / "window/evidence/evidence.json").read_text())
    names = (ev["names"]["robot"], ev["names"]["object"])
    was = fix.git("symbolic-ref", "-q", "--short", "HEAD", check=False).strip() or fix.git("rev-parse", "HEAD").strip()
    if fix.git("status", "--porcelain").strip():
        sys.exit(f"{TARGET} has uncommitted changes")
    fix.git("checkout", "-q", "--detach", a.base)
    base = fix.git("rev-parse", "HEAD").strip()
    events.begin(run, "ablation", snapshot=str(snapshot), target=str(TARGET))
    ledger, history, attempts, t0 = models.Ledger(), [], [], time.time()
    found = fixed = False
    try:
        for i in range(1, a.attempts + 1):
            out = run / f"attempt-{i}"
            prompt = PROMPT.format(sentence=a.sentence)
            if history:
                prompt += fix.HISTORY.format(attempts="\n\n".join(history))
            mc = fix.muse_code(prompt, out, base, ledger, f"ablation attempt {i}", models.MUSE_CODE)
            diff = mc["change"]["diff"]
            rec = {"attempt": i, "muse_code_s": mc["seconds"], "summary": mc["summary"], "problems": mc["problems"],
                   "files": mc["change"]["files"], "stat": mc["change"]["stat"], "names_key": KEY in diff,
                   "verdict": None, "control": None}
            attempts.append(rec)
            found = found or rec["names_key"]
            if mc["problems"]:
                fix.undo(base, "rejected before any replay")
                history.append(f"Attempt {i} was rejected before any replay: {'; '.join(mc['problems'])}.")
                continue
            t = time.time()
            v = prove.prove(snapshot, out, names, before["travel_m"])
            rec["verdict"] = {k: v.get(k) for k in ("fixed", "incident", "contact", "valid", "first_contact_s",
                                                    "closest_gap_px", "closest_s", "travel_m", "problems")}
            told = f"Attempt {i} changed:\n```diff\n{diff}```\nIts note: {mc['summary']}\n"
            if v.get("fixed"):
                c = prove.control(out / "control")
                rec["control"] = {s: {"clean": x["clean"], "why": x["why"]} for s, x in c.items()}
                dirty = [s for s, x in c.items() if not x["clean"]]
                if not dirty:
                    rec["proof_s"] = round(time.time() - t, 1)
                    fixed = True
                    break
                told += (f"In the replay of the same scene the robot no longer hit the purple box, but with this "
                         f"change it failed in other scenes ({', '.join(dirty)}).")
            else:
                told += "In the replay of the same scene the robot still hit the purple box."
            rec["proof_s"] = round(time.time() - t, 1)
            history.append(told)
            fix.undo(base, f"attempt {i} did not pass")
    finally:
        final_diff = fix.change(base)["diff"]
        fix.undo(base, "the ablation is over")
        fix.git("checkout", "-q", was)                       # the branch it was on, untouched (base was detached)
        ledger.write(run / "models-muse-code.json")
    muse_cost = round(sum(c["cost_usd"] or 0 for c in ledger.calls), 5)
    summary = {"sentence": a.sentence, "base": base, "model": models.MUSE_CODE, "attempts": attempts,
               "found_key": found, "fixed_and_control_clean": fixed, "seconds": round(time.time() - t0, 1),
               "muse_code_usd": muse_cost, "proof_usd": round(cost_of(run), 5),
               "kept_diff": final_diff if fixed else None}
    (run / "ablation.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != "attempts"}, indent=1))


if __name__ == "__main__":
    main()
