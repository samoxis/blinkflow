// SAM 3.1 mask payloads -> binary rasters, in the browser. The same decoder as blinkflow/maskcodec.py
// (itself a port of Meta's @meta-sam/parser): base-85 text, then a 32-bit range-coded stream,
// `!` one bit per pixel with a 12-pixel causal context, `~` coverage bytes with a predictor.
"use strict";

const MaskCodec = (() => {
  const EXCLUDED = new Set('"\\,;<>|');
  const VALUE = new Int16Array(128).fill(-1);
  let n = 0;
  for (let c = 0x21; c < 0x7f; c++) if (!EXCLUDED.has(String.fromCharCode(c))) VALUE[c] = n++;
  const RADIX = 85, PREFIX = 5, TOP = 1 << 24, BOTTOM = 1 << 16;

  function digit(s, i) {
    const c = s.charCodeAt(i), v = c < 128 ? VALUE[c] : -1;
    if (v < 0 || v >= RADIX) throw new Error("invalid character in mask payload");
    return v;
  }

  function unpack(s, from) {
    let length = 0;
    for (let i = 0; i < PREFIX; i++) length = length * RADIX + digit(s, from + i);
    const rem = length % 4;
    if (s.length - from !== PREFIX + Math.floor(length / 4) * 5 + (rem ? rem + 1 : 0))
      throw new Error("mask payload length does not match its prefix");
    const out = new Uint8Array(length);
    let src = from + PREFIX;
    for (let dst = 0; dst < length - rem; dst += 4, src += 5) {
      let v = 0;
      for (let i = 0; i < 5; i++) v = v * RADIX + digit(s, src + i);
      if (v > 0xffffffff) throw new Error("out-of-range group in mask payload");
      out[dst] = v >>> 24; out[dst + 1] = (v >>> 16) & 255; out[dst + 2] = (v >>> 8) & 255; out[dst + 3] = v & 255;
    }
    if (rem) {
      let v = 0;
      for (let i = 0; i < 5; i++) v = v * RADIX + (i < rem + 1 ? digit(s, src + i) : RADIX - 1);
      if (v > 0xffffffff) throw new Error("out-of-range tail in mask payload");
      const b = [v >>> 24, (v >>> 16) & 255, (v >>> 8) & 255, v & 255];
      for (let i = 0; i < rem; i++) out[length - rem + i] = b[i];
    }
    return out;
  }

  // 32-bit unsigned arithmetic in doubles: every value stays below 2^53, `>>> 0` wraps like & MASK32.
  class RangeDecoder {
    constructor(data) {
      if (data.length < 4) throw new Error("mask payload is missing its finalization");
      this.data = data; this.pos = 4; this.low = 0; this.range = 0xffffffff; this.scaled = 0;
      this.code = ((data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]) >>> 0;
    }
    freq(total) {
      this.scaled = Math.floor(this.range / total);
      if (this.scaled === 0) throw new Error("invalid coding state");
      const v = Math.floor(((this.code - this.low) >>> 0) / this.scaled);
      return v >= total ? total - 1 : v;
    }
    decode(cum, f) {
      let low = (this.low + this.scaled * cum) >>> 0;
      let rng = this.scaled * f;
      let code = this.code, pos = this.pos;
      const data = this.data;
      for (;;) {
        if (((low ^ ((low + rng) >>> 0)) >>> 0) >= TOP) {
          if (rng >= BOTTOM) break;
          rng = (-low >>> 0) & (BOTTOM - 1);
        }
        if (pos >= data.length) throw new Error("mask payload ended early");
        code = (((code << 8) >>> 0) | data[pos++]) >>> 0;
        low = (low << 8) >>> 0;
        rng = (rng * 256) % 4294967296;
      }
      this.low = low; this.range = rng; this.code = code; this.pos = pos;
    }
  }

  function oneBit(s, w, h) {
    const dec = new RangeDecoder(unpack(s, 1));
    const counts = new Uint16Array(2 * 4096).fill(1);
    const pw = w + 4, pad = new Uint8Array(pw * (h + 2)), out = new Uint8Array(w * h);
    let i = 0;
    for (let y = 0; y < h; y++) {
      const row = (y + 2) * pw + 2;
      for (let x = 0; x < w; x++, i++) {
        const p = row + x, q = p - pw, e = p - 2 * pw;
        const ctx = (pad[p - 1] | pad[p - 2] << 1 | pad[q - 2] << 2 | pad[q - 1] << 3 | pad[q] << 4
          | pad[q + 1] << 5 | pad[q + 2] << 6 | pad[e - 2] << 7 | pad[e - 1] << 8
          | pad[e] << 9 | pad[e + 1] << 10 | pad[e + 2] << 11) << 1;
        const zero = counts[ctx], one = counts[ctx + 1];
        let bit;
        if (dec.freq(zero + one) < zero) { dec.decode(0, zero); bit = 0; }
        else { dec.decode(zero, one); bit = 1; out[i] = 1; }
        pad[p] = bit;
        counts[ctx + bit] += 14;
        if (counts[ctx] + counts[ctx + 1] >= 4096) {
          counts[ctx] = (counts[ctx] >> 1) || 1;
          counts[ctx + 1] = (counts[ctx + 1] >> 1) || 1;
        }
      }
    }
    return out;
  }

  function predict(out, o, x, y, mode, w) {
    const left = x > 0 ? out[o - 1] : 0, up = y > 0 ? out[o - w] : 0;
    if (mode === 1) return up;
    if (mode === 2) return left;
    if (mode === 3) return (left + up) >> 1;
    const ul = x > 0 && y > 0 ? out[o - w - 1] : 0;
    if (mode === 0) {
      const est = left + up - ul, dl = Math.abs(est - left), du = Math.abs(est - up), dul = Math.abs(est - ul);
      if (dl <= du && dl <= dul) return left;
      return du <= dul ? up : ul;
    }
    if (ul >= Math.max(left, up)) return Math.min(left, up);
    if (ul <= Math.min(left, up)) return Math.max(left, up);
    return left + up - ul;
  }

  function lossless(s, w, h) {
    const packed = unpack(s, 1);
    if (packed.length < 5) throw new Error("lossless mask payload is truncated");
    const mode = packed[0];
    if (mode >= 5) throw new Error("lossless mask payload uses an invalid predictor");
    const dec = new RangeDecoder(packed.subarray(1));
    const n = w * h, out = new Uint8Array(n), res = new Uint8Array(n);
    const zc = new Uint32Array(32).fill(1), o1 = new Uint32Array(256 * 256).fill(1);
    const o1t = new Uint32Array(256).fill(256), o0 = new Uint32Array(256).fill(2);
    let o0t = 512, prev = 0;
    const o2 = new Map();
    for (let o = 0; o < n; o++) {
      const x = o % w, y = (o - x) / w;
      const z = ((x === 0 || res[o - 1] === 0 ? 1 : 0)
        | (y === 0 || res[o - w] === 0 ? 1 : 0) << 1
        | (x === 0 || y === 0 || res[o - w - 1] === 0 ? 1 : 0) << 2
        | (y === 0 || x === w - 1 || res[o - w + 1] === 0 ? 1 : 0) << 3) << 1;
      const zero = zc[z], nonzero = zc[z + 1];
      const bit = dec.freq(zero + nonzero) < zero ? 0 : 1;
      if (bit === 0) dec.decode(0, zero); else dec.decode(zero, nonzero);
      zc[z + bit] += 32;
      if (zc[z] + zc[z + 1] >= 16384) { zc[z] = (zc[z] >> 1) || 1; zc[z + 1] = (zc[z + 1] >> 1) || 1; }
      let sym = 0;
      if (bit) {
        const above = o >= w ? res[o - w] : 0, key = prev << 8 | above;
        let sec = o2.get(key);
        if (!sec) { sec = new Uint32Array(257); o2.set(key, sec); }
        const f1 = prev << 8;
        const total = sec[256] + o1t[prev] + o0t - (sec[0] + o1[f1] + o0[0]);
        const target = dec.freq(total);
        let cum = 0;
        sym = 1;
        let f = sec[1] + o1[f1 + 1] + o0[1];
        while (cum + f <= target) {
          cum += f;
          sym++;
          if (sym >= 256) throw new Error("lossless mask payload is malformed");
          f = sec[sym] + o1[f1 + sym] + o0[sym];
        }
        dec.decode(cum, f);
        sec[sym] += 616; sec[256] += 616;
        if (sec[256] >= 50176) {
          let t = 0;
          for (let v = 0; v < 256; v++) { sec[v] >>= 1; t += sec[v]; }
          sec[256] = t;
        }
        o1[f1 + sym] += 56; o1t[prev] += 56;
        if (o1t[prev] >= 8192) {
          let t = 0;
          for (let v = 0; v < 256; v++) { o1[f1 + v] = (o1[f1 + v] >> 1) || 1; t += o1[f1 + v]; }
          o1t[prev] = t;
        }
        o0[sym] += 32; o0t += 32;
        if (o0t >= 4096) {
          let t = 0;
          for (let v = 0; v < 256; v++) { o0[v] >>= 1; t += o0[v]; }
          o0t = t;
        }
      }
      res[o] = sym;
      const delta = sym & 1 ? -((sym + 1) >> 1) : sym >> 1;
      out[o] = (predict(out, o, x, y, mode, w) + delta) & 255;
      prev = sym;
    }
    for (let o = 0; o < n; o++) out[o] = out[o] >= 129 ? 1 : 0;
    return out;
  }

  // `<Nf>` lines of a reply saved by blinkflow.sam -> {frame: line}, decoded only when asked for.
  const FRAME = /^<(\d+)f(?:;[^>]*)?>/;
  const RECORD = /,?(\d+)((?:<\|[^|]*\|>)+)/g;
  const TOKEN = /<\|([A-Za-z][\w.-]*)(?:;([^|]*))?\|>/g;

  function fields(body) {
    const out = {};
    for (const part of (body || "").split(";")) {
      const k = part.indexOf("=");
      if (k > 0) out[part.slice(0, k).trim()] = part.slice(k + 1).trim();
    }
    return out;
  }

  class Track {
    constructor(text) {
      this.lines = new Map();
      this.cache = new Map();
      for (const line of text.split("\n")) {
        const m = FRAME.exec(line.trim());
        if (m) this.lines.set(+m[1], line.trim());
      }
    }
    // [{box: [x1, y1, x2, y2], w, h, mask: Uint8Array(h * w)}] for one frame (empty: not seen)
    frame(f) {
      if (this.cache.has(f)) return this.cache.get(f);
      const line = this.lines.get(f), found = [];
      if (line) {
        const body = line.replace(FRAME, "");
        for (const rec of body.matchAll(RECORD)) {
          const tokens = {};
          for (const t of rec[2].matchAll(TOKEN)) tokens[t[1]] = fields(t[2]);
          const box = tokens.box, mask = tokens.mask;
          if (!box || !mask) continue;
          const d = /^(\d+),(\d+),([!~][^|]+)$/.exec(mask.data || "");
          if (!d) continue;
          const h = +d[1], w = +d[2];
          try {
            found.push({ box: [+box.x1, +box.y1, +box.x2, +box.y2], w, h, mask: decode(d[3], w, h) });
          } catch (e) { console.warn("mask", f, e); }
        }
      }
      this.cache.set(f, found);
      return found;
    }
  }

  function decode(payload, w, h) {
    if (payload[0] === "!") return oneBit(payload, w, h);
    if (payload[0] === "~") return lossless(payload, w, h);
    throw new Error("unknown mask encoding");
  }

  return { decode, Track };
})();

if (typeof module !== "undefined") module.exports = MaskCodec;
