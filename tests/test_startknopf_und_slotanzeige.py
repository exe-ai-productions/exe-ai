"""What the start button still wrote by hand, and what the slot's rows still
showed after a run — the three holes a review found after ``ca8ad11``.

``ca8ad11`` built ``lib/nurgeaendert.js`` so a page sends only what the hand in
it actually moved: a second window's number is not overwritten by this
window's stale copy, and a pre-filled default is not stored as a choice. The
watchers on both pages went through it. Three ways past it were left:

  * **The start button on the model server did not.** It handed the store
    ``{modell, kontext, schichten, port}`` by hand — so pressing start undid
    both rules at once — and, worse, it wrote the two module rows as a
    deliberate answer. Where the row showed "none" about a projector the name
    heuristic had attached, the first press of start DELETED that projector.
    The guard test of ``ca8ad11`` searched for one exact layout and walked
    past this call because ``modell`` happened to stand first.

  * **The slot's page never took its rows back after a run.** ``Lauf.vision``
    is the parameter that was handed in, not the projector that was resolved,
    so a run started on "nobody said" reports ``None`` while ``--mmproj``
    stands on its command line. The page folded that to ``""`` and left it
    there for good after the stop — and a row already reading "none" cannot be
    set to "none", so switching the projector off was unreachable.

  * **The candidate rule blanked the field.** A remembered or declared module
    the rule would not propose was taken out of the row — while the process,
    which knows nothing of that rule, went on starting with it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import runnermodellwahl
from app.modellrunner import Modellrunner

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
MODELLSERVER = FRONTEND / "src" / "teile" / "Modellserver.svelte"
AGENTSERVER = FRONTEND / "src" / "teile" / "Agentserver.svelte"


def ohne_kommentare(quelle: str) -> str:
    """The source without its prose.

    Every guard below asks what the code DOES, and these two files carry more
    comment than code on purpose. A guard that reads the prose too would go
    red on a sentence explaining the very rule it checks.
    """
    quelle = re.sub(r"/\*.*?\*/", "", quelle, flags=re.S)
    return re.sub(r"^\s*//.*$", "", quelle, flags=re.M)


def rumpf(quelle: str, kopf: str) -> str:
    """The body of one function, brace-matched.

    Matched on braces rather than on indentation so the guard does not depend
    on how the file happens to be laid out — which is exactly what let the
    finding through the last time.
    """
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


def klammern_weg(quelle: str, aufruf: str) -> str:
    """The source with every ``aufruf(…)`` cut out, brackets matched."""
    while aufruf in quelle:
        anfang = quelle.index(aufruf)
        i, tiefe = anfang + len(aufruf), 1
        while i < len(quelle) and tiefe:
            if quelle[i] in "([{":
                tiefe += 1
            elif quelle[i] in ")]}":
                tiefe -= 1
            i += 1
        quelle = quelle[:anfang] + quelle[i:]
    return quelle


# --- The start button goes through the filter too ------------------


@pytest.mark.parametrize("datei", [MODELLSERVER, AGENTSERVER], ids=lambda p: p.name)
def test_der_startknopf_geht_durch_denselben_filter(datei: Path):
    """Both start buttons ask the filter, neither writes the numbers by hand.

    The watcher and the button write the same three numbers to the same row.
    A filter on only one of them is not a filter: the button is pressed with
    the whole form standing in the window, including the two values this
    window read when it opened and nobody has touched since.
    """
    quelle = ohne_kommentare(datei.read_text(encoding="utf-8"))
    koerper = rumpf(quelle, "async function starten()")
    assert "nurGeaendert(" in koerper, datei.name
    # Named as an argument to the filter is what the filter is for; named
    # anywhere ELSE in the body is a value going out beside it.
    ausser_filter = klammern_weg(koerper, "nurGeaendert(")
    for feld in ("kontext", "schichten", "port", "fein"):
        assert not re.search(rf"\b{feld}\b", ausser_filter), (datei.name, feld)


@pytest.mark.parametrize("datei", [MODELLSERVER, AGENTSERVER], ids=lambda p: p.name)
def test_der_startknopf_schreibt_keine_modulzeile(datei: Path):
    """The heaviest half of the finding: start must not answer for the rows.

    The two module rows write themselves the moment they are picked. A row
    nobody picked has to stay ``null``, because ``null`` is what lets the
    folder manifest and the name heuristic step in (app/modellrunner.py). The
    model server's button wrote ``{drafter: drafter || '', vision: vision ||
    ''}`` instead — whatever the rows happened to show, as a deliberate
    answer. That froze the manifest's pairing into a choice nobody made, and
    where the row showed "none" about a projector the heuristic had attached
    it switched that projector off for good.
    """
    quelle = ohne_kommentare(datei.read_text(encoding="utf-8"))
    koerper = rumpf(quelle, "async function starten()")
    assert "modulSetzen" not in koerper, datei.name
    for rolle in ("drafter", "vision"):
        assert not re.search(rf"\b{rolle}\b", koerper), (datei.name, rolle)


@pytest.mark.parametrize("datei", [MODELLSERVER, AGENTSERVER], ids=lambda p: p.name)
def test_die_modulzeilen_schreiben_wenn_sie_gewaehlt_werden(datei: Path):
    """And the capability is not lost with it — the rows still store a choice,
    they just store it when it is made."""
    quelle = ohne_kommentare(datei.read_text(encoding="utf-8"))
    assert "function drafterGewaehlt()" in quelle, datei.name
    assert "function visionGewaehlt()" in quelle, datei.name
    assert "drafterGewaehlt" in quelle.split("Serverregler", 1)[-1], datei.name


def test_der_startknopf_friert_die_motorhebel_nicht_mehr_ein():
    """The third key, with a writer of its own.

    ``feineinstellungen`` is written with PUT and had no brake at all: merely
    opening the page stored the shipped levers as a choice, and the start
    button wrote them a second time. Same rule as the numbers, same filter.
    """
    quelle = ohne_kommentare(MODELLSERVER.read_text(encoding="utf-8"))
    # No naked write left anywhere — both writers go through one place.
    assert quelle.count("api.einstellungSetzen('global', FEINEINSTELLUNGEN") == 1
    assert "function feinSchreiben()" in quelle
    # And that one place is asked whether there is anything to say.
    assert "feinNachzutragen()" in rumpf(quelle, "async function starten()")
    assert quelle.count("feinNachzutragen()") >= 3  # definition + two callers


# --- At the command line: what one press of start used to cost ------------


def _ordner_mit_projektor(tmp_path: Path) -> Path:
    """A model with a projector beside it that only the NAME heuristic pairs.

    No manifest entry on purpose: that is the case the page cannot see —
    ``auskunft.zuordnung`` carries the manifest only — so the row reads "none"
    while the command line carries ``--mmproj``.
    """
    ordner = tmp_path / "startmodelle"
    (ordner / "vision").mkdir(parents=True)
    (ordner / "gemma.gguf").write_bytes(b"x" * 5)
    (ordner / "vision" / "gemma-mmproj-Q8_0.gguf").write_bytes(b"x" * 5)
    return ordner


def _zeile(ordner: Path, repositories) -> str:
    start = runnermodellwahl.startwerte(repositories, "gemma.gguf")
    runner = Modellrunner(ordner, programm="llama-server")
    return " ".join(
        runner.befehl(
            "gemma.gguf", start["kontext"], start["schichten"], 8099,
            drafter=start["drafter"], vision=start["vision"], fein=start["fein"],
        )
    )


def test_ein_start_ohne_modulzeile_laesst_den_projektor_dran(
    tmp_path, client: TestClient
):
    """What the fixed button leaves behind, taken to the command line.

    The row was never picked, so nothing about it is stored — and the
    heuristic attaches the projector, exactly as it did before anybody pressed
    anything.
    """
    ordner = _ordner_mit_projektor(tmp_path)
    laden = client.app.state.repositories
    # What the fixed start button stores: the file and the numbers, no module
    # row at all.
    client.put(
        "/api/v1/settings/global/runnermodell",
        json={"wert": {"modell": "gemma.gguf", "kontext": 131072}},
    )
    assert "--mmproj" in _zeile(ordner, laden)


def test_ein_start_der_die_modulzeile_mitschreibt_loescht_den_projektor(
    tmp_path, client: TestClient
):
    """The counter-test, and the reason this is the heaviest of the three.

    ``{"vision": ""}`` is what the old button stored for a row that showed
    "none" — and ``""`` is "chosen: none" all the way to
    app/modellrunner.py. One press of a button that says "start", and the
    projector the user had been running with is gone.
    """
    ordner = _ordner_mit_projektor(tmp_path)
    laden = client.app.state.repositories
    client.put(
        "/api/v1/settings/global/runnermodell",
        json={
            "wert": {
                "modell": "gemma.gguf",
                "kontext": 131072,
                "module": {"gemma.gguf": {"drafter": "", "vision": ""}},
            }
        },
    )
    assert "--mmproj" not in _zeile(ordner, laden)


# --- The slot's rows come back after the run -----------------------


def test_die_slotseite_haelt_den_projektor_waehrend_des_laufs():
    """``Lauf.vision`` is the parameter, not the projector.

    It is handed in and stored as it came (app/modellrunner.py ``Lauf``); the
    manifest and the heuristic are read later, in ``befehl``. A run started on
    "nobody said" therefore reports ``None`` with ``--mmproj`` on its line.
    Folding that to ``""`` put "none" in the row about a projector that was
    running. The speed module does not have the problem — ``Lauf.drafter``
    carries the resolved name — which is why only one of the two rows changes.

    Written as ``||`` here and corrected to ``??`` the same day: ``""`` is a
    third answer, not a missing one. It means "started mute", and ``||`` threw
    it away with the ``null`` — see test_kleinkram_und_cli.py.
    """
    quelle = ohne_kommentare(AGENTSERVER.read_text(encoding="utf-8"))
    koerper = rumpf(quelle, "async function laden()")
    assert "vision = auskunft.vision ?? vision" in koerper
    assert "drafter = auskunft.drafter || ''" in koerper


def test_die_slotseite_nimmt_die_felder_nach_dem_lauf_zurueck():
    """After the stop the run's report is not an answer any more.

    A slot model starts the moment it is picked, so the first thing this page
    ever shows is a run's report; without a hand-back it stood there for good
    after the stop, and the row could not be set to what it already claimed to
    be. The model server's page has had this since the run's numbers were
    found in its fields (``liefVorher`` → ``werteUebernehmen`` /
    ``modulUebernehmen``); this is that same shape, not a second one.
    """
    quelle = ohne_kommentare(AGENTSERVER.read_text(encoding="utf-8"))
    koerper = rumpf(quelle, "async function laden()")
    assert "liefVorher" in koerper
    # The hand-back happens in this branch, and the branch has moved twice.
    # It first pinned "and nothing before it" and went red on the fresh read
    # the branch grew the same day (test_kleinkram_und_cli.py) — a read that
    # is the whole point of "the STORED choice takes the fields back", as
    # opposed to this window's copy of it. It then pinned "the read, then the
    # hand-back", and the read moved again: the fields are put on this
    # window's copy BEFORE the read as well, which is what makes the wait
    # harmless without a lock (test_stoppfenster_und_cli.py).
    #
    # What has been true through all three shapes, and is what this guard is
    # for: the branch hands the fields back, it reads the setting rather than
    # trusting its copy, and the LAST word belongs to the read. Nothing but
    # plain statements between them, so a conditional hand-back cannot pass.
    assert re.search(
        r"\}\s*else if \(liefVorher\)\s*\{[^{}]*werteUebernehmen\(\)[^{}]*"
        r"await standLaden\([^)]*\)\s*werteUebernehmen\(\)",
        koerper,
    )
    stelle = koerper.index("else if (liefVorher)")
    stelle = koerper.index("{", stelle) + 1
    vorlauf = koerper[stelle : koerper.index("werteUebernehmen()", stelle)]
    assert not re.search(r"\b(if|return|for|while|switch)\b", vorlauf), (
        "the branch fetches the fields back only under one condition"
    )
    assert "liefVorher = Boolean(auskunft.laeuft)" in koerper
    # And the hand-back carries the module rows with it.
    assert "moduleUebernehmen()" in rumpf(quelle, "function werteUebernehmen()")


# --- The candidate rule narrows the suggestion, not the truth ------


@pytest.mark.parametrize("datei", [MODELLSERVER, AGENTSERVER], ids=lambda p: p.name)
def test_ein_modul_das_der_filter_nicht_vorschlaegt_wird_trotzdem_gezeigt(datei: Path):
    """Display and effect may not part ways.

    ``drafterKandidaten`` is a suggestion rule — same family, matching
    parameter count. The process knows nothing of it: what a start drafts
    against comes from the remembered choice and the folder manifest
    (app/modellrunner.py ``starten``). Taking a non-candidate out of the field
    therefore said "none" about a command line carrying ``--model-draft``, and
    made the choice unreachable on top, because a row already reading "none"
    writes nothing when "none" is picked (Auswahlfeld.svelte ``waehlen``).
    """
    quelle = ohne_kommentare(datei.read_text(encoding="utf-8"))
    # The blanking effect is gone.
    assert not re.search(
        r"drafterKandidaten\.some\([^)]*\)\)\s*drafter\s*=\s*''", quelle
    ), datei.name
    # And the row offers what would actually start.
    auswahl = quelle[quelle.index("const drafterauswahl") :]
    auswahl = auswahl[: auswahl.index("])") + 2]
    assert "drafterKandidaten.some" in auswahl, datei.name
    assert "{ wert: drafter, text: drafter }" in auswahl, datei.name
