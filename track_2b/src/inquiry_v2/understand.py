"""Source-exact inquiry understanding; deterministic mode is explicitly bounded.

An optional model may propose spans, but cannot supply facts without readable
sources or change an inbound source into company authority. No model is called
by this module. Product vocabulary is a domain fallback, not open-world NLP.
"""
import re


PRODUCT_RE = re.compile(
    r"\b(?:ski\s+jackets?|rain\s+jackets?|rain\s+capes?|cycling\s+overshirts?|"
    r"packable\s+overshirts?|work\s+vests?|safety\s+vests?|tote\s+bags?|"
    r"lounge\s+shorts?|technical\s+rainwear|weatherwear|rainwear|"
    r"overshirts?|jackets?|shells?|capes?|vests?|shorts|trousers?|pants|"
    r"shirts?|hoodies?|coats?|bags?|uniforms?|chalecos?|chaquetas?|abrigos?)\b"
    r"|(?:工装马甲|工装背心|夹克|外套|马甲|背心|衬衫|雨衣|短裤|长裤|手提袋)", re.I)
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                "single": 1, "a": 1, "an": 1, "un": 1, "una": 1,
                "uno": 1, "dos": 2, "tres": 3, "一个": 1, "一件": 1}
NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|single|un[ao]?|dos|tres)"
COUNT_NOUN = r"(?:pieces?|pcs|units?|sets?|unidades?|piezas?|prototypes?|samples?|(?:work\s+|safety\s+)?vests?|(?:ski\s+|rain\s+)?jackets?|shells?|overshirts?|capes?|(?:tote\s+)?bags?|garments?|chalecos?|chaquetas?|件|套|个)"
QTY_RE = re.compile(
    rf"(?<![A-Za-z0-9_.-])(?P<qual>about\s+|around\s+|roughly\s+|approximately\s+|approx\.?\s+|at\s+least\s+|at\s+most\s+|minimum\s+|maximum\s+|up\s+to\s+|más\s+de\s+|menos\s+de\s+|约|至少|最多)?"
    rf"(?P<first>{NUM})(?:(?:\s*[–—-]\s*|\s+(?:to|through|hasta|a)\s+)(?P<second>{NUM}))?"
    rf"(?:\s+(?:insulated|cycling|packable|commuter|custom|blue|red|cotton|lightweight|evaluation|rain)){{0,3}}\s*[-]?\s*"
    rf"(?P<unit>{COUNT_NOUN}|of\s+each|per\s+(?:item|style)|each\b)", re.I)
PAYMENT_RE = re.compile(r"(?<![\w/])(?:L\s*/\s*C|LC|T\s*/\s*T|TT|letter\s+of\s+credit|bank\s+transfer|PayPal)(?![\w/])", re.I)
SPEC_RE = re.compile(
    r"\b(?:\d+[-\s]?layer(?:\s+\w+)?|\d+(?:\.\d+)?\s*(?:gsm|g/m2|g/m²|mm|cm|%|K)\b|"
    r"dimensioned\s+drawing|fabric[-\s]weight\s+preferences?|technical\s+drawing|"
    r"short\s+front|drop[-\s]tail\s+back|underarm\s+panels?|removable\s+hood|"
    r"cotton|insulated|licensed\s+reflective\s+material|reflective\s+material|"
    r"waterproof|breathable|taped\s+seams?|logo(?:\s+placement)?)\b", re.I)
FUTURE_RE = re.compile(r"\b(?:in\s+(?:the\s+)?future|later|eventually|next\s+year|future\s+(?:range|collection))\b|未来|以后", re.I)
DATE_RE = re.compile(r"(?<![\w-])(?:\d{4}-\d{2}-\d{2}|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2})(?!\d)", re.I)
AMOUNT_RE = re.compile(r"(?<![A-Za-z0-9_])(?:(?:USD|EUR|GBP)\s*|[$€£]\s*)(\d[\d,]*(?:\.\d+)?)(?![A-Za-z0-9_-]|[.,]\d)", re.I)


def canonical_product(text):
    s = re.sub(r"\s+", " ", str(text).strip().lower())
    # Same product noun, different grammatical number is not a conflict.
    s = re.sub(r"\b(jacket|overshirt|shell|cape|vest|bag|shirt|hoodie|coat|uniform)s\b", r"\1", s)
    s = re.sub(r"\b(chaleco|chaqueta|abrigo)s\b", r"\1", s)
    s = {"chaleco": "vest", "chaqueta": "jacket", "abrigo": "coat"}.get(s, s)
    # Existing Chinese garment nouns share the same category identity across
    # inquiry language and scoped company rules. Source quotes stay literal.
    s = {"工装马甲": "work vest", "工装背心": "work vest",
         "马甲": "vest", "背心": "vest", "夹克": "jacket", "外套": "coat",
         "衬衫": "shirt", "雨衣": "rainwear", "短裤": "shorts",
         "长裤": "pants", "手提袋": "tote bag"}.get(s, s)
    return s


def _number(token):
    s = token.lower().replace(",", "")
    if s in NUMBER_WORDS:
        return NUMBER_WORDS[s]
    v = float(s)
    return int(v) if v.is_integer() else v


def _proposal_value_present(value, quote, key=None):
    """The proposed subspan itself must prove the entire value, not one digit."""
    for m in QTY_RE.finditer(quote):
        a = _number(m.group("first"))
        b = _number(m.group("second")) if m.group("second") else None
        if value == ({"min": a, "max": b} if b is not None else a):
            return True
    if isinstance(value, dict):
        return all(_proposal_value_present(v, quote, key) for v in value.values())
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        matches = re.findall(rf"(?<![\w.-]){NUM}(?![\w.-])", quote, re.I)
        return any(_number(token) == value for token in matches)
    if key == "payment_terms":
        return any(re.sub(r"\s+", "", m.group()).upper() == value
                   for m in PAYMENT_RE.finditer(quote))
    if key == "product":
        return isinstance(value, str) and value in quote
    return str(value).strip().casefold() == quote.strip().casefold()


def _proposal_span(source, proposal):
    """Align an exact quote, never a fuzzy/case-normalized model paraphrase.

    Correct offsets can disambiguate a repeated quote. Wrong or missing offsets
    can be replaced only by a unique literal occurrence in that named source.
    """
    text = source.get("text", "")
    provenance = proposal.get("provenance", {})
    provenance = provenance if isinstance(provenance, dict) else {}
    span = proposal.get("span", provenance.get("span"))
    quote = proposal.get("quote")
    valid_span = (isinstance(span, list) and len(span) == 2 and
                  all(type(x) is int for x in span) and
                  0 <= span[0] < span[1] <= len(text))
    if quote is not None and (not isinstance(quote, str) or not quote):
        return None, "proposal_invalid_quote", None
    if valid_span and (quote is None or text[span[0]:span[1]] == quote):
        return span, None, "model_span_exact"
    if quote is None:
        return None, "proposal_invalid_source_span", None
    first = text.find(quote)
    if first < 0:
        return None, "proposal_quote_not_in_source", None
    if text.find(quote, first + 1) >= 0:
        return None, "proposal_ambiguous_quote", None
    return [first, first + len(quote)], None, "unique_exact_quote"


def _sentence_bounds(text, start, end):
    left = max(text.rfind(".", 0, start), text.rfind("?", 0, start),
               text.rfind("!", 0, start), text.rfind("\n", 0, start)) + 1
    stops = [text.find(c, end) for c in ".?!\n"]
    stops = [i for i in stops if i >= 0]
    return left, min(stops) + 1 if stops else len(text)


def _purpose(text, start, end, source, value=None):
    if source.get("kind") == "platform_field":
        return "bulk_interest"
    left, right = _sentence_bounds(text, start, end)
    clause = text[left:right].lower()
    local = text[max(left, start-28):min(right, end+35)].lower()
    if re.search(r"prototype|pattern\s+work|development|原型|开发", local):
        return "prototype"
    if value == 1 and re.search(r"fit\s+trial|prototype|pattern\s+work|development|原型|开发", clause):
        return "prototype"
    if re.search(r"sample|evaluate\s+(?:one|a)|evaluation|试样|样品|muestra", local):
        return "evaluation_sample"
    if re.search(r"price\s+tier|pricing\s+tier|quote\s+(?:for\s+)?(?:different|each)|volume\s+tier|cost\s+tier", clause):
        return "quote_tier"
    if re.search(r"personal\s+use|for\s+myself|个人|uso\s+personal", clause):
        return "personal_purchase"
    if re.search(r"interested|considering|planning|looking\s+at|before\s+deciding|form\s+shows|platform\s+form|indicative|not\s+(?:a\s+)?(?:confirmed\s+)?order|意向", clause):
        return "bulk_interest"
    if re.search(r"pieces?|pcs|units?|unidades?|of\s+each|per\s+(?:item|style)|件|套", text[start:end], re.I):
        return "bulk"
    if isinstance(value, dict) or isinstance(value, (int, float)) and value > 1:
        return "bulk"
    return "unknown"


def _qualifier(text, second):
    if second is not None:
        return "range"
    text = (text or "").strip().lower()
    if re.search(r"least|minimum|más|至少", text):
        return "minimum"
    if re.search(r"most|maximum|up\s+to|menos|最多", text):
        return "maximum"
    return "approximate" if text else "exact"


def _language(text):
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if re.search(r"[\u0e00-\u0e7f]", text):
        return "th"
    if re.search(r"[¿¡]|\b(?:necesito|necesitamos|precio|puedes|interesa|chaleco|cantidad|unidades)\b", text, re.I):
        return "es"
    if re.search(r"[ąćęłńóśźż]|\b(?:proszę|potrzebuję|cena|ilość)\b", text, re.I):
        return "pl"
    if re.search(r"\b(?:potrebujem|količina|prosim)\b", text, re.I):
        return "sl"
    return "en"


def _stage(text):
    # A requested sample before deciding remains an inquiry. Confirmed commercial
    # execution or an already-running job falls outside the first-inquiry slice.
    pattern = re.compile(r"\b(?:confirmed\s+(?:\d[\d,]*\s+)?order|order(?:\s+for\s+[^.!?\n]{1,90}?)?\s+(?:is\s+)?confirmed|"
                 r"deposit\s+(?:has\s+been\s+)?paid|payment\s+(?:has\s+been\s+)?sent|"
                 r"(?:issue|send|open)\s+(?:the\s+)?(?:PI|proforma\s+invoice)|"
                 r"production\s+(?:has\s+)?started)\b|订单已确认|已付定金|请开.{0,5}发票", re.I)
    for m in pattern.finditer(text):
        prefix = text[max(0, m.start()-40):m.start()]
        if re.search(r"(?:\bnot(?:\s+yet)?|\bno|\bnever|isn't|hasn't|未|没有|不是)\s+(?:a\s+)?$", prefix, re.I):
            continue
        left, right = _sentence_bounds(text, *m.span())
        sentence = text[left:right]
        if sentence.rstrip().endswith("?") and not re.search(r"\b(?:issue|send|open)\s+(?:the\s+)?(?:PI|proforma)", m.group(), re.I):
            continue
        return "out_of_scope"
    return "new_lead"


def understand(registry, proposals=None):
    """Return admitted typed facts from read sources, retaining every candidate.

    Optional proposals have ``key,value,source_id,quote`` and optional ``span``. Quantity/payment/product
    proposals must agree with a context-typed deterministic candidate; all other
    keys are rejected rather than accepting arbitrary source substrings as facts.
    """
    sources = [s for s in registry.get("sources", []) if s.get("status") == "read"]
    by_id = {s["id"]: s for s in sources}
    inbound = [s for s in sources if
               (s.get("party") == "customer" and s.get("kind") in {"customer_email", "thread_message", "attachment"}) or
               s.get("kind") in {"platform_field", "referenced_url"}]
    primary = next((s for s in inbound if s.get("kind") == "customer_email"), None)
    text = (primary or {}).get("text", "")
    result = {"stage": _stage(text), "customer_language": _language(text),
              "decision_frame": "Identify the smallest useful next decision for this inquiry.",
              "lines": [], "customer_asks": [], "candidates": [], "evidence": [], "issues": [],
              "mode": "deterministic_typed_fallback", "model_proposals_used": False,
              "proposal_diagnostics": []}

    def evidence(source, start, end, claim, scope):
        ev = {"id": "E" + str(len(result["evidence"])+1), "source_id": source["id"],
              "span": [start, end], "quote": source.get("text", "")[start:end],
              "claim": claim, "status": "FACT", "scope": scope}
        result["evidence"].append(ev)
        return ev["id"]

    def candidate(source, key, value, start, end, line=None, purpose=None, **extra):
        scope = line["id"] if line else source.get("scope", "inquiry")
        ev_id = evidence(source, start, end, key, scope)
        c = {"id": "C" + str(len(result["candidates"])+1), "key": key, "value": value,
             "unit": extra.pop("unit", None), "source_id": source["id"], "scope": scope,
             "line_id": line["id"] if line else None, "purpose": purpose,
             "status": "system_reported" if source.get("kind") == "platform_field" else
                       "public_reference" if source.get("kind") == "referenced_url" else "customer_stated",
             "evidence_ids": [ev_id], "provenance": {"span": [start, end],
             "quote": source.get("text", "")[start:end], "rule": "source_exact_type_context",
             "derived_from": []}, **extra}
        result["candidates"].append(c)
        return c

    def closest_line(source, start, end, stage=None):
        scoped = source.get("metadata", {}).get("line_id")
        if scoped:
            explicit = next((l for l in result["lines"] if l["id"] == scoped), None)
            if explicit:
                return explicit
        local = [l for l in result["lines"] if l["source_id"] == source["id"] and
                 (stage is None or l["stage"] == stage)]
        if not local:
            local = [l for l in result["lines"] if l["stage"] == "current"]
            if len(local) > 1:
                # A parsed attachment with an unscoped total must not be attached
                # to an arbitrary garment merely because a list order is known.
                return None
        if not local:
            return None
        return min(local, key=lambda l: (0 if start < l["span"][1] and end > l["span"][0] else
                                        min(abs(start-l["span"][1]), abs(end-l["span"][0]))))

    # Product identity is per line, not a single globally conflicting field.
    for source in inbound:
        if source.get("kind") == "platform_field":
            continue
        body = source.get("text", "")
        for m in PRODUCT_RE.finditer(body):
            if re.search(r"\d+[-\s]layer\s+$", body[max(0, m.start()-18):m.start()], re.I):
                # A construction bullet's noun is a specification, not a second
                # independently requested product next to the named garment.
                if result["lines"]:
                    continue
            left, right = _sentence_bounds(body, *m.span())
            stage = "future" if FUTURE_RE.search(body[left:right]) else "current"
            product = canonical_product(m.group())
            existing = next((l for l in result["lines"] if l["product_ref"] == product and l["stage"] == stage), None)
            if existing is None:
                existing = {"id": "L"+str(len(result["lines"])+1), "product_ref": product,
                            "source_id": source["id"], "span": list(m.span()), "evidence_ids": [],
                            "stage": stage, "quantity": None, "quantity_purpose": "unknown",
                            "quantity_candidate_ids": [], "spec_cues": []}
                result["lines"].append(existing)
            c = candidate(source, "product", m.group(), *m.span(), line=existing)
            existing["evidence_ids"].extend(c["evidence_ids"])

    for source in inbound:
        body = source.get("text", "")
        matches = list(QTY_RE.finditer(body))
        # A platform quantity field may contain only its numeric payload; it is
        # still a system report of interest, never a firm order.
        if source.get("kind") == "platform_field" and str(source.get("metadata", {}).get("name", source.get("metadata", {}).get("field", ""))).lower() == "quantity":
            numeric = re.fullmatch(r"\s*(\d[\d,]*(?:\.\d+)?)\s*", body)
            if numeric:
                line = closest_line(source, *numeric.span(1))
                c = candidate(source, "quantity", _number(numeric.group(1)), *numeric.span(1), line=line,
                              purpose="bulk_interest", unit="pieces", qualifier="exact")
                if line:
                    line["quantity_candidate_ids"].append(c["id"])
        for m in matches:
            start, end = m.span()
            # hyphenated constructions, identifiers, monetary and technical
            # units are not item counts, even if a model points at their digits.
            prefix = body[max(0, start-12):start]
            if re.search(r"[A-Za-z]-$|(?:USD|EUR|GBP|\$|€)\s*$", prefix):
                continue
            value = _number(m.group("first"))
            second = _number(m.group("second")) if m.group("second") else None
            if second is not None:
                value = {"min": value, "max": second}
                if value["min"] > value["max"]:
                    result["issues"].append("invalid_quantity_range:" + source["id"])
                    continue
            purpose = _purpose(body, start, end, source, value)
            left, right = _sentence_bounds(body, start, end)
            targets = []
            if re.search(r"of\s+each|per\s+(?:item|style)|each\b", m.group("unit"), re.I):
                targets = [l for l in result["lines"] if l["source_id"] == source["id"] and
                           l["stage"] == "current" and l["span"][0] < end]
            if not targets:
                targets = [closest_line(source, start, end)]
            for line in targets:
                c = candidate(source, "quantity", value, start, end, line=line, purpose=purpose,
                              unit="pieces", qualifier=_qualifier(m.group("qual"), second),
                              approximate=bool(m.group("qual") and _qualifier(m.group("qual"), None) == "approximate"))
                negative_prefix = body[max(0, start-35):start]
                negative_suffix = body[end:min(len(body), end+35)]
                if re.search(r"(?:\bnot|no\s+longer|instead\s+of|rather\s+than|不是|并非)\s*[(\[]?\s*$", negative_prefix, re.I) or re.match(r"\s+(?:is|was|are)\s+(?:wrong|incorrect|not\s+correct)\b", negative_suffix, re.I):
                    c.update(status="rejected", requested_status="customer_stated",
                             rejection_reasons=["negated_quantity"], semantic_stance="negated")
                elif re.search(r"\b(?:do\s+not|don't|never)\s+(?:send|ship|produce|make)\s*$", negative_prefix, re.I):
                    c["semantic_stance"] = "prohibited_action"
                    # The prohibition is about an action, not a false numeric
                    # value. Preserve it without admitting it as a buying plan.
                    c["purpose"] = "unknown"
                if line:
                    line["quantity_candidate_ids"].append(c["id"])
        for m in PAYMENT_RE.finditer(body):
            candidate(source, "payment_terms", re.sub(r"\s+", "", m.group()).upper(), *m.span())
        for m in DATE_RE.finditer(body):
            candidate(source, "date", m.group(), *m.span(), line=closest_line(source, *m.span()))
        for m in AMOUNT_RE.finditer(body):
            candidate(source, "amount", _number(m.group(1)), *m.span(), line=closest_line(source, *m.span()),
                      unit=re.match(r"USD|EUR|GBP|[$€£]", m.group(), re.I).group().upper())
        for m in SPEC_RE.finditer(body):
            line = closest_line(source, *m.span())
            if line is not None:
                eid = evidence(source, *m.span(), "specification", line["id"])
                kind = "construction" if re.search(r"layer|panels?|hood|seam|front|back", m.group(), re.I) else "material"
                if re.search(r"drawing", m.group(), re.I):
                    kind = "drawing"
                line["spec_cues"].append({"text": m.group(), "kind": kind, "source_id": source["id"],
                                         "span": list(m.span()), "evidence_id": eid})
        if source.get("kind") in {"customer_email", "thread_message"}:
            for m in re.finditer(r"[^.!?。！？\n]+[?？]|(?:Please|Can\s+you|Could\s+you)[^.!?。！？\n]+[.!。！]?", body, re.I):
                if m.group().strip():
                    result["customer_asks"].append({"id": "Q"+str(len(result["customer_asks"])+1),
                        "text": m.group().strip(), "source_id": source["id"], "span": list(m.span()), "disposition": "unresolved"})

    for line in result["lines"]:
        cs = [c for c in result["candidates"] if c["id"] in line["quantity_candidate_ids"]]
        # Customer body/thread/parsed attachment outranks platform interest. A
        # prototype/sample is the current advance; bulk interest stays in ledger.
        ranked = sorted([c for c in cs if c["status"] != "rejected"], key=lambda c: (c["status"] == "system_reported",
                         c["purpose"] not in {"prototype", "evaluation_sample"}, c["purpose"] in {"bulk_interest", "quote_tier"}))
        if ranked:
            chosen = ranked[0]
            line["quantity"] = chosen["value"]
            line["quantity_purpose"] = chosen["purpose"]
            line["quantity_qualifier"] = chosen.get("qualifier", "exact")
            line["selected_quantity_candidate_id"] = chosen["id"]
        firm = [c for c in cs if c["status"] not in {"system_reported", "rejected"} and c["purpose"] not in {"bulk_interest", "quote_tier"}]
        by_purpose = {}
        for c in firm:
            by_purpose.setdefault(c["purpose"], set()).add(repr(c["value"]))
        if any(len(values) > 1 for values in by_purpose.values()):
            result["issues"].append("line_quantity_conflict:" + line["id"])

    if proposals is not None:
        proposal_list = proposals.get("candidates", []) if isinstance(proposals, dict) else proposals
        for p in proposal_list if isinstance(proposal_list, list) else []:
            if not isinstance(p, dict):
                result["issues"].append("proposal_invalid_shape")
                continue
            source_id = p.get("source_id")
            source = by_id.get(source_id) if isinstance(source_id, str) else None
            if source is None:
                result["issues"].append("proposal_invalid_source_span")
                continue
            span, span_issue, alignment = _proposal_span(source, p)
            diagnostic = {"source_id": source["id"], "key": p.get("key"),
                          "model_span": p.get("span"), "resolved_span": span,
                          "alignment": alignment, "admitted": False}
            result["proposal_diagnostics"].append(diagnostic)
            if span_issue:
                diagnostic["issue"] = span_issue
                result["issues"].append(span_issue)
                continue
            start, end = span
            key, value = p.get("key"), p.get("value")
            if not isinstance(key, str) or key not in {"quantity", "product", "payment_terms"}:
                diagnostic["issue"] = "proposal_type_context_rejected:" + str(key)
                result["issues"].append(diagnostic["issue"])
                continue
            valid_value = (key == "quantity" and (
                isinstance(value, (int, float)) and not isinstance(value, bool) or
                isinstance(value, dict) and set(value) == {"min", "max"} and
                all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value.values())))
            valid_value = valid_value or key in {"product", "payment_terms"} and isinstance(value, str) and bool(value.strip())
            if not valid_value:
                issue = "proposal_invalid_value_type:" + str(key)
                diagnostic["issue"] = issue
                result["issues"].append(issue)
                continue
            quote = source["text"][start:end]
            if not _proposal_value_present(value, quote, key):
                diagnostic["issue"] = "proposal_value_not_proven_by_span"
                result["issues"].append(diagnostic["issue"])
                continue
            found = next((c for c in result["candidates"] if c["source_id"] == source["id"] and
                          c["status"] != "rejected" and c["key"] == key and c["value"] == value and
                          (c["provenance"]["span"][0] <= start < end <= c["provenance"]["span"][1] or
                           start <= c["provenance"]["span"][0] < c["provenance"]["span"][1] <= end)), None)
            if found is None:
                diagnostic["issue"] = "proposal_type_context_rejected:" + str(key)
                result["issues"].append(diagnostic["issue"])
            else:
                found["provenance"]["model_proposed"] = True
                found["provenance"]["model_alignment"] = {"method": alignment,
                    "model_span": p.get("span"), "quote_span": span,
                    "typed_proof_span": found["provenance"]["span"]}
                diagnostic["admitted"] = True
                diagnostic["typed_proof_span"] = found["provenance"]["span"]
                result["model_proposals_used"] = True
    if result["stage"] != "out_of_scope" and any(l["stage"] == "current" and l["spec_cues"] and l["quantity"] is not None and
            l["quantity_purpose"] not in {"evaluation_sample", "bulk_interest", "quote_tier"} for l in result["lines"]):
        result["stage"] = "qualified_inquiry"
    if result["customer_asks"]:
        result["decision_frame"] = result["customer_asks"][0]["text"]
    return result
