"""The loop's event stream: one JSON line per thing that happens, appended to events.jsonl in the run folder.

Each line is {"t": epoch (WSL clock), "type": ..., ...}. The entry point (voice, watch, or fix run on its
own) opens the stream with begin(); the processes it starts inherit it through BLINKFLOW_EVENTS and
append to the same file. ~/blinkflow-runs/console/latest names the newest stream.

The console (blinkflow.console) only reads the stream. The loop never waits on it: a write is one
O_APPEND write of one line, and with no stream open emit() does nothing. The one thing that goes the
other way is an answer: the console may append {"id", "yes"} to answers.jsonl beside the stream, and a
question waiting at the terminal takes whichever answer comes first (answer()).
"""
import json
import os
import pathlib
import threading
import time

ENV = "BLINKFLOW_EVENTS"
CLOCK = "BLINKFLOW_SEEN"      # epoch the incident reached BlinkFlow: the start of "seen -> fixed and verified"
LATEST = pathlib.Path.home() / "blinkflow-runs" / "console" / "latest"
_lock = threading.Lock()


def path():
    p = os.environ.get(ENV)
    return pathlib.Path(p) if p else None


def begin(run_dir, mode, **info):
    """Open the stream for a run, unless a parent process already did. Returns its path."""
    if path():
        return path()
    p = pathlib.Path(run_dir).expanduser().resolve() / "events.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch()
    os.environ[ENV] = str(p)
    LATEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = LATEST.with_suffix(".tmp")
    tmp.write_text(str(p))
    tmp.replace(LATEST)
    emit("run", mode=mode, run=str(p.parent), pid=os.getpid(), **info)
    return p


def emit(type_, **data):
    p = path()
    if not p:
        return
    line = (json.dumps({"t": round(time.time(), 3), "type": type_, **data}, default=str) + "\n").encode()
    with _lock:
        fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)


def clock_start(at, why):
    """Start the clock (once per run; processes started later inherit it). Returns its epoch."""
    if os.environ.get(CLOCK):
        return float(os.environ[CLOCK])
    os.environ[CLOCK] = repr(at)
    emit("clock.start", at=at, why=why)
    return at


def clock():
    return float(os.environ[CLOCK]) if os.environ.get(CLOCK) else None


def answers_path():
    p = path()
    return p and p.with_name("answers.jsonl")


def answer(qid):
    """The console's answer to question `qid` (True/False), or None if it has not given one."""
    a = answers_path()
    if not a or not a.exists():
        return None
    for line in a.read_text().splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("id") == qid and isinstance(d.get("yes"), bool):
            return d["yes"]
    return None


class Batcher:
    """Text that arrives in small pieces (a model's stream), emitted at most every `every` s."""

    def __init__(self, type_, every=0.25, **data):
        self.type, self.every, self.data = type_, every, data
        self.buf, self.last = [], 0.0

    def __call__(self, text):
        self.buf.append(text)
        if time.time() - self.last >= self.every:
            self.flush()

    def flush(self):
        if self.buf:
            emit(self.type, text="".join(self.buf), **self.data)
            self.buf, self.last = [], time.time()
