"""The read-only evidence tools, as an Azure Functions app (Python, v2 model).

Routes (all behind Entra sign-in, "Easy Auth", so a call without a valid token gets
401 before this code runs):
  GET  /api/health       is the app up, and is it configured?
  GET  /api/checks       the 16 checks and the allowed targets
  POST /api/checks/run   run one check: {"check": ..., "target": ..., "run_id": ...}
  GET  /api/access       live mode (H5): which Graph permissions the tools hold in your lab tenant

Every answer is JSON with "ok". A refused or failed call still returns HTTP 200 with
"ok": false and a hint, so an agent can carry on and report the gap instead of
stopping. Every call to checks/run and access writes one AUDIT line. A check result
is returned only after its evidence record has been saved.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import azure.functions as func

from shared import audit, evidence
from shared.checks import CHECK_INFO, run_check
from shared.sources import (GraphError, LiveNotConfigured, MissingData, SignInError, access_report, live_reader,
                            reader_for)
from shared.validate import RUN_ID, TARGETS, Refused, parse_run_request

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)  # Easy Auth checks the caller, not keys
VERSION = "h5"
log = logging.getLogger("nis2.tools")
NOT_LIVE_HINT = "H5 connects the tools to your lab tenant. Until then use target alfa, beta or gamma."


def reply(body: dict[str, Any]) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(body, ensure_ascii=False, default=str),
                             status_code=200, mimetype="application/json")


def refuse(error: str, hint: str) -> func.HttpResponse:
    return reply({"ok": False, "error": error, "hint": hint})


@lru_cache(maxsize=1)
def get_store() -> Any:
    return evidence.BlobStore.from_env()


def audit_salt() -> str:
    salt = os.environ.get("AUDIT_SALT", "")
    if len(salt) < 16:
        raise RuntimeError("AUDIT_SALT is missing or too short")
    return salt


class Call:
    """One audited call: who called (hashed), how long it took, and one AUDIT line at the end."""

    def __init__(self, route: str, req: func.HttpRequest, salt: str):
        self.started = time.monotonic()
        who = audit.caller(req.headers)
        self.event: dict[str, Any] = {"route": route, "caller": audit.hash_id(who["oid"], salt),
                                      "caller_app": who["app"]}

    def done(self, response: func.HttpResponse, outcome: str, **extra: Any) -> func.HttpResponse:
        audit.write({**self.event, **extra, "outcome": outcome,
                     "ms": int((time.monotonic() - self.started) * 1000)})
        return response


def start(route: str, req: func.HttpRequest) -> Call | None:
    try:
        return Call(route, req, audit_salt())
    except RuntimeError:
        log.error("AUDIT_SALT is not set: refusing every call")
        return None


def sign_in_refusal(call: Call, e: SignInError) -> func.HttpResponse:
    return call.done(refuse(f"couldn't sign in to the client's tenant ({e.code})", e.hint),
                     "error", error=f"signin {e.code}")


@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    configured = {
        "audit_salt": len(os.environ.get("AUDIT_SALT", "")) >= 16,
        "evidence_store": bool(os.environ.get("EVIDENCE_ACCOUNT_URL") and os.environ.get("EVIDENCE_CONTAINER")),
        "identity": bool(os.environ.get("AZURE_CLIENT_ID")),
        "live_mode": bool(os.environ.get("LAB_TENANT_ID") and os.environ.get("GRAPH_APP_CLIENT_ID")),
    }
    return reply({"ok": True, "service": "nis2-tools", "version": VERSION, "configured": configured})


@app.route(route="checks", methods=["GET"])
def list_checks(req: func.HttpRequest) -> func.HttpResponse:
    checks = [{"check": name, "reads": reads, "needs": needs} for name, (reads, needs) in CHECK_INFO.items()]
    return reply({"ok": True, "checks": checks, "targets": list(TARGETS), "run_id_pattern": RUN_ID.pattern,
                  "note": "alfa, beta and gamma are made-up firms; lab is your own tenant, read live (from H5)."})


@app.route(route="checks/run", methods=["POST"])
def run(req: func.HttpRequest) -> func.HttpResponse:
    call = start("checks/run", req)
    if call is None:
        return refuse("server not configured", "The tools need the AUDIT_SALT app setting (H4).")

    try:
        ask = parse_run_request(req.get_body() or b"")
    except Refused as r:
        return call.done(refuse(r.error, r.hint), "refused", error=r.error)
    call.event.update(check=ask.check, target=ask.target, run_id=ask.run_id)

    try:
        reader = reader_for(ask.target)
        result = run_check(ask.check, reader)
    except LiveNotConfigured:
        return call.done(refuse("live mode isn't set up yet", NOT_LIVE_HINT), "not_configured")
    except SignInError as e:
        return sign_in_refusal(call, e)
    except GraphError as e:
        hint = ("nis2-evidence-reader lacks a permission or admin consent in that tenant (H5). After you change "
                "its permissions, restart the Function app so it gets a fresh token." if e.status in (401, 403)
                else "Microsoft Graph didn't answer properly; try again in a minute.")
        return call.done(refuse(f"Microsoft Graph said {e.status} {e.code}", hint), "error",
                         error=f"graph {e.status}")
    except MissingData as e:
        return call.done(refuse("data missing", str(e)), "error", error="missing data")
    except Exception:  # never show a stack trace to the caller; log it for you instead
        log.exception("check failed")
        return call.done(refuse("internal error", "The check failed. Look in Application Insights for the exception."),
                         "error", error="exception")

    record = evidence.new_record(ask.run_id, ask.check, ask.target, result, reader)
    try:
        get_store().save(record)
    except Exception:
        log.exception("could not save evidence")
        return call.done(refuse("evidence could not be saved",
                                "Nothing is returned without a saved record. Check the storage role and settings (H4)."),
                         "error", error="store")
    return call.done(reply({"ok": True, **record}), "ok", status=record["status"], evidence_id=record["evidence_id"])


@app.route(route="access", methods=["GET"])
def access(req: func.HttpRequest) -> func.HttpResponse:
    """Live mode only: what the tools' Graph token for your lab tenant allows. No data is read."""
    call = start("access", req)
    if call is None:
        return refuse("server not configured", "The tools need the AUDIT_SALT app setting (H4).")
    try:
        report = access_report(live_reader().token_claims(), now=datetime.now(timezone.utc))
    except LiveNotConfigured:
        return call.done(refuse("live mode isn't set up yet", NOT_LIVE_HINT), "not_configured")
    except SignInError as e:
        return sign_in_refusal(call, e)
    except Exception:
        log.exception("access check failed")
        return call.done(refuse("internal error", "Look in Application Insights for the exception."),
                         "error", error="exception")
    outcome = "ok" if not report["missing"] and not report["extra"] else "mismatch"
    return call.done(reply({"ok": True, **report}), outcome, missing=len(report["missing"]),
                     extra=len(report["extra"]))
