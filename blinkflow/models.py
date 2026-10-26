"""Model calls, and the record of every call: model, where it ran, how much it read and wrote, what it cost.

Prices are Meta Model API list prices (USD). Local calls cost nothing but are recorded the same way.
SAM spend is also kept in a daily ledger, so a run refuses to start tracking past the day's budget.
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

API = "https://api.meta.ai/v1/responses"
OLLAMA = "http://127.0.0.1:11434/api/chat"
GLIMMER = "muse-glimmer"
SPARK = "muse-spark-1.3"
PRICES = {SPARK: (1.25, 0.15, 4.25)}   # per 1M tokens: input, cached input, output
SAM_PER_FRAME = 0.20 / 1000
SPEND = pathlib.Path.home() / "blinkflow-runs" / "sam-spend.jsonl"
SAM_DAILY_BUDGET = float(os.environ.get("BLINKFLOW_SAM_BUDGET", "1.0"))


def api_key():
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        env = pathlib.Path.home() / ".config" / "blinkflow" / "env"
        m = re.search(r"MODEL_API_KEY=(\S+)", env.read_text()) if env.exists() else None
        key = m and m.group(1).strip("'\"")
    if not key:
        raise RuntimeError("MODEL_API_KEY is not set")
    return key


class Ledger:
    """Every model call of one run, written out as models.json."""

    def __init__(self):
        self.calls = []

    def add(self, model, where, purpose, seconds, cost_usd, **amounts):
        self.calls.append({"model": model, "where": where, "purpose": purpose,
                           "seconds": round(seconds, 2), **amounts,
                           "cost_usd": None if cost_usd is None else round(cost_usd, 5)})

    def write(self, path):
        known = [c["cost_usd"] for c in self.calls if c["cost_usd"] is not None]
        doc = {"calls": self.calls, "total_cost_usd": round(sum(known), 5),
               "prices": {"sam-3.1": "$0.20 per 1000 frames",
                          SPARK: "$1.25 / 1M input, $0.15 / 1M cached input, $4.25 / 1M output",
                          GLIMMER: "local (Ollama on this PC), $0"}}
        pathlib.Path(path).write_text(json.dumps(doc, indent=1))
        return doc


# ── SAM daily budget ─────────────────────────────────────────────────────────
def sam_spent_today():
    today = datetime.date.today().isoformat()
    if not SPEND.exists():
        return 0.0
    return sum(e["usd"] for e in map(json.loads, SPEND.read_text().splitlines()) if e["day"] == today)


def sam_reserve(frames, what):
    """Refuse before spending past the day's budget; log the spend otherwise."""
    usd = frames * SAM_PER_FRAME
    spent = sam_spent_today()
    if spent + usd > SAM_DAILY_BUDGET:
        raise RuntimeError(f"SAM budget: ${spent:.3f} spent today, ${usd:.3f} more would pass "
                           f"${SAM_DAILY_BUDGET:.2f} (BLINKFLOW_SAM_BUDGET)")
    SPEND.parent.mkdir(exist_ok=True)
    with SPEND.open("a") as f:
        f.write(json.dumps({"day": datetime.date.today().isoformat(), "t": time.time(),
                            "frames": frames, "usd": usd, "what": what}) + "\n")
    return usd


# ── text + image models ──────────────────────────────────────────────────────
def glimmer(prompt, images, ledger, purpose):
    """Muse Glimmer on this PC through Ollama. `images` are JPEG bytes. Returns the reply text."""
    body = {"model": GLIMMER, "stream": False, "format": "json", "think": False,
            "options": {"temperature": 0, "num_ctx": 8192},
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


def spark(prompt, images, ledger, purpose, effort="low"):
    """Muse Spark 1.3 on the Meta Model API, JSON reply. Returns the reply text."""
    content = [{"type": "input_text", "text": prompt}]
    content += [{"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(i).decode()}
                for i in images]
    body = {"model": SPARK, "input": [{"type": "message", "role": "user", "content": content}],
            "text": {"format": {"type": "json_object"}}, "reasoning": {"effort": effort}}
    t = time.time()
    r = requests.post(API, json=body, timeout=300, headers={"Authorization": "Bearer " + api_key()})
    r.raise_for_status()
    d = r.json()
    u = d.get("usage") or {}
    cached = (u.get("input_tokens_details") or {}).get("cached_tokens", 0)
    pin, pcached, pout = PRICES[SPARK]
    cost = ((u.get("input_tokens", 0) - cached) * pin + cached * pcached + u.get("output_tokens", 0) * pout) / 1e6
    ledger.add(SPARK, "Meta Model API", purpose, time.time() - t, cost, images=len(images),
               input_tokens=u.get("input_tokens"), output_tokens=u.get("output_tokens"))
    text = [c["text"] for o in d["output"] if o["type"] == "message" for c in o["content"]
            if c["type"] == "output_text"]
    return "".join(text)
