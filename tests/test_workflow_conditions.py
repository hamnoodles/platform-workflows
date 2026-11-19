"""Job conditions of .github/workflows/app.yml: one job validates and builds (with a build cache
written only on the push path), offboarding only by hand with confirmation, deploys only from the
default branch, superseded runs cancelled but never a sent request, identity tokens only in the
request jobs (contracts in the admin repository: specs/025-pipeline-minutes/contracts/workflow-jobs.md)."""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((REPO / ".github/workflows/app.yml").read_text())
JOBS = WORKFLOW["jobs"]
BUILD = JOBS["build"]
STEPS = BUILD["steps"]

# The validation steps of v1.2.0's job validate, unchanged and in order.
VALIDATION = [
    "Server", None, "Default branch", "Policy bundle pin", "Pull the policy bundle",
    "Validate platform.yaml and deploy/compose.yaml", "App name and secret names",
]


def _flat(text):
    return " ".join(str(text or "").split())


def _if(job):
    return _flat(JOBS[job].get("if", ""))


def _step(name):
    found = [s for s in STEPS if s.get("name") == name]
    assert len(found) == 1, name
    return found[0]


def _uses(fragment):
    return [s for s in STEPS if fragment in str(s.get("uses", ""))]


# --- Job structure (FR-009, FR-010) ---


def test_three_jobs_validate_and_build_is_one():
    assert set(JOBS) == {"build", "deploy", "offboard"}
    assert BUILD["name"] == "validate and build"
    assert "if" not in BUILD and "needs" not in BUILD
    assert JOBS["deploy"]["needs"] == "build"
    assert JOBS["offboard"]["needs"] == "build"


def test_the_validation_steps_are_unchanged_and_first():
    names = [s.get("name") for s in STEPS[:len(VALIDATION)]]
    assert names == VALIDATION
    assert "actions/checkout" in STEPS[1]["uses"]
    assert len(_uses("actions/checkout")) == 1, "one checkout for validation and build"
    for step in STEPS[:len(VALIDATION)]:
        assert "if" not in step, step.get("name")


def test_every_build_step_runs_only_for_the_deploy_action():
    # A manual offboard on the default branch has PUSH true: the action must be checked too.
    for step in STEPS[len(VALIDATION):]:
        assert "inputs.action == 'deploy'" in _flat(step.get("if")), step.get("name") or step.get("uses")


def test_the_push_flag_comes_from_the_default_branch_step():
    assert "env" not in BUILD, "a job's env can't read its own steps"
    run = _step("Default branch")["run"]
    assert '"$GITHUB_REF" = "refs/heads/$DEFAULT_BRANCH"' in run
    assert "push|workflow_dispatch) echo \"PUSH=true\" >>\"$GITHUB_ENV\"" in run
    assert run.count('echo "PUSH=false" >>"$GITHUB_ENV"') == 2
    assert 'echo "default=true" >>"$GITHUB_OUTPUT"' in run


def test_outputs_of_the_merged_job():
    assert set(BUILD["outputs"]) == {
        "app", "secret_names", "policy_version", "deploy_branch", "server", "deploy_url", "image"}
    assert BUILD["outputs"]["image"] == "${{ steps.result.outputs.image }}"


# --- Conditions of the request jobs ---


def test_deploy_only_from_the_default_branch_on_push_or_dispatch():
    cond = _if("deploy")
    assert "inputs.action == 'deploy'" in cond
    assert "needs.build.outputs.deploy_branch == 'true'" in cond
    assert "(github.event_name == 'push' || github.event_name == 'workflow_dispatch')" in cond
    assert "pull_request" not in cond


def test_offboard_only_by_hand_from_the_default_branch_with_confirmation():
    cond = _if("offboard")
    assert "inputs.action == 'offboard'" in cond
    assert "github.event_name == 'workflow_dispatch'" in cond and "push" not in cond
    assert "needs.build.outputs.deploy_branch == 'true'" in cond
    steps = JOBS["offboard"]["steps"]
    assert steps[0]["name"] == "Confirmation" and '"$CONFIRM" != "$APP"' in steps[0]["run"]
    assert steps[1]["env"]["ACTION"] == "offboard" and "SECRETS_JSON" not in steps[1]["env"]


def test_no_job_reads_the_old_validate_job():
    assert "needs.validate" not in yaml.safe_dump(WORKFLOW)


# Which jobs a run starts (contracts/workflow-jobs.md "Jobs per event"); each row: event, action,
# default branch -> the jobs that run. A job runs when every listed fragment of its `if` holds.
RUNS = [
    ("push", "deploy", True, {"build", "deploy"}),
    ("workflow_dispatch", "deploy", True, {"build", "deploy"}),
    ("workflow_dispatch", "offboard", True, {"build", "offboard"}),
    ("pull_request", "deploy", False, {"build"}),
    ("workflow_dispatch", "deploy", False, {"build"}),
]


def _runs(job, event, action, default):
    cond = _if(job)
    if not cond:
        return True
    checks = {
        "inputs.action == 'deploy'": action == "deploy",
        "inputs.action == 'offboard'": action == "offboard",
        "deploy_branch == 'true'": default,
        "(github.event_name == 'push' || github.event_name == 'workflow_dispatch')":
            event in ("push", "workflow_dispatch"),
        "github.event_name == 'workflow_dispatch'": event == "workflow_dispatch",
    }
    # Longest fragments first; a matched fragment is removed so its parts don't match again.
    holds, rest = [], cond
    for fragment in sorted(checks, key=len, reverse=True):
        if fragment in rest:
            holds.append(checks[fragment])
            rest = rest.replace(fragment, "")
    assert holds, (job, cond)
    return all(holds)


def test_billed_jobs_per_run():
    assert _flat(JOBS["deploy"]["if"]).count("&&") == 2
    assert _flat(JOBS["offboard"]["if"]).count("&&") == 2
    for event, action, default, expected in RUNS:
        started = {job for job in JOBS if _runs(job, event, action, default)}
        assert started == expected, (event, action, default)
    assert [len(row[3]) for row in RUNS] == [2, 2, 2, 1, 1]


# --- Build cache (FR-002 to FR-005) ---


def test_the_cache_is_the_buildcache_tag_of_the_app_package():
    run = _step("Image name")["run"]
    assert 'repo="${GITHUB_REPOSITORY,,}"' in run
    assert 'echo "cache=ghcr.io/$repo:buildcache"' in run
    assert 'echo "tag=ghcr.io/$repo:sha-$GITHUB_SHA"' in run
    assert '} >>"$GITHUB_OUTPUT"' in run


def test_every_build_reads_the_cache_and_only_the_push_path_writes_it():
    build = _step("Build (and push on the default branch)")["with"]
    assert build["cache-from"] == "type=registry,ref=${{ steps.name.outputs.cache }}"
    cache_to = _flat(build["cache-to"])
    assert cache_to == ("${{ env.PUSH == 'true' && format('type=registry,ref={0},mode=max,ignore-error=true', "
                        "steps.name.outputs.cache) || '' }}")
    assert build["push"] == "${{ env.PUSH == 'true' }}"
    assert build["tags"] == "${{ steps.name.outputs.tag }}"


def test_image_tags_stay_immutable():
    existing = _step("Existing image")
    assert _flat(existing["if"]) == "inputs.action == 'deploy' && env.PUSH == 'true'"
    assert "imagetools inspect" in existing["run"]
    for name in ("Build (and push on the default branch)",):
        assert "steps.existing.outputs.digest == ''" in _flat(_step(name)["if"])
    assert "steps.existing.outputs.digest == ''" in _flat(_uses("setup-buildx-action")[0]["if"])


def test_the_cache_never_reaches_a_request():
    for job in ("deploy", "offboard"):
        assert "buildcache" not in yaml.safe_dump(JOBS[job])
        assert "outputs.cache" not in yaml.safe_dump(JOBS[job])
    assert "cache" not in _step("Result")["run"]


# --- Registry login (FR-011) ---


def test_registry_login_mandatory_on_the_push_path_optional_elsewhere():
    logins = _uses("docker/login-action")
    assert len(logins) == 1
    login = logins[0]
    assert _flat(login["if"]) == "inputs.action == 'deploy'"
    assert login["continue-on-error"] == "${{ env.PUSH != 'true' }}"
    assert login["with"]["password"] == "${{ secrets.GITHUB_TOKEN }}"
    assert not [s for j in ("deploy", "offboard") for s in JOBS[j]["steps"]
                if "docker/login-action" in str(s.get("uses", ""))]


# --- Run groups (FR-006 to FR-008) ---


def test_run_groups():
    assert "concurrency" not in WORKFLOW
    assert BUILD["concurrency"] == {
        "group": "platform-build-${{ github.repository }}-${{ github.ref }}-${{ inputs.action }}",
        "cancel-in-progress": True,
    }
    assert JOBS["deploy"]["concurrency"] == {
        "group": "platform-deploy-${{ github.repository }}-${{ github.ref }}",
        "cancel-in-progress": False,
    }
    assert "concurrency" not in JOBS["offboard"]
    assert BUILD["concurrency"]["group"] != JOBS["deploy"]["concurrency"]["group"]


# --- Permissions, secrets, pins ---


def test_permissions_per_job():
    assert WORKFLOW["permissions"] == {}
    assert BUILD["permissions"] == {"contents": "read", "packages": "write"}
    for job in ("deploy", "offboard"):
        assert JOBS[job]["permissions"] == {"contents": "read", "id-token": "write"}
        assert JOBS[job]["environment"] == "${{ inputs.environment }}"


def test_secrets_only_in_the_deploy_request():
    for name, job in JOBS.items():
        text = yaml.safe_dump(job)
        if name == "deploy":
            assert "toJSON(secrets)" in text
        else:
            assert "toJSON(secrets)" not in text, name


def test_third_party_actions_are_pinned_by_commit():
    for job in JOBS.values():
        for step in job.get("steps", []):
            uses = step.get("uses")
            if uses:
                ref = uses.split("@", 1)[1]
                assert len(ref) == 40 and all(c in "0123456789abcdef" for c in ref), uses


def test_the_server_is_chosen_once_by_the_server_step():
    # D35: the input platform selects the profile; only the "Server" step reads the inputs that
    # name a server or URL, and every later step uses its outputs.
    assert WORKFLOW["on"]["workflow_call"]["inputs"]["platform"]["default"] == "apps"
    assert WORKFLOW["on"]["workflow_call"]["inputs"]["controller-url"]["default"] == ""
    assert BUILD["steps"][0]["id"] == "server"
    readers = [(job, step.get("name")) for job, spec in JOBS.items() for step in spec.get("steps", [])
               if "inputs.controller-url" in yaml.safe_dump(step) or "inputs.platform" in yaml.safe_dump(step)]
    assert readers == [("build", "Server")]


def test_the_apps_pin_keeps_its_name_and_version():
    # The admin check of every server reads POLICY_BUNDLE (apps) or POLICY_BUNDLE_<SERVER>.
    assert "platform-policy:2.4.0@sha256:" in WORKFLOW["env"]["POLICY_BUNDLE"]


def test_the_caller_interface_is_unchanged():
    # FR-001: the inputs and the secret of v1.2.0.
    call = WORKFLOW["on"]["workflow_call"]
    assert set(call["inputs"]) == {"action", "confirm", "environment", "platform", "controller-url",
                                   "dockerfile", "context"}
    assert set(call["secrets"]) == {"PLATFORM_SECRETS"}
