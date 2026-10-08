"""The model plan (config/models.json) and the checks that keep your deployments on it (H2).

In this lab each model deployment is named after its model. For each model the plan says
which version and deployment type to use, its speed limit, whether it's a reasoning model,
and when Microsoft retires it.

Why check in code: the portal's "Default settings" picks Global Standard, which may process
your clients' data anywhere in the world. And at a retirement date Azure can move a deployment
to another model by itself. Both would happen quietly; these checks make them loud.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PLAN_FILE = Path(__file__).resolve().parent.parent / "config" / "models.json"
WARN_DAYS = 90   # warn when a model retires within about three months


@dataclass
class Deployment:
    """The parts of one model deployment that the checks look at."""
    name: str           # what your code calls it, e.g. gpt-5.4-mini
    model: str          # the model behind it
    version: str        # the model's version, e.g. 2026-03-17
    type: str           # the deployment type's code, e.g. DataZoneStandard
    tpm_k: int | None   # the speed limit: 1 means 1,000 tokens per minute


def load_plan(path: Path = PLAN_FILE) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def is_reasoning(model: str, plan: dict[str, Any] | None = None) -> bool:
    """True for a model that thinks before it answers, so it takes a reasoning effort.
    A model the plan doesn't know counts as not reasoning: then no effort is sent."""
    plan = plan or load_plan()
    return bool(plan["models"].get(model, {}).get("reasoning", False))


def from_sdk(item: Any) -> Deployment:
    """Turn what the Foundry SDK returns (project.deployments) into a Deployment."""
    sku = getattr(item, "sku", None)
    return Deployment(name=item.name, model=getattr(item, "model_name", "") or "",
                      version=getattr(item, "model_version", "") or "",
                      type=getattr(sku, "name", "") or "", tpm_k=getattr(sku, "capacity", None))


def read(project: Any, name: str) -> Deployment | None:
    """One deployment of your project by name, or None if there's none with that name."""
    from azure.core.exceptions import ResourceNotFoundError
    try:
        return from_sdk(project.deployments.get(name))
    except ResourceNotFoundError:
        return None


def why_not(deployment_type: str) -> str:
    """Why the lab refuses a deployment type that isn't in the plan."""
    if "Global" in deployment_type or "Developer" in deployment_type:
        return "it may process data anywhere in the world"
    if "Provisioned" in deployment_type:
        return "it bills reserved capacity by the hour"
    return "the lab uses only Data Zone Standard and Standard"


def problems(dep: Deployment, plan: dict[str, Any] | None = None) -> list[str]:
    """What's wrong with one deployment, in plain words. Empty = it matches the plan."""
    plan = plan or load_plan()
    want = plan["models"].get(dep.name)
    if want is None:
        return [f"{dep.name} isn't in config/models.json, so the lab doesn't use it"]
    found, label = [], plan["types"][want["type"]]["label"]
    if dep.type not in plan["types"]:
        found.append(f"type is {dep.type or 'unknown'}: {why_not(dep.type)}. "
                     f"Delete it and deploy it again as {label}")
    elif dep.type != want["type"]:
        found.append(f"type is {plan['types'][dep.type]['label']}, the plan says {label}")
    if dep.model != dep.name:
        found.append(f"it runs the model {dep.model}; in this lab a deployment is named after its model")
    elif dep.version != want["version"]:
        found.append(f"version is {dep.version}, the plan says {want['version']}: a different version can "
                     "answer differently, so change config/models.json only after the H10 evaluation passes")
    return found


def retirement_note(model: str, plan: dict[str, Any] | None = None, today: dt.date | None = None) -> str:
    """'retires 2027-04-14 (in 190 days)', a warning when that's close, or '' if no date is known."""
    plan = plan or load_plan()
    when = plan["models"].get(model, {}).get("retires")
    if not when:
        return ""
    days = (dt.date.fromisoformat(when) - (today or dt.date.today())).days
    if days < 0:
        return f"RETIRED on {when}: replace it in config/models.json"
    if days <= WARN_DAYS:
        return f"WARNING: retires {when}, in {days} days. Move to its replacement now"
    return f"retires {when} (in {days} days)"