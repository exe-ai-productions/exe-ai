"""The window treats `draw_video` the way it treats `draw_image`.

While the model makes a video the chat shows the same working tile as for a
picture, and the finished video stands at the chat at once; the tool list of
the settings names the tool with its kind, its mark and its sentence. Read off
the sources and the two language files, because the stream is the window's."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
LOCALES = ROOT / "app" / "locales"


def _read(path: str) -> str:
    return (SRC / path).read_text(encoding="utf-8")


def test_one_question_names_both_drawing_calls():
    state = _read("lib/zustand.svelte.js")
    body = state.split("export function isDrawingTool(name) {", 1)[1].split("}", 1)[0]
    assert "'draw_image'" in body and "'draw_video'" in body


def test_the_stream_and_the_reconnect_ask_that_question_and_no_longer_the_picture_alone():
    app = _read("App.svelte")
    assert app.count("isDrawingTool(ereignis.name)") == 2
    assert "ereignis.name === 'draw_image'" not in app
    state = _read("lib/zustand.svelte.js")
    assert "isDrawingTool(w.name) && w.ergebnis == null" in state
    assert "w.name === 'draw_image'" not in state


def test_the_tool_list_gives_the_video_tool_its_kind_and_its_mark():
    kinds = _read("lib/werkzeugarten.js")
    marks = _read("lib/werkzeugkatalog.js")
    assert re.search(r"draw_video:\s*'bilder'", kinds)
    assert re.search(r"draw_video:\s*'clapperboard'", marks)


def test_both_languages_carry_the_sentence_the_settings_asked_for():
    expected = {
        "de": "Erstellt ein kurzes Video mit dem lokalen Videomodell.",
        "en": "Creates a short video with the local video model.",
    }
    for locale, sentence in expected.items():
        texts = json.loads((LOCALES / f"{locale}.json").read_text(encoding="utf-8"))
        assert texts["werkzeuge"]["eingebaut_satz"]["draw_video"] == sentence, locale


def test_the_picture_tool_is_untouched():
    """Silence probe: the picture keeps its sentence, kind and mark."""
    texts = json.loads((LOCALES / "de.json").read_text(encoding="utf-8"))
    assert texts["werkzeuge"]["eingebaut_satz"]["draw_image"] == "Erzeugt ein Bild mit dem lokalen Bildmodell."
    assert re.search(r"draw_image:\s*'bilder'", _read("lib/werkzeugarten.js"))
    assert re.search(r"draw_image:\s*'bild'", _read("lib/werkzeugkatalog.js"))


def test_the_video_tool_wears_the_clapperboard_of_the_house_catalogue():
    """The sign is the catalogue's drawing, verbatim, in the house's one
    place for signs — not a second drawing in the tool marks."""
    signs = _read("teile/Hauszeichen.svelte")
    branch = signs.split("{:else if zeichen === 'clapperboard'}", 1)[1].split("{:else if", 1)[0]
    assert '<rect x="5.89" y="13.04" width="14" height="9.6" rx="1.6" />' in branch
    assert 'd="M5.89 13.04 L15.79 3.14 L14.02 1.37 L4.12 11.27 Z" stroke-width="1.33"' in branch
    assert branch.count('stroke-width="1.33"') == 5
    assert "'clapperboard'" not in _read("teile/Werkzeugzeichen.svelte")


def test_the_working_tile_says_video_while_the_video_tool_runs():
    state = _read("lib/zustand.svelte.js")
    body = state.split("export function drawingMakesVideo(answerId) {", 1)[1].split("\n}\n", 1)[0]
    assert "w.name === 'draw_video' && w.ergebnis == null" in body
    message = _read("teile/Nachricht.svelte")
    assert "drawingMakesVideo(nachricht.answerId) ? t('nachricht.video_laeuft') : t('nachricht.bild_laeuft')" in message
    assert '<span class="bild-kopf">{drawingWord}</span>' in message
    assert "setContext('tileWord', () => drawingWord)" in message
    filling = _read("teile/Bildfuellung.svelte")
    assert "const tileWord = getContext('tileWord')" in filling
    assert "(tileWord?.() ?? t('nachricht.bild_laeuft'))" in filling
    expected = {"de": "Video wird erzeugt", "en": "Generating video"}
    for locale, sentence in expected.items():
        texts = json.loads((LOCALES / f"{locale}.json").read_text(encoding="utf-8"))
        assert texts["nachricht"]["video_laeuft"] == sentence, locale


def test_silence_the_picture_tile_keeps_its_word():
    for locale, sentence in {"de": "Bild wird erzeugt", "en": "Generating image"}.items():
        texts = json.loads((LOCALES / f"{locale}.json").read_text(encoding="utf-8"))
        assert texts["nachricht"]["bild_laeuft"] == sentence, locale
    state = _read("lib/zustand.svelte.js")
    body = state.split("export function drawingMakesVideo(answerId) {", 1)[1].split("\n}\n", 1)[0]
    # A tile with no answer behind it — the picture window's own — is a picture.
    assert "if (answerId == null) return false" in body
