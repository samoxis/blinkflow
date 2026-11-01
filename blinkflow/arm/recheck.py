"""Re-derive a public arm run with network/model access blocked and no API key: examples/arm, and the two runs
made in the arm's own repo before it moved here (examples/arm-bug2, a logic bug; examples/arm-voice, a spoken
sentence). Those were made in its flat layout, where the robot was arm/brain.py and arm/brain.toml; their
diffs and file lists name that path, read here as the robot (robot/ now), and their bytes stay as published."""
import argparse
import hashlib
import json
import math
import os
import pathlib
import shutil
import subprocess
import tempfile
import urllib.request
import wave

import requests
from blinkflow import diagnose as original_diagnose, models, sam, see
from . import REL, WORLD, prove, twin, use_target

ROBOT_FILES = ("brain.py", "brain.toml")
LAYOUTS = (REL, "arm")                # this repo's robot/, and the arm repo's flat arm/ (examples/arm-bug2, -voice)


def deny(*args,**kwargs):
    raise RuntimeError("offline recheck: network/model call forbidden")


def read(p):
    return json.loads(pathlib.Path(p).read_text())


def relative(value,parent):
    p=pathlib.Path(value).expanduser()
    return (p if p.is_absolute() else parent/p).resolve()


def robot_files(files):
    """The changed files, as long as they are the robot's own in either layout: (layout, names)."""
    for layout in LAYOUTS:
        if files and all(f.startswith(layout+"/") for f in files):
            names=[f[len(layout)+1:] for f in files]
            if layout==REL or all(n in ROBOT_FILES for n in names):
                return layout,names
    raise AssertionError(f"changed files outside the robot: {files}")


def recheck(example,physics=True):
    root=pathlib.Path(example).resolve()
    use_target()                     # the SDK audit below judges paths against this arm
    os.environ.pop("MODEL_API_KEY",None)
    os.environ.pop("BASETEN_API_KEY",None)
    models.api_key=deny
    requests.sessions.Session.request=deny
    urllib.request.urlopen=deny
    manifest=root/"sha256.json"
    if manifest.exists():
        for rel,expected in read(manifest).items():
            assert hashlib.sha256((root/rel).read_bytes()).hexdigest()==expected,rel
    result=read(root/"result.json")
    checkpoint=read(root/"checkpoint.json")
    before=read(root/"before/verdict.json")
    attempts=sorted(p for p in root.glob("attempt-*") if p.is_dir())
    groups=[root/"before"]
    for p in attempts:
        if (p/"verdict.json").exists():
            groups.append(p)
            groups.extend(sorted((p/"control").glob("*")))
    rederived,checks,physical={},{},{}
    with tempfile.TemporaryDirectory(prefix="arm-recheck-") as tmp:
        tmp=pathlib.Path(tmp)
        for src in groups:
            name=str(src.relative_to(root))
            out=tmp/name
            out.mkdir(parents=True)
            shutil.copytree(src/"evidence",out/"evidence")
            old=read(src/"verdict.json")
            meta_path=relative(old.get("meta","./twin/meta.json"),src)   # the voice run's before is its window
            meta=read(meta_path)
            snap=see.load_snapshot(meta_path)
            meta.update(video=snap["clip"],record=snap["record"])
            m=out/"meta.json";m.write_text(json.dumps(meta))
            saved=read(src/"evidence/evidence.json")
            control="control" in src.relative_to(root).parts
            v=prove.look(m,out,reference=None if name=="before" else before["travel_m"],
                         reuse=True,control=control,said=saved["names"].get("said"))
            ev=read(out/"evidence/evidence.json")
            for k in ("gap_by_frame","contacts","tracking","closest"):
                assert ev[k]==saved[k],(name,k)
            for k in ("valid","contact","fixed","first_contact_s","closest_gap_px",
                      "target_error_m","target_reached","full_tracking"):
                assert v[k]==old[k],(name,k,v[k],old[k])
            if control: assert v["clean"]==old["clean"]
            rederived[name]={k:v[k] for k in ("valid","contact","first_contact_s","target_error_m")}
        evdir=root/"before/evidence"
        d=read(evdir/"diagnosis.json")
        files=read(evdir/"source.json")
        chk=original_diagnose.check(d,files,d["key_frames"],d["tick_times"])
        assert chk==d["check"] and chk["grounded"] and not chk["bad_refs"]
        # Every attempt: where it wrote and which tools it called, never what it wrote. A kept one's diff,
        # applied to the brain before, must give the brain after, byte for byte.
        from blinkflow import fix
        for p in attempts:
            rec=read(p/"muse-code.json")
            assert not rec["change"]["agent_commits"]
            problems=fix.audit(rec["tool_calls"])
            passed=(p/"proof.json").exists() and read(p/"proof.json")["passed"]
            if passed:
                assert not rec["problems"] and not problems,(p.name,rec["problems"],problems)
                layout,names=robot_files(rec["change"]["files"])
                work=tmp/(p.name+"-patch")/layout
                work.mkdir(parents=True)
                for n in ROBOT_FILES: shutil.copy(root/"brain-before"/n,work/n)
                subprocess.run(["git","apply",str(p/"change.diff")],cwd=tmp/(p.name+"-patch"),check=True,capture_output=True)
                after=p/"brain" if (p/"brain").exists() else root/"brain-after"
                for n in ROBOT_FILES: assert (work/n).read_bytes()==(after/n).read_bytes(),(p.name,n)
            else:
                assert (p/"failure.json").exists(),p.name
            checks[p.name]={"passed":passed,"files":rec["change"]["files"],"audit_problems":problems}
        if result["passed"]:
            proof=read(root/f"attempt-{result['attempt']}/proof.json")
            assert proof["passed"] and proof["incident"]["fixed"]
            assert len(proof["controls"])==2 and all(c["clean"] for c in proof["controls"].values())
        else:
            assert checks and not any(c["passed"] for c in checks.values())
        assert read(root/"alignment.json")["delta_s"]<=0.1
        accounting=read(root/"models.json")
        assert accounting["repo_spend_usd"]<=3.
        if checkpoint.get("phase")==3: assert accounting["phase3_spend_usd"]<=2.
        assert abs(sum(c["cost_usd"] for c in accounting["calls"])-accounting["total_cost_usd"])<1e-4
        heard=None
        if checkpoint.get("input")=="voice":
            # The sentence as Muse Voice Transcribe returned it, the delay read from it, the key press it was
            # measured back from, and the clip and log that window cut, all from the saved files.
            v=read(root/"voice/voice.json");h=v["heard"];raw=read(root/"voice/voice-reply.json")
            assert h["said"]==raw["transcript"].strip()==checkpoint["spoken"]
            accepted=next(a for a in h["read_attempts"] if a.get("reply") and not a.get("rejected"))
            assert float(json.loads(accepted["reply"])["seconds_ago"])==h["seconds_ago"]
            assert h["moment"]==round(h["press"]-h["seconds_ago"],3)==h["moment_brain_s"]
            t0=h["moment"]-5.;t1=min(h["moment"]+3.,h["press"]+1.)
            assert v["incident"]["window_brain_s"]==[round(t0,3),round(t1,3)]
            window=read(root/"voice/window/snapshot.json");full=read(root/"before/twin/meta.json");i0,i1=window["window"]
            assert window["video_times"]==full["video_times"][i0:i1] and all(t0<=t<=t1 for t in window["video_times"])
            assert relative(before["meta"],root/"before")==root/"voice/window/snapshot.json"
            cut=see.load_snapshot(root/"voice/window/snapshot.json")["record"]
            whole=see.load_snapshot(root/"before/twin/meta.json")["record"]
            assert prove.ticks(cut)==[r for r in prove.ticks(whole) if r["t"]<=window["seconds"]]
            assert hashlib.sha256(pathlib.Path(cut).read_bytes()).hexdigest()==window["record_sha256"]
            with wave.open(str(root/"voice/said.wav")) as w: audio_s=w.getnframes()/w.getframerate()
            assert math.isclose(h["release"]-h["press"],audio_s,abs_tol=1e-6)
            assert any(c["model"]==models.VOICE and c["cost_usd"]>0 for c in accounting["calls"])
            assert h["said"] in (evdir/"diagnosis-input.txt").read_text()
            heard={"said":h["said"],"seconds_ago":h["seconds_ago"],"press_s":h["press"],"moment_s":h["moment"],
                   "window_s":[t0,t1],"audio_sha256":hashlib.sha256((root/"voice/said.wav").read_bytes()).hexdigest()}
        if physics:
            assert (root/"snapshot/scene.xml").read_bytes()==(WORLD/"scene.xml").read_bytes()
            first=twin.replay(tmp/"repeat-a",root/"brain-before",video=False)
            second=twin.replay(tmp/"repeat-b",root/"brain-before",video=False)
            assert first["record_sha256"]==second["record_sha256"]==read(root/"before/twin/meta.json")["record_sha256"]
            physical["determinism"]={"before_record_sha256":first["record_sha256"],"repeats":2}
            t=read(tmp/"repeat-a/truth.json")
            assert t["contact_episodes"] and abs(t["first_contact_s"]-before["first_contact_s"])<=.1
            physical["before"]={"first_contact_s":t["first_contact_s"],"episodes":len(t["contact_episodes"])}
            for p in attempts:
                if not (p/"proof.json").exists(): continue
                proof=read(p/"proof.json")
                brain=p/"brain" if (p/"brain").exists() else root/"brain-after"
                for scene in ("incident",*proof["controls"]):
                    dest=tmp/(p.name+"-physical-"+scene)
                    replay=twin.replay(dest,brain,scene,video=False)
                    src=p if scene=="incident" else p/"control"/scene
                    assert replay["record_sha256"]==read(src/"twin/meta.json")["record_sha256"]
                    t=read(dest/"truth.json")
                    if proof["passed"]: assert not t["contact_episodes"] and t["target_error_m"]<=.02
                    physical[p.name+"/"+scene]={"contact_episodes":len(t["contact_episodes"]),
                                                "target_error_m":t["target_error_m"],"record_sha256":replay["record_sha256"]}
        return {"passed":True,"offline":True,"pixel_rederivations":rederived,"diagnosis":chk,"attempts":checks,
                "voice":heard,"repo_spend_usd":accounting["repo_spend_usd"],
                "run_cost_usd":accounting["total_cost_usd"],"physics":physical}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("example",nargs="?",default="examples/arm")
    ap.add_argument("--pixels-only",action="store_true")
    ap.add_argument("--write")
    a=ap.parse_args()
    try:
        r=recheck(a.example,not a.pixels_only)
    finally:
        if sam._decoders is not None:
            sam._decoders.shutdown(wait=True)
            sam._decoders=None
    if a.write:pathlib.Path(a.write).write_text(json.dumps(r,indent=1))
    print(json.dumps(r,indent=1))


if __name__=="__main__":main()
