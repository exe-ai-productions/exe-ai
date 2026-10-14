"""The window a stop opens, and the one rule for the remembered choice.

Four holes, all of them about the same sentence: which model, with which
numbers, does this program call its own? One of them was opened by the
repair before it.

  * **The hand-back's own ``await``.** When a run ends, both server pages
    read the setting again and put it back into the fields (``3fffe30``).
    Between those two acts stands a read, and a read is a wait: ``laeuft``
    is already false, ``zahlenStehen`` is still true, and the RUN's numbers
    are still in the fields. The 600 ms watcher sees exactly that and writes
    them down as the choice. Measured with a read braked to 1500 ms —
    131072/0 replaced by 32768/99 on the model server, by the slot's
    16384/99 on the agent page.

    ``18ffae6`` closed it with a lock, ``holtZurueck``, that held the
    watcher and the foot button for the length of the read. The lock is
    gone: the fields are handed back out of this window's own copy BEFORE
    the read as well, so what stands in the form during the wait is what the
    store already holds — and the watcher writes only what the form says and
    the store does not (lib/nurgeaendert.js), which is then nothing. The
    wait is made harmless instead of guarded.

    The lock was also worse than the race. It came down in one branch only,
    so a single refused settings read left it up — through the whole of the
    NEXT run, with the stop button dead and no word on the page about why.
    Measured: still locked 15 seconds into a second run.

  * **The page's own stop button opened the same window, in front of the
    lock.** ``anhalten`` took the stop's answer into ``auskunft``, and that
    answer carries ``laeuft: false``. So the run ended for this window one
    statement after the click, with the RUN's numbers still in the fields,
    while the hand-back waited for a poll up to two seconds away — and the
    600 ms watcher fits inside that every time. Measured on the real page,
    seven stops out of seven: the stored 131072/0 became the run's 32768/99
    at +750 ms. The slot's page never had the hole; its ``anhalten`` does not
    touch ``auskunft``, and this one does not either now.

  * **A repeated read failure rang every two seconds.** The strict read
    throws, the poll's catch reports it, and ``melde(..., 'fehler')`` makes a
    sound. Measured on both pages: 15 red tiles and 15 sounds in 30 seconds.
    Reported once per streak now — the error stays visible, its repetition
    stops.

  * **The rule for the remembered choice stood twice, word for word.** In
    the page's poll and in a second start path, held together by a guard that
    matched the front of the line while the ``.some(...)`` half could drift
    with both tests green. It lives in one function now
    (lib/runnermodell.svelte.js ``gemerkteDatei``).

  * **A stored ``""`` is a chosen "none" and was treated as nothing.**
    ``gemerkt && …`` is falsy for it, so a start took the folder's first
    file and had it recorded as the main model. The page holds the same
    answer the other way: it counts ``''`` as valid and LOCKS the start
    button. Two paths to one act, disagreeing about what the answer means.

  * **The reads were not in the queue the writes go through.** An answer
    still on the wire while a PATCH lands puts the store back to the state
    before that PATCH. Measured on the slot: the field fell back to the
    model picked before, while the setting held the new one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import runnermodellwahl

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
MODELLSERVER = FRONTEND / "src" / "teile" / "Modellserver.svelte"
AGENTSERVER = FRONTEND / "src" / "teile" / "Agentserver.svelte"
RUNNERMODELL = FRONTEND / "src" / "lib" / "runnermodell.svelte.js"
AGENTENSERVER = FRONTEND / "src" / "lib" / "agentenserver.svelte.js"

SEITEN = [MODELLSERVER, AGENTSERVER]


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


def zweig(quelle: str) -> str:
    """What stands between ``else if (liefVorher) {`` and its closing brace."""
    koerper = rumpf(quelle, "async function laden()")
    stelle = koerper.index("else if (liefVorher)")
    anfang = koerper.index("{", stelle)
    return koerper[anfang + 1 : koerper.index("}", anfang)]


# --- The wait inside the hand-back ---------------------------------


@pytest.mark.parametrize("datei", SEITEN, ids=lambda p: p.name)
def test_die_rueckgabe_setzt_die_felder_vor_dem_lesen(datei: Path):
    """``werteUebernehmen()`` stands BEFORE the read, and again after it.

    That order is the whole fix. Before the read, the fields are put on this
    window's own copy of the choice — so for the length of the wait the form
    says what the store says, and ``nurGeaendert`` leaves the watcher with
    nothing to write. After the read, they are put on whatever the read
    brought, which is what the hand-back is for: the stored choice, not this
    window's copy of it.

    Take the first one out and the wait holds the RUN's numbers again, which
    is the loss measured at 131072/0 → 32768/99.
    """
    quelle = ohne_kommentare(datei.read_text(encoding="utf-8"))
    z = zweig(quelle)
    lesen = z.index("await standLaden(")
    vor = z[:lesen]
    nach = z[lesen:]
    assert "werteUebernehmen()" in vor, (
        f"{datei.name}: the branch reads before it sets the fields to the copy — "
        "during that wait the run stands in the form and the guard "
        "writes it as the choice"
    )
    assert "werteUebernehmen()" in nach, (
        f"{datei.name}: nothing is taken over again after the read — the "
        "fields would stay on the copy this window already had"
    )


@pytest.mark.parametrize("datei", SEITEN, ids=lambda p: p.name)
def test_der_rueckgabe_zweig_sperrt_nichts(datei: Path):
    """No lock, on either page — not under this name and not under another.

    A lock that comes down in one branch stays up when that branch throws.
    ``holtZurueck`` came down in the hand-back alone, so one refused settings
    read left the stop button dead for the whole of the next run. There is no
    state to be stuck in any more, so there is nothing to release either: no
    ``finally``, no catch of its own, nothing between the branch and its two
    hand-backs but the read.
    """
    quelle = ohne_kommentare(datei.read_text(encoding="utf-8"))
    assert "holtZurueck" not in quelle, (
        f"{datei.name}: the lock is back — a state that is only lowered in the "
        "hand-back branch stays up after a failed read"
    )
    z = zweig(quelle)
    assert "finally" not in z, datei.name
    assert "catch" not in z, datei.name
    # Nothing may stand between the branch and its FIRST hand-back — that one
    # is what makes the read harmless, so it must not be conditional. What
    # comes after it may branch (`if (modell) modulUebernehmen(modell)`).
    assert not re.search(r"\b(if|return|for|while|switch)\b", z[: z.index("werteUebernehmen()")]), (
        f"{datei.name}: the branch sets the fields to the copy only under one condition"
    )


@pytest.mark.parametrize("datei", SEITEN, ids=lambda p: p.name)
def test_die_rueckgabe_liest_streng(datei: Path):
    """``standLaden(true)`` — the caller acts on this answer.

    A read that did not reach the setting leaves this window's own copy
    standing, and that copy is exactly what the hand-back exists to stop
    using. Both stores let a caller say so.
    """
    quelle = ohne_kommentare(datei.read_text(encoding="utf-8"))
    assert "await standLaden(true)" in zweig(quelle), datei.name


@pytest.mark.parametrize("datei", SEITEN, ids=lambda p: p.name)
def test_der_waechter_fragt_nur_nach_laeuft(datei: Path):
    """The 600 ms watcher has one condition again, and needs one.

    It never had to be told about the hand-back: what it writes is decided at
    the write itself, by ``nurGeaendert``, and during the hand-back the form
    holds exactly what the store holds. A brake at the watcher could hang;
    the filter at the write cannot.
    """
    quelle = ohne_kommentare(datei.read_text(encoding="utf-8"))
    treffer = re.search(r"if \(!zahlenStehen \|\| laeuft([^)]*)\) return", quelle)
    assert treffer, f"{datei.name}: the guard's brake can no longer be found"
    assert treffer.group(1).strip() == "", (
        f"{datei.name}: the guard hangs on a second state again — "
        f"{treffer.group(1)!r}"
    )
    assert "nurGeaendert(" in quelle, (
        f"{datei.name}: without the filter at the place of writing the build does not hold"
    )


@pytest.mark.parametrize("datei", SEITEN, ids=lambda p: p.name)
def test_der_fussknopf_haengt_an_keinem_rueckgabe_zustand(datei: Path):
    """And the button in the rail's foot is not hung on one either.

    Pressed inside the hand-back it stores only the file — the filter empties
    its supplement — and the service reads window, layers and port out of the
    setting itself (app/runnermodellwahl.py ``startwerte``,
    app/agentenmodellwahl.py ``slot_startwerte``). There is nothing for a lock
    to protect, and a lock left up is a dead button with no explanation.
    """
    quelle = ohne_kommentare(datei.read_text(encoding="utf-8"))
    treffer = re.search(r"gesperrt: ([^\n]*),", quelle)
    assert treffer, f"{datei.name}: the start button no longer reports `gesperrt`"
    assert "holtZurueck" not in treffer.group(1), (
        f"{datei.name}: the footer button hangs on the hand-back state again"
    )


def test_der_eigene_stoppknopf_kippt_die_laufanzeige_nicht():
    """``anhalten`` does not take the stop's answer into ``auskunft``.

    That answer carries ``laeuft: false``, so assigning it ended the run for
    this window one statement after the click — with the RUN's numbers in the
    fields and the hand-back still up to two seconds away in the poll. The
    600 ms watcher fits inside that gap every time: measured on the real page,
    seven stops out of seven turned a stored 131072/0 into the run's 32768/99
    at +750 ms. The slot's page has never done it (``Agentserver.svelte``
    ``anhalten``), which is where the shape comes from.
    """
    for datei in SEITEN:
        quelle = ohne_kommentare(datei.read_text(encoding="utf-8"))
        koerper = rumpf(quelle, "async function anhalten()")
        assert not re.search(r"auskunft\s*=", koerper), (
            f"{datei.name}: `anhalten` sets `auskunft` — the run then ends for "
            "this window at once, while the run's figures still stand in the form "
            "and only the next tick brings the hand-back"
        )


@pytest.mark.parametrize("datei", SEITEN, ids=lambda p: p.name)
def test_ein_wiederkehrender_lesefehler_meldet_nur_einmal(datei: Path):
    """The poll's catch does not report the same failure every two seconds.

    ``melde(..., 'fehler')`` makes a sound (lib/zustand.svelte.js). A refused
    settings read lasts, and the poll runs every two seconds: measured, 15 red
    tiles and 15 sounds in 30 seconds on each page. The error still has to be
    SEEN — so it is reported when it starts and again when it says something
    else — and the memory is cleared by a tick that gets through, so the same
    failure returning later is news again.
    """
    quelle = ohne_kommentare(datei.read_text(encoding="utf-8"))
    koerper = rumpf(quelle, "async function laden()")
    assert "letzterFehler = null" in koerper, (
        f"{datei.name}: nothing resets the memory — an error that "
        "came once and comes again would stay silent afterwards"
    )
    assert re.search(r"if \([^)]*!== letzterFehler\)\s*melde\(", koerper), (
        f"{datei.name}: the notice in the error branch rings at every tick"
    )


# --- The rule for the remembered choice stands once ------------


def test_die_regel_der_gemerkten_wahl_steht_nur_an_einem_ort():
    """One act, two paths, ONE line — not two that have to be kept in step.

    The rule stood word for word in the page's poll and in a second start path,
    and what held them together was a guard matching the front of it. The
    ``.some(...)`` half could have drifted with both tests green, and that
    half is the point: ``''`` is a chosen "none" and counts as an answer, a
    name whose file has gone does not, ``null`` is nobody having chosen.

    So it is asked for by name in one place. Bend ``gemerkteDatei`` and both
    callers change together, because there is nothing else left to change.
    """
    regel = r"gemerkt !== null && \(gemerkt === ''"
    treffer = [
        d
        for d in sorted((FRONTEND / "src").rglob("*"))
        if d.is_file()
        and d.suffix in {".js", ".svelte"}
        and re.search(regel, ohne_kommentare(d.read_text(encoding="utf-8")))
    ]
    assert [d.name for d in treffer] == ["runnermodell.svelte.js"], (
        f"the rule stands in {len(treffer)} places: {[d.name for d in treffer]} — "
        "two versions of one rule drift apart, and the wording test "
        "between them only checks their start"
    )


def test_the_page_asks_the_one_function():
    """And the page really asks it, rather than keeping a second opinion.

    The page pre-picks the answer into its field and writes nothing; a start
    records whatever came up as the main model (app/api/v1/runner.py
    ``modell_merken``). WHICH file the question answers with is decided in
    one place, and the page reads it from there.
    """
    kopf = "async function laden()"
    quelle = ohne_kommentare(MODELLSERVER.read_text(encoding="utf-8"))
    assert "gemerkteDatei" in rumpf(quelle, kopf), (
        f"{MODELLSERVER.name}: does not ask for the remembered choice through `gemerkteDatei`"
    )
    assert "gemerkteDatei" in quelle.split(kopf)[0], (
        f"{MODELLSERVER.name}: `gemerkteDatei` is not imported"
    )


def test_die_regel_achtet_ein_gewaehltes_keins():
    """``''`` is an answer, and ``gemerkt && …`` throws it away.

    The page counts it as valid and locks the button; the command took the
    folder's first file and had it written down as the main model. Asked at
    the one place the rule now lives.
    """
    quelle = ohne_kommentare(RUNNERMODELL.read_text(encoding="utf-8"))
    koerper = rumpf(quelle, "export function gemerkteDatei(dateien)")
    assert "gemerkt === ''" in koerper, (
        'runnermodell.svelte.js: a stored "" means "no model, '
        'explicitly chosen" — without the check it falls back to dateien[0]'
    )
    assert not re.search(r"\bgemerkt &&", koerper), (
        'runnermodell.svelte.js: `gemerkt && …` is falsy for the choice ""'
    )
    assert "dateien[0]?.name" in koerper, (
        "runnermodell.svelte.js: the fallback to the folder's first file is missing"
    )


def test_ein_start_ersetzt_ein_gewaehltes_keins(client: TestClient):
    """Why the guard above is worth having, at the route.

    ``POST /runner/start`` records whatever started as the main model. So a
    start path that picks its own file where the user picked "none" does not
    merely start something unasked — it deletes the answer.
    """
    laden = client.app.state.repositories
    client.put("/api/v1/settings/global/runnermodell", json={"wert": {"modell": ""}})
    assert runnermodellwahl.wahl(laden)["modell"] == ""
    runnermodellwahl.modell_merken(laden, "gemma.gguf")
    assert runnermodellwahl.wahl(laden)["modell"] == "gemma.gguf"


# --- A read is a writer of the store -------------------------------


def test_das_lesen_des_hauptmodells_ist_gereiht():
    """``standLaden`` goes through the same queue as the writers.

    An answer still on the wire while a PATCH lands puts the store back to
    the state before that PATCH — the value on screen is then this window's
    own choice, undone by its own read.
    """
    quelle = ohne_kommentare(RUNNERMODELL.read_text(encoding="utf-8"))
    koerper = rumpf(quelle, "export function standLaden(erneut = false)")
    assert "nacheinander(" in koerper, (
        "runnermodell.svelte.js: standLaden does not go through `nacheinander` — a "
        "GET still on its way sets the store back behind a PATCH"
    )
    assert "einlesen" in koerper


def test_das_lesen_des_slots_ist_gereiht():
    """The same on the slot's key, where the pick itself makes the crossing.

    ``waehlen`` writes and then stops and starts the process; the poll that
    sees the gap reads. Measured: the field fell back to the model picked
    before, and stayed there.
    """
    quelle = ohne_kommentare(AGENTENSERVER.read_text(encoding="utf-8"))
    koerper = rumpf(quelle, "export function standLaden(streng = false)")
    assert "nacheinander(" in koerper, (
        "agentenserver.svelte.js: standLaden does not go through `nacheinander`"
    )


def test_der_slot_liest_aus_der_schlange_heraus_ohne_sich_selbst_zu_erwarten():
    """``waehlen`` runs inside the queue, so it reads the unqueued way.

    A queued call that joins the same queue waits for itself. The model
    server's store has had this shape from the start (``werteSetzen`` calls
    ``einlesen``); this is that shape on the slot.
    """
    quelle = ohne_kommentare(AGENTENSERVER.read_text(encoding="utf-8"))
    koerper = rumpf(quelle, "export function waehlen(wahl)")
    assert "await einlesen()" in koerper, (
        "agentenserver.svelte.js: waehlen calls standLaden from inside the queue — that "
        "waits for itself"
    )
    assert "standLaden(" not in koerper


@pytest.mark.parametrize(
    "datei,kopf",
    [
        (RUNNERMODELL, "async function einlesen(streng = false)"),
        (AGENTENSERVER, "async function einlesen(streng = false)"),
    ],
    ids=lambda x: getattr(x, "name", str(x)[:20]),
)
def test_ein_gescheitertes_lesen_bleibt_nicht_stumm(datei: Path, kopf: str):
    """A read that did not arrive says so — to whoever asked for it.

    Both stores kept the old copy silently, so "read it again" could quietly
    mean "kept what you had". The mount read stays lenient: nothing has been
    read there yet and the defaults are the honest answer.
    """
    quelle = ohne_kommentare(datei.read_text(encoding="utf-8"))
    koerper = rumpf(quelle, kopf)
    assert re.search(r"if \(streng\) throw", koerper), (
        f"{datei.name}: a failed read leaves the old copy standing "
        "without the caller learning of it"
    )
