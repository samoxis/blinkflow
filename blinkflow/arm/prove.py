"""Arm adapter: whole-mask contact, reaching the target, two pixel controls."""
import argparse
import copy
import gzip
import json
import math
import pathlib

from blinkflow import prove as original, see
from . import HERE, budget, twin, see as arm_see

NAMES=json.loads((HERE/"obstacles.json").read_text())


def pixels(ev):
    """A fixed-base arm has no feet or biped fall. Keep the original mask gap."""
    out=copy.deepcopy(ev)
    out["base"]=None
    out["fall"]={"first":None}
    out["contacts"]["base"]=out["contacts"]["body"]=None
    hit=out["contacts"]["whole_mask"]
    out["first_contact"]={"reading":"whole_mask",**hit} if hit else None
    out["incident"]="contact"
    return out


def ticks(record):
    with gzip.open(record,"rt") as fh:
        next(fh)
        return [json.loads(s) for s in fh]


def target_error(record):
    row=ticks(record)[-1]
    return math.dist(row["end_effector"],row["target"])


def look(meta_path,out,reference=None,reuse=False,control=False):
    arm_see.configure()
    meta_path,out=pathlib.Path(meta_path),pathlib.Path(out)
    meta=json.loads(meta_path.read_text())
    snap=see.load_snapshot(meta_path)
    ev=see.see(meta_path,out/"evidence",follow=(NAMES["robot"],NAMES["scenes"][meta["scene"]]["noun"]),
               reuse=reuse,said="a couple of seconds ago the arm hit the red block")
    (out/"tracking-prompts.json").write_text(json.dumps({"robot":"robot arm","robot_prompt":arm_see.PROMPT,
             "robot_prompt_source":"box marked in the initial rendered image; identical before/after",
             "object_prompt":"red block","method":"SAM 3.1 masks, whole-mask gap <= 2 pixels"},indent=1))
    a=pixels(ev)
    v=(original.judge(a,snap["record"],"contact") if control else
       original.verdict(a,snap["record"],reference,kind="contact"))
    err=target_error(snap["record"])
    # Require full coverage: an incomplete tracker may hide the only contact frame.
    covered=all(t["status"]=="completed" and t["frames_with_mask"]==ev["shot"]["frames"]
                for t in ev["tracking"].values())
    valid=v["valid"] and covered
    reached=err<=0.02
    v.update(valid=valid,target_error_m=err,target_reached=reached,full_tracking=covered,
             reading="whole_mask",evidence=str(out/"evidence"),meta=str(meta_path))
    v["fixed"]=v.get("fixed",False) and valid and reached
    if control:
        v["clean"]=v["clean"] and valid and reached
    (out/"verdict.json").write_text(json.dumps(v,indent=1))
    return v


def prove(out,brain=HERE,reference=None):
    out=pathlib.Path(out)
    meta=twin.replay(out/"twin",brain)
    incident=look(out/"twin/meta.json",out,reference)
    controls={}
    if incident["fixed"]:
        for scene in twin.SCENES[1:]:
            p=out/"control"/scene
            twin.replay(p/"twin",brain,scene,fps=9.5)
            controls[scene]=look(p/"twin/meta.json",p,control=True)
    result={"incident":incident,"controls":controls,
            "passed":incident["fixed"] and len(controls)==2 and all(v["clean"] for v in controls.values())}
    (out/"proof.json").write_text(json.dumps(result,indent=1))
    return result


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",required=True)
    ap.add_argument("--reference-travel",type=float,required=True)
    a=ap.parse_args()
    budget.configure()
    result=prove(a.out,reference=a.reference_travel)
    print(json.dumps(result,indent=1))
    raise SystemExit(0 if result["passed"] else 1)


if __name__=="__main__": main()
