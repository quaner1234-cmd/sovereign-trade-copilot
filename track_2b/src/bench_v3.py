# -*- coding: utf-8 -*-
"""v3 benchmark runner — reports RAW MODEL and FINAL SYSTEM separately.

The v2 runner produced ONE number per gate, which hid the fact that validation
failures were being returned to the user anyway. v3 scores the same 48 cases on
two surfaces:

  RAW MODEL    pre-guard classification and draft; extraction is already
               evidence-validated, so this is only a partial RAW view.
  FINAL SYSTEM what the v3 pipeline would actually show the user (post-guard).

Gates are evaluated on FINAL SYSTEM. RAW MODEL is reported alongside as
evidence, never blended into the gate number.

Usage:
  python src/bench_v3.py --runs 3 --tag v3-70b
Configure LLM_NAME, LLM_BASE_URL and LLM_API_KEY for real inference.
"""
import argparse, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import pipeline_v3
import bench as B2  # reuse the v2 matchers so the gates stay comparable

CASES = json.load(open(os.path.join(HERE, "..", "data", "bench", "cases.json"), encoding="utf-8"))["cases"]


def score_final(case, result):
    """Score the shipped output (post-guard). Same mechanics as v2."""
    return B2.score_case(case, result, case["email"])


def score_raw(case, result):
    """Score what the model literally produced, before the guard.

    Reuse the same scorer with pre-guard classification and draft. Extraction
    is the FINAL validated store on both surfaces; this is a partial RAW view,
    not a pure measurement of the selector before evidence validation.
    """
    raw = result.get("raw_model") or {}
    ext = result.get("extraction")
    raw_ext = dict(ext) if isinstance(ext, dict) else {}
    # Keep the historical output schema, but do not claim raw extraction here.
    ns = raw_ext.get("not_stated")
    if isinstance(ns, list):
        raw_ext = dict(raw_ext)
    raw_result = {
        "classification": raw.get("classification") or result.get("classification"),
        "extraction": raw_ext,
        "draft": raw.get("draft") or "",
        "validation": {"extraction": {"ok": True, "issues": []},
                       "draft": {"ok": True, "issues": []},
                       "claims": {"ok": True, "issues": []}},
    }
    return B2.score_case(case, raw_result, case["email"])


def accumulate(t, s):
    t["runs"] += 1
    t["schema"] += bool(s["schema_ok"])
    t["intent"] += bool(s["intent_ok"])
    t["kf_m"] += s["kf_matched"]
    t["kf_t"] += s["kf_total"]
    t["abs_hit"] += s["absent_hit"]
    t["abs_tot"] += s["absent_total"]
    t["invented"] += len(s["invented"])
    t["unsupported"] += len(s["unsupported"])
    t["draft_ok"] += bool(s["draft_ok"])
    t["e2e"] += bool(s["e2e_ok"])
    return t


def blank():
    return dict(runs=0, schema=0, intent=0, kf_m=0, kf_t=0, abs_hit=0, abs_tot=0,
                invented=0, unsupported=0, draft_ok=0, e2e=0)


def gates_for(R):
    n = R["runs"]
    return {
        "G1 json_schema_100%": (R["schema"], n, n > 0 and R["schema"] == n),
        "G2 invented_numeric_0": (R["invented"], "issues", R["invented"] == 0),
        "G3 unsupported_claims_0": (R["unsupported"], "issues", R["unsupported"] == 0),
        "G4 not_stated>=95%": (R["abs_hit"], R["abs_tot"], bool(R["abs_tot"]) and R["abs_hit"] / R["abs_tot"] >= 0.95),
        "G5 key_fields>=95%": (R["kf_m"], R["kf_t"], bool(R["kf_t"]) and R["kf_m"] / R["kf_t"] >= 0.95),
        "G6 intent>=90%": (R["intent"], n, n > 0 and R["intent"] / n >= 0.90),
        "G7 e2e>=90%": (R["e2e"], n, n > 0 and R["e2e"] / n >= 0.90),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--tag", default="v3")
    ap.add_argument("--only", default=None)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    out_dir = os.path.join(ROOT, "experiments", "records", "bench-slice", args.tag)
    os.makedirs(out_dir, exist_ok=True)
    # --only accepts a comma-separated list of case ids (or a single substring).
    # Previously it was `args.only in c["id"]`, so a comma-joined list matched
    # nothing and the run silently scored 0/0.
    if args.only:
        wanted = [w.strip() for w in args.only.split(",") if w.strip()]
        cases = [c for c in CASES
                 if c["id"] in wanted or any(w in c["id"] for w in wanted)]
    else:
        cases = list(CASES)
    cases = cases[:args.limit or None]
    if not cases:
        raise SystemExit(f"--only {args.only!r} matched no case ids")

    final_t, raw_t = blank(), blank()
    failures, guard_hits = [], {"blocked_first": 0, "retry_ok": 0, "fallback": 0, "clean": 0}
    lat = []

    for case in cases:
        for run in range(1, args.runs + 1):
            t0 = time.time()
            try:
                result = pipeline_v3.process(case["email"])
            except Exception as e:
                result = {"error": f"{type(e).__name__}: {e}",
                          "classification": {"intent": "other"}, "extraction": None,
                          "draft": "", "validation": {}, "raw_model": {}, "meta": {}}
            lat.append(time.time() - t0)
            sf = score_final(case, result)
            sr = score_raw(case, result)
            accumulate(final_t, sf)
            accumulate(raw_t, sr)
            if not sf["e2e_ok"]:
                failures.append({"case": case["id"], "run": run, "final": sf, "raw": sr})
            g = ((result.get("meta") or {}).get("guards") or {}).get("final") or {}
            via = g.get("via")
            if via == "retry":
                guard_hits["retry_ok"] += 1
            elif via == "deterministic_fallback":
                guard_hits["fallback"] += 1
            elif g.get("passed"):
                guard_hits["clean"] += 1
            else:
                guard_hits["blocked_first"] += 1

            rec = {"case_id": case["id"], "run": run, "tag": args.tag, "cat": case["cat"],
                   "email": case["email"], "gt": case["gt"], "result": result,
                   "scores": {"final": sf, "raw": sr},
                   "wall_ms": round((time.time() - t0) * 1000),
                   "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "channel": f"{__import__('llm_client').CONFIG['model']}"}
            with open(os.path.join(out_dir, f"{case['id']}__run{run}.json"), "w", encoding="utf-8") as fh:
                json.dump(rec, fh, ensure_ascii=False, indent=1)
        print(f"{case['id']} done", flush=True)

    summary = {"tag": args.tag, "runs": args.runs, "cases": len(cases),
               "raw_model": {"totals": raw_t, "gates": {k: bool(v[2]) for k, v in gates_for(raw_t).items()}},
               "final_system": {"totals": final_t, "gates": {k: bool(v[2]) for k, v in gates_for(final_t).items()}},
               "guard": guard_hits,
               "latency_avg_s": round(sum(lat) / len(lat), 2) if lat else None,
               "latency_max_s": round(max(lat), 2) if lat else None,
               "failures": failures[:60]}
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)

    for label, T in (("RAW MODEL   ", raw_t), ("FINAL SYSTEM", final_t)):
        print(f"\n===== {label} =====")
        for k, (num, den, ok) in gates_for(T).items():
            pct = f" = {num/den:.1%}" if isinstance(den, int) and den else ""
            print(f"{'PASS' if ok else 'FAIL'}  {k:28s} {num}/{den}{pct}")
    print("\nguard:", json.dumps(guard_hits))
    print(f"records: {out_dir}")


if __name__ == "__main__":
    main()
