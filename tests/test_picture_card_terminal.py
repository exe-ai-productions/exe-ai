"""The picture card of the terminal tab: one prompt, named dials.

A drawing job's card used to unfold with the prompt a second time and with
the fields under the service's own names (`hoehe`, `diffusion_model`). The
dials now carry the words the studio and the picture server already have;
a field none of them names stays under its own name, and that list is
pinned here so a new field of the request cannot join it unseen.

The word table is a plain module and is run in node rather than read.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "frontend" / "src" / "lib" / "pictureFieldNames.js"
CARD = ROOT / "frontend" / "src" / "teile" / "ModulTerminal.svelte"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _catalogue(language: str) -> dict[str, str]:
    flat: dict[str, str] = {}

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}{key}.")
        else:
            flat[path[:-1]] = node

    walk(json.loads((ROOT / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8")), "")
    return flat


def _module() -> dict:
    """What the word table says: field -> key, the fields without a word."""
    script = (
        "import(process.argv[1]).then((m) => console.log(JSON.stringify("
        "{table: m.FIELD_WORD, without: m.WITHOUT_LABEL,"
        " names: Object.fromEntries(['hoehe','hires_width','control_image','constructor','toString'].map((f) =>"
        " [f, m.pictureFieldName(f, (k) => ({'bild.hoehe': 'Height', 'bild.hires_breite': 'Target width'}[k] ?? k))]))})))"
    )
    done = subprocess.run(
        ["node", "-e", script, LIB.as_uri()], capture_output=True, text=True, timeout=60, check=True
    )
    return json.loads(done.stdout)


@needs_node
def test_every_word_the_table_points_to_exists_in_both_catalogues():
    table = _module()["table"]
    for language in ("de", "en"):
        catalogue = _catalogue(language)
        missing = [key for key in table.values() if key not in catalogue]
        assert missing == [], (language, missing)


@needs_node
def test_the_table_names_every_field_a_word_exists_for_and_lists_the_rest():
    """Falls over when the request gains a field: it is either named in the
    table or listed as one without a word — never silently raw."""
    from app.api.v1.bild import BildWunsch
    from app.bildlauf import _ALS_ZEILE_GEZEIGT, _NICHT_REGLER

    module = _module()
    catalogue = _catalogue("de")
    shown = set(BildWunsch.model_fields) - _NICHT_REGLER - _ALS_ZEILE_GEZEIGT
    assert shown == set(module["table"]) | set(module["without"])
    assert not set(module["table"]) & set(module["without"])
    # A field whose own `bild.<field>` word exists is never left without one.
    own = {field for field in module["without"] if f"bild.{field}" in catalogue}
    assert own == set()


@needs_node
def test_a_named_field_shows_its_word_and_an_unnamed_one_its_own_name():
    names = _module()["names"]
    assert names["hoehe"] == "Height"
    assert names["hires_width"] == "Target width"
    assert names["control_image"] == "control_image"
    # A name the table does not hold must not resolve to a member of Object.
    assert names["constructor"] == "constructor"
    assert names["toString"] == "toString"


def test_the_card_names_the_dials_and_does_not_cut_them_off():
    source = CARD.read_text(encoding="utf-8")
    assert "pictureFieldName(schluessel, t)" in source
    # The one raw `<dt>{schluessel}</dt>` left is the tool call's own
    # arguments, which are the tool's, not a picture's.
    assert source.count("<dt>{schluessel}</dt>") == 1
    assert re.search(r"\.aufruf-text\.picture-values\s*{[^}]*max-height:\s*none", source)
