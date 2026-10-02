# -*- coding: utf-8 -*-
"""Self-test: run the pipeline over data/samples.json, print mechanical results.
Usage (from repo root of track_2b, with LLM_* env set for llm mode):
  python src/selftest.py            # demo mode if LLM_BASE_URL unset
Records raw outputs to stdout as JSON lines; no manual polishing."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline, llm_client

SAMPLES = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "..", "data", "samples.json"), encoding="utf-8"))["samples"]


def main():
    print(f"mode={'demo' if llm_client.demo_mode() else 'llm'} "
          f"model={llm_client.CONFIG['model'] or '(demo)'} base={llm_client.CONFIG['base_url'] or '(unset)'}")
    for s in SAMPLES:
        t0 = time.time()
        r = pipeline.process(s["email"])
        wall = round((time.time() - t0) * 1000)
        v = r["validation"]
        out = {
            "id": s["id"], "wall_ms": wall,
            "mode": r.get("meta", {}).get("mode"),
            "classification": r.get("classification"),
            "extraction_json_ok": isinstance(r.get("extraction"), dict),
            "not_stated": (r.get("extraction") or {}).get("not_stated"),
            "extraction_ok": v["extraction"]["ok"], "extraction_issues": v["extraction"]["issues"],
            "draft_ok": v["draft"]["ok"], "draft_issues": v["draft"]["issues"],
            "draft": r.get("draft"),
            "steps": r.get("meta", {}).get("steps"),
        }
        print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
