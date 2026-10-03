"""One real end-to-end run per frozen v4 acceptance case. No prompt tuning.

Set LLM_* in the process environment; never write credentials to a config file.
Usage: python -B src/acceptance_live.py --output experiments/records/v4-live-001
The record contains synthetic inputs, all model calls, checks and source hashes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
from datetime import datetime, timezone
from unittest.mock import patch
import acceptance as A
import fact_parsers as FP
import fact_store as FS
import pipeline_v3 as P


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if P.llm_client.demo_mode() or P.llm_client.CONFIG["model"] != "swiss-ai/Apertus-v1.5-70B":
        raise SystemExit("Real Apertus v1.5 70B configuration is required; demo is forbidden here.")
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parent
    tracked_sources = sorted(root.glob("*.py")) + sorted((root / "prompts").glob("*.json"))
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked_sources}
    write(args.output / "manifest.json", {
        "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "started_at": datetime.now(timezone.utc).isoformat(), "source_hashes": hashes,
        "case_hash": hashlib.sha256(json.dumps(A.CASES, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        "model_requested": P.llm_client.CONFIG["model"], "cases": len(A.CASES), "runs_per_case": 1,
        "note": "Working source hashes identify the fallback-safety fix; base commit alone does not.",
    })
    write(args.output / "cases.json", A.CASES)
    summary = []
    transport_chat = P.llm_client.chat
    for case in A.CASES:
        calls, checks = [], []
        def capture(messages, **kw):
            system = messages[0]["content"]
            stage = "classify" if system == P.PROMPTS["classify"]["system"] else (
                "select" if system == P.PROMPTS["select"]["system"] else "retry" if len(messages) > 2 else "reply")
            text, meta = transport_chat(messages, **kw)
            calls.append({"stage": stage, "text": text, "meta": meta, "settings": kw})
            return text, meta
        def check(name, cond, detail=""):
            checks.append({"name": name, "passed": bool(cond), "detail": detail if not cond else ""})
        started = time.perf_counter()
        with patch.object(P.llm_client, "chat", side_effect=capture):
            result = P.process(case["email"], debug=True)
        parsed = FP.collect(case["email"])
        store, _, _ = FS.build(parsed, case["email"], result["raw_model"].get("selection") or {})
        typed = result["semantics"]["typed_facts"]
        final_issues = P.guard_reply(result["draft"], store, case["email"], parsed, typed)[2]
        with patch.object(A, "check", side_effect=check):
            A.evaluate_case(case, typed, result["draft"], final_issues)
        check("real transport for every model call", bool(calls) and all(
            not c["meta"].get("error") and c["meta"].get("model") == P.llm_client.CONFIG["model"] for c in calls))
        check("final status matches independent full guard", result["validation"]["guard"]["passed"] == (not final_issues))
        usage = {key: sum((c["meta"].get("usage") or {}).get(key, 0) for c in calls)
                 for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
        record = {"case_id": case["id"], "parser_candidates": parsed,
                  "apertus_calls": calls, "result": result, "checks": checks,
                  "latency_ms": round((time.perf_counter() - started) * 1000), "usage": usage}
        # Guard against accidental credential persistence even on provider errors.
        key = P.llm_client.CONFIG["api_key"]
        if key and key in json.dumps(record, ensure_ascii=False):
            raise SystemExit("Credential detected in output; record withheld.")
        write(args.output / (case["id"] + ".json"), record)
        row = {"id": case["id"], "status": "PASS" if all(x["passed"] for x in checks) else "FAIL",
               "failures": [x for x in checks if not x["passed"]],
               "raw_guard": result["meta"]["guards"]["raw"],
               "final_via": result["validation"]["guard"]["via"],
               "latency_ms": record["latency_ms"], "usage": usage, "model_calls": len(calls)}
        summary.append(row)
        print(case["id"], row["status"], "via=" + row["final_via"], flush=True)
        for failure in row["failures"]:
            print("  " + failure["name"] + ": " + failure["detail"], flush=True)
    unchanged = all(hashlib.sha256((root / p).read_bytes()).hexdigest() == h for p, h in hashes.items())
    write(args.output / "summary.json", {"cases": summary, "frozen_sources_unchanged": unchanged,
                                         "passed": sum(x["status"] == "PASS" for x in summary),
                                         "finished_at": datetime.now(timezone.utc).isoformat()})
    if not unchanged:
        raise SystemExit("Source changed during evaluation.")


if __name__ == "__main__":
    main()
