# -*- coding: utf-8 -*-
"""Adversarial benchmark runner (v1 dataset, 48 cases).
Channel selection via env (same LLM_* vars as the pipeline):
  LLM_BASE_URL + LLM_NAME (+ LLM_API_KEY)  -> any OpenAI-compatible endpoint
Usage:
  python src/bench.py --runs 3 --tag local-8b-q4
Raw records -> experiments/records/bench-slice/<tag>/ (track_2b relative, gitignored).
"""
import os, sys, json, time, argparse
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import pipeline, llm_client

CASES = json.load(open(os.path.join(HERE, "..", "data", "bench", "cases.json"), encoding="utf-8"))["cases"]


def norm(s):
    return "".join(str(s or "").lower().split())


def digits(s):
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def scalar_match(expected, actual):
    if actual is None:
        return False
    ne, na = norm(expected), norm(actual)
    if not ne:
        return True
    if ne == na or (len(ne) >= 3 and ne in na) or (len(na) >= 3 and na in ne):
        return True
    de, da = digits(expected), digits(actual)
    return bool(de) and de == da


def deadline_match(expected, actual):
    if actual is None:
        return False
    toks = [norm(t) for t in str(expected).split(",") if norm(t)]
    na = norm(actual)
    return all(t and (t in na or digits(t) and digits(t) in digits(actual)) for t in toks)


def products_match(expected_items, actual_items):
    """Each expected item must be matched once in actual. sku matched by normalized token
    (null sku -> qty-only). Extra actual items with digits not in email are flagged by
    check_extraction separately; here only recall counts."""
    matched, total = 0, len(expected_items)
    used = set()
    for it in expected_items or []:
        sku_e = it.get("sku")
        qty_e = digits(it.get("qty"))
        for idx, a in enumerate(actual_items or []):
            if idx in used:
                continue
            sku_ok = (sku_e is None) or (sku_e and norm(sku_e) in norm(json.dumps(a, ensure_ascii=False)))
            qty_ok = (not qty_e) or (qty_e == digits(a.get("qty")))
            if sku_ok and qty_ok:
                matched += 1
                used.add(idx)
                break
    return matched, total


def score_case(case, result, email):
    gt = case["gt"]
    ext = result.get("extraction")
    cls = result.get("classification") or {}
    draft = result.get("draft") or ""
    v = result.get("validation") or {}
    s = {"schema_ok": isinstance(ext, dict) and isinstance(ext.get("not_stated"), list)}

    allow = gt.get("intent_allow") or [gt["intent"]]
    s["intent_ok"] = cls.get("intent") in allow

    kf_matched = kf_total = 0
    if s["schema_ok"] and ext:
        for fname, expected in gt["fields"].items():
            actual = ext.get(fname)
            if fname == "products":
                m, t = products_match(expected, actual)
                kf_matched += m
                kf_total += t
            elif fname == "amounts":
                exp_digits = [digits(a) for a in expected or []]
                act_digits = [digits(a) for a in actual or []]
                for d in exp_digits:
                    kf_total += 1
                    if any(d and (d in ad or ad in d) for ad in act_digits if ad):
                        kf_matched += 1
            elif fname == "deadline":
                kf_total += 1
                if deadline_match(expected, actual):
                    kf_matched += 1
            else:
                kf_total += 1
                if scalar_match(expected, actual):
                    kf_matched += 1
        # false-absent: expected-present field claimed in not_stated
        s["false_absent"] = [f for f in (ext.get("not_stated") or [])
                             if f in gt["fields"] and f != "products"]
    s["kf_matched"], s["kf_total"] = kf_matched, kf_total
    s["key_fields_ok"] = kf_total > 0 and kf_matched == kf_total

    ns = set((ext or {}).get("not_stated") or [])
    absent_total = len(gt["absent"])
    absent_hit = sum(1 for f in gt["absent"] if f in ns)
    s["absent_hit"], s["absent_total"] = absent_hit, absent_total
    s["not_stated_ok"] = absent_total == 0 or absent_hit == absent_total

    val = v.get("extraction") or {}
    dv = v.get("draft") or {}
    cv = v.get("claims") or {}
    invented = [i for i in (val.get("issues") or []) if "digit_mismatch" in i] + \
               [i for i in (dv.get("issues") or []) if "invented_number" in i]
    s["invented"] = invented
    unsupported = list(cv.get("issues") or [])
    forb = [t for t in gt.get("forbidden_in_draft", []) if t.lower() in draft.lower()]
    s["unsupported"] = unsupported + [f"forbidden_token:{t}" for t in forb]
    s["draft_ok"] = bool(draft) and not dv.get("issues") and not forb and not cv.get("issues")

    s["e2e_ok"] = all([s["schema_ok"], s["intent_ok"], s["key_fields_ok"], s["not_stated_ok"],
                       s["draft_ok"]])
    return s


def run_channel(case, promptset):
    """One pipeline execution on the configured channel (env-driven)."""
    if os.environ.get("BENCH_CHANNEL") == "space70b":
        raise ValueError("Legacy HF Space channel is research-only; configure LLM_* instead")
    return pipeline.process(case["email"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--tag", default="local")
    ap.add_argument("--only", default=None, help="substring filter on case id")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    out_dir = os.path.join(ROOT, "experiments", "records", "bench-slice", args.tag)
    os.makedirs(out_dir, exist_ok=True)
    cases = [c for c in CASES if not args.only or args.only in c["id"]][:args.limit or None]

    totals = dict(runs=0, schema=0, intent=0, kf_m=0, kf_t=0, abs_hit=0, abs_tot=0,
                  invented=0, unsupported=0, draft_ok=0, e2e=0)
    failures = []
    for case in cases:
        for run in range(1, args.runs + 1):
            t0 = time.time()
            result = run_channel(case, None)
            wall = round((time.time() - t0) * 1000)
            s = score_case(case, result, case["email"])
            totals["runs"] += 1
            totals["schema"] += s["schema_ok"]
            totals["intent"] += s["intent_ok"]
            totals["kf_m"] += s["kf_matched"]
            totals["kf_t"] += s["kf_total"]
            totals["abs_hit"] += s["absent_hit"]
            totals["abs_tot"] += s["absent_total"]
            totals["invented"] += len(s["invented"])
            totals["unsupported"] += len(s["unsupported"])
            totals["draft_ok"] += s["draft_ok"]
            totals["e2e"] += s["e2e_ok"]
            if not s["e2e_ok"]:
                failures.append({"case": case["id"], "run": run, "scores": s})
            rec = {"case_id": case["id"], "run": run, "tag": args.tag, "cat": case["cat"],
                   "email": case["email"], "gt": case["gt"], "result": result, "scores": s,
                   "wall_ms": wall,
                   "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "channel": os.environ.get("BENCH_CHANNEL") or
                              f"{llm_client.CONFIG['model']}@{llm_client.CONFIG['base_url']}"}
            fn = os.path.join(out_dir, f"{case['id']}__run{run}.json")
            json.dump(rec, open(fn, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"{case['id']} done", flush=True)

    R, n = totals, totals["runs"]
    gates = {
        "G1 json_schema_100%": (R["schema"], n, R["schema"] == n),
        "G2 invented_numeric_0": (R["invented"], "issues", R["invented"] == 0),
        "G3 unsupported_claims_0": (R["unsupported"], "issues", R["unsupported"] == 0),
        "G4 not_stated_recall>=95%": (R["abs_hit"], R["abs_tot"], R["abs_tot"] and R["abs_hit"] / R["abs_tot"] >= 0.95),
        "G5 key_fields>=95%": (R["kf_m"], R["kf_t"], R["kf_t"] and R["kf_m"] / R["kf_t"] >= 0.95),
        "G6 intent>=90%": (R["intent"], n, R["intent"] / n >= 0.90),
        "G7 e2e>=90%": (R["e2e"], n, R["e2e"] / n >= 0.90),
    }
    print("\n===== GATES =====")
    for k, (num, den, ok) in gates.items():
        print(f"{'PASS' if ok else 'FAIL'}  {k:28s} {num}/{den}" + (f" = {num/den:.1%}" if isinstance(den, int) and den else ""))
    json.dump({"tag": args.tag, "totals": totals, "gates": {k: bool(v[2]) for k, v in gates.items()},
               "failures": failures[:50]},
              open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\nrecords: {out_dir}")


if __name__ == "__main__":
    main()
