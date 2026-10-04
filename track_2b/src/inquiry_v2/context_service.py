"""Small authenticated boundary for private context; no identity from requests."""
import hmac
import os
import sqlite3

from .private_context import ContextStore
from .natural_updates import apply_text


class PrivateContextError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class PrivateContextAccess:
    def __init__(self, environ=None):
        environ = os.environ if environ is None else environ
        self._path = environ.get("COMPANY_CONTEXT_DB", "")
        self._token = environ.get("COMPANY_CONTEXT_TOKEN", "")
        self._actor = environ.get("COMPANY_CONTEXT_ACTOR", "")
        self.ready = bool(self._path and self._token and self._actor.strip())

    def authenticated(self, headers):
        authorization = headers.get("Authorization", "")
        scheme, separator, token = authorization.partition(" ")
        return bool(self.ready and separator and scheme.casefold() == "bearer" and
                    hmac.compare_digest(token.encode("utf-8"), self._token.encode("utf-8")))

    def _store(self, headers):
        if not self.ready:
            raise PrivateContextError(503, "private context is not configured")
        if not self.authenticated(headers):
            raise PrivateContextError(403, "operator authorization required")
        try:
            return ContextStore(self._path)
        except (ValueError, OSError, sqlite3.Error):
            raise PrivateContextError(503, "private context is unavailable") from None

    def inquiry(self, body, headers):
        from . import analyze
        authorized = self.authenticated(headers)
        if not authorized and (any(name in body for name in ("company_context", "request_context")) or
                               isinstance(body.get("research"), dict) and body["research"].get("identity_verification") is not None):
            raise PrivateContextError(403, "operator authorization required for company context")
        try:
            return analyze(body, context_store=self._store(headers) if authorized else None)
        except ValueError:
            raise PrivateContextError(400, "invalid inquiry or context contract") from None
        except (OSError, sqlite3.Error):
            raise PrivateContextError(503, "private context is unavailable") from None

    def view(self, headers):
        try:
            return self._store(headers).view()
        except (ValueError, OSError, sqlite3.Error):
            raise PrivateContextError(503, "private context is unavailable") from None

    def mutate(self, action, body, headers):
        store = self._store(headers)
        if any(name in body for name in ("actor", "path", "db_path", "token", "authorization")):
            raise PrivateContextError(400, "operator configuration cannot be supplied in requests")
        try:
            if action == "record":
                return store.record(body.get("context"), authority=body.get("authority", "reference"), actor=self._actor)
            if action == "confirm":
                return store.confirm(body.get("candidate_id"), actor=self._actor, scope_spec=body.get("scope_spec"))
            if action == "edit":
                if "text" in body:
                    if "changes" in body or "statement" in body:
                        raise ValueError("edit must use one complete input mode")
                    return apply_text(store, body["text"], actor=self._actor,
                                      scope_spec=body.get("scope_spec"), target_ids=body.get("target_ids"))
                return store.apply_edits(body.get("changes"), actor=self._actor,
                                         statement=body.get("statement"), scope_spec=body.get("scope_spec"))
            raise PrivateContextError(404, "not found")
        except ValueError:
            raise PrivateContextError(400, "invalid context operation; no changes applied") from None
        except (OSError, sqlite3.Error):
            raise PrivateContextError(503, "private context is unavailable") from None
