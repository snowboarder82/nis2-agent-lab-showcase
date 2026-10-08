"""Check every request before anything runs. Allow-lists only: if a value isn't on
the list, it's refused, with a hint that says what would be accepted.

A refused request still gets HTTP 200 with "ok": false. A 400 would make the agent
stop its whole run; a 200 with a hint lets it carry on and report the gap.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from shared.checks import CHECK_INFO

TARGETS = ("alfa", "beta", "gamma", "lab")   # three made-up firms, and your own lab tenant (live, H5)
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{6,62}[a-z0-9]$")
MAX_BODY_BYTES = 2048
FIELDS = {"check", "target", "run_id"}


@dataclass(frozen=True)
class RunRequest:
    check: str
    target: str
    run_id: str


class Refused(ValueError):
    """The request broke a rule. `hint` says how to fix it."""

    def __init__(self, error: str, hint: str):
        super().__init__(error)
        self.error, self.hint = error, hint


def parse_run_request(body: bytes) -> RunRequest:
    if len(body) > MAX_BODY_BYTES:
        raise Refused("request too large", f"Send at most {MAX_BODY_BYTES} bytes: just check, target and run_id.")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise Refused("body is not JSON", 'Send JSON like {"check": "security_defaults", "target": "beta", "run_id": "test-0001"}.')
    if not isinstance(data, dict):
        raise Refused("body must be a JSON object", "Send one object with the keys check, target and run_id.")
    extra = sorted(set(data) - FIELDS)
    if extra:
        raise Refused(f"{len(extra)} unknown field(s)", "Send only check, target and run_id.")  # never echo input
    missing = sorted(FIELDS - set(data))
    if missing:
        raise Refused(f"missing field(s): {', '.join(missing)}", "Send check, target and run_id.")
    check, target, run_id = data["check"], data["target"], data["run_id"]
    if not isinstance(check, str) or check not in CHECK_INFO:
        raise Refused("unknown check", "Use one of: " + ", ".join(CHECK_INFO) + ". GET /api/checks lists them.")
    if not isinstance(target, str) or target not in TARGETS:
        raise Refused("unknown target", "Use one of: " + ", ".join(TARGETS) + ".")
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise Refused("bad run_id", "Use 8 to 64 characters: lowercase letters, digits and '-', for example test-0001.")
    return RunRequest(check, target, run_id)