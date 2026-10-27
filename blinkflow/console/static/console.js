// BlinkFlow console: the loop's event stream (blinkflow.events) drawn as eight steps.
// Live: the server sends the stream as server-sent events and the files it names at /file?p=.
// Static report: static.js holds the stream and a map from each named path to its copy beside the page.
"use strict";
(() => {
const STATIC = window.BLINKFLOW_STATIC || null;
const TEXT = window.BLINKFLOW_TEXT;

// ── small helpers ──────────────────────────────────────────────────────────
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat(Infinity)) if (k != null && k !== false) el.append(k instanceof Node ? k : String(k));
  return el;
}
const SVG = "http://www.w3.org/2000/svg";
function s(tag, attrs, ...kids) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null) el.setAttribute(k, v);
  for (const k of kids.flat()) if (k != null) el.append(k instanceof Node ? k : String(k));
  return el;
}
const num = (x, d = 1) => (x == null || isNaN(x) ? "–" : (+x).toFixed(d));
const secs = (x, d = 1) => (x == null ? "–" : `${num(x, d)} s`);
const usd = (x) => (x == null ? "–" : x > 0 && x < 0.01 ? `$${x.toFixed(4)}` : `$${x.toFixed(2)}`);
const tilde = (p) => String(p || "").replace(/^\/home\/[^/]+/, "~");
const last = (a) => a[a.length - 1];
function clockText(sec) {
  if (sec == null) return "–";
  const m = Math.floor(sec / 60), r = sec - 60 * m;
  return `${m}:${r.toFixed(1).padStart(4, "0")}`;
}

function url(p) {
  if (!p) return null;
  if (STATIC) return STATIC.files[p] || null;
  return "/file?p=" + encodeURIComponent(p);
}
async function text(p) {
  if (!STATIC) {
    const r = await fetch(url(p));
    if (!r.ok) throw new Error(`${r.status} ${p}`);
    return r.text();
  }
  if (TEXT[p] == null) {
    const src = url(p);
    if (!src) throw new Error(`not in the report: ${p}`);
    await new Promise((ok, no) => document.head.append(h("script", { src, onload: ok, onerror: no })));
  }
  return TEXT[p];
}
// a part fades in the first time it is drawn, not on every redraw
const faded = new Set();
const fx = (k) => (faded.has(k) ? "" : (faded.add(k), "fade"));
const tracks = new Map();
function track(p) {
  if (!tracks.has(p)) tracks.set(p, text(p).then((t) => new MaskCodec.Track(t)));
  return tracks.get(p);
}

// ── the models and the steps ───────────────────────────────────────────────
const MODEL = {
  voice: ["Muse Voice", "listens"],
  glimmer: ["Muse Glimmer", "sees the scene, on this PC"],
  sam: ["SAM 3.1", "follows every object"],
  wonder: ["Muse Wonder", "finds the cause"],
  code: ["Muse Code", "writes the fix"],
  you: ["You", "decide"],
};
const chip = (m) => h("span", { class: `model m-${m}` }, h("b", {}, MODEL[m][0]), ` · ${MODEL[m][1]}`);
const plain = (t) => h("span", { class: "model plain" }, t);

const STEPS = [
  { id: "watch", title: "The last 60 seconds", models: () => [plain("the screen, kept in a 60 s ring")] },
  { id: "heard", title: "Something went wrong",
    models: () => (st.mode === "watch" ? [chip("glimmer")] : [chip("voice")]) },
  { id: "see", title: "See what happened", models: () => [chip("glimmer"), chip("sam")] },
  { id: "cause", title: "Find the cause", models: () => [chip("wonder")] },
  { id: "ask", title: "Fix it?", models: () => [chip("you")] },
  { id: "fix", title: "Write the fix", models: () => [chip("code")] },
  { id: "proof", title: "Prove it: replay", models: () => [chip("sam"), plain("same scene, same inputs, in the twin")] },
  { id: "done", title: "Fixed and verified", models: () => [plain("the real clock and the bill")] },
];
const STEP = Object.fromEntries(STEPS.map((x, i) => [x.id, { ...x, n: i + 1 }]));

// ── state, built from events ───────────────────────────────────────────────
let st, skew = 0, shown = null, shownAt = 0, pinned = null, dirty = true;
let replaying = null;               // static report: the replay in progress
function fresh() {
  return {
    mode: null, run: null, feed: null, brainStart: null, brainStop: null, listen: null, key: null, said: null,
    read: null, rewind: null, snapshot: null, confirmed: [], looks: [], raises: [], confirmStarts: [],
    sees: {}, keyframes: {}, logs: {}, wonder: {}, wonderOrder: [], asks: [], answers: {}, checkpoint: null,
    code: {}, codeOrder: [], undos: [], commit: null, replays: {}, attemptTags: [],
    control: { start: null, rendered: {}, scenes: {}, done: null }, clock: { start: null, stop: null },
    seeing: null, stages: [], open: {}, models: [], cost: 0, done: null, loop: null, step: {}, current: null, lastT: null,
  };
}
const see = (tag) => (st.sees[tag] ||= { tag, start: null, named: null, sam: {}, pieces: {}, evidence: null });
const isProof = (tag) => tag === "before" || /^attempt-/.test(tag || "") || /^control-/.test(tag || "");

function on(e) {
  st.lastT = e.t;
  let step = null, follow = true;
  switch (e.type) {
    case "run": st.mode = e.mode; st.run = e; step = "watch"; break;
    case "feed": st.feed = e; step = "watch"; break;
    case "brain.start": st.brainStart = e; step = "watch"; break;
    case "brain.stop": st.brainStop = e; break;
    case "listen": st.listen = e; step = "watch"; break;
    case "key": st.key = e; step = "heard"; break;
    case "said": st.said = e; step = "heard"; break;
    case "read": st.read = e; step = "heard"; break;
    case "rewind": st.rewind = e; step = "watch"; break;
    case "snapshot": st.snapshot = e; step = "watch"; follow = false; break;
    case "look": st.looks.push(e); step = "heard"; follow = false; break;
    case "raise": st.raises.push(e); step = "heard"; break;
    case "confirm.start": st.confirmStarts.push(e); step = "heard"; break;
    case "confirmed": st.confirmed.push(e); step = "heard"; follow = false; break;
    case "see.start": case "named": case "sam.start": case "sam.piece": case "evidence": {
      // SAM's own events carry the role (robot / object), not the look they belong to: that is the open one
      const tag = e.type === "sam.start" || e.type === "sam.piece" ? st.seeing : e.tag;
      if (tag == null) break;
      const v = see(tag);
      if (e.type === "see.start") { v.start = e; st.seeing = tag; }
      else if (e.type === "named") v.named = e;
      else if (e.type === "sam.start") { v.sam[e.concept] = e; v.pieces[e.concept] = new Set(); }
      else if (e.type === "sam.piece") (v.pieces[e.concept] ||= new Set()).add(e.piece);
      else v.evidence = e;
      if (/^control-/.test(tag)) step = null;
      else { step = isProof(tag) ? "proof" : "see"; follow = tag !== "before"; }
      break;
    }
    case "keyframes": st.keyframes[e.tag] = e; step = "cause"; break;
    case "log": st.logs[e.tag] = e; step = "cause"; break;
    case "wonder.start": case "wonder.text": case "wonder.thinking": case "diagnosis": {
      const w = st.wonder[e.tag] ||= { tag: e.tag, start: null, text: "", thinking: "", diagnosis: null };
      if (!st.wonderOrder.includes(e.tag)) st.wonderOrder.push(e.tag);
      if (e.type === "wonder.start") w.start = e;
      else if (e.type === "wonder.text") w.text += e.text;
      else if (e.type === "wonder.thinking") w.thinking += e.text;
      else w.diagnosis = e;
      step = "cause";
      break;
    }
    case "ask": st.asks.push(e); step = e.question === "Fix it?" ? "ask" : "proof"; break;
    case "answer": st.answers[e.id] = e; step = "ask"; follow = false; break;
    case "checkpoint": st.checkpoint = e; step = "fix"; follow = false; break;
    case "musecode.start": case "musecode.tool": case "change": {
      const c = st.code[e.tag] ||= { tag: e.tag, start: null, tools: new Map(), change: null };
      if (!st.codeOrder.includes(e.tag)) st.codeOrder.push(e.tag);
      if (e.type === "musecode.start") c.start = e;
      else if (e.type === "musecode.tool") c.tools.set(e.id, e);
      else c.change = e;
      step = "fix";
      break;
    }
    case "undo": st.undos.push(e); step = "fix"; follow = false; break;
    case "commit": st.commit = e; step = "fix"; follow = false; break;
    case "replay.start": case "replay.rendered": case "verdict": {
      const r = st.replays[e.tag] ||= { tag: e.tag, start: null, rendered: null, verdict: null };
      if (/^attempt-/.test(e.tag) && !st.attemptTags.includes(e.tag)) st.attemptTags.push(e.tag);
      r[{ "replay.start": "start", "replay.rendered": "rendered", verdict: "verdict" }[e.type]] = e;
      step = "proof"; follow = e.tag !== "before";
      break;
    }
    case "control.start": st.control.start = e; step = "proof"; break;
    case "control.rendered": st.control.rendered[e.scene] = e; step = "proof"; break;
    case "control.scene": st.control.scenes[e.scene] = e; step = "proof"; break;
    case "control.done": st.control.done = e; step = "proof"; break;
    case "clock.start": st.clock.start = e; break;
    case "clock.stop": st.clock.stop = e; break;
    case "stage.start": st.open[e.stage] = e; break;
    case "stage": delete st.open[e.stage]; st.stages.push(e); break;
    case "model": st.models.push(e); st.cost += e.cost_usd || 0; break;
    case "loop.start": st.loop = e; break;
    case "done": st.done = e; step = "done"; break;
  }
  if (step) {
    const r = st.step[step] ||= { first: null, last: e.t };
    r.last = e.t;
    if (follow) { st.current = step; if (r.first == null) r.first = e.t; }
  }
  dirty = true;
}

// time on the loop's clock: live, the server's epoch; in a report replay, the replayed moment
function now() {
  if (replaying) return replaying.now();
  if (STATIC) return st.lastT || 0;
  return Date.now() / 1000 + skew;
}
const toEpoch = (x) => (st.feed && st.feed.clock === "brain" ? st.feed.t_start + x : x);
const since = (t) => (t == null ? null : t - (st.clock.start ? st.clock.start.at : st.run ? st.run.t : t));
const pending = () => st.asks.filter((a) => !st.answers[a.id]);

function status(id) {
  if (id === "ask" && pending().some((a) => a.question === "Fix it?")) return "waiting";
  if (id === "proof" && pending().some((a) => a.question !== "Fix it?")) return "waiting";
  const r = st.step[id];
  if (!r || r.first == null) return "idle";      // only background work so far (the safety save, the replay before)
  if (id === "done" && st.done) return st.done.fixed ? "done" : "bad";
  if (st.current === id && !st.done) return "active";
  return "done";
}

// ── persistent media (kept across re-renders so videos keep playing) ───────
const keep = new Map();
function kept(key, make) {
  if (!keep.has(key)) keep.set(key, make());
  return keep.get(key);
}
const pic = (src) => (src ? kept(`img:${src}`, () => h("img", { src, alt: "" })) : null);
let tickers = [];                   // what the shown panel moves on every frame, without a redraw

// A video with SAM 3.1's masks drawn over each frame it shows.
class Player {
  constructor(src, frames) {
    this.frames = frames;                     // frames in the file: frame index = round(t * frames / duration)
    this.video = h("video", { src, muted: true, loop: true, playsinline: true, autoplay: true, preload: "auto" });
    this.video.muted = true;
    this.canvas = h("canvas");
    this.flash = h("div", { class: "flash" });
    this.label = h("span", { class: "label" });
    this.badge = h("span", { class: "badge", hidden: true });
    this.el = h("div", { class: "player" }, this.video, this.canvas, this.flash, this.label, this.badge);
    this.layers = [];
    this.listeners = [];
    this.frame = 0;
    this.hit = null;                          // the contact frame: the edge flashes red there
    this.video.addEventListener("loadedmetadata", () => {
      this.canvas.width = this.video.videoWidth;
      this.canvas.height = this.video.videoHeight;
    });
    const tick = (_, meta) => {
      this.draw(meta.mediaTime);
      this.video.requestVideoFrameCallback(tick);
    };
    this.video.requestVideoFrameCallback(tick);
  }
  set(label, badge, cls) {
    this.label.textContent = label || "";
    this.label.hidden = !label;
    this.badge.hidden = !badge;
    this.badge.textContent = badge || "";
    this.badge.className = `badge ${cls || ""}`;
  }
  mask(path, color) {
    if (!path || this.layers.some((l) => l.path === path)) return;
    const layer = { path, color, t: null, cache: new Map() };
    this.layers.push(layer);
    track(path).then((t) => { layer.t = t; }).catch((e) => console.warn(e));
  }
  index(mt) {
    const d = this.video.duration;
    return this.frames && d ? Math.min(this.frames - 1, Math.round((mt * this.frames) / d)) : Math.round(mt * 30);
  }
  draw(mt) {
    const f = this.index(mt);
    this.frame = f;
    const c = this.canvas.getContext("2d");
    c.clearRect(0, 0, this.canvas.width, this.canvas.height);
    for (const L of this.layers) {
      if (!L.t) continue;
      L.t.frame(f).forEach((m, i) => c.drawImage(tint(L, f, i, m), m.box[0], m.box[1]));
    }
    this.flash.classList.toggle("on", this.hit != null && Math.abs(f - this.hit) <= 2);
    for (const cb of this.listeners) cb(f);
  }
}
function tint(L, f, i, m) {
  const key = `${f}:${i}`;
  if (L.cache.has(key)) return L.cache.get(key);
  const cv = h("canvas"), { w, h: hh, mask } = m;
  cv.width = w; cv.height = hh;
  const ctx = cv.getContext("2d"), img = ctx.createImageData(w, hh), d = img.data;
  const [r, g, b] = L.color;
  for (let y = 0; y < hh; y++) {
    for (let x = 0; x < w; x++) {
      const o = y * w + x;
      if (!mask[o]) continue;
      // a 2-pixel outline, so the mask reads on any colour (the box is violet itself)
      let edge = false;
      for (let k = 1; k <= 2 && !edge; k++)
        edge = x < k || y < k || x >= w - k || y >= hh - k || !mask[o - k] || !mask[o + k] || !mask[o - k * w] || !mask[o + k * w];
      d[4 * o] = r; d[4 * o + 1] = g; d[4 * o + 2] = b; d[4 * o + 3] = edge ? 255 : 80;
    }
  }
  ctx.putImageData(img, 0, 0);
  L.cache.set(key, cv);
  return cv;
}
const ROBOT = [53, 224, 224], OBJECT = [255, 181, 71];

function evidencePlayer(tag) {
  const v = st.sees[tag];
  const ev = v && v.evidence, start = v && v.start;
  const src = (ev && ev.shot) || (start && start.shot);
  if (!src || !url(src)) return null;
  const p = kept(`player:${tag}:${src}`, () => new Player(url(src), (start && start.frames) || (ev && ev.frames)));
  if (ev) {
    p.mask(ev.sam.robot, ROBOT);
    p.mask(ev.sam.object, OBJECT);
    p.hit = ev.first_contact ? ev.first_contact.shot_frame : null;
  }
  return p;
}

// gap (px) between the robot's mask and the object's, over brain time; the contact in red
function chart(series, contact, opts = {}) {
  const W = opts.w || 1400, H = opts.h || 220, L = 58, R = 16, T = 22, B = 30;
  const lines = opts.lines || [{ series, color: "var(--cyan)", contact }];
  const all = lines.flatMap((l) => l.series || []).filter((p) => p[2] != null);
  if (!all.length) return { el: h("div", { class: "wait" }, "waiting for the masks"), at() {} };
  const xs = all.map((p) => p[1]), ys = all.map((p) => p[2]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const top = Math.max(40, Math.ceil(Math.min(Math.max(...ys), 400) / 20) * 20);
  const X = (t) => L + ((t - x0) / (x1 - x0 || 1)) * (W - L - R);
  const Y = (g) => T + (1 - Math.min(g, top) / top) * (H - T - B);
  const svg = s("svg", { class: "plot", viewBox: `0 0 ${W} ${H}` });
  for (let i = 0; i <= 4; i++) {
    const g = (top * i) / 4;
    svg.append(s("line", { class: i ? "grid" : "zero", x1: L, x2: W - R, y1: Y(g), y2: Y(g) }),
      s("text", { x: L - 8, y: Y(g) + 4, "text-anchor": "end" }, i ? Math.round(g) : "0 px"));
  }
  const step = x1 - x0 > 30 ? 10 : x1 - x0 > 12 ? 2 : 1;
  for (let t = Math.ceil(x0 / step) * step; t <= x1; t += step)
    svg.append(s("text", { x: X(t), y: H - 10, "text-anchor": "middle" }, `${t} s`));
  svg.append(s("text", { x: L + 6, y: T - 4, class: "lab" }, opts.title || "gap between robot and object (pixels) · brain time"));
  for (const l of lines) {
    let d = "", pen = false;
    for (const p of l.series || []) {
      if (p[2] == null) { pen = false; continue; }
      d += `${pen ? "L" : "M"}${X(p[1]).toFixed(1)},${Y(p[2]).toFixed(1)}`;
      pen = true;
    }
    svg.append(s("path", { class: "line", d, style: `stroke:${l.color}` }));
    if (l.label) {
      const q = last((l.series || []).filter((p) => p[2] != null));
      if (q) svg.append(s("text", { x: X(q[1]) - 4, y: Y(q[2]) - 8, "text-anchor": "end", style: `fill:${l.color}` }, l.label));
    }
    if (l.contact) {
      const c = l.contact, x = X(c.brain_s);
      svg.append(s("line", { class: "hit", x1: x, x2: x, y1: T, y2: H - B }),
        s("circle", { cx: x, cy: Y(c.gap_px || 0), r: 7, style: "fill:var(--red)" }),
        s("text", { x: x + 10, y: T + 14, class: "red" }, `first contact · ${num(c.brain_s, 2)} s`));
    }
  }
  const play = s("line", { class: "play", x1: -10, x2: -10, y1: T, y2: H - B });
  svg.append(play);
  return {
    el: svg,
    at(t) {
      if (t == null) return;
      const x = X(t);
      play.setAttribute("x1", x);
      play.setAttribute("x2", x);
    },
  };
}

// ── the panels ─────────────────────────────────────────────────────────────
function head(id, aside) {
  const S = STEP[id];
  return h("div", { class: "head" }, h("span", { class: "big-n" }, S.n), h("h1", {}, S.title),
    h("div", { class: "models" }, S.models()), aside ? h("span", { class: "aside" }, aside) : null);
}
const fact = (k, v, cls) => h("div", { class: `fact ${cls || ""}` }, h("span", { class: "k" }, k), h("span", { class: "v" }, v));
const wait = (t) => h("div", { class: "wait" }, h("div", {}, t, h("span", { class: "dots" })));

const P = {};

P.watch = () => {
  const box = h("div", { class: "body watch" });
  let view;
  if (st.snapshot && url(st.snapshot.video)) {
    const p = kept(`snap:${st.snapshot.video}`, () => new Player(url(st.snapshot.video), null));
    p.set(`the window around the moment · ${num(st.snapshot.window[1] - st.snapshot.window[0])} s, saved`);
    view = p.el;
  } else if (st.feed && st.feed.kind === "live" && !STATIC) {
    const img = kept("live", () => h("img", { alt: "" }));
    view = h("div", { class: "player" }, img, h("span", { class: "label" }, "the simulator, live"));
  } else if (st.feed && st.feed.kind === "clip" && url(st.feed.clip)) {
    const p = kept(`clip:${st.feed.clip}`, () => new Player(url(st.feed.clip), st.feed.frames));
    p.video.loop = false;
    p.set("the simulator (a recorded run, played as if live)");
    view = p.el;
  } else view = h("div", { class: "player" }, wait("waiting for the simulator"));
  box.append(view, timeline());
  return [head("watch", st.feed ? `buffer ${st.feed.buffer_s || 60} s` : null), box];
};

let rewound = null;                 // {t: the rewind event's time, at: when its animation started}
function timeline() {
  // the last 60 s up to now; frozen when the person speaks, then rewound to the moment. Redrawn every
  // frame from the clock, so a redraw of the page never cuts the rewind short.
  const marks = h("div"), dot = h("div", { class: "head-dot" });
  const ticks = h("div", { class: "ticks" });
  for (let k = 0; k <= 6; k++) ticks.append(h("span", { style: `left:${(k / 6) * 100}%` }, k === 6 ? "now" : `−${60 - 10 * k} s`));
  const el = h("div", { class: "timeline" }, h("div", { class: "bar" }), ticks, marks, dot);
  const span = 60;
  const draw = () => {
    const end = st.rewind ? toEpoch(st.rewind.release ?? st.rewind.press) : now();
    const start = end - span;
    const pos = (t) => Math.max(0, Math.min(100, ((t - start) / span) * 100));
    const at = (t) => `left:${pos(t)}%`;
    const side = (t) => (pos(t) > 80 ? " end" : pos(t) < 20 ? " start" : "");   // labels stay inside the panel
    const out = [];
    if (st.brainStart && toEpoch(st.brainStart.at) > start) out.push(h("div", { class: `mark${side(toEpoch(st.brainStart.at))}`, style: at(toEpoch(st.brainStart.at)) }, h("span", {}, "robot starts")));
    let x = 100;
    if (st.rewind) {
      const [w0, w1] = st.rewind.window.map(toEpoch), m = toEpoch(st.rewind.moment);
      const press = toEpoch(st.rewind.press), near = Math.abs(pos(press) - pos(m)) < 20;
      const keyword = st.mode === "watch" ? "hand raised" : "key pressed";
      out.push(h("div", { class: "win", style: `left:${pos(w0)}%;width:${pos(w1) - pos(w0)}%` }),
        h("div", { class: "mark key", style: at(press) }, near ? null : h("span", {}, keyword)),
        h("div", { class: `mark moment${side(m)}`, style: at(m) },
          h("span", {}, `the moment · ${num(press - m)} s before the ${st.mode === "watch" ? "hand" : "key"}`)));
      if (!rewound || rewound.t !== st.rewind.t) {
        const recent = replaying || (!STATIC && now() - st.rewind.t < 6);
        rewound = { t: st.rewind.t, at: recent ? performance.now() : -1e9 };
      }
      const k = (performance.now() - rewound.at) / 2000;
      if (k < 1) {
        const e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
        x = 100 + (pos(m) - 100) * e;
      } else {
        const p = st.snapshot && keep.get(`snap:${st.snapshot.video}`);
        x = p && p.video.duration ? pos(w0 + (p.video.currentTime / p.video.duration) * (w1 - w0)) : pos(m);
      }
    } else if (st.raises.length) {
      out.push(h("div", { class: `mark moment${side(toEpoch(last(st.raises).t))}`, style: at(toEpoch(last(st.raises).t)) }, h("span", {}, "hand raised")));
    }
    marks.replaceChildren(...out);
    dot.style.left = `${x}%`;
  };
  draw();
  tickers.push(draw);
  return el;
}

P.heard = () => {
  const box = h("div", { class: "body", style: "align-content:center; gap:1.6rem" });
  if (st.mode === "watch") {
    const looks = h("div", { class: "looks" });
    const raised = new Set(st.raises.map((r) => r.t));
    for (const l of st.looks.slice(-60)) {
      const sign = ["touching", "close", "fallen", "stuck"].some((k) => l[k]);
      looks.append(h("i", { class: raised.has(l.t) ? "raised" : sign ? "sign" : "", title: `${num(l.t)} s` }));
    }
    box.append(h("div", { class: "card" }, h("h3", {}, `Muse Glimmer looks at the screen, on this PC · ${st.looks.length} looks`), looks));
    const r = last(st.raises);
    if (r) box.append(h("div", { class: `quote ${fx("quote@449")}` }, `Something is ${r.signs.join(" and ")} at ${num(r.t)} s`));
    const c = last(st.confirmed), cs = last(st.confirmStarts);
    if (cs) box.append(h("div", { class: `facts ${fx("facts@451")}` },
      fact("SAM 3.1 checks the window", `${num(cs.window[0])}–${num(cs.window[1])} s`),
      c ? fact("confirmed", c.confirmed ? `${c.kind} at ${num(c.incident_s, 2)} s` : "no incident", c.confirmed ? "red" : "") : null));
    if (!st.looks.length) box.append(wait("the watcher has not looked yet"));
    return [head("heard"), box];
  }
  if (!st.said) {
    box.append(h("div", {}, h("div", { class: "mic" }, st.listen ? st.listen.key || "F9" : "mic"),
      h("div", { class: "wait", style: "height:auto" }, st.key ? h("div", {}, "transcribing", h("span", { class: "dots" }))
        : `Hold ${st.listen ? st.listen.key || "F9" : "the key"} and say what you saw`)));
    return [head("heard"), box];
  }
  box.append(h("div", { class: `quote ${fx("quote@463")}` }, st.said.text || "(nothing heard)"));
  const by = String(st.said.heard_by || "");
  box.append(h("div", { class: "facts" },
    fact(by.startsWith("typed") ? "typed" : "Muse Voice heard it", by.startsWith("typed") ? "text input" : `in ${secs(st.said.seconds)}`),
    st.said.audio_s ? fact("speech", secs(st.said.audio_s)) : null));
  if (st.read) {
    const r = st.read;
    box.append(h("div", { class: `facts ${fx("facts@470")}` },
      fact("what", r.event), fact("object", r.object || "–"), fact("robot", r.robot || "–"),
      fact("when", `${num(r.seconds_ago)} s before the key`, "red"),
      fact("read by", `${r.read_by === "glimmer" ? "Muse Glimmer, on this PC" : r.read_by} · ${secs(r.seconds)}`)));
  }
  const c = last(st.confirmed);
  if (c) box.append(h("div", { class: `facts ${fx("facts@476")}` },
    fact("SAM 3.1 confirms", c.confirmed ? `${c.kind} at ${num(c.incident_s, 2)} s` : "nothing there", c.confirmed ? "red" : ""),
    c.names ? fact("in the pixels", c.names.join(" · ")) : null));
  return [head("heard", st.key ? `key held ${num(st.key.release - st.key.press)} s` : null), box];
};

P.see = () => {
  const tags = Object.keys(st.sees).filter((t) => !isProof(t));
  const tag = last(tags);
  if (!tag) return [head("see"), h("div", { class: "body" }, wait("waiting for the snapshot"))];
  const v = st.sees[tag], ev = v.evidence, start = v.start;
  const box = h("div", { class: "body see" });
  const p = evidencePlayer(tag);
  const fc = ev && ev.first_contact;
  if (p) {
    p.set(ev ? "SAM 3.1 masks, every frame" : "the incident shot", fc ? `contact · frame ${fc.shot_frame}` : null, fc ? "hit" : null);
    box.append(p.el);
  } else box.append(h("div", { class: "player" }, wait("cutting the shot")));
  const side = h("div", { class: "side" });
  const named = v.named;
  side.append(h("div", { class: "card" }, h("h3", {}, named ? `named by ${named.named_by === "glimmer" ? "Muse Glimmer, on this PC" : named.named_by}` : "naming the objects"),
    named ? [h("div", { class: `name ${fx("name@497")}` }, h("i", { style: "background:var(--robot)" }), named.robot, h("small", {}, "robot")),
      h("div", { class: `name ${fx("name@498")}` }, h("i", { style: "background:var(--object)" }), named.object, h("small", {}, named.object_is || "object")),
      named.why ? h("div", { class: "mute", style: "font-size:.85rem" }, `renamed: ${named.why}`) : null]
      : wait(start ? `Glimmer looks at ${(start.naming_frames || []).length || "a few"} frames` : "")));
  const pieces = h("div", { class: "pieces" });
  for (const [label, concept] of [["robot", named && named.robot], ["object", named && named.object]]) {
    const sam = concept && v.sam[concept];
    const row = h("div", { class: "row" });
    const n = sam ? sam.pieces : 4, got = (concept && v.pieces[concept]) || new Set();
    for (let i = 0; i < n; i++) row.append(h("i", { class: got.has(i) || ev ? "done" : "", style: `--sam:var(--${label})` }));
    pieces.append(h("span", { class: "mute" }, label), row);
  }
  side.append(h("div", { class: "card" }, h("h3", {}, `SAM 3.1 follows both · ${start ? start.frames : "–"} frames${start ? ` · ${start.size.join("×")}` : ""}`), pieces,
    ev ? h("div", { class: "mute", style: "font-size:.85rem; margin-top:.5rem" },
      `masks in ${ev.frames_with_mask.robot} / ${ev.frames_with_mask.object} frames (robot / object)`) : null));
  if (ev) {
    side.append(fc ? h("div", { class: `card contact ${fx("card.contact@513")}` }, h("h3", {}, "first contact, measured in pixels"),
      h("div", { class: "v" }, `${num(fc.brain_s, 2)} s`),
      h("div", { class: "mute" }, `frame ${fc.shot_frame} · gap ${num(fc.gap_px)} px · ${fc.reading || ""}`))
      : h("div", { class: `card nocontact ${fx("card.nocontact@516")}` }, h("h3", {}, "contact"), h("div", { class: "v" }, "none"),
        h("div", { class: "mute" }, ev.closest ? `closest ${num(ev.closest.gap_px)} px at ${num(ev.closest.brain_s, 2)} s` : "")));
  }
  box.append(side);
  const c = chart(ev ? ev.series : [], fc);
  box.append(h("div", { class: "card chart" }, c.el));
  if (p && start) p.listeners = [(f) => c.at(start.times[f])];
  return [head("see", start ? `${tag} · ${num(start.times[0])}–${num(last(start.times))} s` : null), box];
};

function partial(textSoFar, key) {
  // a string field of JSON that is still arriving
  const m = new RegExp(`"${key}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)`).exec(textSoFar);
  if (!m) return null;
  let raw = m[1].replace(/\\$/, "");
  try { return JSON.parse(`"${raw}"`); } catch { return raw.replace(/\\n/g, "\n").replace(/\\"/g, '"'); }
}

P.cause = () => {
  const tag = last(st.wonderOrder) || last(Object.keys(st.keyframes));
  if (!tag) return [head("cause"), h("div", { class: "body" }, wait("waiting for the evidence"))];
  const w = st.wonder[tag] || {}, d = w.diagnosis, kf = st.keyframes[tag], log = st.logs[tag];
  const box = h("div", { class: "body cause" });
  const story = h("div", { class: "story" });
  if (d) {
    story.append(h("div", { class: "card", style: "flex:none" }, h("h3", {}, "the cause, in plain words"),
      h("div", { class: `explain ${fx("explain@542")}` }, d.explanation)));
  } else {
    const ex = partial(w.text, "explanation"), ob = partial(w.text, "observed"), what = partial(w.text, "what");
    const sw = w.start;
    story.append(h("div", { class: "card", style: "flex:none" },
      h("h3", {}, sw ? `Muse Wonder reads ${sw.key_frames} key frames, ${sw.log_ticks} log ticks and ${sw.files} code files` : "Muse Wonder"),
      ex ? h("div", { class: "explain streaming" }, ex)
        : what ? h("div", { class: "explain streaming" }, what)
          : ob ? h("div", { class: "explain streaming", style: "color:var(--ink2)" }, ob)
            : h("div", { class: "reading" }, (w.thinking || w.text || "").slice(-900) || "thinking…")));
  }
  if (d && d.code) {
    const c = d.code;
    const pre = h("pre", { class: "code" });
    for (const [n, line] of c.lines) pre.append(h("div", { class: n >= c.start && n <= c.end ? "hl" : "" }, h("span", { class: "ln" }, n), line || " "));
    story.append(h("div", { class: `card ${fx("card@557")}`, style: "flex:1" },
      h("h3", {}, "the line it cites"),
      h("div", { class: "where", style: "margin-bottom:.4rem" }, `${c.file} · line${c.end > c.start ? "s" : ""} ${c.start}${c.end > c.start ? "–" + c.end : ""}${d.cause && d.cause.function ? " · " + d.cause.function : ""}`),
      pre));
  } else if (log) {
    story.append(logCard(log, "flex:1"));
  }
  box.append(story);
  // right: the key frame at contact and the log row of that moment
  const k = kf && (kf.frames.find((f) => /contact|fall/.test(f.label || "") && !/before/.test(f.label || "")) || last(kf.frames));
  box.append(k ? h("div", { class: "card keyframe" }, h("h3", {}, `key frame · ${k.label} · ${num(k.brain_s, 2)} s`),
    pic(url(k.image)),
    h("div", { class: "mute", style: "font-size:.88rem" }, k.glimmer ? `Muse Glimmer: “${k.glimmer}”` : ""))
    : h("div", { class: "card" }, wait("choosing key frames")));
  if (d) {
    box.append(h("div", { style: "display:flex; flex-direction:column; gap:1rem; min-height:0" },
      log ? logCard(log, "flex:1", 2, 0) : null,
      h("div", { class: "card conf" }, h("span", {}, "confidence"), h("b", { class: "mono" }, num(d.confidence, 2)),
        h("span", { class: "meterbar" }, h("i", { style: `width:${(d.confidence || 0) * 100}%` })),
        h("span", { class: "mute" }, d.grounded ? "file, lines and evidence checked" : "not grounded"))));
  } else if (log && d == null && w.text) box.append(h("div"));
  const m = d && d.model;
  return [head("cause", m ? `${secs(m.seconds)} · ${usd(m.cost_usd)}` : tag !== "incident" ? tag : null), box];
};

function logCard(log, style, before = 6, after = 2) {
  const rows = log.rows || [];
  let at = 0;
  rows.forEach((r, i) => { if (Math.abs(r[0] - log.moment) < Math.abs(rows[at][0] - log.moment)) at = i; });
  const pre = h("pre", { class: "log" }, h("div", { class: "hd" }, log.head));
  for (const [i, r] of rows.entries()) if (i >= at - before && i <= at + after) pre.append(h("div", { class: i === at ? "hl" : "" }, r[1]));
  return h("div", { class: "card", style }, h("h3", {}, `the robot's own log at ${num(log.moment, 2)} s · ${log.event || ""}`), pre);
}

function askCard(a, big) {
  const ans = st.answers[a.id];
  const ctx = a.question === "Fix it?"
    ? [a.cause, a.file ? h("div", { class: "where", style: "margin-top:.6rem" }, `${a.file} · lines ${a.lines.join("–")} · confidence ${num(a.confidence, 2)}`) : null]
    : [`With the fix: ${a.after}.`, h("br"), `Before it: ${a.before}.`, a.stat ? h("div", { class: "mono mute", style: "margin-top:.5rem; font-size:1rem" }, `${a.stat} · ${(a.files || []).join(", ")}`) : null];
  return h("div", { class: big ? `ask ${fx("ask@" + a.id)}` : "" },
    h("div", { class: "q" }, a.question),
    h("div", { class: "ctx" }, ctx),
    ans ? h("div", { class: `answered ${ans.yes ? "y" : "n"}` }, ans.yes ? "Yes" : "No",
      h("small", {}, `answered in the ${ans.by} · +${num(since(ans.t))} s`))
      : buttons(a));
}
function buttons(a) {
  const local = answering.get(a.id);
  const off = !!STATIC || local != null;
  return h("div", { class: "answer" }, h("div", { class: "btns" },
    h("button", { class: "yes", disabled: off, onclick: () => answer(a.id, true) }, local === true ? "Yes…" : "Yes"),
    h("button", { class: "no", disabled: off, onclick: () => answer(a.id, false) }, local === false ? "No…" : "No")),
    STATIC ? null : h("div", { class: "hint" }, "or y / n in the terminal: whichever comes first"));
}
const answering = new Map();
async function answer(id, yes) {
  answering.set(id, yes);
  dirty = true;
  const r = await fetch("/answer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, yes }) });
  if (!r.ok) { answering.delete(id); dirty = true; }
}

P.ask = () => {
  const box = h("div", { class: "body asks" });
  const asks = st.asks.filter((a) => a.question === "Fix it?");
  if (!asks.length) box.append(wait(st.loop && !st.loop.asked ? "this run fixes on its own: nobody is asked" : "the question comes once the cause is known"));
  else box.append(askCard(last(asks), true));
  return [head("ask", asks.length > 1 ? `attempt ${last(asks).attempt}` : null), box];
};

P.fix = () => {
  const box = h("div", { class: "body fix" });
  const cp = st.checkpoint, u = last(st.undos);
  box.append(h("div", { class: `card save ${u && !st.commit ? "undo" : ""}` },
    h("span", { class: "lock" }, u && !st.commit ? "↺" : "git"),
    cp ? h("div", {}, h("b", {}, "Safety save before any change"), h("br"),
      h("span", { class: "mute" }, "commit "), h("span", { class: "mono" }, cp.commit.slice(0, 10)),
      h("span", { class: "mute" }, ` in ${tilde(cp.target)}${cp.committed_now ? " · saved just now" : " · already clean"} · any failed attempt goes back to it`))
      : h("div", { class: "mute" }, "the safety save comes first"),
    u ? h("div", { style: "margin-left:auto; color:var(--amber)" }, `rolled back to ${u.to.slice(0, 10)}: ${u.why}`) : null,
    st.commit ? h("div", { style: "margin-left:auto; color:var(--green)" }, h("b", {}, "kept · "), h("span", { class: "mono" }, st.commit.commit.slice(0, 10)), ` ${st.commit.subject}`) : null));
  // a tool call reads as the file it touches and the lines, not as its raw arguments
  const brief = (a) => {
    const v = (k) => ((a || "").match(new RegExp(`["']${k}["']\\s*:\\s*["']?([^"',}]+)`)) || [])[1];
    const path = v("path") || v("file_path");
    if (!path) return a || "";
    const off = +v("offset") || 0, lim = +v("limit") || 0;
    return path.replace(/^.*\/duck-target\//, "") + (lim ? ` · lines ${off || 1}–${(off || 1) + lim - 1}` : "");
  };
  const tag = last(st.codeOrder);
  const c = tag && st.code[tag];
  const tools = h("div", { class: "tools" });
  if (c) {
    for (const t of [...c.tools.values()].slice(-16)) {
      const ok = /complete|done|success/i.test(t.status || ""), bad = /fail|error|declin|reject/i.test(t.status || "");
      tools.append(h("div", {}, h("span", { class: `st ${ok ? "ok" : bad ? "bad" : ""}` }, ok ? "✓" : bad ? "✗" : "…"),
        h("span", {}, t.tool || "tool"), h("span", { class: "args" }, brief(t.args))));
    }
    if (!c.tools.size) tools.append(wait("Muse Code reads the diagnosis and the code"));
  }
  box.append(h("div", { class: "card" }, h("h3", {}, c ? `Muse Code at work · ${tag}${c.start && c.start.model ? " · " + c.start.model : ""}` : "Muse Code"),
    c ? tools : wait(st.asks.length ? "waiting for the answer" : "it starts once you say yes")));
  const ch = c && c.change;
  const diff = h("pre", { class: "diff" });
  if (ch) {
    for (const line of (ch.diff || "").split("\n")) {
      if (/^(diff --git|index )/.test(line)) continue;
      const cls = /^(\+\+\+|---)/.test(line) ? "fh" : line[0] === "+" ? "add" : line[0] === "-" ? "del" : line.startsWith("@@") ? "at" : "ctxl";
      diff.append(h("span", { class: cls }, line || " "));
    }
  }
  box.append(h("div", { class: "card" }, h("h3", {}, ch ? `the change · ${ch.stat} · ${secs(ch.seconds)} · ${ch.tool_calls} tool calls${ch.sandbox ? " · sandboxed" : ""}` : "the change"),
    ch ? [h("div", { class: `summary ${fx("summary@660")}` }, String(ch.summary || "").replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")),
      ch.problems && ch.problems.length ? h("div", { style: "color:var(--red); margin-bottom:.5rem" }, `rejected: ${ch.problems.join("; ")}`) : null, diff]
      : wait(c ? "writing" : "")));
  return [head("fix", c && c.start ? `edits only inside ${tilde(st.checkpoint ? st.checkpoint.target : "the target")}` : null), box];
};

function says(v) {
  if (!v) return null;
  if (!v.valid) return "no verdict";
  if (v.kind === "fall") return v.incident ? `falls at ${num(v.fell_s, 2)} s` : "does not fall";
  return v.contact ? `contact at ${num(v.first_contact_s, 2)} s` : `no contact · closest ${num(v.closest_gap_px)} px`;
}

P.proof = () => {
  const box = h("div", { class: "body proof" });
  const atag = last(st.attemptTags);
  const before = st.replays.before, after = atag && st.replays[atag];
  const panes = [];
  for (const [tag, r, label] of [["before", before, "before the fix"], [atag, after, "with the fix"]]) {
    const v = r && r.verdict;
    let p = tag && st.sees[tag] && evidencePlayer(tag);
    if (!p && r && r.rendered && url(r.rendered.video)) p = kept(`twin:${r.rendered.video}`, () => new Player(url(r.rendered.video), null));
    if (p) {
      p.set(`${label}${tag && tag !== "before" ? " · " + tag : ""}`, v ? says(v) : null, v ? (v.incident ? "hit" : "clean") : null);
      panes.push(p);
      box.append(p.el);
    } else box.append(h("div", { class: "player" }, wait(r && r.start ? `the twin replays ${r.start.seconds} s` : tag ? "waiting" : "the replay with the fix comes after Muse Code")));
  }
  // keep the two in step: the one with the fix follows the one before it
  if (panes.length === 2) {
    const [a, b] = panes;
    a.listeners = [() => {
      if (b.video.duration && Math.abs(b.video.currentTime - a.video.currentTime) > 0.08) b.video.currentTime = a.video.currentTime;
      if (b.video.paused) b.video.play().catch(() => {});
    }];
  }
  const vb = before && before.verdict, va = after && after.verdict;
  const keep = last(st.asks.filter((a) => a.question !== "Fix it?" && (!atag || a.attempt === +atag.split("-")[1])));
  const count = (v) => (v ? (v.incident ? 1 : 0) : "?");
  box.append(h("div", { class: "card counter" }, h("h3", {}, vb && vb.kind === "fall" ? "falls" : "contacts"),
    h("div", { class: "n" }, h("span", { class: "a" }, count(vb)), h("span", { class: "arrow" }, "→"), h("span", { class: "b", style: va && va.incident ? "color:var(--red)" : "" }, count(va))),
    h("div", { class: "v" }, va ? (va.valid && !va.incident ? h("b", { style: "color:var(--green)" }, "Fixed: the same scene, no contact.") : h("b", { style: "color:var(--red)" }, "Not fixed yet.")) : "the verdict comes from the pixels, as before",
      va ? h("div", { class: "mute", style: "margin-top:.4rem; font-size:.9rem" }, `robot walked ${num(va.travel_m, 2)} m (before: ${num(vb && vb.travel_m, 2)} m)`) : null),
    keep ? h("div", { class: "keep" }, askCard(keep, false)) : null));
  const lines = [];
  for (const [tag, color, label] of [["before", "var(--red)", "before"], [atag, "var(--green)", "with the fix"]]) {
    const ev = tag && st.sees[tag] && st.sees[tag].evidence;
    if (ev) lines.push({ series: ev.series, color, label, contact: ev.first_contact });
  }
  const c = chart(null, null, { lines, h: 150, title: "gap robot ↔ object (pixels), before and with the fix" });
  box.append(h("div", { class: "card both" }, c.el));
  if (panes[0] && st.sees.before && st.sees.before.start) {
    const t = st.sees.before.start.times;
    panes[0].listeners.push((f) => c.at(t[f]));
  }
  box.append(controls(va));
  return [head("proof", after && after.rendered ? `twin replay ${secs(after.rendered.seconds)}` : null), box];
};

function controls(va) {
  const C = st.control;
  const el = h("div", { class: "controls" },
    h("div", { class: "lead" }, h("b", {}, "Control"), C.start ? "the same brain in every other scene, judged in pixels" : st.done || !va ? "the other scenes come after the verdict" : "waiting"));
  const scenes = ["box", ...((C.start && C.start.scenes) || ["low_cube", "ledge", "corner", "doorway"])];
  for (const sc of scenes) {
    if (sc === "box") {
      el.append(h("div", { class: `scene ${va ? (va.valid && !va.incident ? "clean" : "dirty") : ""}` },
        h("div", { style: "width:5.6rem; height:4.2rem; border-radius:.35rem; display:grid; place-items:center; background:#000; color:var(--mute); font-size:.75rem" }, "the proof"),
        h("div", {}, h("div", { class: "s" }, "box"), h("div", { class: "r" }, va ? says(va) : "the incident's scene"))));
      continue;
    }
    const r = C.scenes[sc], ev = st.sees[`control-${sc}`], img = ev && ev.evidence && url(ev.evidence.image);
    const state = r ? (r.clean ? "clean" : "dirty") : "";
    const what = r ? (r.clean ? `clean${r.closest_gap_px != null ? ` · closest ${num(r.closest_gap_px)} px` : ""}` : r.why || "not clean")
      : ev ? "SAM 3.1 follows" : C.rendered[sc] ? "rendered" : C.start ? "rendering" : "";
    el.append(h("div", { class: `scene ${state}` },
      img ? pic(img) : h("div", { style: "width:5.6rem; height:4.2rem; border-radius:.35rem; background:#000" }),
      h("div", {}, h("div", { class: "s" }, sc.replace("_", " ")), h("div", { class: "r" }, what))));
  }
  return el;
}

P.done = () => {
  const box = h("div", { class: "body finale" });
  const d = st.done;
  const big = h("div", { class: "v" });
  const g = h("div");
  tickers.push(() => {
    const c = st.clock.stop ? st.clock.stop.seconds : st.clock.start ? Math.max(0, now() - st.clock.start.at) : null;
    big.textContent = c == null ? "–" : `${num(c)} s`;
    big.style.color = st.clock.stop ? "" : "var(--cyan)";
    if (Object.keys(st.open).length || !g.firstChild) g.replaceChildren(gantt());
  });
  box.append(h("div", { class: "bigclock" },
    h("div", {}, h("div", { class: "k" }, `seen → fixed and verified${st.clock.start ? ` · from “${st.clock.start.why}”` : ""}`),
      big),
    h("div", { class: "cost" }, h("div", { class: "k" }, "cost of the whole run"), h("div", { class: "v" }, usd(st.cost))),
    d ? h("div", {}, h("div", { class: "k" }, "outcome"),
      h("div", { class: `outcome ${d.fixed ? "ok" : "bad"}` }, d.kept ? `fixed, verified, kept · ${(d.fix_commit || "").slice(0, 10)}` : d.fixed ? "fixed and verified, not kept" : "not fixed"),
      d.stopped ? h("div", { class: "mute" }, d.stopped) : null) : null));
  const rows = manifest(st.models);     // the stream sees every call: the voice, the look, the control
  const tb = h("table", { class: "models" }, h("tr", {}, ["model", "where", "calls", "tokens in / out", "frames", "seconds", "cost"].map((k) => h("th", {}, k))));
  for (const m of rows) tb.append(h("tr", {}, h("td", {}, m.model), h("td", { class: "mute" }, m.where),
    h("td", { class: "num" }, m.calls), h("td", { class: "num" }, m.input_tokens || m.output_tokens ? `${m.input_tokens} / ${m.output_tokens}` : "–"),
    h("td", { class: "num" }, m.frames || "–"), h("td", { class: "num" }, num(m.seconds)), h("td", { class: "num" }, m.cost_usd ? usd(m.cost_usd) : "$0")));
  box.append(h("div", { class: "card" }, h("h3", {}, "every model call, with its cost"), tb));
  box.append(h("div", { class: "card" }, h("h3", {}, "where the time went (from the snapshot)"), g));
  return [head("done", d ? `run took ${secs(d.seconds)}` : null), box];
};

function manifest(calls) {
  const out = new Map();
  for (const c of calls) {
    const m = out.get(c.model) || { model: c.model, where: c.where, calls: 0, input_tokens: 0, output_tokens: 0, frames: 0, cost_usd: 0, seconds: 0 };
    m.calls++; m.seconds += c.seconds || 0; m.cost_usd += c.cost_usd || 0;
    for (const k of ["input_tokens", "output_tokens", "frames"]) m[k] += c[k] || 0;
    out.set(c.model, m);
  }
  return [...out.values()];
}

function gantt() {
  const el = h("div", { class: "gantt" });
  const all = [...st.stages, ...Object.values(st.open).map((o) => ({ stage: o.stage, start: o.start, seconds: Math.max(0, now() - o.t), open: true }))];
  if (!all.length) return wait("no stages yet");
  const end = Math.max(...all.map((x) => x.start + x.seconds), 1);
  for (const x of all.slice(-18)) {
    const cls = /background/.test(x.stage) ? "bg" : /person decides/.test(x.stage) ? "you" : "";
    el.append(h("div", {}, h("span", { class: "nm", title: x.stage }, x.stage),
      h("span", { class: "lane" }, h("i", { class: cls, style: `left:${(x.start / end) * 100}%; width:${Math.max(0.4, (x.seconds / end) * 100)}%` }))));
  }
  return el;
}

// ── drawing ────────────────────────────────────────────────────────────────
function dwell() {
  return shown === "watch" && st.rewind ? 6000 : 2600;
}
function render() {
  const t = performance.now();
  if (!pinned && st.current && st.current !== shown && t - shownAt > dwell()) {
    shown = st.current;
    shownAt = t;
    dirty = true;
  }
  if (!shown) shown = st.current || "watch";
  document.getElementById("mode").textContent = STATIC ? (replaying ? "replay" : "report") : st.mode ? `live · ${st.mode}` : "live";
  document.getElementById("mode").className = `pill ${STATIC ? "" : "live"}`;
  const clock = document.getElementById("clock");
  const c = st.clock.stop ? st.clock.stop.seconds : st.clock.start ? Math.max(0, now() - st.clock.start.at) : null;
  clock.textContent = c == null ? "–" : clockText(c);
  clock.classList.toggle("stopped", !!st.clock.stop);
  document.getElementById("cost").textContent = usd(st.cost);
  if (!dirty) return;
  dirty = false;
  const rail = document.getElementById("rail");
  rail.replaceChildren(...STEPS.map((S, i) => {
    const r = st.step[S.id], stt = status(S.id);
    return h("button", { class: `step ${stt} ${shown === S.id ? "shown" : ""}`, onclick: () => pin(S.id) },
      h("span", { class: "n" }, stt === "done" ? "✓" : i + 1),
      h("div", {}, h("div", { class: "t" }, S.title), h("div", { class: "models" }, S.models()),
        h("div", { class: "result" }, result(S.id))),
      h("span", { class: "when" }, r && r.first != null && st.clock.start ? `${since(r.first) >= 0 ? "+" : ""}${num(since(r.first))} s` : ""));
  }));
  const stage = document.getElementById("stage");
  tickers = [];
  stage.replaceChildren(...P[shown]());
  for (const v of stage.querySelectorAll("video")) if (v.paused && v.autoplay) v.play().catch(() => {});
  const bar = document.getElementById("askbar");
  const open = pending();
  const a = last(open);
  if (a && !(shown === (a.question === "Fix it?" ? "ask" : "proof"))) {
    bar.hidden = false;
    bar.replaceChildren(h("div", { class: "q" }, a.question),
      h("div", { class: "ctx" }, a.question === "Fix it?" ? a.cause : `with the fix: ${a.after} · before: ${a.before}`),
      buttons(a));
  } else bar.hidden = true;
}
function result(id) {
  // one line per step, what it found: readable from the rail alone
  const fc = (tag) => { const v = st.sees[tag]; return v && v.evidence && v.evidence.first_contact; };
  const seeTag = last(Object.keys(st.sees).filter((t) => !isProof(t)));
  const atag = last(st.attemptTags), va = atag && st.replays[atag] && st.replays[atag].verdict;
  const vb = st.replays.before && st.replays.before.verdict;
  const d = st.wonder[last(st.wonderOrder)] && st.wonder[last(st.wonderOrder)].diagnosis;
  const fixQ = last(st.asks.filter((a) => a.question === "Fix it?")), fixA = fixQ && st.answers[fixQ.id];
  const ch = st.codeOrder.length && st.code[last(st.codeOrder)].change;
  const ctl = st.control.scenes, nctl = Object.keys(ctl).length;
  switch (id) {
    case "watch": return st.rewind ? `rewound ${num(toEpoch(st.rewind.press) - toEpoch(st.rewind.moment))} s to the moment` : st.brainStart ? "recording" : "";
    case "heard": return st.said ? `“${st.said.text}”` : st.raises.length ? `${last(st.raises).signs.join(", ")} at ${num(last(st.raises).t)} s` : "";
    case "see": { const v = seeTag && st.sees[seeTag], c = fc(seeTag);
      return v && v.named ? `${v.named.robot} · ${v.named.object}${c ? ` · contact ${num(c.brain_s, 2)} s` : ""}` : ""; }
    case "cause": return d ? `${d.code ? `${d.code.file}:${d.code.start}` : d.cause_key} · ${num(d.confidence, 2)}` : st.wonderOrder.length ? "reading" : "";
    case "ask": return fixA ? `${fixA.yes ? "yes" : "no"} · in the ${fixA.by}` : fixQ ? "waiting for you" : "";
    case "fix": return ch ? `${ch.stat}${st.commit ? " · kept" : st.undos.length ? " · rolled back" : ""}` : st.checkpoint ? `safety save ${st.checkpoint.commit.slice(0, 7)}` : "";
    case "proof": return va ? `contacts ${vb && vb.incident ? 1 : 0} → ${va.incident ? 1 : 0}${nctl ? ` · control ${Object.values(ctl).filter((c) => c.clean).length + (va.valid && !va.incident ? 1 : 0)}/${nctl + 1} clean` : ""}` : "";
    case "done": return st.clock.stop ? `${num(st.clock.stop.seconds)} s · ${usd(st.cost)}` : "";
  }
  return "";
}
function pin(id) {
  pinned = pinned === id ? null : id;
  shown = id;
  shownAt = performance.now();
  dirty = true;
}
function loop() {
  render();
  for (const t of tickers) t();
  requestAnimationFrame(loop);
}
document.addEventListener("keydown", (e) => {
  if (e.key >= "1" && e.key <= "8") pin(STEPS[+e.key - 1].id);
  if (e.key === "f" || e.key === "Escape") { pinned = null; shownAt = 0; dirty = true; }
});

// the live picture of the simulator, from the sidecar, through the console's server
let liveURL = null;
async function poll() {
  if (!STATIC && shown === "watch" && st.feed && st.feed.kind === "live" && !st.snapshot) {
    try {
      const r = await fetch("/sim.jpg", { cache: "no-store" });
      if (r.status === 200) {
        const u = URL.createObjectURL(await r.blob());
        const img = keep.get("live");
        if (img) img.src = u;
        if (liveURL) URL.revokeObjectURL(liveURL);
        liveURL = u;
      }
    } catch (e) { /* the sidecar is busy or gone: the last picture stays */ }
  }
  setTimeout(poll, 160);
}

// ── start ──────────────────────────────────────────────────────────────────
function reset() {
  st = fresh();
  keep.clear();
  shown = null; shownAt = 0; pinned = null; dirty = true;
}
reset();
if (STATIC) {
  for (const e of STATIC.events) on(e);
  shown = st.done ? "done" : st.current;
  const btn = document.getElementById("replay");
  btn.hidden = false;
  btn.onclick = replay;
  document.title = `BlinkFlow report · ${tilde(STATIC.source).split("/").slice(-2, -1)[0] || "run"}`;
} else {
  const es = new EventSource("/events");
  es.addEventListener("stream", (m) => {
    const d = JSON.parse(m.data);
    reset();
    skew = d.now - Date.now() / 1000;
    shownAt = -1e9;
  });
  es.addEventListener("ping", (m) => { skew = +m.data - Date.now() / 1000; });
  es.onmessage = (m) => {
    try { on(JSON.parse(m.data)); } catch (e) { console.warn(e, m.data); }
  };
  poll();
}
requestAnimationFrame(loop);
// for scripts driving the page (screenshots, tests): what is shown and what waits for an answer
window.BLINKFLOW = { state: () => ({ shown, current: st.current, pending: pending().map((a) => a.question), done: !!st.done }), pin };

// a static report replays its run: long waits shortened to `cap` s, the clock still showing the real times
let replays = 0;
function replay() {
  const evs = STATIC.events;
  if (!evs.length) return;
  reset();
  const run = ++replays;                // a second click starts over: the first replay stops feeding events
  const cap = 1.6;
  const plan = [];
  let d = 0;
  evs.forEach((e, i) => { if (i) d += Math.min(cap, Math.max(0, e.t - evs[i - 1].t)); plan.push(d); });
  const t0 = performance.now();
  let i = 0;
  replaying = {
    now() {
      const el = (performance.now() - t0) / 1000;
      if (i >= evs.length) return evs[evs.length - 1].t;
      if (i === 0) return evs[0].t;
      const a = plan[i - 1], b = plan[i], f = b > a ? Math.min(1, (el - a) / (b - a)) : 1;
      return evs[i - 1].t + f * (evs[i].t - evs[i - 1].t);
    },
  };
  const step = () => {
    if (run !== replays) return;
    const el = (performance.now() - t0) / 1000;
    while (i < evs.length && plan[i] <= el) on(evs[i++]);
    if (i < evs.length) setTimeout(step, 50);
    else replaying = null;
  };
  step();
}
})();
