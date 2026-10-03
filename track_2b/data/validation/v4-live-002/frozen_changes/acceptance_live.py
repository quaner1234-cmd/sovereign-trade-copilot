"""One real end-to-end run per frozen v4 acceptance case. No prompt tuning.

Set LLM_* in the process environment; never write credentials to a config file.
Usage: python -B src/acceptance_live.py --output experiments/records/v4-live-001
The record contains synthetic inputs, all model calls, checks and source hashes.

TWO SURFACES, REPORTED SEPARATELY
  RAW BUSINESS CORRECTNESS — the frozen business rubric applied to the text the
    MODEL wrote. No guard verdict is mixed in: a case can be business-wrong and
    system-safe, and reporting one number for both hides which one failed.
  FINAL SYSTEM SAFETY — what actually ships: the full guard verdict on the final
    draft, the frozen rubric on that text, and which path produced it
    (raw / retry / deterministic fallback / withheld).
Neither surface can change the cases, the expectations or the prompts.
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


def drift_classes(issues):
    """The three guard classes present in an issue list, as a sorted list."""
    return sorted({c for c in (P.drift_class(i) for i in issues or []) if c})


def business_checks(case, typed, draft, gissues):
    """The frozen business rubric on one draft.

    `acceptance.check` is patched out, so nothing is printed and nothing global is
    appended: the same frozen expectations are simply re-read on a second surface.
    The guard verdict is dropped — it is a safety measurement, not a business one.
    """
    out = []
    with patch.object(A, "check",
                      side_effect=lambda n, c, d="": out.append(
                          {"name": n, "passed": bool(c), "detail": d if not c else ""})):
        A.evaluate_case(case, typed, draft, gissues)
    return [c for c in out if not c["name"].endswith(": draft passes the guard")]


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
        "note": "Working source hashes identify the frozen-semantic-guard fix; base commit alone does not.",
        "changed_sources": ["pipeline_v3.py", "acceptance_live.py"],
        "unchanged": ["acceptance.py (cases and expectations)", "semantics.py",
                      "judgment.py + judgment_policies.json (Judgment Layer)",
                      "prompts/v1-v3.json", "fact_parsers.py", "fact_store.py", "llm_client.py"],
        "benchmarks_run": "none (no 144-call benchmark, no additional scenarios)",
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
        # --- RAW BUSINESS CORRECTNESS: the text the MODEL wrote, guard ignored
        raw_draft = result["raw_model"].get("draft") or ""
        raw_guard_issues = P.guard_reply(raw_draft, store, case["email"], parsed, typed)[2]
        raw_business = business_checks(case, typed, raw_draft, raw_guard_issues)
        # --- FINAL SYSTEM SAFETY: the text that SHIPS
        with patch.object(A, "check", side_effect=check):
            A.evaluate_case(case, typed, result["draft"], final_issues)
        check("real transport for every model call", bool(calls) and all(
            not c["meta"].get("error") and c["meta"].get("model") == P.llm_client.CONFIG["model"] for c in calls))
        check("final status matches independent full guard", result["validation"]["guard"]["passed"] == (not final_issues))
        check("shipped draft carries none of the three drift classes",
              not drift_classes(final_issues), ",".join(drift_classes(final_issues)))
        final_business = business_checks(case, typed, result["draft"], final_issues)
        raw_surface = {"draft": raw_draft, "guard_issues": raw_guard_issues,
                       "drift_classes": drift_classes(raw_guard_issues),
                       "business_checks": raw_business,
                       "business_pass": all(c["passed"] for c in raw_business)}
        final_surface = {"draft": result["draft"], "guard_issues": final_issues,
                         "guard_passed": result["validation"]["guard"]["passed"],
                         "via": result["validation"]["guard"]["via"],
                         "drift_classes": drift_classes(final_issues),
                         "business_checks": final_business,
                         "business_pass": all(c["passed"] for c in final_business),
                         "guard_and_business_pass": all(c["passed"] for c in checks)}
        usage = {key: sum((c["meta"].get("usage") or {}).get(key, 0) for c in calls)
                 for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
        record = {"case_id": case["id"], "parser_candidates": parsed,
                  "apertus_calls": calls, "result": result, "checks": checks,
                  "raw_business": raw_surface, "final_system": final_surface,
                  "latency_ms": round((time.perf_counter() - started) * 1000), "usage": usage}
        # Guard against accidental credential persistence even on provider errors.
        key = P.llm_client.CONFIG["api_key"]
        if key and key in json.dumps(record, ensure_ascii=False):
            raise SystemExit("Credential detected in output; record withheld.")
        write(args.output / (case["id"] + ".json"), record)
        row = {"id": case["id"], "status": "PASS" if all(x["passed"] for x in checks) else "FAIL",
               "failures": [x for x in checks if not x["passed"]],
               "raw_business_pass": raw_surface["business_pass"],
               "raw_drift_classes": raw_surface["drift_classes"],
               "final_guard_passed": final_surface["guard_passed"],
               "final_business_pass": final_surface["business_pass"],
               "final_drift_classes": final_surface["drift_classes"],
               "raw_guard": result["meta"]["guards"]["raw"],
               "final_via": result["validation"]["guard"]["via"],
               "latency_ms": record["latency_ms"], "usage": usage, "model_calls": len(calls)}
        summary.append(row)
        print(case["id"], row["status"], "via=" + row["final_via"],
              "raw_business=" + ("PASS" if raw_surface["business_pass"] else "FAIL"),
              "raw_drift=" + (",".join(raw_surface["drift_classes"]) or "none"),
              "final_drift=" + (",".join(final_surface["drift_classes"]) or "none"), flush=True)
        print(case["id"], row["status"], "via=" + row["final_via"], flush=True)
        for failure in row["failures"]:
            print("  " + failure["name"] + ": " + failure["detail"], flush=True)
    unchanged = all(hashlib.sha256((root / p).read_bytes()).hexdigest() == h for p, h in hashes.items())
    write(args.output / "summary.json", {"cases": summary, "frozen_sources_unchanged": unchanged,
                                         "passed": sum(x["status"] == "PASS" for x in summary),
                                         "raw_business_correctness_passed": sum(x["raw_business_pass"] for x in summary),
                                         "final_system_safety_passed": sum(
                                             x["final_guard_passed"] and not x["final_drift_classes"] for x in summary),
                                         "finished_at": datetime.now(timezone.utc).isoformat()})
    if not unchanged:
        raise SystemExit("Source changed during evaluation.")


if __name__ == "__main__":
    main()
