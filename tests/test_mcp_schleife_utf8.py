"""The bundled MCP servers answer in UTF-8 whatever the console code page is.

On Windows a text pipe takes the ANSI code page. An answer with a character
outside it (an emoji, Cyrillic or CJK) used to raise ``UnicodeEncodeError``
and end the server; an umlaut reached the client, which reads UTF-8, as a
replacement character. ``PYTHONIOENCODING=cp1252`` is how a Windows pipe is
reproduced on any system.

Needs only ``mcp/mcp_schleife.py`` and the standard library.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

MCP_FOLDER = Path(__file__).resolve().parents[1] / "mcp"

TEXT = "Phone \U0001F4DE, Müller, Straße, Привет, 你好"

SERVER = f"""
import sys
sys.path.insert(0, {str(MCP_FOLDER)!r})
import mcp_schleife

TEXT = {TEXT!r}


async def run(name, arguments):
    return TEXT


mcp_schleife.starten("echo", "0.0.0", [], run)
"""

CALL = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {"name": "echo", "arguments": {}},
}


def _ask(tmp_path: Path, encoding: str) -> subprocess.CompletedProcess[bytes]:
    script = tmp_path / "server.py"
    script.write_text(textwrap.dedent(SERVER), encoding="utf-8")
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONUTF8"}
    environment["PYTHONIOENCODING"] = encoding
    return subprocess.run(
        [sys.executable, str(script)],
        input=(json.dumps(CALL) + "\n").encode("utf-8"),
        capture_output=True,
        env=environment,
        timeout=60,
    )


def test_an_answer_outside_the_console_code_page_arrives_as_utf8(tmp_path):
    done = _ask(tmp_path, "cp1252")
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    line = done.stdout.decode("utf-8").splitlines()[0]
    answer = json.loads(line)
    assert answer["result"]["content"][0]["text"] == TEXT


def test_an_answer_in_a_utf8_console_stays_character_for_character_the_same(tmp_path):
    done = _ask(tmp_path, "utf-8")
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    expected = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": TEXT}]},
        },
        ensure_ascii=False,
    )
    assert done.stdout == (expected + "\n").encode("utf-8")
