"""SAM 3.1 on the Meta Model API: one noun phrase, one video, every instance tracked with its mask.

The reply streams as text, one line per frame:

    <12f>0<|box;x1=..;y1=..;x2=..;y2=..;w=W;h=H;c=0.93|><|mask;x=0;y=0;data=H,W,PAYLOAD|>,1<|box;...|>...

Box corners are inclusive; the mask covers exactly the box. Lines can be split across stream deltas,
so text is buffered until a newline.
"""
import base64
import concurrent.futures
import json
import multiprocessing
import os
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


_decoders = None


def decoders():
    """Processes that decode masks. Each mask is a range-coded stream of its own, decoded pixel by pixel
    in Python: ~40 ms for a box, 26 s for one followed through 658 frames, all of it holding the GIL
    while the replies stream in. Frames are independent, so they are decoded side by side."""
    global _decoders
    if _decoders is None:
        # forkserver: the callers are threaded, and a fork of a threaded process can inherit a held lock
        _decoders = concurrent.futures.ProcessPoolExecutor(max(1, (os.cpu_count() or 2) // 2),
                                                           mp_context=multiprocessing.get_context("forkserver"))
    return _decoders


def parse_lines(lines, only=None):
    """{frame: [Instance]} for the frame lines among `lines` (those numbered in `only`, if given),
    decoded in parallel."""
    lines = [line for line in lines if (m := FRAME.match(line.strip())) and (only is None or int(m.group(1)) in only)]
    if only is not None:
        return dict(p for p in map(parse_line, lines) if p)
    return dict(p for p in decoders().map(parse_line, lines, chunksize=4) if p)


def load_raw(path, only=None):
    """Per-frame instances from a reply saved by `track`, without calling the API again."""
    return parse_lines(pathlib.Path(path).read_text().split("\n"), only)


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
    first, buf, raw, pending, usage, status = None, "", [], [], None, "eof"

    def take(line):                         # decoded in the background while the reply streams on
        if FRAME.match(line.strip()):
            pending.append(decoders().submit(parse_line, line))

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
    per_frame = dict(p for p in (f.result() for f in pending) if p)
    if raw_path:
        open(raw_path, "w").write("".join(raw))
    return {"concept": concept, "frames": per_frame, "status": status, "usage": usage, "raw": "".join(raw),
            "seconds": time.time() - t0, "seconds_to_first_frame": first,
            "frames_sent": frames, "cost_usd": cost, "price_per_frame": SAM_PER_FRAME}


def renumber(raw, offset, keep):
    """The frame lines of a reply for one piece of a shot, only those in `keep` (the piece's own frame
    numbers), numbered as in the whole shot (+ `offset`)."""
    out = []
    for line in raw.split("\n"):
        m = FRAME.match(line.strip())
        if m and int(m.group(1)) in keep:
            out.append(re.sub(r"^<(\d+)f", lambda x: f"<{int(x.group(1)) + offset}f", line.strip()))
    return "\n".join(out)
