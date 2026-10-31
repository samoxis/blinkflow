// BlinkFlow console: the loop's event stream (blinkflow.events) drawn as eight steps.
// Live: the server sends the stream as server-sent events and the files it names at /file?p=.
// Static report: static.js holds the stream and a map from each named path to its copy beside the page.
"use strict";
(() => {
const STATIC = window.BLINKFLOW_STATIC || null;
const TEXT = window.BLINKFLOW_TEXT;
// ?film=1: made to be filmed (no cursor, no buttons, the three verbs on top, bigger badges, the clock in seconds);
// &speed=N: a finished run replayed at N times its pace; &script=1: the whole run loaded and held still, for a
// script to show (BLINKFLOW.seek / pin)
const Q = new URLSearchParams(location.search);
const FILM = Q.has("film"), SPEED = +Q.get("speed") || null, SCRIPTED = Q.has("script");

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
const BAND = [["voice", "Muse Voice", "listens"], ["glimmer", "Muse Glimmer", "watches, on this PC"],
  ["sam", "SAM 3.1", "follows every object"], ["wonder", "Muse Wonder", "finds the cause"], ["code", "Muse Code", "writes the fix"]];
if (FILM) MODEL.voice[0] = BAND[0][1] = "Muse Voice Transcribe";       // the film names the model in full
// the film's three verbs: say it (the moment and what was seen), fix it (the cause and the change), prove it
const PHASE = { watch: 0, heard: 0, see: 0, cause: 1, ask: 1, fix: 1, proof: 2, done: 2 };
const verbs = FILM ? h("div", { id: "verbs" }, ["say", "fix", "prove"].map((v, i) => [i ? h("i", {}, "·") : null, h("span", { class: "verb" }, `${v} it`)])) : null;
const chip = (m) => h("span", { class: `model m-${m}` }, h("b", {}, MODEL[m][0]), ` · ${MODEL[m][1]}`);
const plain = (t) => h("span", { class: "model plain" }, t);

const STEPS = [
  { id: "watch", title: "The last 60 seconds", models: () => [plain("the screen, kept in a 60 s ring")] },
  { id: "heard", title: "Something went wrong",
    models: () => (st.mode === "watch" ? [chip("glimmer")] : typed() ? [plain("typed by the person")] : [chip("voice")]) },
  { id: "see", title: "See what happened", models: () => [chip("glimmer"), chip("sam")] },
  { id: "cause", title: "Find the cause", models: () => [chip("wonder")] },
  { id: "ask", title: "Fix it?", models: () => [chip("you")] },
  { id: "fix", title: "Write the fix", models: () => [chip("code")] },
  { id: "proof", title: "Prove it: replay", models: () => [chip("sam"), plain("same start, same world, replayed in the twin")] },
  { id: "done", title: "Fixed and verified", models: () => [plain("the real clock and the bill")] },
];
const STEP = Object.fromEntries(STEPS.map((x, i) => [x.id, { ...x, n: i + 1 }]));

// ── state, built from events ───────────────────────────────────────────────
let st, skew = 0, shown = null, shownAt = 0, pinned = null, dirty = true, drawn = null;
let replaying = null;               // static report: the replay in progress
function fresh() {
  return {
    mode: null, run: null, feed: null, brainStart: null, brainStop: null, listen: null, key: null, said: null,
    read: null, rewind: null, snapshot: null, confirmed: [], looks: [], raises: [], confirmStarts: [],
    sees: {}, keyframes: {}, logs: {}, wonder: {}, wonderOrder: [], asks: [], answers: {}, checkpoint: null,
    code: {}, codeOrder: [], undos: [], commit: null, replays: {}, attemptTags: [],
    control: { start: null, rendered: {}, scenes: {}, done: null }, clock: { start: null, stop: null },
    seeing: null, stages: [], open: {}, models: [], cost: 0, done: null, loop: null, step: {}, current: null, lastT: null,
    brainClock: null, vram: null,
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
    case "brain.clock": st.brainClock = e; break;
    case "glimmer.vram": st.vram = e; break;
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
    case "musecode.start": case "musecode.gate": case "musecode.tool": case "musecode.blocked": case "change": {
      const c = st.code[e.tag] ||= { tag: e.tag, start: null, tools: new Map(), change: null };
      if (!st.codeOrder.includes(e.tag)) st.codeOrder.push(e.tag);
      if (e.type === "musecode.start") c.start = e;
      else if (e.type === "musecode.gate") c.gate = e;
      else if (e.type === "musecode.tool") c.tools.set(e.id, e);
      else if (e.type === "musecode.blocked") c.tools.set(`blocked-${e.id}`, { ...e, status: "blocked" });
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
  if (STATIC || EVENTS) return st.lastT || 0;      // a finished run: its last moment
  return Date.now() / 1000 + skew;
}
const toEpoch = (x) => (st.feed && st.feed.clock === "brain" ? st.feed.t_start + x : x);
const pending = () => st.asks.filter((a) => !st.answers[a.id]);
const typed = () => !!(st.key && st.key.typed) || String((st.said && st.said.heard_by) || "").startsWith("typed");

// The clock counts the machine's time only. The person's share is the time a "Fix it?" waits for an answer
// while no machine work is left (the replay before any change runs beside the first one), as blinkflow.fix
// counts it; "Keep the fix?" comes after the clock has stopped.
function held(upTo) {
  const b = st.replays.before;
  const busy = b && b.verdict ? b.verdict.t : b && b.start ? Infinity : -Infinity;
  let s = 0;
  for (const a of st.asks) {
    if (a.question !== "Fix it?") continue;
    const ans = st.answers[a.id];
    s += Math.max(0, Math.min(ans ? ans.t : now(), upTo) - Math.max(a.t, busy));
  }
  return s;
}
function clockNow() {
  const a = st.clock.start, b = st.clock.stop;
  if (!a) return null;
  if (b) return b.person_s != null ? b.seconds : b.at - a.at - held(b.at);   // older streams: worked out here
  return Math.max(0, now() - a.at - held(now()));
}
const since = (t) => (t == null ? null : t - (st.clock.start ? st.clock.start.at : st.run ? st.run.t : t) - held(t));
const tookFor = (a) => { const ans = st.answers[a.id]; return ans ? ans.seconds ?? ans.t - a.t : null; };

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
// one frame of a rendered video, as a picture: a scene the twin has rendered, before SAM's evidence lands
const still = (src) => kept(`still:${src}`, () => h("video", { src: `${src}#t=3`, muted: true, preload: "auto", playsinline: true, class: "still" }));
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
    this.slowTag = h("span", { class: "slow", hidden: true }, "0.25× speed");
    this.el.append(this.slowTag);
    this.layers = [];
    this.listeners = [];
    this.frame = 0;
    this.hit = null;                          // the contact frame: the edge flashes red there
    this.crop = null;                         // [x1, y1, x2, y2], video pixels: the part that fills the pane
    this.span = null;                         // [first, last] frame played in a loop
    this.slow = null;                         // [first, last] frame played at quarter speed
    this.lens = null;                         // {x, y, r}, video pixels: the spot the magnifier shows
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
    const d = this.video.duration;
    if (this.span && d && (f < this.span[0] - 1 || f > this.span[1])) this.video.currentTime = (this.span[0] * d) / this.frames;
    if (this.slow) {
      const r = f >= this.slow[0] && f <= this.slow[1] ? 0.25 : 1;
      if (this.video.playbackRate !== r) this.video.playbackRate = r;
      this.slowTag.hidden = r === 1;
    }
    this.fit();
    if (this.lens) this.magnify(f);
    for (const cb of this.listeners) cb(f);
  }
  // the crop fills the pane: widened to the pane's shape, kept inside the picture, no bars
  fit() {
    const v = this.video, vw = v.videoWidth, vh = v.videoHeight;
    if (!this.crop || !vw) return;
    const W = this.el.clientWidth, H = this.el.clientHeight;
    if (!W || !H) return;
    let [x1, y1, x2, y2] = this.crop, cw = x2 - x1, ch = y2 - y1;
    const A = W / H;
    if (cw / ch < A) cw = ch * A; else ch = cw / A;
    if (cw > vw) { cw = vw; ch = cw / A; }
    if (ch > vh) { ch = vh; cw = ch * A; }
    const x = Math.max(0, Math.min(vw - cw, (x1 + x2) / 2 - cw / 2)), y = Math.max(0, Math.min(vh - ch, (y1 + y2) / 2 - ch / 2));
    const k = W / cw;
    this.view = { x, y, cw, ch };
    const css = `position:absolute; max-width:none; max-height:none; object-fit:fill; left:${-x * k}px; top:${-y * k}px; width:${vw * k}px; height:${vh * k}px`;
    if (this.fitted !== css) { v.style.cssText = css; this.canvas.style.cssText = css; this.fitted = css; }
  }
  // the magnifier: the spot around the first touch, from the same frame and the same masks
  magnify(f) {
    if (!this.inset) {
      this.inset = h("canvas", { class: "lens" });
      this.inset.width = this.inset.height = 360;
      this.lensBox = h("div", { class: "lensbox" }, this.inset, h("span", {}, "magnified · where they touch"));
      this.el.append(this.lensBox);
    }
    const { x, y, r } = this.lens, c = this.inset.getContext("2d"), n = this.inset.width;
    c.clearRect(0, 0, n, n);
    try {
      c.drawImage(this.video, x - r, y - r, 2 * r, 2 * r, 0, 0, n, n);
      c.drawImage(this.canvas, x - r, y - r, 2 * r, 2 * r, 0, 0, n, n);
    } catch (e) { return; }
    const on = this.hit != null && Math.abs(f - this.hit) <= 2;
    c.strokeStyle = on ? "#ff4d5e" : "rgba(255,255,255,.75)";
    c.lineWidth = on ? 6 : 2;
    c.beginPath(); c.arc(n / 2, n / 2, n * 0.16, 0, 2 * Math.PI); c.stroke();
    this.lensBox.classList.toggle("on", on);
    // the inset sits in the corner away from the touch, never over it
    const v = this.view || { x: 0, y: 0, cw: this.video.videoWidth || 1, ch: this.video.videoHeight || 1 };
    this.lensBox.classList.toggle("r", (x - v.x) / v.cw < 0.5);
    this.lensBox.classList.toggle("t", (y - v.y) / v.ch > 0.5);
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

// Where the robot touches the object at the first contact, from SAM 3.1's masks of that frame: the closest
// pair of edge pixels between the robot's lowest fifth ("down" from the object's faces, as see.py measures
// it) and the object that was measured. {x, y} in video pixels, or null.
const touches = new Map();
function touchPoint(ev) {
  const key = ev.sam.robot;
  if (!touches.has(key)) touches.set(key, Promise.all([track(ev.sam.robot), track(ev.sam.object)]).then(([R, O]) => {
    const f = ev.first_contact.shot_frame, [dy, dx] = (ev.base && ev.base.down) || [1, 0];
    const ob = ev.object_box;
    const near = (m) => !ob || (Math.min(m.box[2], ob[2]) > Math.max(m.box[0], ob[0]) && Math.min(m.box[3], ob[3]) > Math.max(m.box[1], ob[1]));
    const edge = (ms) => {
      const out = [];
      for (const m of ms) for (let y = 0; y < m.h; y++) for (let x = 0; x < m.w; x++) {
        const o = y * m.w + x;
        if (m.mask[o] && (x === 0 || y === 0 || x === m.w - 1 || y === m.h - 1 || !m.mask[o - 1] || !m.mask[o + 1] || !m.mask[o - m.w] || !m.mask[o + m.w]))
          out.push([m.box[0] + x, m.box[1] + y]);
      }
      return out;
    };
    let r = edge(R.frame(f));
    const o = edge(O.frame(f).filter(near));
    if (!r.length || !o.length) return null;
    const depth = (p) => p[0] * dx + p[1] * dy, lo = Math.max(...r.map(depth)), hi = Math.min(...r.map(depth));
    const feet = r.filter((p) => depth(p) >= lo - 0.2 * (lo - hi));
    if (feet.length) r = feet;
    const thin = (a, n) => a.filter((_, i) => i % Math.ceil(a.length / n) === 0);
    let best = null;
    for (const a of thin(r, 700)) for (const b of thin(o, 1500)) {
      const d = (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2;
      if (!best || d < best[0]) best = [d, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    }
    return best && { x: best[1], y: best[2] };
  }).catch(() => null));
  return touches.get(key);
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
  } else if (savedFeed()) {
    view = kept(`snap:${savedFeed().video}`, () => new Player(url(savedFeed().video), null)).el;
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

// A finished run replayed: the live picture was never kept, but the seconds saved around the moment were.
// They stand in for the feed, played where the replayed clock is (held on their first or last frame outside
// them), and follow the rewind back to the moment.
const savedFeed = () => (replaying && st.feed && st.feed.kind === "live" && EVENTS
  ? EVENTS.find((e) => e.type === "snapshot" && e.t0_epoch != null && url(e.video)) || null : null);
function scrub(p, snap, at, k) {
  const v = p.video, d = v.duration;
  v.autoplay = false;
  if (!d) return;
  const clamp = (t) => Math.max(0, Math.min(d - 0.05, t));
  if (k != null && k >= 1) {                // rewound: the window from the moment, in a loop, at its own pace
    if (!p.rewound) {
      p.rewound = true;
      v.loop = true;
      v.playbackRate = 1;
      v.currentTime = clamp(toEpoch(st.rewind.moment) - snap.t0_epoch);
      v.play().catch(() => {});
    }
    return;
  }
  p.rewound = false;
  v.loop = false;
  const t = at - snap.t0_epoch, inside = t >= 0 && t < d;
  if (k != null || !inside) {               // the rewind sweeping back, or a moment the clip does not hold
    if (!v.paused) v.pause();
    if (!v.seeking && Math.abs(v.currentTime - clamp(t)) > 0.04) v.currentTime = clamp(t);
  } else {
    const rate = SPEED || 1;
    if (v.playbackRate !== rate) v.playbackRate = rate;
    if (!v.seeking && Math.abs(v.currentTime - t) > 0.3 * rate) v.currentTime = t;
    if (v.paused) v.play().catch(() => {});
  }
  if (!st.snapshot) p.set(t < 0 ? `the simulator · this run's saved seconds start in ${num(-t, 0)} s`
    : "the simulator · this run's saved seconds, replayed");
}
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
    let x = 100, k = null;
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
      k = (performance.now() - rewound.at) / 2000;
      if (k < 1) {
        const e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
        x = 100 + (pos(m) - 100) * e;
      } else {
        const p = st.snapshot && keep.get(`snap:${st.snapshot.video}`);
        const t0 = st.snapshot && st.snapshot.t0_epoch;        // the clip's first frame, when the stream says
        x = !p || !p.video.duration ? pos(m)
          : pos(t0 ? toEpoch(t0) + p.video.currentTime : w0 + (p.video.currentTime / p.video.duration) * (w1 - w0));
      }
    } else if (st.raises.length) {
      out.push(h("div", { class: `mark moment${side(toEpoch(last(st.raises).t))}`, style: at(toEpoch(last(st.raises).t)) }, h("span", {}, "hand raised")));
    }
    marks.replaceChildren(...out);
    dot.style.left = `${x}%`;
    const snap = savedFeed(), sp = snap && keep.get(`snap:${snap.video}`);
    if (sp) scrub(sp, snap, start + (x / 100) * span, k);
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
      h("div", { class: "wait", style: "height:auto" }, st.key ? h("div", {}, typed() ? "reading" : "transcribing", h("span", { class: "dots" }))
        : st.listen && st.listen.typed ? "Press Enter and type what you saw" : `Hold ${st.listen ? st.listen.key || "F9" : "the key"} and say what you saw`)),
      ...keyLine());
    return [head("heard"), box];
  }
  const r = st.read;
  if (!typed() && st.said.audio && url(st.said.audio)) box.append(wave(st.said));
  box.append(...keyLine());
  box.append(h("div", { class: `quote ${fx("quote@463")}` }, marked(st.said.text || "(nothing heard)", r)));
  if (r) {
    const part = (cls, k, v) => h("div", { class: `fact part ${cls}` }, h("span", { class: "k" }, k), h("span", { class: "v" }, v));
    box.append(h("div", { class: `facts ${fx("facts@470")}` },
      part("moment", "when", `${num(r.seconds_ago)} s before the key`), part("robot", "robot", r.robot || "–"),
      part("event", "what happened", r.event), part("object", "object", r.object || "–"),
      fact("read by", `${r.read_by === "glimmer" ? "Muse Glimmer, on this PC" : r.read_by} · ${secs(r.seconds)}`)));
    const bridge = bridgeLine(r);
    if (bridge) box.append(bridge);
  }
  const c = last(st.confirmed);
  if (c) box.append(h("div", { class: `facts ${fx("facts@476")}` },
    fact("SAM 3.1 confirms", c.confirmed ? `${c.kind} at ${num(c.incident_s, 2)} s` : "nothing there", c.confirmed ? "red" : ""),
    c.names ? fact("in the pixels", c.names.join(" · ")) : null));
  // typed: the step's own line already says "typed by the person"; only the voice gets a badge
  const badge = typed() ? null : h("span", { class: "said-by voice" }, `heard by ${MODEL.voice[0]} in ${secs(st.said.seconds)}`);
  return [head("heard", badge), box];
};
// film: the key and the microphone the stream names (voice live writes the device into its listen event;
// older streams have none, and no chip); none, or one line to append. A glasses tap is the key event's own
// trigger; anything else is the held key
const tapped = () => !!(st.key && st.key.trigger === "glasses-tap");
function keyLine() {
  if (!FILM || typed() || (st.listen && st.listen.typed)) return [];
  const mic = st.listen && st.listen.mic;
  return [h("div", { class: "keyline" }, tapped() ? h("span", {}, h("b", {}, "tap the glasses"), " · Ray-Ban Meta")
    : h("span", {}, h("b", {}, (st.listen && st.listen.key) || "F9"), " · hold and speak"),
    mic ? h("span", { title: mic }, "mic: ", h("b", {}, /RB Meta/i.test(mic) ? "Ray-Ban Meta glasses" : mic)) : null)];
}

// The sentence's own words, coloured by what was read from them: the moment, the robot, what happened, the
// object. Only words that are there are coloured; the facts below say what the reader took from them.
const NUMS = "\\d+(?:\\.\\d+)?|a|one|two|three|four|five|six|seven|eight|nine|ten|half a|a couple of|a few";
const PARTS = [
  ["moment", () => new RegExp(`\\b(?:just now|a (?:moment|second) ago|(?:about |around |roughly |maybe )?(?:${NUMS})\\s+(?:seconds?|secs?)\\s+ago)\\b`, "gi")],
  ["object", (r) => r && r.object ? new RegExp(`\\b(?:the |a |that )?${r.object.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "gi") : null],
  // and the words the reader took as the robot, so "she" or "it" is coloured when that is what it read
  ["robot", (r) => new RegExp(String.raw`\b(?:(?:its|the|his|her|their)\s+)?(?:(?:left|right|front|back)\s+)?(?:legs?|foot|feet|knee|arm|head|body|side|hip|ankle|robot|duck)\b` +
    (r && r.robot ? String.raw`|\b${r.robot.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\b` : ""), "gi")],
  ["event", () => /\b(?:hit|hits|touched|touches|touch|bumped|bumps|brushed|scraped|clipped|knocked|ran into|walked into|collided with|fell off|fell|falls|tripped|got stuck|stuck)\b/gi],
];
function marked(text, r) {
  if (!r) return text;
  const taken = new Array(text.length).fill(null);
  for (const [cls, make] of PARTS) {
    const re = make(r);
    if (!re) continue;
    for (const m of text.matchAll(re)) {
      const a = m.index, b = a + m[0].length;
      if (taken.slice(a, b).some((x) => x)) continue;
      taken.fill(cls, a, b);
    }
  }
  const out = [];
  for (let i = 0; i < text.length;) {
    let j = i;
    while (j < text.length && taken[j] === taken[i]) j++;
    out.push(taken[i] ? h("span", { class: `part ${taken[i]}` }, text.slice(i, j)) : text.slice(i, j));
    i = j;
  }
  return out;
}
// the key on the robot's own clock, minus the delay said, is the moment: one line of arithmetic
let brainT0 = null;
function bridgeLine(r) {
  const k = st.key, live = st.feed && st.feed.clock !== "brain";
  let t0 = !live ? 0 : st.brainClock ? st.brainClock.start : brainT0;
  if (live && t0 == null && st.snapshot && !bridgeLine.asked) {
    bridgeLine.asked = true;          // a stream from before brain.clock: the snapshot has the brain's start
    text(st.snapshot.snapshot).then((t) => { brainT0 = JSON.parse(t).brain_start ?? null; dirty = true; }).catch(() => {});
  }
  if (!k || t0 == null) return null;
  const said = (String(st.said.text || "").match(PARTS[0][1]()) || [])[0] || `${num(r.seconds_ago)} s ago`;
  const c = last(st.confirmed);
  return h("div", { class: `bridge ${fx("bridge")}` },
    h("span", {}, "key at ", h("b", {}, `${num(k.press - t0, 2)} s`)), h("span", { class: "op" }, "−"),
    h("span", { class: "part moment" }, `“${said}”`), h("span", { class: "op" }, "="),
    h("b", {}, `${num(r.moment - t0, 2)} s`), h("span", { class: "mute" }, "on the robot's clock"),
    c && c.confirmed ? h("span", { class: "then" }, `→ SAM 3.1 finds the first ${c.kind} at `, h("b", {}, `${num(c.incident_s, 2)} s`)) : null);
}
// the recording, drawn from the file Muse Voice heard
function wave(said) {
  const cv = kept(`wave:${said.audio}`, () => {
    const c = h("canvas", { class: "wave" });
    c.width = 1600; c.height = 140;
    fetch(url(said.audio)).then((r) => r.arrayBuffer()).then((b) => new AudioContext().decodeAudioData(b)).then((a) => {
      const d = a.getChannelData(0), g = c.getContext("2d"), n = c.width, step = Math.ceil(d.length / n);
      g.fillStyle = getComputedStyle(document.body).getPropertyValue("--m-voice");
      for (let i = 0; i < n; i++) {
        let m = 0;
        for (let j = i * step; j < Math.min(d.length, (i + 1) * step); j++) m = Math.max(m, Math.abs(d[j]));
        const hh = Math.max(2, m * c.height * 0.95);
        g.fillRect(i, (c.height - hh) / 2, 1, hh);
      }
    }).catch((e) => console.warn("wave", e));
    return c;
  });
  return h("div", { class: "wavebox" }, cv, h("span", { class: "mute" }, `${secs(said.audio_s)} of speech · ${tapped() ? "between taps" : "held"} ${secs(st.key ? st.key.release - st.key.press : null)}`));
}

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
    if (fc) {
      p.slow = [fc.shot_frame - 12, fc.shot_frame + 8];         // the touch itself, at quarter speed
      if (!p.lens && !p.lensAsked) {
        p.lensAsked = true;
        touchPoint(ev).then((pt) => { if (pt) p.lens = { ...pt, r: 70 }; });
      }
    }
    box.append(p.el);
  } else box.append(h("div", { class: "player" }, wait("cutting the shot")));
  const side = h("div", { class: "side" });
  const named = v.named;
  if (FILM && named && named.named_by === "glimmer") {     // the film's badge: the names came from this PC
    const quant = (st.vram && st.vram.quantization) || (STATIC && STATIC.glimmer_quantization);
    side.append(h("div", { class: `card glimmer-pc ${fx("glimmer-pc")}` }, h("b", {}, "Muse Glimmer"), h("span", { class: "pc" }, "on this PC"),
      h("small", {}, `open weights · local GPU${quant ? ` · ${quant}` : ""}${st.vram && st.vram.vram_gb ? ` · ${num(st.vram.vram_gb)} GB VRAM` : ""}`)));
  }
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
  const m = d && d.model;
  const aside = m ? `${secs(m.seconds)} · ${usd(m.cost_usd)}` : tag !== "incident" ? tag : null;
  const k = kf && (kf.frames.find((f) => /contact|fall/.test(f.label || "") && !/before/.test(f.label || "")) || last(kf.frames));
  if (!d) {
    const box = h("div", { class: "body cause" });
    const ex = partial(w.text, "explanation"), ob = partial(w.text, "observed"), what = partial(w.text, "what");
    const sw = w.start;
    box.append(h("div", { class: "story" }, h("div", { class: "card", style: "flex:none" },
      h("h3", {}, sw ? `Muse Wonder reads ${sw.key_frames} key frames, ${sw.log_ticks} log ticks and ${sw.files} code files` : "Muse Wonder"),
      ex ? h("div", { class: "explain streaming" }, ex)
        : what ? h("div", { class: "explain streaming" }, what)
          : ob ? h("div", { class: "explain streaming", style: "color:var(--ink2)" }, ob)
            : h("div", { class: "reading" }, (w.thinking || w.text || "").slice(-900) || "thinking…")),
      log ? logCard(log, "flex:1") : null));
    box.append(k ? h("div", { class: "card keyframe" }, h("h3", {}, `key frame · ${k.label} · ${num(k.brain_s, 2)} s`), pic(url(k.image)))
      : h("div", { class: "card" }, wait("choosing key frames")));
    return [head("cause", aside), box];
  }
  // three plain rows, each beside the evidence it rests on: the key frame, the log row, the code line
  const first = (x) => String(x || "").split(/(?<=[.;:])\s/)[0].replace(/[:;]$/, ".");
  const pl = d.plain || { camera: first(d.observed), robot: first((d.evidence || []).find((e) => e.source === "log")?.shows),
    why: first(d.cause && d.cause.what) };
  const c = d.code;
  const where = c ? `${c.file}:${c.start}${c.end > c.start ? "–" + c.end : ""}` : d.cause ? `${d.cause.file}:${d.cause.lines.start}` : "";
  const code = c && h("pre", { class: "code" }, c.lines.filter(([n]) => n >= c.start - 1 && n <= c.end + 1)
    .map(([n, line]) => h("div", { class: n >= c.start && n <= c.end ? "hl" : "" }, h("span", { class: "ln" }, n), line || " ")));
  // film: each row's source, checked as diagnose.check() checks it: the key frames cited are ones that were sent,
  // the log ticks cited exist (the stream's "grounded"), the lines named are in the target's file
  const refs = (d.evidence || []).filter((e) => e.source !== "code");
  const sent = new Set((kf ? kf.frames : []).map((f) => f.tag));
  const kcited = [...new Set(refs.flatMap((e) => e.ref.match(/K\d+/g) || []))].filter((t) => sent.has(t));
  const lcited = refs.filter((e) => e.source === "log").map((e) => e.ref.replace(/^brain log\s*/, ""));
  const inFile = !!c && Array.from({ length: c.end - c.start + 1 }, (_, i) => c.start + i).every((n) => c.lines.some(([m]) => m === n));
  const chk = (ok, what) => (FILM ? h("div", { class: `chk ${ok ? "ok" : "no"}` }, ok ? `✓ source checked · ${what}` : "source not checked") : null);
  const rows = [
    ["saw", "What the camera saw", [pl.camera, chk(kcited.length, `key frame${kcited.length > 1 ? "s" : ""} ${kcited.join(", ")}`)], k ? h("div", { class: "ev keyframe" }, pic(url(k.image)),
      h("span", { class: "cap" }, `key frame · ${k.label} · ${num(k.brain_s, 2)} s`)) : null],
    ["believed", "What the robot believed", [pl.robot, chk(d.grounded, lcited.length ? `log ${lcited[0]}` : "log ticks")], log ? h("div", { class: "ev" }, logRows(log, 2, 0),
      h("span", { class: "cap" }, `the robot's own log at ${num(log.moment, 2)} s`)) : null],
    ["why", "Why", [pl.why, h("span", { class: "where" }, where), chk(inFile, `the line is in the target's ${c && c.file}`)], code ? h("div", { class: "ev" }, code,
      h("span", { class: "cap" }, `${where}${d.cause && d.cause.function ? " · " + d.cause.function : ""}`)) : null],
  ];
  const box = h("div", { class: "body cause3" });
  rows.forEach(([cls, label, said, ev], i) => box.append(h("div", { class: `row3 ${cls} ${fx("row3@" + cls)}`, style: `animation-delay:${i * 0.25}s` },
    h("div", { class: "say" }, h("span", { class: "no" }, i + 1), h("div", {}, h("div", { class: "lab" }, label), h("div", { class: "txt" }, said))),
    h("div", { class: "link" }), ev || h("div", { class: "ev" }))));
  // the confidence is the number Muse Wonder gives itself; the three citations are BlinkFlow's checks above
  const checked = [kcited.length > 0, !!d.grounded, inFile].filter(Boolean).length;
  box.append(h("div", { class: "tech" }, `Muse Wonder's own confidence ${num(d.confidence, 2)} · citations checked ${checked}/3`,
    m ? ` · Muse Wonder ${secs(m.seconds)}, ${m.input_tokens} tokens in (${m.cached_input_tokens || 0} cached), ${m.output_tokens} out, ${usd(m.cost_usd)}` : "",
    h("details", {}, h("summary", {}, "the full explanation"), d.explanation)));
  return [head("cause", aside), box];
};

function logRows(log, before, after) {
  const rows = log.rows || [];
  let at = 0;
  rows.forEach((r, i) => { if (Math.abs(r[0] - log.moment) < Math.abs(rows[at][0] - log.moment)) at = i; });
  const pre = h("pre", { class: "log" }, h("div", { class: "hd" }, log.head));
  for (const [i, r] of rows.entries()) if (i >= at - before && i <= at + after) pre.append(h("div", { class: i === at ? "hl" : "" }, r[1]));
  return pre;
}
function logCard(log, style, before = 6, after = 2) {
  return h("div", { class: "card", style }, h("h3", {}, `the robot's own log at ${num(log.moment, 2)} s · ${log.event || ""}`), logRows(log, before, after));
}

function askCard(a, big) {
  const ans = st.answers[a.id];
  const ctx = a.question === "Fix it?"
    ? [a.cause, a.file ? h("div", { class: "where", style: "margin-top:.6rem" }, `${a.file} · ${a.lines[0] === a.lines[1] ? `line ${a.lines[0]}` : `lines ${a.lines.join("–")}`} · Muse Wonder's own confidence ${num(a.confidence, 2)}`) : null]
    : [`With the fix: ${a.after}.`, h("br"), `Before it: ${a.before}.`, a.stat ? h("div", { class: "mono mute", style: "margin-top:.5rem; font-size:1rem" }, `${a.stat} · ${(a.files || []).join(", ")}`) : null];
  return h("div", { class: big ? `ask ${fx("ask@" + a.id)}` : "" },
    h("div", { class: "q" }, a.question),
    h("div", { class: "ctx" }, ctx),
    ans ? h("div", { class: `answered ${ans.yes ? "y" : "n"}` }, ans.yes ? "Yes" : "No",
      h("small", {}, `in the ${ans.by} · you took ${secs(tookFor(a))} to answer, not on the clock`))
      : buttons(a));
}
function buttons(a) {
  const local = answering.get(a.id);
  const off = !!STATIC || !!EVENTS || local != null;
  return h("div", { class: "answer" }, h("div", { class: "btns" },
    h("button", { class: "yes", disabled: off, onclick: () => answer(a.id, true) }, local === true ? "Yes…" : "Yes"),
    h("button", { class: "no", disabled: off, onclick: () => answer(a.id, false) }, local === false ? "No…" : "No")),
    STATIC || EVENTS ? null : h("div", { class: "hint" }, "or y / n in the terminal: whichever comes first"));
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
    cp ? h("div", {}, h("b", {}, FILM ? "Safety copy saved" : "Safety save before any change"), h("br"),
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
      const ok = /complete|done|success/i.test(t.status || ""), bad = /fail|error|declin|reject|block/i.test(t.status || "");
      tools.append(h("div", {}, h("span", { class: `st ${ok ? "ok" : bad ? "bad" : ""}` }, ok ? "✓" : bad ? "✗" : "…"),
        h("span", {}, t.tool || "tool"),
        h("span", { class: "args" }, t.reason ? `blocked before it ran: ${t.reason}` : brief(t.args))));
    }
    if (!c.tools.size) tools.append(wait("Muse Code reads the diagnosis and the code"));
    // film: BlinkFlow's gate asks before every tool call; shown only when the stream says which hook was loaded
    const blocked = [...c.tools.values()].filter((t) => t.status === "blocked").length;
    if (FILM && c.gate) tools.append(h("div", { class: `gatebadge ${blocked ? "hit" : ""}`, title: `${c.gate.hook} sha256 ${c.gate.hook_sha256}` }, h("b", {}, "gate: target folder only"),
      ` · ${c.tools.size} call${c.tools.size === 1 ? "" : "s"} checked · ${blocked} blocked`));
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
    ch ? [oneLine(ch.diff), h("div", { class: `summary ${fx("summary@660")}` }, String(ch.summary || "").replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")),
      ch.problems && ch.problems.length ? h("div", { style: "color:var(--red); margin-bottom:.5rem" }, `rejected: ${ch.problems.join("; ")}`) : null, diff]
      : wait(c ? "writing" : "")));
  return [head("fix", c && c.start ? `edits only inside ${tilde(st.checkpoint ? st.checkpoint.target : "the target")}` : null), box];
};

// film: a change of one `key = value` line, read from the diff as file:line · key · old → new (else nothing)
function oneLine(diff) {
  if (!FILM) return null;
  const file = ((diff || "").match(/^\+\+\+ b\/(.+)$/m) || [])[1];
  let n = 0, del = [], add = [];
  for (const line of (diff || "").split("\n")) {
    const at = line.match(/^@@ -\d+(?:,\d+)? \+(\d+)/);
    if (at) { n = +at[1]; continue; }
    if (!n || /^(\+\+\+|---)/.test(line)) continue;
    if (line[0] === "-") del.push(line.slice(1));
    else if (line[0] === "+") add.push([n++, line.slice(1)]);
    else if (line[0] !== "\\") n++;
  }
  const kv = (l) => l.match(/^\s*([\w.]+)\s*=\s*(.+?)\s*(?:#.*)?$/);
  const a = del.length === 1 && kv(del[0]), b = add.length === 1 && kv(add[0][1]);
  if (!file || !a || !b || a[1] !== b[1]) return null;
  return h("div", { class: `oneline ${fx("oneline")}` }, h("span", { class: "where" }, `${file}:${add[0][0]}`), ` · ${b[1]} · `,
    h("span", { class: "was" }, a[2]), h("span", { class: "arrow" }, " → "), h("span", { class: "now" }, b[2]));
}

function says(v) {
  if (!v) return null;
  if (!v.valid) return "no verdict";
  if (v.kind === "fall") return v.incident ? `falls at ${num(v.fell_s, 2)} s` : "does not fall";
  return v.contact ? `contact at ${num(v.first_contact_s, 2)} s` : `no contact · closest ${num(v.closest_gap_px, 0)} px`;
}

P.proof = () => {
  const box = h("div", { class: "body proof" });
  const atag = last(st.attemptTags);
  const before = st.replays.before, after = atag && st.replays[atag];
  const vb = before && before.verdict, va = after && after.verdict;
  const fall = (vb && vb.kind === "fall") || (va && va.kind === "fall");
  const panes = [];
  for (const [tag, r, side] of [["before", before, "before"], [atag, after, "after"]]) {
    const v = r && r.verdict;
    const p = tag && st.sees[tag] && evidencePlayer(tag);
    const label = side === "before"
      ? (v ? `BEFORE · ${v.incident ? (fall ? `falls at ${num(v.fell_s, 2)} s` : `1 contact at ${num(v.first_contact_s, 2)} s`) : says(v)}` : "BEFORE")
      : (v ? (v.valid && !v.incident ? `FIXED · ${fall ? "no fall" : `no contact · closest ${num(v.closest_gap_px, 0)} px`}` : `WITH THE FIX · ${says(v)}`) : "WITH THE FIX");
    const good = side === "after" && v && v.valid && !v.incident;
    const pane = h("div", { class: `pane ${side} ${v ? (good ? "good" : v.incident ? "bad" : "") : ""}` }, h("div", { class: "tag" }, label));
    if (p) {
      p.set(null, null);
      pane.append(p.el);
      panes.push([p, tag]);
    } else pane.append(h("div", { class: "player" }, wait(r && r.start ? `the twin replays ${num(r.start.seconds)} s of the scene` : tag ? "SAM 3.1 follows" : "the replay with the fix comes after Muse Code")));
    box.append(pane);
  }
  if (panes.length === 2) frame(panes[0], panes[1]);
  const keep = last(st.asks.filter((a) => a.question !== "Fix it?" && (!atag || a.attempt === +atag.split("-")[1])));
  const count = (v) => (v ? (v.incident ? 1 : 0) : "?");
  box.append(h("div", { class: "card counter" }, h("h3", {}, fall ? "falls" : "contacts"),
    h("div", { class: "n" }, h("span", { class: "a" }, count(vb)), h("span", { class: "arrow" }, "→"), h("span", { class: "b", style: va && va.incident ? "color:var(--red)" : "" }, count(va))),
    h("div", { class: "v" }, va ? (va.valid && !va.incident ? h("b", { style: "color:var(--green)" }, `Fixed: the same scene, no ${fall ? "fall" : "contact"}.`) : h("b", { style: "color:var(--red)" }, "Not fixed yet.")) : "the verdict comes from the pixels, as before",
      va ? h("div", { class: "mute", style: "margin-top:.4rem; font-size:.9rem" }, `same start, same world, replayed in the twin · robot walked ${num(va.travel_m, 2)} m (before: ${num(vb && vb.travel_m, 2)} m)`) : null),
    keep ? h("div", { class: "keep" }, askCard(keep, false)) : null));
  box.append(controls(va, atag));
  return [head("proof", after && after.rendered ? `twin replay ${secs(after.rendered.seconds)}` : null), box];
};

// Both replays framed on the robot and the object, the same crop (same camera), looped over the seconds
// around the contact, the one with the fix kept on the same brain time as the one before it.
const framed = new Map();
function frame([a, ta], [b, tb]) {
  const A = st.sees[ta], B = st.sees[tb];
  if (!A.evidence || !B.evidence || !A.start || !B.start) return;
  const key = `${ta}|${tb}`;
  if (!framed.has(key)) framed.set(key, Promise.all([A, B].flatMap((v) => [track(v.evidence.sam.robot), track(v.evidence.sam.object)])).then(([ra, oa, rb, ob]) => {
    const ea = A.evidence, at = (ea.first_contact || ea.closest || {}).brain_s;
    if (at == null) return null;
    const ta_ = A.start.times, tb_ = B.start.times;
    const near = (times, t) => times.reduce((k, x, i) => (Math.abs(x - t) < Math.abs(times[k] - t) ? i : k), 0);
    // from just before the contact until the fixed robot has been in the shot for 2 s (a fix that slows
    // the robot down brings it into the picture later, on the same brain clock), 1.5 to 4 s after it
    const seenB = tb_.findIndex((x, g) => x >= at - 1 && rb.frame(g).length);
    const until = seenB < 0 ? at + 1.5 : Math.min(at + 4, Math.max(at + 1.5, tb_[seenB] + 2));
    const f0 = near(ta_, at - 1), f1 = near(ta_, until);
    let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
    const grow = (ms) => { for (const m of ms) { x1 = Math.min(x1, m.box[0]); y1 = Math.min(y1, m.box[1]); x2 = Math.max(x2, m.box[2]); y2 = Math.max(y2, m.box[3]); } };
    for (let f = f0; f <= f1; f += 3) {
      grow(ra.frame(f)); grow(oa.frame(f).filter((m) => !ea.object_box || overlaps(m.box, ea.object_box)));
      const g = near(tb_, ta_[f]);
      grow(rb.frame(g)); grow(ob.frame(g).filter((m) => !B.evidence.object_box || overlaps(m.box, B.evidence.object_box)));
    }
    if (!isFinite(x1)) return null;
    const px = 0.08 * (x2 - x1), py = 0.08 * (y2 - y1);
    return { crop: [x1 - px, y1 - py, x2 + px, y2 + py], span: [f0, f1] };
  }).catch(() => null));
  framed.get(key).then((fr) => {
    const ta_ = A.start.times, tb_ = B.start.times;
    if (fr) a.crop = b.crop = fr.crop;
    const [t0, t1] = fr ? [ta_[fr.span[0]], ta_[fr.span[1]]] : [Math.min(ta_[0], tb_[0]), Math.max(ta_[ta_.length - 1], tb_[tb_.length - 1])];
    if (!synced.has(key)) synced.set(key, new Sync([[a, ta_], [b, tb_]], t0, t1));
  });
  tickers.push(() => { const s = synced.get(key); if (s) s.tick(); });
}

// Replays on one scene clock: brain seconds [t0, t1], looped. Each video plays by itself and is steered
// toward the clock by its speed; it is seeked only when far off, because the twin's shots have a keyframe
// every ~9 s and every seek decodes up to that much video. A shot that ends before the clock holds its
// last frame. At t1 all go back to t0, wait until each has its frame, and start again together; the clock
// waits for a video that is still loading.
const synced = new Map();
class Sync {
  constructor(players, t0, t1) {
    this.ps = players.map(([p, times]) => ({ p, times }));
    this.t0 = t0; this.t1 = t1; this.T = t0;
    this.last = null; this.restart = true;
    for (const { p } of this.ps) { p.video.loop = false; p.video.pause(); p.span = null; }
  }
  // the video time that shows brain time T in this shot, or null past its last frame
  at({ p, times }, T) {
    const d = p.video.duration;
    if (!d || !times.length) return 0;
    if (T > times[times.length - 1]) return null;
    let i = 0;
    for (let k = 0; k < times.length; k++) if (Math.abs(times[k] - T) < Math.abs(times[i] - T)) i = k;
    return ((i + 0.5) * d) / p.frames;
  }
  tick() {
    const now = performance.now(), dt = this.last == null ? 0 : (now - this.last) / 1000;
    this.last = now;
    const v = (x) => x.p.video;
    if (this.ps.some((x) => !v(x).duration)) return;
    if (this.restart) {                               // seek every shot to t0 once, start when all have it
      if (!this.seeking) {
        this.T = this.t0;
        for (const x of this.ps) { v(x).pause(); v(x).playbackRate = 1; v(x).currentTime = this.at(x, this.T) ?? v(x).duration; }
        this.seeking = true;
      }
      if (this.ps.some((x) => v(x).seeking || v(x).readyState < 3)) return;
      this.seeking = false; this.restart = false;
      for (const x of this.ps) if (this.at(x, this.T) != null) v(x).play().catch(() => {});
      return;
    }
    const live = this.ps.filter((x) => this.at(x, this.T) != null);
    if (!live.some((x) => v(x).seeking || v(x).readyState < 3)) this.T += Math.min(dt, 0.1);
    if (this.T >= this.t1) { this.restart = true; return; }
    for (const x of this.ps) {
      const want = this.at(x, this.T), vid = v(x);
      if (want == null) {                             // this shot has ended: hold its last frame
        if (!vid.paused) vid.pause();
        continue;
      }
      if (vid.paused && !vid.seeking) vid.play().catch(() => {});
      const off = vid.currentTime - want;
      if (Math.abs(off) > 1 && !vid.seeking) vid.currentTime = want;
      else vid.playbackRate = Math.min(1.5, Math.max(0.5, 1 - off));
    }
  }
}
const overlaps = (p, q) => Math.min(p[2], q[2]) > Math.max(p[0], q[0]) && Math.min(p[3], q[3]) > Math.max(p[1], q[1]);

// A control scene without a verdict (the robot or the object not found) is neither clean nor dirty: not measured.
// Older logs carry no "valid", only the reason.
const unmeasured = (r) => r && !r.clean && (r.valid === false || /^no verdict|not found|robot found in only|robot walked/.test(r.why || ""));

// A clean scene says which reading decided it, as prove.contact_of picks it from the scene's evidence: with the
// object's base found, a touch at the base; else the whole masks. The closest gap is the whole masks' on screen,
// so 2 px "in view" next to a base that was never touched is the base's call, not a near miss.
function cleanLine(r, e) {
  const gap = r.closest_gap_px != null ? `closest ${num(r.closest_gap_px, 0)} px` : "";
  if (gap && e && e.base) return `clean · ${gap} in view · no touch at the base`;
  return `clean${gap ? ` · ${gap}` : ""}`;
}

function controls(va, atag) {
  const C = st.control;
  const all = ["box", ...((C.start && C.start.scenes) || [])];
  const clean = (va && va.valid && !va.incident ? 1 : 0) + Object.values(C.scenes).filter((c) => c.clean).length;
  const open = Object.values(C.scenes).filter(unmeasured).length;
  const el = h("div", { class: "controls" },
    C.done ? h("div", { class: `banner ${clean === all.length ? "good" : clean + open === all.length ? "" : "bad"} ${fx("banner")}` }, "Same fix, other scenes",
      h("b", {}, `${clean}/${all.length} clean`), open ? h("span", { class: "mute" }, `${open} not measured`) : "")
      : h("div", { class: "lead" }, h("b", {}, "Same fix, other scenes"), C.start ? "the same brain in every other scene, judged in pixels" : st.done || !va ? "they come after the verdict" : "waiting"));
  const scenes = ["box", ...((C.start && C.start.scenes) || ["low_cube", "ledge", "corner", "doorway"])];
  for (const sc of scenes) {
    if (sc === "box") {
      const ev = atag && st.sees[atag], img = ev && ev.evidence && url(ev.evidence.image);
      el.append(h("div", { class: `scene ${va ? (va.valid && !va.incident ? "clean" : "dirty") : ""}` },
        img ? pic(img) : h("div", { style: "width:5.6rem; height:4.2rem; border-radius:.35rem; display:grid; place-items:center; background:#000; color:var(--mute); font-size:.75rem" }, "the proof"),
        h("div", {}, h("div", { class: "s" }, "box"), h("div", { class: "r" }, va ? says(va) : "the incident's scene"))));
      continue;
    }
    const r = C.scenes[sc], ev = st.sees[`control-${sc}`], img = ev && ev.evidence && url(ev.evidence.image);
    const state = r ? (r.clean ? "clean" : unmeasured(r) ? "unmeasured" : "dirty") : "";
    const what = r ? (r.clean ? cleanLine(r, ev && ev.evidence)
      : unmeasured(r) ? `not measured · ${r.why}` : r.why || "not clean")
      : ev ? "SAM 3.1 follows" : C.rendered[sc] ? "rendered" : C.start ? "rendering" : "";
    const shot = C.rendered[sc] && url(C.rendered[sc].video);
    el.append(h("div", { class: `scene ${state}` },
      img ? pic(img) : shot ? still(shot) : h("div", { style: "width:5.6rem; height:4.2rem; border-radius:.35rem; background:#000" }),
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
    const c = clockNow();
    big.textContent = c == null ? "–" : `${num(c)} s`;
    big.style.color = st.clock.stop ? "" : "var(--cyan)";
    if (Object.keys(st.open).length || !g.firstChild) g.replaceChildren(gantt());
  });
  const answered = st.asks.filter((a) => st.answers[a.id]);
  box.append(h("div", { class: "bigclock" },
    h("div", {}, h("div", { class: "k" }, "seen → fixed and verified · the machine's time"), big,
      answered.length ? h("div", { class: "you" }, answered.map((a) => `you took ${secs(tookFor(a))} to answer “${a.question}”`).join(" · "), ", not on the clock") : null),
    FILM ? h("div", { class: "cost" }, h("div", { class: "k" }, "what it cost · every model call"), h("div", { class: "v" }, usd(st.cost))) : null,
    d ? h("div", {}, h("div", { class: "k" }, "outcome"),
      h("div", { class: `outcome ${d.fixed ? "ok" : "bad"}` }, d.kept ? `fixed, verified, kept · ${(d.fix_commit || "").slice(0, 10)}` : d.fixed ? "fixed and verified, not kept" : "not fixed"),
      d.stopped ? h("div", { class: "mute" }, d.stopped) : null) : null));
  // where the work ran, from the model calls the stream saw
  const local = st.models.filter((m) => m.where === "local"), cloud = st.models.filter((m) => m.where !== "local");
  const billed = local.reduce((x, m) => x + (m.cost_usd || 0), 0);
  const names = [];
  for (const m of cloud) { const n = friendly(m); if (!names.includes(n)) names.push(n); }
  const quant = (st.vram && st.vram.quantization) || (STATIC && STATIC.glimmer_quantization);
  const mine = [...new Set(local.map(friendly))].map((n) => n === "Muse Glimmer" && quant ? `${n} ${quant}` : n);
  box.append(h("div", { class: "where2" },
    h("div", { class: "pc" }, h("span", { class: "k" }, "On this PC"),
      h("span", {}, `${mine.join(", ") || "Muse Glimmer"}${st.vram && st.vram.vram_gb ? `, ${num(st.vram.vram_gb)} GB VRAM` : ""}, `,
        h("b", {}, billed === 0 ? "0 tokens billed" : `${usd(billed)} billed`), ".")),
    h("div", { class: "cloud" }, h("span", { class: "k" }, "In the cloud"),
      h("span", {}, names.join(", ") || "–", " · ", h("b", {}, usd(cloud.reduce((x, m) => x + (m.cost_usd || 0), 0)))))));
  const rows = manifest(st.models);     // the stream sees every call: the voice, the look, the control
  const tb = h("table", { class: "models" }, h("tr", {}, ["model", "where", "calls", "tokens in / out", "frames", "seconds", "cost"].map((k) => h("th", {}, k))));
  for (const m of rows) tb.append(h("tr", {}, h("td", {}, m.model), h("td", { class: "mute" }, m.where),
    h("td", { class: "num" }, m.calls), h("td", { class: "num" }, m.input_tokens || m.output_tokens ? `${m.input_tokens} / ${m.output_tokens}` : "–"),
    h("td", { class: "num" }, m.frames || "–"), h("td", { class: "num" }, num(m.seconds)), h("td", { class: "num" }, m.cost_usd ? usd(m.cost_usd) : "$0")));
  box.append(h("div", { class: "card small" }, h("h3", {}, "every model call, with its cost"), tb));
  box.append(h("div", { class: "card small" }, h("h3", {}, "where the time went (from the snapshot)"), g));
  return [head("done", d ? `run took ${secs(d.seconds)} in all` : null), box];
};
function friendly(m) {
  if (/Muse Code/.test(m.where || "")) return "Muse Code";
  return { "sam-3.1": "SAM 3.1", "muse-wonder-1.0": "Muse Wonder", "muse-spark-1.3": "Muse Spark", "muse-spark-open-1026": "Muse Spark Open", "muse-glimmer": "Muse Glimmer",
    "muse-voice-transcribe-1.0": "Muse Voice" }[m.model] || m.model;
}

function manifest(calls) {
  const out = new Map();
  for (const c of calls) {
    const key = `${c.model}|${c.where}`;     // a cached SAM reply is a row of its own, at $0
    const m = out.get(key) || { model: c.model, where: c.where, calls: 0, input_tokens: 0, output_tokens: 0, frames: 0, cost_usd: 0, seconds: 0 };
    m.calls++; m.seconds += c.seconds || 0; m.cost_usd += c.cost_usd || 0;
    for (const k of ["input_tokens", "output_tokens", "frames"]) m[k] += c[k] || 0;
    out.set(key, m);
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
  const fromFile = STATIC || SCRIPTED || SPEED;
  document.getElementById("mode").textContent = SPEED ? `replay · ${SPEED}×` : fromFile ? (replaying ? "replay" : "report") : st.mode ? `live · ${st.mode}` : "live";
  document.getElementById("mode").className = `pill ${fromFile ? "" : "live"} ${SPEED ? "speed" : ""}`;
  const clock = document.getElementById("clock");
  const c = clockNow();
  clock.textContent = c == null ? "–" : FILM ? `${num(c)} s` : clockText(c);     // the film says the seconds aloud
  clock.classList.toggle("stopped", !!st.clock.stop);
  const answered = st.asks.filter((a) => st.answers[a.id] && a.question === "Fix it?");
  document.getElementById("youm").hidden = !answered.length;
  document.getElementById("you").textContent = answered.map((a) => secs(tookFor(a))).join(" + ");
  document.getElementById("cost").textContent = usd(st.cost);
  document.getElementById("privacy").hidden = st.mode !== "watch";
  if (verbs) {                           // lit from the moment something is said (or seen by the watcher)
    const p = st.key || st.said || st.raises.length ? PHASE[shown] : -1;
    verbs.querySelectorAll(".verb").forEach((v, i) => { v.classList.toggle("on", i === p); v.classList.toggle("past", i < p); });
  }
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
  if (shown !== drawn) {                 // a new step fades in; a redraw of the same one does not
    drawn = shown;
    stage.animate([{ opacity: 0, transform: "translateY(.6rem)" }, { opacity: 1, transform: "none" }], { duration: 500, easing: "ease-out" });
  }
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
    case "cause": return d ? `${d.code ? `${d.code.file}:${d.code.start}` : d.cause_key} · own confidence ${num(d.confidence, 2)}` : st.wonderOrder.length ? "reading" : "";
    case "ask": return fixA ? `${fixA.yes ? "yes" : "no"} · in the ${fixA.by}` : fixQ ? "waiting for you" : "";
    case "fix": return ch ? `${ch.stat}${st.commit ? " · kept" : st.undos.length ? " · rolled back" : ""}` : st.checkpoint ? `safety save ${st.checkpoint.commit.slice(0, 7)}` : "";
    case "proof": return va ? `contacts ${vb && vb.incident ? 1 : 0} → ${va.incident ? 1 : 0}${nctl ? ` · control ${Object.values(ctl).filter((c) => c.clean).length + (va.valid && !va.incident ? 1 : 0)}/${nctl + 1} clean` : ""}${
      Object.values(ctl).some(unmeasured) ? `, ${Object.values(ctl).filter(unmeasured).length} not measured` : ""}` : "";
    case "done": return st.clock.stop ? `${num(clockNow())} s machine time · ${usd(st.cost)}` : "";
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
document.getElementById("band").prepend(...BAND.map(([m, name, what]) => h("span", { class: `model m-${m}` }, h("b", {}, name), ` · ${what}`)));
if (FILM) document.body.classList.add("film");
if (verbs) document.querySelector("#top .right").prepend(verbs);
let EVENTS = STATIC ? STATIC.events : null;
if (STATIC) {
  for (const e of STATIC.events) on(e);
  shown = st.done ? "done" : st.current;
  const btn = document.getElementById("replay");
  btn.hidden = FILM;
  btn.onclick = () => replay();
  document.title = `BlinkFlow report · ${tilde(STATIC.source).split("/").slice(-2, -1)[0] || "run"}`;
  if (SPEED) replay(SPEED);
} else if (SPEED || SCRIPTED) {
  // a finished run from the server, replayed at SPEED times its pace, or loaded whole for a script
  fetch("/events.json").then((r) => r.json()).then((evs) => {
    EVENTS = evs;
    if (SPEED) replay(SPEED);
    else { for (const e of evs) on(e); shown = st.done ? "done" : st.current; }
  });
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
window.BLINKFLOW = {
  state: () => ({ shown, current: st.current, pending: pending().map((a) => a.question), done: !!st.done }), pin,
  // the run as it stood at stream time t, held still (the rewind and the fades start from there)
  seek(t, id) {
    reset();
    for (const e of EVENTS || []) if (e.t <= t) on(e);
    replaying = { now: () => t };
    if (id) pin(id);
  },
  events: () => EVENTS,
  marked: (text) => marked(text, st.read),          // the sentence coloured as the heard step colours it
  player: (key) => keep.get(key),
  players: () => [...keep.entries()].filter(([, v]) => v instanceof Player).map(([k]) => k),
};

// A finished run replayed: at `speed` times its pace (on screen as "N×"), or, from the report's button,
// with long waits shortened to `cap` s; the clocks always show the real times.
let replays = 0;
function replay(speed) {
  const evs = EVENTS;
  if (!evs || !evs.length) return;
  reset();
  const run = ++replays;                // a second click starts over: the first replay stops feeding events
  const cap = 1.6;
  const plan = [];
  let d = 0;
  evs.forEach((e, i) => {
    const dt = i ? Math.max(0, e.t - evs[i - 1].t) : 0;
    d += speed ? dt / speed : Math.min(cap, dt);
    plan.push(d);
  });
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
