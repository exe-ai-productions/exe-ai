"""Why a run ended, where somebody can actually read it.

The catalogue block ``jobs.grund.*`` translated every ending a run can have
and had **not one reader in the whole program** — measured, and older than
the ending that was added last. The reason WAS written: as the run's ``ende``
step. But the step log only opens for a run that is waiting or running, and
the ending is the very moment a run leaves that list for the reports list.
The one line saying what went wrong appeared on screen never.

So two ways out, and both are checked here:

  * the finished run's own row in the reports list carries it
    (frontend/src/teile/ModulAgenten.svelte, ``grundtext``), and
  * an entry on ``deliver = 'announce'`` carries it in the SAME notification
    it already sent (``app/cronmeldung.mit_grund``) — not in a second one.

The same file also guards the second state of a cron entry that could not be
seen: a script entry whose file is no longer where it has to be
(``skript_nicht_startbar``), which walks the road "waiting for a model"
already walks, from the flow's memory through the route into the mask.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import cronablauf, cronmeldung
from app.i18n import LOCALES_VERZEICHNIS

WURZEL = Path(__file__).resolve().parent.parent


# --- Every ending the program can write has words for it --------------------


# Every value that reaches ``ende_grund``, read off the places that write it:
# app/api/v1/auftraege.py (the model run), app/cronablauf.py (the script run),
# app/db/repositories/auftraege.py (the restart sweep), plus the two constants.
# The free-form ``fehler: <message>`` is deliberately not in the list — it
# carries its own text and can have no entry; that case has its own test.
ALLE_GRUENDE = (
    "fertig",
    "benutzer_abbruch",
    "zeitgrenze",
    "rundengrenze",
    "kontext_voll",
    "kein_fortschritt",
    "anbieter_ausfall",
    "wiederholte_ablehnung",
    "ablage_gescheitert",
    "skript_fehler",
    "dienst_neustart",
)


def _katalog(sprache: str) -> dict:
    return json.loads((LOCALES_VERZEICHNIS / f"{sprache}.json").read_text("utf-8"))


@pytest.mark.parametrize("grund", ALLE_GRUENDE)
@pytest.mark.parametrize("sprache", ["de", "en"])
def test_jeder_grund_hat_worte_in_beiden_sprachen(grund, sprache):
    """A reason with no entry would reach the surface as its own key.

    The list above is the point of this test: three of these — the lost
    provider, the run that got no further, the tool call rejected over and
    over — were NOT in the catalogue while the block was described as
    translating them all. Nobody noticed, because nobody read the block.
    """
    assert grund in _katalog(sprache)["jobs"]["grund"]


def test_die_gruende_sind_wirklich_uebersetzt():
    deutsch = _katalog("de")["jobs"]["grund"]
    englisch = _katalog("en")["jobs"]["grund"]
    assert set(deutsch) == set(englisch)
    gleich = [name for name in deutsch if deutsch[name] == englisch[name]]
    assert not gleich, f"left untranslated: {gleich}"


# --- The reason in the notification -----------------------------------------


def test_die_meldung_traegt_den_grund():
    assert cronmeldung.mit_grund("Postfach lesen", "zeitgrenze") == (
        "Postfach lesen — time limit reached"
    )


def test_der_grund_kommt_aus_dem_vorhandenen_sprachblock():
    """Not a second wording invented in the notification module: what stands
    in the notification is what stands in ``jobs.grund.*``."""
    for grund in ALLE_GRUENDE:
        if grund == "fertig":
            continue
        satz = _katalog("en")["jobs"]["grund"][grund]
        assert cronmeldung.mit_grund("Postfach lesen", grund).endswith(f" — {satz}")


def test_ein_sauberer_lauf_meldet_sich_wie_bisher():
    """The counter-check: nothing added where there is nothing to explain —
    no reason at all (a script that exited 0) and 'fertig' both leave the
    text byte for byte what it was."""
    assert cronmeldung.mit_grund("Postfach lesen", None) == "Postfach lesen"
    assert cronmeldung.mit_grund("Postfach lesen", "fertig") == "Postfach lesen"
    assert cronmeldung.mit_grund("Postfach lesen", "") == "Postfach lesen"


def test_ein_unbekannter_grund_zeigt_sich_selbst():
    """A run that died on an error carries its message inline and can have no
    catalogue entry. Showing the key would put ``jobs.grund.fehler: Kabelbrand``
    in front of somebody."""
    text = cronmeldung.mit_grund("Postfach lesen", "fehler: Kabelbrand")
    assert text == "Postfach lesen — fehler: Kabelbrand"
    assert "jobs.grund" not in text


def test_es_bleibt_bei_einer_mitteilung(monkeypatch):
    """The reason rides in the notification that already goes out — no second
    one behind it, and the failure sound is still the one that plays."""
    befehle = []
    monkeypatch.setattr(cronmeldung.sys, "platform", "darwin")
    monkeypatch.setattr(cronmeldung.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        cronmeldung.subprocess, "run",
        lambda befehl, **k: befehle.append(befehl) or SimpleNamespace(returncode=0),
    )

    cronmeldung.melden(
        cronmeldung.mit_grund("Postfach lesen", "ablage_gescheitert"), erfolgreich=False
    )

    klang, mitteilung = befehle
    assert klang[0] == "afplay" and "fehler" in klang[1]
    assert len([b for b in befehle if b[0] == "osascript"]) == 1
    assert "Failed — Postfach lesen — delivery to the dock failed" in mitteilung[-1]


async def test_der_ganze_weg_bis_zur_mitteilung(repos, monkeypatch):
    """From the entry to the notification, through the real function the run's
    end path calls."""
    aufrufe: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        cronablauf.cronmeldung, "melden",
        lambda text, *, erfolgreich, sprache=None: aufrufe.append((text, erfolgreich)),
    )
    eintrag = repos.cronjobs.erstellen(
        agent="a", task="Postfach lesen", zeitplan="08:00", herkunft="chat",
        deliver="announce",
    )

    await cronablauf.melde_wenn_faellig(
        repos, eintrag.id, "Postfach lesen", erfolgreich=False, grund="rundengrenze"
    )

    assert aufrufe == [("Postfach lesen — round limit reached", False)]


async def test_ein_stiller_eintrag_bleibt_still(repos, monkeypatch):
    """`log` is the default and never reaches the notification module at all —
    a reason changes nothing about that."""
    aufrufe: list[str] = []
    monkeypatch.setattr(
        cronablauf.cronmeldung, "melden",
        lambda text, *, erfolgreich, sprache=None: aufrufe.append(text),
    )
    eintrag = repos.cronjobs.erstellen(
        agent="a", task="Postfach lesen", zeitplan="08:00", herkunft="chat",
    )

    await cronablauf.melde_wenn_faellig(
        repos, eintrag.id, "Postfach lesen", erfolgreich=False, grund="zeitgrenze"
    )

    assert aufrufe == []


# --- The reason on the finished run's own row -------------------------------


MODUL_AGENTEN = WURZEL / "frontend/src/teile/ModulAgenten.svelte"
# The expression moved out of the panel when a second display started
# reading it — the notice a finished run puts up reaches for the same
# sentence, and one expression written down twice is how two displays of
# the same run come apart.
MELDER = WURZEL / "frontend/src/lib/auftragsmelder.js"
DOT_MODULE = WURZEL / "frontend/src/lib/agentenampel.svelte.js"


def test_die_berichtszeile_liest_den_sprachblock():
    """The block had no reader. This is the reader."""
    quelle = MELDER.read_text(encoding="utf-8")
    assert "'jobs.grund.' + grund" in quelle
    assert "end_reason" in quelle
    # And the panel still draws it, from the one place it now lives in.
    panel = MODUL_AGENTEN.read_text(encoding="utf-8")
    assert "grundtext(auftrag)" in panel
    assert "auftragsmelder.js" in panel


def test_ein_sauber_gelaufener_bericht_bekommt_keine_zeile():
    """'fertig geworden' under every good report is noise nobody reads past
    the second day — and the row must look exactly as it looked before."""
    quelle = MELDER.read_text(encoding="utf-8")
    funktion = quelle[quelle.index("export function grundtext("):]
    funktion = funktion[: funktion.index("\n}")]
    assert "grund === 'fertig'" in funktion
    assert "return ''" in funktion


def test_ein_gebrochener_lauf_ohne_text_steht_trotzdem_in_der_liste():
    """Measured on the running service: a run stopped at its time limit in
    the middle of a tool call produces no text at all, so ``result`` is None
    — and the list that only took runs WITH a result left out the one run
    whose only news is the reason. A finished run with nothing to say and an
    abort stay out, as before.

    The list grew a second half since (F2/F3, tests/test_anzeigefunde.py):
    'unterbrochen' joins it, and a handed-on link steps aside for anything
    newer of the same work. Neither touches what this test is about, so it
    asks the same two questions of the wider block.

    Which endings have a row is one function since, shared with the dot on
    the rail: the list calls it, and the two conditions stand in it."""
    quelle = MODUL_AGENTEN.read_text(encoding="utf-8")
    block = quelle[quelle.index("const berichte = $derived"):]
    block = block[: block.index("\n  })")]
    assert "worthReading(auftrag)" in block
    row_rule = DOT_MODULE.read_text(encoding="utf-8")
    row_rule = row_rule[row_rule.index("export function worthReading("):]
    row_rule = row_rule[: row_rule.index("\n}")]
    assert "job.result" in row_rule
    assert "job.state === 'gescheitert'" in row_rule


def test_der_unbekannte_grund_zeigt_sich_auch_auf_dem_schirm_selbst():
    quelle = MELDER.read_text(encoding="utf-8")
    assert "text === schluessel ? grund : text" in quelle


# --- "Script cannot start", the same road "waiting for a model" takes -------

# The refusal as the flow really holds it: the catalogue key and its values,
# so the panel can render it in whatever language the browser asks in — and a
# pair rather than the exception, which would drag its traceback into a
# module-level dict.


def _nicht_ausfuehrbar() -> tuple[str, dict]:
    return (
        "fehler.skript_nicht_ausfuehrbar",
        {"name": "sicherung.sh", "ordner": "/wo/anders"},
    )



def test_die_route_reicht_den_zustand_durch(client, monkeypatch):
    eintrag = client.app.state.repositories.cronjobs.erstellen(
        agent=".skript", task="", zeitplan="08:00", herkunft="chat",
        skript="sicherung.sh",
    )
    (ruhig,) = client.get("/api/v1/cronjobs").json()
    assert ruhig["skript_nicht_startbar"] is None

    monkeypatch.setattr(
        cronablauf, "skript_nicht_startbar",
        lambda cronjob_id, sprache=None: (
            "There is no script 'sicherung.sh' in /wo/anders."
            if cronjob_id == eintrag.id else None
        ),
    )
    (gestoert,) = client.get("/api/v1/cronjobs").json()
    assert gestoert["skript_nicht_startbar"] == (
        "There is no script 'sicherung.sh' in /wo/anders."
    )


def test_die_route_nimmt_den_satz_aus_dem_ablauf(client):
    """Read from the flow's own memory, exactly the way ``wartet_auf_modell``
    is — not from a column that would survive the restart, or the file put
    back, that fixed it."""
    eintrag = client.app.state.repositories.cronjobs.erstellen(
        agent=".skript", task="", zeitplan="08:00", herkunft="chat",
        skript="sicherung.sh",
    )
    cronablauf._skript_fehlt[eintrag.id] = (
        datetime(2026, 9, 2, 9, 0), False, _nicht_ausfuehrbar(),
    )
    try:
        # In the reader's own language, both of them. The German panel used
        # to wrap an English middle -- "Kann nicht starten -- There is no
        # script 'x' in ..." -- because the refusal was rendered where it was
        # raised and stored as a finished sentence.
        (deutsch,) = client.get(
            "/api/v1/cronjobs", headers={"Accept-Language": "de"}
        ).json()
        assert deutsch["skript_nicht_startbar"] == (
            "„sicherung.sh“ ist nicht ausführbar. Erteile der Datei im Skriptordner "
            "(/wo/anders) eine Ausführungsberechtigung und versuche es erneut."
        )

        (englisch,) = client.get(
            "/api/v1/cronjobs", headers={"Accept-Language": "en"}
        ).json()
        assert englisch["skript_nicht_startbar"] == (
            "'sicherung.sh' is not executable. Grant execute permission in the "
            "scripts folder (/wo/anders) and try again."
        )
    finally:
        cronablauf._skript_fehlt.pop(eintrag.id, None)


def test_die_maske_zeigt_den_zustand():
    """Beside "waiting for a model", not instead of it, and with the refusal
    in its own words — the file being gone and the file not being executable
    are two different things to go and do. The settings page carries it in
    the line under the schedule's head."""
    seite = (WURZEL / "frontend/src/teile/SettingsCronjobs.svelte").read_text("utf-8")
    assert "if (z.wartet_auf_modell)" in seite
    assert re.search(r"if \(z\.skript_nicht_startbar\)", seite), "no branch of its own"
    assert "t('cronjobs.skript_nicht_startbar', { grund: z.skript_nicht_startbar })" in seite


@pytest.mark.parametrize("sprache", ["de", "en"])
def test_die_maske_hat_worte_fuer_den_zustand(sprache):
    text = _katalog(sprache)["cronjobs"]["skript_nicht_startbar"]
    assert "{grund}" in text


# --- A paused entry answers neither question --------------------------------
#
# Both live states are held in the flow's memory, and that memory is only
# cleared by a run that starts. A paused entry never starts, and the tick loop
# skips it — so whatever the last tick before the pause wrote stayed on the
# row for good: a red "cannot start" naming a file that had long since been
# put back, on an entry nobody had asked to run for weeks.


def test_pausierter_termin_meldet_kein_nicht_startbar(client):
    eintrag = client.app.state.repositories.cronjobs.erstellen(
        agent=".skript", task="", zeitplan="08:00", herkunft="chat",
        skript="sicherung.sh",
    )
    cronablauf._skript_fehlt[eintrag.id] = (
        datetime(2026, 9, 2, 9, 0), False, _nicht_ausfuehrbar(),
    )
    try:
        (laufend,) = client.get("/api/v1/cronjobs").json()
        assert laufend["skript_nicht_startbar"] is not None

        pausiert = client.post(f"/api/v1/cronjobs/{eintrag.id}/pause").json()
        assert pausiert["skript_nicht_startbar"] is None
        (aus_der_liste,) = client.get("/api/v1/cronjobs").json()
        assert aus_der_liste["skript_nicht_startbar"] is None

        # And back again: switching it on asks the same question anew, so an
        # entry whose file is still missing says so from the first tick.
        fortgesetzt = client.post(f"/api/v1/cronjobs/{eintrag.id}/resume").json()
        assert fortgesetzt["skript_nicht_startbar"] is not None
    finally:
        cronablauf._skript_fehlt.pop(eintrag.id, None)


def test_pausierter_termin_meldet_kein_warten_auf_modell(client):
    """The same road, one state over — the model wait is held the same way and
    was cleared the same way, by a run that a paused entry never has."""
    eintrag = client.app.state.repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    cronablauf._wartend[eintrag.id] = (datetime(2026, 9, 2, 9, 0), False)
    try:
        (laufend,) = client.get("/api/v1/cronjobs").json()
        assert laufend["wartet_auf_modell"] is True

        pausiert = client.post(f"/api/v1/cronjobs/{eintrag.id}/pause").json()
        assert pausiert["wartet_auf_modell"] is False
        (aus_der_liste,) = client.get("/api/v1/cronjobs").json()
        assert aus_der_liste["wartet_auf_modell"] is False

        fortgesetzt = client.post(f"/api/v1/cronjobs/{eintrag.id}/resume").json()
        assert fortgesetzt["wartet_auf_modell"] is True
    finally:
        cronablauf._wartend.pop(eintrag.id, None)


def test_ein_stiller_termin_bleibt_still(client):
    """The silence test: an entry that is on and has nothing wrong with it
    must not start reporting a state because the gate was added."""
    client.app.state.repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    (zeile,) = client.get("/api/v1/cronjobs").json()
    assert zeile["aktiv"] is True
    assert zeile["wartet_auf_modell"] is False
    assert zeile["skript_nicht_startbar"] is None
