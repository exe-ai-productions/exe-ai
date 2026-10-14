"""What an ended run says, and how often it says it.

The ranking is the point of the module, so it is executed rather than read:
the shipped file is imported in node against real job rows, with only the
two modules it talks TO replaced — the notice list and the text catalogue.
The catalogue stub is the real ``app/locales/en.json``, so a reason that
has a translation resolves the way it does in the program and one that has
none falls back the way it does there too.

``weitergereicht`` is not stubbed either: it is loaded from
frontend/src/lib/laufstand.js, the file both displays of a run already
import, exactly as tests/test_agentenampel.py does it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

WURZEL = Path(__file__).resolve().parents[1]
FRONTEND = WURZEL / "frontend"
MODUL = FRONTEND / "src" / "lib" / "auftragsmelder.js"
LAUFSTAND = FRONTEND / "src" / "lib" / "laufstand.js"
MARKE = FRONTEND / "src" / "lib" / "agentmarke.js"
KATALOG = WURZEL / "app" / "locales" / "en.json"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)


@contextmanager
def _pruefordner():
    ordner = FRONTEND / "node_modules" / f".pruefstand-auftragsmelder-{uuid4().hex}"
    ordner.mkdir(parents=True)
    try:
        yield ordner
    finally:
        shutil.rmtree(ordner, ignore_errors=True)


def _melden(*ticks: list[dict]) -> list[dict]:
    """Hand the module one job list per tick and return every notice it
    asked for, in order."""
    with _pruefordner() as ordner:
        (ordner / "meldewesen.mjs").write_text(
            "export const gemeldet = []\n"
            "export function melden(m) { gemeldet.push(m) }\n",
            encoding="utf-8",
        )
        (ordner / "texte.mjs").write_text(
            "import { readFileSync } from 'fs'\n"
            f"const katalog = JSON.parse(readFileSync({json.dumps(str(KATALOG))}, 'utf-8'))\n"
            "export function t(schluessel) {\n"
            "  let knoten = katalog\n"
            "  for (const teil of schluessel.split('.')) {\n"
            "    if (knoten == null || typeof knoten !== 'object') return schluessel\n"
            "    knoten = knoten[teil]\n"
            "  }\n"
            "  return typeof knoten === 'string' ? knoten : schluessel\n"
            "}\n",
            encoding="utf-8",
        )
        quelle = MODUL.read_text(encoding="utf-8")
        # The agent's display name: the shipped file, with only the
        # catalogue behind it replaced like the module's own.
        (ordner / "agentmarke.mjs").write_text(
            MARKE.read_text(encoding="utf-8").replace("./texte.svelte.js", "./texte.mjs"),
            encoding="utf-8",
        )
        (ordner / "melder.mjs").write_text(
            # An import wants a URL, not a path: a Windows path is read as a
            # protocol ('c:') and refused.
            quelle.replace("./laufstand.js", LAUFSTAND.as_uri())
            .replace("./agentmarke.js", "./agentmarke.mjs")
            .replace("./meldewesen.svelte.js", "./meldewesen.mjs")
            .replace("./texte.svelte.js", "./texte.mjs"),
            encoding="utf-8",
        )
        treiber = ordner / "pruefung.mjs"
        treiber.write_text(
            textwrap.dedent(
                """
                const m = await import('./melder.mjs')
                const { gemeldet } = await import('./meldewesen.mjs')
                for (const tick of %s) m.auftraegeBeobachten(tick)
                console.log('---BERICHT---' + JSON.stringify(gemeldet))
                """
            )
            % json.dumps(list(ticks)),
            encoding="utf-8",
        )
        ergebnis = subprocess.run(
            ["node", treiber.name], cwd=ordner, capture_output=True, text=True,
            encoding="utf-8", timeout=120,
        )
    assert ergebnis.returncode == 0, (ergebnis.stdout + ergebnis.stderr)[-2000:]
    marke = "---BERICHT---"
    assert marke in ergebnis.stdout, ergebnis.stdout[-2000:]
    return json.loads(ergebnis.stdout.split(marke, 1)[1].strip())


def _job(kennung, zustand, *, grund=None, ergebnis=None, agent="Rechercheur", wann=None):
    """A run row. `wann` is when it last moved; left out it is a fixed date
    far in the future, so it counts as news whenever the module was loaded."""
    return {
        "id": kennung,
        "agent": agent,
        "state": zustand,
        "end_reason": grund,
        "result": ergebnis,
        "updated_at": wann if wann is not None else SPAETER,
    }


# Fixed dates, far on either side of any moment the module could be loaded:
# it takes its floor from `Date.now()` when node imports it, and a stamp
# computed from the clock would drift towards that floor the longer the suite
# runs before this file (a full suite runs for minutes).
SPAETER = "2999-01-01T00:00:00+00:00"
FRUEHER = "2000-01-01T00:00:00+00:00"


# --- The ranking -----------------------------------------------------------


def test_der_satz_des_agenten_steht_im_toast():
    """First choice: the run's own closing text, cut to one line."""
    meldungen = _melden(
        [],
        [_job("a", "fertig", grund="fertig", ergebnis="Drei Quellen geprüft. Zwei davon taugen.")],
    )
    assert len(meldungen) == 1
    assert meldungen[0]["text"] == "Rechercheur · Drei Quellen geprüft."
    assert meldungen[0]["was"] == "fertig"
    assert meldungen[0]["auftragId"] == "a"


def test_a_run_without_agent_is_named_by_the_word_never_by_the_marker():
    """The marker an entry with no agent carries is bookkeeping: the notice
    reads "No agent", not "(none)" — for an ending and for a question."""
    meldungen = _melden(
        [],
        [
            _job("a", "fertig", grund="fertig", ergebnis="Erledigt.", agent="(none)"),
            {
                **_job("b", "wartet", agent="(none)"),
                "question": {"aufruf_id": "q1", "frage": "Welche Datei?"},
            },
        ],
    )
    assert sorted(m["text"] for m in meldungen) == [
        "No agent · Erledigt.",
        "No agent · Welche Datei?",
    ]
    assert not any("(none)" in m["text"] for m in meldungen)
    # Silence probe: a run with an agent keeps its own name.
    (eigener,) = _melden([], [_job("c", "fertig", grund="fertig", ergebnis="Gut.")])
    assert eigener["text"] == "Rechercheur · Gut."


def test_ohne_ergebnis_steht_der_grund_in_worten():
    """Second choice — and the sentence a run that dies at its time limit
    must carry instead of 'done'."""
    meldungen = _melden([], [_job("a", "gescheitert", grund="zeitgrenze")])
    assert len(meldungen) == 1
    assert meldungen[0]["text"].startswith("Rechercheur · ")
    assert meldungen[0]["text"] != "Rechercheur · "
    assert "zeitgrenze" not in meldungen[0]["text"]
    assert meldungen[0]["was"] == "fehler"


def test_ein_unbekannter_grund_zeigt_sich_selbst():
    """A run that died on an error carries the message inline and can have
    no catalogue entry — it must not read as a key on screen."""
    meldungen = _melden([], [_job("a", "gescheitert", grund="fehler: connection reset")])
    assert meldungen[0]["text"] == "Rechercheur · fehler: connection reset"


def test_weder_noch_meldet_namen_und_ausgang():
    """Third choice, the last resort — never an empty notice."""
    meldungen = _melden([], [_job("a", "gescheitert")])
    assert len(meldungen) == 1
    assert meldungen[0]["text"].startswith("Rechercheur · ")
    assert meldungen[0]["text"] != "Rechercheur · "


def test_ein_langer_bericht_wird_gekuerzt():
    lang = "x" * 400
    meldungen = _melden([], [_job("a", "fertig", ergebnis=lang)])
    assert meldungen[0]["text"].endswith("…")
    assert len(meldungen[0]["text"]) < 200


def test_drei_laeufe_drei_verschiedene_saetze_mit_namen():
    """The measurement from the order: three at once, three sentences, and
    each says whose it was."""
    meldungen = _melden(
        [],
        [
            _job("a", "fertig", ergebnis="Bericht liegt im Ordner.", agent="Rechercheur"),
            _job("b", "fertig", ergebnis="Nichts Neues gefunden.", agent="Wächter"),
            _job("c", "gescheitert", grund="zeitgrenze", agent="Sammler"),
        ],
    )
    texte = [m["text"] for m in meldungen]
    assert len(texte) == 3
    assert len(set(texte)) == 3
    assert texte[0] == "Rechercheur · Bericht liegt im Ordner."
    assert texte[1] == "Wächter · Nichts Neues gefunden."
    assert texte[2].startswith("Sammler · ")


# --- Once, and only for a real ending --------------------------------------


def test_was_vor_dem_start_endete_ist_keine_neuigkeit():
    """Whatever ended before this window loaded is not announced — the same
    floor, and the same comparison, the dot on the rail keeps."""
    assert _melden([_job("a", "fertig", ergebnis="Fertig.", wann=FRUEHER)]) == []


def test_die_leere_startliste_verbraucht_die_geschichte_nicht():
    """The bug this floor replaced a "skip the first list" rule for.

    `zustand.auftraege` starts empty and the effect that feeds this module
    runs on mount, so the FIRST list handed over is that empty one — the
    rail's fetch answers a moment later. A rule that spends its one free
    pass on the empty list has none left for the job history, and every run
    that ended days ago arrives as news."""
    alt = [
        _job("alt1", "fertig", ergebnis="Gestern fertig.", wann=FRUEHER),
        _job("alt2", "gescheitert", grund="zeitgrenze", wann=FRUEHER),
    ]
    neu = _job("neu", "fertig", ergebnis="Eben fertig.")
    # Tick 1 is the empty state, tick 2 the first answer from the service.
    meldungen = _melden([], alt, [*alt, neu])
    assert [m["auftragId"] for m in meldungen] == ["neu"]


def test_dasselbe_ende_meldet_sich_nur_einmal():
    """The list is fetched every few seconds and carries the same finished
    run every time."""
    fertig = _job("a", "fertig", ergebnis="Fertig.")
    assert len(_melden([], [fertig], [fertig], [fertig])) == 1


def test_ein_laufender_auftrag_meldet_nichts():
    """The silence probe."""
    assert _melden([], [_job("a", "laeuft")], [_job("a", "wartet")]) == []


def test_eine_kette_meldet_einmal_nicht_je_glied():
    """Two links hand their work on, the third ends: one notice."""
    meldungen = _melden(
        [],
        [_job("a", "unterbrochen", grund="kontext_voll")],
        [
            _job("a", "unterbrochen", grund="kontext_voll"),
            _job("b", "unterbrochen", grund="anbieter_ausfall"),
        ],
        [
            _job("a", "unterbrochen", grund="kontext_voll"),
            _job("b", "unterbrochen", grund="anbieter_ausfall"),
            _job("c", "fertig", ergebnis="Doch noch fertig geworden."),
        ],
    )
    assert len(meldungen) == 1
    assert meldungen[0]["auftragId"] == "c"


def test_ein_neustart_abgeschnittener_lauf_meldet_sich():
    """The one interrupted run nobody handed on."""
    meldungen = _melden([], [_job("a", "unterbrochen", grund="dienst_neustart")])
    assert len(meldungen) == 1
    assert meldungen[0]["was"] == "fehler"


def test_ein_abbruch_sagt_nichts():
    """The user stopped that run a second ago; a notice about it is noise.
    The service leaves an abort out of its own announcements for the same
    reason (app/api/v1/auftraege.py)."""
    assert _melden([], [_job("a", "abgebrochen", grund="benutzer_abbruch")]) == []
