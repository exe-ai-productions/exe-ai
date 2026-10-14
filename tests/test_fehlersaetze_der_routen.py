"""The sentences the routers in ROUTEN hand to the interface come from
the catalogue, in the language of the request.

A fixed sentence in the source reaches an English window in German — the
interface shows `detail` verbatim (frontend/src/lib/api.js). The guard below
walks the source; the calls behind it show the sentence the user really gets.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.i18n import t

WURZEL = Path(__file__).resolve().parents[1]
ROUTEN = [
    WURZEL / "app/api/v1/skills.py",
    WURZEL / "app/api/v1/berechtigungen.py",
    WURZEL / "app/api/v1/einstellungen.py",
    WURZEL / "app/api/v1/generierung.py",
    WURZEL / "app/api/v1/bild.py",
]

EN = {"X-Ui-Language": "en"}
DE = {"X-Ui-Language": "de"}


def _ist_fester_satz(knoten: ast.expr) -> bool:
    """A sentence written here instead of taken from the catalogue: a plain
    literal, an f-string — and the three ways a literal is dressed up,
    .format(), % and +."""
    if isinstance(knoten, ast.JoinedStr):
        return True
    if isinstance(knoten, ast.Constant) and isinstance(knoten.value, str):
        return True
    if isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Attribute):
        return knoten.func.attr == "format"
    if isinstance(knoten, ast.BinOp) and isinstance(knoten.op, (ast.Add, ast.Mod)):
        return True
    return False


def test_keine_feste_zeichenkette_in_http_exception():
    """Guard: every refusal in the routers of ROUTEN is built through `t(…)`.

    A sentence written here would be one the catalogue never sees — and the
    catalogue is the one place the interface's texts live (Repo-CLAUDE.md).
    every argument after the status counts, keyword ones included:
    `detail="…"` is the form the neighbouring routers use. `str(fehler)`
    stays allowed — it is no sentence written here; the German sentences of
    the exceptions behind it are an open point of their own.
    """
    fehler = []
    for pfad in ROUTEN:
        for knoten in ast.walk(ast.parse(pfad.read_text(encoding="utf-8"))):
            if not isinstance(knoten, ast.Call):
                continue
            gerufen = getattr(knoten.func, "id", None) or getattr(knoten.func, "attr", None)
            if gerufen != "HTTPException":
                continue
            gemeldet = [*knoten.args[1:]]
            gemeldet += [
                eintrag.value
                for eintrag in knoten.keywords
                if eintrag.arg not in ("status_code", "headers")
            ]
            if any(_ist_fester_satz(argument) for argument in gemeldet):
                fehler.append(f"{pfad.name}:{knoten.lineno}")
    assert fehler == []


def test_an_f_string_is_a_sentence_of_this_file():
    """The guard's own edge, pinned: an f-string counts, own text or not —
    gluing a catalogue sentence and a value together is the shape this very
    source used to have (app/api/v1/bild.py), and the reason for it belongs
    in the catalogue now."""
    assert _ist_fester_satz(ast.parse('f"{t(\'x\', s)}\\n\\n{error}"').body[0].value)
    assert _ist_fester_satz(ast.parse('f"Der Wert {x} ist falsch"').body[0].value)


def test_a_stop_with_an_id_passes_this_check(client):
    """The silence probe for the stop route: with a `chat_id` it answers as it
    always did — the sentence above is only for the request that names no id
    at all."""
    antwort = client.post("/api/v1/chat/stop", json={"chat_id": "gibtsnicht"}, headers=DE)
    assert antwort.status_code == 200
    assert antwort.json()["abgebrochen"] == 0


def test_the_key_of_the_picture_check_is_known_to_the_handler():
    """The tie between the two halves: the KIND the check raises is one the
    handler's table carries. A renamed kind would otherwise fall back to the
    general sentence, and nothing would notice."""
    import pytest
    from pydantic import ValidationError

    from app.api.v1.bild import BildWunsch
    from app.input_errors import SENTENCE_FOR_KIND

    with pytest.raises(ValidationError) as abgelehnt:
        BildWunsch(modell="probe", prompt="x", von=2, nr=3)
    (eintrag,) = abgelehnt.value.errors()
    assert eintrag["type"] in SENTENCE_FOR_KIND


# Every sentence these routes hand out, as the two catalogues carry it: the
# call, the status, and the same sentence in both languages. A wrong language
# argument stays invisible to the English side alone — `t()` falls back to
# English for an unknown language — so both sides are pinned.
SAETZE = [
    (
        "der Skillname",
        "post",
        "/api/v1/skills",
        {"json": {"name": "kein/name", "inhalt": "x"}},
        400,
        "'kein/name' is not a valid skill name",
        "'kein/name' ist kein gültiger Skill-Name",
    ),
    (
        "der leere Inhalt",
        "put",
        "/api/v1/skills/handoff",
        {"json": {"inhalt": "   "}},
        400,
        "The skill's content is empty",
        "Der Skill-Inhalt ist leer",
    ),
    (
        "der leere Inhalt beim Anlegen",
        "post",
        "/api/v1/skills",
        {"json": {"name": "probe", "inhalt": "   "}},
        400,
        "The skill's content is empty",
        "Der Skill-Inhalt ist leer",
    ),
    (
        "die unbekannte Einstellung beim Teilsetzen",
        "patch",
        "/api/v1/settings/global/gibtsnicht",
        {"json": {"wert": {"a": 1}}},
        400,
        "Unknown setting 'gibtsnicht'",
        "Unbekannte Einstellung 'gibtsnicht'",
    ),
    (
        "die unbekannte Skilldatei",
        "get",
        "/api/v1/skills/nichts-davon",
        {},
        404,
        "No skill named 'nichts-davon'",
        "Kein Skill namens 'nichts-davon'",
    ),
    (
        "der unbekannte Skill beim Bearbeiten",
        "put",
        "/api/v1/skills/nichts-davon",
        {"json": {"inhalt": "x"}},
        404,
        "No skill named 'nichts-davon'",
        "Kein Skill namens 'nichts-davon'",
    ),
    (
        "der unbekannte Skill beim Umschalten",
        "patch",
        "/api/v1/skills/nichts-davon",
        {"json": {"auto": True}},
        404,
        "No skill named 'nichts-davon'",
        "Kein Skill namens 'nichts-davon'",
    ),
    (
        "die fehlende eigene Fassung",
        "delete",
        "/api/v1/skills/handoff",
        {},
        404,
        "No user-defined copy of 'handoff'",
        "Keine benutzereigene Fassung von 'handoff'",
    ),
    (
        "die fehlende Berechtigung",
        "delete",
        "/api/v1/permissions/always-allow/gibtsnicht",
        {},
        404,
        "There is no such rule",
        "Diese Regel gibt es nicht",
    ),
    (
        "die unbekannte Einstellung",
        "put",
        "/api/v1/settings/global/gibtsnicht",
        {"json": {"wert": 1}},
        400,
        "Unknown setting 'gibtsnicht'",
        "Unbekannte Einstellung 'gibtsnicht'",
    ),
    (
        "der teilweise Wertesatz",
        "patch",
        "/api/v1/settings/global/parameter",
        {"json": {"wert": 5}},
        400,
        "Only a set of values can be partly updated",
        "Nur ein Wertesatz lässt sich teilweise setzen",
    ),
    (
        "der falsche Bereich",
        "get",
        "/api/v1/settings/schraeg/parameter",
        {},
        400,
        "The scope must be 'global', 'modell:<id>' or 'chat:<id>'",
        "Bereich muss 'global', 'modell:<id>' oder 'chat:<id>' sein",
    ),
    (
        "die leere Schlüsselliste",
        "get",
        "/api/v1/settings/resolved?keys=",
        {},
        400,
        "'keys' must not be empty",
        "keys darf nicht leer sein",
    ),
    (
        "der Abbruch ohne Kennung",
        "post",
        "/api/v1/chat/stop",
        {"json": {}},
        400,
        "generation_id or chat_id is required",
        "generation_id oder chat_id ist erforderlich",
    ),
]


def test_jeder_satz_dieser_routen_kommt_in_beiden_sprachen(client):
    for name, ruf, pfad, wie, status, englisch, deutsch in SAETZE:
        antwort = getattr(client, ruf)(pfad, headers=EN, **wie)
        assert antwort.status_code == status, name
        assert antwort.json()["detail"] == englisch, name
        # The silence probe: with the German header the same sentence stands
        # in German — this is what catches a language argument passed wrong,
        # because `t()` would quietly answer in English for it.
        antwort = getattr(client, ruf)(pfad, headers=DE, **wie)
        assert antwort.json()["detail"] == deutsch, name


# The body checks are answered by FastAPI itself, in English. The handler in
# app/input_errors.py builds those sentences from the catalogue instead — the
# window above the skill editor shows exactly the `msg` of each entry
# (frontend/src/lib/api.js). The entries below name the catalogue key and the
# values the check handed over, not the wording: the wording is a working
# title until the order giver sets it. Where a sentence carries a number, the
# number is checked on its own too — otherwise a sentence that lost its
# placeholder would pass, because both sides of the comparison lost it.
TOO_LONG = {"name": "probe", "inhalt": "x" * 100_001}
VALID = {"name": "probe", "inhalt": "---\ndescription: Probe\n---\n\nKurz.\n"}


def _send_body(client, wie, sprache):
    return client.post("/api/v1/skills", headers={"X-Ui-Language": sprache}, **wie)


def test_a_too_long_body_is_refused_in_german(client):
    response = _send_body(client, {"json": TOO_LONG}, "de")
    assert response.status_code == 422
    (entry,) = response.json()["detail"]
    assert entry["msg"] == t("fehler.eingabe_zu_lang", "de", max_length=100_000)
    # The number the check itself used has to stand in the sentence — a
    # sentence without it names no limit the person could stay under.
    assert "100000" in entry["msg"]


def test_a_too_long_body_is_refused_in_english(client):
    response = _send_body(client, {"json": TOO_LONG}, "en")
    assert response.status_code == 422
    (entry,) = response.json()["detail"]
    assert entry["msg"] == t("fehler.eingabe_zu_lang", "en", max_length=100_000)
    assert entry["msg"] != t("fehler.eingabe_zu_lang", "de", max_length=100_000)


def test_the_shape_of_the_422_answer_stays_as_fastapi_writes_it(client):
    """Place, kind and the check's own numbers stand as they were — the
    window reads the list entry-wise, and a client that looks at the check
    itself keeps finding it. The refused value is the one part that does
    not travel (see `test_the_refused_body_does_not_come_back_with_the_answer`)."""
    response = _send_body(client, {"json": TOO_LONG}, "de")
    (entry,) = response.json()["detail"]
    assert entry["type"] == "string_too_long"
    assert entry["loc"] == ["body", "inhalt"]
    assert entry["ctx"] == {"max_length": 100_000}


def test_a_missing_field_is_named_in_both_languages(client):
    for sprache in ("de", "en"):
        response = _send_body(client, {"json": {}}, sprache)
        assert response.status_code == 422
        assert [entry["msg"] for entry in response.json()["detail"]] == [
            t("fehler.eingabe_feld_fehlt", sprache, field="name"),
            t("fehler.eingabe_feld_fehlt", sprache, field="inhalt"),
        ]
        # A check that reports a missing field refuses the WHOLE body, so
        # `input` would hand the neighbouring values back with it — the same
        # door as the long text above, and no test held this side of it.
        assert all("input" not in entry for entry in response.json()["detail"])


def test_a_kind_without_its_own_sentence_names_the_field(client):
    """A check the catalogue has no sentence for falls to the general one —
    and that one names the field, because that is all it can say."""
    response = _send_body(client, {"json": {"name": "probe", "inhalt": 5}}, "de")
    assert response.status_code == 422
    (entry,) = response.json()["detail"]
    assert entry["msg"] == t("fehler.eingabe_ungueltig", "de", field="inhalt")
    assert entry["type"] == "string_type"


def test_a_body_that_does_not_parse_is_reported_as_the_body(client):
    """A JSON error carries the parser's position in `loc` — a number, not a
    field. The sentence names the body: "The value for "13" is not valid"
    would name a place where nothing stands."""
    response = client.post(
        "/api/v1/skills",
        content='{"name": "probe",}',
        headers={"Content-Type": "application/json", **DE},
    )
    assert response.status_code == 422
    (entry,) = response.json()["detail"]
    assert entry["type"] == "json_invalid"
    assert entry["loc"][0] == "body"
    assert entry["msg"] == t("fehler.eingabe_ungueltig", "de", field="body")


def test_a_too_short_body_names_its_minimum(client):
    """The other bound: an API key under eight characters (app/api/v1/
    anbieter.py) — the same sentence shape, with the other number."""
    response = client.post(
        "/api/v1/providers",
        json={"art": "anthropic", "schluessel": "kurz"},
        headers=DE,
    )
    assert response.status_code == 422
    (entry,) = response.json()["detail"]
    assert entry["msg"] == t("fehler.eingabe_zu_kurz", "de", min_length=8)
    assert "8" in entry["msg"]


def test_a_valid_body_passes_unchanged(client):
    """The silence probe for the whole handler: a body that passes its
    checks never reaches it."""
    response = _send_body(client, {"json": VALID}, "de")
    assert response.status_code == 201
    assert response.json()["name"] == "probe"


def test_a_picture_beyond_the_run_names_the_catalogue_sentence(client):
    """A Image number is outside the range of this run.'s last one is refused by the model's
    own check (`BildWunsch._lauf_stimmig`, app/api/v1/bild.py). What that
    check carries is a catalogue KEY — no sentence of its own, and above all
    no key for the window to show: the sentence is taken under it, in the
    language of the request, like every other check of this door."""
    for sprache in ("de", "en"):
        antwort = client.post(
            "/api/v1/bild",
            json={"modell": "gibtsnicht", "prompt": "x", "von": 2, "nr": 3},
            headers={"X-Ui-Language": sprache},
        )
        assert antwort.status_code == 422
        (eintrag,) = antwort.json()["detail"]
        assert eintrag["msg"] == t("bild.lauf_nr_zu_gross", sprache)
        assert "bild.lauf_nr_zu_gross" not in eintrag["msg"]


def test_a_picture_inside_the_run_passes_this_check(client):
    """The silence probe: the same request with a number inside the run is
    not answered by this sentence. It walks on and ends at the next refusal
    of that route — no image program (503), or a model name that is not there
    (404) where a built sd-cli stands on the PATH — so the test pins the
    sentence that must NOT stand, and that the answer is one of those two."""
    antwort = client.post(
        "/api/v1/bild",
        json={"modell": "gibtsnicht", "prompt": "x", "von": 3, "nr": 2},
        headers=DE,
    )
    assert antwort.status_code in (404, 503)
    assert t("bild.lauf_nr_zu_gross", "de") not in str(antwort.json())


def test_the_checks_own_context_cannot_rewrite_the_sentence():
    """`ctx` belongs to the check, not to the sentence. A key of it named like
    a placeholder would fake the field name, and one named like a parameter of
    ``t`` broke the call outright — a 500 instead of a 422. Driven on the
    function itself: pydantic hands a `ctx` of its own only for some checks,
    so no route reaches these two shapes today."""
    from app.input_errors import _sentence

    assert _sentence(
        {"type": "missing", "loc": ("body", "x"), "ctx": {"field": "GEFAELSCHT"}},
        "de",
    ) == t("fehler.eingabe_feld_fehlt", "de", field="x")
    assert _sentence(
        {"type": "missing", "loc": ("body", "x"), "ctx": {"sprache": "de"}}, "de"
    ) == t("fehler.eingabe_feld_fehlt", "de", field="x")


def test_the_refused_body_does_not_come_back_with_the_answer(client):
    """The answer names what was wrong; it does not hand the body back.

    FastAPI returns the refused value whole, and on a long one the answer
    outgrows the request: a skill of 100,001 characters was answered by
    100,159, the whole text in it (app/input_errors.py).
    """
    antwort = _send_body(client, {"json": TOO_LONG}, "de")
    assert antwort.status_code == 422
    # Two bounds, and both are needed: the absolute one says an answer built
    # from one sentence is short — whatever the sentences grow to, a leak of
    # a few thousand characters fails it. The relative one says the answer
    # stays below the text it refuses, which is the point of the change.
    assert len(antwort.text) < 1_000
    assert len(antwort.text) < len(TOO_LONG["inhalt"])
    assert "x" * 100 not in antwort.text
    (entry,) = antwort.json()["detail"]
    assert "input" not in entry


def test_a_missing_interface_answers_in_the_language_of_the_window(client, monkeypatch, tmp_path):
    """`GET /app/` without a build says so in the language of the interface.

    The Electron shell loads exactly this route into its window
    (fenster-electron/main.js), so a fixed German sentence reaches an English
    window — these were the last two of this route. Driven with an empty
    static folder: the route's own file is what is missing here, not the
    language.

    Only the `auto` case is measured: with no language stored (which is what
    this fixture holds) the header decides. A stored choice wins over the
    header by design (app/sprachwahl.page_language), so a stored `de` would
    answer German here.
    """
    from app import main

    monkeypatch.setattr(main, "STATIC_VERZEICHNIS", tmp_path)
    for sprache in ("de", "en"):
        antwort = client.get("/app/", headers={"X-Ui-Language": sprache})
        assert antwort.status_code == 404
        assert antwort.json()["detail"] == t("fehler.oberflaeche_fehlt", sprache)


def test_a_missing_manifest_answers_in_the_language_of_the_window(client, monkeypatch, tmp_path):
    """The fixed address the page asks for — its answer too comes from the
    catalogue in the language of the request.

    The shell itself never reads the manifest; the page names it
    (`frontend/index.html`, `<link rel="manifest">`).
    """
    from app import main

    monkeypatch.setattr(main, "STATIC_VERZEICHNIS", tmp_path)
    for sprache in ("de", "en"):
        antwort = client.get("/manifest.webmanifest", headers={"X-Ui-Language": sprache})
        assert antwort.status_code == 404
        assert antwort.json()["detail"] == t("fehler.manifest_fehlt", sprache)


def test_the_page_carries_the_language_it_is_served_in(client):
    """The document names its language before a line of the program runs.

    A reading tool or a translator trusts `<html lang>`, and the catalogue
    only arrives with the first request
    (frontend/src/lib/texte.svelte.js) — a page that failed to load its
    texts would stand there claiming to be German. Only the English half is
    a probe of the replacing: the built page carries German as its own
    default, so the German half would hold without the route as well.
    """
    for sprache in ("de", "en"):
        antwort = client.get("/app/", headers={"X-Ui-Language": sprache})
        assert antwort.status_code == 200
        assert f'<html lang="{sprache}">' in antwort.text
