"""The chat's small history: every tool call, in the order it happened.

The bug this replaces was quiet and complete: a conversation spent reading
and writing files reported "no command has run yet". The module was looking
at shell runs only, and everything else the program can do was invisible in
the place built to show what it had done.

The ordering is the part worth testing hardest. Runs and calls come from two
sources with no shared clock — the messages carry the order, the runs are
threaded into it — and a mistake there does not look like an error, it looks
like a history of things that happened in the wrong sequence.
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
MODUL = FRONTEND / "src" / "lib" / "werkzeughistorie.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="no Node on this machine"
)


def _laufen(js: str):
    treiber = FRONTEND / "werkzeughistorie.pruefung.mjs"
    treiber.write_text(
        textwrap.dedent(
            """
            import { historie, kurzargument, leer } from %r
            const bericht = (() => {
            %s
            })()
            console.log(JSON.stringify(bericht))
            """
        )
        % ("./" + str(MODUL.relative_to(FRONTEND)), textwrap.indent(js, "  ")),
        encoding="utf-8",
    )
    try:
        lauf = subprocess.run(
            ["node", treiber.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60
        )
    finally:
        treiber.unlink(missing_ok=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-2000:]
    return json.loads(lauf.stdout.strip().splitlines()[-1])


def test_jeder_aufruf_bekommt_eine_zeile_egal_woher():
    """Built in, memory, or a server — the module used to see only one."""
    bericht = _laufen(
        """
        const nachrichten = [
          { werkzeuge: [
            { name: 'read_file', argumente: { path: 'app/main.py' } },
            { name: 'memory_save', server: 'memory', argumente: { text: 'etwas' } },
          ] },
          { stats: { werkzeuge: [
            { name: 'web_search', server: 'suche', argumente: { query: 'Wetter morgen' } },
          ] } },
        ]
        return historie(nachrichten, []).map((e) => [e.art, e.name, e.kurz])
        """
    )
    assert bericht == [
        ["aufruf", "read_file", "app/main.py"],
        ["aufruf", "memory_save", "etwas"],
        ["trennung", None, None],
        ["aufruf", "web_search", "Wetter morgen"],
    ]


def test_ein_shell_befehl_erscheint_als_lauf_und_nicht_doppelt():
    bericht = _laufen(
        """
        const nachrichten = [{ werkzeuge: [
          { name: 'read_file', argumente: { path: 'a.py' } },
          { name: 'run_command', argumente: { command: 'ls -F' } },
        ] }]
        const laeufe = [{ lauf: 1, befehl: 'ls -F', zustand: 'fertig' }]
        const eintraege = historie(nachrichten, laeufe)
        return {
          arten: eintraege.map((e) => e.art),
          namen: eintraege.map((e) => e.name ?? e.lauf.befehl),
        }
        """
    )
    assert bericht["arten"] == ["aufruf", "lauf"]
    assert bericht["namen"] == ["read_file", "ls -F"]


def test_die_reihenfolge_kommt_aus_dem_gespraech():
    """A run is threaded in where its call stands, not appended at the end."""
    bericht = _laufen(
        """
        const nachrichten = [
          { werkzeuge: [{ name: 'run_command', argumente: { command: 'erst' } }] },
          { werkzeuge: [{ name: 'read_file', argumente: { path: 'dann.py' } }] },
          { werkzeuge: [{ name: 'run_command', argumente: { command: 'zuletzt' } }] },
        ]
        const laeufe = [
          { lauf: 1, befehl: 'erst', zustand: 'fertig' },
          { lauf: 2, befehl: 'zuletzt', zustand: 'fertig' },
        ]
        return historie(nachrichten, laeufe).map((e) =>
          e.art === 'lauf' ? e.lauf.befehl : e.name,
        )
        """
    )
    assert bericht == ["erst", None, "read_file", None, "zuletzt"]


def test_ein_lauf_ohne_aufruf_geht_nicht_verloren():
    """The CLI module starts runs too — they happened, so they are shown."""
    bericht = _laufen(
        """
        const laeufe = [{ lauf: 7, befehl: 'aus der CLI', zustand: 'fertig' }]
        return historie([], laeufe).map((e) => [e.art, e.lauf.befehl])
        """
    )
    assert bericht == [["lauf", "aus der CLI"]]


def test_ein_shell_aufruf_ohne_lauf_faellt_auf_die_zeile_zurueck():
    """After a service restart the call is still in the chat, its output is not."""
    bericht = _laufen(
        """
        const nachrichten = [{ werkzeuge: [
          { name: 'run_command', argumente: { command: 'von gestern' } },
        ] }]
        return historie(nachrichten, []).map((e) => [e.art, e.name, e.kurz])
        """
    )
    assert bericht == [["aufruf", "run_command", "von gestern"]]


def test_die_leere_meldung_gilt_nur_wenn_wirklich_nichts_da_ist():
    bericht = _laufen(
        """
        return {
          nichts: leer([], []),
          nur_aufruf: leer([{ werkzeuge: [{ name: 'read_file', argumente: {} }] }], []),
          nur_lauf: leer([], [{ lauf: 1, befehl: 'x', zustand: 'fertig' }]),
        }
        """
    )
    assert bericht["nichts"] is True
    assert bericht["nur_aufruf"] is False
    assert bericht["nur_lauf"] is False


def test_das_kurzargument_sagt_worum_es_ging():
    bericht = _laufen(
        """
        return {
          pfad: kurzargument({ path: 'app/main.py' }),
          zahl: kurzargument({ zeilen: 42 }),
          lang: kurzargument({ text: 'x'.repeat(200) }).length,
          leer: kurzargument({}),
          keins: kurzargument(null),
          umbruch: kurzargument({ text: 'zwei\\n  zeilen' }),
        }
        """
    )
    assert bericht["pfad"] == "app/main.py"
    assert bericht["zahl"] == "42"
    # Long enough to recognise, short enough not to wrap.
    assert bericht["lang"] == 61
    assert bericht["leer"] == ""
    assert bericht["keins"] == ""
    assert bericht["umbruch"] == "zwei zeilen"


def test_der_ausgang_wird_mitgefuehrt():
    bericht = _laufen(
        """
        const nachrichten = [{ werkzeuge: [
          { name: 'read_file', argumente: {}, fehlgeschlagen: true },
          { name: 'write_file', argumente: {} },
        ] }]
        return historie(nachrichten, []).map((e) => e.fehlgeschlagen)
        """
    )
    assert bericht == [True, False]


# --- Two kinds of run in one list -----------------------------------------
#
# The merge brought drawing jobs into the same run list without telling the
# pairing about them. `shift()` then handed the next run to whichever shell
# call asked first, and a picture ended up filed under a command.


def test_ein_bildlauf_wird_keinem_shell_befehl_untergeschoben():
    """The regression.

    The picture was drawn first, so it stands first in the run list. The
    shell call must still get ITS run — not the picture — and the picture
    must still appear.
    """
    bericht = _laufen(
        """
        const nachrichten = [{ werkzeuge: [
          { name: 'run_command', argumente: { command: 'ls -F' } },
        ] }]
        const laeufe = [
          { lauf: 1, art: 'bild', befehl: 'ein Fuchs im Schnee', zustand: 'fertig' },
          { lauf: 2, art: 'befehl', befehl: 'ls -F', zustand: 'fertig' },
        ]
        return historie(nachrichten, laeufe).map((e) => [e.lauf.art, e.lauf.befehl])
        """
    )
    assert bericht == [
        ["befehl", "ls -F"],
        ["bild", "ein Fuchs im Schnee"],
    ]


def test_ein_lauf_ohne_art_gilt_weiter_als_befehl():
    """Runs stored before the kind existed must not become orphans."""
    bericht = _laufen(
        """
        const nachrichten = [{ werkzeuge: [
          { name: 'run_command', argumente: { command: 'ls' } },
        ] }]
        const laeufe = [{ lauf: 1, befehl: 'ls', zustand: 'fertig' }]
        const eintraege = historie(nachrichten, laeufe)
        return { anzahl: eintraege.length, befehl: eintraege[0].lauf.befehl }
        """
    )
    assert bericht == {"anzahl": 1, "befehl": "ls"}


# --- A divider at the boundary between two messages ----------


def test_trennung_steht_zwischen_zwei_nachrichten():
    bericht = _laufen(
        """
        const nachrichten = [
          { werkzeuge: [{ name: 'read_file', argumente: { path: 'a.py' } }] },
          { werkzeuge: [{ name: 'read_file', argumente: { path: 'b.py' } }] },
        ]
        return historie(nachrichten, []).map((e) => e.art)
        """
    )
    assert bericht == ["aufruf", "trennung", "aufruf"]


def test_keine_trennung_innerhalb_einer_nachricht():
    bericht = _laufen(
        """
        const nachrichten = [
          { werkzeuge: [
            { name: 'read_file', argumente: { path: 'a.py' } },
            { name: 'read_file', argumente: { path: 'b.py' } },
          ] },
        ]
        return historie(nachrichten, []).map((e) => e.art)
        """
    )
    assert bericht == ["aufruf", "aufruf"]


def test_keine_trennung_vor_dem_allerersten_eintrag():
    bericht = _laufen(
        """
        const nachrichten = [{ werkzeuge: [{ name: 'read_file', argumente: { path: 'a.py' } }] }]
        return historie(nachrichten, []).map((e) => e.art)
        """
    )
    assert bericht == ["aufruf"]


def test_eine_leere_nachricht_dazwischen_erzeugt_keine_luecke():
    """A message that made no calls of its own is not a boundary."""
    bericht = _laufen(
        """
        const nachrichten = [
          { werkzeuge: [{ name: 'read_file', argumente: { path: 'a.py' } }] },
          { werkzeuge: [] },
          { werkzeuge: [{ name: 'read_file', argumente: { path: 'b.py' } }] },
        ]
        return historie(nachrichten, []).map((e) => e.art)
        """
    )
    assert bericht == ["aufruf", "trennung", "aufruf"]


def test_die_leere_meldung_uebersieht_die_trennung_nicht():
    """A history that is only dividers, never real calls, cannot happen —
    but ``leer`` still must not be fooled by one standing alone."""
    bericht = _laufen(
        """
        return leer([{ werkzeuge: [] }], [])
        """
    )
    assert bericht is True


def test_ein_bild_ohne_befehl_daneben_steht_trotzdem_da():
    bericht = _laufen(
        """
        const laeufe = [{ lauf: 1, art: 'bild', befehl: 'ein Hafen', zustand: 'fertig' }]
        return historie([], laeufe).map((e) => [e.art, e.lauf.art])
        """
    )
    assert bericht == [["lauf", "bild"]]


def test_die_zeile_behaelt_das_volle_argument_und_das_ergebnis():
    """The refused download used to look like a crash: the address cut at
    sixty characters, the error nowhere. Not hidden — gone. The line now
    carries the full arguments and the result, so a click can show them."""
    bericht = _laufen(
        """
        const adresse = 'https://beispiel.test/api/download/models/999999?type=Model&format=SafeTensor&size=full&fp=fp16&token=xyz'
        const nachrichten = [
          { stats: { werkzeuge: [{
            name: 'run_command',
            argumente: { command: 'curl -L -o modell.safetensors "' + adresse + '"' },
            ergebnis: 'curl: (22) The requested URL returned error: 401\\n[exit code 22]',
            fehlgeschlagen: true,
          }] } },
        ]
        const zeile = historie(nachrichten, [])[0]
        return {
          kurz: zeile.kurz.length,
          befehl: zeile.argumente.command,
          ergebnis: zeile.ergebnis,
          fehlgeschlagen: zeile.fehlgeschlagen,
        }
        """
    )
    assert bericht["kurz"] == 61  # the short line stays short (60 + ellipsis)
    assert "token=xyz" in bericht["befehl"]  # the full address survives
    assert "401" in bericht["ergebnis"]  # and so does the error
    assert bericht["fehlgeschlagen"] is True


def test_der_deckel_haelt_argument_und_ergebnis_unter_der_grenze():
    """A `find /` must not sit whole in every line — the lid is the same
    20,000 characters the shell cuts its own output at."""
    bericht = _laufen(
        """
        const lang = 'x'.repeat(30000)
        const nachrichten = [
          { stats: { werkzeuge: [{
            name: 'run_command',
            argumente: { command: lang },
            ergebnis: lang,
          }] } },
        ]
        const zeile = historie(nachrichten, [])[0]
        return { befehl: zeile.argumente.command.length, ergebnis: zeile.ergebnis.length }
        """
    )
    assert bericht["befehl"] == 20_001  # 20,000 plus the ellipsis
    assert bericht["ergebnis"] == 20_001


def test_laufend_und_alt_bleiben_unterscheidbar():
    """null means "still running", a missing field means an old message that
    never stored a result — the opened line says a different sentence for
    each, so the shapes must survive the pass-through."""
    bericht = _laufen(
        """
        const nachrichten = [
          { werkzeuge: [
            { name: 'web_search', argumente: { query: 'x' }, ergebnis: null },
            { name: 'web_search', argumente: { query: 'y' } },
          ] },
        ]
        const zeilen = historie(nachrichten, [])
        return [zeilen[0].ergebnis === null, 'ergebnis' in zeilen[1] && zeilen[1].ergebnis === undefined]
        """
    )
    assert bericht == [True, True]


def test_die_berichtszeile_eines_hintergrundlaufs_zaehlt_nicht_als_aufruf():
    """A finished background run's report row carries the call a second
    time, for the model. The run is in the list already, claimed by the call
    that started it — the report's copy must not put the command in twice."""
    bericht = _laufen(
        """
        const nachrichten = [
          { werkzeuge: [{ name: 'run_command', argumente: { command: 'npm install', background: true }, lauf_nummer: 1 }] },
          { art: 'werkzeugmeldung', stats: { werkzeuge: [
            { name: 'run_command', argumente: { command: 'npm install', background: true }, lauf_nummer: 1, ergebnis: 'added 70 packages' },
          ] } },
        ]
        const laeufe = [{ lauf: 1, befehl: 'npm install', hintergrund: true, zustand: 'fertig' }]
        return { arten: historie(nachrichten, laeufe).map((e) => e.art) }
        """
    )
    assert bericht["arten"] == ["lauf"]


def test_ein_abgelehnter_befehl_nimmt_dem_echten_nicht_seinen_lauf():
    """A shell call refused before it started never became a run. Paired
    by position it took the next real run's output, and the real call —
    the one carrying the run's number — fell to a bare line under it."""
    bericht = _laufen(
        """
        const nachrichten = [
          { werkzeuge: [{ name: 'run_command', argumente: { command: 'sleep 20' }, fehlgeschlagen: true, ergebnis: 'no shared folder' }] },
          { werkzeuge: [
            { name: 'list_dir', argumente: { path: '.' }, fehlgeschlagen: true },
            { name: 'run_command', argumente: { command: 'sleep 20' }, lauf_nummer: 1 },
          ] },
        ]
        const laeufe = [{ lauf: 1, befehl: 'sleep 20', zustand: 'fertig' }]
        const eintraege = historie(nachrichten, laeufe).filter((e) => e.art !== 'trennung')
        return { arten: eintraege.map((e) => e.art), namen: eintraege.map((e) => e.name ?? e.lauf.befehl) }
        """
    )
    assert bericht["arten"] == ["aufruf", "aufruf", "lauf"]
    assert bericht["namen"] == ["run_command", "list_dir", "sleep 20"]


def test_alte_zeilen_ohne_nummern_werden_weiter_nach_reihenfolge_gepaart():
    bericht = _laufen(
        """
        const nachrichten = [{ werkzeuge: [
          { name: 'run_command', argumente: { command: 'ls' } },
          { name: 'run_command', argumente: { command: 'pwd' } },
        ] }]
        const laeufe = [{ lauf: 1, befehl: 'ls', zustand: 'fertig' }, { lauf: 2, befehl: 'pwd', zustand: 'fertig' }]
        return { arten: historie(nachrichten, laeufe).map((e) => e.art) }
        """
    )
    assert bericht["arten"] == ["lauf", "lauf"]
