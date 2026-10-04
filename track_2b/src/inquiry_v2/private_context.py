"""Private append-only Company Context. Caller authenticates user actions."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from .scope import normalize_scope, scope_matches, scope_token, specificity
from .value_store import ValueStore
from .research_evidence import current

SCHEMA_VERSION = "private-company-context-1"
_RANK = {"company_confirmed": 5, "working_value": 3, "public_reference": 1}


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _actor(actor):
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("explicit authorized actor required")
    return actor.strip()


def _conflicts(candidates):
    def identity(candidate):
        return candidate.get("value"), candidate.get("unit"), candidate.get("conditions", [])
    return any(identity(candidate) != identity(candidates[0]) for candidate in candidates[1:])


class ContextStore:
    def __init__(self, path):
        requested = Path(path)
        if not requested.is_absolute():
            raise ValueError("private database path must be absolute")
        self.path = requested.resolve()
        app_root = Path(__file__).resolve().parents[2]
        if self.path == app_root or app_root in self.path.parents:
            raise ValueError("private database must be outside application files")
        if any((parent / ".git").exists() for parent in (self.path.parent, *self.path.parent.parents)):
            raise ValueError("private database must be outside every Git checkout")
        if self.path.exists() and not self.path.is_file():
            raise ValueError("private database path must name a file")

    def _open(self, write=False):
        # Re-resolve at every operation, including after a parent became a symlink.
        if self.path.resolve() != self.path:
            raise ValueError("private database path changed after validation")
        if any((parent / ".git").exists() for parent in (self.path.parent, *self.path.parent.parents)):
            raise ValueError("private database entered a Git checkout")
        if not write and not self.path.exists():
            return None
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(self.path), timeout=10)
            try:
                connection.execute("PRAGMA foreign_keys=ON")
                # Serialize first-use initialization as well as subsequent writes.
                connection.execute("BEGIN IMMEDIATE")
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                if tables:
                    if not {"meta", "sources", "candidates", "events"} <= tables:
                        raise ValueError("not a private Company Context database")
                    existing_version = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                    if not existing_version or existing_version[0] != SCHEMA_VERSION:
                        raise ValueError("unsupported private context schema")
                for statement in (
                    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, data TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS candidates (id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id), data TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, data TEXT NOT NULL)",
                    "INSERT OR IGNORE INTO meta VALUES ('schema_version', 'private-company-context-1')",
                ):
                    connection.execute(statement)
                for table in ("sources", "candidates", "events"):
                    for operation in ("UPDATE", "DELETE"):
                        connection.execute("CREATE TRIGGER IF NOT EXISTS " + table + "_no_" + operation.lower() +
                                           " BEFORE " + operation + " ON " + table +
                                           " BEGIN SELECT RAISE(ABORT,'immutable ledger'); END")
                connection.commit()
                connection.execute("BEGIN IMMEDIATE")
            except Exception:
                connection.close()
                raise
        else:
            connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=10)
            connection.execute("BEGIN")
        try:
            version = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        except Exception:
            connection.close()
            raise
        if not version or version[0] != SCHEMA_VERSION:
            connection.close()
            raise ValueError("unsupported private context schema")
        return connection

    @staticmethod
    def _read(connection):
        if connection is None:
            return {"sources": [], "candidates": [], "resolutions": []}
        return {
            "sources": [json.loads(row[0]) for row in connection.execute("SELECT data FROM sources ORDER BY rowid")],
            "candidates": [json.loads(row[0]) for row in connection.execute("SELECT data FROM candidates ORDER BY rowid")],
            "resolutions": [json.loads(row[0]) for row in connection.execute("SELECT data FROM events ORDER BY seq")],
        }

    @staticmethod
    def _insert(connection, table, item):
        data = _json(item)
        old = connection.execute("SELECT data FROM " + table + " WHERE id=?", (item["id"],)).fetchone()
        if old:
            if old[0] != data:
                raise ValueError("immutable " + table + " id cannot be overwritten")
            return
        if table == "candidates":
            connection.execute("INSERT INTO candidates(id,source_id,data) VALUES (?,?,?)", (item["id"], item["source_id"], data))
        else:
            connection.execute("INSERT INTO sources(id,data) VALUES (?,?)", (item["id"], data))

    @staticmethod
    def _event(connection, action, actor, **detail):
        event = {"id": "event-" + uuid.uuid4().hex, "action": action, "actor": actor,
                 "at": _now(), **detail}
        connection.execute("INSERT INTO events(id,data) VALUES (?,?)", (event["id"], _json(event)))
        return event["id"]

    def record(self, context, *, authority="reference", actor=None):
        if not isinstance(authority, str) or authority not in {"reference", "trusted_company"}:
            raise ValueError("explicit source authority required")
        if authority == "trusted_company":
            actor = _actor(actor)
        if not isinstance(context, dict) or any(not isinstance(context.get(k, []), list) for k in ("sources", "candidates")):
            raise ValueError("context requires source and candidate arrays")
        sources, candidates = deepcopy(context.get("sources", [])), deepcopy(context.get("candidates", []))
        for source in sources:
            if not isinstance(source, dict) or not isinstance(source.get("kind"), str) or source["kind"] not in {"public_source", "referenced_url", "company_context", "operator_input"} or not isinstance(source.get("party"), str) or source["party"] not in {"public", "company"}:
                raise ValueError("customer or untrusted source cannot enter Company Context")
            expected_party = "public" if source["kind"] in {"public_source", "referenced_url"} else "company"
            if source["party"] != expected_party:
                raise ValueError("source kind and authority party must agree")
            if not isinstance(source.get("id"), str) or not source["id"] or source.get("status") != "read" or not isinstance(source.get("text"), str) or not source["text"].strip() or not isinstance(source.get("metadata", {}), dict):
                raise ValueError("context sources require readable immutable evidence")
            source.setdefault("metadata", {})
            source.setdefault("scope", "reference")
            if not isinstance(source["scope"], str) or not source["scope"]:
                raise ValueError("source scope must be a nonempty string")
        for candidate in candidates:
            if not isinstance(candidate, dict) or not isinstance(candidate.get("status"), str) or candidate["status"] not in _RANK:
                raise ValueError("only public, working or explicitly trusted company candidates may persist")
            if any(not isinstance(candidate.get(name), str) or not candidate[name] for name in ("id", "key", "scope")) or not isinstance(candidate.get("provenance", {}), dict):
                raise ValueError("candidate requires id, key, scope and provenance object")
            if candidate.get("unit") is not None and not isinstance(candidate["unit"], str):
                raise ValueError("candidate unit must be a string")
            if candidate["status"] == "company_confirmed" and authority != "trusted_company":
                raise ValueError("reference import cannot grant company authority")
            if "scope_spec" in candidate:
                candidate["scope_spec"] = normalize_scope(candidate["scope_spec"])
            if candidate["status"] == "company_confirmed" and "scope_spec" not in candidate:
                raise ValueError("trusted company candidate requires explicit applicability")
        if not sources and not candidates:
            return {"recorded_candidate_ids": [], "event_id": None}
        connection = self._open(write=True)
        try:
            old = self._read(connection)
            combined = {s["id"]: s for s in old["sources"]}
            for source in sources:
                if source["id"] in combined and combined[source["id"]] != source:
                    raise ValueError("immutable source cannot be overwritten")
                combined[source["id"]] = source
            known = {c["id"] for c in old["candidates"]} | {c.get("id") for c in candidates} | set(combined)
            for candidate in candidates:
                derivation = candidate.get("provenance", {}).get("derived_from", [])
                if not isinstance(derivation, list) or any(not isinstance(cid, str) or cid not in known or cid == candidate.get("id") for cid in derivation):
                    raise ValueError("candidate derivation must refer to retained source or candidate history")
            ledger = ValueStore({"sources": list(combined.values())}).extend(candidates)
            if any(c["status"] == "rejected" for c in ledger.candidates):
                raise ValueError("context candidate failed provenance validation: " + ",".join(ledger.issues))
            for source in sources:
                self._insert(connection, "sources", source)
            for candidate in ledger.candidates:
                self._insert(connection, "candidates", candidate)
            event_id = self._event(connection, "record", actor, authority=authority,
                                   candidate_ids=[c["id"] for c in candidates], source_ids=[s["id"] for s in sources])
            connection.commit()
            return {"recorded_candidate_ids": [c["id"] for c in candidates], "event_id": event_id}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def confirm(self, candidate_id, *, actor, scope_spec):
        return self._attest(candidate_id, actor=actor, scope_spec=scope_spec, edit=False)

    def edit(self, candidate_id, value, *, actor, scope_spec, unit=None, conditions=None, statement=None):
        return self._attest(candidate_id, value=value, actor=actor, scope_spec=scope_spec,
                            unit=unit, conditions=conditions, statement=statement, edit=True)

    def apply_edits(self, changes, *, actor, statement, scope_spec):
        """A natural-language parser proposes changes; the trusted caller attests them."""
        actor, spec = _actor(actor), normalize_scope(scope_spec)
        if not isinstance(changes, list) or not 1 <= len(changes) <= 5 or any(not isinstance(c, dict) for c in changes):
            raise ValueError("one to five explicit changes required")
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError("explicit user statement required")
        connection = self._open(write=True)
        try:
            history = self._read(connection)
            old = {c["id"]: c for c in history["candidates"]}
            inactive = {cid for e in history["resolutions"] for cid in e.get("supersedes", [])}
            source_id, scope, at = "operator-" + uuid.uuid4().hex, scope_token(spec), _now()
            source = {"id": source_id, "kind": "operator_input", "party": "company", "status": "read",
                      "text": statement, "scope": scope,
                      "metadata": {"confirmed_by": actor, "confirmed_at": at, "authorization": "explicit_user_attestation"}}
            candidates, supersedes, seen = [], [], set()
            for change in changes:
                key, target = change.get("key"), change.get("candidate_id")
                if not isinstance(key, str) or not key.strip() or "value" not in change:
                    raise ValueError("change requires key and value")
                if target is not None and (not isinstance(target, str) or not target):
                    raise ValueError("edit target must be a candidate id")
                if key in seen:
                    raise ValueError("a batch cannot contain duplicate keys")
                seen.add(key)
                prior = old.get(target) if target else None
                if target and (not prior or target in inactive or prior["key"] != key or "scope_spec" not in prior
                               or normalize_scope(prior["scope_spec"]) != spec):
                    raise ValueError("edit target must be active and have exactly the same key and scope")
                conditions = deepcopy(change.get("conditions", prior.get("conditions", []) if prior else []))
                if not isinstance(conditions, list) or any(not isinstance(v, str) or not v.strip() for v in conditions):
                    raise ValueError("conditions require strings")
                candidate = {"id": "value-" + uuid.uuid4().hex, "key": key, "value": deepcopy(change["value"]),
                             "unit": change.get("unit", prior.get("unit") if prior else None), "conditions": conditions,
                             "scope": scope, "scope_spec": spec, "source_id": source_id, "status": "company_confirmed",
                             "provenance": {"span": [0, len(statement)], "quote": statement,
                                            "derived_from": [target] if target else [], "rule": "explicit_user_edit"}}
                if candidate["unit"] is not None and not isinstance(candidate["unit"], str):
                    raise ValueError("edited unit must be a string")
                validation = ValueStore({"sources": [source]}).add(candidate)
                if validation["status"] == "rejected":
                    raise ValueError("user statement does not support change: " + ",".join(validation["rejection_reasons"]))
                candidates.append(candidate)
                if target:
                    supersedes.append(target)
            self._insert(connection, "sources", source)
            for candidate in candidates:
                self._insert(connection, "candidates", candidate)
            event_id = self._event(connection, "edit_batch", actor, candidate_ids=[c["id"] for c in candidates],
                                   scope_spec=spec, supersedes=supersedes, derived_from=supersedes)
            connection.commit()
            return {"candidate_ids": [c["id"] for c in candidates], "source_id": source_id, "event_id": event_id}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    edit_many = apply_edits

    def _attest(self, candidate_id, *, actor, scope_spec, edit, value=None, unit=None, conditions=None, statement=None):
        actor, spec = _actor(actor), normalize_scope(scope_spec)
        if not self.path.exists():
            raise ValueError("candidate does not exist in the private ledger")
        connection = self._open(write=True)
        try:
            history = self._read(connection)
            prior = next((c for c in history["candidates"] if c["id"] == candidate_id), None)
            if prior is None or prior["status"] not in _RANK:
                raise ValueError("candidate cannot be confirmed or edited")
            inactive = {cid for e in history["resolutions"] for cid in e.get("supersedes", [])}
            if candidate_id in inactive:
                raise ValueError("inactive candidate cannot be silently revised again")
            if edit and ("scope_spec" not in prior or normalize_scope(prior["scope_spec"]) != spec):
                raise ValueError("Edit may supersede only a candidate with exactly the same explicit scope")
            scope = scope_token(spec)
            new_value = deepcopy(value if edit else prior["value"])
            new_unit = unit if unit is not None else prior.get("unit")
            if new_unit is not None and not isinstance(new_unit, str):
                raise ValueError("edited unit must be a string")
            new_conditions = deepcopy(conditions if conditions is not None else prior.get("conditions", []))
            if not isinstance(new_conditions, list) or any(not isinstance(v, str) or not v.strip() for v in new_conditions):
                raise ValueError("conditions require strings")
            if statement is None:
                statement = "User confirmed " + prior["key"] + ": " + _json(new_value)
                if new_unit:
                    statement += " " + str(new_unit)
            if not isinstance(statement, str) or not statement.strip():
                raise ValueError("user attestation statement required")
            source_id, new_id, at = "operator-" + uuid.uuid4().hex, "value-" + uuid.uuid4().hex, _now()
            source = {"id": source_id, "kind": "operator_input", "party": "company", "status": "read",
                      "text": statement, "scope": scope,
                      "metadata": {"confirmed_by": actor, "confirmed_at": at, "authorization": "explicit_user_attestation"}}
            candidate = {"id": new_id, "key": prior["key"], "value": new_value, "unit": new_unit,
                         "conditions": new_conditions, "scope": scope, "scope_spec": spec,
                         "status": "company_confirmed", "source_id": source_id,
                         "provenance": {"span": [0, len(statement)], "quote": statement,
                                        "derived_from": [candidate_id], "rule": "explicit_user_edit" if edit else "explicit_user_confirm"}}
            validation = ValueStore({"sources": [source]}).add(candidate)
            if validation["status"] == "rejected":
                raise ValueError("user statement does not support the edited value: " + ",".join(validation["rejection_reasons"]))
            self._insert(connection, "sources", source)
            self._insert(connection, "candidates", candidate)
            event_id = self._event(connection, "edit" if edit else "confirm", actor,
                                   candidate_id=new_id, derived_from=[candidate_id], scope_spec=spec,
                                   supersedes=[candidate_id] if edit else [])
            connection.commit()
            return {"candidate_id": new_id, "source_id": source_id, "event_id": event_id}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def view(self, request_context=None):
        if request_context is not None and not isinstance(request_context, dict):
            raise ValueError("request_context must be an object")
        connection = self._open()
        try:
            result = self._read(connection)
        finally:
            if connection is not None:
                connection.close()
        return project_context(result, request_context)

    snapshot = view


def project_context(history, request_context=None):
    """Pure applicability/preference projection for stored or supplied candidates."""
    if not isinstance(history, dict) or request_context is not None and not isinstance(request_context, dict):
        raise ValueError("context history and request_context must be objects")
    result = deepcopy(history)
    for name in ("sources", "candidates", "resolutions"):
        result.setdefault(name, [])
        if not isinstance(result[name], list):
            raise ValueError("context history collections must be arrays")
    if any(not isinstance(candidate, dict) or any(not isinstance(candidate.get(name), str) or not candidate[name]
               for name in ("id", "key", "status")) for candidate in result["candidates"]):
        raise ValueError("context projection requires typed candidates")
    inactive = {cid for e in result["resolutions"] for cid in e.get("supersedes", [])}
    context = request_context or {}
    lines = context.get("lines", [])
    if not isinstance(lines, list) or any(not isinstance(line, dict) or not line.get("id") for line in lines):
        raise ValueError("request_context lines require identified objects")
    for candidate in result["candidates"]:
        spec = candidate.get("scope_spec")
        candidate["expired"] = candidate.get("status") in {"public_reference", "working_value"} and not current(candidate)
        candidate["active"] = candidate["id"] not in inactive
        candidate["applicable_line_ids"] = [line["id"] for line in lines if spec and scope_matches(spec, {**context, **line})]
        candidate["applicable"] = bool(not candidate["expired"] and spec and (candidate["applicable_line_ids"] if lines else scope_matches(spec, context)))
        candidate["preferred"] = False
        candidate["preferred_line_ids"] = []
    result["schema_version"] = SCHEMA_VERSION
    result["selections"] = []
    result["unresolved"] = []
    groups = {}
    for candidate in result["candidates"]:
        if candidate["active"] and candidate["applicable"] and candidate.get("status") in _RANK:
            groups.setdefault((candidate["key"], scope_token(candidate["scope_spec"])), []).append(candidate)
    for (key, scope), pool in groups.items():
        best = max(_RANK[c["status"]] for c in pool)
        winners = [c for c in pool if _RANK[c["status"]] == best]
        conflict = _conflicts(winners)
        selection = {"key": key, "scope": scope, "status": "unresolved" if conflict else winners[0]["status"],
                     "candidate_id": None if conflict else winners[0]["id"], "candidate_ids": [c["id"] for c in winners]}
        result["selections"].append(selection)
        if conflict:
            result["unresolved"].append(selection)
    # Mark a current preference per line while retaining every applicable alternative.
    targets = [line["id"] for line in lines] or [None]
    for key in {c["key"] for c in result["candidates"]}:
        for target in targets:
            pool = [c for c in result["candidates"] if c["key"] == key and c["active"] and c["applicable"] and c.get("status") in _RANK
                    and (target is None or target in c["applicable_line_ids"])]
            if not pool:
                continue
            rank = max((_RANK[c["status"]], specificity(c["scope_spec"])) for c in pool)
            winners = [c for c in pool if (_RANK[c["status"]], specificity(c["scope_spec"])) == rank]
            if not _conflicts(winners):
                winners[0]["preferred"] = True
                winners[0].setdefault("preferred_line_ids", []).append(target)
            elif len({scope_token(c["scope_spec"]) for c in winners}) > 1:
                result["unresolved"].append({"key": key, "scope": "overlapping_applicability", "status": "unresolved",
                                              "line_id": target, "candidate_id": None, "candidate_ids": [c["id"] for c in winners]})
    return result
