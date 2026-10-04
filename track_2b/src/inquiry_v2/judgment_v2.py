"""Choose one reversible inquiry advance from validated lines and scoped values.

This layer does not compose replies, infer company authority from customer text,
or execute commercial actions. Unknowns remain visible without becoming an
automatic customer questionnaire.
"""

import json
import re


_PRODUCT_FAMILIES = {
    "weatherwear": {"rainwear", "weatherwear", "shell", "shells", "cape", "capes", "poncho", "ponchos", "overshirt", "overshirts", "jacket", "jackets", "coat", "coats", "raincoat", "raincoats"},
    "vest": {"vest", "vests", "waistcoat", "waistcoats", "chaleco", "chalecos"},
    "bottoms": {"shorts", "trousers", "pants", "leggings", "bottoms"},
    "bags": {"tote", "totes", "bag", "bags", "backpack", "backpacks"},
    "tops": {"shirt", "shirts", "polo", "polos", "blouse", "blouses", "tshirt", "tshirts"},
}


def _tokens(text):
    return set(re.findall(r"[a-záéíóúñ]+", str(text).lower()))


def _family(text):
    words = _tokens(text)
    return {name for name, vocabulary in _PRODUCT_FAMILIES.items() if words & vocabulary}


def _sources(registry):
    sources = registry.get("sources", []) if isinstance(registry, dict) else getattr(registry, "sources", [])
    return list(sources.values()) if isinstance(sources, dict) else list(sources)


def _read_text(sources):
    return "\n".join(str(source.get("text", "")) for source in sources
                     if source.get("status") in {"read", "parsed"}
                     and source.get("party") == "customer")


def _value_list(values):
    if isinstance(values, list):
        return values
    if isinstance(values, dict):
        return values.get("candidates", values.get("values", []))
    return getattr(values, "candidates", [])


def _scope_applies(candidate, line=None):
    if not candidate.get("active", True) or not candidate.get("applicable", True):
        return False
    if "scope_spec" in candidate:
        if not candidate.get("preferred", True) and candidate.get("resolution") != "unresolved":
            return False
        allowed = candidate.get("preferred_line_ids", candidate.get("applicable_line_ids", []))
        if candidate.get("resolution") == "unresolved":
            allowed = candidate.get("applicable_line_ids", [])
        return line is None or line.get("id") in allowed or candidate["scope_spec"].get("global") and not allowed
    scope = str(candidate.get("scope", "")).lower()
    if scope in {"company.default", "company.global", "company.all", "company.all_styles", "bulk.per_style", "all styles", "all", "default"}:
        return True
    if line is None:
        return False
    line_id = str(line.get("id", ""))
    if scope in {line_id.lower(), "line:" + line_id.lower(), "line." + line_id.lower()}:
        return True
    if scope.startswith(("product:", "company.product:")):
        category = scope.rsplit(":", 1)[-1]
        return bool(_family(category) & _family(line.get("product_ref", ""))) or category == str(line.get("product_ref", "")).lower()
    return False


def _confirmed(values, key, line=None):
    pool = [value for value in values if value.get("key") == key
            and value.get("status") == "company_confirmed" and _scope_applies(value, line)]
    if line is not None:
        specific = [value for value in pool if str(value.get("scope", "")).lower().startswith(("line:", "line.", "product:", "company.product:"))
                    or str(value.get("scope", "")).lower() == str(line.get("id", "")).lower()]
        return specific or pool
    return pool


def _conflicts(candidates):
    if any(c.get("resolution") == "unresolved" for c in candidates):
        return True
    groups = {}
    for candidate in candidates:
        identity = {"value": candidate.get("value"), "unit": candidate.get("unit"), "conditions": candidate.get("conditions") or []}
        groups.setdefault(candidate.get("scope"), set()).add(json.dumps(identity, sort_keys=True, ensure_ascii=False))
    return any(len(group) > 1 for group in groups.values())


def _piece_per_style(candidate):
    unit = str(candidate.get("unit") or "").lower().strip()
    unit = re.sub(r"\s+", " ", unit.replace("_", " "))
    return bool(re.fullmatch(r"(?:pcs?|pieces?)\s*(?:/|per)\s*style", unit))


def _quantity_bounds(line):
    quantity = line.get("quantity")
    if isinstance(quantity, (int, float)) and not isinstance(quantity, bool) and quantity > 0:
        if line.get("quantity_qualifier") == "minimum":
            return quantity, float("inf")
        if line.get("quantity_qualifier") == "maximum":
            return 0, quantity
        return quantity, quantity
    if isinstance(quantity, dict):
        low = quantity.get("min", quantity.get("value"))
        high = quantity.get("max", quantity.get("value", low))
        if isinstance(low, (int, float)) and low > 0 and isinstance(high, (int, float)) and high >= low:
            return low, high
    return None


def _purpose(line):
    return {"evaluation_sample": "sample", "bulk_interest": "bulk"}.get(
        line.get("quantity_purpose"), line.get("quantity_purpose", "unknown"))


def _line_context(sources, lines):
    by_id = {source.get("id"): source for source in sources if source.get("status") in {"read", "parsed"}}
    pieces = []
    for line in lines:
        source = by_id.get(line.get("source_id"))
        span = line.get("span")
        if source and isinstance(span, list) and len(span) == 2:
            text = source.get("text", "")
            start, end = span
            left = max(text.rfind(char, 0, start) for char in ".?!\n") + 1
            right = [text.find(char, end) for char in ".?!\n"]
            right = min([pos for pos in right if pos >= 0], default=len(text))
            pieces.append(text[left:right])
    return " ".join(pieces)


def _evidence_ids(lines, asks=()):
    result = []
    for item in list(lines) + list(asks):
        result.extend(item.get("evidence_ids", []))
        if item.get("evidence_id"):
            result.append(item["evidence_id"])
        for cue in item.get("spec_cues", []):
            if cue.get("evidence_id"):
                result.append(cue["evidence_id"])
    return list(dict.fromkeys(result))


def _asset_status(sources, line, words):
    """Distinguish an available source, unread reference and absent source."""
    relevant = []
    for source in sources:
        metadata = source.get("metadata") or {}
        name = " ".join(str(source.get(field, "")) for field in ("name", "text")) + " " + str(metadata.get("name", ""))
        if source.get("kind") in {"attachment", "referenced_url", "public_source"} and any(word in name.lower() for word in words):
            relevant.append(source.get("status"))
    if any(status in {"read", "parsed"} for status in relevant):
        return "read"
    if relevant:
        return "referenced_unread"
    return "absent"


def _question(language, field, product=""):
    translations = {
        "quantity": ("What quantity do you want to assess for this item?", "¿Qué cantidad necesitas para este modelo?", "这款产品希望先评估多少件？"),
        "customization": ("Do you want the referenced model unchanged or with custom changes?", "¿Buscas el modelo sin cambios o una versión personalizada?", "需要现成款不变，还是希望定制修改？"),
        "quantity_purpose": ("Is the stated volume your production plan or only an evaluation reference?", "¿La cantidad indicada es un plan de producción o solo una referencia de evaluación?", "所列数量是希望评估的生产计划，还是仅作试样参考？"),
        "quantity_flexibility": ("Could the standard production quantity work for one priority style?", "¿Podría funcionar la cantidad mínima de producción para un modelo prioritario?", "能否按标准生产起订量先做一个优先款？"),
        "product_reference": ("Please share a reference for the first item you want to assess.", "¿Puedes compartir una referencia del primer modelo que quieres evaluar?", "请提供最想先评估的那一款产品参考。"),
        "drawing": ("Please share the existing dimensioned drawing for the prototype review.", "¿Puedes compartir el dibujo con medidas que ya tienes para revisar el prototipo?", "请提供已有的尺寸图，用于原型技术评审。"),
        "material_reference": ("Do you already have a preferred material reference?", "¿Tienes una referencia de material preferida?", "是否已有优先采用的材料型号或参考？"),
        "logo_reference": ("Please share the logo or its placement reference for the sample review.", "¿Puedes compartir el logotipo o una referencia de su posición para revisar la muestra?", "请提供标志或位置参考，用于评估试样工艺。"),
    }
    row = translations[field]
    return row[1] if language == "es" else row[2] if language == "zh" else row[0]


def judge(understanding, registry, values, research):
    """Return assessment and a single preferred advance, preserving Unknown."""
    sources = _sources(registry)
    values = _value_list(values)
    research = research or {}
    lines = [line for line in understanding.get("lines", []) if line.get("stage", "current") != "future"]
    asks = understanding.get("customer_asks", [])
    asks = [ask if isinstance(ask, dict) else {"text": str(ask)} for ask in asks]
    asks = [ask for ask in asks if ask.get("stage") != "future"]
    evidence_ids = _evidence_ids(lines, asks)
    text = _read_text(sources)
    ask_text = " ".join(str(ask.get("text", "")) for ask in asks)
    cue_text = " ".join(str(cue.get("text", "")) for line in lines for cue in line.get("spec_cues", []))
    operative_text = " ".join([ask_text, cue_text, _line_context(sources, lines)]).lower()
    language = understanding.get("customer_language", "en")
    primary = lines[0] if lines else {"id": None, "product_ref": "", "spec_cues": []}
    checks = []
    questions = []
    assumptions = []
    used_value_ids = []
    boundaries = ["No automatic email, quote release, purchase, payment or production.",
                  "Company capability, sourcing rights, stock, prices, performance and dates require scoped company confirmation and human approval."]

    def check(field, task, owner, trigger="Before a firm commercial commitment", blocks=False):
        if not any(item["field"] == field for item in checks):
            checks.append({"field": field, "task": task, "owner": owner, "status": "pending", "blocks_this_step": blocks, "trigger": trigger})

    def supported_working_value(field, line):
        keys = {field, "line." + field, "inquiry." + field}
        supporting = [value for value in values if value.get("status") == "working_value" and value.get("key") in keys
                      and _scope_applies(value, line) and value.get("provenance", {}).get("confirmation_point")]
        used_value_ids.extend(value["id"] for value in supporting if value.get("id"))
        return bool(supporting)

    def question(field, line, changes):
        if len(questions) >= 3 or supported_working_value(field, line):
            return
        # The validated line already carries body/thread/parsed-attachment facts.
        if field == "quantity" and _quantity_bounds(line):
            return
        if field == "customization":
            source_map = {source.get("id"): source for source in sources}
            customer_cues = [cue for cue in line.get("spec_cues", []) if source_map.get(cue.get("source_id"), {}).get("party") == "customer"
                             and cue.get("kind") in {"construction", "drawing"}]
            if customer_cues or re.search(r"\b(?:unchanged|same model|sin cambios|no\s+logo\s+changes|without\s+changes|(?:want|need|request|busco|necesito).{0,40}(?:custom\w*|personaliz\w*))\b", text, re.I):
                return
        if field in {"drawing", "product_reference", "logo_reference"}:
            words = {"drawing": ["drawing", "dimension", "tech pack", "dibujo"],
                     "product_reference": ["reference", "listing", "design", "drawing", "model"],
                     "logo_reference": ["logo", "placement"]}[field]
            asset = _asset_status(sources, line, words)
            if asset != "absent":
                if asset != "read":
                    check(field, "Read the already referenced source; retain Unknown until inspected.", "sales+technical", "Before asking the customer to resend information")
                return
        questions.append({"field": field, "line_id": line.get("id"), "question": _question(language, field, line.get("product_ref", "")),
                          "changes_decision": changes, "no_re_ask_basis": "Not answered in admitted current lines or readable sources; no scoped reversible working value supports this decision.",
                          "evidence_ids": _evidence_ids([line])})

    capabilities = _confirmed(values, "capability.products")
    used_value_ids.extend(value["id"] for value in capabilities if value.get("id"))
    capability_conflict = _conflicts(capabilities)
    capability_names = []
    for candidate in capabilities:
        value = candidate.get("value")
        capability_names.extend(value if isinstance(value, list) else [str(value)])
    known_families = set().union(*[_family(name) for name in capability_names]) if capability_names else set()
    outside = [line for line in lines if capability_names and not (
        _family(line.get("product_ref", "")) & known_families
        or any(_tokens(name) & _tokens(line.get("product_ref", "")) for name in capability_names))]
    fit_status = "needs_internal_review" if outside or capability_conflict else "fit" if capability_names and lines else "explorable"
    fit = {"status": fit_status, "basis": [value.get("id") for value in capabilities if value.get("id")],
           "current_line_ids": [line.get("id") for line in lines], "note": "Confirmed category scope supports review only; it does not confirm this construction or performance." if fit_status == "fit" else "Unknown or outside confirmed scope requires internal review, not rejection based on buyer identity."}
    identity = understanding.get("buyer_identity", {})
    if not isinstance(identity, dict):
        identity = {}
    identity_status = identity.get("status", "unverified")
    if identity_status not in {"verified", "partial", "unverified", "contradictory"}:
        identity_status = "unverified"
    if identity_status == "verified" and not identity.get("evidence_ids"):
        identity_status = "unverified"
    identity_research_done = bool(identity.get("research_done") and identity.get("evidence_ids"))
    buyer_identity = {"status": identity_status, "research_done": identity_research_done,
                      "research_reason": research.get("reason") or "Buyer verification would not change this reversible first-inquiry step."}
    declared_scope = _confirmed(values, "capability.declared_scope")
    if declared_scope:
        used_value_ids.extend(value["id"] for value in declared_scope if value.get("id"))
        check("declared_company_scope", "Review the literal scoped capability source for applicability to the current item; do not infer unsupported translated capabilities.", "technical", "Before any specific capability claim")

    for source in sources:
        if source.get("status") in {"referenced_unread", "unavailable"} and source.get("kind") in {"attachment", "thread_message", "referenced_url"}:
            check("source:" + str(source.get("id")), "Inspect or recover the existing referenced source; do not describe unread content as not provided.", "sales+technical", "Before a dependent decision or a customer re-ask")

    purposes = {_purpose(line) for line in lines}
    prototype_lines = [line for line in lines if _purpose(line) == "prototype"]
    sample_lines = [line for line in lines if _purpose(line) == "sample"]
    quantity_candidates = {candidate.get("id"): candidate for candidate in understanding.get("candidates", [])}
    quantity_candidates.update({value.get("id"): value for value in values if value.get("key") == "quantity"})

    def plan_quantity(line):
        candidate = quantity_candidates.get(line.get("selected_quantity_candidate_id"), {})
        return candidate.get("status") not in {"rejected", "system_reported"} and candidate.get("semantic_stance") not in {"negated", "prohibited_action"}

    bulk_lines = [line for line in lines if _purpose(line) in {"bulk", "quote_tier", "unknown"} and _quantity_bounds(line) and plan_quantity(line)]
    licensed = bool(re.search(r"\b(licensed|licensing|genuine|traceability|authori[sz]ed|branded.material|supplier account)\b", operative_text))
    moq_conflict = False
    moq_unit_unknown = False
    below_moq = []
    below_general_moq = []
    for line in bulk_lines:
        candidates = _confirmed(values, "moq.style", line)
        used_value_ids.extend(value["id"] for value in candidates if value.get("id"))
        if _conflicts(candidates):
            moq_conflict = True
            continue
        for candidate in candidates:
            if not _piece_per_style(candidate):
                moq_unit_unknown = True
                check("moq_quantity_unit", "Verify the MOQ count unit and basis; sets, pairs or an unspecified unit cannot be compared with a piece quantity without confirmation.", "sales+management", "Before MOQ comparison", True)
                continue
            minimum = candidate.get("value")
            if isinstance(minimum, (int, float)) and not isinstance(minimum, bool) and minimum > 0 and _quantity_bounds(line)[0] < minimum:
                below_moq.append(line)
                break
        general_candidates = _confirmed(values, "moq.general", line)
        if general_candidates:
            used_value_ids.extend(value["id"] for value in general_candidates if value.get("id"))
            check("general_moq_scope", "Verify how the literal general MOQ applies to this product and quantity basis; do not promote it to per-style or per-colour policy.", "sales+management", "Before quoting an applicable MOQ or an exception")
            if _conflicts(general_candidates):
                moq_conflict = True
            elif not candidates and any(isinstance(value.get("value"), (int, float)) and not isinstance(value.get("value"), bool)
                                        and _quantity_bounds(line)[0] < value["value"] for value in general_candidates):
                below_general_moq.append(line)

    stage = understanding.get("stage", "new_lead")
    quantity_conflict = any(str(issue).startswith("line_quantity_conflict:") for issue in understanding.get("issues", []))
    rejected_ids = {value.get("id") for value in values if value.get("status") == "rejected"}
    quantity_rejected = any(line.get("quantity") is not None and line.get("selected_quantity_candidate_id") in rejected_ids for line in lines)
    if stage in {"out_of_scope", "confirmed_order", "order", "existing_order", "payment", "production", "sample_test"}:
        action, owner, reason, next_state = "OUT_OF_SCOPE", "business_owner", "This source concerns a committed order or a later operational stage, outside new-inquiry judgment.", "Human routing to the existing project owner"
        uncertainty = ("Appropriate existing-project owner and authorised next step", "C", "business_owner", "Which operational workflow may handle the request")
        barrier = ("business_owner", "A new-inquiry contract cannot authorise execution of an existing commercial commitment.")
    elif quantity_conflict or quantity_rejected:
        action, owner, reason, next_state = "INTERNAL_VERIFICATION", "sales", "A same-line quantity conflict or rejected selected candidate must be resolved before using a quantity basis; distinct products remain distinct lines.", "One admitted quantity purpose and basis for the relevant line"
        uncertainty = ("Applicable source-backed quantity basis for this line", "B", "read source/thread first; customer only if unresolved", "Which quantity may support the next costing decision")
        barrier = ("sales", "The quantity basis is unresolved, so choosing one candidate would conceal a conflict or use rejected evidence.")
        check("quantity_basis", "Compare the same-line candidates, purposes and original source context without choosing an arbitrary value.", "sales", "Before quantity-dependent costing", True)
    elif capability_conflict or moq_conflict or moq_unit_unknown:
        action, owner, reason, next_state = "INTERNAL_VERIFICATION", "business_owner+sales", "Conflicting scoped company-confirmed candidates require adjudication; no latest-value overwrite is allowed.", "One applicable company policy selected by its accountable owner"
        uncertainty = ("Which scoped company candidate applies", "C", "business_owner", "Whether a category or quantity route is authorised")
        barrier = ("business_owner", "Company candidates disagree in value, unit or conditions, or the count unit is not established for this comparison.")
        if capability_conflict or moq_conflict:
            check("company_value_conflict", "Review all conflicting candidates, units, conditions and provenance without deleting any candidate.", "business_owner", "Before stating the disputed company policy", True)
        if moq_unit_unknown and not (capability_conflict or moq_conflict):
            reason = "The confirmed MOQ uses an unestablished count unit or basis; it cannot yet be compared with a piece quantity."
    elif licensed:
        action, owner, reason, next_state = "INTERNAL_VERIFICATION", "purchasing+sales", "The actual sourcing and documented sample-access route are company-side unknowns; a buyer's missing supplier account is not a hard stop.", "Verified sourcing options and evidence available for human review"
        uncertainty = ("Actual licensed sourcing and documented reference access", "C", "purchasing", "Whether the requested material and evidence can be offered")
        barrier = ("purchasing", "Sourcing rights, traceability and supply evidence have not been verified internally.")
        check("licensed_sourcing", "Verify the named material/supplier route, rights and documented provenance; label alternatives separately.", "purchasing")
        check("stock_and_certification", "Verify actual availability and applicable certificates before any claim.", "purchasing+technical")
        if not any(cue.get("kind") in {"material_reference", "material_brand", "supplier_reference"} for line in lines for cue in line.get("spec_cues", [])):
            question("material_reference", primary, "A preferred material reference narrows the supplier route to verify.")
    elif outside:
        action, owner, reason, next_state = "ASSESS_COMPANY_FIT", "business_owner+sales", "Review the current requested categories against confirmed scope; future ambitions do not establish present fit.", "A decision to pursue one current item and its production route"
        uncertainty = ("Current-item fit and justified development effort", "C", "business_owner", "Whether to pursue this category")
        barrier = ("business_owner", "The current items are outside the confirmed category view, so pursuit needs a scope decision.")
        check("current_category_fit", "Assess only current lines against actual production scope and resource budget.", "business_owner+technical", "Before committing development resources")
        if not primary.get("spec_cues"):
            question("product_reference", primary, "A reference for one current item supports a concrete fit decision.")
    elif prototype_lines:
        primary = prototype_lines[0]
        has_brief = bool(primary.get("spec_cues")) or _asset_status(sources, primary, ["drawing", "dimension", "tech pack"]) == "read"
        action = "INTERNAL_COSTING" if has_brief else "INTERNAL_VERIFICATION"
        owner, reason, next_state = "technical+sample_coordinator", "A prototype is a development unit. Review its existing working brief and preliminary development costs without applying bulk MOQ.", "A scoped prototype method, development cost basis and approval point"
        uncertainty = ("Prototype construction route and development cost basis", "C", "technical+sample_coordinator", "Which pattern/sample method and budget to propose")
        barrier = ("technical", "A development method and budget require review before accepting spend or promising performance.")
        check("prototype_review", "Review the existing brief and drawing; scope pattern work and preliminary development costing.", "technical+sample_coordinator", "Before accepting development charges")
        check("performance_evidence", "Define which performance requires supplier evidence or testing; do not promise results.", "technical", "Before any performance or certification claim")
        if _asset_status(sources, primary, ["drawing", "dimension", "tech pack"]) == "absent" and re.search(r"\b(drawing|dimensioned|tech.pack|dibujo)\b", operative_text):
            question("drawing", primary, "The existing dimensioned source sets the pattern-work basis.")
        assumptions.append({"value": "Use the admitted working brief for reversible preliminary development review, not final production specifications.", "scope": "development", "owner": "technical", "confirmation_point": "Before accepting development spend", "evidence_ids": _evidence_ids([primary])})
    elif sample_lines:
        primary = sample_lines[0]
        action, owner, reason, next_state = "VERIFY_SAMPLE_ROUTE", "sales+sample_coordinator", "The customer explicitly requests evaluation before a production decision; interested or platform quantities are not a confirmed order.", "A verified sample/customisation method and cost basis"
        uncertainty = ("Available evaluation sample and customisation route", "C", "sample_coordinator", "Which sample option may be proposed")
        barrier = ("sample_coordinator", "Actual sample availability, method and cost require internal confirmation.")
        check("sample_route", "Check the requested model's actual evaluation route and sample cost, separately from bulk interest.", "sample_coordinator")
        check("sample_stock_dispatch", "Confirm availability and dispatch only after the route is approved.", "sales+sample_coordinator")
        if re.search(r"\b(logo|logotipo)\b", operative_text):
            check("logo_method", "Assess logo position and applicable method; do not promise a process before review.", "technical")
            if not any(cue.get("kind") in {"logo", "logo_reference", "placement"} for cue in primary.get("spec_cues", [])):
                question("logo_reference", primary, "The actual logo/placement determines the sample method and cost.")
    elif "personal_purchase" in purposes and not bulk_lines:
        action, owner, reason, next_state = "INTERNAL_VERIFICATION", "sales", "A personal purchase quantity does not establish a bulk order; verify an actual retail or available-model route without inventing stock or applying bulk MOQ as a rejection.", "A verified available-model route or a clear human-reviewed boundary"
        uncertainty = ("Whether an actual personal-purchase route exists", "C", "sales", "Whether a stocked/reference model can be offered")
        barrier = ("sales", "Retail availability and company policy have not been confirmed.")
        check("personal_purchase_route", "Verify an actual available-model route and applicable company policy.", "sales")
    elif below_moq:
        primary = below_moq[0]
        action, owner, reason, next_state = "ALIGN_MOQ", "sales+technical", "The bulk plan includes a volume below an applicable confirmed per-style MOQ; align a viable volume band and assess any internally approved exception.", "One viable priority style and quantity route for technical/cost review"
        flexible_known = bool(re.search(r"\b(flexible|can increase|cannot increase|can not increase|maximum|not negotiable|no podemos aumentar)\b", text, re.I))
        uncertainty = ("Approved low-volume route" if flexible_known else "Launch quantity flexibility", "C" if flexible_known else "B", "sales+management" if flexible_known else "customer", "Standard-volume route versus an exception review")
        barrier = ("sales+management", "A below-MOQ production exception has not been approved.")
        check("below_moq_exception", "Assess the below-MOQ option without treating it as approved or inventing a price.", "sales+management", "Before a below-MOQ quote")
        check("colour_material_minimum", "Verify colour and material minimums separately from per-style MOQ.", "purchasing+technical")
        check("priority_design_review", "Inspect the customer's existing priority design/reference rather than restarting a full specification questionnaire.", "technical")
        if not flexible_known:
            question("quantity_flexibility", primary, "Quantity flexibility determines standard production versus exception assessment.")
    elif below_general_moq:
        action, owner, reason, next_state = "INTERNAL_VERIFICATION", "sales+management", "The volume may fall below a declared general MOQ, whose product and count basis are not confirmed as per-style; verify applicability without inventing a more specific policy.", "An applicable MOQ scope and authorised quantity route"
        uncertainty = ("Applicability and counting basis of the general MOQ", "C", "sales+management", "Which quantity policy and exception route applies")
        barrier = ("sales+management", "The general MOQ cannot yet be represented as per-style or per-colour policy.")
    elif bulk_lines and any(line.get("product_ref") for line in bulk_lines):
        primary = bulk_lines[0]
        action, owner, reason, next_state = "INTERNAL_COSTING", "sales+technical+purchasing", "The admitted product and quantity basis support preliminary internal costing; unknown final specifications, buyer identity, stock or freight do not prevent this reversible review.", "A scoped rough cost basis and a short internal verification list"
        uncertainty = ("Material and construction cost basis", "C", "technical+purchasing", "The assumptions that must be confirmed before a firm quote")
        barrier = ("sales", "Firm quotation needs confirmed construction, costing assumptions and commercial approval; rough review can proceed now.")
        check("construction_cost_basis", "Review stated material/construction cues and document remaining costing assumptions rather than requiring a global specification field.", "technical+purchasing", "Before a firm quote")
        check("company_scope", "Confirm that this specific construction can follow a company production route.", "technical", "Before a capability commitment")
        check("quote_release", "Approve the scoped cost and commercial terms before release.", "sales+management", "Before a firm quote")
        assumptions.append({"value": "Review the admitted product and quantity as a preliminary cost brief; final construction and commercial terms remain Unknown until confirmed.", "scope": "rough_costing", "owner": "technical+purchasing", "confirmation_point": "Before a firm quote", "evidence_ids": _evidence_ids(bulk_lines)})
    else:
        action, owner, reason, next_state = "REQUEST_INFORMATION", "sales", "Only the decision variables needed to distinguish the next product/quantity route are requested; a full quote questionnaire is unnecessary.", "A minimal product and quantity/customisation basis for internal review"
        missing_quantity = next((line for line in lines if not _quantity_bounds(line)), None)
        if not lines or not primary.get("product_ref"):
            uncertainty = ("Current product reference", "B", "customer or the already referenced source", "Which product route to evaluate")
            barrier = ("sales", "No admitted current product reference identifies a concrete costing/review route.")
            question("product_reference", primary, "A current product reference identifies the next production/review route.")
        else:
            uncertainty = ("Requested quantity and unchanged/customised route", "B", "customer", "Whether to assess a sample, production quantity or custom development")
            barrier = ("sales", "The current quotation request has no usable production quantity basis yet.")
            if missing_quantity:
                question("quantity", missing_quantity, "Quantity determines the sample/production route and costing basis.")
            elif _quantity_bounds(primary) and not plan_quantity(primary):
                question("quantity_purpose", primary, "A platform report or prohibited shipment quantity does not establish the customer's actual production-plan basis.")
            question("customization", primary, "Unchanged versus custom construction determines which cost basis to review.")
        unread_brief = any(source.get("kind") == "attachment" and source.get("status") not in {"read", "parsed"} for source in sources) and bool(re.search(r"\b(attached|attachment|brief|tech.pack|drawing)\b", text, re.I))
        if unread_brief:
            action, owner, reason, next_state = "INTERNAL_VERIFICATION", "sales+technical", "Read the supplied working source before treating its quantity or construction as missing customer information.", "A reviewed brief with admitted line facts or a recorded recovery need"
            questions = [item for item in questions if item["field"] not in {"quantity", "customization", "product_reference", "drawing"}]
            uncertainty = ("Contents of the supplied unread brief", "B", "sales+technical source reading", "Which quantity and construction facts are already supplied")
            barrier = ("sales+technical", "The working source has not been inspected, so its coverage cannot justify a customer re-ask.")
        unread_reference = any(source.get("kind") == "referenced_url" and source.get("status") not in {"read", "parsed"} for source in sources)
        if unread_reference and not lines:
            action, owner, reason, next_state = "RESEARCH" if research.get("enabled") else "INTERNAL_VERIFICATION", "sales", "Read the existing product reference before asking the customer to restate it; offline operation keeps the content Unknown.", "A source-backed current product reference or a recorded coverage gap"
            questions = [item for item in questions if item["field"] != "product_reference"]
            uncertainty = ("Contents of the already referenced listing", "A", "targeted reference reading", "Which current product route is relevant")
            barrier = ("sales", "The referenced source has not been read; this is a coverage gap rather than missing customer information.")

    if action == "INTERNAL_COSTING" and re.search(r"\b(?:performance|claim|waterproof|breathab\w*).{0,65}\b(?:must|needs?\s+to).{0,35}\btest", text, re.I):
        uncertainty = ("Performance evidence requiring testing", "D", "technical testing or validated supplier evidence", "Whether a performance claim may later be made; preliminary costing can still proceed")
        check("test_evidence", "Define and verify the required test evidence before any performance claim.", "technical", "Before the dependent performance claim")

    assessment = {"current_key_uncertainty": {"item": uncertainty[0], "klass": uncertainty[1], "verify_with": uncertainty[2], "changes": uncertainty[3]},
                  "decision_barrier": {"owner": barrier[0], "cannot_decide_because": barrier[1]}, "hard_blocker": None,
                  "company_fit": fit, "buyer_identity": buyer_identity}
    advance = {"action": action, "owner": owner, "reason": reason, "next_state": next_state, "evidence_ids": evidence_ids,
               "value_candidate_ids": list(dict.fromkeys(used_value_ids)),
               "internal_checks": checks, "customer_questions": questions, "working_assumptions": assumptions,
               "commitment_boundaries": boundaries, "needs_human_approval": True}
    if action == "INTERNAL_COSTING":
        advance["costing_scope"] = "development" if prototype_lines else "rough"
    return {"assessment": assessment, "advance": advance}
