"""SAM 3.1 on the Meta Model API: one noun phrase, one video, every instance tracked with its mask.

The reply streams as text, one line per frame:

    <12f>0<|box;x1=..;y1=..;x2=..;y2=..;w=W;h=H;c=0.93|><|mask;x=0;y=0;data=H,W,PAYLOAD|>,1<|box;...|>...

Box corners are inclusive; the mask covers exactly the box. Lines can be split across stream deltas,
so text is buffered until a newline.
"""
import base64
import json
import pathlib
import re
import time

import numpy as np
import requests

from . import maskcodec
from .models import API, SAM_PER_FRAME, api_key, sam_reserve

FRAME = re.compile(r"^<(\d+)f(?:;[^>]*)?>(.*)$")
RECORD = re.compile(r",?(\d+)((?:<\|[^|]*\|>)+)")
TOKEN = re.compile(r"<\|([A-Za-z][\w.-]*)(?:;([^|]*))?\|>")
MASK_DATA = re.compile(r"^(\d+),(\d+),([!~][^|]+)$")


class Instance:
    __slots__ = ("id", "box", "size", "mask", "conf")

    def __init__(self, id_, box, size, mask, conf):
        self.id, self.box, self.size, self.mask, self.conf = id_, box, size, mask, conf

    def full(self):
        """The mask placed in a full-frame (h, w) boolean array."""
        w, h = self.size
        out = np.zeros((h, w), bool)
        x1, y1, x2, y2 = self.box
        out[y1:y2 + 1, x1:x2 + 1] = self.mask.astype(bool)
        return out


def _fields(body):
    out = {}
    for part in (body or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def parse_line(line):
    """One output line -> (frame, [Instance]) or None for anything that is not a frame line."""
    m = FRAME.match(line.strip())
    if not m:
        return None
    frame, body, found = int(m.group(1)), m.group(2), []
    for rec in RECORD.finditer(body):
        tokens = {name: _fields(b) for name, b in TOKEN.findall(rec.group(2))}
        box, mask = tokens.get("box"), tokens.get("mask")
        if not box or not mask:
            continue
        data = MASK_DATA.match(mask.get("data", ""))
        if not data:
            continue
        h, w = int(data.group(1)), int(data.group(2))
        coords = tuple(int(box[k]) for k in ("x1", "y1", "x2", "y2"))
        raster = maskcodec.decode(data.group(3), w, h)
        found.append(Instance(rec.group(1), coords, (int(box["w"]), int(box["h"])), raster,
                              float(box["c"]) if "c" in box else None))
    return frame, found


def load_raw(path):
    """Per-frame instances from a reply saved by `track`, without calling the API again."""
    per_frame = {}
    for line in pathlib.Path(path).read_text().split("\n"):
        parsed = parse_line(line)
        if parsed:
            per_frame[parsed[0]] = parsed[1]
    return per_frame


def track(clip, concept, frames, raw_path=None):
    """Track `concept` through `clip` (which has `frames` frames). Returns a dict with per-frame
    instances, timing, usage and cost. Spends against the daily SAM budget before sending."""
    cost = sam_reserve(frames, f"sam-3.1 '{concept}' on {clip}")
    video = "data:video/mp4;base64," + base64.b64encode(open(clip, "rb").read()).decode()
    body = {"model": "sam-3.1", "stream": True, "metadata": {"include_confidence": "true"},
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": concept},
                {"type": "input_video", "video_url": video}]}]}
    t0 = time.time()
    first, buf, raw, per_frame, usage, status = None, "", [], {}, None, "eof"

    def take(line):
        parsed = parse_line(line)
        if parsed:
            per_frame[parsed[0]] = parsed[1]

    with requests.post(API, json=body, stream=True, timeout=900,
                       headers={"Authorization": "Bearer " + api_key()}) as r:
        if r.status_code != 200:
            raise RuntimeError(f"SAM HTTP {r.status_code}: {r.text[:500]}")
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                ev = json.loads(payload)
            except json.JSONDecodeError:
                continue
            kind = ev.get("type")
            if kind == "response.output_text.delta":
                if first is None:
                    first = time.time() - t0
                delta = ev.get("delta", "")
                raw.append(delta)
                buf += delta
                *done, buf = buf.split("\n")
                for d in done:
                    take(d)
            elif kind == "response.completed":
                usage, status = (ev.get("response") or {}).get("usage"), "completed"
            elif kind in ("response.incomplete", "response.failed", "error"):
                status = kind
                break
    take(buf)
    if raw_path:
        open(raw_path, "w").write("".join(raw))
    return {"concept": concept, "frames": per_frame, "status": status, "usage": usage,
            "seconds": time.time() - t0, "seconds_to_first_frame": first,
            "frames_sent": frames, "cost_usd": cost, "price_per_frame": SAM_PER_FRAME}
