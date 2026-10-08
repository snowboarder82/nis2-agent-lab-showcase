"""H11 tests for the workflow files themselves: the security rules every job must keep. A change that
breaks one fails here, in the pull request, before it can run on GitHub with your Azure identities."""
import re
from pathlib import Path

import pytest
import yaml

from tools import changed

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
FILES = {"ci": WORKFLOWS / "ci.yml", "release": WORKFLOWS / "release.yml"}
# The job each GitHub environment belongs to, and the identity it signs in as (tools/ci_env.py).
ENVIRONMENTS = {"tools": "tools", "gate": "eval", "agent": "agent"}


def load(name):
    return yaml.safe_load(FILES[name].read_text(encoding="utf-8"))


def triggers(wf):
    return wf.get("on", wf.get(True))   # YAML 1.1 reads the key "on" as True


def all_jobs():
    for name in FILES:
        for job_name, job in load(name)["jobs"].items():
            yield name, job_name, job


def all_steps():
    for name, job_name, job in all_jobs():
        for step in job["steps"]:
            yield name, job_name, step


def test_ci_has_exactly_the_two_checks_the_ruleset_requires():
    assert set(load("ci")["jobs"]) == {"tests", "secrets"}


def test_every_action_is_pinned_to_a_full_commit_id_with_its_version_beside_it():
    for name, path in FILES.items():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "uses:" in line:
                assert re.fullmatch(r"\s+(- )?uses: [\w.-]+/[\w.-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+", line), (name, line)


def test_one_action_one_commit_everywhere():
    seen = {}
    for name, job_name, step in all_steps():
        if "uses" in step:
            action, sha = step["uses"].split("@")
            assert seen.setdefault(action, sha) == sha, (name, job_name, action)


def test_only_the_actions_this_lab_trusts():
    used = {step["uses"].split("@")[0] for _, _, step in all_steps() if "uses" in step}
    assert used == {"actions/checkout", "actions/setup-python", "azure/login", "Azure/functions-action"}


def test_the_token_can_only_read_unless_a_job_says_otherwise():
    for name in FILES:
        assert load(name)["permissions"] == {"contents": "read"}, name


def test_only_jobs_behind_an_approval_can_sign_in_to_azure():
    for name, job_name, job in all_jobs():
        perms = job.get("permissions", {})
        if perms.get("id-token") == "write":
            assert job.get("environment") == ENVIRONMENTS.get(job_name), (name, job_name)
            assert perms == {"contents": "read", "id-token": "write"}, (name, job_name)
        else:
            assert "environment" not in job and "id-token" not in perms, (name, job_name)
    signs_in = {job_name for _, job_name, job in all_jobs() if job.get("permissions", {}).get("id-token")}
    assert signs_in == set(ENVIRONMENTS)


def test_each_job_writes_the_settings_for_its_own_environment():
    jobs = load("release")["jobs"]
    for job_name, environment in ENVIRONMENTS.items():
        runs = [s["run"] for s in jobs[job_name]["steps"] if "ci_env" in s.get("run", "")]
        assert len(runs) == 1 and runs[0].split()[-1] == environment, job_name
        dotenv = [s for s in jobs[job_name]["steps"] if "ci_env" in s.get("run", "")][0]["env"]
        assert dotenv == {"DOTENV": "${{ secrets.DOTENV }}"}


def test_the_only_secret_is_dotenv_and_only_in_the_release_jobs():
    assert "secrets." not in FILES["ci"].read_text(encoding="utf-8")
    used = set(re.findall(r"secrets\.(\w+)", FILES["release"].read_text(encoding="utf-8")))
    assert used == {"DOTENV"}


def test_no_trigger_that_runs_someone_elses_code_with_your_rights():
    for name in FILES:
        assert not {"pull_request_target", "workflow_run"} & set(triggers(load(name))), name


def test_the_release_runs_only_from_main_or_by_hand():
    on = triggers(load("release"))
    assert set(on) == {"push", "workflow_dispatch"} and on["push"] == {"branches": ["main"]}
    choice = on["workflow_dispatch"]["inputs"]["run"]
    assert set(choice["options"]) == set(changed.BY_HAND) and choice["default"] == "agent"
    step = load("release")["jobs"]["changes"]["steps"][-1]
    assert step["env"]["RUN"] == "${{ inputs.run }}" and step["run"] == "python3 -m tools.changed"


def test_checkout_never_leaves_a_token_behind():
    for name, job_name, step in all_steps():
        if step.get("uses", "").startswith("actions/checkout@"):
            assert step["with"]["persist-credentials"] is False, (name, job_name)


def test_no_expression_inside_a_script():
    """${{ }} inside run: is pasted into the script before it runs, so a crafted value could become a
    command. Values go in through env: instead."""
    for name, job_name, step in all_steps():
        assert "${{" not in step.get("run", ""), (name, job_name, step.get("name"))


def test_nothing_is_uploaded_where_any_github_user_could_download_it():
    for name, path in FILES.items():
        text = path.read_text(encoding="utf-8")
        assert "upload-artifact" not in text and "GITLEAKS_ENABLE_UPLOAD_ARTIFACT" not in text, name


def test_every_job_has_a_time_limit():
    for name, job_name, job in all_jobs():
        assert 0 < job["timeout-minutes"] <= 90, (name, job_name)


def test_the_job_that_can_deploy_runs_no_python_packages():
    steps = load("release")["jobs"]["tools"]["steps"]
    assert {s["uses"].split("@")[0] for s in steps if "uses" in s} == {"actions/checkout", "azure/login",
                                                                       "Azure/functions-action"}
    scripts = " ".join(s.get("run", "") for s in steps)
    assert "pip" not in scripts and "python -m" not in scripts   # only python3 -m tools.ci_env, plain Python


def test_the_tools_deploy_ends_with_the_401_check():
    steps = load("release")["jobs"]["tools"]["steps"]
    assert steps[-2]["uses"].startswith("Azure/functions-action@") and steps[-2]["with"]["remote-build"] is True
    assert '"401"' in steps[-1]["run"] and "/api/health" in steps[-1]["run"]


def test_the_gate_measures_judges_gates_and_always_cleans_up():
    steps = load("release")["jobs"]["gate"]["steps"]
    runs = [s.get("run", "") for s in steps]
    order = ["eval.candidates --next --create", "eval.run --next", "eval.judge", "eval.gate", "agents.release"]
    where = [next(i for i, r in enumerate(runs) if text in r) for text in order]
    assert where == sorted(where)
    assert "agents.release --create" not in " ".join(runs)          # the gate job never publishes
    build = next(s for s in steps if s.get("id") == "build")
    assert "eval.candidates --next --create" in build["run"]
    # always deleted once the build step started, even when a later step failed
    assert steps[-1]["if"] == "${{ always() && steps.build.outcome != 'skipped' }}" and "--delete" in steps[-1]["run"]
    logins = [i for i, s in enumerate(steps) if s.get("uses", "").startswith("azure/login@")]
    assert len(logins) == 2 and logins[1] < where[2]                # signed in again before the judge


def test_the_gate_runs_after_skipped_tools_but_never_after_failed_ones():
    gate = load("release")["jobs"]["gate"]
    condition = gate["if"].replace(" ", "")
    assert set(gate["needs"]) == {"changes", "tools"} and "||" not in condition
    assert condition.startswith("${{!cancelled()&&!failure()&&")


def test_nothing_can_swallow_a_failed_gate():
    assert "continue-on-error" not in FILES["release"].read_text(encoding="utf-8")
    steps = load("release")["jobs"]["gate"]["steps"]
    asks = next(s for s in steps if s.get("run", "").startswith("python -m eval.gate"))
    differs = next(s for s in steps if s.get("id") == "differs")
    assert "if" not in asks and "||" not in asks["run"] and "if" not in differs
    assert steps.index(asks) < steps.index(differs)
    assert "||" not in load("release")["jobs"]["agent"]["if"]


def test_every_job_that_changes_azure_first_checks_it_is_mains_newest_commit():
    jobs = load("release")["jobs"]
    for job_name in ENVIRONMENTS:
        steps = jobs[job_name]["steps"]
        assert steps[0]["uses"].startswith("actions/checkout@") and "ref" not in steps[0]["with"]
        assert steps[1]["run"] == "python3 -m tools.changed --newest", job_name


def test_the_changes_job_may_read_past_runs_and_nothing_else():
    job = load("release")["jobs"]["changes"]
    assert job["permissions"] == {"contents": "read", "actions": "read"}
    step = job["steps"][-1]
    assert step["env"]["GH_TOKEN"] == "${{ github.token }}" and "BEFORE" not in step["env"]
    # an older run stops before it decides anything, so it never asks you to approve
    assert [s.get("run") for s in job["steps"][1:]] == ["python3 -m tools.changed --newest", "python3 -m tools.changed"]


def test_only_a_passed_gate_on_main_can_publish():
    agent = load("release")["jobs"]["agent"]
    assert agent["needs"] == "gate"
    for condition in ("needs.gate.result == 'success'", "needs.gate.outputs.publish == 'true'",
                      "github.ref == 'refs/heads/main'"):
        assert condition in agent["if"]
    assert agent["steps"][-1]["run"] == "python -m agents.release --create"
    gate = load("release")["jobs"]["gate"]
    assert gate["outputs"]["publish"] == "${{ steps.differs.outputs.publish }}"


def test_releases_wait_in_line():
    assert load("release")["concurrency"] == {"group": "release", "cancel-in-progress": False}


def test_the_secret_scan_checks_its_download_and_scans_the_whole_history():
    steps = load("ci")["jobs"]["secrets"]["steps"]
    assert steps[0]["with"]["fetch-depth"] == 0
    install = steps[1]
    assert re.fullmatch(r"[0-9a-f]{64}", install["env"]["SHA256"]) and "sha256sum --check" in install["run"]
    assert steps[-1]["run"].startswith("./gitleaks git --redact")


# ------------------------------------------------------------------ Dependabot
@pytest.fixture
def dependabot():
    return yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))


def test_dependabot_updates_packages_and_actions_after_a_cooldown(dependabot):
    assert dependabot["version"] == 2
    by = {u["package-ecosystem"]: u for u in dependabot["updates"]}
    assert set(by) == {"pip", "github-actions"}
    for update in by.values():
        assert update["directory"] == "/" and update["cooldown"]["default-days"] >= 7
        assert update["schedule"]["interval"] == "weekly"


def test_dependabot_never_offers_the_version_requirements_txt_rules_out(dependabot):
    pip = next(u for u in dependabot["updates"] if u["package-ecosystem"] == "pip")
    assert {"dependency-name": "azure-ai-projects", "versions": [">=2.8.0"]} in pip["ignore"]
    assert "agent-framework-foundry 1.14 needs <2.8" in (ROOT / "requirements.txt").read_text(encoding="utf-8")