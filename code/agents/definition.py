"""What the agent kwestionariusz-nis2 is made of, in one place (H6).

expected() describes the agent as plain data: the model and how hard it thinks, the
instructions, the two tools, the strict answer format and the guardrail. build() turns it into the SDK's
definition for create_agent.py, and check_agent.py compares a live agent with it,
so the agent in Foundry and the code in Git can't silently drift apart.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from common import models
from common.answer import ANSWER_SCHEMA, SCHEMA_NAME

ROOT = Path(__file__).resolve().parent.parent
INSTRUCTIONS_FILE = ROOT / "agents" / "instructions.md"
OPENAPI_FILE = ROOT / "functions" / "openapi.json"
TOOL_NAME = "nis2_tools"
TOOL_DESCRIPTION = ("Read-only NIS2 evidence tools: list the checks, and run one check against one firm. "
                    "Every result is saved as evidence with an evidence_id.")
QUERY_TYPE = "simple"   # keyword search with the Polish analyser (H3); the index has no vectors
TOP_K = 3               # the three best-matching controls are enough to pick one
REASONING_EFFORT = "medium"   # how hard the drafter thinks first; set here, not left to the model's default


def instructions() -> str:
    return INSTRUCTIONS_FILE.read_text(encoding="utf-8").strip()


def tools_spec(func_host: str) -> dict[str, Any]:
    """The OpenAPI description from H4, pointed at your Function app's real address."""
    spec = json.loads(OPENAPI_FILE.read_text(encoding="utf-8"))
    spec["servers"] = [{"url": f"https://{func_host}/api"}]
    return spec


def guardrail_id(cfg: dict[str, str]) -> str:
    """The guardrail's full Azure ID. Microsoft says to use the full ID, not the bare name: a name that
    doesn't resolve is accepted without an error and leaves the agent with no filtering at all."""
    return (f"/subscriptions/{cfg['AZ_SUBSCRIPTION_ID']}/resourceGroups/{cfg['AZ_RESOURCE_GROUP']}"
            f"/providers/Microsoft.CognitiveServices/accounts/{cfg['FOUNDRY_RESOURCE']}"
            f"/raiPolicies/{cfg['GUARDRAIL_NAME']}")


def expected(cfg: dict[str, str], search_connection_id: str) -> dict[str, Any]:
    """The whole agent as plain data, in the same shape Foundry stores it."""
    want = {
        "kind": "prompt",
        "model": cfg["MODEL_DRAFT"],
        "instructions": instructions(),
        "tools": [
            {"type": "openapi", "openapi": {
                "name": TOOL_NAME, "description": TOOL_DESCRIPTION, "spec": tools_spec(cfg["FUNC_HOST"]),
                "auth": {"type": "managed_identity",
                         "security_scheme": {"audience": f"api://{cfg['TOOLS_API_APP_ID']}"}}}},
            {"type": "azure_ai_search", "azure_ai_search": {"indexes": [{
                "project_connection_id": search_connection_id, "index_name": cfg["SEARCH_INDEX"],
                "query_type": QUERY_TYPE, "top_k": TOP_K}]}},
        ],
        "text": {"format": {"type": "json_schema", "name": SCHEMA_NAME, "schema": copy.deepcopy(ANSWER_SCHEMA),
                            "strict": True}},
        "rai_config": {"rai_policy_name": guardrail_id(cfg)},
    }
    if models.is_reasoning(cfg["MODEL_DRAFT"]):   # only reasoning models take an effort (config/models.json)
        want["reasoning"] = {"effort": REASONING_EFFORT}
    return want


def build(cfg: dict[str, str], search_connection_id: str) -> Any:
    """The SDK object create_version() needs, made from expected()."""
    from azure.ai.projects.models import (AISearchIndexResource, AzureAISearchTool, AzureAISearchToolResource,
                                          OpenApiFunctionDefinition, OpenApiManagedAuthDetails,
                                          OpenApiManagedSecurityScheme, OpenApiTool, PromptAgentDefinition,
                                          PromptAgentDefinitionTextOptions, RaiConfig, Reasoning,
                                          TextResponseFormatJsonSchema)
    want = expected(cfg, search_connection_id)
    api, search = want["tools"][0]["openapi"], want["tools"][1]["azure_ai_search"]["indexes"][0]
    fmt = want["text"]["format"]
    return PromptAgentDefinition(
        model=want["model"],
        instructions=want["instructions"],
        tools=[
            OpenApiTool(openapi=OpenApiFunctionDefinition(
                name=api["name"], description=api["description"], spec=api["spec"],
                auth=OpenApiManagedAuthDetails(security_scheme=OpenApiManagedSecurityScheme(
                    audience=api["auth"]["security_scheme"]["audience"])))),
            AzureAISearchTool(azure_ai_search=AzureAISearchToolResource(indexes=[AISearchIndexResource(
                project_connection_id=search["project_connection_id"], index_name=search["index_name"],
                query_type=search["query_type"], top_k=search["top_k"])])),
        ],
        text=PromptAgentDefinitionTextOptions(format=TextResponseFormatJsonSchema(
            name=fmt["name"], schema=fmt["schema"], strict=fmt["strict"])),
        rai_config=RaiConfig(rai_policy_name=want["rai_config"]["rai_policy_name"]),
        reasoning=Reasoning(effort=want["reasoning"]["effort"]) if "reasoning" in want else None,
    )


def policy_name(value: str | None) -> str:
    """A guardrail may be stored by name or by its full Azure ID; compare the name."""
    return (value or "").rstrip("/").rsplit("/", 1)[-1]


def effort_problem(want: dict[str, Any], have: dict[str, Any]) -> list[str]:
    """The reasoning effort must be exactly the code's, or absent for a model that doesn't reason."""
    have_effort, want_effort = ((d.get("reasoning") or {}).get("effort") for d in (have, want))
    return [] if have_effort == want_effort else [f"reasoning effort is {have_effort!r}, expected {want_effort!r}"]


def differences(want: dict[str, Any], have: dict[str, Any]) -> list[str]:
    """What differs between the expected agent and a live one, in plain words. Empty = identical."""
    found = []
    for key in ("kind", "model"):
        if have.get(key) != want[key]:
            found.append(f"{key} is {have.get(key)!r}, expected {want[key]!r}")
    found += effort_problem(want, have)
    if (have.get("instructions") or "").strip() != want["instructions"]:
        found.append("the instructions differ from agents/instructions.md")
    tools = {t.get("type"): t for t in have.get("tools") or []}
    if set(tools) != {"openapi", "azure_ai_search"}:
        found.append(f"tools are {sorted(tools)}, expected ['azure_ai_search', 'openapi']")
    api = (tools.get("openapi") or {}).get("openapi") or {}
    want_api = want["tools"][0]["openapi"]
    if api:
        if (api.get("auth") or {}).get("type") != "managed_identity":
            found.append("the OpenAPI tool doesn't sign in with the managed identity")
        if ((api.get("auth") or {}).get("security_scheme") or {}).get("audience") != \
                want_api["auth"]["security_scheme"]["audience"]:
            found.append("the OpenAPI tool's audience isn't api:// plus TOOLS_API_APP_ID")
        if (api.get("spec") or {}).get("servers") != want_api["spec"]["servers"]:
            found.append("the OpenAPI tool points at another address than FUNC_HOST")
        if (api.get("spec") or {}).get("paths") != want_api["spec"]["paths"]:
            found.append("the OpenAPI tool's operations differ from functions/openapi.json")
    indexes = ((tools.get("azure_ai_search") or {}).get("azure_ai_search") or {}).get("indexes") or [{}]
    want_index = want["tools"][1]["azure_ai_search"]["indexes"][0]
    for key in ("project_connection_id", "index_name", "query_type", "top_k"):
        if tools.get("azure_ai_search") and indexes[0].get(key) != want_index[key]:
            found.append(f"the search tool's {key} is {indexes[0].get(key)!r}, expected {want_index[key]!r}")
    fmt = (have.get("text") or {}).get("format") or {}
    if fmt.get("type") != "json_schema" or fmt.get("strict") is not True:
        found.append("the answer format isn't strict JSON schema")
    elif fmt.get("schema") != want["text"]["format"]["schema"]:
        found.append("the answer schema differs from common/answer.py")
    have_policy = (have.get("rai_config") or {}).get("rai_policy_name") or ""
    want_policy = want["rai_config"]["rai_policy_name"]
    if policy_name(have_policy) != policy_name(want_policy):
        found.append(f"the guardrail is {policy_name(have_policy) or 'not set'!r}, expected {policy_name(want_policy)!r}")
    elif "/" in have_policy and have_policy.lower() != want_policy.lower():
        found.append("the guardrail's ID points at another Foundry resource or subscription")
    return found