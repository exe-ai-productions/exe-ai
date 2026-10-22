"""On a real Windows the shell tool's line writes a file from a command with
angle brackets in double quotes.

``test_shell_windows_line.py`` imitates the platform and checks the string the
tool hands to the system. This one runs the real thing and looks at the result:
a ``<`` or ``>`` inside the user's quotes must reach the program, not be read
by a command processor as a redirection. It runs on Windows only.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from app.tools import shell

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the line is a Windows one")

HTML = "<h1>a</h1>"
# Exactly as a model writes it: the interpreter by its bare name, the code in
# double quotes, the angle brackets inside them.
COMMAND = """python -c "open('page.html','w').write('<h1>a</h1>')" """.strip()


@pytest.mark.asyncio
async def test_angle_brackets_in_double_quotes_reach_the_program_through_the_tools_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # The bare name finds the interpreter that runs the tests, whatever the
    # PATH of the machine says.
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    process = await shell._starten(COMMAND, tmp_path)
    _, error = await asyncio.wait_for(process.communicate(), timeout=60)
    written = tmp_path / "page.html"
    assert written.is_file(), error.decode("utf-8", "replace")
    assert written.read_text(encoding="utf-8") == HTML
