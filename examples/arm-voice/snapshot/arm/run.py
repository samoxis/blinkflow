"""Run see -> diagnose -> SDK fix -> prove, checkpointed and resumable by stage."""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import time

from blinkflow import events, fix, models, prove as original_prove
from . import budget, diagnose, prove, twin, gate as robot_gate


def git(*args):
    return subprocess.check_output(["git",*args],cwd=twin.ROOT,text=True)


def ledger(out,extra=None):
    calls=[]
    for p in sorted(out.rglob("*models.json")):
        if p==out/"models.json": continue
        calls.extend({**c,"stage":str(p.parent.relative_to(out))} for c in json.loads(p.read_text())["calls"])
    if extra:
        calls.extend(extra.calls)
    l=models.Ledger();l.calls=calls
    doc=l.write(out/"models.json")
    doc.update(repo_spend_usd=round(budget.total(),8),budget_cap_usd=budget.CAP,
               phase3_spend_usd=round(budget.phase_total(),8),phase3_cap_usd=2.)
    (out/"models.json").write_text(json.dumps(doc,indent=1))
    return doc


def change(base):
    """Inspect every repo path, but only stage the authorized arm subtree."""
    names=git("diff",base,"--name-only").splitlines()
    names+=git("ls-files","--others","--exclude-standard").splitlines()
    if any(n not in {"arm/brain.py","arm/brain.toml"} for n in names):
        raise RuntimeError(f"Muse Code changed paths outside arm/: {names}")
    git("add","--","arm")
    return {"diff":git("diff","--cached",base),"files":git("diff","--cached",base,"--name-only").splitlines(),
            "stat":git("diff","--cached",base,"--shortstat").strip(),
            "agent_commits":git("rev-parse","HEAD").strip()!=base}


def rollback(base):
    """Restore only the checkpointed arm; refuse pre-existing dirty work at entry."""
    git("restore","--source",base,"--staged","--worktree","--","arm")
    known=set(git("ls-tree","-r","--name-only",base,"--","arm").splitlines())
    for p in (twin.ROOT/"arm").rglob("*"):
        if p.is_file() and str(p.relative_to(twin.ROOT)) not in known and "__pycache__" not in p.parts:
            p.unlink()


def run(out,until="done",attempts=3,fix_kind="clearance",wav=None,press=4.):
    if not 1<=attempts<=3: raise ValueError("at most three attempts")
    out=pathlib.Path(out).resolve()
    out.mkdir(parents=True,exist_ok=True)
    os.environ[events.ENV]=str(out/"events.jsonl")
    budget.configure(phase=3,run=out)
    robot_gate.configure()
    # Critical check: never allow the SDK to inherit BlinkFlow's Microduck target.
    if fix.TARGET != (twin.ROOT/"arm").resolve():
        raise RuntimeError(f"wrong Muse target: {fix.TARGET}")
    manifest=out/"checkpoint.json"
    if not manifest.exists():
        if git("status","--porcelain").strip():
            raise RuntimeError("commit verified work before the loop")
        base=git("rev-parse","HEAD").strip()
        (out/"brain-before").mkdir()
        for name in ("brain.py","brain.toml"):
            shutil.copy(twin.ROOT/"arm"/name,out/"brain-before"/name)
        manifest.write_text(json.dumps({"base":base,"started":time.time(),"spoken":
                            "a couple of seconds ago the arm hit the red block","fix_kind":fix_kind,
                            "phase":3,"input":"voice" if wav else "text","press_s":press if wav else None},indent=1))
    else:
        base=json.loads(manifest.read_text())["base"]
    try:
        if not (out/"before/twin/meta.json").exists():
            twin.replay(out/"before/twin",out/"brain-before")
        spoken=json.loads(manifest.read_text())["spoken"]
        if wav:
            from .voice import recorded
            if not (out/"voice/voice.json").exists():
                voice_doc=recorded(out/"before/twin/meta.json",out,pathlib.Path(wav).resolve(),press)
            else:voice_doc=json.loads((out/"voice/voice.json").read_text())
            if not voice_doc["incident"]["confirmed"]:raise RuntimeError("voice incident not confirmed")
            spoken=voice_doc["heard"]["said"]
            state=json.loads(manifest.read_text());state["spoken"]=spoken
            manifest.write_text(json.dumps(state,indent=1))
        if not (out/"before/verdict.json").exists():
            before=prove.look(out/"before/twin/meta.json",out/"before",said=spoken)
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
            try: diagnose.diagnose(evdir,l,spoken,fix_kind)
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
                if prior["passed"]:
                    return json.loads((out/"result.json").read_text())
                history.append(json.dumps(prior));continue
            if (p/"muse-code.json").exists():
                if (p/"failure.json").exists():
                    history.append((p/"failure.json").read_text());continue
                raise RuntimeError("interrupted attempt needs explicit reconciliation before reuse")
            # Checkpoint before EVERY SDK attempt, including after a stage commit.
            if git("status","--porcelain").strip(): raise RuntimeError("dirty tree before Muse Code")
            base=git("rev-parse","HEAD").strip()
            (out/f"attempt-{i}-checkpoint.json").write_text(json.dumps({"base":base}))
            editable="brain.py" if fix_kind=="logic" else "brain.toml"
            prompt=(f"Fix this fixed-base three-joint manipulator controller. Edit only {editable}; "
                    "make the smallest change justified by the diagnosis. Do not touch git. "
                    "Do not read outside this workspace. Do not change scene, speed, timing, gains or target. "
                    "Only brain.py and brain.toml can be read/edited; scene.xml can be read. All other files "
                    "and tools are blocked by the pre-tool gate. Do not list the workspace. "
                    "The arm must lift over the block, descend and reach the target. Do not run a simulator. "
                    "No delegation.\nDIAGNOSIS\n"+(evdir/"diagnosis.md").read_text()+
                    "\nCODE\n"+(evdir/"diagnosis-input.txt").read_text().split("Spoken sentence:")[0]+
                    "\nEARLIER FAILED ATTEMPTS\n"+"\n".join(history))
            l=models.Ledger()
            # The contributor model's bounded small edit is reserved very conservatively.
            reservation=budget.book(0.25,f"Muse Code attempt {i} maximum allowance")
            try:
                rec=fix.muse_code(prompt,p,base,l,f"arm {fix_kind} fix attempt {i}",model=models.MUSE_CODE)
                cost=l.calls[-1]["cost_usd"]
                if cost is None: raise RuntimeError("Muse Code cost unavailable; reservation retained")
                budget.book(cost-reservation,f"settle Muse Code attempt {i}")
                l.write(p/"models.json")
                if rec["problems"]: raise RuntimeError(str(rec["problems"]))
                robot_audit=[bad for c in rec["tool_calls"]
                             if (bad:=robot_gate.outside(c["tool"],c["args"]))]
                (p/"robot-audit.json").write_text(json.dumps({"bad_calls":robot_audit,
                        "writable":sorted(robot_gate.WRITABLE),"readable":sorted(robot_gate.READABLE)},indent=1))
                if robot_audit:raise RuntimeError(f"robot-file audit: {robot_audit}")
                changed=rec["change"]["files"]
                if changed != ["arm/"+editable]: raise RuntimeError(f"unexpected fix diff: {changed}")
                import tomllib
                old=tomllib.loads((out/"brain-before/brain.toml").read_text())
                new=tomllib.loads((twin.ROOT/"arm/brain.toml").read_text())
                if fix_kind=="logic":
                    if new!=old or new["planner"]["clearance"]!=.08:raise RuntimeError("logic fix changed configuration")
                    diff=rec["change"]["diff"].splitlines()
                    edits=[s for s in diff if s.startswith(("+","-")) and not s.startswith(("+++","---"))]
                    if len(edits)>4:raise RuntimeError("logic fix exceeds two lines")
                else:
                    value=new["planner"]["clearance"]
                    new["planner"]["clearance"]=old["planner"]["clearance"]
                    if new!=old or value<=0:raise RuntimeError("fix changed more than positive clearance")
                (p/"brain").mkdir()
                for name in ("brain.py","brain.toml"):shutil.copy(twin.ROOT/"arm"/name,p/"brain"/name)
                result=prove.prove(p,reference=before["travel_m"],said=spoken)
                if not result["passed"]: raise RuntimeError("proof or control failed")
                git("commit","-m",f"Fix arm {fix_kind} with Muse Code; prove incident and controls")
                result.update(commit=git("rev-parse","HEAD").strip(),attempt=i)
                (out/"result.json").write_text(json.dumps(result,indent=1))
                (out/"brain-after").mkdir(exist_ok=True)
                for name in ("brain.py","brain.toml"):shutil.copy(twin.ROOT/"arm"/name,out/"brain-after"/name)
                return result
            except Exception as exc:
                l.write(p/"models.json")
                rollback(base)
                history.append(str(exc))
                (p/"failure.json").write_text(json.dumps({"error":str(exc),"rollback":base},indent=1))
                if str(exc).startswith("STOP:"): raise
        result={"passed":False,"attempt":attempts,"failures":history,"status":"not fixed"}
        (out/"result.json").write_text(json.dumps(result,indent=1))
        shutil.copytree(out/"brain-before",out/"brain-after",dirs_exist_ok=True)
        return result
    finally:
        ledger(out)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",default="runs/arm-loop")
    ap.add_argument("--until",choices=("see","diagnose","done"),default="done")
    ap.add_argument("--attempts",type=int,default=3)
    ap.add_argument("--fix-kind",choices=("clearance","logic"),default="clearance")
    ap.add_argument("--wav")
    ap.add_argument("--press",type=float,default=4.)
    a=ap.parse_args()
    print(json.dumps(run(a.out,a.until,a.attempts,a.fix_kind,a.wav,a.press),indent=1))


if __name__=="__main__":main()
