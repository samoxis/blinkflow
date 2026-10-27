"""BlinkFlow capture sidecar (Windows side, stdlib only).

Keeps the last ~60 s of one window's client area as 1 s H.264 segments
(ffmpeg ddagrab -> NVENC -> segment ring) and samples the cursor at 60 Hz.
Serves snapshots over HTTP so the agent in WSL can ask for "the last N seconds".
With --listen, also push-to-talk: while the key is held (F9 by default, anywhere on the desktop) the
microphone is recorded; the moment of the press is the moment the person speaks about.

    python capture.py --host 172.20.80.1 --title Viser --crop-top 45 --crop-right 356 [--listen [--mic NAME]]

GET /health                  -> state, capture rect, clock offset
GET /snapshot?seconds=N      -> metadata of a new clip (optionally &end=<epoch>)
GET /clip/<id>               -> the clip's mp4 bytes
GET /frame?width=N           -> the newest frame as JPEG (epoch in X-Frame-Epoch), for the watcher
GET /listen?after=N&timeout=S -> the next utterance after id N (press/release epochs), or id null
GET /utterance/<id>          -> its WAV (mono, 16-bit, 24 kHz)
POST /quit[?close=1]         -> stop ffmpeg and exit (optionally close the window)
"""
import argparse
import collections
import ctypes
import ctypes.wintypes as wt
import io
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

FPS = 30
RING = 60          # segments kept on disk (1 s each)
MAX_SNAP = 50      # never hand out segments close to being overwritten
KEEP_SNAPS = 6

user32 = ctypes.windll.user32
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2: physical pixels
HWND_TOPMOST = -1
SWP_NOMOVE, SWP_NOSIZE = 0x2, 0x1


def find_window(title):
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value == title:
                found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def client_rect(hwnd):
    r = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, r.right, r.bottom


class Ring:
    """ffmpeg writing the segment ring, plus a map from stream time to epoch."""

    def __init__(self, ffmpeg, workdir, rect):
        self.ffmpeg, self.dir, self.rect = ffmpeg, workdir, rect
        self.segs = collections.OrderedDict()   # name -> (start_pts, end_pts)
        self.offsets = collections.deque(maxlen=30)
        self.lock = threading.Condition()
        self.proc = None

    def start(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        os.makedirs(os.path.join(self.dir, "snaps"))
        x, y, w, h = self.rect
        src = f"ddagrab=output_idx=0:framerate={FPS}:offset_x={x}:offset_y={y}:video_size={w}x{h}"
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
               "-f", "lavfi", "-i", src,
               "-c:v", "h264_nvenc", "-preset", "p4", "-tune", "ll", "-rc", "vbr", "-cq", "21",
               "-g", str(FPS), "-bf", "0",
               "-f", "segment", "-segment_time", "1", "-segment_wrap", str(RING),
               "-segment_format", "mpegts",
               "-segment_format_options", "flush_packets=1",   # /frame reads the open segment
               "-segment_list", os.path.join(self.dir, "ring.csv"),
               "-segment_list_type", "csv", "-segment_list_size", "0",
               os.path.join(self.dir, "seg%02d.ts")]
        self.proc = subprocess.Popen(cmd, cwd=self.dir)
        threading.Thread(target=self._follow_list, daemon=True).start()

    def _follow_list(self):
        # A segment is listed when the first frame of the next one has been encoded,
        # so arrival time - end_pts is the clock offset plus encode latency. The
        # smallest value seen recently is the best estimate of the offset itself.
        path = os.path.join(self.dir, "ring.csv")
        pos = 0
        while self.proc.poll() is None:
            try:
                with open(path, "rb") as f:
                    f.seek(pos)
                    chunk = f.read()
            except FileNotFoundError:
                chunk = b""
            now = time.time()
            if chunk.endswith(b"\n"):
                pos += len(chunk)
                for line in chunk.decode().splitlines():
                    name, start, end = line.split(",")
                    with self.lock:
                        self.segs[name] = (float(start), float(end))
                        self.segs.move_to_end(name)
                        while len(self.segs) > RING:
                            self.segs.popitem(last=False)
                        self.offsets.append(now - float(end))
                        self.lock.notify_all()
            time.sleep(0.005)

    def offset(self):
        return min(self.offsets) if self.offsets else None

    def snapshot(self, seconds, end=None):
        seconds = min(float(seconds), MAX_SNAP)
        end = time.time() if end is None else float(end)
        with self.lock:
            # wait for the segment that contains `end` to close (at most ~1.5 s)
            deadline = time.time() + 2.0
            while (not self.segs or list(self.segs.values())[-1][1] + self.offset() < end) \
                    and time.time() < deadline:
                self.lock.wait(0.05)
            off = self.offset()
            if off is None:
                raise RuntimeError("no segments yet")
            picked = [(n, s, e) for n, (s, e) in self.segs.items()
                      if e + off > end - seconds and s + off < end]
        if not picked:
            raise RuntimeError("requested window is not in the ring")
        sid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        tmp = os.path.join(self.dir, "snaps", sid)
        os.makedirs(tmp)
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            for i, (n, _, _) in enumerate(picked):
                shutil.copyfile(os.path.join(self.dir, n), os.path.join(tmp, f"{i:02d}.ts"))
                f.write(f"file '{i:02d}.ts'\n")
        out = os.path.join(self.dir, "snaps", sid + ".mp4")
        subprocess.run([self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy",
                        "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", out],
                       check=True)
        shutil.rmtree(tmp, ignore_errors=True)
        self._prune()
        t0 = picked[0][1] + off
        return {"id": sid, "t0_epoch": t0, "t1_epoch": picked[-1][2] + off, "fps": FPS,
                "frames": round((picked[-1][2] - picked[0][1]) * FPS),
                "requested": [end - seconds, end], "rect": self.rect, "clock_offset": off}

    def frame(self, width=448):
        """The newest frame as JPEG, and its epoch. MPEG-TS can be read while it is written, so the
        open segment (the one after the last listed) is decoded first; if it has no whole frame yet,
        the last closed one. Frames come at a constant FPS from the segment's start."""
        with self.lock:
            if not self.segs:
                raise RuntimeError("no segments yet")
            name, (_, end) = next(reversed(self.segs.items()))
            off = self.offset()
        nxt = "seg%02d.ts" % ((int(name[3:5]) + 1) % RING)
        for seg, is_open in ((nxt, True), (name, False)):
            p = os.path.join(self.dir, seg)
            try:
                if is_open and os.path.getmtime(p) + 0.5 < time.time():
                    continue                    # not written since the last wrap: an old segment
            except FileNotFoundError:
                continue
            out = subprocess.run([self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", p,
                                  "-vf", f"scale={int(width)}:-2", "-c:v", "mjpeg", "-q:v", "3",
                                  "-f", "image2pipe", "-"], capture_output=True).stdout
            jpegs = [j + b"\xff\xd9" for j in out.split(b"\xff\xd9") if j.startswith(b"\xff\xd8")]
            # the open segment's last packet may be cut mid-write: its frame is not trusted
            k = len(jpegs) - 1 - is_open
            if k >= 0:
                return jpegs[k], end + off + (k / FPS if is_open else -1 / FPS), is_open
        raise RuntimeError("no frame could be decoded")

    def _prune(self):
        d = os.path.join(self.dir, "snaps")
        clips = sorted(f for f in os.listdir(d) if f.endswith(".mp4"))
        for f in clips[:-KEEP_SNAPS]:
            os.remove(os.path.join(d, f))

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(5)


class Cursor:
    def __init__(self, rect, hz=60, keep_s=65):
        self.rect, self.dt = rect, 1.0 / hz
        self.samples = collections.deque(maxlen=hz * keep_s)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        pt = wt.POINT()
        nxt = time.perf_counter()
        while True:
            user32.GetCursorPos(ctypes.byref(pt))
            self.samples.append((round(time.time(), 4), pt.x - self.rect[0], pt.y - self.rect[1]))
            nxt += self.dt
            time.sleep(max(0.0, nxt - time.perf_counter()))

    def between(self, t0, t1):
        return [s for s in list(self.samples) if t0 <= s[0] <= t1]


class Mic:
    """Push-to-talk. The microphone is read (ffmpeg dshow, 50 ms chunks) all the while, but with the key
    up only the last PREROLL s are kept, in memory; nothing is written to disk. Holding the key records
    an utterance, PREROLL before the press to POSTROLL after the release (the first word is often
    spoken with the press). Each chunk is stamped when it arrives."""
    RATE, CHUNK = 24000, 1200
    PREROLL, POSTROLL, MAX_S, KEEP = 0.3, 0.3, 60, 10

    def __init__(self, ffmpeg, device, vk):
        self.device, self.vk = device, vk
        self.chunks = collections.deque()
        self.utterances = collections.OrderedDict()
        self.press = None
        self.n = 0
        self.lock = threading.Condition()
        self.proc = subprocess.Popen([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                                      "-f", "dshow", "-audio_buffer_size", "50", "-i", f"audio={device}",
                                      "-ac", "1", "-ar", str(self.RATE), "-f", "s16le", "-"],
                                     stdout=subprocess.PIPE)
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._keys, daemon=True).start()

    @staticmethod
    def devices(ffmpeg):
        out = subprocess.run([ffmpeg, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                             capture_output=True, text=True, errors="replace").stderr
        return re.findall(r'"([^"]+)" \(audio\)', out)

    def _read(self):
        while True:
            b = self.proc.stdout.read(self.CHUNK * 2)
            if not b:
                return
            now = time.time()
            with self.lock:
                self.chunks.append((now, b))
                keep = self.PREROLL + 0.2 if self.press is None else self.MAX_S
                while self.chunks and self.chunks[0][0] < now - keep:
                    self.chunks.popleft()

    def _keys(self):
        down = False
        while True:
            held = bool(user32.GetAsyncKeyState(self.vk) & 0x8000)
            if held and not down:
                with self.lock:
                    self.press = time.time()
            elif down and not held:
                threading.Thread(target=self._cut, args=(self.press, time.time()), daemon=True).start()
            down = held
            time.sleep(0.01)

    def _cut(self, press, release):
        time.sleep(self.POSTROLL + 0.1)
        with self.lock:
            pcm = b"".join(b for t, b in self.chunks if press - self.PREROLL <= t <= release + self.POSTROLL)
            if self.press == press:
                self.press = None
            self.n += 1
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(self.RATE)
                w.writeframes(pcm)
            self.utterances[self.n] = {"id": self.n, "press": press, "release": release,
                                       "audio_s": round(len(pcm) / 2 / self.RATE, 3), "wav": buf.getvalue()}
            while len(self.utterances) > self.KEEP:
                self.utterances.popitem(last=False)
            self.lock.notify_all()

    def next(self, after, timeout):
        """The first utterance after id `after`, waiting up to `timeout` s for one."""
        deadline = time.time() + timeout
        with self.lock:
            while True:
                u = next((u for i, u in self.utterances.items() if i > after), None)
                if u or time.time() >= deadline:
                    return u, self.press is not None
                self.lock.wait(min(0.5, deadline - time.time()))

    def alive(self):
        return self.proc.poll() is None

    def stop(self):
        if self.alive():
            self.proc.terminate()


def vk_code(key):
    """F1..F24 or a hex virtual-key code (0x..)."""
    k = key.upper()
    return 0x6F + int(k[1:]) if re.fullmatch(r"F([1-9]|1[0-9]|2[0-4])", k) else int(k, 16)


def make_handler(ring, cursor, hwnd, stop, mic=None):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/health":
                    alive = ring.proc.poll() is None
                    self._json({"now": time.time(), "recording": alive, "rect": ring.rect, "fps": FPS,
                                "segments": len(ring.segs), "clock_offset": ring.offset(),
                                "window_alive": bool(user32.IsWindow(hwnd)),
                                "listening": bool(mic and mic.alive()), "mic": mic and mic.device})
                elif u.path == "/listen":
                    if not (mic and mic.alive()):
                        raise RuntimeError("not listening (start with --listen; is there a microphone?)")
                    utt, held = mic.next(int(q.get("after", 0)), min(float(q.get("timeout", 20)), 60))
                    self._json({"id": None, "held": held} if not utt else
                               {**{k: v for k, v in utt.items() if k != "wav"}, "held": held, "now": time.time()})
                elif u.path.startswith("/utterance/"):
                    utt = mic and mic.utterances.get(int(os.path.basename(u.path)))
                    if not utt:
                        raise KeyError("no such utterance (only the last 10 are kept)")
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/wav")
                    self.send_header("Content-Length", str(len(utt["wav"])))
                    self.end_headers()
                    self.wfile.write(utt["wav"])
                elif u.path == "/snapshot":
                    meta = ring.snapshot(q.get("seconds", 10), q.get("end"))
                    meta["cursor"] = cursor.between(meta["t0_epoch"], meta["t1_epoch"])
                    self._json(meta)
                elif u.path == "/frame":
                    data, t, live = ring.frame(q.get("width", 448))
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("X-Frame-Epoch", repr(t))
                    self.send_header("X-Open-Segment", "1" if live else "0")
                    self.end_headers()
                    self.wfile.write(data)
                elif u.path.startswith("/clip/"):
                    sid = os.path.basename(u.path)
                    p = os.path.join(ring.dir, "snaps", sid + ".mp4")
                    with open(p, "rb") as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self._json({"error": "not found"}, 404)
            except Exception as e:  # report, keep serving
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)

        def do_POST(self):
            if self.path.startswith("/quit"):
                self._json({"ok": True})
                if "close=1" in self.path:
                    user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                stop.set()
            else:
                self._json({"error": "not found"}, 404)

    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8771)
    ap.add_argument("--title", default="Viser")
    ap.add_argument("--crop-top", type=int, default=45)
    ap.add_argument("--crop-right", type=int, default=356)
    ap.add_argument("--wait", type=float, default=60, help="seconds to wait for the window")
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    ap.add_argument("--dir", default=os.path.join(os.environ["LOCALAPPDATA"], "BlinkFlow", "ring"))
    ap.add_argument("--listen", action="store_true", help="push-to-talk: record the microphone while the key is held")
    ap.add_argument("--mic", help="dshow audio device (default: the first that is not a virtual one)")
    ap.add_argument("--ptt-key", default="F9", help="F1..F24 or a hex virtual-key code")
    a = ap.parse_args()

    mic = None
    if a.listen:
        found = Mic.devices(a.ffmpeg)
        real = [d for d in found if not re.search(r"steam|virtual|cable|voicemeeter", d, re.I)]
        device = a.mic or (real or found or [None])[0]
        if not device:
            raise SystemExit("--listen: no microphone found (ffmpeg -list_devices true -f dshow -i dummy)")
        mic = Mic(a.ffmpeg, device, vk_code(a.ptt_key))

    deadline = time.time() + a.wait
    while not (hwnd := find_window(a.title)):
        if time.time() > deadline:
            raise SystemExit(f"no visible window titled {a.title!r}")
        time.sleep(0.25)
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
    x, y, w, h = client_rect(hwnd)
    w, h = (w - a.crop_right) & ~1, (h - a.crop_top) & ~1
    rect = (x, y + a.crop_top, w, h)

    ring = Ring(a.ffmpeg, a.dir, rect)
    ring.start()
    cursor = Cursor(rect)
    stop = threading.Event()
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(ring, cursor, hwnd, stop, mic))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(json.dumps({"listening": f"{a.host}:{a.port}", "rect": rect, "mic": mic and mic.device,
                      "ptt_key": a.listen and a.ptt_key}), flush=True)
    try:
        while not stop.is_set() and ring.proc.poll() is None:
            stop.wait(0.5)
    finally:
        srv.shutdown()
        ring.stop()
        if mic:
            mic.stop()
        user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)  # HWND_NOTOPMOST


if __name__ == "__main__":
    main()
