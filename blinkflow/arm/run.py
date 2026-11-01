"""Run see -> diagnose -> SDK fix -> prove, checkpointed and resumable by stage."""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import time

from blinkflow import events, fix, models, prove as original_prove
from . import REL, REPO, ROBOT, STATE, budget, diagnose, prove, twin, use_target


def git(*args):
    return subprocess.check_output(["git",*args],cwd=REPO,text=True)


def ledger(out,extra=None):
    calls=[]
    for p in sorted(out.rglob("*models.json")):
        if p==out/"models.json": continue
        calls.extend({**c,"stage":str(p.parent.relative_to(out))} for c in json.loads(p.read_text())["calls"])
    if extra:
        calls.extend(extra.calls)
    l=models.Ledger();l.calls=calls
    doc=l.write(out/"models.json")
    doc.update(repo_spend_usd=round(budget.total(),8),budget_cap_usd=budget.CAP)
    (out/"models.json").write_text(json.dumps(doc,indent=1))
    return doc


def change(base):
    """Every changed repo path must be inside the robot (REL); only that is staged."""
    names=git("diff",base,"--name-only").splitlines()
    names+=git("ls-files","--others","--exclude-standard").splitlines()
    if any(not n.startswith(REL+"/") for n in names):
        raise RuntimeError(f"Muse Code changed paths outside {REL}/: {names}")
    git("add","--",REL)
    return {"diff":git("diff","--cached",base),"files":git("diff","--cached",base,"--name-only").splitlines(),
            "stat":git("diff","--cached",base,"--shortstat").strip(),
            "agent_commits":git("rev-parse","HEAD").strip()!=base}


def rollback(base):
    """Restore only the checkpointed arm; refuse pre-existing dirty work at entry."""
    git("restore","--source",base,"--staged","--worktree","--",REL)
    known=set(git("ls-tree","-r","--name-only",base,"--",REL).splitlines())
    for p in (REPO/REL).rglob("*"):
        if p.is_file() and str(p.relative_to(REPO)) not in known and "__pycache__" not in p.parts:
            p.unlink()


def run(out,until="done",attempts=3):
    if not 1<=attempts<=3: raise ValueError("at most three attempts")
    out=pathlib.Path(out).resolve()
    out.mkdir(parents=True,exist_ok=True)
    os.environ[events.ENV]=str(out/"events.jsonl")
    budget.configure()
    use_target()
    # Critical check: never allow the SDK to inherit BlinkFlow's Microduck target.
    if fix.TARGET != ROBOT:
        raise RuntimeError(f"wrong Muse target: {fix.TARGET}")
    manifest=out/"checkpoint.json"
    if not manifest.exists():
        if git("status","--porcelain").strip():
            raise RuntimeError("commit verified work before the loop")
        base=git("rev-parse","HEAD").strip()
        (out/"brain-before").mkdir()
        for name in ("brain.py","brain.toml"):
            shutil.copy(ROBOT/name,out/"brain-before"/name)
        manifest.write_text(json.dumps({"base":base,"started":time.time(),"spoken":
                            "a couple of seconds ago the arm hit the red block"},indent=1))
    else:
        base=json.loads(manifest.read_text())["base"]
    try:
        if not (out/"before/twin/meta.json").exists():
            twin.replay(out/"before/twin",out/"brain-before")
        if not (out/"before/verdict.json").exists():
            before=prove.look(out/"before/twin/meta.json",out/"before")
        else:
            before=json.loads((out/"before/verdict.json").read_text())
        truth=json.loads((out/"before/twin/truth.json").read_text())
        if not before["valid"] or not before["contact"] or truth["first_contact_s"] is None:
            raise RuntimeError("incident not measured")
        delta=abs(before["first_contact_s"]-truth["first_contact_s"])
        if delta>0.1: raise RuntimeError(f"pixel/physics timing mismatch: {delta}s")
        (out/"alignment.json").write_text(json.dumps({"pixel_s":before["first_contact_s"],
                  "physical_s":truth["first_contact_s"],"delta_s":delta,"passed":True},indent=1))
        if until=="see": return before
        evdir=out/"before/evidence"
        if not (evdir/"diagnosis.json").exists():
            l=models.Ledger()
            try: diagnose.diagnose(evdir,l)
            finally: l.write(evdir/"diagnosis-models.json")
        d=json.loads((evdir/"diagnosis.json").read_text())
        if not d["check"]["grounded"] or d["check"]["bad_refs"]:
            raise RuntimeError("saved diagnosis is ungrounded")
        if until=="diagnose": return d["check"]
        history=[]
        fix.change=change
        # Keep the reusable gate, with a narrow filesystem target, and suppress shell execution.
        original_gate=fix.gate
        def gate():
            args,env,loaded=original_gate()
            return args+["--disable-shell","--disable-request-user-input","--no-session-log"],env,loaded
        fix.gate=gate
        for i in range(1,attempts+1):
            p=out/f"attempt-{i}"
            if (p/"proof.json").exists():
                prior=json.loads((p/"proof.json").read_text())
                if prior["passed"]: return prior
                history.append(json.dumps(prior));continue
            if (p/"muse-code.json").exists():
                raise RuntimeError("interrupted attempt needs explicit reconciliation before reuse")
            # Checkpoint before EVERY SDK attempt, including after a stage commit.
            if git("status","--porcelain").strip(): raise RuntimeError("dirty tree before Muse Code")
            base=git("rev-parse","HEAD").strip()
            (out/f"attempt-{i}-checkpoint.json").write_text(json.dumps({"base":base}))
            prompt=("You are fixing the controller of a fixed-base three-joint robot arm; this workspace is its "
                    "code. In a simulator the arm hit a red block on its way to a green target. BlinkFlow filmed "
                    "it, measured it from the pixels and read the controller's own log; its diagnosis follows.\n"
                    "Make the smallest change to this workspace that removes the cause. Rules:\n"
                    "- Edit only files inside this workspace. Do not commit or otherwise touch git.\n"
                    "- Do not read anything outside this workspace.\n"
                    "- Keep the arm's behaviour otherwise the same: it must still reach the target.\n"
                    "- You cannot run the simulator. When you finish, BlinkFlow replays the same scene in a "
                    "deterministic twin and looks at the camera again. No delegation.\nDIAGNOSIS\n"+(evdir/"diagnosis.md").read_text()+
                    "\nCODE\n"+(evdir/"diagnosis-input.txt").read_text().split("Spoken sentence:")[0]+
                    "\nEARLIER FAILED ATTEMPTS\n"+"\n".join(history))
            l=models.Ledger()
            # The contributor model's bounded small edit is reserved very conservatively.
            reservation=budget.book(0.25,f"Muse Code attempt {i} maximum allowance")
            try:
                rec=fix.muse_code(prompt,p,base,l,f"arm fix attempt {i}",model=models.MUSE_CODE)
                cost=l.calls[-1]["cost_usd"]
                if cost is None: raise RuntimeError("Muse Code cost unavailable; reservation retained")
                budget.book(cost-reservation,f"settle Muse Code attempt {i}")
                l.write(p/"models.json")
                if rec["problems"]: raise RuntimeError(str(rec["problems"]))
                if not rec["change"]["files"]: raise RuntimeError("Muse Code changed nothing")
                result=prove.prove(p,reference=before["travel_m"])
                if not result["passed"]: raise RuntimeError("proof or control failed")
                git("commit","-m","Fix the arm with Muse Code; prove incident and controls")
                result.update(commit=git("rev-parse","HEAD").strip(),attempt=i)
                (out/"result.json").write_text(json.dumps(result,indent=1))
                return result
            except Exception as exc:
                l.write(p/"models.json")
                rollback(base)
                history.append(str(exc))
                (p/"failure.json").write_text(json.dumps({"error":str(exc),"rollback":base},indent=1))
                if str(exc).startswith("STOP:"): raise
        raise RuntimeError("three attempts exhausted: "+"; ".join(history))
    finally:
        ledger(out)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",default=str(STATE/"arm-loop"))
    ap.add_argument("--until",choices=("see","diagnose","done"),default="done")
    ap.add_argument("--attempts",type=int,default=3)
    a=ap.parse_args()
    print(json.dumps(run(a.out,a.until,a.attempts),indent=1))


if __name__=="__main__":main()
