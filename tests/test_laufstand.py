"""One rule, two displays — and the guard that they cannot come apart.

A run whose work was handed on to a continuation is told apart from a run a
service restart merely cut off by one expression (``weitergereicht``,
frontend/src/lib/laufstand.js). The reports list
(frontend/src/teile/ModulAgenten.svelte) and the dot on the rail
(frontend/src/lib/agentenampel.svelte.js) both read it, and they mean
different things by it: the list folds a handed-on link away only when
something newer of the same work exists, the dot skips every handed-on run
outright.

They disagreed about one run before, each with a copy of the expression and
a test of its own — and either test would have stayed green while the other
side changed. That is what this file is for. It is the only place that puts
the two side by side:

* the rule itself, run in node,
* the dot, run in node,
* the list's block, run in node,

all three over the same rows, and all three have to give the same answer
about what is handed on. Widen one side to a set of reasons and this goes
red, whichever side it was.

And one plain reading of the source on top, because "there is exactly one
copy" is a claim about the files and cannot be measured by running them.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

# Borrowed rather than copied — running the dot and running the list is
# exactly what those two files already do, and a second way of doing it here
# is the duplication this whole file exists to prevent.
from tests.test_agentenampel import _lauf as punktfarbe_fuer
from tests.test_anzeigefunde import _zeilen as zeilen_fuer

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
LAUFSTAND = FRONTEND / "src" / "lib" / "laufstand.js"
MODUL_AGENTEN = FRONTEND / "src" / "teile" / "ModulAgenten.svelte"
AMPEL = FRONTEND / "src" / "lib" / "agentenampel.svelte.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

# Every row an ending can be, and the two the whole distinction turns on.
# Each carries a result, so the list's other condition ("has something to
# show for itself") is true for all of them and the ONLY thing that can move
# an answer here is the rule under test.
ZEILEN = [
    ("unterbrochen", "kontext_voll", True),
    ("unterbrochen", "anbieter_ausfall", True),
    ("unterbrochen", "zeitgrenze", True),
    ("unterbrochen", None, True),
    ("unterbrochen", "dienst_neustart", False),
    ("gescheitert", "kontext_voll", False),
    ("gescheitert", "anbieter_ausfall", False),
    ("abgebrochen", "benutzer_abbruch", False),
    ("fertig", None, False),
]

FRUEH = "2026-09-01T10:00:00+00:00"
SPAET = "2026-09-01T12:00:00+00:00"


def _zeile(zustand, grund, *, kennung="l1", werk="w", wann=FRUEH) -> dict:
    return {
        "id": kennung,
        "state": zustand,
        "end_reason": grund,
        "result": "Bericht",
        "work_id": werk,
        "updated_at": wann,
    }


def _regel_sagt(zeilen: list[dict]) -> list[bool]:
    """The shared rule, run on its own.

    It imports nothing, so it needs no node_modules beside it and the driver
    lives outside the repository — nothing an abort could leave behind."""
    quelle = LAUFSTAND.read_text(encoding="utf-8").replace(
        "export function weitergereicht", "function weitergereicht"
    )
    with tempfile.TemporaryDirectory(prefix="laufstand-") as ordner:
        treiber = Path(ordner) / "pruefung.mjs"
        treiber.write_text(
            quelle
            + textwrap.dedent(
                """
                const zeilen = %s
                console.log(JSON.stringify(zeilen.map(weitergereicht)))
                """
            )
            % json.dumps(zeilen),
            encoding="utf-8",
        )
        lauf = subprocess.run(
            ["node", treiber.name], cwd=ordner, capture_output=True, text=True, timeout=60
        )
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-2000:]
    return json.loads(lauf.stdout.strip().splitlines()[-1])


def _die_liste_reicht_weiter(zustand, grund) -> bool:
    """What the reports list makes of one row, read off its behaviour.

    A handed-on link steps aside as soon as anything newer of the same work
    exists — so put a newer run of the same work beside it and see whether
    the row survives. The newer one is 'laeuft', which produces no row of its
    own, so what comes back is about the row under test and nothing else."""
    zeilen = zeilen_fuer(
        [
            {
                "id": "neuer", "state": "laeuft", "end_reason": None,
                "result": None, "work_id": "w",
            },
            _zeile(zustand, grund, wann=FRUEH),
        ]
    )
    return zeilen == []


def _die_ampel_reicht_weiter(zustand, grund) -> bool:
    """And what the dot makes of the same row. It skips every handed-on run,
    so a row it skips leaves the rail with nothing to report at all."""
    return punktfarbe_fuer([_zeile(zustand, grund, wann=SPAET)]) == "still"


@pytest.mark.parametrize("zustand,grund,weitergereicht", ZEILEN)
def test_beide_anzeigen_lesen_dieselbe_regel(zustand, grund, weitergereicht):
    """The guard the two displays did not have. Whatever a run ended as, the
    rule, the list and the dot answer the same question the same way — and
    changing one of the three alone turns this red.

    'unterbrochen' with any reason but a service restart is handed on; a
    restart cut the run off and handed it nowhere; nothing else is
    'unterbrochen' at all."""
    assert _regel_sagt([_zeile(zustand, grund)]) == [weitergereicht]
    assert _die_liste_reicht_weiter(zustand, grund) is weitergereicht
    assert _die_ampel_reicht_weiter(zustand, grund) is weitergereicht


def test_die_regel_steht_an_genau_einer_stelle():
    """The one claim that has to be read rather than run: there is no second
    copy. Both displays import the rule and neither declares one of its own —
    which is what keeps the test above from measuring one file twice.

    Until cefa779 the expression stood in ModulAgenten.svelte alone; that
    commit wrote it a second time into the dot, with a guard on each copy, so
    that widening one of them left both guards green. Reading the two files
    is the only way to see that state coming back."""
    for datei in (MODUL_AGENTEN, AMPEL):
        quelle = datei.read_text(encoding="utf-8")
        assert "laufstand.js" in quelle, f"{datei.name} does not import the rule"
        assert "function weitergereicht" not in quelle, (
            f"{datei.name} declares the rule itself — there are two copies again"
        )


def test_die_liste_wendet_sie_bedingt_an_die_ampel_nicht():
    """The other half of "one rule, two uses": what is shared is the
    distinction, not what is done with it, and that difference is meant.

    A handed-on link with nothing newer behind it is the last of its chain,
    and the list keeps it — that is the row carrying the reason. The dot
    skips it all the same, because a chain still running is no ending it
    could report."""
    letztes_glied = _zeile("unterbrochen", "kontext_voll", kennung="l1", wann=SPAET)

    assert zeilen_fuer([letztes_glied]) == ["l1"]
    assert punktfarbe_fuer([letztes_glied]) == "still"
