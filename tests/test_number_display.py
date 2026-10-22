"""How a number with a fractional step is written in a field and read from
it (frontend/src/lib/numberDisplay.js), RUN in node, and where the fields of
the program take it from.

One fractional digit at least, as many as the step has at most, the decimal
sign of the language, no thousands separator; a whole step stays a plain
whole number; typed, a comma and a point both count.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from tests.test_hintergrundmeldung import _node

FRONTEND = Path(__file__).resolve().parent.parent / "frontend/src"
MODULE = FRONTEND / "lib" / "numberDisplay.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")


def _run(expression: str):
    source = re.sub(r"^export ", "", MODULE.read_text(encoding="utf-8"), flags=re.M)
    return json.loads(_node(f"{source}\nconsole.log(JSON.stringify({expression}))"))


@needs_node
@pytest.mark.parametrize(
    ("wert", "schritt", "sprache", "erwartet"),
    [
        (1, 0.01, "de", "1,0"),
        (0.95, 0.01, "de", "0,95"),
        (0.8, 0.05, "de", "0,8"),
        (1, 0.01, "en", "1.0"),
        (0.8, 0.05, "en", "0.8"),
        (7, 0.5, "de", "7,0"),
        (40, 1, "de", "40"),
        (8192, 1, "de", "8192"),
        (4096, 1, "en", "4096"),
    ],
)
def test_a_value_is_written_with_the_digits_of_its_step(wert, schritt, sprache, erwartet):
    expression = f"formatNumber({wert}, fractionDigits({schritt}), {json.dumps(sprache)})"
    assert _run(expression) == erwartet


@needs_node
@pytest.mark.parametrize(
    ("wert", "sprache", "erwartet"),
    [
        (0.01, "de", "0,01"),
        (0.5, "de", "0,50"),
        (0.64, "de", "0,64"),
        (14.8, "de", "14,8"),
        (7, "de", "7,0"),
        (1, "de", "1,0"),
        (60.84, "de", "60,8"),
        (0.01, "en", "0.01"),
        (14.8, "en", "14.8"),
        (7, "en", "7.0"),
        (1234.5, "de", "1234,5"),
        (0.994, "de", "0,99"),
        (0.996, "de", "1,0"),
        (0.996, "en", "1.0"),
        (-0.001, "en", "0.00"),
    ],
)
def test_a_size_in_gb_has_two_digits_under_one_gb_and_one_from_one_gb(wert, sprache, erwartet):
    assert _run(f"formatGb({wert}, {json.dumps(sprache)})") == erwartet


@needs_node
def test_a_size_that_is_no_number_is_a_hyphen():
    assert _run(
        '[formatGb(null, "de"), formatGb(undefined, "de"), formatGb(NaN, "en"), formatGb("x", "de"),'
        ' formatGb("", "de"), formatGb(true, "de"), formatGb([], "de"), formatGb(Infinity, "en")]'
    ) == ["-"] * 8


@needs_node
def test_a_speed_in_mb_per_second_takes_the_sign_of_the_language():
    assert _run('[formatNumber(48.2, 1, "de"), formatNumber(48.2, 1, "en"), formatNumber(7, 1, "de")]') == [
        "48,2", "48.2", "7,0",
    ]


@needs_node
def test_the_digits_of_a_step_are_read_from_the_way_it_is_written():
    assert _run("[fractionDigits(1), fractionDigits(0.5), fractionDigits(0.05), fractionDigits(1e-7)]") == [
        0, 1, 2, 7,
    ]


@needs_node
def test_typed_input_counts_with_a_comma_and_with_a_point():
    assert _run('[parseNumber("0,9"), parseNumber("0.9"), parseNumber(" 1,25 "), parseNumber(""), parseNumber("   ")]') == [
        0.9, 0.9, 1.25, None, None,
    ]
    # Something that is no number is not read as one (JSON turns NaN into null,
    # so the check is done in the script).
    assert _run('Number.isNaN(parseNumber("abc"))') is True


def _source(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_the_number_field_with_a_fractional_step_is_a_text_field_of_its_own():
    source = _source("teile/Zahlenfeld.svelte")
    assert "import { fractionDigits, formatNumber, parseNumber } from '../lib/numberDisplay.js'" in source
    assert "const decimal = $derived(digits > 0)" in source
    assert 'inputmode="decimal"' in source
    assert 'role="spinbutton"' in source
    # Silence: a whole step keeps the native number field, with its own bind.
    assert 'type="number"' in source and "bind:value={wert}" in source
    # A whole-number field never takes the text path.
    assert "ganzzahlig ? 0 : fractionDigits(schritt)" in source


def test_the_other_fields_write_through_the_same_module():
    tafel = _source("teile/Parametertafel.svelte")
    assert "toFixed(nachkomma)" not in tafel
    assert "formatNumber(wert, nachkomma, texte.sprache)" in tafel
    assert "parseNumber(eingabe)" in tafel and not re.search(r"(?<!parse)Number\(eingabe\)", tafel)
    for name in ("teile/Bereinigungsserver.svelte", "teile/Sprachserver.svelte"):
        source = _source(name)
        assert "toFixed(2)" not in source, name
        assert "formatNumber(zahl, fractionDigits(schritt), texte.sprache)" in source, name
        assert "anzeige(w, p.ganzzahlig, p.schritt)" in source, name
