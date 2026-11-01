"""Re-derive the public run with network/model access blocked and no API key."""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import tempfile
import tomllib
import urllib.request

import requests
from blinkflow import diagnose as original_diagnose, models, sam, see
from . import HERE, prove, twin, use_target


def deny(*args,**kwargs):
    raise RuntimeError("offline recheck: network/model call forbidden")


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
        for rel,expected in json.loads(manifest.read_text()).items():
            assert hashlib.sha256((root/rel).read_bytes()).hexdigest()==expected,rel
    result=json.loads((root/"result.json").read_text())
    attempt=result["attempt"]
    groups=[("before",False),(f"attempt-{attempt}",False),
            (f"attempt-{attempt}/control/obstacle_moved",True),
            (f"attempt-{attempt}/control/target_moved",True)]
    before=json.loads((root/"before/verdict.json").read_text())
    rederived={}
    with tempfile.TemporaryDirectory(prefix="arm-recheck-") as tmp:
        tmp=pathlib.Path(tmp)
        for name,control in groups:
            src=root/name
            out=tmp/name
            out.mkdir(parents=True)
            shutil.copytree(src/"evidence",out/"evidence")
            meta=json.loads((src/"twin/meta.json").read_text())
            snap=see.load_snapshot(src/"twin/meta.json")
            meta.update(video=snap["clip"],record=snap["record"])
            m=out/"meta.json";m.write_text(json.dumps(meta))
            old=json.loads((src/"verdict.json").read_text())
            v=prove.look(m,out,reference=None if name=="before" else before["travel_m"],
                         reuse=True,control=control)
            ev=json.loads((out/"evidence/evidence.json").read_text())
            saved=json.loads((src/"evidence/evidence.json").read_text())
            for k in ("gap_by_frame","contacts","tracking","closest"):
                assert ev[k]==saved[k],(name,k)
            for k in ("valid","contact","fixed","first_contact_s","closest_gap_px",
                      "target_error_m","target_reached","full_tracking"):
                assert v[k]==old[k],(name,k,v[k],old[k])
            if control: assert v["clean"]
            rederived[name]={k:v[k] for k in ("valid","contact","first_contact_s","target_error_m")}
        evdir=root/"before/evidence"
        d=json.loads((evdir/"diagnosis.json").read_text())
        files=json.loads((evdir/"source.json").read_text())
        chk=original_diagnose.check(d,files,d["key_frames"],d["tick_times"])
        assert chk==d["check"] and chk["grounded"] and not chk["bad_refs"]
        cause=d["cause"];a,b=cause["lines"]["start"],cause["lines"]["end"]
        assert any("clearance" in s for s in files[chk["file"]].splitlines()[a-1:b])
        rec=json.loads((root/f"attempt-{attempt}/muse-code.json").read_text())
        # the run was made in its own repo, where the arm was arm/
        assert not rec["problems"] and rec["change"]["files"]==["arm/brain.toml"]
        assert not rec["change"]["agent_commits"]
        # Re-audit the SDK tool paths against the same arm workspace.
        from blinkflow import fix
        calls=rec["tool_calls"]
        assert not fix.audit(calls)
        initial=tomllib.loads((root/"brain-before/brain.toml").read_text())
        final=tomllib.loads((root/"brain-after/brain.toml").read_text())
        assert final["planner"]["clearance"]>initial["planner"]["clearance"]
        final["planner"]["clearance"]=initial["planner"]["clearance"]
        assert initial==final
        align=json.loads((root/"alignment.json").read_text())
        assert align["delta_s"]<=0.1
        accounting=json.loads((root/"models.json").read_text())
        assert accounting["repo_spend_usd"]<=3.
        assert abs(sum(c["cost_usd"] for c in accounting["calls"])-accounting["total_cost_usd"])<1e-4
        physical={}
        if physics:
            assert (root/"snapshot/scene.xml").read_bytes()==(HERE/"scene.xml").read_bytes()
            first=twin.replay(tmp/"repeat-a",root/"brain-before",video=False)
            second=twin.replay(tmp/"repeat-b",root/"brain-before",video=False)
            saved=json.loads((root/"before/twin/meta.json").read_text())
            assert first["record_sha256"]==second["record_sha256"]==saved["record_sha256"]
            physical["determinism"]={"before_record_sha256":first["record_sha256"],"repeats":2}
            t=json.loads((tmp/"repeat-a/truth.json").read_text())
            assert len(t["contact_episodes"])==1 and abs(t["first_contact_s"]-before["first_contact_s"])<=.1
            for scene in twin.SCENES:
                replay=twin.replay(tmp/("physical-"+scene),root/"brain-after",scene,video=False)
                saved_path=(root/f"attempt-{attempt}" if scene=="incident" else
                            root/f"attempt-{attempt}/control"/scene)/"twin/meta.json"
                assert replay["record_sha256"]==json.loads(saved_path.read_text())["record_sha256"]
                t=json.loads((tmp/("physical-"+scene)/"truth.json").read_text())
                assert not t["contact_episodes"] and t["target_error_m"]<=.02
                physical[scene]={"contact_episodes":len(t["contact_episodes"]),"target_error_m":t["target_error_m"],
                                 "record_sha256":replay["record_sha256"]}
        return {"passed":True,"offline":True,"pixel_rederivations":rederived,"diagnosis":chk,
                "fix_files":rec["change"]["files"],"repo_spend_usd":accounting["repo_spend_usd"],
                "physics":physical}


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
