# -*- coding: utf-8 -*-
"""Minimal OpenAI-compatible client (stdlib only) + offline demo fallback.
Config via env (official template contract):
  LLM_NAME      — model id, e.g. swiss-ai/Apertus-v1.5-8B
  LLM_BASE_URL  — e.g. https://api.publicai.co/v1  (unset => offline demo mode)
  LLM_API_KEY   — bearer token (optional for local endpoints)
"""
import json, os, time, urllib.request, urllib.error

CONFIG = {
    "model": os.environ.get("LLM_NAME", ""),
    "base_url": os.environ.get("LLM_BASE_URL", ""),
    "api_key": os.environ.get("LLM_API_KEY", ""),
    "timeout_s": int(os.environ.get("LLM_TIMEOUT_S", "60")),
}


def demo_mode():
    return not CONFIG["base_url"]


def chat(messages, max_tokens=400, temperature=0.2, json_mode=False):
    """Returns (text, meta). meta: {"mode": "llm"|"demo", "latency_ms", "error"?}"""
    if demo_mode():
        return None, {"mode": "demo", "latency_ms": 0}
    body = {"model": CONFIG["model"], "messages": messages,
            "max_tokens": max_tokens, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json", "User-Agent": "HackApertus-track2b/0.1"}
    if CONFIG["api_key"]:
        headers["Authorization"] = "Bearer " + CONFIG["api_key"]
    t0 = time.time()
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(CONFIG["base_url"].rstrip("/") + "/chat/completions",
                                         data=json.dumps(body).encode(), headers=headers)
            with urllib.request.urlopen(req, timeout=CONFIG["timeout_s"]) as r:
                data = json.loads(r.read().decode("utf-8"))
            text = data["choices"][0]["message"]["content"] or ""
            return text, {"mode": "llm", "latency_ms": round((time.time() - t0) * 1000),
                          "transport_attempts": attempt + 1, "model": data.get("model"),
                          "usage": data.get("usage"),
                          "finish_reason": data["choices"][0].get("finish_reason")}
        except urllib.error.HTTPError as e:
            last = {"mode": "llm", "error": f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}",
                    "latency_ms": round((time.time() - t0) * 1000)}
            if e.code < 500 and e.code != 429:  # client error: retrying cannot fix it
                break
        except Exception as e:  # network/HTTP errors must not kill the demo path
            last = {"mode": "llm", "error": f"{type(e).__name__}: {e}",
                    "latency_ms": round((time.time() - t0) * 1000)}
        if attempt < 2:
            time.sleep(5 * (attempt + 1))
    return None, last
