"""The 20 s teaser, made for a phone: the loop once, in order, with large type and a subtitle burned in.

    python3 tools/teaser.py EVENTS [--angle 38] [--out C:/Users/sorin/blinkflow/footage]

EVENTS is a finished run's events.jsonl; every word and number on screen is read from that stream, or,
for the first shot, from the twin's own contact log. The shots:
  1. the first touch, low from behind and to the right, slowed and held (tools/side_shot.py, in the twin)
  2. the sentence, coloured as the console colours it
  3. the console's 60 s bar rewinding to the moment
  4. SAM 3.1's masks, cropped to the picture and enlarged
  5. the cause in three rows
  6. "1 → 0"
Two files: teaser2-16x9-<date>.mp4 (1920x1080) and teaser2-1x1-<date>.mp4 (1080x1080), no sound.
The console is filmed headless in its 1920x1080 layout at twice the pixels (a browser of its own, never the Viser
window); the text shots are cards the console's own page draws with its own styles, sized for the format.
Needs Playwright with Google Chrome (h264) and microduck_rl's interpreter for the twin.
"""
import argparse
import base64
import io
import json
import pathlib
import socket
import subprocess
import sys
import tempfile
import textwrap
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import side_shot  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
FOOTAGE = pathlib.Path("/mnt/c/Users/sorin/blinkflow/footage")
FONT = "/mnt/c/Windows/Fonts/arialbd.ttf"
FPS = 30
BG = (10, 11, 14)                      # the console's --bg
ZOOM = 2                               # the console is filmed at 3840x2160 with the page zoomed 2x: real pixels to crop
# per format: frame, picture area above the subtitle band, subtitle size (px), card type scale
FORMATS = {"16x9": {"size": (1920, 1080), "pic": (1920, 820), "sub": 66, "k": 1.1},
           "1x1": {"size": (1080, 1080), "pic": (1080, 760), "sub": 54, "k": 0.8}}
SHOTS = [("impact", 4.0), ("said", 2.6), ("rewind", 3.2), ("masks", 3.6), ("cause", 3.9), ("result", 2.7)]
FADE = 0.15                            # each shot after the first comes up from the background


def facts(events):
    """What the shots say, from the stream only."""
    last = lambda t: ([e for e in events if e["type"] == t][-1:] or [None])[0]
    ev = next((e for e in reversed(events) if e["type"] == "evidence" and e.get("tag") == "incident"), {})
    said, rew, diag = last("said"), last("rewind"), last("diagnosis") or {}
    code = diag.get("code") or {}
    verdicts = {e.get("tag"): e for e in events if e["type"] == "verdict"}
    after = next((v for k, v in reversed(list(verdicts.items())) if str(k).startswith("attempt")), {})
    return {"contact": (ev.get("first_contact") or {}).get("brain_s"), "names": ev.get("names") or {},
            "said": said and said.get("text"), "typed": said and said.get("heard_by") == "typed",
            "rewound": rew and rew["press"] - rew["moment"], "plain": diag.get("plain") or {},
            "where": code and f"{code.get('file')}:{code.get('start')}",
            "before": 1 if (verdicts.get("before") or {}).get("incident") else 0, "after": 1 if after.get("incident") else 0}


def body_words(body):
    """"ankle_right" -> "right ankle"."""
    w = body.replace("_", " ").split()
    return " ".join(w[1:] + w[:1]) if len(w) == 2 and w[1] in ("left", "right") else " ".join(w)


CARD_CSS = """
#tcard { position: fixed; left: 0; top: 0; z-index: 99999; background: var(--bg); color: var(--ink); box-sizing: border-box;
         display: flex; flex-direction: column; justify-content: center; gap: calc(var(--k) * 14px); padding: 0 calc(var(--k) * 48px); }
#tcard .quote { font-size: calc(var(--k) * 46px); font-weight: 700; line-height: 1.3; }
#tcard .row3 { display: block; }
#tcard .say { padding: calc(var(--k) * 10px) calc(var(--k) * 16px); gap: calc(var(--k) * 16px); }
#tcard .no { flex: 0 0 auto; box-sizing: border-box; padding: 0; line-height: 1; font-size: calc(var(--k) * 20px);
             width: calc(var(--k) * 38px); min-width: calc(var(--k) * 38px); height: calc(var(--k) * 38px); }
#tcard .lab { font-size: calc(var(--k) * 13px); }
#tcard .txt { font-size: calc(var(--k) * 26px); line-height: 1.22; font-weight: 600; }
#tcard .txt .where { font: calc(var(--k) * 20px) var(--mono); color: var(--violet); }
#tcard .big { font: 700 calc(var(--k) * 190px) var(--mono); text-align: center; line-height: 1; }
#tcard .big .a { color: var(--red); } #tcard .big .b { color: var(--green); } #tcard .big .to { color: var(--mute); font-size: .6em; vertical-align: .2em; }
#tcard .small { text-align: center; font-size: calc(var(--k) * 24px); color: var(--ink2); }
"""

CARD_JS = """([kind, w, h, k, d, rows]) => {
  document.getElementById('tcard')?.remove();
  if (!document.getElementById('tcardcss')) {
    const s = document.createElement('style'); s.id = 'tcardcss'; s.textContent = d.css; document.head.append(s);
  }
  const c = document.createElement('div'); c.id = 'tcard';
  c.style.width = w + 'px'; c.style.height = h + 'px'; c.style.setProperty('--k', k);
  if (kind === 'said') {
    const q = document.createElement('div'); q.className = 'quote';
    q.append(...[BLINKFLOW.marked(d.said)].flat()); c.append(q);          // .quote draws its own quotes
  } else if (kind === 'cause') {
    [['saw', 'What the camera saw', d.plain.camera], ['believed', 'What the robot believed', d.plain.robot],
     ['why', 'Why', d.plain.why]].slice(0, rows).forEach(([cls, lab, txt], i) => {
      const r = document.createElement('div'); r.className = 'row3 ' + cls;
      r.innerHTML = `<div class="say"><span class="no">${i + 1}</span><div><div class="lab">${lab}</div><div class="txt"></div></div></div>`;
      const t = r.querySelector('.txt'); t.textContent = txt;
      if (cls === 'why' && d.where) { const s = document.createElement('span'); s.className = 'where'; s.textContent = d.where; t.append(s); }
      c.append(r);
    });
    for (let i = rows; i < 3; i++) { const r = document.createElement('div'); r.className = 'row3'; r.style.visibility = 'hidden';
      r.innerHTML = '<div class="say"><span class="no">0</span><div><div class="lab">x</div><div class="txt">x<br>x</div></div></div>'; c.append(r); }
  } else {
    c.innerHTML = `<div class="small">contacts</div><div class="big"><span class="a">${d.before}</span> <span class="to">→</span> <span class="b">${d.after}</span></div>
      <div class="small">the same scene, the same inputs, replayed with the fix</div>`;
  }
  document.body.append(c);
}"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def film_console(events_path, f, tmp):
    """Cards per format (stills) and the two moving console shots (screencast frames + their crop)."""
    events = [json.loads(line) for line in pathlib.Path(events_path).read_text().splitlines() if line.strip()]
    end = events[-1]["t"]
    rew_t = next(e["t"] for e in events if e["type"] == "snapshot")
    port = free_port()
    server = subprocess.Popen([sys.executable, "-m", "blinkflow.console", "serve", "--port", str(port), "--events",
                               str(events_path)], cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cards, moving = {}, {}
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome", headless=True, args=["--autoplay-policy=no-user-gesture-required",
                                                                          "--hide-scrollbars"])
            pg = b.new_page(viewport={"width": 1920 * ZOOM, "height": 1080 * ZOOM})
            for _ in range(50):
                try:
                    pg.goto(f"http://localhost:{port}/?film=1&script=1")
                    break
                except Exception:
                    time.sleep(0.2)
            pg.wait_for_function("window.BLINKFLOW && window.BLINKFLOW.events()", timeout=20000)
            # the 1920x1080 layout, at twice the pixels: vw/vh do not shrink under zoom, so the page is pinned to 1920x1080
            pg.add_style_tag(content="html { font-size: 16px !important; } body { width: 1920px !important; height: 1080px !important; }")
            pg.evaluate(f"document.documentElement.style.zoom = '{ZOOM}'")
            for step in ("see", "cause", "proof"):      # every video and mask loaded before anything is filmed
                pg.evaluate(f"BLINKFLOW.seek({end}, '{step}')")
                pg.wait_for_timeout(3000)
            d = {"css": CARD_CSS, "said": f["said"], "plain": f["plain"], "where": f["where"],
                 "before": f["before"], "after": f["after"]}
            for name, fm in FORMATS.items():
                w, h = fm["pic"][0] // ZOOM, fm["pic"][1] // ZOOM
                for kind, rows in (("said", 0), ("cause", 1), ("cause", 2), ("cause", 3), ("result", 0)):
                    pg.evaluate(CARD_JS, [kind, w, h, fm["k"], d, rows])
                    pg.wait_for_timeout(150)
                    cards[(name, kind, rows)] = Image.open(io.BytesIO(pg.screenshot(clip={"x": 0, "y": 0, "width": w * ZOOM,
                                                                                          "height": h * ZOOM}))).convert("RGB")
            pg.evaluate("document.getElementById('tcard')?.remove()")
            cdp = pg.context.new_cdp_session(pg)
            frames = []

            def frame(e):
                path = tmp / f"c{len(frames):05d}.jpg"
                path.write_bytes(base64.b64decode(e["data"]))
                frames.append((e["metadata"]["timestamp"], path))
                cdp.send("Page.screencastFrameAck", {"sessionId": e["sessionId"]})

            cdp.on("Page.screencastFrame", frame)
            cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": 1920 * ZOOM,
                                              "maxHeight": 1080 * ZOOM})
            for kind, seconds in SHOTS:
                if kind == "rewind":
                    pg.evaluate(f"BLINKFLOW.seek({rew_t + 0.01}, 'watch')")
                    pick = """() => { const vis = (s) => [...document.querySelectorAll(s)].find((e) => e.offsetParent);
                                      return [vis('.player'), vis('.timeline')]; }"""
                elif kind == "masks":
                    pg.evaluate(f"BLINKFLOW.seek({end}, 'see')")
                    pg.wait_for_function("BLINKFLOW.players().some(k => BLINKFLOW.player(k).slow)", timeout=10000)
                    pg.evaluate("""() => { const p = BLINKFLOW.players().map(k => BLINKFLOW.player(k)).find(p => p.slow);
                                           p.video.currentTime = Math.max(0, p.slow[0] - 75) / 30; p.video.play(); }""")
                    pick = """() => [BLINKFLOW.players().map(k => BLINKFLOW.player(k)).find(p => p.slow).el]"""
                    # the player's corner tags fall outside a phone crop: hidden here, the teaser draws the speed itself
                    pg.add_style_tag(content=".player .label, .player .badge, .player .slow { visibility: hidden !important; }"
                                             " .player .lensbox.r { right: 12% !important; }")
                else:
                    continue
                pg.wait_for_timeout(700)
                rect = pg.evaluate(f"""() => {{ const els = ({pick})();
                    const r = els.map((e) => e.getBoundingClientRect());
                    const x0 = Math.min(...r.map(q => q.left)), y0 = Math.min(...r.map(q => q.top));
                    return [x0, y0, Math.max(...r.map(q => q.right)) - x0, Math.max(...r.map(q => q.bottom)) - y0]; }}""")
                moving[kind] = {"from": time.time(), "rect": rect, "slow": []}   # zoomed: already in the frames' pixels
                until = time.time() + seconds + 0.1
                while time.time() < until:      # when the console plays the clip at quarter speed, as it shows it
                    slow = pg.evaluate("() => BLINKFLOW.players().some(k => !BLINKFLOW.player(k).slowTag.hidden)")
                    moving[kind]["slow"].append((time.time(), slow))
                    pg.wait_for_timeout(50)
            cdp.send("Page.stopScreencast")
            b.close()
    finally:
        server.terminate()
    # the screencast's clock is the wall clock: a frame for any moment of a shot
    for m in moving.values():
        m["frames"] = frames
    return cards, moving


def cover(img, rect, size, anchor=(0.5, 0.5)):
    """The rect of img cut to the size's aspect (where `anchor` says) and scaled to it."""
    x, y, w, h = rect
    a = size[0] / size[1]
    if w / h > a:
        nw = h * a
        x, w = x + (w - nw) * anchor[0], nw
    else:
        nh = w / a
        y, h = y + (h - nh) * anchor[1], nh
    return img.crop((round(x), round(y), round(x + w), round(y + h))).resize(size, Image.LANCZOS)


def tag(img, text, xy, size, anchor, fill=(255, 255, 255)):
    d = ImageDraw.Draw(img, "RGBA")
    font = ImageFont.truetype(FONT, size)
    box = d.textbbox(xy, text, font=font, anchor=anchor)
    pad = size * 0.35
    d.rounded_rectangle((box[0] - pad, box[1] - pad * 0.8, box[2] + pad, box[3] + pad * 0.8), size * 0.25, fill=(0, 0, 0, 165))
    d.text(xy, text, font=font, fill=fill, anchor=anchor)


def subtitle(canvas, text, fm):
    """The band under the picture, the line centred, wrapped to fit."""
    W, H = fm["size"]
    top = fm["pic"][1]
    d = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(FONT, fm["sub"])
    width = max(10, int((W - 100) / (fm["sub"] * 0.55)))
    lines = textwrap.wrap(text, width)
    while any(d.textlength(line, font=font) > W - 90 for line in lines):
        width -= 2
        lines = textwrap.wrap(text, width)
    lh = fm["sub"] * 1.22
    y = top + (H - top - lh * len(lines)) / 2 + lh / 2
    for line in lines:
        d.text((W / 2, y), line, font=font, fill=(255, 255, 255), anchor="mm")
        y += lh


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("events")
    ap.add_argument("--angle", type=float, default=38, help="the impact camera: degrees from behind, towards the right")
    ap.add_argument("--brain", default=str(side_shot.HOME / "duck-target"))
    ap.add_argument("--out", default=str(FOOTAGE))
    a = ap.parse_args()
    events = [json.loads(line) for line in pathlib.Path(a.events).read_text().splitlines() if line.strip()]
    f = facts(events)
    obj = f["names"].get("object", "object")
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="teaser-") as t:
        tmp = pathlib.Path(t)
        # 1. the touch in the twin, from the chosen angle, without labels (the speed is drawn here)
        hit, body, point, heading = side_shot.touch(side_shot.twin(a.brain, tmp / "probe"))
        cam = side_shot.camera(point, heading, a.angle)
        run = side_shot.twin(a.brain, tmp / "impact", cam)
        _, ring = side_shot.clip(run, cam, hit, body, point, tmp / "impact.mp4", plain=True)
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(tmp / "impact.mp4"), "-vf", f"fps={FPS}",
                        str(tmp / "i%04d.png")], check=True)
        impact = sorted(tmp.glob("i*.png"))
        # 2-6. the console
        cards, moving = film_console(a.events, f, tmp)
        stamps = [ts for ts, _ in moving["masks"]["frames"]]
        S = side_shot
        slow_from, hold_from = S.BEFORE, S.BEFORE + S.SLOW_IN * S.SLOW
        slow_to = hold_from + S.HOLD + S.SLOW_OUT * S.SLOW
        subs = {"impact": f"The robot's {body_words(body)} touches the {obj}",
                "said": "You tell it what you saw" if f["typed"] else "You say what you saw",
                "rewind": f"Its last 60 s, rewound {f['rewound']:.1f} s to that moment",
                "masks": "SAM 3.1 follows the robot and the box, every frame",
                "cause": "Muse Wonder finds the cause in the robot's code",
                "result": "Muse Code fixes it; the same scene, replayed"}
        made, stamp = [], time.strftime('%Y%m%d-%H%M')
        for name, fm in FORMATS.items():
            W, H = fm["size"]
            pw, ph = fm["pic"]
            dest = out / f"teaser2-{name}-{stamp}.mp4"
            enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                                    "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
                                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dest)], stdin=subprocess.PIPE)
            shot_i = 0
            for shot_i, (kind, seconds) in enumerate(SHOTS):
                for n in range(round(seconds * FPS)):
                    tau = n / FPS
                    if kind == "impact":
                        src = Image.open(impact[min(n, len(impact) - 1)]).convert("RGB")
                        # the picture's aspect, centred across on the ring, from its bottom edge up
                        rw = 1920 if pw / ph >= 1920 / 1080 else 1080 * pw / ph
                        rh = rw * ph / pw
                        x0 = min(max(ring[0] - rw / 2, 0), 1920 - rw)
                        y0 = min(max(ring[1] - rh * 0.55, 0), 1080 - rh)
                        pic = cover(src, (x0, y0, rw, rh), (pw, ph))
                        k = pw / 1920
                        tag(pic, "replayed in the twin", (round(40 * k + 10), round(40 * k + 10)), round(40 * k + 12), "la")
                        speed = ("paused" if hold_from <= tau < hold_from + S.HOLD else
                                 "¼× speed" if slow_from <= tau < slow_to else None)
                        if speed:
                            tag(pic, speed, (pw - round(40 * k + 10), round(40 * k + 10)), round(48 * k + 14), "ra",
                                fill=(217, 194, 255))
                    elif kind in ("rewind", "masks"):
                        m = moving[kind]
                        at = m["from"] + tau
                        i = int(np.searchsorted(stamps, at))
                        src = Image.open(m["frames"][min(i, len(stamps) - 1)][1]).convert("RGB")
                        pic = cover(src, m["rect"], (pw, ph), (1.0, 1.0) if kind == "rewind" else (0.5, 0.5))
                        now = [v for ts, v in m["slow"] if ts <= at]
                        if now and now[-1]:
                            k = pw / 1920
                            tag(pic, "¼× speed", (pw - round(40 * k + 10), round(40 * k + 10)), round(48 * k + 14), "ra",
                                fill=(217, 194, 255))
                    elif kind == "cause":
                        rows = 1 if tau < 1.0 else 2 if tau < 2.0 else 3
                        pic = cards[(name, "cause", rows)].resize((pw, ph), Image.LANCZOS)
                    else:
                        pic = cards[(name, kind, 0)].resize((pw, ph), Image.LANCZOS)
                    canvas = Image.new("RGB", (W, H), BG)
                    canvas.paste(pic, (0, 0))
                    subtitle(canvas, subs[kind], fm)
                    if shot_i and tau < FADE:
                        canvas = Image.blend(Image.new("RGB", (W, H), BG), canvas, tau / FADE)
                    enc.stdin.write(canvas.tobytes())
            enc.stdin.close()
            enc.wait()
            made.append(str(dest))
    print(json.dumps({"out": made, "seconds": sum(s for _, s in SHOTS), "angle": a.angle, "first_touch_twin_s": hit,
                      "body": body, **{k: v for k, v in f.items() if k != "names"}}))


if __name__ == "__main__":
    main()
