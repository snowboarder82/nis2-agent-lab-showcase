"""The answer checker (H7): plain code that checks every draft before you see it.

The model proposes, this code checks, a person decides. For one draft answer it:
  1. sends anything it can't trust to a person: a guardrail block, a reply in the wrong shape,
     or an evidence ID that doesn't exist, was changed, or belongs to another run or firm;
  2. reads the cited evidence records itself and works out, with common/evaluate.py, what
     they prove for the control;
  3. lowers an answer that claims more than that (a Tak without evidence becomes
     Do uzupełnienia), and never raises one;
  4. marks for review anything a person should look at: a lowered answer, a control the
     search disagrees with, a question about several controls, flags, missing checks.
It calls no model, and it never sees the agent's reasoning, only its answer and the records.

H9 closed a gap: when the workflow's own match (its search, or the matching model when the
search isn't sure) says which control a question is about, that match decides which rule the
answer is judged by, not the agent. For a question about several controls, the weakest of them
decides. Before, an agent talked into "answering about C02" could carry C02's better evidence
over to a backup question; now it can't choose the rule it's judged by.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from common import answer as answer_format
from common.evaluate import DO_UZUP, RANK, TAK, Verdict, evaluate

OK, REVIEW, PERSON = "ok", "review", "person"
STATUS_ORDER = {OK: 0, REVIEW: 1, PERSON: 2}


class EvidenceStore(Protocol):
    def get(self, run_id: str, evidence_id: str) -> dict[str, Any] | None: ...   # None = no such record


@dataclass
class Checked:
    status: str                          # ok, review or person
    answer: str | None                   # the answer to propose; None when only a person can answer
    reasons: list[str]                   # why, in plain English, for the review workbook
    records: list[dict[str, Any]] = field(default_factory=list)   # the verified records the answer rests on
    expected: Verdict | None = None      # what those records prove
    flags: list[str] = field(default_factory=list)
    text_fits: bool = False              # True if the agent's Polish text was written for this answer
    control: str | None = None           # the control the answer was judged by (H9); None = no control

    def raise_to(self, status: str, reason: str) -> None:
        """Make the status stricter (never milder) and say why."""
        if STATUS_ORDER[status] > STATUS_ORDER[self.status]:
            self.status = status
        self.reasons.append(reason)


def record_hash(record: dict[str, Any]) -> str:
    """The same SHA-256 as the tools' evidence.digest() (a test keeps the two equal)."""
    body = {k: v for k, v in record.items() if k != "sha256"}
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_evidence(ids: list[str], run_id: str, firm: str, store: EvidenceStore
                    ) -> tuple[list[dict[str, Any]], list[str]]:
    """(the records that passed, a sentence for each ID that didn't)."""
    good, bad = [], []
    for evidence_id in ids:
        record = store.get(run_id, evidence_id)
        if record is None:
            bad.append(f"{evidence_id} doesn't exist in run {run_id}: a made-up or foreign evidence ID.")
        elif record.get("sha256") != record_hash(record):
            bad.append(f"{evidence_id} was changed after the tools saved it (its hash doesn't match).")
        elif record.get("run_id") != run_id or record.get("evidence_id") != evidence_id:
            bad.append(f"{evidence_id} belongs to another run.")
        elif record.get("target") != firm:
            bad.append(f"{evidence_id} is about another firm ({record.get('target')}), not {firm}.")
        else:
            good.append(record)
    return good, bad


def instruction_like(records: list[dict[str, Any]]) -> list[str]:
    """Code's own flag, whatever the model said: tenant data whose names read like instructions."""
    found = []
    for r in records:
        facts = r.get("facts") or {}
        for kind in ("apps", "policies"):
            for i, item in enumerate(facts.get(kind) or [], start=1):
                if isinstance(item, dict) and item.get("name_looks_like_instruction"):
                    found.append(f"{r['evidence_id']}: {kind[:-1]} {i} has a name that reads like an instruction.")
    return found


def check(draft: dict[str, Any] | None, *, run_id: str, firm: str, controls: dict[str, dict[str, Any]],
          store: EvidenceStore, matched: list[str] | None = None, blocked: bool = False,
          error: str | None = None) -> Checked:
    """Check one draft answer. `matched` is what the workflow's own search matched (None if unknown)."""
    if blocked:
        return Checked(PERSON, None, ["The guardrail stopped this request. Nothing from it was used; "
                                      "a person answers this question."])
    if draft is None:
        return Checked(PERSON, None, [f"No draft: {error or 'the agent gave no answer'}."])
    shape = answer_format.problems(draft)
    if shape:
        return Checked(PERSON, None, ["The reply isn't in the agreed format: " + "; ".join(shape) + "."])

    control_id, said = draft["control_id"], draft["answer"]
    records, bad = verify_evidence(draft["evidence_ids"], run_id, firm, store)
    result = Checked(OK, said, [], records, flags=list(draft["flags"]))
    if bad:   # an ID that's made up, changed or foreign: the whole draft can't be trusted
        result.raise_to(PERSON, "Evidence that can't be trusted: " + " ".join(bad))

    if control_id == answer_format.NO_CONTROL:
        result.expected = Verdict(DO_UZUP, "No catalogue control covers this question.")
        result.raise_to(REVIEW, "No catalogue control covers this question: answer it with the client.")
    else:
        judged = [control_id]   # the control(s) the answer is judged by
        if matched and (control_id not in matched or len(matched) > 1):   # H9: the workflow's match decides
            judged = [c for c in matched if c in controls] or judged
        bearing = set().union(*(controls[c]["evidence_checks"] for c in judged))
        unrelated = sorted({r["check"] for r in records} - bearing)
        if unrelated:
            result.reasons.append(f"Cited checks that don't bear on {', '.join(judged)} were ignored: "
                                  f"{', '.join(unrelated)}.")
        # Several controls: the answer can't claim more than the weakest of them proves.
        verdicts = {c: evaluate(controls[c], records) for c in judged}
        result.control = min(judged, key=lambda c: RANK[verdicts[c].answer])
        result.expected = verdicts[result.control]

    expected = result.expected
    if RANK[said] > RANK[expected.answer]:
        result.answer = expected.answer
        if said == TAK and not records:
            result.raise_to(REVIEW, f"Lowered from Tak to {expected.answer}: a Tak needs evidence, and none was cited.")
        else:
            result.raise_to(REVIEW, f"Lowered from {said} to {expected.answer}: the evidence proves only that. "
                                    f"{expected.why}")
    elif RANK[said] < RANK[expected.answer]:
        result.raise_to(REVIEW, f"The evidence supports {expected.answer} ({expected.why}), but the agent said "
                                f"{said}. Code never raises an answer: decide which is right.")
    if expected.missing:
        result.raise_to(REVIEW, f"Not checked, though it could decide this: {', '.join(expected.missing)}.")

    if matched is not None and control_id != answer_format.NO_CONTROL:
        if control_id not in matched and judged != [control_id]:
            result.raise_to(REVIEW, f"The agent answered about {control_id}, but the search matched "
                                    f"{', '.join(matched)}, so the answer was checked against "
                                    f"{', '.join(judged)}.")
        elif control_id not in matched:
            result.raise_to(REVIEW, f"The agent answered about {control_id}, but the search matched "
                                    f"{', '.join(matched) or 'no control'}.")
        elif len(matched) > 1:
            result.raise_to(REVIEW, f"The question asks about {', '.join(matched)}; one answer covers only "
                                    f"{control_id}, so it was checked against the weakest of them "
                                    f"({result.control}).")
    elif matched and control_id == answer_format.NO_CONTROL:
        result.raise_to(REVIEW, f"The agent found no control, but the search matched {', '.join(matched)}.")
    for flag in instruction_like(records):
        if flag not in result.flags:
            result.flags.append(flag)
    if result.flags:
        result.raise_to(REVIEW, f"{len(result.flags)} flag(s) to read: data that may be trying to steer the agent.")

    result.text_fits = result.answer == said
    if not result.text_fits:
        result.reasons.append("The agent's Polish text was written for a different answer; it needs new wording.")
    return result