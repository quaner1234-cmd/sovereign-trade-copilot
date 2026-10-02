# -*- coding: utf-8 -*-
"""Track 2B pipeline v2: email -> classify -> extract -> draft + mechanical validation.
v2 changes (driven by bench findings, see experiments/bench-slice/):
  - prompts/v2: sharper intent definitions, strict not_stated discipline, no-inference rule
  - normalize_extraction(): null/missing field -> not_stated (mechanical, model-agnostic)
  - one mechanical retry when a step returns unparseable JSON
LLM arithmetic/transcription is never trusted; validators flag anything not verbatim."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm_client
from validators import load_json_strict, check_extraction, check_draft, check_claims

PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "v2.json")
PROMPTS = json.load(open(PROMPT_PATH, encoding="utf-8"))
FIELDS = PROMPTS["FIELDS"]

OFFLINE_SAMPLE = {
    "email": ("Hi, we saw your catalogue. We need 5,000 pcs of TS-001 cotton tee, ribbed collar. "
              "Please quote CIF Hamburg and delivery time. Payment 30% T/T deposit is fine. "
              "Sarah Lau, Nordic Apparel AB"),
    "classification": {"intent": "inquiry", "language": "en", "urgency": "normal"},
    "extraction": {"buyer": "Sarah Lau, Nordic Apparel AB",
                   "products": [{"sku": "TS-001", "qty": "5,000", "desc": "cotton tee, ribbed collar"}],
                   "incoterm": "CIF", "payment_terms": "30% T/T deposit", "deadline": "not_stated_placeholder",
                   "amounts": [], "not_stated": ["deadline"]},
    "draft": ("Sarah 您好，感谢垂询。TS-001 罗纹领棉T恤 5,000 件我们已记录，CIF Hamburg 报价与交期将在1个工作日内确认。"
              "付款条款按 30% T/T 定金执行。Nordic Apparel AB 团队期待合作。"),
}


def _fill(tpl, **kw):
    out = tpl
    for k, v in kw.items():
        out = out.replace("{" + k + "}", v)
    return out


ABSENT_VALUE = {"not_stated", "n/a", "na", "none", "null", "-", "未提及", "未知", "not mentioned", "not specified"}
USUAL_VALUE = ("as usual", "as always", "usual", "same as last", "same as before", "as before",
               "as per our standing agreement", "照旧", "按惯例", "惯例", "跟以前一样", "和以前一样", "老规矩")


def _value_is_absent(v):
    """Mechanical: these 'values' carry no concrete fact -> treat the field as absent."""
    if v is None or v == "" or v == [] or v == {}:
        return True
    if isinstance(v, str):
        s = v.strip().lower().rstrip(".")
        if s in ABSENT_VALUE or s in USUAL_VALUE:
            return True
        if len(s) <= 40 and any(u in s for u in USUAL_VALUE):
            return True
    return False


def normalize_extraction(extraction):
    """Mechanical normalization, no ground-truth knowledge:
    - absent-ish values (null/empty/'not_stated'/'as usual'/...) -> moved into not_stated
    - fields WITH a concrete value are removed from not_stated (double-reporting fix)
    - unknown not_stated entries -> unmapped (flagged, not silently fixed)
    Returns (clean_extraction, normalizations:list)."""
    if not isinstance(extraction, dict):
        return None, ["not_a_dict"]
    norm = []
    ext = {k: v for k, v in extraction.items() if k != "not_stated"}
    ns = list(extraction.get("not_stated") or [])
    for f in FIELDS:
        v = ext.get(f)
        if _value_is_absent(v):
            if v is not None and v != "" and v != [] and v != {}:
                norm.append(f"absent_value_normalized:{f}")
            ext.pop(f, None)
            if f not in ns:
                ns.append(f)
                norm.append(f"moved_to_not_stated:{f}")
        elif f in ns:
            ns.remove(f)
            norm.append(f"removed_from_not_stated:{f}")
    unknown = [x for x in ns if x not in FIELDS]
    known = [x for x in ns if x in FIELDS]
    if unknown:
        norm.append("unmapped_not_stated:" + "|".join(unknown))
    ext["not_stated"] = known
    if unknown:
        ext["unmapped_notes"] = unknown
    return ext, norm


def _chat_json(messages, max_tokens, temperature):
    """chat + parse; one mechanical retry on unparseable output."""
    for attempt in range(2):
        text, meta = llm_client.chat(messages, max_tokens=max_tokens, temperature=temperature)
        obj = load_json_strict(text)
        if obj is not None or meta.get("error"):
            return obj, text, meta | {"attempts": attempt + 1}
    return obj, text, meta | {"attempts": 2}


def process(email, debug=False):
    meta = {"mode": "llm", "steps": {}}
    if llm_client.demo_mode():
        result = dict(OFFLINE_SAMPLE)
        result["meta"] = {"mode": "demo", "note": "LLM_BASE_URL not set; deterministic demo output"}
        result["validation"] = {"extraction": check_extraction(result["extraction"], result["email"]),
                                "draft": check_draft(result["draft"], result["email"]),
                                "claims": check_claims(result["draft"], result["email"])}
        return result

    cls, _, m1 = _chat_json([{"role": "system", "content": PROMPTS["classify"]["system"]},
                             {"role": "user", "content": _fill(PROMPTS["classify"]["user"], email=email)}],
                            max_tokens=120, temperature=0.0)
    meta["steps"]["classify"] = m1 | {"json_ok": cls is not None}

    extraction, _, m2 = _chat_json([{"role": "system", "content": PROMPTS["extract"]["system"]},
                                    {"role": "user", "content": _fill(PROMPTS["extract"]["user"], email=email)}],
                                   max_tokens=900, temperature=0.0)
    normalizations = []
    if extraction is not None:
        extraction, normalizations = normalize_extraction(extraction)
    meta["steps"]["extract"] = m2 | {"json_ok": extraction is not None,
                                     "normalizations": normalizations}

    ext_str = json.dumps(extraction, ensure_ascii=False) if extraction else "{}"
    draft, m3 = llm_client.chat([{"role": "system", "content": PROMPTS["draft"]["system"]},
                                 {"role": "user", "content": _fill(PROMPTS["draft"]["user"],
                                                                   email=email, extraction=ext_str)}],
                                max_tokens=300, temperature=0.2)
    draft = (draft or "").strip()
    meta["steps"]["draft"] = m3 | {"ok": bool(draft)}

    validation = {"extraction": check_extraction(extraction, email) if extraction else {"ok": False, "issues": ["no_json"]},
                  "draft": check_draft(draft, email),
                  "claims": check_claims(draft, email)}
    return {"classification": cls, "extraction": extraction, "draft": draft,
            "validation": validation, "meta": meta}
