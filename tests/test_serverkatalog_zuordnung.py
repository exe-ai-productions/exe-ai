"""Which card a server entry belongs to, executed rather than read.

A server of one's own under a shipped name — a self-run `sentry` on another
address — used to appear as the shipped card, with its title and logo, and
wait for a sign-in it does not need. The rule lives in
frontend/src/lib/serverkatalog.js (`gehoertZurKachel`); the module is plain
ES and is run in node as it stands.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "frontend" / "src" / "lib" / "serverkatalog.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")

SHIPPED = "https://mcp.sentry.dev/mcp"


def _belongs(shipped_name: str, entry: dict) -> bool:
    script = f"""
import {{ SERVERKATALOG, gehoertZurKachel }} from {json.dumps(MODULE.as_uri())}
const katalog = SERVERKATALOG.find((k) => k.name === {json.dumps(shipped_name)})
console.log(JSON.stringify(gehoertZurKachel(katalog, {json.dumps(entry)})))
"""
    done = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=60, check=True,
    )
    return json.loads(done.stdout)


def test_an_entry_under_the_shipped_name_on_another_address_is_a_server_of_its_own():
    entry = {"name": "sentry", "type": "http", "url": "https://sentry.example.org/mcp"}
    assert _belongs("sentry", entry) is False


def test_an_entry_on_the_shipped_address_belongs_to_the_shipped_card():
    assert _belongs("sentry", {"name": "sentry", "type": "http", "url": SHIPPED}) is True


def test_a_program_started_here_under_a_shipped_name_is_a_server_of_its_own():
    entry = {"name": "sentry", "type": "stdio", "url": None}
    assert _belongs("sentry", entry) is False


def test_a_shipped_server_without_an_address_belongs_to_the_entry_of_its_name():
    assert _belongs("websuche", {"name": "websuche", "type": "stdio", "url": None}) is True


def test_silence_another_name_never_belongs_to_the_card():
    assert _belongs("sentry", {"name": "linear", "type": "http", "url": SHIPPED}) is False
    assert _belongs("websuche", {"name": "searxng", "type": "stdio", "url": None}) is False
