"""Explicit read coverage. Unread material never becomes missing customer data."""
from copy import deepcopy


def build(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("inquiry"), dict):
        raise ValueError("inquiry object required")
    inquiry = payload["inquiry"]
    primary = inquiry.get("primary")
    if not isinstance(primary, dict) or not isinstance(primary.get("text"), str) or not primary["text"].strip():
        raise ValueError("inquiry.primary.text required")
    if primary.get("status", "read") != "read":
        raise ValueError("primary body must be readable")
    sources, ids = [], set()

    def add(item, kind, party, status, default_id):
        if not isinstance(item, dict):
            raise ValueError("source object required")
        source_id = item.get("id", default_id)
        if not isinstance(source_id, str) or not source_id or source_id in ids:
            raise ValueError("source ids must be unique nonempty strings")
        text = item.get("text", "")
        if not isinstance(text, str):
            raise ValueError("source text must be a string")
        if status == "read" and not text.strip():
            raise ValueError("read source requires text")
        if party not in {"customer", "company", "public", "system", "unknown"}:
            raise ValueError("invalid source party")
        metadata = deepcopy(item.get("metadata", {}))
        if not isinstance(metadata, dict):
            raise ValueError("source metadata must be an object")
        for field in ("name", "subject", "url", "publisher", "access_date", "source_date",
                      "confirmed_by", "confirmed_at", "line_id", "seq", "reference"):
            if field in item:
                metadata[field] = item[field]
        scope = item.get("scope", "inquiry")
        if not isinstance(scope, str) or not scope:
            raise ValueError("source scope required")
        sources.append({"id": source_id, "kind": kind, "party": party, "status": status,
                        "text": text if status == "read" else "", "scope": scope,
                        "metadata": metadata})
        ids.add(source_id)

    add(primary, "customer_email", "customer", "read", "primary")
    thread = inquiry.get("thread", [])
    attachments = inquiry.get("attachments", [])
    references = inquiry.get("referenced_urls", [])
    platform = inquiry.get("platform_fields", [])
    if any(not isinstance(v, list) for v in (thread, attachments, references, platform)):
        raise ValueError("source collections must be arrays")
    if any(not isinstance(item, dict) for item in thread + attachments + platform):
        raise ValueError("source collections require objects")
    if any(not isinstance(item, (dict, str)) for item in references):
        raise ValueError("referenced_urls requires source objects or URLs")
    if inquiry.get("thread_coverage", "none") not in {"none", "partial", "complete"}:
        raise ValueError("invalid thread coverage")
    for index, item in enumerate(thread):
        status = item.get("status", "read")
        if status not in {"read", "referenced_unread", "unavailable"}:
            raise ValueError("invalid thread message status")
        add(item, "thread_message", item.get("party", "unknown"), status, "thread-" + str(index))
    for index, item in enumerate(attachments):
        status = item.get("status", "referenced_unread")
        if status not in {"parsed", "read", "referenced_unread", "unavailable"}:
            raise ValueError("invalid attachment status")
        add(item, "attachment", item.get("party", "customer"),
            "read" if status in {"parsed", "read"} else status, "attachment-" + str(index))
    for index, item in enumerate(references):
        if isinstance(item, str):
            item = {"url": item, "status": "referenced_unread"}
        status = item.get("status", "referenced_unread")
        if status not in {"read", "referenced_unread", "unavailable"}:
            raise ValueError("invalid reference status")
        add(item, "referenced_url", "public", status, "reference-" + str(index))
    for index, item in enumerate(platform):
        item = deepcopy(item)
        if not isinstance(item.get("metadata", {}), dict):
            raise ValueError("platform metadata must be an object")
        item["text"] = str(item.get("value", ""))
        item["metadata"] = {**item.get("metadata", {}), "field": item.get("name"),
                            "value": item.get("value"), "authority": "system_reported"}
        add(item, "platform_field", "system", "read", "platform-" + str(index))
    context = payload.get("company_context") or {}
    if not isinstance(context, dict):
        raise ValueError("company_context must contain sources and candidates")
    if not isinstance(context.get("sources", []), list) or not isinstance(context.get("candidates", []), list):
        raise ValueError("company_context sources and candidates must be arrays")
    for index, item in enumerate(context.get("sources", [])):
        if not isinstance(item, dict) or item.get("status", "read") not in {"read", "referenced_unread", "unavailable"}:
            raise ValueError("invalid company source status")
        add(item, "company_context", "company", item.get("status", "read"), "company-" + str(index))
    research = payload.get("research") or {}
    if not isinstance(research, dict):
        raise ValueError("research object required")
    if not isinstance(research.get("sources", []), list):
        raise ValueError("research sources must be an array")
    for index, item in enumerate(research.get("sources", [])):
        if not isinstance(item, dict) or not all(item.get(k) for k in ("url", "publisher", "access_date")):
            raise ValueError("public research requires url, publisher and access_date")
        if item.get("status", "read") != "read":
            raise ValueError("research sources require retrieved readable text")
        add(item, "public_source", "public", "read", "research-" + str(index))
    gaps = []
    for source in sources:
        if source["status"] != "read":
            gaps.append({"source_id": source["id"], "status": source["status"],
                         "reason": "Referenced material has not been read; not evidence of absence."})
    coverage = {
        "body": {"status": "read", "source_ids": [sources[0]["id"]]},
        "thread": {"status": ("partial" if any(s["kind"] == "thread_message" and s["status"] != "read" for s in sources)
                              else inquiry.get("thread_coverage", "partial" if thread else "none")),
                   "source_ids": [s["id"] for s in sources if s["kind"] == "thread_message"]},
        "attachments": [{"source_id": s["id"], "name": s["metadata"].get("name"),
                         "status": "parsed" if s["status"] == "read" else s["status"]}
                        for s in sources if s["kind"] == "attachment"],
        "company_context": {"status": ("partial" if any(s["kind"] == "company_context" and s["status"] != "read" for s in sources)
                                      else "read" if context.get("sources") else "none"),
                            "source_ids": [s["id"] for s in sources if s["kind"] == "company_context"]},
        "research": {"status": "read" if research.get("sources") else "none",
                     "source_ids": [s["id"] for s in sources if s["kind"] == "public_source"]},
        "references": [{"source_id": s["id"], "status": s["status"]}
                       for s in sources if s["kind"] == "referenced_url"],
        "platform": {"status": "system_reported" if platform else "none"},
        "gaps": gaps,
    }
    return {"sources": sources, "coverage": coverage}
