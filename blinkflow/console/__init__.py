"""BlinkFlow's console: the loop, live, step by step, in a browser (made to be filmed at 1920x1080).

It only reads the loop's event stream (blinkflow.events: events.jsonl in the run folder) and the files
the stream names; the loop runs the same without it. The one thing it writes is a person's answer to
"Fix it?" or "Keep the fix?", to answers.jsonl beside the stream; the terminal's answer is as good.

    python3 -m blinkflow.console serve [--port 8777] [--events PATH]   # default: follow the newest run
    python3 -m blinkflow.console serve --film [--speed 4] [--events PATH]   # full screen on Windows, to film
    python3 -m blinkflow.console report [EVENTS] [--out DIR]           # the same page, static, from a run

A static report is a folder: the same page, the stream embedded, and every file it shows copied in.
A stream may name its files relative to its own folder ("./fix/models.json"), as the packed examples do.
Never served or copied, whatever the stream names: the simulator's contact logs, the twin's own record
(truth.json, contacts.csv) and scene files.
"""
import argparse
import http.server
import json
import mimetypes
import pathlib
import re
import shutil
import socketserver
import subprocess
import threading
import time
import urllib.parse
import urllib.request

from .. import events, sim

HOME = pathlib.Path.home()
STATIC = pathlib.Path(__file__).resolve().parent / "static"
ICON = pathlib.Path(__file__).resolve().parents[2] / "docs" / "icon.png"
ROOTS = (HOME / "blinkflow-runs",)
NEVER = re.compile(r"(^contacts.*\.csv$|^truth\.json$|\.xml$|^cam-.*\.csv$)")
PAGE_FILES = ("index.html", "console.css", "console.js", "maskcodec.js")


# ── the stream ───────────────────────────────────────────────────────────────
def latest():
    try:
        return pathlib.Path(events.LATEST.read_text().strip())
    except OSError:
        return None


def read_events(path):
    out = []
    for line in pathlib.Path(path).read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def named_paths(evs):
    """Every path the stream names (any string value, at any depth): absolute, or "./" from its folder."""
    out = set()

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str) and x.startswith(("/", "./")) and len(x) < 400:
            out.add(x)

    for e in evs:
        walk(e)
    return out


def servable(p, evs, stream):
    """A file the page may show: named by the stream, under the runs folder or the stream's own, never
    ground truth."""
    base = pathlib.Path(stream).resolve().parent
    try:
        q = (base / p if p.startswith("./") else pathlib.Path(p)).resolve()
    except (OSError, RuntimeError):
        return None
    if NEVER.search(q.name) or not q.is_file() or not any(r == q or r in q.parents for r in ROOTS + (base,)):
        return None
    return q if p in named_paths(evs) else None


# ── serve ────────────────────────────────────────────────────────────────────
class Frames:
    """The newest frame of the live sidecar, shared by every open page (one /frame call per 0.2 s at most:
    each is an ffmpeg decode on the Windows side)."""

    def __init__(self):
        self.lock, self.at, self.jpeg = threading.Lock(), 0.0, None

    def get(self, sidecar):
        with self.lock:
            if time.time() - self.at >= 0.2:
                self.at = time.time()
                try:
                    with urllib.request.urlopen(f"{sidecar}/frame?width=960", timeout=2) as r:
                        self.jpeg = r.read()
                except OSError:
                    self.jpeg = None
            return self.jpeg


def handler(fixed, frames):
    def stream():
        return fixed or latest()

    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def send(self, code, body=b"", ctype="text/plain", headers=()):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in headers:
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            try:
                if u.path in ("/", "/index.html"):
                    return self.send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
                if u.path == "/static.js":                      # the static report's data; none when live
                    return self.send(200, b"window.BLINKFLOW_STATIC = null;", "text/javascript")
                if u.path == "/icon.png":
                    return self.send(200, ICON.read_bytes(), "image/png")
                if u.path.lstrip("/") in PAGE_FILES:
                    f = STATIC / u.path.lstrip("/")
                    return self.send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "text/plain")
                if u.path == "/events":
                    return self.events()
                if u.path == "/events.json":                    # the whole stream at once (a replay)
                    p = stream()
                    return self.send(200, json.dumps(read_events(p) if p else []).encode(), "application/json")
                if u.path == "/file":
                    p = stream()
                    f = p and servable(q.get("p", ""), read_events(p), p)
                    return self.file(f) if f else self.send(404, b"not in this run's stream")
                if u.path == "/sim.jpg":
                    p = stream()
                    feed = next((e for e in reversed(read_events(p)) if e["type"] == "feed"), None) if p else None
                    jpeg = feed and feed.get("sidecar") and frames.get(feed["sidecar"])
                    return self.send(200, jpeg, "image/jpeg") if jpeg else self.send(204)
                self.send(404, b"not found")
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            if self.path != "/answer":
                return self.send(404)
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            p = stream()
            evs = read_events(p) if p else []
            asked = {e["id"] for e in evs if e["type"] == "ask"}
            done = {e["id"] for e in evs if e["type"] == "answer"}
            qid, yes = body.get("id"), body.get("yes")
            if qid not in asked or qid in done or not isinstance(yes, bool):
                return self.send(409, b"no such open question")
            with p.with_name("answers.jsonl").open("a") as f:
                f.write(json.dumps({"id": qid, "yes": yes, "t": time.time(), "by": "console"}) + "\n")
            self.send(200, b"ok")

        def file(self, f):
            size = f.stat().st_size
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            if not m:
                return self.send(200, f.read_bytes(), ctype, [("Accept-Ranges", "bytes")])
            a = int(m.group(1)) if m.group(1) else max(0, size - int(m.group(2)))
            b = int(m.group(2)) if m.group(1) and m.group(2) else size - 1
            b = min(b, size - 1)
            with f.open("rb") as fh:
                fh.seek(a)
                body = fh.read(b - a + 1)
            self.send(206, body, ctype, [("Accept-Ranges", "bytes"), ("Content-Range", f"bytes {a}-{b}/{size}")])

        def events(self):
            """Server-sent events: the whole stream, then each new line; a newer run starts over ("stream")."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            cur, offset, ping = None, 0, time.time()
            self.close_connection = True
            while True:
                p = stream()
                if p != cur and p and p.exists():
                    cur, offset = p, 0
                    self.wfile.write(f"event: stream\ndata: {json.dumps({'path': str(p), 'now': time.time()})}\n\n"
                                     .encode())
                out = []
                if cur:
                    with cur.open("rb") as fh:
                        fh.seek(offset)
                        chunk = fh.read()
                    end = chunk.rfind(b"\n") + 1               # whole lines only
                    offset += end
                    out = [f"data: {line}\n\n" for line in chunk[:end].decode().splitlines() if line.strip()]
                if not out and time.time() - ping > 10:
                    out = [f"event: ping\ndata: {time.time()}\n\n"]
                if out:
                    ping = time.time()
                    self.wfile.write("".join(out).encode())
                    self.wfile.flush()
                time.sleep(0.15)

    return H


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(port, fixed=None, film=False, speed=None):
    srv = Server(("127.0.0.1", port), handler(fixed and pathlib.Path(fixed).expanduser().resolve(), Frames()))
    print(f"BlinkFlow console: http://localhost:{port}/  (following {fixed or 'the newest run'})", flush=True)
    if film:
        open_film(port, speed)
    srv.serve_forever()


def open_film(port, speed=None):
    """The console full screen at 1920x1080 on the Windows desktop, in a profile of its own: no browser bars,
    no cursor (the page hides it), no buttons. With `speed`, the stream is a finished run replayed at that
    pace, which the page shows ("4x")."""
    q = "film=1" + (f"&speed={speed:g}" if speed else "")
    # full screen on any monitor, laid out at 1920x1080 CSS pixels: the scale is the screen's physical width
    # over 1920 (a 4K screen at 150 % would otherwise give the page 2560x1440)
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController | "
                        "Where-Object CurrentHorizontalResolution | Select-Object -First 1).CurrentHorizontalResolution"],
                       capture_output=True, text=True)
    width = int(r.stdout.strip() or 1920)
    args = [f"--app=http://localhost:{port}/?{q}", r"--user-data-dir=$env:LOCALAPPDATA\BlinkFlow\film",
            "--no-first-run", "--no-default-browser-check", "--window-position=0,0",
            f"--force-device-scale-factor={width / 1920:g}", "--start-fullscreen",
            "--autoplay-policy=no-user-gesture-required", "--hide-scrollbars"]
    arglist = ",".join(f'"{a}"' for a in args)   # double quotes: PowerShell expands $env:
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", f"Start-Process '{sim.CHROME}' -ArgumentList {arglist}"],
                   check=True)


# ── a static report ──────────────────────────────────────────────────────────
def report(path, out=None):
    """The page with the stream embedded and every file it names copied beside it. Texts the page reads
    (SAM replies) are wrapped as scripts, so the report also opens from disk (file://)."""
    path = pathlib.Path(path).expanduser().resolve()
    evs = read_events(path)
    out = pathlib.Path(out).expanduser() if out else path.parent / "console-report"
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    for name in PAGE_FILES:
        shutil.copy(STATIC / name, out / name)
    shutil.copy(ICON, out / "icon.png")
    files, n = {}, 0
    for p in sorted(named_paths(evs)):
        f = servable(p, evs, path)
        if not f:
            continue
        n += 1
        dest = f"assets/{n:03d}-{f.name}"
        if f.suffix == ".txt":                      # SAM replies: read by the page as text
            dest += ".js"
            (out / dest).write_text(f"window.BLINKFLOW_TEXT[{json.dumps(p)}] = {json.dumps(f.read_text())};\n")
        else:
            shutil.copy(f, out / dest)
        files[p] = dest
    (out / "static.js").write_text("window.BLINKFLOW_STATIC = " + json.dumps({"events": evs, "files": files,
                                                                              "source": str(path)}) + ";\n")
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(json.dumps({"report": str(out / "index.html"), "events": len(evs), "files": len(files),
                      "mb": round(size / 1e6, 1)}))
    return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="the live console")
    s.add_argument("--port", type=int, default=8777)
    s.add_argument("--events", help="this stream only (default: follow the newest run)")
    s.add_argument("--film", action="store_true", help="open it full screen on Windows, made to be filmed")
    s.add_argument("--speed", type=float, help="replay the (finished) stream at this pace, e.g. 1 or 4")
    r = sub.add_parser("report", help="a static report of a finished run")
    r.add_argument("events", nargs="?", help="its events.jsonl (default: the newest run's)")
    r.add_argument("--out", help="default: console-report/ beside the stream")
    a = ap.parse_args()
    if a.cmd == "serve":
        if a.speed and not a.events:
            ap.error("--speed replays a finished run: give its --events")
        serve(a.port, a.events, a.film, a.speed)
    else:
        report(a.events or latest(), a.out)
