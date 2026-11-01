"""Use blinkflow.voice.clip unchanged, adapting only the arm's pixel confirmation."""
import json
import pathlib
import hashlib

from blinkflow import models, voice as original, watch
from . import budget, prove


def recorded(meta,out,wav,press):
    out=pathlib.Path(out)
    original_confirm=original.confirm
    post=models.requests.post
    transcribe=models.transcribe
    voice_ledger=None

    def capture(url,*args,**kwargs):
        response=post(url,*args,**kwargs)
        if url==models.ASR:
            (out/"voice/voice-reply.json").write_text(json.dumps(response.json(),indent=1))
        return response

    def metered(data,ledger,purpose,mode="PUSH_TO_TALK"):
        nonlocal voice_ledger
        voice_ledger=ledger
        seconds=original.wav_seconds(data)
        held=budget.book(seconds/60*models.VOICE_PER_MIN,"Muse Voice Transcribe")
        result=transcribe(data,ledger,purpose,mode)
        budget.book(ledger.calls[-1]["cost_usd"]-held,"settle Muse Voice Transcribe")
        return result

    def confirm(snapshot,evdir,heard,ledger):
        # Only this robot-specific pixel adapter differs from voice.clip's confirmation.
        path=pathlib.Path(snapshot);meta=json.loads(path.read_text())
        meta["source_record_sha256"]=meta.get("record_sha256")
        meta["record_sha256"]=hashlib.sha256(pathlib.Path(meta["record"]).read_bytes()).hexdigest()
        path.write_text(json.dumps(meta,indent=1))
        v=prove.look(snapshot,out/"before",said=heard["said"])
        mo=watch.motion(out/"before/evidence",snapshot)
        doc={"kind":"contact" if v["valid"] and v["contact"] and mo["moved"] else None,
             "confirmed":v["valid"] and v["contact"] and mo["moved"],
             "names":["robot arm","red block"],"robot_moved":mo["moved"],
             "object_as_said":heard["object"],"names_agree":"red block" in heard["object"].lower(),
             "incident_s":v["first_contact_s"],"reading":"whole_mask","seconds":0.,
             "snapshot":str(snapshot),"evidence":str(out/"before/evidence")}
        ledger.write(out/"voice/models.json")
        return doc

    original.confirm=confirm
    models.requests.post=capture
    models.transcribe=metered
    try:
        doc=original.clip(pathlib.Path(meta),press,out/"voice",wav=str(wav),with_loop=False,
                          auto=True,brain=out/"brain-before")
        if not doc.get("incident",{}).get("confirmed"):
            raise RuntimeError("spoken incident not confirmed")
        h=doc["heard"]
        (out/"voice/input.json").write_text(json.dumps({"mode":"blinkflow.voice.clip","press_s":press,
            "press_provenance":"specified on the saved replay timeline; not a captured physical key event",
            "audio":"said.wav","moment_formula":"press_s - parsed seconds_ago", "moment_s":h["moment"],
            "source_snapshot":str(meta),"rewind_snapshot":doc["incident"]["snapshot"]},indent=1))
        return doc
    finally:
        if voice_ledger is not None:voice_ledger.write(out/"voice/models.json")
        original.confirm=original_confirm
        models.requests.post=post
        models.transcribe=transcribe
