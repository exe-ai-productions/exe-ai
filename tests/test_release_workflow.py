"""The release workflow (.github/workflows/pakete.yml): on a version tag it
builds the Windows package — interface, frozen service, Electron shell — and
electron-builder hangs the installer and latest.yml on the release draft of
the tag. The macOS package is built on the maintainer's machine, so no job
runs on macOS here; and only the workflow uploads, the local scripts never do.

Read as YAML and checked for its shape: the trigger, the permission the
upload needs, the one Windows job, the order of its steps.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pakete.yml"
PACKAGE = ROOT / "fenster-electron" / "package.json"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _trigger(workflow: dict) -> dict:
    # YAML reads the bare key `on` as the boolean True.
    return workflow.get("on") or workflow[True]


def _runs(job: dict) -> list[str]:
    """The run lines of a job's steps, as written."""
    return [str(step.get("run", "")) for step in job["steps"]]


def _index(runs: list[str], text: str) -> int:
    hits = [i for i, run in enumerate(runs) if text in run]
    assert len(hits) == 1, (text, runs)
    return hits[0]


def test_a_version_tag_or_a_hand_start_triggers_the_build():
    trigger = _trigger(_workflow())
    assert "workflow_dispatch" in trigger
    assert trigger["push"]["tags"] == ["v*"]


def test_the_tests_use_every_core_of_the_runner():
    job = _workflow()["jobs"]["tests"]
    (step,) = [step for step in job["steps"] if str(step.get("run", "")).startswith("python -m pytest")]
    assert step["run"] == "python -m pytest tests/ -q -n 4 --dist loadfile"
    (install,) = [step for step in job["steps"] if "pip install" in str(step.get("run", ""))]
    assert "pytest-xdist" in install["run"]


def test_the_run_may_write_the_release():
    assert _workflow()["permissions"]["contents"] == "write"


def test_the_package_job_builds_on_windows_and_publishes_with_the_runs_token():
    job = _workflow()["jobs"]["paket"]
    assert job["runs-on"] == "windows-latest"
    # The package does not wait for the tests any more: both jobs start at
    # once, and a red test job is seen before the draft is published by hand.
    assert "needs" not in job
    (step,) = [
        step for step in job["steps"] if "electron-builder" in str(step.get("run", ""))
    ]
    assert step["run"] == "npx electron-builder --win --publish always"
    assert step["working-directory"] == "fenster-electron"
    assert step["env"]["GH_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"


def _install(job: dict, folder: str) -> int:
    """The index of the one `npm ci` run in ``folder``."""
    hits = [
        i for i, step in enumerate(job["steps"])
        if step.get("run") == "npm ci" and step.get("working-directory") == folder
    ]
    assert len(hits) == 1, (folder, job["steps"])
    return hits[0]


def test_interface_then_service_then_shell():
    job = _workflow()["jobs"]["paket"]
    runs = _runs(job)
    interface = _index(runs, "npm run build")
    service = _index(runs, "pyinstaller deploy/exe-ai-terminal.spec")
    shell = _index(runs, "electron-builder --win")
    assert interface < service < shell
    # Each build stands behind the install it needs.
    assert _install(job, "frontend") < interface
    assert service < _install(job, "fenster-electron") < shell


def test_the_tests_run_on_windows_before_the_package():
    job = _workflow()["jobs"]["tests"]
    assert job["runs-on"] == "windows-latest"
    assert any("pytest" in run for run in _runs(job))


def test_no_job_runs_on_macos():
    """The macOS package is built on the maintainer's machine: no job of
    the workflow runs on a macOS runner, by name or through a matrix."""
    for name, job in _workflow()["jobs"].items():
        assert "strategy" not in job, name
        assert str(job["runs-on"]).startswith("windows-"), (name, job["runs-on"])


def test_the_local_scripts_never_upload():
    """The silence probe: the upload is the workflow's alone — the scripts a
    developer runs by hand say `--publish never`."""
    scripts = json.loads(PACKAGE.read_text(encoding="utf-8"))["scripts"]
    assert scripts["packen"].endswith("--publish never")
    assert scripts["pack:win"].endswith("--publish never")
