# -*- coding: utf-8 -*-
"""Offline parser-reachability audit: can the deterministic layer even SEE every
ground-truth value? No model calls. This is the ceiling for G5/G4.

For each case and field we ask: does the parser produce a candidate whose value
matches the GT expectation (under the same comparison the bench scorer uses)?
If not, no amount of LLM selection work can recover that field, and we must
extend the parser instead of prompting harder.
"""
import json, os, re, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fact_parsers as FP

CASES = json.load(open(os.path.join(HERE, "..", "data", "bench", "cases.json"), encoding="utf-8"))["cases"]


def norm(s):
    return "".join(str(s or "").lower().split())


def digits(s):
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def scalar_match(expected, actual):
    ne, na = norm(expected), norm(actual)
    if not ne:
        return True
    if ne == na or (len(ne) >= 3 and ne in na) or (len(na) >= 3 and na in ne):
        return True
    de, da = digits(expected), digits(actual)
    return bool(de) and de == da


def deadline_match(expected, actual):
    toks = [norm(t) for t in str(expected).split(",") if norm(t)]
    na = norm(actual)
    return all(t and (t in na or (digits(t) and digits(t) in digits(actual))) for t in toks)


def reachable(parsed, expected):
    """Is the GT value derivable from some parser candidate?

    `expected` may be a scalar, a list of scalars (amounts), or a
    comma-joined multi-value string (deadline). All three must be handled —
    treating a list as a comma string is what produced a bogus 70% ceiling.
    """
    vals = [f["value"] for f in parsed["_facts"]]
    # list-valued field: every element must be independently reachable
    if isinstance(expected, (list, tuple)):
        if not expected:
            return True
        return all(any(scalar_match(e, v) or norm(e) in norm(v) for v in vals)
                   for e in expected)
    # scalar or comma-joined multi-value string
    toks = [t.strip() for t in str(expected).split(",") if t.strip()]
    if len(toks) > 1:
        return all(any(scalar_match(t, v) or norm(t) in norm(v) for v in vals) for t in toks)
    return any(scalar_match(expected, v) or norm(expected) in norm(v) for v in vals)


def products_reachable(parsed, expected):
    """Each expected product needs an identifier AND a quantity candidate present."""
    ids = [f["value"] for f in parsed["_facts"] if f["type"] in ("sku", "doc_id")]
    qtys = [f["number"] for f in parsed["_facts"] if f["type"] == "qty"]
    for it in expected or []:
        sku, qty = it.get("sku"), digits(it.get("qty"))
        if sku is None and qty is None:
            continue
        sku_ok = (sku is None) or any(norm(sku) in norm(i) for i in ids)
        qty_ok = (not qty) or any(qty in digits(q) or digits(q) in qty for q in qtys)
        if not (sku_ok and qty_ok):
            return False
    return True


def main():
    miss = collections.defaultdict(list)
    tot = collections.Counter()
    for case in CASES:
        parsed = FP.collect(case["email"])
        gt = case["gt"]
        for fname, expected in gt["fields"].items():
            if fname == "products":
                ok = products_reachable(parsed, expected)
            elif fname == "deadline":
                ok = reachable(parsed, expected)
            else:
                ok = reachable(parsed, expected)
            tot[fname] += 1
            tot["ALL"] += 1
            if not ok:
                miss[fname].append((case["id"], expected))
                tot["MISS_ALL"] += 1
    print("=" * 78)
    print("PARSER REACHABILITY CEILING (offline, no LLM)")
    print("=" * 78)
    for f in ["buyer", "products", "incoterm", "payment_terms", "deadline", "amounts", "ALL"]:
        if tot[f]:
            n = tot[f] - len(miss[f])
            print(f"  {f:14s} {n}/{tot[f]} = {n/tot[f]:6.1%}")
    print()
    for f, lst in miss.items():
        print(f"--- UNREACHABLE {f} ({len(lst)}) ---")
        for cid, exp in lst:
            print(f"    {cid:8s} expected={exp!r}")
    return miss


if __name__ == "__main__":
    main()