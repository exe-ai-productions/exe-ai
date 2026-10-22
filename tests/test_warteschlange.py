"""The message queue, run for real instead of read.

The queue decides what happens to a message that was typed while an answer
was still running — whether it goes out by itself afterwards, whether it
stays put after a failed run, whether the ``✕`` really takes it out. Those
are three sentences of behaviour, and a test that only greps the source
would confirm the sentences exist, not that they hold.

So the module is compiled with Svelte's own compiler and executed in Node:
``$state`` works outside a browser, and the queue is plain data. What runs
here is the same file the interface imports, not a copy of its logic.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
MODUL = FRONTEND / "src" / "lib" / "warteschlange.svelte.js"


def _laufen(js: str) -> dict:
    """Compile the queue module and run `js` against it, return its report."""
    treiber = FRONTEND / "warteschlange.pruefung.mjs"
    gebaut = FRONTEND / "warteschlange.gebaut.mjs"
    treiber.write_text(
        textwrap.dedent(
            """
            import { compileModule } from 'svelte/compiler'
            import { readFileSync, writeFileSync } from 'fs'
            const quelle = readFileSync(%r, 'utf-8')
            const gebaut = compileModule(quelle, {
              filename: 'warteschlange.svelte.js', generate: 'client',
            })
            writeFileSync(%r, gebaut.js.code)
            const w = await import(%r)
            const bericht = await (async () => {
            %s
            })()
            console.log('---BERICHT---' + JSON.stringify(bericht))
            """
        )
        % (str(MODUL), str(gebaut), "./" + gebaut.name, textwrap.indent(js, "  ")),
        encoding="utf-8",
    )
    try:
        lauf = subprocess.run(
            ["node", treiber.name],
            cwd=FRONTEND,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        treiber.unlink(missing_ok=True)
        gebaut.unlink(missing_ok=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-2000:]
    marke = "---BERICHT---"
    assert marke in lauf.stdout, lauf.stdout[-2000:]
    return json.loads(lauf.stdout.split(marke, 1)[1].strip())


pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)


def test_die_schlange_gibt_der_reihe_nach_heraus():
    """First in, first out — and per chat, not across all of them."""
    bericht = _laufen(
        """
        w.einreihen('a', { inhalt: 'eins' })
        w.einreihen('b', { inhalt: 'fremd' })
        w.einreihen('a', { inhalt: 'zwei' })
        return {
          erste: w.ausreihen('a').inhalt,
          zweite: w.ausreihen('a').inhalt,
          dann: w.ausreihen('a'),
          fremd_bleibt: w.fuerChat('b').map((e) => e.inhalt),
        }
        """
    )
    assert bericht["erste"] == "eins"
    assert bericht["zweite"] == "zwei"
    assert bericht["dann"] is None
    assert bericht["fremd_bleibt"] == ["fremd"]


def test_the_line_never_holds():
    """A failed run holds nothing: its messages stay due and go on like
    after a clean end. The hold itself does not exist any more."""
    bericht = _laufen(
        """
        w.einreihen('a', { inhalt: 'eins' })
        w.einreihen('a', { inhalt: 'zwei' })
        return {
          hold_exists: [typeof w.anhalten, typeof w.loesen, typeof w.haelt],
          field: w.fuerChat('a').some((e) => 'haelt' in e),
          due: w.awaitingInterrupt('a').map((e) => e.inhalt),
          first: w.ausreihen('a').inhalt,
        }
        """
    )
    assert bericht["hold_exists"] == ["undefined", "undefined", "undefined"]
    assert bericht["field"] is False
    assert bericht["due"] == ["eins", "zwei"]
    assert bericht["first"] == "eins"


def test_a_stop_by_hand_gives_back_all_entries_of_the_chat_in_written_order():
    """Everything waiting in the chat leaves the line at once, in the order it
    was written; another chat keeps its own. Without the give-back the entries
    stay in line and go out after the stop."""
    bericht = _laufen(
        """
        w.einreihen('a', { inhalt: 'eins' })
        w.einreihen('b', { inhalt: 'fremd' })
        w.einreihen('a', { inhalt: 'zwei' })
        w.einreihen('a', { inhalt: 'drei' })
        const given_back = w.takeAllOut('a')
        return {
          given_back: given_back.map((e) => e.inhalt),
          a_empty: w.fuerChat('a').length,
          other_stays: w.fuerChat('b').map((e) => e.inhalt),
          again: w.takeAllOut('a').length,
        }
        """
    )
    assert bericht["given_back"] == ["eins", "zwei", "drei"]
    assert bericht["a_empty"] == 0
    assert bericht["other_stays"] == ["fremd"]
    assert bericht["again"] == 0


def test_das_kreuz_nimmt_genau_einen_eintrag_heraus():
    bericht = _laufen(
        """
        const eins = w.einreihen('a', { inhalt: 'eins' })
        w.einreihen('a', { inhalt: 'zwei' })
        w.entfernen(eins)
        w.entfernen(99999)
        return { rest: w.fuerChat('a').map((e) => e.inhalt) }
        """
    )
    assert bericht["rest"] == ["zwei"]


def test_ein_geloeschter_chat_nimmt_seine_schlange_mit():
    bericht = _laufen(
        """
        w.einreihen('a', { inhalt: 'eins' })
        w.einreihen('b', { inhalt: 'fremd' })
        w.leeren('a')
        return { a: w.fuerChat('a').length, b: w.fuerChat('b').length }
        """
    )
    assert bericht["a"] == 0
    assert bericht["b"] == 1


def test_ein_stopp_gilt_nur_fuer_was_schon_wartet():
    """A stop is made once for the messages standing in line; what comes
    later needs a stop of its own."""
    bericht = _laufen(
        """
        w.einreihen('a', { inhalt: 'eins' })
        w.einreihen('a', { inhalt: 'zwei' })
        const vorher = w.awaitingInterrupt('a').length
        w.markInterrupted('a')
        const danach = w.awaitingInterrupt('a').length
        w.einreihen('a', { inhalt: 'drei' })
        const spaeter = w.awaitingInterrupt('a').map((e) => e.inhalt)
        return { vorher, danach, spaeter }
        """
    )
    assert bericht["vorher"] == 2
    assert bericht["danach"] == 0
    assert bericht["spaeter"] == ["drei"]


def test_ein_ausgebliebener_stopp_macht_die_nachrichten_wieder_faellig():
    bericht = _laufen(
        """
        w.einreihen('a', { inhalt: 'eins' })
        w.markInterrupted('a')
        w.unmarkInterrupted('a')
        return { faellig: w.awaitingInterrupt('a').length }
        """
    )
    assert bericht["faellig"] == 1


def _words(js: str) -> object:
    """Run `js` against the plain module that merges given-back words."""
    treiber = FRONTEND / "zurueckworte.pruefung.mjs"
    treiber.write_text(
        "import { wordsInFront } from './src/lib/giveBackWords.js'\n"
        "console.log('---BERICHT---' + JSON.stringify(await (async () => {\n"
        + textwrap.indent(textwrap.dedent(js), "  ")
        + "\n})()))\n",
        encoding="utf-8",
    )
    try:
        lauf = subprocess.run(
            ["node", treiber.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60
        )
    finally:
        treiber.unlink(missing_ok=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-2000:]
    return json.loads(lauf.stdout.split("---BERICHT---", 1)[1].strip())


def test_given_back_words_stand_in_written_order_before_the_typed_ones():
    bericht = _words(
        """
        const e = (inhalt) => ({ inhalt })
        return {
          vor_getipptem: wordsInFront([e('eins'), e('zwei')], 'danach getippt'),
          ohne_getipptes: wordsInFront([e('eins'), e('zwei')], ''),
          leere_nachricht: wordsInFront([e('eins'), e(''), e(undefined), e('zwei')], '  '),
          nur_getipptes: wordsInFront([e('')], 'getippt'),
        }
        """
    )
    assert bericht["vor_getipptem"] == "eins\nzwei\ndanach getippt"
    assert bericht["ohne_getipptes"] == "eins\nzwei"
    assert bericht["leere_nachricht"] == "eins\nzwei"
    assert bericht["nur_getipptes"] == "getippt"


def test_nur_ein_stopp_von_hand_gibt_zurueck_ein_fehler_haelt_nichts():
    """The run hands the waiting messages back for a stop by hand and for
    nothing else; a failure and a stop made for a message leave the line be."""
    lauf = (FRONTEND / "src" / "lib" / "chatlauf.svelte.js").read_text(encoding="utf-8")
    assert "anhalten" not in lauf and "haelt(" not in lauf
    assert "else if (fertigerChat && abgebrochen && (!stopForMessage || stopByHand)) giveBackQueued(fertigerChat)" in lauf
    treffer = [m.start() for m in re.finditer(r"giveBackQueued\(", lauf)]
    assert len(treffer) == 3  # the definition and the two stops by hand
    # the stop of a window with no run of its own, waiting on another claim
    assert "      giveBackQueued(chatId)\n      void api.abbrechen(null, chatId)" in lauf
    app = (FRONTEND / "src" / "App.svelte").read_text(encoding="utf-8")
    assert "haelt(" not in app
    # the stop button, the key and the phone's arrow are stops by hand
    assert "abbrechen={abbrechenVonHand}" in app and "abbrechenVonHand()" in app
    phone = (FRONTEND / "src" / "phone" / "InputBar.svelte").read_text(encoding="utf-8")
    assert "chatRun.abbrechenVonHand()" in phone
