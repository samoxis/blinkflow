"""Arm evidence adapter; reuse Wonder request/schema and BlinkFlow citation checker."""
import base64
import json
import pathlib

from blinkflow import diagnose as original, models, sam, see
from . import prove

INSTRUCTIONS="""Debug a fixed-base three-joint robot manipulator in the x-z plane, not a biped.
The controller plans Cartesian waypoints, solves inverse kinematics and runs joint PD at 200 Hz.
Find one causal code/config location from the frames, pixel gaps, controller log and numbered code.
Every claim cites its source: frame K1..K4, measurement at a sent key-frame time,
log t=... from the provided table, or code file:line. Cite at least one key frame and one log tick.
No contact truth from the simulator is supplied. Mask contact means gap <= 2 pixels in this side view.
The cause is one real file, function/config key, and line range <=30 lines. Cite the exact setting
when a configuration value is the cause. Explain alternatives ruled out by the evidence.
Do not write a patch. Suggest a direction for the fix.
The fixed robot must still reach the green target. Return JSON matching the schema.
plain has three short everyday sentences (camera, robot, why); confidence is your estimate.
"""


def diagnose(evdir,ledger):
    evdir=pathlib.Path(evdir)
    ev=prove.pixels(json.loads((evdir/"evidence.json").read_text()))
    snap=see.load_snapshot(ev["snapshot"])
    keys=original.key_frames(ev,snap)
    needed={k["shot_frame"] for k in keys}
    masks=[sam.load_raw(evdir/f"sam-{name}.txt",needed) for name in ("robot","object")]
    by_frame={p["frame"]:p for p in ev["gap_by_frame"]}
    (evdir/"keyframes").mkdir(exist_ok=True)
    for k in keys:
        f=k["shot_frame"]
        m=by_frame[k["frame"]]
        img=original.annotate(see.rgb(str(evdir/"shot.mp4"),f),
                              see.union(masks[0][f],tuple(ev["shot"]["size"])),
                              see.union(masks[1][f],tuple(ev["shot"]["size"])),None,k,m,
                              ("robot arm","red block"))
        k.update(image=f"keyframes/{k['tag']}.jpg",gap_px=m["gap_px"])
        img.save(evdir/k["image"],quality=88)
    tc=ev["first_contact"]["brain_s"]
    rows=[r for r in prove.ticks(snap["record"]) if tc-3<=r["t"]<=tc+0.25]
    sent=rows[::10]
    table="t(s) | ee_xyz(m) | joint_targets(rad) | waypoint | clearance(m)\n"
    table+="\n".join(f"t={r['t']:.3f} | {r['end_effector']} | {r['joint_targets']} | {r['waypoint']} | {r['clearance']}"
                     for r in sent)
    folder=pathlib.Path(snap["source"]).resolve()
    # Code snapshot stays with the run even after Muse Code changes the live arm.
    target=pathlib.Path(json.loads(folder.read_text())["brain"])
    files={n:(target/n).read_text() for n in ("brain.py","brain.toml")}
    (evdir/"source.json").write_text(json.dumps(files,indent=1))
    measurements="\n".join(f"{k['tag']}: t={k['brain_s']:.3f}, frame={k['frame']}, gap={k['gap_px']} px" for k in keys)
    text=f"Spoken sentence: a couple of seconds ago the arm hit the red block\nFirst mask contact: {tc:.3f} s\n{measurements}\n\n{table}"
    content=[{"type":"input_text","text":INSTRUCTIONS+"\n"+original.code_text(files)},
             {"type":"input_text","text":text}]
    for k in keys:
        content.extend([{"type":"input_text","text":k["tag"]},
                        {"type":"input_image","image_url":"data:image/jpeg;base64,"+
                         base64.b64encode((evdir/k["image"]).read_bytes()).decode()}])
    (evdir/"diagnosis-input.txt").write_text(INSTRUCTIONS+"\n"+original.code_text(files)+"\n"+text)
    reply=models.respond(models.WONDER,content,ledger,"arm diagnosis",schema=original.SCHEMA,max_output=6000)
    (evdir/"wonder-reply.json").write_text(reply)
    d=json.loads(reply)
    check=original.check(d,files,keys,[r["t"] for r in sent])
    doc={**d,"check":check,"key_frames":keys,"tick_times":[r["t"] for r in sent],
         "model":ledger.calls[-1]}
    (evdir/"diagnosis.json").write_text(json.dumps(doc,indent=1))
    (evdir/"diagnosis.md").write_text(d["explanation"]+"\n\n"+json.dumps(d,indent=1)+"\n")
    if not check["grounded"] or check["bad_refs"]:
        raise RuntimeError(f"Ungrounded diagnosis: {check}")
    return doc
