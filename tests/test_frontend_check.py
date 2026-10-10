"""svelte-check as part of the test run: catches missing component imports.

The trigger: a reference without an import built cleanly and then took down
the whole app in the browser (blank page, hotfix 4cd1b68). Vite doesn't check
for this — svelte-check does. Warnings are allowed, errors are not.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


@pytest.mark.skipif(shutil.which("npx") is None, reason="no Node on this machine")
def test_svelte_check_findet_keine_fehler():
    npx = shutil.which("npx")
    assert npx is not None
    lauf = subprocess.run(
        # By its found path: on Windows the name alone is no program, the
        # file is `npx.cmd` (WinError 2).
        [npx, "svelte-check", "--threshold", "error"],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-2000:]
