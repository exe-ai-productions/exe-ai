"""What the program writes reaches the model in English — also at language de.

The comment guard (``tests/test_hausregeln.py``) checks the SOURCE. This one
checks what really goes out: a tool result, a refusal, a report line, an
error. It is a test and nothing else — the program gains no check of its own,
because these texts are written once per request and a check in the hot path
would be paid by every answer.

Two readers, two languages, one source: wherever a sentence is the program's
own, its German and English copies come from the same catalogue entry. What
this file holds on to is the English half of each such pair, from the side
the model reads it.

What it does NOT look at: the user's own words, files, command output, web
pages and the model's answers. Those are not the program's text — a German
file that is read in is not a mistake (the silence probes below hold that
boundary open).
"""

from __future__ import annotations

import asyncio
import re

import pytest

from tests.test_hausregeln import DEUTSCHE_WOERTER

# The shared list holds the little words every German sentence needs. These
# are the words a Program text uses when it names a THING — the ones the five
# faults below were made of. The list grows with every case found; a German
# word that is nowhere on it is a word this guard cannot see.
WEITERE_DEUTSCHE_WOERTER = {
    "abgeschnitten", "anzeige", "ausgabe", "befehl", "benutzer", "datei",
    "fehler", "gerät", "herunterfahren", "kontext", "netz", "ordner",
    "rundengrenze", "schreiben", "systemdienste", "verboten", "weitere",
    "zeichen", "zeitgrenze", "zurueck", "zurück",
}

ALLE_DEUTSCHEN_WOERTER = DEUTSCHE_WOERTER | WEITERE_DEUTSCHE_WOERTER


def _deutsch(text: str) -> list[str]:
    """The German-only words in a text the program wrote."""
    if not isinstance(text, str):
        return []
    woerter = {w.lower() for w in re.findall(r"[A-Za-zÄÖÜäöüß]+", text)}
    return sorted(woerter & ALLE_DEUTSCHEN_WOERTER)


def _pruefen(wo: str, text: str) -> None:
    gefunden = _deutsch(text)
    assert not gefunden, f"{wo}: deutsche Woerter {gefunden} in {text[:200]!r}"


# --- run_command: the refusal's reason and the cut-off note ------------------


def test_run_command_refusal_is_english(tmp_path):
    """The blocked-pattern names sit inside the English refusal — a German
    name makes the whole sentence half German for the model that has to
    understand why it was refused."""
    from app.tools import shell
    from app.tools.registry import WerkzeugRegistry, WerkzeugVerboten

    registry = WerkzeugRegistry([], shell_an=True)
    for befehl in ("sudo ls", "shutdown now", "dd if=/dev/zero of=/dev/disk0"):
        with pytest.raises(WerkzeugVerboten) as fehler:
            asyncio.run(registry.ausfuehren(
                shell.WERKZEUG_NAME, {"command": befehl}, ordner=[str(tmp_path)]
            ))
        _pruefen(f"run_command abgewiesen ({befehl})", str(fehler.value))


def test_run_command_truncation_note_is_english():
    """The note appended to a cut-off result is text the program wrote.

    Read through the function that builds the tool's answer
    (``_antwort_bauen``), not through the cutting helper alone: only there
    is it the text a model actually gets.
    """
    from app.api.v1.generierung import WERKZEUGERGEBNIS_GRENZE
    from app.tools import shell

    lang = "x" * (shell.MAX_AUSGABE_ZEICHEN + 500)
    text = shell._antwort_bauen([lang], [], 0)
    _pruefen("run_command gekuerzt", text)
    # The note has to SURVIVE the ceiling a tool result is cut to on its way
    # out, and that ceiling is this same figure — added on top of it, the
    # note was cut off every single time and nobody ever read it.
    assert "additional characters omitted" in text[:WERKZEUGERGEBNIS_GRENZE]
    assert len(text) <= shell.MAX_AUSGABE_ZEICHEN
    # And its figure is what the reader LOST, not what the note cost: the
    # count once ran against the ceiling before the note took its room, so
    # it understated the loss by the length of the note itself.
    notiz = re.search(r"\n… \[(\d+) additional characters omitted\]$", text)
    assert notiz, text[-80:]
    behalten = len(text) - len(notiz.group(0))
    assert int(notiz.group(1)) == shell.MAX_AUSGABE_ZEICHEN + 500 - behalten


def test_the_note_survives_two_streams_that_each_just_fit():
    """stdout and stderr are cut together, not one after the other.

    Two parts that each just fit under the ceiling are a full answer over it
    once they are joined — and the caller cuts again at exactly that figure,
    so the note would be torn in half where it stands and the model would
    read a sentence with no end.
    """
    from app.api.v1.generierung import WERKZEUGERGEBNIS_GRENZE
    from app.tools import shell

    rand = "y" * (shell.MAX_AUSGABE_ZEICHEN - 1)
    text = shell._antwort_bauen([rand], [rand], 1)
    assert len(text) <= shell.MAX_AUSGABE_ZEICHEN
    assert len(text) <= WERKZEUGERGEBNIS_GRENZE
    assert "additional characters omitted]" in text
    # The exit code is not part of the cut: it is carried behind it.
    assert text.endswith("\n[exit code 1]")


def test_the_exit_code_survives_a_long_output_alone():
    """A failing command whose output is cut still reports its exit code."""
    from app.tools import shell

    text = shell._antwort_bauen([], ["x" * (shell.MAX_AUSGABE_ZEICHEN + 900)], 2)
    assert text.endswith("[exit code 2]")
    assert len(text) <= shell.MAX_AUSGABE_ZEICHEN
    # And a command with no output at all stays as it was.
    assert shell._antwort_bauen([], [], 0) == "(completed without output)"
    assert shell._antwort_bauen([], [], 3) == "[exit code 3]"


# --- skill_save's refusals ---------------------------------------------------


def test_skill_save_refusal_is_english(tmp_path):
    """Every refusal of skill_save is the tool's result — the model is the
    one that has to correct itself from it."""
    from app.skills import SkillKaputt, skill_aus_text

    faelle = [
        # English names on purpose: the name is echoed in the refusal, and a
        # German name of the test's own making is not the program's text.
        ("Not_Allowed", "---\ndescription: d\n---\n\nDo it.\n"),
        ("no-header", "plain text"),
    ]
    for name, text in faelle:
        with pytest.raises(SkillKaputt) as fehler:
            skill_aus_text(name, text, ordner=tmp_path / name, eigen=True)
        _pruefen(f"skill_save ({name})", str(fehler.value))


def test_a_broken_skill_reads_german_in_the_window(tmp_path):
    """The other half of the pair: the mask asks for the language of its
    page, and gets a German sentence for the same failure."""
    from app.skills import SkillKaputt, skill_aus_text

    with pytest.raises(SkillKaputt) as fehler:
        skill_aus_text("no-header", "plain text", ordner=tmp_path / "x", eigen=True)
    de = fehler.value.text("de")
    assert de != fehler.value.text("en")
    assert "fehlt" in de or "Kopfteil" in de


def test_a_rebuilt_skill_fault_never_prints_a_key():
    """``type(fehler)(*fehler.args)`` hands the finished sentence in where a
    kind belongs. It must not become a catalogue key — and it must not
    escape the catch either: everything around this class catches
    ``SkillKaputt``, so a different error type would fly past every one."""
    from app.skills import SkillKaputt

    wieder = type(SkillKaputt("kopfteil", anzeige="x/SKILL.md"))(
        "'x/SKILL.md': the header is missing"
    )
    assert isinstance(wieder, SkillKaputt)
    for sprache in ("de", "en"):
        satz = wieder.text(sprache)
        assert "skills.fehler" not in satz, satz
        assert "SKILL.md" in satz, satz
    _pruefen("SkillKaputt (rebuilt, model's copy)", str(wieder))


def test_a_broken_skill_survives_being_pickled(tmp_path):
    """It travels through queues and copies. Carrying the sentence instead of
    its key, a copy comes back as a catalogue key with a warning."""
    import pickle

    from app.skills import SkillKaputt, skill_aus_text

    with pytest.raises(SkillKaputt) as fehler:
        skill_aus_text("no-header", "plain text", ordner=tmp_path / "x", eigen=True)
    kopie = pickle.loads(pickle.dumps(fehler.value))
    assert kopie.key == fehler.value.key
    assert str(kopie) == str(fehler.value)
    assert "skills.fehler" not in str(kopie)


# --- The line an agent report carries ----------------------------------------


class _Auftrag:
    """Just enough of a job for the report: the function reads attributes."""

    agent = "recherche"
    id = "abc123"
    zustand = "gescheitert"
    auftrag = "List the files."
    ergebnis = "done"

    def __init__(self, grund: str) -> None:
        self.ende_grund = grund


def test_the_agent_report_speaks_english():
    """Every ending this program stores becomes a sentence; the short
    identifier is for the job list and the log, not for a model.

    The list is every identifier the run can actually store — the endings
    named in app/api/v1/auftraege.py, app/auftragsende.py and the cron path.
    An ending with no catalogue entry is the failure this guards against.
    """
    from app import agent_report

    gruende = [
        "benutzer_abbruch", "eltern_abbruch", "chat_deleted", "dienst_neustart",
        "modell_nicht_gefunden", "antwortlaenge_zu_gross", "anbieter_ausfall",
        "anbietergrenze", "rundengrenze", "zeitgrenze", "kontext_voll",
        "kein_fortschritt", "wiederholte_ablehnung", "skript_fehler",
        "ablage_gescheitert", "frage_beantwortet", "denken_aufgebraucht",
        "denken_aufgebraucht_eigene_grenze", "fehler_allgemein",
    ]
    for grund in gruende:
        bericht = agent_report.report_text(_Auftrag(grund))
        _pruefen(f"Agentenbericht ({grund})", bericht)
        # And it says something: an unknown ending would fall back to a
        # sentence that names nothing.
        assert "without a stated reason" not in bericht, grund
        assert f"jobs.grund.{grund}" not in bericht


def test_an_unknown_ending_is_not_a_key():
    """An ending this program does not know gets a sentence of its own — a
    key handed to a model reads like a fact and is none."""
    from app import agent_report

    bericht = agent_report.report_text(_Auftrag("ein_grund_den_es_nicht_gibt"))
    _pruefen("Agentenbericht (unbekannt)", bericht)
    assert "jobs.grund.ein_grund_den_es_nicht_gibt" not in bericht
    assert "without a stated reason" in bericht


def test_a_provider_error_keeps_its_own_words():
    """What the provider itself said rides along behind ``fehler:`` — a
    rewritten error hides what really happened. It is foreign text, and the
    guard has no business crying about it."""
    from app import agent_report

    bericht = agent_report.report_text(_Auftrag("fehler: the model said no"))
    assert "the model said no" in bericht
    _pruefen("Agentenbericht (Anbieterfehler)", bericht)


# --- A provider's error text -------------------------------------------------


@pytest.mark.asyncio
async def test_the_providers_error_text_is_english():
    """The frame around a refusal or a dead server is the program's text —
    the provider's own words inside it are not. The model is one reader of
    this sentence and gets English."""
    from app.providers import ProviderFehler

    from tests.test_openai_provider import _einsammeln, _provider

    with pytest.raises(ProviderFehler) as fehler:
        await _einsammeln(_provider("http://127.0.0.1:9/v1"))
    _pruefen("Anbieter nicht erreichbar", str(fehler.value))


@pytest.mark.asyncio
async def test_the_window_reads_the_same_error_in_its_own_language():
    """The other reader of that sentence is the person in front of the chat
    bubble — the very same error, from the very same catalogue entry, in the
    language their page shows. Measured on one error, both copies."""
    from app.providers import ProviderFehler

    from tests.test_openai_provider import _einsammeln, _provider

    with pytest.raises(ProviderFehler) as fehler:
        await _einsammeln(_provider("http://127.0.0.1:9/v1"))
    de = fehler.value.text("de")
    assert de != str(fehler.value)
    assert "nicht erreichbar" in de


# --- A refusal of the job route ----------------------------------------------


def test_a_refusal_carries_both_copies():
    """``start_job`` is called from a chat (a model reads the result) and
    from the window (a person reads it). The refusal carries the catalogue
    key, so both copies come from one sentence instead of two."""
    from app.api.v1.auftraege import Refusal

    fehler = Refusal(404, "fehler.modell_nicht_erreichbar", "de", name="homelab")
    assert "homelab" in fehler.detail
    assert fehler.detail != fehler.model
    _pruefen("Refusal (model's copy)", fehler.model)
    # And the model's copy carries the name it was raised with — the German
    # one carries it too, from the same values.
    assert "homelab" in fehler.model


def test_a_start_job_refusal_reaches_the_model_english():
    """The frame is written in one place, and the copy behind it is the
    model's — both start_job callers (the chat and a running job) take it
    from the refusal rather than from the sentence the window shows."""
    from app.api.v1.auftraege import Refusal, job_could_not_start

    fehler = Refusal(400, "fehler.kein_modell_verfuegbar", "de")
    satz = job_could_not_start(fehler.model)
    _pruefen("start_job abgewiesen (Modellkopie)", satz)


# --- Silence probes: text that is not the program's --------------------------


def test_a_german_file_in_a_tool_result_is_no_finding(tmp_path):
    """A file the user wrote is read back as it is, through the real tool.
    The guard must not cry at that — a guard that cries at correct code is a
    guard nobody believes."""
    from app.tools import datei_lesen

    datei = tmp_path / "notiz.md"
    datei.write_text("Der Bericht ist fertig und wird nicht mehr geändert.\n")
    gelesen = asyncio.run(
        datei_lesen.ausfuehren({"path": str(datei)}, [str(tmp_path)])
    )
    assert _deutsch(gelesen), "the case must contain German words"


def test_a_german_user_message_is_no_finding():
    """The user's own words travel to the model unchanged — in whatever
    language they were typed."""
    assert _deutsch("Bitte schreib mir eine Zusammenfassung für den Bericht")
