"""The language page of the settings: where its row stands, what the value in
the list says, and how the choice is made.

The row sits second in the group of the interface; the list shows the language
that is in use — "German" or "English", never "Auto" — while the field itself
offers "Auto" first and changes the language only through `spracheStellen`.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
PROMPT = SRC / "teile" / "SystemPrompt.svelte"
FIGURES = SRC / "lib" / "settingsState.svelte.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _find(pattern: str, text: str) -> re.Match[str]:
    match = re.search(pattern, text)
    assert match, pattern
    return match


def _node(code: str) -> Any:
    run = subprocess.run(
        ["node", "--input-type=module", "-e", code],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_the_language_row_is_second_in_the_group_of_the_interface():
    data = _node(
        f"import {{ GRUPPEN, SEITEN }} from '{SRC.as_uri()}/lib/einstellungsliste.js'\n"
        "console.log(JSON.stringify({ GRUPPEN, SEITEN }))"
    )
    group = next(g for g in data["GRUPPEN"] if g["name"] == "oberflaeche")
    assert [row["id"] for row in group["zeilen"]][:2] == ["darstellung", "sprache"]
    assert data["SEITEN"]["sprache"]["zeichen"] == "sprache"


def _list_value(language: str) -> str:
    """The text the derivation of the list's value gives for a language in use,
    run as it stands in the page, with the catalogue's `t` as an echo."""
    source = _read(FIGURES)
    derivation = _find(r"case 'sprache':\s*return (.*)\n", source).group(1)
    return _node(
        f"""
        const texte = {{ sprache: {json.dumps(language)} }}
        const t = (key) => key
        console.log(JSON.stringify({derivation.strip().rstrip(',')}))
        """
    )


def test_the_value_in_the_list_is_the_language_in_use_never_auto():
    assert _list_value("de") == "einstellungen.sprache_deutsch"
    assert _list_value("en") == "einstellungen.sprache_englisch"
    derivation = _find(r"case 'sprache':\s*return (.*)\n", _read(FIGURES)).group(1)
    # The choice (which can be "auto") never reaches the list, under any name.
    assert "sprachwahl" not in derivation and "texte.wahl" not in derivation
    assert "sprache_auto" not in derivation


def test_the_field_offers_auto_first_and_changes_the_language_only_through_the_switch():
    source = _read(PROMPT)
    entries = _find(r"const sprachauswahl = \$derived\(\[([\s\S]*?)\]\)", source).group(1)
    assert re.findall(r"wert: '([a-z]+)'", entries) == ["auto", "en", "de"]
    # Bound for reading only: the choice made is the one the texts report.
    assert re.search(r"bind:wert=\{\(\) => sprachwahl, \(\) => \{\}\}", source)
    assert re.search(r"gewaehlt=\{spracheStellen\}", source)
    assert re.search(
        r"import \{ spracheStellen \} from '\.\./lib/sprachwahl\.svelte\.js'", source
    )


def test_a_click_that_came_too_late_reports_no_failure():
    switch = _read(SRC / "lib" / "sprachwahl.svelte.js")
    assert "const mine = ++attempt" in switch
    assert re.search(
        r"catch \{\s*if \(mine === attempt\) melde\(t\('fehler\.allgemein'\), 'fehler'\)", switch
    )
