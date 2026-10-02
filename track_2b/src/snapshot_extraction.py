# -*- coding: utf-8 -*-
"""Deterministic extraction snapshot over the 48 bench cases (no LLM calls).

Run before and after a refactor and diff the two JSON blobs to see exactly which
cases changed:

    python src/snapshot_extraction.py > /tmp/after.json
    diff /tmp/before.json /tmp/after.json

This is how the v4 semantic refactor was proved regression-safe without spending
144 model calls: selection is demo-deterministic, so any difference is caused by
the parser/store and not by sampling. The benchmark's own GT is untouched.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "src")
sys.path.insert(0, ROOT)
import fact_parsers as FP
import fact_store as FS

CASES = json.load(open(os.path.join(HERE, "..", "data", "bench", "cases.json"), encoding="utf-8"))["cases"]
FIELDS = FS.FIELDS

out = {}
for c in CASES:
    em = c["email"]
    p = FP.collect(em)
    sel = {}
    for f in FIELDS:
        allowed = FS.FIELD_TYPES.get(f, set())
        cands = [x for x in p["_facts"] if x["type"] in allowed and not x.get("negated")]
        if f == "buyer":
            sigs = [x for x in cands if x["type"] == "buyer_signature"]
            sel[f] = [sigs[0]["id"]] if sigs else []
        elif f == "products":
            sel[f] = [x["id"] for x in cands if x["type"] in ("sku", "doc_id")]
        elif f == "deadline":
            absd = [x for x in cands if x["type"] in ("date", "date_range", "date_bare_month", "duration")]
            rel = [x for x in cands if x["type"] == "relative_time" and x.get("deadline_hint")]
            sel[f] = [x["id"] for x in (absd or rel)]
        elif f == "amounts":
            sel[f] = [x["id"] for x in cands if not x.get("weak")]
        elif f == "payment_terms":
            sel[f] = [x["id"] for x in cands if x["type"] == "payment_terms"]
        elif f == "incoterm":
            sel[f] = [x["id"] for x in cands if x["type"] == "incoterm"]
    store, ns, issues = FS.build(p, em, sel)
    ext = store.extraction()
    out[c["id"]] = {k: v for k, v in ext.items() if k != "product_names"}
print(json.dumps(out, ensure_ascii=False, sort_keys=True, indent=1))
