"""Model calls, and the record of every call: model, where it ran, how much it read and wrote, what it cost.

Prices are list prices (USD): the Meta Model API's, and Baseten's for Muse Spark Open. Local calls cost
nothing but are recorded the same way. Muse Spark runs on Baseten (the open-weight Muse Spark Open), so
the Meta credits go to SAM 3.1, Muse Wonder, Muse Code and Muse Voice Transcribe.
SAM and Muse Wonder spend is also kept in daily ledgers, so a run refuses to start a call that could
take the day past its budget.
"""
import base64
import datetime
import json
import os
import pathlib
import re
import time
import urllib.request

import requests

from . import events

API = "https://api.meta.ai/v1/responses"
ASR = "https://api.meta.ai/v1/asr/transcribe"
OLLAMA = "http://127.0.0.1:11434/api/chat"
GLIMMER = "muse-glimmer"
SPARK = "muse-spark-open-1026"
BASETEN = "https://inference.baseten.co/v1/chat/completions"
BASETEN_MODEL = "meta-models/" + SPARK
WONDER = "muse-wonder-1.0"
VOICE = "muse-voice-transcribe-1.0"
VOICE_PER_MIN = 3.00 / 1000
PRICES = {SPARK: (1.25, 0.15, 4.25), WONDER: (4.0, 0.20, 20.0)}   # per 1M tokens: input, cached input, output
WARM_OUTPUT = 16         # output tokens of a call that only fills the prompt cache
GLIMMER_KEEP = "30m"     # Ollama unloads an idle model after 5 min; a cold Glimmer is a ~20 GB load
SAM_PER_FRAME = 0.20 / 1000
SPEND = pathlib.Path.home() / "blinkflow-runs" / "sam-spend.jsonl"
SAM_DAILY_BUDGET = float(os.environ.get("BLINKFLOW_SAM_BUDGET", "5.0"))
WONDER_SPEND = pathlib.Path.home() / "blinkflow-runs" / "wonder-spend.jsonl"
WONDER_DAILY_BUDGET = float(os.environ.get("BLINKFLOW_WONDER_BUDGET", "15.0"))


def api_key(name="MODEL_API_KEY"):
    key = os.environ.get(name)
    if not key:
        env = pathlib.Path.home() / ".config" / "blinkflow" / "env"
        m = re.search(name + r"=(\S+)", env.read_text()) if env.exists() else None
        key = m and m.group(1).strip("'\"")
    if not key:
        raise RuntimeError(f"{name} is not set")
    return key


def baseten_key():
    return api_key("BASETEN_API_KEY")


class Ledger:
    """Every model call of one run, written out as models.json."""

    def __init__(self):
        self.calls = []

    def add(self, model, where, purpose, seconds, cost_usd, **amounts):
        self.calls.append({"model": model, "where": where, "purpose": purpose,
                           "seconds": round(seconds, 2), **amounts,
                           "cost_usd": None if cost_usd is None else round(cost_usd, 5)})
        events.emit("model", **{k: v for k, v in self.calls[-1].items() if k != "usage"})

    def write(self, path):
        known = [c["cost_usd"] for c in self.calls if c["cost_usd"] is not None]
        doc = {"calls": self.calls, "total_cost_usd": round(sum(known), 5),
               "prices": {"sam-3.1": "$0.20 per 1000 frames",
                          SPARK: "Baseten: $1.25 / 1M input, $0.15 / 1M cached input, $4.25 / 1M output",
                          WONDER: "$4.00 / 1M input, $0.20 / 1M cached input, $20.00 / 1M output",
                          VOICE: "$3.00 per 1000 audio minutes",
                          GLIMMER: "local (Ollama on this PC), $0",
                          "cached": "a SAM 3.1 reply for the same video bytes, concept and parameters, $0"}}
        pathlib.Path(path).write_text(json.dumps(doc, indent=1))
        return doc


# ── daily budgets ────────────────────────────────────────────────────────────
def spent_today(path=SPEND):
    today = datetime.date.today().isoformat()
    if not path.exists():
        return 0.0
    return sum(e["usd"] for e in map(json.loads, path.read_text().splitlines()) if e["day"] == today)


def reserve(path, usd, budget, knob, what):
    """Refuse before spending past the day's budget; log the spend (or the most it can be) otherwise."""
    spent = spent_today(path)
    if spent + usd > budget:
        raise RuntimeError(f"budget: ${spent:.3f} spent today, ${usd:.3f} more could pass ${budget:.2f} ({knob})")
    path.parent.mkdir(exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps({"day": datetime.date.today().isoformat(), "t": time.time(), "usd": usd, "what": what}) + "\n")
    return usd


def settle(path, reserved, actual, what):
    """Replace a worst-case reservation with what the call actually cost."""
    with path.open("a") as f:
        f.write(json.dumps({"day": datetime.date.today().isoformat(), "t": time.time(),
                            "usd": actual - reserved, "what": "settle " + what}) + "\n")


def sam_spent_today():
    return spent_today(SPEND)


def sam_reserve(frames, what):
    return reserve(SPEND, frames * SAM_PER_FRAME, SAM_DAILY_BUDGET, "BLINKFLOW_SAM_BUDGET", what)


# ── text + image models ──────────────────────────────────────────────────────
def glimmer(prompt, images, ledger, purpose, schema=None):
    """Muse Glimmer on this PC through Ollama. `images` are JPEG bytes. Returns the reply text.
    `schema`: a JSON schema the reply must follow. Plain "json" lets it reason inside a string field,
    and on a long prompt it can loop until Ollama aborts (seen naming hazards, Oct 27)."""
    body = {"model": GLIMMER, "stream": False, "format": schema or "json", "think": False,
            "options": {"temperature": 0, "num_ctx": 8192}, "keep_alive": GLIMMER_KEEP,
            "messages": [{"role": "user", "content": prompt,
                          "images": [base64.b64encode(i).decode() for i in images]}]}
    req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.load(r)
    ledger.add(GLIMMER, "local", purpose, time.time() - t, 0.0, images=len(images),
               input_tokens=d.get("prompt_eval_count"), output_tokens=d.get("eval_count"))
    return d["message"]["content"].replace("<|eot|>", "").strip()


def warm_glimmer():
    """Load Glimmer into VRAM (with the context size the calls use) and keep it there; returns seconds.
    Ollama loads a model on its first request, so without this the first naming waits for the load."""
    body = {"model": GLIMMER, "messages": [], "keep_alive": GLIMMER_KEEP, "options": {"num_ctx": 8192}}
    req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        r.read()
    return time.time() - t


def glimmer_vram():
    """Glimmer as Ollama holds it now: {"vram_gb", "size_gb", "context"} (None when it is not loaded)."""
    with urllib.request.urlopen(OLLAMA.replace("/api/chat", "/api/ps"), timeout=5) as r:
        m = next((m for m in json.load(r)["models"] if m["name"].split(":")[0] == GLIMMER), None)
    return m and {"vram_gb": round(m["size_vram"] / 1e9, 1), "size_gb": round(m["size"] / 1e9, 1),
                  "context": m.get("context_length")}


def chat_content(content):
    """Responses API parts (input_text / input_image) as chat completion parts."""
    return [{"type": "text", "text": c["text"]} if c["type"] == "input_text"
            else {"type": "image_url", "image_url": {"url": c["image_url"]}} for c in content]


def spark_cost(u):
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    pin, pcached, pout = PRICES[SPARK]
    return cached, ((u.get("prompt_tokens", 0) - cached) * pin + cached * pcached + u.get("completion_tokens", 0) * pout) / 1e6


def spark(prompt, images, ledger, purpose, effort="low"):
    """Muse Spark Open on Baseten, JSON reply. Returns the reply text."""
    content = [{"type": "input_text", "text": prompt}]
    content += [{"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(i).decode()}
                for i in images]
    body = {"model": BASETEN_MODEL, "messages": [{"role": "user", "content": chat_content(content)}],
            "response_format": {"type": "json_object"}, "reasoning_effort": effort}
    t = time.time()
    r = requests.post(BASETEN, json=body, timeout=300, headers={"Authorization": "Api-Key " + baseten_key()})
    r.raise_for_status()
    d = r.json()
    u = d.get("usage") or {}
    cached, cost = spark_cost(u)
    ledger.add(SPARK, "Baseten", purpose, time.time() - t, cost, images=len(images),
               input_tokens=u.get("prompt_tokens"), cached_input_tokens=cached, output_tokens=u.get("completion_tokens"))
    return d["choices"][0]["message"]["content"] or ""


def spark_stream(content, ledger, purpose, effort, schema, max_output, on_text=None, on_thinking=None):
    """`respond` for Muse Spark: the same call as a streamed chat completion on Baseten.
    Returns (text, status, ledger entry fields)."""
    fmt = ({"type": "json_schema", "json_schema": {"name": "reply", "schema": schema, "strict": True}} if schema
           else {"type": "json_object"})
    body = {"model": BASETEN_MODEL, "stream": True, "stream_options": {"include_usage": True},
            "messages": [{"role": "user", "content": chat_content(content)}],
            "response_format": fmt, "reasoning_effort": effort, "max_tokens": max_output}
    text, usage, status = [], {}, "eof"
    with requests.post(BASETEN, json=body, stream=True, timeout=900,
                       headers={"Authorization": "Api-Key " + baseten_key()}) as r:
        if r.status_code != 200:
            raise RuntimeError(f"{SPARK} HTTP {r.status_code}: {r.text[:500]}")
        r.encoding = "utf-8"
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
            usage = ev.get("usage") or usage
            for ch in ev.get("choices") or []:
                delta = ch.get("delta") or {}
                if delta.get("content"):
                    text.append(delta["content"])
                    if on_text:
                        on_text(delta["content"])
                if delta.get("reasoning_content") and on_thinking:
                    on_thinking(delta["reasoning_content"])
                if ch.get("finish_reason"):
                    status = "completed" if ch["finish_reason"] == "stop" else "incomplete: " + ch["finish_reason"]
    cached, cost = spark_cost(usage)
    return "".join(text), status, cost, dict(
        input_tokens=usage.get("prompt_tokens"), cached_input_tokens=cached,
        output_tokens=usage.get("completion_tokens"),
        reasoning_tokens=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens"))


def transcribe(wav, ledger, purpose, mode="PUSH_TO_TALK"):
    """Muse Voice Transcribe on one recording (WAV: mono, 16-bit PCM, 16 or 24 kHz). Push-to-talk: the
    key held down is the whole turn, so the reply is one transcript. Returns (text, audio seconds)."""
    req = {"mode": mode, "model": VOICE, "audioEncoding": "WAV", "languageBias": ["English"]}
    t = time.time()
    r = requests.post(ASR, timeout=60, headers={"Authorization": "Bearer " + api_key()},
                      files={"request": (None, json.dumps(req), "application/json"),
                             "audio": ("utterance.wav", wav, "audio/wav")})
    r.raise_for_status()
    d = r.json()
    audio_s = (d.get("audioDurationMs") or 0) / 1000
    ledger.add(VOICE, "Meta Model API", purpose, time.time() - t, audio_s / 60 * VOICE_PER_MIN,
               mode=mode, audio_seconds=audio_s, session=d.get("sessionId"))
    return d.get("transcript", "").strip(), audio_s


def respond(model, content, ledger, purpose, effort="medium", schema=None, max_output=16000, warm=False,
            on_text=None, on_thinking=None):
    """One Responses API call with text and images (`content` as input_text / input_image parts),
    streamed (long non-streaming calls end in HTTP 504). JSON reply, held to `schema` when given.
    Muse Wonder first reserves the most the call can cost against its daily budget.
    `warm`: only read `content` into the prompt cache (same model, format and cache key as the real
    call, so its prefix matches); the reply is cut off after a few tokens and not returned.
    `on_text`, `on_thinking`: called with each piece of the reply, and of any reasoning the stream shows."""
    if warm:
        max_output = WARM_OUTPUT
    if model == SPARK:
        t = time.time()
        text, status, cost, amounts = spark_stream(content, ledger, purpose, effort, schema, max_output,
                                                   on_text, on_thinking)
        ledger.add(model, "Baseten", purpose, time.time() - t, cost, effort=effort, status=status,
                   images=sum(c["type"] == "input_image" for c in content), **amounts)
        if warm:
            return None
        if status != "completed":
            raise RuntimeError(f"{model} ended {status}: {text[:300]!r}")
        return text
    pin, pcached, pout = PRICES[model]
    if model == WONDER:
        chars = sum(len(c.get("text", "")) for c in content)
        images = sum(c["type"] == "input_image" for c in content)
        worst = ((chars / 3 + 1600 * images) * pin + max_output * pout) / 1e6
        reserve(WONDER_SPEND, worst, WONDER_DAILY_BUDGET, "BLINKFLOW_WONDER_BUDGET", purpose)
    fmt = ({"type": "json_schema", "name": "reply", "schema": schema, "strict": True} if schema
           else {"type": "json_object"})
    body = {"model": model, "stream": True, "input": [{"type": "message", "role": "user", "content": content}],
            "text": {"format": fmt}, "reasoning": {"effort": effort}, "max_output_tokens": max_output,
            "prompt_cache_key": "blinkflow-diagnose"}
    t, text, usage, status = time.time(), [], {}, "eof"
    try:
        with requests.post(API, json=body, stream=True, timeout=900,
                           headers={"Authorization": "Bearer " + api_key()}) as r:
            if r.status_code != 200:
                raise RuntimeError(f"{model} HTTP {r.status_code}: {r.text[:500]}")
            r.encoding = "utf-8"            # text/event-stream has no charset; requests would assume latin-1
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
                    text.append(ev.get("delta", ""))
                    if on_text:
                        on_text(ev.get("delta", ""))
                elif on_thinking and kind and "reasoning" in kind and kind.endswith(".delta"):
                    on_thinking(ev.get("delta", ""))
                elif kind in ("response.completed", "response.incomplete", "response.failed"):
                    usage, status = (ev.get("response") or {}).get("usage") or {}, kind.split(".")[1]
                elif kind == "error":
                    status = "error: " + json.dumps(ev)[:300]
    finally:
        cached = (usage.get("input_tokens_details") or {}).get("cached_tokens") or 0
        cost = ((usage.get("input_tokens", 0) - cached) * pin + cached * pcached
                + usage.get("output_tokens", 0) * pout) / 1e6
        if model == WONDER and usage:     # no usage (call broke off): the worst case stays booked
            settle(WONDER_SPEND, worst, cost, purpose)
    ledger.add(model, "Meta Model API", purpose, time.time() - t, cost, effort=effort, status=status,
               images=sum(c["type"] == "input_image" for c in content),
               input_tokens=usage.get("input_tokens"), cached_input_tokens=cached,
               output_tokens=usage.get("output_tokens"),
               reasoning_tokens=(usage.get("output_tokens_details") or {}).get("reasoning_tokens"))
    if warm:
        return None
    if status != "completed":
        raise RuntimeError(f"{model} ended {status}: {''.join(text)[:300]!r}")
    return "".join(text)
