"""The "Server" step of .github/workflows/app.yml (D35): the input `platform` selects one profile
(deploy URL = identity token audience, policy bundle pin); unknown and unavailable servers fail
before anything is built or sent. The Python code is taken from the workflow itself."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((REPO / ".github/workflows/app.yml").read_text())
ENV = {k: str(v).strip() for k, v in WORKFLOW["env"].items()}
APPS_URL = "https://deploy.platform.shirtracer.gmbh"
TEST_PIN = "ghcr.io/x/platform-policy-testbox:1.0.0@sha256:" + "c" * 64
TEST_SERVERS = {
    "apps": json.loads(ENV["PLATFORM_SERVERS"])["apps"],
    "testbox": {"deploy_url": "https://deploy.test.example", "bundle": "POLICY_BUNDLE_TESTBOX"},
    "shops": None,
}


def server_step():
    steps = WORKFLOW["jobs"]["build"]["steps"]
    return next(s for s in steps if s.get("name") == "Server")


def server_code():
    return server_step()["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]


def run(tmp_path, platform="", controller_url="", **extra):
    out = tmp_path / "output"
    out.write_text("")
    env = {"PATH": os.environ["PATH"], "GITHUB_OUTPUT": str(out),
           "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
           "PLATFORM_SERVERS": ENV["PLATFORM_SERVERS"], "POLICY_BUNDLE": ENV["POLICY_BUNDLE"],
           "PLATFORM": platform, "CONTROLLER_URL_INPUT": controller_url}
    env.update(extra)
    proc = subprocess.run([sys.executable, "-c", server_code()], env=env, capture_output=True, text=True)
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)
    return proc.returncode, proc.stdout + proc.stderr, outputs


# --- US1: callers without the input get v1.0.6's behaviour --------------------------------------

def test_default_is_the_apps_server(tmp_path):
    rc, log, out = run(tmp_path)
    assert rc == 0, log
    assert out == {"server": "apps", "deploy_url": APPS_URL, "bundle": ENV["POLICY_BUNDLE"],
                   "version": ENV["POLICY_BUNDLE"].split(":", 1)[1].split("@", 1)[0]}
    assert out["version"] == "2.4.0"


def test_naming_apps_is_the_same_as_the_default(tmp_path):
    assert run(tmp_path, "apps")[2] == run(tmp_path, "")[2]


@pytest.mark.parametrize("given", [APPS_URL, APPS_URL + "/"])
def test_the_old_url_input_still_works_for_apps(tmp_path, given):
    rc, log, out = run(tmp_path, controller_url=given)
    assert rc == 0, log
    assert out["deploy_url"] == APPS_URL
    assert "::warning::controller-url is deprecated" in log


def test_the_server_step_comes_first_and_reads_the_inputs():
    steps = WORKFLOW["jobs"]["build"]["steps"]
    assert steps[0]["name"] == "Server" and steps[0]["id"] == "server"
    assert server_step()["env"] == {"PLATFORM": "${{ inputs.platform }}",
                                    "CONTROLLER_URL_INPUT": "${{ inputs.controller-url }}"}


# --- US2: an app chooses its server ---------------------------------------------------------------

def test_shops_has_its_own_url_audience_and_pin(tmp_path):
    rc, log, out = run(tmp_path, "shops", POLICY_BUNDLE_SHOPS=ENV["POLICY_BUNDLE_SHOPS"])
    assert rc == 0, log
    assert out["server"] == "shops" and out["deploy_url"] == "https://deploy.shops.shirtracer.gmbh"
    assert out["bundle"] == ENV["POLICY_BUNDLE_SHOPS"] and "platform-policy-shops:" in out["bundle"]
    assert APPS_URL not in out.values() and ENV["POLICY_BUNDLE"] not in out.values()


def test_a_known_server_without_a_profile_is_not_available(tmp_path):
    rc, log, out = run(tmp_path, "testbox", PLATFORM_SERVERS=json.dumps({**TEST_SERVERS, "testbox": None}))
    assert rc == 1 and out == {}
    assert "::error::the server testbox isn't available yet (known: apps, testbox, shops)" in log


def test_an_unknown_server_names_the_known_ones(tmp_path):
    rc, log, out = run(tmp_path, "other")
    assert rc == 1 and out == {}
    assert "::error::unknown platform other (known: apps, shops)" in log


def test_a_profile_brings_its_own_url_audience_and_pin(tmp_path):
    rc, log, out = run(tmp_path, "testbox", PLATFORM_SERVERS=json.dumps(TEST_SERVERS),
                       POLICY_BUNDLE_TESTBOX=TEST_PIN)
    assert rc == 0, log
    assert out == {"server": "testbox", "deploy_url": "https://deploy.test.example",
                   "bundle": TEST_PIN, "version": "1.0.0"}
    assert APPS_URL not in out.values() and ENV["POLICY_BUNDLE"] not in out.values()


def test_a_pin_of_another_package_is_refused(tmp_path):
    # The apps server's package as testbox's pin: one server's bundle with another's URL.
    rc, log, out = run(tmp_path, "testbox", PLATFORM_SERVERS=json.dumps(TEST_SERVERS),
                       POLICY_BUNDLE_TESTBOX=ENV["POLICY_BUNDLE"])
    assert rc == 1 and out == {}
    assert "::error::no policy bundle pinned for testbox (POLICY_BUNDLE_TESTBOX)" in log


def test_a_missing_pin_is_refused(tmp_path):
    rc, log, out = run(tmp_path, "testbox", PLATFORM_SERVERS=json.dumps(TEST_SERVERS))
    assert rc == 1 and out == {}
    assert "no policy bundle pinned for testbox" in log


def test_a_url_input_of_another_server_is_refused(tmp_path):
    rc, log, out = run(tmp_path, "testbox", controller_url=APPS_URL,
                       PLATFORM_SERVERS=json.dumps(TEST_SERVERS), POLICY_BUNDLE_TESTBOX=TEST_PIN)
    assert rc == 1 and out == {}
    assert "is not the deploy URL of testbox; use the platform input only" in log
    rc, log, _ = run(tmp_path, controller_url="https://deploy.elsewhere.example")
    assert rc == 1 and "use the platform input only" in log


def test_deploy_and_offboard_go_to_the_selected_server():
    for job in ("deploy", "offboard"):
        request = next(s for s in WORKFLOW["jobs"][job]["steps"] if s.get("name", "").startswith("Send"))
        assert request["env"]["CONTROLLER_URL"] == "${{ needs.build.outputs.deploy_url }}"
    assert WORKFLOW["jobs"]["build"]["outputs"]["deploy_url"] == "${{ steps.server.outputs.deploy_url }}"


def test_the_bundle_steps_use_the_selected_pin():
    steps = {s.get("name"): s for s in WORKFLOW["jobs"]["build"]["steps"]}
    for name in ("Policy bundle pin", "Pull the policy bundle"):
        assert steps[name]["env"]["BUNDLE"] == "${{ steps.server.outputs.bundle }}"
        assert "POLICY_BUNDLE" not in steps[name]["run"]


def test_every_known_server_with_a_profile_has_its_pin():
    servers = json.loads(ENV["PLATFORM_SERVERS"])
    assert servers["apps"] == {"deploy_url": APPS_URL, "bundle": "POLICY_BUNDLE"}
    for name, profile in servers.items():
        if profile:
            expected = "POLICY_BUNDLE" if name == "apps" else "POLICY_BUNDLE_" + name.upper()
            assert profile["bundle"] == expected and expected in ENV
