"""The MCP gallery says why a call failed: the sentence the service gave for
its refusal, and the general one only where it gave none (source guard of
``frontend/src/teile/Verbindungen.svelte``)."""

from __future__ import annotations

import re
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "frontend/src/teile/Verbindungen.svelte"


def _text() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_the_four_calls_hand_the_error_to_the_message():
    text = _text()
    for name in ("laden", "kippen", "vergessen", "entfernen"):
        body = re.search(rf"function {name}\(.*?\n  \}}\n", text, re.S)
        assert body is not None, name
        assert "catch (error)" in body.group(0), name
        assert "melde(errorSentence(error), 'fehler')" in body.group(0), name


def test_the_message_is_the_service_sentence_and_only_otherwise_the_general_one():
    text = _text()
    helper = re.search(r"function errorSentence\(error\) \{.*?\n  \}\n", text, re.S)
    assert helper is not None
    assert "error instanceof ApiFehler" in helper.group(0)
    assert "error.message" in helper.group(0)
    assert "t('fehler.allgemein')" in helper.group(0)
    assert "import { api, ApiFehler } from '../lib/api.js'" in text
