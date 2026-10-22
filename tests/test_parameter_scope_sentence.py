"""No sentence about how far the parameters reach stands over them.

The panel of a model's parameters is the same one on the local models page,
on the cloud page and on the phone. It names the parameters and shows their
values; it does not say for which chats they hold. Read off the source, the
way the other interface tests do.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
KEY = "gilt_fuer_modell"


def _markup(path: str) -> str:
    return (SRC / path).read_text(encoding="utf-8").split("<style>", 1)[0]


def _catalogue(language: str) -> dict:
    return json.loads((ROOT / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))


def test_the_panel_carries_no_hint_over_the_parameters():
    panel = _markup("teile/Parametertafel.svelte")
    # Everything from the section's opening tag to its first knob.
    section = panel.split("<Serverabschnitt", 1)[1].split("{#each", 1)[0]

    assert "hinweis" not in section
    assert KEY not in panel
    # The section has no head tooltip to carry one either.
    assert "hinweis" not in _markup("teile/Serverabschnitt.svelte")


def test_the_sentence_is_in_neither_catalogue():
    for language in ("de", "en"):
        assert KEY not in _catalogue(language).get("parameter", {}), language


def test_no_source_names_the_key_any_more():
    places = [*SRC.rglob("*"), *(ROOT / "app").rglob("*.py")]
    for path in places:
        if path.suffix in {".svelte", ".js", ".ts", ".py"}:
            assert KEY not in path.read_text(encoding="utf-8"), path


def test_silence_the_title_and_the_knobs_stand_where_they_stood():
    panel = _markup("teile/Parametertafel.svelte")

    # The title is the word, and with `withName` the word and the model's name.
    assert re.search(r"t\(['\"]parameter\.titel['\"]\)", panel)
    assert re.search(r"<Serverabschnitt[^>]*titel=\{sectionTitle\}", panel, re.S)
    assert re.search(r"zeichen=['\"]settings_two['\"]", panel)
    assert panel.index("{@render card(sampling)}") < panel.index("{@render card(lengths)}")
    assert "parameter.zuruecksetzen" in panel
    for language in ("de", "en"):
        assert _catalogue(language)["parameter"]["titel"], language


def test_all_three_places_still_use_the_one_panel():
    for path in ("teile/ModelleLokal.svelte", "teile/ModelleCloud.svelte", "phone/servers/ModelParams.svelte"):
        assert re.search(r"<Parametertafel\b", _markup(path)), path
