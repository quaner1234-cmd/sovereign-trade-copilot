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


ERRORS = {
    "timeout": "The model endpoint did not respond before the timeout.",
    "connection": "Could not connect to the model endpoint.",
    "http_error": "The model endpoint rejected the request.",
    "invalid_response": "The model endpoint returned an invalid completion response.",
    "empty_response": "The model endpoint returned no draft text.",
    "client_error": "The model request could not be completed.",
}


def _completion_details(data, choice):
    usage = data.get("usage")
    safe_usage = {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                  if isinstance(usage, dict) and type(usage.get(key)) is int and usage[key] >= 0}
    reason = choice.get("finish_reason")
    safe_reason = reason if isinstance(reason, str) and reason in (
        "stop", "length", "content_filter", "tool_calls", "function_call") else None
    return {"usage": safe_usage or None, "finish_reason": safe_reason}


def chat(messages, max_tokens=400, temperature=0.2, json_mode=False, transport_attempts=3):
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
    def failure(kind, attempt, **details):
        # Never return provider bodies, exception text or request URLs. They may
        # contain credentials, signed links or customer content.
        return {"mode": "llm", "error_kind": kind, "error": ERRORS[kind],
                "latency_ms": round((time.time() - t0) * 1000),
                "transport_attempts": attempt + 1, **details}
    last = None
    for attempt in range(transport_attempts):
        try:
            req = urllib.request.Request(CONFIG["base_url"].rstrip("/") + "/chat/completions",
                                         data=json.dumps(body).encode(), headers=headers)
            with urllib.request.urlopen(req, timeout=CONFIG["timeout_s"]) as r:
                data = json.loads(r.read().decode("utf-8"))
            if (not isinstance(data, dict) or not isinstance(data.get("choices"), list)
                or not data["choices"] or not isinstance(data["choices"][0], dict)
                or not isinstance(data["choices"][0].get("message"), dict)
                or "content" not in data["choices"][0]["message"]):
                return None, failure("invalid_response", attempt)
            choice = data["choices"][0]
            text = choice["message"]["content"]
            details = _completion_details(data, choice)
            if text is not None and not isinstance(text, str):
                return None, failure("invalid_response", attempt, **details)
            if text is None or not text.strip():
                return None, failure("empty_response", attempt, **details)
            return text, {"mode": "llm", "latency_ms": round((time.time() - t0) * 1000),
                          "transport_attempts": attempt + 1, "model": data.get("model"),
                          **details}
        except urllib.error.HTTPError as e:
            last = failure("http_error", attempt, http_status=e.code)
            e.close()
            if e.code < 500 and e.code != 429:  # client error: retrying cannot fix it
                break
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None, failure("invalid_response", attempt)
        except TimeoutError:
            last = failure("timeout", attempt)
        except urllib.error.URLError as e:
            last = failure("timeout" if isinstance(e.reason, TimeoutError) else "connection", attempt)
        except (OSError, ConnectionError):
            last = failure("connection", attempt)
        except Exception:  # Do not expose request data in unexpected failures.
            return None, failure("client_error", attempt)
        if attempt < transport_attempts - 1:
            time.sleep(5 * (attempt + 1))
    return None, last
