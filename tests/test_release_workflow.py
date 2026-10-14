"""The release workflow (.github/workflows/pakete.yml): on a version tag it
runs the tests and builds the Windows package — interface, frozen service,
Electron shell — in two jobs that start side by side, and electron-builder
hangs the installer and latest.yml on the release draft of the tag. Nothing
runs when that draft is published, and no job writes to another repository.
The macOS package is built on the maintainer's machine, so no job runs on
macOS here; and only the workflow uploads, the local scripts never do.

Read as YAML and checked for its shape: the triggers, the permission the
upload needs, the runner of each job, what its steps run and in which order.
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


def test_the_tests_run_on_four_workers():
    runs = _runs(_workflow()["jobs"]["tests"])
    assert runs[_index(runs, "python -m pytest")] == "python -m pytest tests/ -q -n 4 --dist loadfile"
    assert "pytest-xdist" in runs[_index(runs, "pip install")]


def test_the_run_may_write_the_release():
    assert _workflow()["permissions"]["contents"] == "write"


def test_the_package_job_builds_on_windows_and_publishes_with_the_runs_token():
    job = _workflow()["jobs"]["paket"]
    assert job["runs-on"] == "windows-latest"
    # The package does not wait for the tests any more: both jobs start at
    # once, and a red test job is seen before the draft is published by hand.
    assert "needs" not in job
    step = job["steps"][_index(_runs(job), "electron-builder")]
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


def test_the_tests_run_on_windows():
    job = _workflow()["jobs"]["tests"]
    assert job["runs-on"] == "windows-latest"
    runs = _runs(job)
    assert "pytest" in runs[_index(runs, "python -m pytest")]


def test_no_job_runs_on_macos():
    """The macOS package is built on the maintainer's machine: no job of
    the workflow runs on a macOS runner, by name or through a matrix. The
    two jobs that build and test stay on Windows."""
    jobs = _workflow()["jobs"]
    for name, job in jobs.items():
        assert "strategy" not in job, name
        assert not str(job["runs-on"]).startswith("macos"), (name, job["runs-on"])
    for name in ("tests", "paket"):
        assert str(jobs[name]["runs-on"]).startswith("windows-"), name


# --- no cask, and nothing runs on a published release ------------------------


def test_no_job_describes_a_cask_or_writes_to_another_repository():
    """The program reaches a Mac with the app, and the command with it: no
    job describes a tap, none checks out a repository other than this one,
    and no token for another repository is asked for."""
    jobs = _workflow()["jobs"]
    assert "cask" not in jobs
    for name, job in jobs.items():
        for step in job["steps"]:
            assert "repository" not in (step.get("with") or {}), name
    assert "TAP_TOKEN" not in WORKFLOW.read_text(encoding="utf-8")


def test_publishing_the_draft_starts_nothing():
    """A published release is no trigger, so no job carries a condition
    that asks whether the run came from one."""
    workflow = _workflow()
    assert "release" not in _trigger(workflow)
    for name, job in workflow["jobs"].items():
        assert "release" not in str(job.get("if", "")), name


def test_the_local_scripts_never_upload():
    """The silence probe: the upload is the workflow's alone — the scripts a
    developer runs by hand say `--publish never`."""
    scripts = json.loads(PACKAGE.read_text(encoding="utf-8"))["scripts"]
    assert scripts["packen"].endswith("--publish never")
    assert scripts["pack:win"].endswith("--publish never")
