"""Bounded reverse-admission gates, independent of draft generation.

These checks catch typed count, token, provenance and authority failures. A
passing gate is not a proof of complete open-vocabulary semantic correctness or
reply usefulness. No retry or fallback text is generated in P0-P2.
"""
import re

from .understand import (AMOUNT_RE, DATE_RE, PAYMENT_RE, PRODUCT_RE, QTY_RE,
                         _number, _qualifier, canonical_product, canonical_payment)


NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_,.-])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![A-Za-z0-9_-]|[.,]\d)|(?<![A-Za-z0-9_,.-])\d+(?:\.\d+)?(?![A-Za-z0-9_-]|[.,]\d)")
IDENTIFIER_RE = re.compile(r"\b[A-Z]{1,8}[-_]\d[\w-]*\b", re.I)
POSITIVE_COMPANY_RE = re.compile(
    r"\b(?:we\s+(?:can|will|support|provide|offer|guarantee|confirm|have|manufacture|produce|make|sew)|"
    r"our\s+(?:(?:standard|normal|sample|bulk|production|factory)\s+){0,3}(?:MOQ|minimum|stock|certificates?|price|quote|payment\s+terms|delivery\s+date|lead\s*time|delivery\s*time)\s+(?:is|are|has)|"
    r"(?:podemos|ofrecemos|garantizamos|confirmamos|tenemos|fabricamos)|"
    r"nuestro\s+(?:MOQ|mínimo|stock)\s+es)\b|"
    r"(?:我司|我们|本公司)(?:支持|可以|可提供|提供|保证|已确认|有库存|能够|生产|制造)|"
    r"(?:我司|我们|本公司).{0,12}(?:起订量|MOQ|交期).{0,6}(?:是|为)", re.I)
NEGATIVE_COMPANY_RE = re.compile(r"\b(?:we\s+(?:cannot|can't|do\s+not|don't)|cannot\s+confirm|not\s+confirmed|"
                                  r"no\s+podemos|necesitamos\s+verificar)\b|不能|尚未确认|需核实|需要核实", re.I)
HEDGE_RE = re.compile(r"\b(?:about|around|roughly|approximately|approx\.?)\b|约|大约|aproximadamente", re.I)
MIN_RE = re.compile(r"\b(?:at\s+least|minimum|min\.?|more\s+than)\b|至少|最低|más\s+de", re.I)
MAX_RE = re.compile(r"\b(?:at\s+most|maximum|max\.?|up\s+to|less\s+than)\b|最多|最高|menos\s+de", re.I)


def _status(candidate):
    return candidate.get("status", candidate.get("value_status", candidate.get("state")))


def _raw_values(value):
    if isinstance(value, dict):
        return [v for v in value.values() if isinstance(v, (str, int, float)) and not isinstance(v, bool)]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, (str, int, float)) and not isinstance(v, bool)]
    return [value]


def _source_valid(candidate, by_id):
    source = by_id.get(candidate.get("source_id"))
    if not source or source.get("status") != "read":
        return False
    provenance = candidate.get("provenance", {})
    span = provenance.get("span", candidate.get("span"))
    quote = provenance.get("quote", candidate.get("quote"))
    if not isinstance(span, list) or len(span) != 2 or any(type(x) is not int for x in span):
        return False
    start, end = span
    valid = 0 <= start < end <= len(source.get("text", "")) and source.get("text", "")[start:end] == quote
    if not valid:
        return False
    if _status(candidate) == "company_confirmed":
        if source.get("kind") not in {"company_context", "operator_input"} or source.get("party") != "company":
            return False
        if not all(source.get("metadata", {}).get(k) for k in ("confirmed_by", "confirmed_at")) or candidate.get("scope") != source.get("scope"):
            return False
    if candidate.get("key") == "quantity":
        if source.get("kind") == "platform_field":
            return str(source.get("metadata", {}).get("field", source.get("metadata", {}).get("name", ""))).lower() == "quantity" and bool(re.fullmatch(r"\d[\d,]*(?:\.\d+)?", quote))
        matches = []
        for m in QTY_RE.finditer(quote):
            a = _number(m.group("first"))
            b = _number(m.group("second")) if m.group("second") else None
            matches.append({"min": a, "max": b} if b is not None else a)
        return candidate.get("value") in matches
    if candidate.get("key") == "payment_terms":
        return canonical_payment(candidate.get("value")) in {canonical_payment(m.group()) for m in PAYMENT_RE.finditer(quote)}
    return True


def _product_supported(product, allowed):
    canonical = canonical_product(product)
    return canonical in allowed or any(p.endswith(" " + canonical) for p in allowed)


def _sentences(draft):
    return [s.strip() for s in re.split(r"(?<=[.!?。！？])\s*|\n", draft) if s.strip()]


def _numeric_tokens(text):
    # Identifiers never stand in for quantity/date/price values.
    masked = IDENTIFIER_RE.sub(lambda m: " " * len(m.group()), text)
    return [_number(m.group()) for m in NUMBER_RE.finditer(masked)]


def _confirmation_covers(sentence, confirmed):
    terms = [canonical_payment(m.group()) for m in PAYMENT_RE.finditer(sentence)]
    products = [canonical_product(m.group()) for m in PRODUCT_RE.finditer(sentence)]
    numbers = _numeric_tokens(sentence)
    for c in confirmed:
        key = str(c.get("key", ""))
        vals = _raw_values(c.get("value"))
        textual = " ".join(str(v) for v in vals).lower()
        source_claim = str(c.get("_authority_quote", c.get("provenance", {}).get("quote", textual)))
        # Confirmation of a negative or pending company fact is not authority
        # for an affirmative customer promise merely mentioning the same token.
        if re.search(r"\b(?:unknown|unavailable|pending|(?:do|does)\s+not|don't|doesn't|cannot|can't|no\s+podemos|not\s+(?:confirmed|available|authorized|supported)|requires?\s+(?:human\s+)?(?:approval|verification|checking))\b|未确认|不支持|不能|需.{0,5}(?:核实|批准)|未知", source_claim, re.I):
            continue
        if terms and ("payment" in key or key.startswith("capability.payment")):
            if all(t in re.sub(r"\s+", "", textual).upper() for t in terms):
                return True
        if re.search(r"our\s+(?:price|quote)\s+(?:is|are)", sentence, re.I):
            if key in {"amount", "price", "target_price", "sample_price", "bulk_price"} and numbers and all(n in vals for n in numbers):
                return True
            continue
        if re.search(r"\bMOQ\b|minimum|起订量|mínimo", sentence, re.I):
            if "moq" in key.lower() and numbers and all(n in vals for n in numbers):
                scope = " ".join([str(c.get("scope", "")), str(c.get("key", "")), str(c.get("unit", ""))]).lower()
                if re.search(r"per\s+colou?r|每色", sentence, re.I) and not re.search(r"colou?r|per_colour|per_color", scope):
                    continue
                if re.search(r"per\s+(?:style|item)|每款", sentence, re.I) and not re.search(r"style|item", scope):
                    continue
                return True
            continue
        if re.search(r"lead\s*time|delivery\s*time|交期", sentence, re.I):
            if key.startswith("lead_time.") and numbers and all(n in vals for n in numbers) and c.get("unit") == "days":
                if ".sample" in key and not re.search(r"sample|样品", sentence, re.I):
                    continue
                if ".normal" in key and not re.search(r"normal|standard|正常|常规", sentence, re.I):
                    continue
                conditions = c.get("conditions", [])
                if any(condition != "normal_conditions" and str(condition).casefold() not in sentence.casefold() for condition in conditions):
                    continue
                return True
            continue
        if key == "capability.products" and products and not terms:
            admitted = {canonical_product(m.group()) for m in PRODUCT_RE.finditer(textual)}
            if all(_product_supported(p, admitted) for p in products) and re.search(r"manufactur|produc|make|sew|制造|生产|fabricar", sentence, re.I):
                return True
            continue
        if key.startswith("capability.") or key == "capability":
            if re.search(r"review|assessment|evaluate", key, re.I):
                if re.search(r"review|assess|evaluate|check", sentence, re.I) and not re.search(r"stock|certif|traceab|authoriz|guarantee|库存|认证|保证", sentence, re.I):
                    return True
            # Capability text must be relevant to this claim; generic capability
            # authority is not permission to promise stock, dates or all tests.
            tokens = set(re.findall(r"[a-z]{3,}", textual)) - {"company", "confirmed", "can", "our", "the", "and", "with"}
            claim = set(re.findall(r"[a-z]{3,}", sentence.lower()))
            overlap = tokens & claim
            if overlap and not terms and all(_product_supported(p, {canonical_product(m.group()) for m in PRODUCT_RE.finditer(textual)}) for p in products):
                if re.search(r"guarantee|stock|certif|traceab|authoriz|guarantiz|库存|认证|保证|溯源", sentence, re.I):
                    if not re.search(r"guarantee|stock|certif|traceab|authoriz|guarantiz|库存|认证|保证|溯源", textual, re.I):
                        continue
                return True
    return False


def _scoped_authority(claim, confirmed, understanding):
    """A rule usable for one line never licenses a promise for every line."""
    lines = [line for line in understanding.get("lines", []) if line.get("stage") == "current"]
    products = [canonical_product(m.group()) for m in PRODUCT_RE.finditer(claim)]
    targets = {line["id"] for line in lines if not products or any(
        _product_supported(product, {line["product_ref"]}) for product in products)}
    if products and any(not any(_product_supported(product, {line["product_ref"]}) for line in lines) for product in products):
        return [c for c in confirmed if "scope_spec" not in c]
    return [c for c in confirmed if "scope_spec" not in c or
            (targets and targets.issubset(set(c.get("preferred_line_ids", c.get("applicable_line_ids", []))))) or
            (not lines and c["scope_spec"].get("global") is True)]


def validate_draft(draft, understanding, registry, values, *, semantic_checked=False):
    """Validate a proposed draft without creating a reply or changing evidence."""
    if not isinstance(draft, str) or not draft.strip():
        return {"passed": False, "issues": ["empty_draft"], "checked": [],
                "limitations": ["No reply workflow is implemented in P0-P2."]}
    by_id = {s["id"]: s for s in registry.get("sources", [])}
    candidates = list(understanding.get("candidates", []))
    if isinstance(values, dict):
        values = values.get("candidates", values.get("values", []))
    # A ValueStore decision for an id overrides the raw understanding candidate.
    # Rejected evidence remains in the ledger but never grants admission.
    keyed = {c.get("id"): c for c in candidates if isinstance(c, dict)}
    keyed.update({c.get("id"): c for c in (values or []) if isinstance(c, dict)})
    candidates = list(keyed.values())
    active = {"customer_stated", "system_reported", "public_reference", "working_value", "company_confirmed"}
    admitted = [c for c in candidates if _status(c) in active and _source_valid(c, by_id)
                and c.get("active", True) and c.get("applicable", True)
                and (c.get("preferred", True) or c.get("resolution") == "unresolved")]
    issues = []
    for c in candidates:
        if _status(c) in active and c.get("active", True) and c.get("applicable", True) and not _source_valid(c, by_id):
            issues.append("invalid_value_provenance:" + str(c.get("id", "unknown") if isinstance(c, dict) else "unknown"))
    confirmed = [c for c in admitted if _status(c) == "company_confirmed" and c.get("resolution") != "unresolved" and
                 by_id[c["source_id"]].get("kind") in {"company_context", "operator_input"} and
                 by_id[c["source_id"]].get("party") == "company"]
    grouped = {}
    for c in confirmed:
        grouped.setdefault((c.get("key"), c.get("scope")), []).append(c)
    conflicts = {group for group, cs in grouped.items() if any(
        (c.get("value"), c.get("unit"), c.get("conditions", [])) !=
        (cs[0].get("value"), cs[0].get("unit"), cs[0].get("conditions", [])) for c in cs)}
    # A retained conflicting confirmation is evidence of a dispute, not current
    # authority to silently select whichever value appears in the draft.
    confirmed = [c for c in confirmed if (c.get("key"), c.get("scope")) not in conflicts]
    bounded_confirmed = []
    for candidate in confirmed:
        source = by_id[candidate["source_id"]]["text"]
        start, end = candidate["provenance"]["span"]
        left = max(source.rfind(mark, 0, start) for mark in ".!?。！？\n") + 1
        ends = [source.find(mark, end) for mark in ".!?。！？\n"]
        right = min((position for position in ends if position >= 0), default=len(source))
        bounded_confirmed.append({**candidate, "_authority_quote": source[left:right]})
    confirmed = bounded_confirmed
    allowed_products = {canonical_product(str(c.get("value"))) for c in admitted if c.get("key") == "product"}
    for c in admitted:
        if str(c.get("key", "")) == "capability.products":
            allowed_products.update(canonical_product(m.group()) for v in _raw_values(c.get("value")) for m in PRODUCT_RE.finditer(str(v)))
    for m in PRODUCT_RE.finditer(draft):
        if not _product_supported(m.group(), allowed_products):
            issues.append("unsupported_product:" + canonical_product(m.group()))

    allowed_numbers = set()
    for c in admitted:
        for v in _raw_values(c.get("value")):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                allowed_numbers.add(v)
            elif isinstance(v, str):
                allowed_numbers.update(_numeric_tokens(v))
    for line in understanding.get("lines", []):
        for cue in line.get("spec_cues", []):
            source = by_id.get(cue.get("source_id"), {})
            span = cue.get("span", [])
            if source.get("status") == "read" and len(span) == 2 and source.get("text", "")[span[0]:span[1]] == cue.get("text"):
                allowed_numbers.update(_numeric_tokens(cue["text"]))
    for n in _numeric_tokens(draft):
        if n not in allowed_numbers:
            issues.append("unsupported_number:" + str(n))
    currency_aliases = {"$": "USD", "€": "EUR", "£": "GBP"}
    for m in AMOUNT_RE.finditer(draft):
        amount = _number(m.group(1))
        currency = re.match(r"USD|EUR|GBP|[$€£]", m.group(), re.I).group().upper()
        currency = currency_aliases.get(currency, currency)
        supported = [c for c in admitted if str(c.get("key", "")).lower() in
                     {"amount", "price", "target_price", "sample_price", "bulk_price"} and c.get("value") == amount]
        if not any(currency_aliases.get(str(c.get("unit", "")).upper(), str(c.get("unit", "")).upper()) == currency for c in supported):
            issues.append("unsupported_amount_or_currency")
    allowed_dates = {str(c["value"]).lower() for c in admitted if c.get("key") == "date"}
    for m in DATE_RE.finditer(draft):
        if m.group().lower() not in allowed_dates:
            issues.append("unsupported_date:" + m.group())
    allowed_terms = {re.sub(r"\s+", "", str(c["value"])).upper() for c in admitted if c.get("key") == "payment_terms"}
    for m in PAYMENT_RE.finditer(draft):
        term = re.sub(r"\s+", "", m.group()).upper()
        if term not in allowed_terms:
            issues.append("unsupported_payment_term:" + term)

    quantity_candidates = [c for c in admitted if c.get("key") == "quantity" or
                           str(c.get("key", "")).lower().startswith("moq")]
    previous_quantity_end = 0
    for m in QTY_RE.finditer(draft):
        a = _number(m.group("first"))
        b = _number(m.group("second")) if m.group("second") else None
        value = {"min": a, "max": b} if b is not None else a
        local = draft[max(0, m.start()-60):min(len(draft), m.end()+65)]
        nearby_products = [canonical_product(p.group()) for p in PRODUCT_RE.finditer(local)]
        eligible = quantity_candidates
        if nearby_products:
            line_ids = {l["id"] for l in understanding.get("lines", []) if any(_product_supported(p, {l["product_ref"]}) for p in nearby_products)}
            bound = [c for c in eligible if c.get("line_id") in line_ids or str(c.get("key", "")).lower().startswith("moq")]
            if bound:
                eligible = bound
        matched = [c for c in eligible if c.get("value") == value]
        if not matched:
            if any(isinstance(c.get("value"), dict) and a in c["value"].values() for c in eligible):
                issues.append("range_collapsed")
            else:
                issues.append("unsupported_quantity:" + str(value))
            continue
        qualifier = _qualifier(m.group("qual"), b)
        boundary = max(draft.rfind(c, 0, m.start()) for c in ".!?\n,;，；") + 1
        hedge_prefix = draft[max(boundary, previous_quantity_end, m.start()-55):m.start()]
        previous_quantity_end = m.end()
        if qualifier == "exact" and re.search(r"\b(?:approximate|approximately|roughly|about|around)\b|约|大约|aproximadamente", hedge_prefix, re.I):
            qualifier = "approximate"
        observed_approximate = bool(m.group("qual") and _qualifier(m.group("qual"), None) == "approximate") or bool(HEDGE_RE.search(hedge_prefix))
        if not any(c.get("qualifier", "exact") == qualifier for c in matched):
            issues.append("quantity_qualifier_changed")
        if b is not None and not any(bool(c.get("approximate")) == observed_approximate for c in matched):
            issues.append("quantity_hedge_changed")
        if any(c.get("status") in {"customer_stated", "system_reported", "public_reference", "working_value"} for c in matched):
            if re.search(r"confirmed\s+order|your\s+order|order\s+of|已确认订单|您的订单|pedido\s+confirmado", local, re.I):
                issues.append("interest_stated_as_order")

    for sentence in _sentences(draft):
        # A leading "For <product>," qualifies following clauses. Preserve it
        # for scope binding while keeping separate promises/negations local.
        prefix = re.match(r"^(?:for|regarding|对于|针对)\s*([^,，;；]+)[,，]", sentence, re.I)
        product_prefix = prefix.group(1) if prefix and PRODUCT_RE.search(prefix.group(1)) else ""
        for claim in re.split(r"[,;，；]|\bbut\b|\bpero\b", sentence, flags=re.I):
            # Negation applies to its own clause only, not an earlier promise.
            cleaned = re.sub(r"\bno\s+podemos\b|(?:我司|我们|本公司)(?:不能|不支持|无法)", "", claim, flags=re.I)
            scope_claim = cleaned if PRODUCT_RE.search(cleaned) else product_prefix + " " + cleaned
            verification = re.search(r"\b(?:check|verify|confirm|review|assess)\b.{0,45}\b(?:whether|if|ability|options|possibility)\b", cleaned, re.I)
            if POSITIVE_COMPANY_RE.search(cleaned) and not verification and not _confirmation_covers(cleaned, _scoped_authority(scope_claim, confirmed, understanding)):
                issues.append("unsupported_company_capability")
    unread = [s for s in registry.get("sources", []) if s.get("kind") == "attachment" and s.get("status") != "read"]
    if unread and re.search(r"(?:not|haven't|hasn't)\s+(?:provided|sent|supplied)|(?:missing|no)\s+(?:drawing|tech\s*pack|attachment|specification)|未提供|没有提供|未给|no\s+(?:has|ha)\s+(?:enviado|proporcionado)", draft, re.I):
        issues.append("coverage_gap_stated_as_not_provided")
    if re.search(r"\b(?:we\s+(?:have\s+)?attached|(?:please\s+)?find\s+attached|I\s+(?:have\s+)?attached)\b|已附上|adjunt[oa]", draft, re.I):
        attached = [s for s in registry.get("sources", []) if s.get("party") == "company" and s.get("metadata", {}).get("actually_attached") is True]
        if not attached:
            issues.append("unsupported_attachment_claim")
    # Unknown authority and coverage are preserved. Passing these implemented
    # gates does not imply all meaning-bearing nouns or assertions were parsed.
    return {"passed": not issues, "issues": list(dict.fromkeys(issues)),
            "checked": ["source_exact", "quantity_type", "qualifier_fidelity", "payment_token",
                        "product_admission", "number_date_admission", "company_authority", "coverage_honesty"],
            "limitations": ["Product admission uses a bounded garment vocabulary; open-vocabulary semantic correctness is not certified.",
                            "No complete reply workflow or business sufficiency score is implemented in P0-P2."]}
