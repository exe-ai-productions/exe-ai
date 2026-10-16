"""Three small holes around a chosen "none" and the remembered model choice.

  * **``||`` on a field where ``""`` is an answer.** ``Lauf.vision`` is the
    parameter a run was handed, not the projector that got resolved. ``null``
    means "the run says nothing about it"; ``""`` means "started mute, no
    --mmproj on the command line". Both server pages folded the second into
    the first, so a window that had not written the choice itself went on
    naming a projector that was not running — and, after the stop, took its
    fields back from a copy of the setting as old as the moment that page
    opened.

  * **A model file carries ``name``, and the start route reads ``modell``.**
    A reader that asked for ``datei`` got nothing every single time; the one
    rule that picks the remembered file reads ``name``, and the route turns
    the old field away.

  * **Two comments said what the code stopped doing in 7c49647:** that the
    start button writes the module rows.

  * **The slot key holds ONE module pair for every file.** A draft picked by
    hand for one model stood in the row for the next one and went out on its
    command line — a 12B draft against a 31B model is the pairing the
    candidate rule exists to prevent.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.api.v1.runner import Modelldatei, Start

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
MODELLSERVER = FRONTEND / "src" / "teile" / "Modellserver.svelte"
AGENTSERVER = FRONTEND / "src" / "teile" / "Agentserver.svelte"
RUNNERMODELL = FRONTEND / "src" / "lib" / "runnermodell.svelte.js"


def ohne_kommentare(quelle: str) -> str:
    """The source without its prose.

    Every guard below asks what the code DOES, and these files carry more
    comment than code on purpose — a guard that read the prose too would go
    red on the sentence explaining the very rule it checks.
    """
    quelle = re.sub(r"/\*.*?\*/", "", quelle, flags=re.S)
    return re.sub(r"^\s*//.*$", "", quelle, flags=re.M)


def rumpf(quelle: str, kopf: str) -> str:
    """The body of one function, brace-matched."""
    stelle = quelle.index(kopf) + len(kopf)
    anfang = quelle.index("{", stelle)
    tiefe, i = 0, anfang
    while i < len(quelle):
        if quelle[i] == "{":
            tiefe += 1
        elif quelle[i] == "}":
            tiefe -= 1
            if tiefe == 0:
                return quelle[anfang + 1 : i]
        i += 1
    raise AssertionError(f"no body for {kopf!r}")


# --- `""` is an answer, and `||` throws it away --------------------


@pytest.mark.parametrize("datei", [MODELLSERVER, AGENTSERVER])
def test_der_projektor_des_laufs_wird_mit_zwei_fragezeichen_uebernommen(datei: Path):
    """``vision = auskunft.vision ?? vision`` — never ``||``.

    Measured in two real windows: A picks "none" on a standing slot and
    starts, B has the page open and had not written the choice itself. With
    ``||`` B went on showing the old projector while the command line ran
    without --mmproj; with ``??`` it says "none", which is what is running.
    """
    quelle = ohne_kommentare(datei.read_text(encoding="utf-8"))
    treffer = re.findall(r"vision\s*=\s*auskunft[?.]*\.vision\s*(\?\?|\|\|)", quelle)
    assert treffer, f"{datei.name}: the line for auskunft.vision has disappeared"
    assert "||" not in treffer, (
        f"{datei.name}: auskunft.vision is taken over with || — that throws away the "
        'explicit choice "", which means exactly: started without a projector'
    )


@pytest.mark.parametrize("datei", [MODELLSERVER, AGENTSERVER])
def test_nach_dem_lauf_wird_die_wahl_frisch_gelesen(datei: Path):
    """The stored choice, not this window's copy of it.

    ``standLaden`` reads once when a page opens. Taking the fields back from
    that copy when a run ends is how a projector another window had switched
    off walked straight back into the row after the stop.
    """
    quelle = ohne_kommentare(datei.read_text(encoding="utf-8"))
    koerper = rumpf(quelle, "async function laden()")
    stelle = koerper.index("else if (liefVorher)")
    zweig = koerper[stelle : koerper.index("}", stelle)]
    assert "standLaden(" in zweig, (
        f"{datei.name}: the branch for the end of a run does not read the choice "
        "again — it takes the copy read when the page was opened"
    )
    # The read has the LAST word. The branch also puts the fields on this
    # window's copy BEFORE reading — that is what makes the wait harmless
    # without a lock — so "there is a hand-back after the read" is the half of
    # it this guard is about (test_stop_window_and_remembered_choice.py has
    # the other).
    assert "werteUebernehmen()" in zweig[zweig.index("standLaden(") :], (
        f"{datei.name}: nothing is taken over after the fresh read — then "
        "the read was for nothing and the copy stays in the fields"
    )


def test_der_speicher_kann_erneut_gelesen_werden():
    """``standLaden(erneut)`` — once per page life is right for the mount
    storm and wrong for everything after it."""
    quelle = ohne_kommentare(RUNNERMODELL.read_text(encoding="utf-8"))
    assert re.search(r"export function standLaden\(\s*erneut", quelle), (
        "runnermodell.svelte.js: standLaden no longer knows a fresh read — "
        "then every page falls back to its copy from opening time"
    )
    assert re.search(r"if \(runnermodell\.geladen && !erneut\)", quelle), (
        "runnermodell.svelte.js: the lock ignores the fresh read"
    )


# --- The field a model file carries --------------------------------


def test_the_page_sends_the_field_the_start_route_reads():
    """``POST /runner/start`` carries the file and nothing else.

    Tied to the schema rather than to a string: the day the route renames its
    field, this goes red instead of the start button silently going quiet.
    """
    felder = set(Start.model_fields)
    assert felder == {"modell"}, f"the route reads {felder} today"
    seite = ohne_kommentare(MODELLSERVER.read_text(encoding="utf-8"))
    assert "runnerStarten({ modell })" in seite, (
        f"Modellserver.svelte: the start does not send the field the route reads ({felder})"
    )


def test_the_remembered_choice_is_read_by_the_field_a_model_file_carries():
    """``Auskunft.modelle`` are ``Modelldatei``: they carry ``name``.

    Which entry of that list is taken, and by which field, is decided in one
    place (lib/runnermodell.svelte.js ``gemerkteDatei``) — the rule the
    server page and the local area ask. It must read ``name``, the only
    field a model file has.
    """
    felder = set(Modelldatei.model_fields)
    assert "name" in felder and "datei" not in felder, f"today: {felder}"
    regel = rumpf(
        ohne_kommentare(RUNNERMODELL.read_text(encoding="utf-8")),
        "export function gemerkteDatei(dateien)",
    )
    assert ".name" in regel and ".datei" not in regel, (
        "runnermodell.svelte.js: `gemerkteDatei` reads a field other than "
        "`name` — the only one a model file carries"
    )


def test_die_startroute_weist_das_alte_feld_ab(client):
    """Not a source guard: the two field names really are two field names."""
    assert client.post("/api/v1/runner/start", json={"datei": "m.gguf"}).status_code == 422


# --- Two comments that said the opposite of the code ---------------


def test_kein_kommentar_behauptet_noch_der_startknopf_schreibe_die_module():
    """7c49647 took that out of both start buttons. A comment that lies costs
    the next reader an hour."""
    # Whitespace-blind: these sentences are wrapped, and a claim does not
    # stop being a claim because a line break falls in the middle of it.
    def fliessend(datei: Path) -> str:
        return " ".join(datei.read_text(encoding="utf-8").split())

    modellserver = fliessend(MODELLSERVER)
    runnermodell = fliessend(RUNNERMODELL)
    assert "the start button writes what stands in them" not in modellserver
    assert "and again at start" not in runnermodell
    assert "and the start button writes the module" not in runnermodell
    # And the code the sentences described really is gone.
    starten = rumpf(
        ohne_kommentare(MODELLSERVER.read_text(encoding="utf-8")),
        "async function starten()",
    )
    assert "modulSetzen" not in starten, (
        "Modellserver.svelte: the start button writes the module lines again — "
        "then the comments are not the problem"
    )


# --- One module pair per file --------------------------------------


def test_ein_modellwechsel_gibt_die_gemerkte_modulwahl_zurueck():
    """The slot key holds a pair per file, so a switch hands back nothing.

    It used to hold ONE pair, and a draft picked by hand for one model stood
    in the row for the next one — measured: after switching to
    ``gross-12B.gguf`` the start carried ``--model-draft …/mtp-gemma.gguf``.
    The pair is remembered per file now: the switch changes nothing in the
    row, and the rows on the page are read again for the file that was
    chosen.
    """
    quelle = ohne_kommentare(AGENTSERVER.read_text(encoding="utf-8"))
    koerper = rumpf(quelle, "async function modellGewaehlt(wahl)")
    assert "werteSetzen({ drafter: null, vision: null })" not in koerper, (
        "Agentserver.svelte: the module choice is handed back at a switch — "
        "then the pair of the file before is lost for the file itself"
    )
    waehlen = koerper.index("agentenmodellWaehlen(wahl)")
    lesen = koerper.index("moduleUebernehmen()")
    assert waehlen < lesen, (
        "Agentserver.svelte: the rows are read before the file is chosen — "
        "they would show the pair of the file before"
    )
