"""SAM 3.1's masks for the page: each reply (sam-*.txt) decoded once in Python and kept beside it as
<name>.masks.json, so the browser draws masks without a SAM decoder of its own.

    {"format": "blinkflow-masks/1", "sha256": <of the reply>, "frames": {"<frame>": [
        {"box": [x1, y1, x2, y2], "w": W, "h": H, "rle": [zeros, ones, zeros, ...]}, ...]}}

The mask covers its box row by row (H x W); `rle` is run lengths over that order, starting with a run of
zeros (0 when the first pixel is set). Reading a kept file needs only the standard library; writing one
decodes the reply with sam.parse_lines (meta-sam-parser, numpy).

    python3 -m blinkflow.masks <sam-*.txt>...      # write each one's .masks.json
"""
import hashlib
import json
import pathlib
import sys

FORMAT = "blinkflow-masks/1"


def path_of(reply):
    reply = pathlib.Path(reply)
    return reply.with_name(reply.stem + ".masks.json")


def rle(mask):
    """A (h, w) array of 0/1 -> run lengths in row-major order, zeros first."""
    import numpy as np
    flat = np.asarray(mask, np.uint8).ravel()
    edges = np.flatnonzero(np.diff(flat)) + 1
    runs = np.diff(np.concatenate(([0], edges, [flat.size]))).tolist()
    return ([0] + runs) if flat.size and flat[0] else runs


def unrle(runs, size):
    """Run lengths -> a bytearray of 0/1 (the inverse of rle)."""
    out, at, bit = bytearray(size), 0, 0
    for n in runs:
        if bit:
            out[at:at + n] = b"\x01" * n
        at, bit = at + n, 1 - bit
    if at != size:
        raise ValueError(f"runs cover {at} pixels, the box {size}")
    return out


def build(reply):
    """The masks of a reply, decoded: the document described above."""
    from .sam import parse_lines
    data = pathlib.Path(reply).read_bytes()
    frames = {str(f): [{"box": list(i.box), "w": int(i.mask.shape[1]), "h": int(i.mask.shape[0]), "rle": rle(i.mask)}
                       for i in found] for f, found in sorted(parse_lines(data.decode().split("\n")).items())}
    return {"format": FORMAT, "sha256": hashlib.sha256(data).hexdigest(), "frames": frames}


def load(reply):
    """The kept masks of a reply as JSON text, written first if missing or made from other bytes."""
    reply, kept = pathlib.Path(reply), path_of(reply)
    if kept.is_file():
        text = kept.read_text()
        doc = json.loads(text)
        if doc.get("format") == FORMAT and doc.get("sha256") == hashlib.sha256(reply.read_bytes()).hexdigest():
            return text
    text = json.dumps(build(reply), separators=(",", ":"))
    try:
        kept.write_text(text)
    except OSError:                      # a read-only folder: decoded, not kept
        pass
    return text


if __name__ == "__main__":
    for r in sys.argv[1:]:
        load(r)
        print(path_of(r), path_of(r).stat().st_size)
