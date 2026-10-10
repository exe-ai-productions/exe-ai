"""The schedule list says so when a goal was never reached (02.09.).

The case that used to fall through every crack: a one-off entry with a goal,
on ``deliver = 'log'``, that ran and found nothing. No notification — that is
what ``log`` means since dc9d2c4, and it is right. A green lamp — the run
itself worked. And in the mask: nothing at all, because ``angehalten`` wants
the failure count level with its limit (0) and ``abgeschlossen`` wants
``ziel_erreicht_am`` (empty). The only trace was a line in the python log,
which this window does not show. Silent must not mean invisible.

The state is read off the goal alone, so it holds for every switched-off
entry with an open goal, whatever switched it off and whatever ``deliver``
says. The three predicates are therefore checked against each other here,
not just for themselves: ``abgeschlossen`` must never coincide with it, and
``angehalten`` must be able to, because a failure limit is a REASON for an
unreached goal rather than a contradiction of it.

The functions are lifted out of the component and really run, rather than
matched with a regular expression: a condition that reads right and answers
wrong is exactly what this is insurance against.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
MASKE = FRONTEND / "src" / "teile" / "SettingsCronjobs.svelte"
KATALOGE = WURZEL / "app" / "locales"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="no Node on this machine",
)

# One switched-off entry with a goal it never reported, in the six shapes the
# list can hold it in. ``id`` is the name the report and the failures use.
FAELLE = [
    # The case this whole state exists for: a one-off that fired, ended
    # properly, and never called ``goal``.
    {"id": "einmalig_gelaufen_ohne_zielmeldung", "aktiv": False,
     "ziel": "Antwort von der Werkstatt", "ziel_stilllegen": False,
     "ziel_erreicht_am": None, "fehlversuche": 0, "fehlergrenze": 5},
    # Switched off by hand with the goal still open. Same answer: WHY it is
    # off says nothing about whether the goal was reached.
    {"id": "von_hand_aus_ziel_offen", "aktiv": False, "ziel": "Paket ist da",
     "ziel_stilllegen": False, "ziel_erreicht_am": None,
     "fehlversuche": 0, "fehlergrenze": 5},
    # The failure limit: a reason, not a contradiction — both lines stand.
    {"id": "fehlergrenze_gerissen", "aktiv": False, "ziel": "Sicherung gelaufen",
     "ziel_stilllegen": False, "ziel_erreicht_am": None,
     "fehlversuche": 2, "fehlergrenze": 2},
    # Reached and stopped itself: "finished", and never this.
    {"id": "ziel_erreicht_stillgelegt", "aktiv": False, "ziel": "Mail ist da",
     "ziel_stilllegen": True, "ziel_erreicht_am": "2026-09-01T13:07:00+02:00",
     "fehlversuche": 0, "fehlergrenze": 5},
    # Nothing it could have missed.
    {"id": "aus_ohne_ziel", "aktiv": False, "ziel": None,
     "ziel_stilllegen": False, "ziel_erreicht_am": None,
     "fehlversuche": 0, "fehlergrenze": 5},
    # Still running: its goal is still ahead of it, not missed.
    {"id": "aktiv_mit_ziel", "aktiv": True, "ziel": "Postfach leer",
     "ziel_stilllegen": False, "ziel_erreicht_am": None,
     "fehlversuche": 0, "fehlergrenze": 5},
]


def _antworten() -> dict[str, dict[str, bool]]:
    """What the mask's own three functions answer for each case above.

    Lifted straight out of the component and run: the component itself cannot
    be server-rendered for this, because its rows arrive from ``api.cronjobs``
    in an effect that never runs on the server — the page would render empty
    and prove nothing.
    """
    treiber = FRONTEND / "zielverfehlt.pruefung.mjs"
    treiber.write_text(
        textwrap.dedent(
            """
            import { readFileSync } from 'fs'
            // A checkout with CRLF line ends (git on Windows) would hide the
            // braces from the pattern below.
            const quelle = readFileSync(%r, 'utf-8').replace(/\\r\\n/g, '\\n')
            const muster = /^  function (angehalten|abgeschlossen|zielverfehlt)\\(zeile\\) \\{\\n([\\s\\S]*?)^  \\}$/gm
            const funktionen = {}
            for (const [, name, rumpf] of quelle.matchAll(muster)) {
              funktionen[name] = new Function('zeile', rumpf)
            }
            const fehlend = ['angehalten', 'abgeschlossen', 'zielverfehlt']
              .filter((n) => !funktionen[n])
            if (fehlend.length) throw new Error('nicht gefunden: ' + fehlend.join(', '))
            const aus = {}
            for (const fall of %s) {
              aus[fall.id] = Object.fromEntries(
                Object.entries(funktionen).map(([n, f]) => [n, Boolean(f(fall))]),
              )
            }
            console.log('---BERICHT---')
            console.log(JSON.stringify(aus))
            """
        )
        % (str(MASKE), json.dumps(FAELLE)),
        encoding="utf-8",
    )
    try:
        lauf = subprocess.run(
            ["node", treiber.name],
            cwd=FRONTEND, capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
    finally:
        treiber.unlink(missing_ok=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-2000:]
    marke = "---BERICHT---"
    assert marke in lauf.stdout, lauf.stdout[-2000:]
    return json.loads(lauf.stdout.split(marke, 1)[1].strip())


@pytest.fixture(scope="module")
def antworten() -> dict[str, dict[str, bool]]:
    return _antworten()


# --- The state itself ------------------------------------------------------


def test_einmaliger_lauf_ohne_zielmeldung_steht_in_der_liste(antworten):
    """The order that used to vanish without a word."""
    assert antworten["einmalig_gelaufen_ohne_zielmeldung"]["zielverfehlt"]


def test_von_hand_ausgeschaltet_mit_offenem_ziel_steht_ebenso_da(antworten):
    """Off by hand is still off with the goal unreached — the reason for the
    switch changes nothing about the answer."""
    assert antworten["von_hand_aus_ziel_offen"]["zielverfehlt"]


def test_ohne_ziel_sagt_die_maske_nichts(antworten):
    """No goal, nothing that could have been missed."""
    assert not antworten["aus_ohne_ziel"]["zielverfehlt"]


def test_ein_laufender_termin_sagt_nichts(antworten):
    """Its goal is ahead of it, not missed."""
    assert not antworten["aktiv_mit_ziel"]["zielverfehlt"]


# --- Against the two states that were there first --------------------------


def test_erreichtes_ziel_bleibt_abgeschlossen_und_nur_das(antworten):
    """``ziel_erreicht_am`` is what one wants and the other refuses, so the
    two can never both be true — whatever order the mask asks them in."""
    fall = antworten["ziel_erreicht_stillgelegt"]
    assert fall["abgeschlossen"]
    assert not fall["zielverfehlt"]


def test_die_fehlergrenze_ist_ein_grund_kein_widerspruch(antworten):
    """An entry that gave up at its limit is off AND has not reached its
    goal. Both lines stand: the red one names the reason, the quiet one the
    goal."""
    fall = antworten["fehlergrenze_gerissen"]
    assert fall["angehalten"]
    assert fall["zielverfehlt"]


def test_kein_erreichtes_ziel_faellt_je_in_den_neuen_zustand(antworten):
    """The one overlap that would be a lie, checked across every case."""
    for name, fall in antworten.items():
        assert not (fall["abgeschlossen"] and fall["zielverfehlt"]), name


# --- Where it stands in the markup -----------------------------------------


def test_der_zustand_steht_neben_der_kette_nicht_darin():
    """Its own block, not another branch: the chain answers "why is this not
    running" and exactly one of its branches can win, which would have hidden
    this line behind ``angehalten`` on the very entries that need both."""
    maske = MASKE.read_text("utf-8")
    assert "{#if zielverfehlt(zeile)}" in maske
    assert "{:else if zielverfehlt(zeile)}" not in maske
    assert "t('cronjobs.ziel_nicht_erreicht')" in maske


@pytest.mark.parametrize("sprache", ["de", "en"])
def test_die_maske_hat_worte_fuer_den_zustand(sprache):
    katalog = json.loads((KATALOGE / f"{sprache}.json").read_text("utf-8"))
    assert katalog["cronjobs"]["ziel_nicht_erreicht"].strip()
