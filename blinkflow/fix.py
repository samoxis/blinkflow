"""BlinkFlow fixes and proves: from a snapshot of the incident to a patch that is shown to work.

  1. the target is committed first (a dirty tree as it is), so every attempt starts from a known
     state and a failed one is undone with `git reset --hard`;
  2. see and understand: blinkflow.see and blinkflow.diagnose on the incident (or reuse --evidence);
  3. the replay of the incident's scenario in the twin, before any change, must show the contact too,
     or there is nothing to prove;
  4. Muse Code (`muse serve`, the host's default sandboxed profile) gets diagnosis.md and makes the
     smallest change in the target. Only edits whose every path is inside the target are approved;
     after the turn every tool call is audited the same way, and the agent must not commit;
  5. proof: the same scenario replayed with the change, SAM 3.1 on the rendered shot, contact or not.
     Still a contact: git reset --hard, the new evidence goes back to Muse Wonder (with the change
     in place, and said so), and Muse Code tries again with what failed. At most 3 attempts;
  6. report.md and models.json (every model call of the whole run) in ~/blinkflow-runs/fixes/<stamp>/.

    python3 -m blinkflow.fix <snapshot .json> [--evidence DIR] [--attempts 3] [--model MODEL]
"""
import argparse
import asyncio
import json
import pathlib
import re
import subprocess
import time

from muse_code import (ApprovalDecisionInput, MuseClient, MuseClientSpawnOptions, SendUserTurnOptions,
                       StartSessionOptions)

from . import diagnose, models, prove, see

HOME = pathlib.Path.home()
TARGET = (HOME / "duck-target").resolve()
RUNS = HOME / "blinkflow-runs" / "fixes"
TURN_TIMEOUT = 900
IDENTITY = ["-c", "user.name=BlinkFlow", "-c", "user.email=blinkflow@localhost"]
EDIT_WORDS = ("edit", "write", "patch", "create", "delete", "remove", "move", "rename")
PATH_KEYS = ("path", "file_path", "filePath", "paths", "file", "target", "destination", "source")
SYSTEM_DIRS = ("/usr/", "/bin/", "/lib", "/etc/", "/dev/", "/proc/", "/tmp/", "/opt/")

PROMPT = """You are fixing the brain of a small two-legged walking robot; this workspace is its code. In a \
simulator the robot touched an object it should have kept clear of. BlinkFlow filmed it, measured it from the \
pixels and read the brain's own log; its diagnosis follows.

Make the smallest change to this workspace that removes the cause. Rules:
- Edit only files inside this workspace. Do not commit or otherwise touch git.
- Do not read anything outside this workspace.
- Keep the robot's behaviour otherwise the same: do not lower its speeds, stop it from walking, or loosen \
its safety settings.
- You cannot run the simulator. When you finish, BlinkFlow replays the same scene in a deterministic twin \
and looks at the camera again.
- Quick local checks are fine, e.g. `python3 -m py_compile <file>`, or parsing brain.toml with tomllib.
- Finish with two or three plain sentences in English: what you changed and why.

===== DIAGNOSIS =====
{diagnosis}"""

HISTORY = """

===== EARLIER ATTEMPTS =====
Each one was undone: the workspace is back to its original state. Do not simply repeat one.
{attempts}"""


# ── the target's git ─────────────────────────────────────────────────────────
def git(*args, check=True):
    return subprocess.run(["git", *IDENTITY, *args], cwd=TARGET, capture_output=True, text=True,
                          check=check).stdout


def checkpoint():
    """Commit whatever the target holds now; returns the commit every attempt starts from."""
    if git("status", "--porcelain").strip():
        git("add", "-A")
        git("commit", "-qm", "checkpoint before BlinkFlow's fix")
    return git("rev-parse", "HEAD").strip()


def undo(base):
    git("reset", "-q", "--hard", base)
    git("clean", "-qfd")


def change(base):
    """The agent's change against `base`, new files included."""
    git("add", "-A")
    return {"diff": git("diff", "--cached", base), "files": git("diff", "--cached", "--name-only", base).split(),
            "stat": git("diff", "--cached", "--shortstat", base).strip(),
            "agent_commits": git("rev-parse", "HEAD").strip() != base}


# ── what Muse Code may do ────────────────────────────────────────────────────
def inside(p):
    q = pathlib.Path(p).expanduser()
    q = (q if q.is_absolute() else TARGET / q).resolve()
    return q == TARGET or TARGET in q.parents


def arg_paths(raw):
    """File paths named in a tool call's arguments (JSON keys, or the headers of a patch)."""
    try:
        d = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        d = raw
    out = []

    def walk(x, key=None):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, k)
        elif isinstance(x, list):
            for v in x:
                walk(v, key)
        elif isinstance(x, str):
            if key in PATH_KEYS:
                out.append(x)
            out.extend(re.findall(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", x, re.M))
            out.extend(re.findall(r"^\+\+\+ b/(.+)$", x, re.M))

    walk(d)
    return out


def is_edit(tool):
    return any(w in tool.lower() for w in EDIT_WORDS)


def outside_refs(command):
    """Paths in a shell command that point outside the target (system directories aside)."""
    refs = re.findall(r"(?<![\w.])((?:~|/)[^\s'\"|;&<>()]*)", command)
    bad = [r for r in refs if not inside(r) and not r.startswith(SYSTEM_DIRS) and r not in ("/", "~")]
    if "microduck-brain" in command:
        bad.append("microduck-brain")
    return bad


def decide(req, log):
    """Approve an edit only if every path it names is inside the target; deny everything else."""
    tool = str(req.get("toolName", ""))
    paths = arg_paths(req.get("rawArgs"))
    ok = is_edit(tool) and bool(paths) and all(inside(p) for p in paths)
    choices = req.get("availableChoices") or []
    want = "approved" if ok else "denied"
    pick = (next((c for c in choices if str(c.get("decision")) == want and c.get("scope") in (None, "once")), None)
            or next((c for c in choices if str(c.get("decision")) == want), None)
            or next((c for c in choices if str(c.get("decision")) != "approved"), None))
    log.append({"tool": tool, "paths": paths, "wanted": want, "picked": pick and pick.get("choiceId"),
                "offered": [(c.get("choiceId"), c.get("decision"), c.get("scope")) for c in choices]})
    if pick is None:
        raise RuntimeError(f"no way to deny {tool}: {choices}")
    return ApprovalDecisionInput(choice_id=pick["choiceId"])


def audit(calls):
    """Every tool call of the turn, checked after the fact: file tools inside the target, shell
    commands naming no path outside it."""
    bad = []
    for c in calls:
        if c["tool"] == "bash":
            try:
                cmd = json.loads(c["args"]).get("command", "")
            except (ValueError, AttributeError):
                cmd = str(c["args"])
            if refs := outside_refs(cmd):
                bad.append(f"bash names paths outside the target: {refs}")
        else:
            out = [p for p in arg_paths(c["args"]) if not inside(p)]
            if out:
                bad.append(f"{c['tool']} outside the target: {out}")
    return bad


async def turn(prompt, model, log):
    args = ["serve"] + (["--model", model] if model else [])
    client = await MuseClient.spawn(MuseClientSpawnOptions(muse_bin="muse", args=args,
                                                           client_info={"name": "blinkflow", "version": "0.1.0"}))
    try:
        info = client.initialize_result
        s = await client.start_session(StartSessionOptions(workspace_root=str(TARGET),
                                                           approval_mode="promptUnmatched"))
        s.on_approval(lambda req: decide(req, log))
        t = await s.send_user_turn(SendUserTurnOptions(input=[{"type": "text", "text": prompt}],
                                                       composer_input=prompt))
        items = {}
        async for it in t.items():
            items[it["itemId"]] = dict(it)          # the last revision of each item wins
        outcome = await t.completed
        st = s.fold.session_state
        usage = st.get("session/tokenUsage") if st.has("session/tokenUsage") else {}
        return {"host": info["userAgent"], "sandbox": info["sandboxAvailability"], "items": list(items.values()),
                "outcome": getattr(outcome, "kind", str(outcome)), "params": getattr(outcome, "params", {}),
                "usage": dict(usage)}
    finally:
        await client.close()


def muse_code(prompt, out, base, ledger, purpose, model=None):
    """One Muse Code turn on the target. Returns what it did, its change and the audit."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "muse-code-prompt.txt").write_text(prompt)
    log, t = [], time.time()
    try:
        r = asyncio.run(asyncio.wait_for(turn(prompt, model, log), TURN_TIMEOUT))
    except Exception as e:                                      # the host died, timed out, refused...
        r = {"items": [], "outcome": f"error: {type(e).__name__}: {e}", "params": {}, "usage": {}}
    seconds = time.time() - t
    calls = [{"tool": i.get("tool"), "args": i.get("args"), "status": i.get("status")}
             for i in r["items"] if i.get("kind") == "toolCall"]
    final = [i.get("text", "") for i in r["items"] if i.get("kind") == "agentMessage"
             and i.get("messagePhase") == "finalAnswer"]
    u = r["usage"]
    cum = u.get("cumulative") or {}
    ledger.add(u.get("modelId", model or "muse code default"), "Muse Code (muse serve, sandboxed) -> Meta Model API",
               purpose, seconds, (cum.get("cost") or {}).get("usd"), input_tokens=cum.get("promptTokens"),
               cached_input_tokens=cum.get("cacheReadTokens"), output_tokens=cum.get("outputTokens"),
               cost_note="estimate reported by the Muse Code host")
    ch = change(base)
    problems = audit(calls)
    if ch["agent_commits"]:
        problems.append("the agent made a commit")
    if not ch["diff"].strip():
        problems.append("no change")
    if r["outcome"] != "completed":
        problems.append(f"turn ended {r['outcome']}")
    rec = {"seconds": round(seconds, 1), "outcome": r["outcome"], "session": r["params"].get("sessionId"),
           "host": r.get("host"), "sandbox": r.get("sandbox"), "approval_mode": "promptUnmatched",
           "approvals": log, "tool_calls": calls, "summary": "\n".join(final).strip(), "usage": u,
           "change": ch, "problems": problems}
    (out / "muse-code.json").write_text(json.dumps(rec, indent=1))
    (out / "change.diff").write_text(ch["diff"])
    return rec


# ── the loop ─────────────────────────────────────────────────────────────────
def diagnosis_text(evdir):
    """diagnosis.md without its image links (Muse Code gets text)."""
    md = (pathlib.Path(evdir) / "diagnosis.md").read_text()
    return re.sub(r"^!\[[^\]]*\]\([^)]*\)\n?", "", md, flags=re.M).strip()


def says(v, obj):
    if not v["valid"]:
        return "no verdict (" + "; ".join(v["problems"]) + ")"
    if v["contact"]:
        return (f"the robot still touched the {obj}, first contact at t = {v['first_contact_s']:.3f} s after the brain "
                f"starts ({v['reading']} reading)")
    return f"no contact; closest gap {v['closest_gap_px']:.0f} px at t = {v['closest_s']:.2f} s"


def stage(stages, name, t):
    stages.append({"stage": name, "seconds": round(time.time() - t, 1)})


def fix(snapshot, evidence=None, attempts=3, model=None):
    snapshot = pathlib.Path(snapshot).expanduser().resolve()
    run = RUNS / time.strftime("%Y%m%d-%H%M%S")
    run.mkdir(parents=True)
    t0 = time.time()
    stages, ledger = [], models.Ledger()
    base = checkpoint()

    t = time.time()
    if evidence:
        evdir = pathlib.Path(evidence).expanduser().resolve()
    else:
        evdir = run / "incident"
        see.see(snapshot, evdir)
        stage(stages, "see the incident (Glimmer names, SAM 3.1 masks)", t)
    ev = json.loads((evdir / "evidence.json").read_text())
    t = time.time()
    if not (evdir / "diagnosis.json").exists():
        diagnose.diagnose(evdir)
        stage(stages, "understand (Glimmer key frames, Muse Wonder)", t)
    first_diag = json.loads((evdir / "diagnosis.json").read_text())
    names = (ev["names"]["robot"], ev["names"]["object"])
    obj = names[1]

    t = time.time()
    before = prove.prove(snapshot, run / "before", names)
    stage(stages, "replay before any change (twin + SAM 3.1)", t)
    done = {"run": str(run), "base": base, "before": before, "attempts": [], "fixed": False}
    if not (before["valid"] and before["contact"]):
        done["stopped"] = "the replay without a change does not show the contact: " + says(before, obj)
        return finish(run, snapshot, evdir, ev, first_diag, done, stages, ledger, t0)

    diag_dir, history = evdir, []
    for i in range(1, attempts + 1):
        a = run / f"attempt-{i}"
        prompt = PROMPT.format(diagnosis=diagnosis_text(diag_dir))
        if history:
            prompt += HISTORY.format(attempts="\n\n".join(history))
        t = time.time()
        mc = muse_code(prompt, a, base, ledger, f"fix attempt {i}", model)
        stage(stages, f"attempt {i}: Muse Code edits the target", t)
        rec = {"attempt": i, "diagnosis": str(diag_dir / "diagnosis.md"),
               "cause_key": json.loads((diag_dir / "diagnosis.json").read_text())["cause_key"],
               "muse_code": {k: mc[k] for k in ("seconds", "outcome", "summary", "problems", "session")},
               "change": mc["change"], "verdict": None, "kept": False}
        done["attempts"].append(rec)
        if mc["problems"]:
            undo(base)
            history.append(f"Attempt {i} was rejected before any replay: {'; '.join(mc['problems'])}.")
            continue
        t = time.time()
        try:
            v = prove.prove(snapshot, a, names, before["travel_m"])
        except subprocess.CalledProcessError as e:              # the patched brain did not run
            v = {"valid": False, "contact": None, "problems": [f"the replay failed: {e}"]}
        stage(stages, f"attempt {i}: replay and look again", t)
        rec["verdict"] = v
        if v["valid"] and not v["contact"]:
            git("commit", "-qm", f"fix: {rec['cause_key']}\n\n{mc['summary']}\n\nVerified by BlinkFlow replay: "
                f"{says(v, obj)}.")
            rec["kept"], done["fixed"] = True, True
            done["fix_commit"] = git("rev-parse", "HEAD").strip()
            break
        what = f"Attempt {i} changed:\n```diff\n{mc['change']['diff']}```\nIts note: {mc['summary']}\n" \
               f"Replay of the same scene with this change: {says(v, obj)}."
        if i < attempts and v["valid"]:
            # Back to Muse Wonder with the new evidence, the change still in place so code and pixels agree.
            t = time.time()
            context = (f"NOTE. This replay ran with a fix already applied to the code above, and the robot still "
                       f"touched the {obj}. The fix was:\n{mc['change']['diff']}\nFind what else causes the "
                       f"contact; the cause may be in a different place than the one this fix changed.")
            try:
                diagnose.diagnose(a / "evidence", context=context)
                diag_dir = a / "evidence"
                what += " A new diagnosis of that replay, made with the change in place, is the DIAGNOSIS above."
            except (SystemExit, RuntimeError) as e:
                what += f" (no new diagnosis: {e})"
            stage(stages, f"attempt {i}: understand the replay (Glimmer, Muse Wonder)", t)
        undo(base)
        history.append(what)
    return finish(run, snapshot, evdir, ev, first_diag, done, stages, ledger, t0)


# ── report ───────────────────────────────────────────────────────────────────
def all_calls(run, evdir, ledger):
    """Every model call of the run, from each evidence folder's models.json and Muse Code's."""
    calls = []
    for role, d in [("incident", evdir), ("before", run / "before" / "evidence")] + \
            [(p.name, p / "evidence") for p in sorted(run.glob("attempt-*"))]:
        f = d / "models.json"
        if f.exists():
            calls += [{**c, "stage": role} for c in json.loads(f.read_text())["calls"]]
    calls += [{**c, "stage": c["purpose"].replace("fix attempt ", "attempt-")} for c in ledger.calls]
    return calls


def finish(run, snapshot, evdir, ev, diag, done, stages, ledger, t0):
    done["seconds"] = round(time.time() - t0, 1)
    done["stages"] = stages
    full = models.Ledger()
    full.calls = all_calls(run, evdir, ledger)
    mdoc = full.write(run / "models.json")
    (run / "fix.json").write_text(json.dumps(done, indent=1))
    write_report(run, snapshot, evdir, ev, diag, done, mdoc)
    return done


def rel(run, p):
    p = pathlib.Path(p)
    try:
        return str(p.relative_to(run))
    except ValueError:
        return str(p)


def write_report(run, snapshot, evdir, ev, diag, done, mdoc):
    names, obj = ev["names"], ev["names"]["object"]
    c, b = ev["first_contact"], done["before"]
    kept = next((a for a in done["attempts"] if a["kept"]), None)
    n = len(done["attempts"])
    if kept:
        head = (f"**Fixed and verified in attempt {kept['attempt']} of {n}.** Seen -> fixed and verified: "
                f"**{done['seconds']:.0f} s** of wall time.")
    else:
        head = f"**Not fixed** after {n} attempt(s), {done['seconds']:.0f} s. " + done.get("stopped", "")
    out = [f"# BlinkFlow: {names['robot']} touches the {obj}", "", head, "",
           "## What was seen", "",
           f"Snapshot `{snapshot}` ({ev['kind']} run, {ev['clock']} clock). Named by {names['named_by']}: "
           f"robot = *{names['robot']}*, object = *{obj}*. First contact ({c['reading']} reading) at frame "
           f"{c['frame']}, t = {c['brain_s']:.3f} s after the brain starts"
           + (f", {c['wall_time']}" if c.get("wall_time") else "") + ".", "",
           f"![incident]({rel(run, evdir / 'evidence.png')})", "",
           "## Cause (Muse Wonder)", "",
           f"`{diag['cause']['file']}`, `{diag['cause']['function']}`, lines {diag['cause']['lines']['start']}-"
           f"{diag['cause']['lines']['end']}: {diag['cause']['what']}", "",
           f"In plain words: {diag['explanation']}", "",
           f"Confidence {diag['confidence']:.2f}; grounded in key frames and log ticks: "
           f"{'yes' if diag['check']['grounded'] else 'NO'}. Full diagnosis: `{rel(run, evdir / 'diagnosis.md')}`.", ""]
    if kept:
        out += ["## The fix", "", f"Muse Code: {kept['muse_code']['summary']}", "",
                f"{kept['change']['stat']}. Committed in the target as `{done['fix_commit'][:7]}` "
                f"(base `{done['base'][:7]}`).", "", "```diff", kept["change"]["diff"].rstrip(), "```", ""]
    out += ["## Proof: the same scenario replayed in the twin, before and after", "",
            "The verdict comes from SAM 3.1 masks on the rendered incident shot, following the incident's robot "
            "and object. Contact = masks touching with the robot's feet at the object's base (the base reading).", "",
            "| replay | contact | first contact (s) | masks touch on screen (s) | closest gap (px) | walked (m) |",
            "|---|---|---|---|---|---|"]

    def row(label, v):
        if not v or v.get("contact") is None:
            return f"| {label} | no verdict: {'; '.join((v or {}).get('problems', []))} | | | | |"
        fmt = lambda x, f: "-" if x is None else format(x, f)
        return (f"| {label} | {'**yes**' if v['contact'] else '**no**'}{'' if v['valid'] else ' (invalid: ' + '; '.join(v['problems']) + ')'} "
                f"| {fmt(v['first_contact_s'], '.3f')} | {fmt(v['whole_mask_touch_s'], '.3f')} "
                f"| {fmt(v['closest_gap_px'], '.0f')} | {v['travel_m']:.2f} |")

    out.append(row("before (base commit)", b))
    for a in done["attempts"]:
        out.append(row(f"attempt {a['attempt']}" + (" (kept)" if a["kept"] else " (undone)"), a["verdict"]))
    out += [""]
    out += [f"![before]({rel(run, b['evidence'] + '/evidence.png')})", ""] if b.get("evidence") else []
    if kept:
        out += [f"![after]({rel(run, kept['verdict']['evidence'] + '/evidence.png')})", ""]
    out += ["## Attempts", ""]
    for a in done["attempts"]:
        v = a["verdict"]
        out += [f"### Attempt {a['attempt']}: {'kept' if a['kept'] else 'undone (git reset --hard)'}", "",
                f"- diagnosis used: `{rel(run, a['diagnosis'])}` (cause `{a['cause_key']}`)",
                f"- Muse Code: {a['muse_code']['outcome']}, {a['muse_code']['seconds']:.0f} s, "
                f"{a['change']['stat'] or 'no change'}; files: {', '.join(a['change']['files']) or 'none'}",
                f"- its note: {a['muse_code']['summary'] or '(none)'}",
                f"- rejected before replay: {'; '.join(a['muse_code']['problems'])}" if a["muse_code"]["problems"]
                else f"- replay: {says(v, obj) if v else 'not run'}", ""]
        if not a["kept"] and a["change"]["diff"].strip():
            out += ["```diff", a["change"]["diff"].rstrip(), "```", ""]
    out += ["## Time", "", "| stage | s |", "|---|---|"]
    out += [f"| {s['stage']} | {s['seconds']:.0f} |" for s in done["stages"]]
    out += [f"| **total** | **{done['seconds']:.0f}** |", ""]
    if evdir.parent != run:
        out += ["The incident's evidence and first diagnosis were reused from an earlier run; their time is not "
                "counted above.", ""]
    out += ["## Models", "", "| stage | model | where | purpose | input tokens (cached) | output tokens | cost $ | s |",
            "|---|---|---|---|---|---|---|---|"]
    for m in mdoc["calls"]:
        tok = m.get("input_tokens")
        out.append(f"| {m['stage']} | {m['model']} | {m['where']} | {m['purpose']} | "
                   f"{'-' if tok is None else tok}{'' if not m.get('cached_input_tokens') else ' (' + str(m['cached_input_tokens']) + ')'} | "
                   f"{m.get('output_tokens') if m.get('output_tokens') is not None else '-'} | "
                   f"{'-' if m['cost_usd'] is None else format(m['cost_usd'], '.4f')} | {m['seconds']:.0f} |")
    out += ["", f"Total ${mdoc['total_cost_usd']:.3f}. Every call is in `models.json`; Muse Code's cost is the "
            "host's own estimate.", "",
            "## Guardrails", "",
            "- Muse Code ran under the host's default sandboxed profile (not `:unrestricted`), approval mode "
            "`promptUnmatched`; edits are approved only when every path is inside the target.",
            f"- approval requests that reached BlinkFlow: "
            f"{sum(len(json.loads((run / f'attempt-{a['attempt']}' / 'muse-code.json').read_text())['approvals']) for a in done['attempts'])}"
            " (in-workspace reads and edits are allowed by the host's own rules and never ask).",
            "- every tool call was audited after each turn (file paths, paths named in shell commands); "
            "an attempt with a call outside the target, a commit of its own, or no change is undone unreplayed.",
            "- the simulator's contact log is not read by BlinkFlow; tools/live_check.py (scorer) does that.", ""]
    (run / "report.md").write_text("\n".join(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot", help="the incident's snapshot (.json from blinkflow.sim, or a twin meta.json)")
    ap.add_argument("--evidence", help="reuse this evidence dir (and its diagnosis) instead of seeing again")
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--model", help="Muse Code's model (default: the host's)")
    a = ap.parse_args()
    done = fix(a.snapshot, a.evidence, a.attempts, a.model)
    print(json.dumps({"run": done["run"], "fixed": done["fixed"], "seconds": done["seconds"],
                      "attempts": [{"attempt": x["attempt"], "files": x["change"]["files"],
                                    "contact": (x["verdict"] or {}).get("contact"), "kept": x["kept"]}
                                   for x in done["attempts"]]}, indent=1))


if __name__ == "__main__":
    main()
