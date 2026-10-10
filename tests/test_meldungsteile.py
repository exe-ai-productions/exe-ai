"""A notice knows which of its words were put in a moment ago.

`t()` hands back one finished sentence, and with it the answer to "which of
these words is a file name and which is the sentence around it" is gone. A
display cannot work that out afterwards without guessing — a value can be a
common word, a single digit, or a path that repeats the sentence's own
wording — so the splitting happens where the template still exists.

Measured against the shipped module, compiled the way the browser gets it.
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
QUELLE = FRONTEND / "src"
MODUL = QUELLE / "lib" / "texte.svelte.js"

node_da = pytest.mark.skipif(
    not (FRONTEND / "node_modules" / "svelte").is_dir(),
    reason="svelte is not installed",
)

# The module under test imports `api.js`; the folder gets the REAL file, not
# a hand-written stand-in. A stand-in only has to name the exports — it would
# keep this test green even if api.js lost one of them, and the proof would be
# about the copy instead of the shipped module. The browser globals in api.js
# all sit behind `typeof window`.
def _api_kopie(ordner: Path) -> None:
    (ordner / "api.mjs").write_text(
        (QUELLE / "lib" / "api.js").read_text(encoding="utf-8"), encoding="utf-8"
    )


@contextmanager
def _pruefordner():
    """A folder of this run's own, under node_modules so the compiled module
    can resolve `svelte/internal/client` by walking up — the same stand
    tests/test_meldewesen.py builds, and for the same reason."""
    ordner = FRONTEND / "node_modules" / f".pruefstand-teile-{uuid4().hex}"
    ordner.mkdir(parents=True)
    try:
        yield ordner
    finally:
        shutil.rmtree(ordner, ignore_errors=True)


def _teile(vorlage: str, werte: dict | None) -> list[dict]:
    """Run the shipped splitter against one template."""
    with _pruefordner() as ordner:
        gebaut = ordner / "gebaut.mjs"
        _api_kopie(ordner)
        treiber = ordner / "pruefung.mjs"
        treiber.write_text(
            textwrap.dedent(
                """
                import { compileModule } from 'svelte/compiler'
                import { readFileSync, writeFileSync } from 'fs'
                const quelle = readFileSync(%r, 'utf-8')
                const gebaut = compileModule(quelle, {
                  filename: 'texte.svelte.js', generate: 'client',
                })
                writeFileSync(%r, gebaut.js.code.replace('./api.js', './api.mjs'))
                const m = await import('./gebaut.mjs')
                // One entry, put in by hand: what is measured here is the
                // splitting, not how a catalogue is loaded.
                m.texte.katalog = { probe: %s }
                console.log('---BERICHT---' + JSON.stringify(m.teile('probe', %s)))
                """
            )
            % (str(MODUL), str(gebaut), json.dumps(vorlage), json.dumps(werte)),
            encoding="utf-8",
        )
        ergebnis = subprocess.run(
            ["node", treiber.name], cwd=ordner, capture_output=True, text=True, encoding="utf-8", timeout=120
        )
    assert ergebnis.returncode == 0, (ergebnis.stdout + ergebnis.stderr)[-2000:]
    marke = "---BERICHT---"
    assert marke in ergebnis.stdout, ergebnis.stdout[-2000:]
    return json.loads(ergebnis.stdout.split(marke, 1)[1].strip())


@node_da
def test_ein_satz_ohne_klammern_ist_ein_stueck():
    """Nothing was put in, so nothing is set apart."""
    assert _teile("Gespeichert", None) == [{"fest": "Gespeichert"}]


@node_da
def test_der_wert_steht_fuer_sich():
    assert _teile("{name} wird geschrieben", {"name": "write_file"}) == [
        {"wert": "write_file"},
        {"fest": " wird geschrieben"},
    ]


@node_da
def test_zwei_werte_in_einem_satz():
    """The one sentence in the house that carries two — and the reason the
    splitting cannot simply search for the values: 'Notizen' is a word the
    sentence could have contained on its own."""
    assert _teile(
        "{ordner}: exe.md hat {zeichen} Zeichen und nimmt Platz.",
        {"ordner": "Notizen", "zeichen": "4504"},
    ) == [
        {"wert": "Notizen"},
        {"fest": ": exe.md hat "},
        {"wert": "4504"},
        {"fest": " Zeichen und nimmt Platz."},
    ]


@node_da
def test_ein_wert_der_selbst_klammern_traegt_wird_nicht_erneut_geteilt():
    """A path or a name may contain braces of its own. What was put in is
    never looked at again — otherwise the sentence would be split inside a
    value the user typed."""
    assert _teile("Abgelegt unter {pfad}", {"pfad": "/tmp/{roh}/a.md"}) == [
        {"fest": "Abgelegt unter "},
        {"wert": "/tmp/{roh}/a.md"},
    ]


@node_da
def test_ein_platzhalter_ohne_wert_bleibt_sichtbar_stehen():
    """The same loud failure `t()` gives for a missing key: the brace stays
    on screen rather than leaving a hole nobody notices."""
    assert _teile("Höchstens {anzahl} Bilder", None) == [
        {"fest": "Höchstens "},
        {"fest": "{anzahl}"},
        {"fest": " Bilder"},
    ]


@node_da
def test_eine_null_ist_ein_wert_und_kein_fehlender():
    """0 and '' are values somebody passed. Only undefined and null are
    'nothing was handed over' — a count of zero must not print its brace."""
    assert _teile("{anzahl} Bilder", {"anzahl": 0}) == [
        {"wert": "0"},
        {"fest": " Bilder"},
    ]


@node_da
def test_ein_unbekannter_schluessel_kommt_als_er_selbst_zurueck():
    """What `t()` does for a missing key, in pieces."""
    with _pruefordner() as ordner:
        gebaut = ordner / "gebaut.mjs"
        _api_kopie(ordner)
        treiber = ordner / "pruefung.mjs"
        treiber.write_text(
            textwrap.dedent(
                """
                import { compileModule } from 'svelte/compiler'
                import { readFileSync, writeFileSync } from 'fs'
                const quelle = readFileSync(%r, 'utf-8')
                const gebaut = compileModule(quelle, {
                  filename: 'texte.svelte.js', generate: 'client',
                })
                writeFileSync(%r, gebaut.js.code.replace('./api.js', './api.mjs'))
                const m = await import('./gebaut.mjs')
                m.texte.katalog = {}
                console.log('---BERICHT---' + JSON.stringify(m.teile('no.such.entry')))
                """
            )
            % (str(MODUL), str(gebaut)),
            encoding="utf-8",
        )
        ergebnis = subprocess.run(
            ["node", treiber.name], cwd=ordner, capture_output=True, text=True, encoding="utf-8", timeout=120
        )
    assert ergebnis.returncode == 0, (ergebnis.stdout + ergebnis.stderr)[-2000:]
    antwort = json.loads(ergebnis.stdout.split("---BERICHT---", 1)[1].strip())
    assert antwort == [{"fest": "no.such.entry"}]


@node_da
def test_ein_wert_wird_nie_ein_zweites_mal_eingesetzt():
    """`t()` substitutes value after value into the growing string, so a value
    carrying another key's brace gets walked into on the next pass. The pieces
    never look at what was put in — and the notice builds its sentence from
    the pieces, so the two cannot say different things."""
    assert _teile(
        "Abgelegt unter {pfad}",
        {"pfad": "/tmp/{name}/a.md", "name": "geheim"},
    ) == [
        {"fest": "Abgelegt unter "},
        {"wert": "/tmp/{name}/a.md"},
    ]


def test_der_toast_baut_seinen_satz_aus_den_stuecken():
    """Two sources for one sentence is two sentences waiting to differ:
    `meldeText` joins the pieces rather than asking the catalogue twice."""
    quelle = (QUELLE / "lib" / "meldewesen.svelte.js").read_text(encoding="utf-8")
    assert "teile(pfad, werte)" in quelle, "meldeText does not split the template"
    assert "stueck.wert ?? stueck.fest" in quelle, (
        "meldeText builds its text some other way than from the pieces"
    )


# --- The notice actually uses it -------------------------------------------


def test_der_toast_zeichnet_die_gesetzten_teile_eigens():
    """A rule nobody applies is a rule that does not exist: the notice has to
    ask for the pieces and mark the put-in ones."""
    quelle = (QUELLE / "teile" / "Meldungen.svelte").read_text(encoding="utf-8")
    assert "teile(" in quelle, "the notice never asks for the pieces"
    assert 'class="gesetzt"' in quelle, "nothing marks what was put in"
    # The put-in part reads in the house face with even digits — one face
    # for data and paths — and stands apart by its weight.
    gesetzt = quelle.split(".gesetzt {", 1)[1].split("}", 1)[0]
    assert "var(--schrift)" in gesetzt, "the put-in part left the house face"
    assert "tabular-nums" in gesetzt, "the put-in part lost its even digits"
    assert "font-weight: 600" in gesetzt, "the put-in part no longer stands apart"


def test_jede_meldung_mit_platzhalter_nennt_ihren_schluessel():
    """Every notice whose catalogue text carries a brace must go through
    `meldeText`, or its seams are lost before the notice ever sees it.

    Measured against the catalogue rather than against a list written here:
    a new sentence with a placeholder is caught the day it is added.
    """
    katalog = json.loads((WURZEL / "app" / "locales" / "de.json").read_text("utf-8"))

    def flach(knoten, praefix=""):
        for name, wert in knoten.items():
            pfad = f"{praefix}{name}"
            if isinstance(wert, dict):
                yield from flach(wert, f"{pfad}.")
            elif isinstance(wert, str):
                yield pfad, wert

    mit_klammer = {pfad for pfad, wert in flach(katalog) if "{" in wert}

    saeumig = []
    for pfad in sorted(QUELLE.rglob("*")):
        if pfad.suffix not in (".svelte", ".js") or not pfad.is_file():
            continue
        quelle = pfad.read_text(encoding="utf-8")
        for zeile in quelle.splitlines():
            # A line that only TALKS about the call — a comment, a docstring
            # example — is not a caller. Without this the module that
            # documents the rule fails its own guard.
            nackt = zeile.strip()
            if nackt.startswith(("*", "//", "/*", "#")):
                continue
            if "melde(t(" not in zeile.replace(" ", ""):
                continue
            for schluessel in mit_klammer:
                if f"'{schluessel}'" in zeile:
                    saeumig.append(f"{pfad.relative_to(QUELLE)}: {schluessel}")
    assert not saeumig, (
        "these notices hand over a finished sentence although their text has a "
        "placeholder — use meldeText: " + ", ".join(saeumig)
    )
