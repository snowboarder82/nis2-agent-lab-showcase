# The code

These files are copied unchanged, byte for byte, from my private lab repository at commit `892f75a1e07a42601a0a4dfc9ef1193a99bdadb6`: the merge of module H11, on 8 Oct 2026. They keep their paths from the lab, so `code/common/checker.py` here is `common/checker.py` there.

The four pipeline files are in [`../pipeline/`](../pipeline/) instead of `.github/` and `.githooks/`, so GitHub never runs them here.

The comments in these files say "you" and name lab modules such as H6: I built the lab from a step-by-step guide, so "you" is me, and H0 to H11 are the lab's modules ([table](../docs/security.md#the-build-module-by-module)).

## What each file shows

| File | What it shows |
|---|---|
| [functions/function_app.py](functions/function_app.py) | The read-only tools as an Azure Functions app: routes behind Entra sign-in, no check run without an audit salt, no stack traces, nothing returned before its evidence record is saved |
| [functions/shared/validate.py](functions/shared/validate.py) | Allow-lists for every input, a 2 KB size limit, and refusals that never echo the input |
| [functions/shared/audit.py](functions/shared/audit.py) | One audit line per check run, with the caller as a salted hash |
| [functions/shared/evidence.py](functions/shared/evidence.py) | Evidence records: one fixed JSON form, a SHA-256 hash, saved as the tools' identity and never overwritten |
| [common/answer.py](common/answer.py) | The strict answer schema shared by the agent and the checker, and the checks Azure's strict JSON mode can't do |
| [common/checker.py](common/checker.py) | The checker: evidence must exist, match its hash and belong to this run and firm; an answer is lowered, never raised; "Tak" needs evidence |
| [common/models.py](common/models.py) | The model plan's checks: no Global, Developer or Provisioned deployments, pinned versions, retirement warnings |
| [config/models.json](config/models.json) | The model plan: deployment types, versions, speed limits, jobs and retirement dates |
| [agents/definition.py](agents/definition.py) | The Foundry prompt agent as code: its two tools, strict JSON, the guardrail by full Azure ID, the reasoning effort |
| [agents/check_agent.py](agents/check_agent.py) | Compares the live agent with the code (model, instructions, tools, answer format, guardrail) and checks that the guardrail exists; an optional probe with a well-known jailbreak text |
| [eval/gate.yaml](eval/gate.yaml) | The release gate: zero-tolerance safety rules and quality floors |
| [logicapp/pack.schema.json](logicapp/pack.schema.json) | The shape the approval Logic App accepts for a pack |
| [tests/test_workflows.py](tests/test_workflows.py) | 26 tests that guard the security rules of the CI and release workflows |

How these fit together: [docs/security.md](../docs/security.md).

## Why it doesn't run on its own

These files import parts that stay private: the evidence checks (`functions/shared/checks.py`), the Graph reader (`functions/shared/sources.py`), the catalogue and the evaluation rules (`common/catalogue.py`, `common/evaluate.py`), the settings loader, the Foundry helpers and a release helper (`tools/changed.py`). `tests/test_workflows.py` also expects the workflow files in `.github/` and the lab's `requirements.txt`.

I didn't change any file to make it run here: each one is shown exactly as it is in the lab. A full code walkthrough is available on request.
