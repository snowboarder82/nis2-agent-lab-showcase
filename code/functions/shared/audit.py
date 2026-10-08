"""The audit trail: one line per call, written to Application Insights.

Who called is stored as a salted hash, never as a name: you can still see that the
same caller came back, but the log holds no personal data. The caller's app ID (for
example the Azure CLI, or your Foundry resource's identity) isn't personal data and
stays readable, so you can see which program called. Request values are logged only
after they passed validation, so attack text never lands in the log.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Mapping

logger = logging.getLogger("nis2.audit")
logger.setLevel(logging.INFO)   # audit lines are INFO: never let a quieter default hide them


def caller(headers: Mapping[str, str]) -> dict[str, str]:
    """Who called, from the headers Easy Auth adds after it has checked the token."""
    oid = headers.get("x-ms-client-principal-id", "") or ""
    app = ""
    raw = headers.get("x-ms-client-principal", "")
    if raw:
        try:
            claims = json.loads(base64.b64decode(raw)).get("claims", [])
            app = next((c.get("val", "") for c in claims if c.get("typ") in ("appid", "azp")), "")
        except (ValueError, TypeError, AttributeError):
            app = "unreadable"
    return {"oid": oid, "app": app[:64]}


def hash_id(value: str, salt: str) -> str:
    if not value:
        return "anonymous"
    return hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()[:16]


def write(event: dict[str, Any]) -> None:
    event = {"time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **event}
    logger.info("AUDIT %s", json.dumps(event, sort_keys=True, ensure_ascii=False, default=str))