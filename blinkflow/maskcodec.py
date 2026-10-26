"""SAM 3.1 mask payloads -> binary rasters. A Python port of the decoder in Meta's `@meta-sam/parser`.

A mask covers its object's box (height x width, row-major). The payload is base-85 text holding a
5-digit length prefix and 4-byte groups, then a 32-bit range-coded stream:

  `!` one_bit   each pixel is one bit, coded with a 12-pixel causal context (two rows above, two
                pixels left) and adaptive counts;
  `~` lossless  each pixel is a coverage byte, predicted from its neighbours (selector in byte 0:
                paeth, up, left, average, gradient) and the zig-zag residual coded with a zero flag
                and a blend of order-0/1/2 models. Pixels with coverage >= 129 are inside.
"""
import numpy as np

_EXCLUDED = set('"\\,;<>|')
ALPHABET = "".join(chr(c) for c in range(0x21, 0x7F) if chr(c) not in _EXCLUDED)
_VALUE = {ch: i for i, ch in enumerate(ALPHABET)}
RADIX, PREFIX = 85, 5
TOP, BOTTOM, MASK32 = 1 << 24, 1 << 16, 0xFFFFFFFF


class MaskError(ValueError):
    pass


def _digit(ch):
    v = _VALUE.get(ch, -1)
    if v < 0 or v >= RADIX:
        raise MaskError("invalid character in mask payload")
    return v


def unpack(payload):
    if len(payload) < PREFIX:
        raise MaskError("mask payload has no length prefix")
    length = 0
    for ch in payload[:PREFIX]:
        length = length * RADIX + _digit(ch)
    rem = length % 4
    if len(payload) != PREFIX + length // 4 * 5 + (rem + 1 if rem else 0):
        raise MaskError("mask payload length does not match its prefix")
    out = bytearray(length)
    src = PREFIX
    for dst in range(0, length - rem, 4):
        v = 0
        for ch in payload[src:src + 5]:
            v = v * RADIX + _digit(ch)
        if v > MASK32:
            raise MaskError("out-of-range group in mask payload")
        out[dst:dst + 4] = v.to_bytes(4, "big")
        src += 5
    if rem:
        v = 0
        for i in range(5):
            v = v * RADIX + (_digit(payload[src + i]) if i < rem + 1 else RADIX - 1)
        if v > MASK32:
            raise MaskError("out-of-range tail in mask payload")
        out[length - rem:] = v.to_bytes(4, "big")[:rem]
    return bytes(out)


class RangeDecoder:
    def __init__(self, data):
        if len(data) < 4:
            raise MaskError("mask payload is missing its finalization")
        self.data, self.pos = data, 4
        self.low, self.range, self.scaled = 0, MASK32, 0
        self.code = int.from_bytes(data[:4], "big")

    def freq(self, total):
        self.scaled = self.range // total
        if self.scaled == 0:
            raise MaskError("invalid coding state")
        v = ((self.code - self.low) & MASK32) // self.scaled
        return total - 1 if v >= total else v

    def decode(self, cum, f):
        low = (self.low + self.scaled * cum) & MASK32
        rng = self.scaled * f
        code, data, pos = self.code, self.data, self.pos
        while True:
            if (low ^ (low + rng)) & MASK32 >= TOP:
                if rng >= BOTTOM:
                    break
                rng = (-low) & (BOTTOM - 1)
            if pos >= len(data):
                raise MaskError("mask payload ended early")
            code = ((code << 8) | data[pos]) & MASK32
            pos += 1
            low = (low << 8) & MASK32
            rng = (rng << 8) & MASK32
        self.low, self.range, self.code, self.pos = low, rng, code, pos


def _decode_one_bit(payload, w, h):
    dec = RangeDecoder(unpack(payload[1:]))
    counts = [1] * (2 * 4096)
    pw = w + 4
    pad = bytearray(pw * (h + 2))
    out = np.zeros(w * h, np.uint8)
    i = 0
    for y in range(h):
        row = (y + 2) * pw + 2
        for x in range(w):
            p = row + x
            q, e = p - pw, p - 2 * pw
            ctx = (pad[p - 1] | pad[p - 2] << 1 | pad[q - 2] << 2 | pad[q - 1] << 3 | pad[q] << 4
                   | pad[q + 1] << 5 | pad[q + 2] << 6 | pad[e - 2] << 7 | pad[e - 1] << 8
                   | pad[e] << 9 | pad[e + 1] << 10 | pad[e + 2] << 11) << 1
            zero, one = counts[ctx], counts[ctx + 1]
            if dec.freq(zero + one) < zero:
                dec.decode(0, zero)
                bit = 0
            else:
                dec.decode(zero, one)
                bit = 1
                out[i] = 1
            pad[p] = bit
            counts[ctx + bit] += 14
            if counts[ctx] + counts[ctx + 1] >= 4096:
                counts[ctx] = counts[ctx] >> 1 or 1
                counts[ctx + 1] = counts[ctx + 1] >> 1 or 1
            i += 1
    return out


def _predict(out, o, x, y, mode, w):
    left = out[o - 1] if x > 0 else 0
    up = out[o - w] if y > 0 else 0
    if mode == 1:
        return up
    if mode == 2:
        return left
    if mode == 3:
        return (left + up) >> 1
    ul = out[o - w - 1] if x > 0 and y > 0 else 0
    if mode == 0:
        est = left + up - ul
        dl, du, dul = abs(est - left), abs(est - up), abs(est - ul)
        if dl <= du and dl <= dul:
            return left
        return up if du <= dul else ul
    if ul >= max(left, up):
        return min(left, up)
    if ul <= min(left, up):
        return max(left, up)
    return left + up - ul


def _decode_lossless(payload, w, h):
    packed = unpack(payload[1:])
    if len(packed) < 5:
        raise MaskError("lossless mask payload is truncated")
    mode = packed[0]
    if mode >= 5:
        raise MaskError("lossless mask payload uses an invalid predictor")
    dec = RangeDecoder(packed[1:])
    n = w * h
    out, res = bytearray(n), bytearray(n)
    zc = [1] * 32
    o1 = [1] * (256 * 256)
    o1t = [256] * 256
    o0 = [2] * 256
    o0t = 512
    o2 = {}
    prev = 0
    for o in range(n):
        x, y = o % w, o // w
        z = ((1 if x == 0 or res[o - 1] == 0 else 0)
             | (1 if y == 0 or res[o - w] == 0 else 0) << 1
             | (1 if x == 0 or y == 0 or res[o - w - 1] == 0 else 0) << 2
             | (1 if y == 0 or x == w - 1 or res[o - w + 1] == 0 else 0) << 3) << 1
        zero, nonzero = zc[z], zc[z + 1]
        bit = 0 if dec.freq(zero + nonzero) < zero else 1
        dec.decode(0, zero) if bit == 0 else dec.decode(zero, nonzero)
        zc[z + bit] += 32
        if zc[z] + zc[z + 1] >= 16384:
            zc[z] = zc[z] >> 1 or 1
            zc[z + 1] = zc[z + 1] >> 1 or 1
        sym = 0
        if bit:
            above = res[o - w] if o >= w else 0
            key = prev << 8 | above
            sec = o2.get(key)
            if sec is None:
                sec = o2[key] = [0] * 257
            f1 = prev << 8
            total = sec[256] + o1t[prev] + o0t - (sec[0] + o1[f1] + o0[0])
            target = dec.freq(total)
            cum, sym = 0, 1
            f = sec[1] + o1[f1 + 1] + o0[1]
            while cum + f <= target:
                cum += f
                sym += 1
                if sym >= 256:
                    raise MaskError("lossless mask payload is malformed")
                f = sec[sym] + o1[f1 + sym] + o0[sym]
            dec.decode(cum, f)
            sec[sym] += 616
            sec[256] += 616
            if sec[256] >= 50176:
                for v in range(256):
                    sec[v] >>= 1
                sec[256] = sum(sec[:256])
            o1[f1 + sym] += 56
            o1t[prev] += 56
            if o1t[prev] >= 8192:
                for v in range(256):
                    o1[f1 + v] = o1[f1 + v] >> 1 or 1
                o1t[prev] = sum(o1[f1:f1 + 256])
            o0[sym] += 32
            o0t += 32
            if o0t >= 4096:
                for v in range(256):
                    o0[v] >>= 1
                o0t = sum(o0)
        res[o] = sym
        delta = -((sym + 1) >> 1) if sym & 1 else sym >> 1
        out[o] = (_predict(out, o, x, y, mode, w) + delta) & 0xFF
        prev = sym
    return (np.frombuffer(bytes(out), np.uint8) >= 129).astype(np.uint8)


def decode(payload, width, height):
    """Payload of `<|mask;x=0;y=0;data=H,W,PAYLOAD|>` -> (height, width) uint8 array of 0/1."""
    if width <= 0 or height <= 0:
        raise MaskError("mask dimensions must be positive")
    if payload.startswith("!"):
        flat = _decode_one_bit(payload, width, height)
    elif payload.startswith("~"):
        flat = _decode_lossless(payload, width, height)
    else:
        raise MaskError("unknown mask encoding")
    return flat.reshape(height, width)
