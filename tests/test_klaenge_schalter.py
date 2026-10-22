"""The sound of each occurrence has a switch of its own, and the window
asks the same three things the service does: the main switch, the volume,
and the switch of that sound (frontend/src/lib/klaenge.svelte.js).

The shipped module is compiled and run in node with only what it talks to
replaced: the settings calls and the audio element.
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

# The file name the test harness gives the compiled module: what a sound is asked
# for under, behind its address.
BUNDLE = "gebaut.mjs"

WURZEL = Path(__file__).resolve().parents[1]
FRONTEND = WURZEL / "frontend"
MODUL = FRONTEND / "src" / "lib" / "klaenge.svelte.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)


@contextmanager
def _pruefordner():
    ordner = FRONTEND / "node_modules" / f".pruefstand-klaenge-{uuid4().hex}"
    ordner.mkdir(parents=True)
    try:
        yield ordner
    finally:
        shutil.rmtree(ordner, ignore_errors=True)


def _lauf(js: str, *, gespeichert: dict | None = None) -> dict:
    """Run `js` against the shipped module. `gespeichert` is what the
    settings answer for the key; the script sees `m` (the module), `gespielt`
    (the files played, in order) and `gesetzt` (the objects written back)."""
    with _pruefordner() as ordner:
        gebaut = ordner / "gebaut.mjs"
        (ordner / "api.mjs").write_text(
            "export const gesetzt = []\n"
            "export const api = {\n"
            "  einstellungAufgeloest: async () => (%s),\n"
            "  einstellungSetzen: async (b, k, wert) => { gesetzt.push(wert) },\n"
            "}\n" % json.dumps({"wert": gespeichert} if gespeichert is not None else None),
            encoding="utf-8",
        )
        treiber = ordner / "pruefung.mjs"
        treiber.write_text(
            textwrap.dedent(
                """
                import { compileModule } from 'svelte/compiler'
                import { readFileSync, writeFileSync } from 'fs'
                const gespielt = []
                globalThis.document = { hasFocus: () => false, visibilityState: 'hidden' }
                globalThis.Audio = class {
                  constructor(adresse) { this.adresse = adresse }
                  pause() {}
                  play() { gespielt.push(this.adresse); return Promise.resolve() }
                }
                const gebaut = compileModule(readFileSync(%r, 'utf-8'), {
                  filename: 'klaenge.svelte.js', generate: 'client',
                })
                writeFileSync(%r, gebaut.js.code.replace('./api.js', './api.mjs'))
                const m = await import('./gebaut.mjs')
                const { gesetzt } = await import('./api.mjs')
                let bericht = {}
                %s
                console.log('---BERICHT---' + JSON.stringify({ ...bericht, gespielt, gesetzt }))
                """
            )
            % (str(MODUL), str(gebaut), js),
            encoding="utf-8",
        )
        ergebnis = subprocess.run(
            ["node", treiber.name], cwd=ordner, capture_output=True, text=True, encoding="utf-8", timeout=120
        )
    assert ergebnis.returncode == 0, (ergebnis.stdout + ergebnis.stderr)[-2000:]
    return json.loads(ergebnis.stdout.split("---BERICHT---", 1)[1].strip())


def test_a_sound_is_asked_for_under_the_name_of_the_bundle_it_came_in():
    """A new build brings a new address for every sound: an old copy of the
    file kept under the same name cannot be what plays after an update."""
    bericht = _lauf("m.klingen('fertig')")
    assert bericht["gespielt"] == ["/klaenge/fertig.wav?v=" + BUNDLE]


def test_each_sound_plays_its_own_file():
    bericht = _lauf("for (const name of m.KLAENGE) m.klingen(name)")
    assert bericht["gespielt"] == [
        "/klaenge/fertig.wav?v=" + BUNDLE, "/klaenge/wartet.wav?v=" + BUNDLE, "/klaenge/fehler.wav?v=" + BUNDLE,
        "/klaenge/agent-cronjob.wav?v=" + BUNDLE,
    ]


def test_a_switched_off_sound_does_not_silence_the_others():
    bericht = _lauf(
        "m.klangwahl.ton.agent_cronjob = false\n"
        "for (const name of m.KLAENGE) m.klingen(name)"
    )
    assert bericht["gespielt"] == [
        "/klaenge/fertig.wav?v=" + BUNDLE, "/klaenge/wartet.wav?v=" + BUNDLE, "/klaenge/fehler.wav?v=" + BUNDLE,
    ]


def test_the_main_switch_and_volume_zero_silence_everything():
    aus = _lauf("m.klangwahl.aus = true\nm.klingen('fertig')")
    assert aus["gespielt"] == []
    leise = _lauf("m.pegelSetzen(0)\nm.klingen('fertig')")
    assert leise["gespielt"] == []


def test_the_test_button_asks_no_switch():
    """Pressing the test button is asking to hear it now."""
    bericht = _lauf("m.klangwahl.ton.fehler = false\nm.probehoeren('fehler')")
    assert bericht["gespielt"] == ["/klaenge/fehler.wav?v=" + BUNDLE]


def test_stored_switches_are_read_and_all_four_written():
    bericht = _lauf(
        "await m.klangwahlLaden()\n"
        "bericht = { ton: { ...m.klangwahl.ton } }\n"
        "await m.setSound('wartet', false)",
        gespeichert={"an": True, "pegel": 55, "ton_agent_cronjob": False, "ton_fehler": True},
    )
    assert bericht["ton"] == {"fertig": True, "wartet": True, "fehler": True, "agent_cronjob": False}
    geschrieben = bericht["gesetzt"][-1]
    assert geschrieben["ton_wartet"] is False
    assert geschrieben["ton_agent_cronjob"] is False
    assert geschrieben["ton_fertig"] is True and geschrieben["ton_fehler"] is True
    assert geschrieben["pegel"] == 55


def test_an_old_stored_state_without_the_new_fields_loads_as_before():
    bericht = _lauf(
        "await m.klangwahlLaden()\nbericht = { ton: { ...m.klangwahl.ton }, aus: m.klangwahl.aus }",
        gespeichert={"an": False, "pegel": 10, "nur_hintergrund": False},
    )
    assert bericht["ton"] == {"fertig": True, "wartet": True, "fehler": True, "agent_cronjob": True}
    assert bericht["aus"] is True
