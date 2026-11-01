"""The arm's spoken input: blinkflow.voice.clip unchanged, on the arm's recorded replay, with a replayed key press.

Only the confirmation differs: the window clip it cuts is measured with the arm's pixel reading (prove.look),
whose verdict and evidence become the loop's `before`. Muse Voice Transcribe is booked in the arm's budget, and
its reply is kept (voice/voice-reply.json) so the transcript can be re-checked offline.
"""
import hashlib
import json
import pathlib

from blinkflow import models, voice as original, watch
from . import budget, prove


def recorded(meta, out, wav, press):
    out = pathlib.Path(out)
    original_confirm, post, transcribe = original.confirm, models.requests.post, models.transcribe
    voice_ledger = None

    def capture(url, *args, **kwargs):
        response = post(url, *args, **kwargs)
        if url == models.ASR:
            (out/"voice/voice-reply.json").write_text(json.dumps(response.json(), indent=1))
        return response

    def metered(data, ledger, purpose, mode="PUSH_TO_TALK"):
        nonlocal voice_ledger
        voice_ledger = ledger
        held = budget.book(original.wav_seconds(data)/60*models.VOICE_PER_MIN, "Muse Voice Transcribe")
        result = transcribe(data, ledger, purpose, mode)
        budget.book(ledger.calls[-1]["cost_usd"]-held, "settle Muse Voice Transcribe")
        return result

    def confirm(snapshot, evdir, heard, ledger):
        path = pathlib.Path(snapshot)
        m = json.loads(path.read_text())
        # the window's record is a cut of the replay's: its own hash, the replay's kept beside it
        m.update(source_record_sha256=m.get("record_sha256"),
                 record_sha256=hashlib.sha256(pathlib.Path(m["record"]).read_bytes()).hexdigest())
        path.write_text(json.dumps(m, indent=1))
        v = prove.look(path, out/"before", said=heard["said"])
        mo = watch.motion(out/"before/evidence", path)
        seen = v["valid"] and v["contact"] and mo["moved"]
        ledger.write(out/"voice/models.json")
        return {"kind": "contact" if seen else None, "confirmed": seen, "names": ["robot arm", "red block"],
                "robot_moved": mo["moved"], "object_as_said": heard["object"],
                "names_agree": "red block" in heard["object"].lower(), "incident_s": v["first_contact_s"],
                "reading": "whole_mask", "seconds": 0., "snapshot": str(path), "evidence": str(out/"before/evidence")}

    original.confirm, models.requests.post, models.transcribe = confirm, capture, metered
    try:
        doc = original.clip(pathlib.Path(meta), press, out/"voice", wav=str(wav), with_loop=False, auto=True,
                            brain=out/"brain-before")
        if not (doc.get("incident") or {}).get("confirmed"):
            raise RuntimeError("spoken incident not confirmed")
        h = doc["heard"]
        (out/"voice/input.json").write_text(json.dumps({"mode": "blinkflow.voice.clip", "press_s": press,
            "press_provenance": "specified on the saved replay timeline; not a captured physical key event",
            "audio": "said.wav", "moment_formula": "press_s - parsed seconds_ago", "moment_s": h["moment"],
            "source_snapshot": str(meta), "rewind_snapshot": doc["incident"]["snapshot"]}, indent=1))
        return doc
    finally:
        if voice_ledger is not None:
            voice_ledger.write(out/"voice/models.json")
        original.confirm, models.requests.post, models.transcribe = original_confirm, post, transcribe
