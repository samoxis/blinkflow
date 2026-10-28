"""BlinkFlow fixes and proves: from a snapshot of the incident to a patch that is shown to work.

  1. the target is committed first (a dirty tree as it is), so every attempt starts from a known
     state and a failed one is undone with `git reset --hard`;
  2. see and understand: blinkflow.see and blinkflow.diagnose on the incident (or reuse --evidence);
  3. the replay of the incident's scenario in the twin, before any change, must show the incident too
     (the contact, or the fall), or there is nothing to prove;
  4. Muse Code (`muse serve`, the host's default sandboxed profile) gets diagnosis.md and makes the
     smallest change in the target. Before each tool call, BlinkFlow's gate (muse-gate/, a PreToolUse
     hook) denies it if it names a path outside the target; after the turn every tool call is audited
     the same way, and the agent must not commit;
  5. proof: the same scenario replayed with the change, SAM 3.1 on the rendered shot, incident or not.
     Still there: git reset --hard, the new evidence goes back to Muse Wonder (with the change
     in place, and said so), and Muse Code tries again with what failed. At most 3 attempts;
  6. a person decides twice: before Muse Code writes ("Fix it?", after the cause in two plain sentences)
     and after the proof ("Keep the fix?"; no = git reset --hard). --auto asks no one (suite, watcher);
  7. report.md and models.json (every model call of the whole run) in ~/blinkflow-runs/fixes/<stamp>/.

    python3 -m blinkflow.fix <snapshot .json> [--evidence DIR] [--attempts 3] [--model MODEL] [--out DIR]
                                 [--compare N] [--auto]

The target is ~/duck-target, or the copy named by BLINKFLOW_TARGET.
"""
import argparse
import asyncio
import concurrent.futures
import functools
import json
import os
import pathlib
import re
import select
import subprocess
import sys
import time

from muse_code import (ApprovalDecisionInput, MuseClient, MuseClientSpawnOptions, SendUserTurnOptions,
                       StartSessionOptions)

from . import TARGET, diagnose, events, models, prove, see

HOME = pathlib.Path.home()
RUNS = HOME / "blinkflow-runs" / "fixes"
TURN_TIMEOUT = 900
IDENTITY = ["-c", "user.name=BlinkFlow", "-c", "user.email=blinkflow@localhost"]
EDIT_WORDS = ("edit", "write", "patch", "create", "delete", "remove", "move", "rename")
PATH_KEYS = ("path", "file_path", "filePath", "paths", "file", "target", "destination", "source")
SYSTEM_DIRS = ("/usr/", "/bin/", "/lib", "/etc/", "/dev/", "/proc/", "/opt/")   # a shell command may read these
SCRATCH_DIRS = ("/tmp", "/var/tmp", "/dev/shm")                                  # ...but not name these
REPO = pathlib.Path(__file__).resolve().parent.parent
GATE_BUNDLE = REPO / "muse-gate"
GATE_PLUGIN = "blinkflow_gate"
GATE_HOME = HOME / ".local" / "share" / "blinkflow" / "muse-host"     # XDG_DATA_HOME of the muse host BlinkFlow starts
GATE_CONF = "blinkflow-gate.json"                                      # the hook's target and stream, per turn

PROMPT = """You are fixing the brain of a small two-legged walking robot; this workspace is its code. In a \
simulator the robot {incident}. BlinkFlow filmed it, measured it from the \
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
{diagnosis}

===== WORKSPACE =====
Its files (git ls-files): {files}
The file the diagnosis names, as it is now (line numbers added; read any other file you need):

{cause}"""

HISTORY = """

===== EARLIER ATTEMPTS =====
Each one was undone: the workspace is back to its original state. Do not simply repeat one.
{attempts}"""

EARLIER = """NOTE. Earlier fixes did not remove this incident. Each was replayed in the same deterministic \
scene and looked at again from the pixels; the robot still {event}.

{attempts}

The evidence above is the replay with attempt {last}'s change still in the code shown above. A cause whose \
change left the incident as it was is not the cause, or not the whole of it: look at the other parts of the \
brain that could lead to this incident, and say in ruled_out why the earlier causes were not enough."""


# ── the target's git ─────────────────────────────────────────────────────────
def git(*args, check=True):
    return subprocess.run(["git", *IDENTITY, *args], cwd=TARGET, capture_output=True, text=True,
                          check=check).stdout


def checkpoint():
    """Commit whatever the target holds now; returns the commit every attempt starts from."""
    dirty = bool(git("status", "--porcelain").strip())
    if dirty:
        git("add", "-A")
        git("commit", "-qm", "checkpoint before BlinkFlow's fix")
    base = git("rev-parse", "HEAD").strip()
    events.emit("checkpoint", commit=base, committed_now=dirty, target=str(TARGET),
                subject=git("log", "-1", "--format=%s").strip())
    return base


def undo(base, why=""):
    git("reset", "-q", "--hard", base)
    git("clean", "-qfd")
    events.emit("undo", to=base, why=why)


def change(base):
    """The agent's change against `base`, new files included."""
    git("add", "-A")
    return {"diff": git("diff", "--cached", base), "files": git("diff", "--cached", "--name-only", base).split(),
            "stat": git("diff", "--cached", "--shortstat", base).strip(),
            "agent_commits": git("rev-parse", "HEAD").strip() != base}


# ── what Muse Code may do ────────────────────────────────────────────────────
def inside(p):
    try:
        q = pathlib.Path(p).expanduser()
    except RuntimeError:                    # "~name" for a user that does not exist here: not the target
        return False
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


def expands(p):
    try:
        pathlib.Path(p).expanduser()
        return True
    except RuntimeError:
        return False


def outside_refs(command):
    """Paths in a shell command that point outside the target (system directories aside)."""
    # A path starts where a shell word can: not after "x[i]" or ")" (`distance_mm[i]/1000.0` is a division).
    refs = re.findall(r"(?<![^\s'\"=:(<>|;&,\[{`])((?:~|/)[^\s'\"|;&<>()]*)", command)
    refs = [r for r in refs if not re.match(r"~[^/]", r) or expands(r)]   # "~0.3 m" in a heredoc is no path
    refs = [r for r in refs if not re.fullmatch(r"/[\d.]+", r)]          # "d /1000.0" divides
    bad = [r for r in refs if not inside(r) and (r.startswith(SCRATCH_DIRS) or not r.startswith(SYSTEM_DIRS))
           and r not in ("/", "~")]
    # Paths the pattern above cannot see: $HOME, a "~/" inside a word, and relative paths that climb,
    # resolved against the target (the session's workspace root).
    for w in re.split(r"[\s'\"|;&<>()`]+", command):
        if re.search(r"\$\{?HOME\b|.~/", w):
            bad.append(w)
        elif "../" in w or w == "..":
            if not inside(re.sub(r"^[^/]*?[=:]", "", w)):            # "--file=../x" names "../x"
                bad.append(w)
    bad = list(dict.fromkeys(bad))
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


def outside(tool, args):
    """What one tool call names outside the target: a shell command's paths (outside_refs) and its
    workdir, or the paths in a file tool's arguments. The gate asks it before the call, audit() after."""
    if tool == "bash":
        try:
            d = json.loads(args) if isinstance(args, str) else args
            cmd, workdir = d.get("command", ""), d.get("workdir")
        except (ValueError, AttributeError):
            cmd, workdir = str(args), None
        return outside_refs(cmd) + ([workdir] if workdir and not inside(workdir) else [])
    return [p for p in arg_paths(args) if not inside(p)]


def audit(calls):
    """Every tool call of the turn, checked after the fact: file tools inside the target, shell
    commands naming no path outside it."""
    bad = []
    for c in calls:
        if refs := outside(c["tool"], c["args"]):
            bad.append(f"bash names paths outside the target: {refs}" if c["tool"] == "bash"
                       else f"{c['tool']} outside the target: {refs}")
    return bad


def gate():
    """`muse serve` arguments and environment that load BlinkFlow's gate (muse-gate/, a PreToolUse hook)
    from the host's own data home, trusted for this host only. Refuses if it is missing or stale."""
    env = {**os.environ, "XDG_DATA_HOME": str(GATE_HOME)}
    r = subprocess.run(["muse", "plugins", "inspect", GATE_PLUGIN, "--json"], env=env, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("BlinkFlow's gate is not installed: python3 -m blinkflow.gate install")
    info = json.loads(r.stdout)
    hook = "hooks/pre_tool_use.py"
    if (pathlib.Path(info["record"]["cache_path"]) / hook).read_bytes() != (GATE_BUNDLE / hook).read_bytes():
        raise RuntimeError("BlinkFlow's gate is stale: python3 -m blinkflow.gate install")
    cap = info["runtime_capabilities"][0]["candidate"]
    trust = {cap["stable_id"]: {"enabled": True, "trusted_definition_hash": cap["definition_hash"]}}
    return ["-c", "runtime_capabilities=" + json.dumps(trust)], env


async def turn(prompt, model, log, tag=""):
    gate_args, env = gate()
    (GATE_HOME / GATE_CONF).write_text(json.dumps({"repo": str(REPO), "target": str(TARGET),
                                                   "events": str(events.path() or ""), "tag": tag}))
    args = ["serve", *gate_args] + (["--model", model] if model else [])
    client = await MuseClient.spawn(MuseClientSpawnOptions(muse_bin="muse", args=args, env=env,
                                                           client_info={"name": "blinkflow", "version": "0.1.0"}))
    try:
        info = client.initialize_result
        s = await client.start_session(StartSessionOptions(workspace_root=str(TARGET),
                                                           approval_mode="promptUnmatched"))
        s.on_approval(lambda req: decide(req, log))
        t = await s.send_user_turn(SendUserTurnOptions(input=[{"type": "text", "text": prompt}],
                                                       composer_input=prompt))
        items, told = {}, {}
        async for it in t.items():
            items[it["itemId"]] = dict(it)          # the last revision of each item wins
            if it.get("kind") == "toolCall" and told.get(it["itemId"]) != it.get("status"):
                told[it["itemId"]] = it.get("status")
                events.emit("musecode.tool", tag=tag, id=it["itemId"], tool=it.get("tool"),
                            args=str(it.get("args"))[:400], status=it.get("status"))
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
    events.emit("musecode.start", tag=out.name, model=model or "the host's default", prompt_chars=len(prompt))
    try:
        r = asyncio.run(asyncio.wait_for(turn(prompt, model, log, out.name), TURN_TIMEOUT))
    except Exception as e:                                      # the host died, timed out, refused...
        r = {"items": [], "outcome": f"error: {type(e).__name__}: {e}", "params": {}, "usage": {}}
    seconds = time.time() - t
    calls = [{"tool": i.get("tool"), "args": i.get("args"), "status": i.get("status")}
             for i in r["items"] if i.get("kind") == "toolCall"]
    final = [i.get("text", "") for i in r["items"] if i.get("kind") == "agentMessage"
             and i.get("messagePhase") == "finalAnswer"]
    u = r["usage"]
    cum = u.get("cumulative") or {}
    mid = u.get("modelId", model or "muse code default")
    cost, note = (cum.get("cost") or {}).get("usd"), "estimate reported by the Muse Code host"
    if cost is None and mid in models.PRICES and cum.get("promptTokens") is not None:   # host 1.4.14 reports none
        pin, pcached, pout = models.PRICES[mid]
        cached = cum.get("cacheReadTokens") or 0
        cost = ((cum["promptTokens"] - cached) * pin + cached * pcached + (cum.get("outputTokens") or 0) * pout) / 1e6
        note = "from the host's token counts and the model catalog's prices"
    ledger.add(mid, "Muse Code (muse serve, sandboxed) -> Meta Model API",
               purpose, seconds, cost, input_tokens=cum.get("promptTokens"),
               cached_input_tokens=cum.get("cacheReadTokens"), output_tokens=cum.get("outputTokens"),
               cost_note=note)
    ch = change(base)
    problems = audit(calls)
    if ch["agent_commits"]:
        problems.append("the agent made a commit")
    if not ch["diff"].strip():
        problems.append("no change")
    if r["outcome"] != "completed":
        problems.append(f"turn ended {r['outcome']}")
    rec = {"seconds": round(seconds, 1), "outcome": r["outcome"], "session": r["params"].get("sessionId"),
           "host": r.get("host"), "sandbox": r.get("sandbox"), "approval_mode": "promptUnmatched", "target": str(TARGET),
           "approvals": log, "tool_calls": calls, "summary": "\n".join(final).strip(), "usage": u,
           "change": ch, "problems": problems}
    (out / "muse-code.json").write_text(json.dumps(rec, indent=1))
    (out / "change.diff").write_text(ch["diff"])
    events.emit("change", tag=out.name, diff=ch["diff"], files=ch["files"], stat=ch["stat"], summary=rec["summary"],
                problems=problems, seconds=rec["seconds"], tool_calls=len(calls), sandbox=r.get("sandbox"))
    return rec


# ── the loop ─────────────────────────────────────────────────────────────────
INCIDENT = {"contact": "touched an object it should have kept clear of",
            "fall": "fell off a hazard in the floor (an edge, a pit, a step) it should have kept clear of"}


def event(kind, obj):
    return f"fell off the {obj}" if kind == "fall" else f"touched the {obj}"


def diagnosis_text(evdir):
    """diagnosis.md without its image links (Muse Code gets text)."""
    md = (pathlib.Path(evdir) / "diagnosis.md").read_text()
    return re.sub(r"^!\[[^\]]*\]\([^)]*\)\n?", "", md, flags=re.M).strip()


def workspace_text(evdir):
    """The target's file list and the file the diagnosis names, numbered: Muse Code starts editing
    instead of spending its first turns listing and reading the workspace."""
    files = git("ls-files").split()
    cause = json.loads((pathlib.Path(evdir) / "diagnosis.json").read_text())["cause"]["file"]
    shown = {cause: (TARGET / cause).read_text()} if cause in files else {}
    return {"files": ", ".join(files), "cause": diagnose.code_text(shown) or "(not a file of this workspace)"}


def says(v, obj, kind="contact"):
    if not v["valid"]:
        return "no verdict (" + "; ".join(v["problems"]) + ")"
    if v["incident"] and kind == "fall":
        return (f"the robot still fell off the {obj}, at t = {v['incident_s']:.3f} s after the brain starts "
                f"({v['fall_reading']} reading)")
    if v["incident"]:
        return (f"the robot still touched the {obj}, first contact at t = {v['first_contact_s']:.3f} s after the brain "
                f"starts ({v['reading']} reading)")
    gap = "" if v["closest_gap_px"] is None else f"closest gap {v['closest_gap_px']:.0f} px at t = {v['closest_s']:.2f} s"
    return f"no fall; the robot stayed on its feet{'; ' + gap if gap else ''}" if kind == "fall" else f"no contact; {gap}"


def effect(v, before):
    """What a failed change did to the incident, against the replay without it (same scene, same clock)."""
    if not (v["valid"] and v["incident"]):
        return ""
    d = v["incident_s"] - before["incident_s"]
    if abs(d) < 0.1:
        return (f"; before any change it was at t = {before['incident_s']:.3f} s, so this change did not "
                f"move the incident at all")
    return f", {abs(d):.2f} s {'later' if d > 0 else 'earlier'} than before any change"


def two_sentences(text):
    return " ".join(re.split(r"(?<=[.!?])\s+", text.strip())[:2])


def terminal():
    """The terminal, kept for the person's answers; fd 0 becomes /dev/null, so no child process takes what
    the person types (ffmpeg reads its stdin for commands, and the replay renders while a question waits)."""
    tty = os.fdopen(os.dup(0), "r")
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.close(null)
    return tty


def terminal_ask(question, tty, **context):
    """y or n from the person at the terminal, or the same answer from the console (blinkflow.console),
    whichever comes first; anything else asks again. `context` goes to the console with the question."""
    qid, t = f"q{time.time_ns()}", time.time()
    events.emit("ask", id=qid, question=question, **context)
    print(f"{question} [y/n] ", end="", flush=True)
    while True:
        if select.select([tty], [], [], 0.25)[0]:
            a = tty.readline()
            if not a:
                raise EOFError("the terminal closed before an answer")
            if a.strip().lower() in ("y", "yes", "n", "no"):
                yes, by = a.strip().lower()[0] == "y", "terminal"
                break
            print(f"{question} [y/n] ", end="", flush=True)
        elif (yes := events.answer(qid)) is not None:
            by = "console"
            print(f"{'y' if yes else 'n'} (answered in the console)", flush=True)
            break
    events.emit("answer", id=qid, question=question, yes=yes, by=by, seconds=round(time.time() - t, 1))
    return yes


def stage(stages, name, t, t0):
    stages.append({"stage": name, "start": round(t - t0, 1), "seconds": round(time.time() - t, 1)})
    events.emit("stage", **stages[-1])


def timed(stages, name, t0, fn, *args, **kw):
    """fn(*args, **kw), its wall time kept as a stage (stages may overlap: some run in the background)."""
    t = time.time()
    events.emit("stage.start", stage=name, start=round(t - t0, 1))
    try:
        return fn(*args, **kw)
    finally:
        stage(stages, name, t, t0)


def fix(snapshot, evidence=None, attempts=3, model=None, out=None, compare=0, ask=None, control=None):
    """`ask`: question -> True/False, the person's answer (terminal_ask); None runs with no one asked.
    `control`: after a fix is verified, replay the brain in every other scene and look for an incident
    there from pixels, before the person decides to keep it (default: when a person is asked)."""
    snapshot = pathlib.Path(snapshot).expanduser().resolve()
    model = model or models.MUSE_CODE
    run = pathlib.Path(out).expanduser() if out else RUNS / time.strftime("%Y%m%d-%H%M%S")
    run.mkdir(parents=True)
    t0 = time.time()
    control = bool(ask) if control is None else control
    events.begin(run, "fix", snapshot=str(snapshot), target=str(TARGET))
    events.emit("loop.start", run=str(run), snapshot=str(snapshot), target=str(TARGET), asked=bool(ask),
                control=control, attempts=attempts)
    seen = events.clock() or events.clock_start(t0, "the loop starts on the snapshot")
    stages, ledger = [], models.Ledger()
    base = checkpoint()
    evdir = pathlib.Path(evidence).expanduser().resolve() if evidence else run / "incident"
    diagnosed = (evdir / "diagnosis.json").exists()

    # Started at once, none of them needs the incident's names: Glimmer loaded into VRAM, the
    # diagnosis's fixed head (instructions + code) read into Muse Wonder's prompt cache, and the
    # replay before any change rendered in the twin, at low priority: on the same cores, seeing the
    # incident comes first (its own work took 9.9 s instead of 4.2 s beside a full-speed render).
    pool = concurrent.futures.ThreadPoolExecutor(4)
    def warm():
        models.warm_glimmer()
        try:
            events.emit("glimmer.vram", **(models.glimmer_vram() or {}))
        except OSError as e:                    # only the console's line about the PC goes without it
            print(f"Glimmer's VRAM not read: {e}", flush=True)
    pool.submit(timed, stages, "Glimmer loaded and kept warm (background)", t0, warm)
    cache = None if diagnosed else pool.submit(timed, stages, "Muse Wonder's prompt cache: instructions + code "
                                               "(background)", t0, diagnose.warm, ledger)
    rendered = pool.submit(timed, stages, "replay before any change: twin render (background)", t0,
                           prove.render, snapshot, run / "before", nice=10)

    if not evidence:
        timed(stages, "see the incident (Glimmer names, SAM 3.1 masks)", t0, see.see, snapshot, evdir)
    ev = json.loads((evdir / "evidence.json").read_text())
    names = (ev["names"]["robot"], ev["names"]["object"])
    obj, kind = names[1], ev.get("incident", "contact")
    # The replay's SAM 3.1 runs beside the diagnosis.
    def look_before():
        meta, seconds = rendered.result()
        try:
            return timed(stages, "replay before any change: SAM 3.1 + verdict (background)", t0, prove.look, meta,
                         run / "before", names, kind=kind, replay_s=seconds)
        finally:
            looked_at.append(time.time())
    looked_at = []
    looked = pool.submit(look_before)
    if not diagnosed:
        try:
            cache.result()
        except Exception as e:                  # a cold cache is slower and dearer, not wrong
            print(f"prompt cache not warmed: {e}", flush=True)
        # compare: N runs each of Wonder and Spark, Wonder's majority kept
        timed(stages, "understand (Glimmer key frames, Muse Wonder)", t0, diagnose.diagnose, evdir, compare=compare)
    first_diag = json.loads((evdir / "diagnosis.json").read_text())
    answers = []

    def approve(i, diag_dir):
        """Before Muse Code writes: the cause in two plain sentences, and the person's yes or no."""
        if not ask:
            return True
        d = json.loads((diag_dir / "diagnosis.json").read_text())
        c = d["cause"]
        print(f"\nCause: {two_sentences(d['explanation'])}\n({c['file']}, lines {c['lines']['start']}-"
              f"{c['lines']['end']}; confidence {d['confidence']:.2f})", flush=True)
        t = time.time()
        yes = ask("Fix it?", attempt=i, cause=two_sentences(d["explanation"]), file=c["file"],
                  lines=[c["lines"]["start"], c["lines"]["end"]], confidence=d["confidence"])
        stage(stages, f"attempt {i}: the person decides to fix", t, t0)
        answers.append({"attempt": i, "question": "Fix it?", "yes": yes, "seconds": round(time.time() - t, 1),
                        "asked": t, "answered": time.time()})
        return yes

    def held():
        """The person's share of the clock: the time a "Fix it?" waited for an answer while no machine work
        ran (the first one overlaps the replay before any change, which keeps the machine busy)."""
        busy = looked_at[0] if looked_at else float("inf")
        return sum(max(0.0, a["answered"] - max(a["asked"], busy if a["attempt"] == 1 else 0))
                   for a in answers if a["question"] == "Fix it?")

    # the first question while the replay before any change finishes in the background
    go = approve(1, evdir)
    before = timed(stages, "wait for the replay before any change", t0, looked.result)
    pool.shutdown(wait=False)
    done = {"run": str(run), "base": base, "kind": kind, "before": before, "attempts": [], "fixed": False,
            "kept": False, "asked": bool(ask), "answers": answers, "seen_s": round(t0 - seen, 1)}
    if not go:
        done["stopped"] = "the person said no before Muse Code wrote anything"
        return finish(run, snapshot, evdir, ev, first_diag, done, stages, ledger, t0)
    if not (before["valid"] and before["incident"]):
        done["stopped"] = f"the replay without a change does not show the {kind}: " + says(before, obj, kind)
        return finish(run, snapshot, evdir, ev, first_diag, done, stages, ledger, t0)

    diag_dir, history, tried = evdir, [], []
    # Whatever stops the loop midway (a model's service down, a crash), the target goes back to its
    # safety commit unless a fix was kept: nothing half-done stays in it.
    try:
        for i in range(1, attempts + 1):
            a = run / f"attempt-{i}"
            if i > 1 and not approve(i, diag_dir):
                done["stopped"] = f"the person said no before attempt {i}"
                break
            prompt = PROMPT.format(incident=INCIDENT[kind], diagnosis=diagnosis_text(diag_dir), **workspace_text(diag_dir))
            if history:
                prompt += HISTORY.format(attempts="\n\n".join(history))
            mc = timed(stages, f"attempt {i}: Muse Code edits the target", t0, muse_code, prompt, a, base, ledger,
                       f"fix attempt {i}", model)
            rec = {"attempt": i, "diagnosis": str(diag_dir / "diagnosis.md"),
                   "cause_key": json.loads((diag_dir / "diagnosis.json").read_text())["cause_key"],
                   "muse_code": {k: mc[k] for k in ("seconds", "outcome", "summary", "problems", "session")},
                   "change": mc["change"], "verdict": None, "kept": False}
            done["attempts"].append(rec)
            cause = json.loads((diag_dir / "diagnosis.json").read_text())["cause"]
            if mc["problems"]:
                undo(base, "the change was rejected before any replay")
                history.append(f"Attempt {i} was rejected before any replay: {'; '.join(mc['problems'])}.")
                tried.append(f"Attempt {i}: the diagnosis named `{rec['cause_key']}` ({cause['what']}) The change was "
                             f"rejected before any replay ({'; '.join(mc['problems'])}), so that idea is untested.")
                continue
            t = time.time()
            try:
                v = prove.prove(snapshot, a, names, before["travel_m"], kind=kind)
            except subprocess.CalledProcessError as e:              # the patched brain did not run
                v = {"valid": False, "incident": None, "contact": None, "problems": [f"the replay failed: {e}"]}
            stage(stages, f"attempt {i}: replay and look again", t, t0)
            rec["verdict"] = v
            if v["valid"] and not v["incident"]:
                done["fixed"] = True
                # the machine's time only: the seconds the loop sat waiting for the person are shown apart
                done["person_s"] = round(held(), 1)
                done["verified_s"] = round(time.time() - seen - held(), 1)
                events.emit("clock.stop", at=time.time(), seconds=done["verified_s"], wall_s=round(time.time() - seen, 1),
                            person_s=done["person_s"], why="fixed and verified", attempt=i)
                if control:
                    done["control"] = timed(stages, f"attempt {i}: control, every other scene (pixels)", t0,
                                            prove.control, a / "control")
                if ask:
                    print(f"\nReplay with the change: {says(v, obj, kind)}.\nBefore it: {says(before, obj, kind)}.\n"
                          f"Change: {mc['change']['stat']} ({', '.join(mc['change']['files'])})", flush=True)
                    if control:
                        print("Control: " + "; ".join(f"{s} {'clean' if c['clean'] else 'NOT clean: ' + c['why']}"
                                                      for s, c in done["control"].items()), flush=True)
                    t = time.time()
                    keep = ask("Keep the fix?", attempt=i, after=says(v, obj, kind), before=says(before, obj, kind),
                               stat=mc["change"]["stat"], files=mc["change"]["files"])
                    stage(stages, f"attempt {i}: the person decides to keep", t, t0)
                    answers.append({"attempt": i, "question": "Keep the fix?", "yes": keep,
                                    "seconds": round(time.time() - t, 1), "asked": t, "answered": time.time()})
                    if not keep:
                        undo(base, "the person did not keep the fix")
                        rec["rolled_back"] = True
                        done["stopped"] = "fixed and verified, but the person did not keep it: rolled back to the base commit"
                        break
                git("commit", "-qm", f"fix: {rec['cause_key']}\n\n{mc['summary']}\n\nVerified by BlinkFlow replay: "
                    f"{says(v, obj, kind)}.")
                rec["kept"] = done["kept"] = True
                done["fix_commit"] = git("rev-parse", "HEAD").strip()
                events.emit("commit", commit=done["fix_commit"], base=base, subject=f"fix: {rec['cause_key']}")
                break
            what = f"Attempt {i} changed:\n```diff\n{mc['change']['diff']}```\nIts note: {mc['summary']}\n" \
                   f"Replay of the same scene with this change: {says(v, obj, kind)}{effect(v, before)}."
            tried.append(f"Attempt {i}: the diagnosis named `{rec['cause_key']}` ({cause['what']}) The change:\n"
                         f"```diff\n{mc['change']['diff']}```\nReplay of the same scene with it: {says(v, obj, kind)}"
                         f"{effect(v, before)}.")
            if i < attempts and v["valid"]:
                # Back to Muse Wonder with the new evidence, the change still in place so code and pixels agree,
                # and with every earlier cause and what its change did, so it can look elsewhere.
                t = time.time()
                context = EARLIER.format(event=event(kind, obj), attempts="\n\n".join(tried), last=i)
                try:
                    diagnose.diagnose(a / "evidence", context=context, tag=a.name)
                    diag_dir = a / "evidence"
                    what += " A new diagnosis of that replay, made with the change in place, is the DIAGNOSIS above."
                except (SystemExit, RuntimeError) as e:
                    what += f" (no new diagnosis: {e})"
                stage(stages, f"attempt {i}: understand the replay (Glimmer, Muse Wonder)", t, t0)
            undo(base, f"attempt {i} did not remove the incident")
            history.append(what)
    except BaseException as e:
        if not done["kept"]:
            undo(base, f"the loop stopped: {type(e).__name__}: {e}"[:300])
        raise
    return finish(run, snapshot, evdir, ev, first_diag, done, stages, ledger, t0)


# ── report ───────────────────────────────────────────────────────────────────
def all_calls(run, evdir, ledger):
    """Every model call of the run, from each evidence folder's models.json and Muse Code's."""
    calls = []
    for role, d in [("incident", evdir), ("before", run / "before" / "evidence")] + \
            [(p.name, p / "evidence") for p in sorted(run.glob("attempt-*"))] + \
            [(f"{p.parent.parent.parent.name} control {p.parent.name}", p) for p in sorted(run.glob("attempt-*/control/*/evidence"))]:
        f = d / "models.json"
        if f.exists():
            calls += [{**c, "stage": role} for c in json.loads(f.read_text())["calls"]]
    calls += [{**c, "stage": c["purpose"].replace("fix attempt ", "attempt-") if c["purpose"].startswith("fix")
               else "incident"} for c in ledger.calls]
    return calls


def finish(run, snapshot, evdir, ev, diag, done, stages, ledger, t0):
    done["seconds"] = round(time.time() - t0, 1)
    done["stages"] = stages
    full = models.Ledger()
    full.calls = all_calls(run, evdir, ledger)
    mdoc = full.write(run / "models.json")
    (run / "fix.json").write_text(json.dumps(done, indent=1))
    write_report(run, snapshot, evdir, ev, diag, done, mdoc)
    events.emit("done", fixed=done["fixed"], kept=done["kept"], stopped=done.get("stopped"),
                seconds=done["seconds"], verified_s=done.get("verified_s"), person_s=done.get("person_s"),
                seen_s=done.get("seen_s"),
                attempts=len(done["attempts"]), base=done["base"], fix_commit=done.get("fix_commit"),
                report=str(run / "report.md"), cost_usd=mdoc["total_cost_usd"],
                models=manifest(mdoc["calls"]))
    return done


def manifest(calls):
    """Per model and where it ran (a cached SAM reply is a row of its own): calls, tokens, cost (the console's table)."""
    out = {}
    for c in calls:
        m = out.setdefault((c["model"], c["where"]), {"model": c["model"], "where": c["where"], "calls": 0, "input_tokens": 0,
                                        "output_tokens": 0, "frames": 0, "cost_usd": 0.0, "seconds": 0.0})
        m["calls"] += 1
        m["seconds"] = round(m["seconds"] + (c.get("seconds") or 0), 1)
        for k in ("input_tokens", "output_tokens", "frames"):
            m[k] += c.get(k) or 0
        m["cost_usd"] = round(m["cost_usd"] + (c.get("cost_usd") or 0), 5)
    return list(out.values())


def rel(run, p):
    p = pathlib.Path(p)
    try:
        return str(p.relative_to(run))
    except ValueError:
        return str(p)


def write_report(run, snapshot, evdir, ev, diag, done, mdoc):
    names, obj = ev["names"], ev["names"]["object"]
    kind = done.get("kind", "contact")
    c, b = ev["first_contact"], done["before"]
    kept = next((a for a in done["attempts"] if a["kept"]), None)
    n = len(done["attempts"])
    rolled = next((a for a in done["attempts"] if a.get("rolled_back")), None)
    if rolled:
        head = (f"**Fixed and verified in attempt {rolled['attempt']} of {n}, then rolled back**: the person did not "
                f"keep it ({done['seconds']:.0f} s).")
    elif kept:
        head = (f"**Fixed and verified in attempt {kept['attempt']} of {n}.** Seen -> fixed and verified: "
                f"**{done.get('verified_s', done['seconds']):.0f} s** of machine time"
                + (f" (the person took {done.get('person_s', 0):.1f} s to answer \"Fix it?\", not counted; "
                   f"{done['seconds']:.0f} s in all with the control and the answers)." if done.get("asked")
                   or done.get("control") else "."))
    else:
        head = f"**Not fixed** after {n} attempt(s), {done['seconds']:.0f} s. " + done.get("stopped", "")
    if kind == "fall":
        f, other = ev["fall"]["first"], ev["fall"]["brain_log" if ev["fall"]["first"]["reading"] == "pixels" else "pixels"]
        seen = (f"robot = *{names['robot']}*, {names.get('object_is', 'object')} = *{obj}*. The robot fell off it "
                f"({f['reading']} reading: {f['how']}) at frame {f['frame']}, t = {f['brain_s']:.3f} s after the brain starts"
                + (f"; the {other['reading']} reading has it at t = {other['brain_s']:.3f} s" if other else "") + ".")
    else:
        seen = (f"robot = *{names['robot']}*, object = *{obj}*. First contact ({c['reading']} reading) at frame "
                f"{c['frame']}, t = {c['brain_s']:.3f} s after the brain starts"
                + (f", {c['wall_time']}" if c.get("wall_time") else "") + ".")
    out = [f"# BlinkFlow: {names['robot']} {'falls off' if kind == 'fall' else 'touches'} the {obj}", "", head, "",
           "## What was seen", "",
           f"Snapshot `{snapshot}` ({ev['kind']} run, {ev['clock']} clock). Named by {names['named_by']}: " + seen, "",
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
            f"and {obj}. "
            + ("Fall = the robot's mask drops by 0.6 of its own height while its long axis turns 35 degrees, within "
               "half a second, or the mask vanishes for good mid-frame (pixels); or the brain's own log reports a "
               "fall (brain log). The twin's record of falls is not read." if kind == "fall" else
               "Contact = masks touching with the robot's feet at the object's base (the base reading), or, "
               "when the feet never get there, with the robot within reach of the base (body reading: another part "
               "of it, such as its head)."), "",
            "| replay | fell | fall (s) | seen in | closest gap (px) | walked (m) |" if kind == "fall" else
            "| replay | contact | first contact (s) | masks touch on screen (s) | closest gap (px) | walked (m) |",
            "|---|---|---|---|---|---|"]

    def row(label, v):
        if not v or v.get("incident") is None:
            return f"| {label} | no verdict: {'; '.join((v or {}).get('problems', []))} | | | | |"
        fmt = lambda x, f: "-" if x is None else format(x, f)
        cols = ((fmt(v["incident_s"], ".3f"), v["fall_reading"] or "-") if kind == "fall" else
                (fmt(v["first_contact_s"], ".3f"), fmt(v["whole_mask_touch_s"], ".3f")))
        return (f"| {label} | {'**yes**' if v['incident'] else '**no**'}{'' if v['valid'] else ' (invalid: ' + '; '.join(v['problems']) + ')'} "
                f"| {cols[0]} | {cols[1]} | {fmt(v['closest_gap_px'], '.0f')} | {v['travel_m']:.2f} |")

    out.append(row("before (base commit)", b))
    for a in done["attempts"]:
        out.append(row(f"attempt {a['attempt']}" + (" (kept)" if a["kept"] else " (undone)"), a["verdict"]))
    out += [""]
    out += [f"![before]({rel(run, b['evidence'] + '/evidence.png')})", ""] if b.get("evidence") else []
    if kept:
        out += [f"![after]({rel(run, kept['verdict']['evidence'] + '/evidence.png')})", ""]
    if done.get("control"):
        out += ["## Control: the same brain in every other scene", "",
                "Replayed in the twin, each scene's shot followed by SAM 3.1 (every 3rd frame) with the names "
                "Glimmer gave it; clean = no contact and no fall, from pixels only.", "",
                "| scene | named | clean | why |", "|---|---|---|---|"]
        out += [f"| {s} | {c.get('names') and ' / '.join(c['names'])} | {'yes' if c['clean'] else '**no**'} | "
                f"{c['why']} |" for s, c in done["control"].items()]
        out += [""]
    out += ["## Attempts", ""]
    for a in done["attempts"]:
        v = a["verdict"]
        out += [f"### Attempt {a['attempt']}: {'kept' if a['kept'] else 'rolled back (the person said no)' if a.get('rolled_back') else 'undone (git reset --hard)'}", "",
                f"- diagnosis used: `{rel(run, a['diagnosis'])}` (cause `{a['cause_key']}`)",
                f"- Muse Code: {a['muse_code']['outcome']}, {a['muse_code']['seconds']:.0f} s, "
                f"{a['change']['stat'] or 'no change'}; files: {', '.join(a['change']['files']) or 'none'}",
                f"- its note: {a['muse_code']['summary'] or '(none)'}",
                f"- rejected before replay: {'; '.join(a['muse_code']['problems'])}" if a["muse_code"]["problems"]
                else f"- replay: {says(v, obj, kind) if v else 'not run'}", ""]
        if not a["kept"] and a["change"]["diff"].strip():
            out += ["```diff", a["change"]["diff"].rstrip(), "```", ""]
    out += ["## Time", "", "Stages marked background run beside the others, so the column does not add up to the "
            "total.", "", "| stage | from (s) | s |", "|---|---|---|"]
    out += [f"| {s['stage']} | {s['start']:.0f} | {s['seconds']:.0f} |"
            for s in sorted(done["stages"], key=lambda s: s["start"])]
    out += [f"| **total** | 0 | **{done['seconds']:.0f}** |", ""]
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
            "- the person decided: " + ("; ".join(f"{x['question']} {'yes' if x['yes'] else 'no'} (attempt "
                                                  f"{x['attempt']}, {x['seconds']:.0f} s)" for x in done["answers"])
                                        or "nothing was asked") if done.get("asked") else
            "- run with --auto: no one was asked before Muse Code wrote or before the fix was kept.",
            "- Muse Code ran under the host's default sandboxed profile (not `:unrestricted`), approval mode "
            "`promptUnmatched`; edits are approved only when every path is inside the target.",
            f"- approval requests that reached BlinkFlow: "
            f"{sum(len(json.loads((run / f'attempt-{a['attempt']}' / 'muse-code.json').read_text())['approvals']) for a in done['attempts'])}"
            " (in-workspace reads and edits are allowed by the host's own rules and never ask).",
            "- every tool call was audited after each turn (file paths, paths named in shell commands); "
            "an attempt with a call outside the target, a commit of its own, or no change is undone unreplayed.",
            "- the simulator's contact log and the twin's record of falls are not read by BlinkFlow; the scorers "
            "(tools/live_check.py, tools/bug_suite.py) do that.", ""]
    (run / "report.md").write_text("\n".join(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot", help="the incident's snapshot (.json from blinkflow.sim, or a twin meta.json)")
    ap.add_argument("--evidence", help="reuse this evidence dir (and its diagnosis) instead of seeing again")
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--model", default=models.MUSE_CODE,
                    help=f"Muse Code's model (default: BLINKFLOW_MUSE_MODEL or {models.MUSE_CODE})")
    ap.add_argument("--out", help=f"run folder (default: {RUNS}/<stamp>)")
    ap.add_argument("--auto", action="store_true", help="ask no one: fix and keep on the proof alone (suite, watcher)")
    ap.add_argument("--control", action=argparse.BooleanOptionalAction, default=None,
                    help="after a verified fix, look for an incident in every other scene (default: when asking)")
    ap.add_argument("--compare", type=int, default=0, metavar="N",
                    help="first diagnosis: N runs each of Muse Wonder and Muse Spark (Wonder's majority is used)")
    a = ap.parse_args()
    if not (a.auto or sys.stdin.isatty()):
        raise SystemExit("no one at a terminal to ask: run with --auto")
    ask = None if a.auto else functools.partial(terminal_ask, tty=terminal())
    done = fix(a.snapshot, a.evidence, a.attempts, a.model, a.out, a.compare, ask, a.control)
    print(json.dumps({"run": done["run"], "fixed": done["fixed"], "kept": done["kept"], "seconds": done["seconds"],
                      "attempts": [{"attempt": x["attempt"], "files": x["change"]["files"],
                                    "incident": (x["verdict"] or {}).get("incident"), "kept": x["kept"]}
                                   for x in done["attempts"]]}, indent=1))


if __name__ == "__main__":
    main()
