"""No text of the catalogues and no stand-in written in the sources of the
interface carries a long dash, and a choice with nothing chosen and a log with
nothing in it show a hyphen, not the word "empty".

The checks read the catalogues and the sources of the interface as they ship;
a sentence the backend builds from several parts is not read here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "app" / "locales"
FRONTEND = ROOT / "frontend" / "src"
LONG_DASH = "—"


def _values(node: dict, path: str = "") -> dict[str, str]:
    found: dict[str, str] = {}
    for key, value in node.items():
        if isinstance(value, dict):
            found.update(_values(value, f"{path}{key}."))
        elif isinstance(value, str):
            found[f"{path}{key}"] = value
    return found


def _catalogue(language: str) -> dict[str, str]:
    return _values(json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8")))


def _without_comments(source: str) -> str:
    # A "/*" inside a string ("video/*", "./pages/*.svelte") opens no comment.
    source = re.sub(r"(?<![\w'\"/.*])/\*.*?\*/", "", source, flags=re.S)
    source = re.sub(r"<!--.*?-->", "", source, flags=re.S)
    return re.sub(r"(?m)(?<![:\"'])//[^\n]*", "", source)


@pytest.mark.parametrize("language", ["de", "en"])
def test_no_value_of_a_catalogue_carries_a_long_dash(language):
    carrying = [key for key, value in _catalogue(language).items() if LONG_DASH in value]
    assert not carrying, f"{language}.json: {carrying}"


@pytest.mark.parametrize("language", ["de", "en"])
def test_no_value_is_the_word_empty_for_a_choice_of_nothing(language):
    words = {"empty", "leer"}
    carrying = [key for key, value in _catalogue(language).items() if value.strip().lower() in words]
    assert not carrying, f"{language}.json: {carrying}"


@pytest.mark.parametrize("key", [
    "sprachserver.bereinigung_aus",
    "bereinigungsserver.leer",
    "modell.modell_keiner",
    "modell.drafter_keiner",
    "modell.vision_keiner",
    "studio.stil_keiner",
])
def test_a_choice_of_nothing_and_an_empty_log_show_a_hyphen(key):
    for language in ("de", "en"):
        assert _catalogue(language)[key] == "-"


def test_the_cleaner_model_entry_carries_no_addition():
    assert _catalogue("en")["sprachserver.bereinigung_putzmodell_leer"] == "Clean-up model"
    assert _catalogue("de")["sprachserver.bereinigung_putzmodell_leer"] == "Bereinigungsmodell"


def test_no_source_of_the_interface_writes_a_long_dash_outside_its_comments():
    carrying = []
    for path in sorted(FRONTEND.rglob("*")):
        if path.suffix in (".svelte", ".js") and LONG_DASH in _without_comments(path.read_text(encoding="utf-8")):
            carrying.append(str(path.relative_to(FRONTEND)))
    assert not carrying, carrying


def test_silence_a_value_with_a_placeholder_keeps_it():
    for language in ("de", "en"):
        catalogue = _catalogue(language)
        assert "{zeit}" in catalogue["nachricht.gedankengang_laeuft"]
        # The reasons of a permission name no place any more: the card marks it
        # in the command, so no sentence waits for a value.
        for key in ("grund_ausserhalb", "grund_netz", "reason_cli"):
            assert "{pfad}" not in catalogue[f"werkzeug.{key}"], key
    assert _catalogue("en")["nachricht.ziel_erreicht"] == "Goal reached -"
