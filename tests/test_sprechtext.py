"""What the voice reads, and in which pieces (frontend/src/lib/sprechtext.js).

The voice used to wait for the whole answer and then read it raw, asterisks
and code blocks included. Now the answer is cleaned into a spoken script and
cut into sentences while it is still being written, so the first sentence can
speak before the model has finished.

Run in node, like tests/test_codeblock.py: what is asserted is what the real
module returns.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")

MODUL = Path(__file__).resolve().parent.parent / "frontend/src/lib/sprechtext.js"


def _lauf(skript: str):
    """The module with its exports made plain declarations, then *skript*,
    which prints one JSON value."""
    quelle = re.sub(r"^export ", "", MODUL.read_text(), flags=re.M)
    lauf = subprocess.run(["node", "-e", f"{quelle}\n{skript}"], capture_output=True, text=True)
    assert lauf.returncode == 0, lauf.stderr
    return json.loads(lauf.stdout)


def _js(ausdruck: str):
    return _lauf(f"console.log(JSON.stringify({ausdruck}))")


def _putzen(text: str) -> str:
    return _js(f"sprechtextPutzen({json.dumps(text)})")


def _schneiden(script: str, ab: int = 0, fertig: bool = False) -> dict:
    return _js(f"stueckeSchneiden({json.dumps(script)}, {ab}, {json.dumps(fertig)})")


def test_codebloecke_und_markdownzeichen_werden_nicht_gesprochen():
    text = (
        "## Setup\n\nRun **this** and read [the docs](https://x.y/z).\n\n"
        "```bash\nnpm install\n```\n\n- first item\n1. numbered item\n> quoted `code`"
    )
    gesprochen = _putzen(text)
    assert "npm install" not in gesprochen
    for zeichen in ("**", "##", "```", "](", "`", "> ", "- ", "1. "):
        assert zeichen not in gesprochen, (zeichen, gesprochen)
    for wort in ("Setup", "Run this and read the docs.", "first item", "numbered item", "quoted code"):
        assert wort in gesprochen, (wort, gesprochen)


def test_ein_offener_codeblock_haelt_alles_danach_zurueck():
    """Still being written: nothing inside it is spoken, and what stood
    before it stays exactly as it was."""
    davor = "Here is the fix, it is short. "
    assert _putzen(davor + "```python\nprint(1)") == davor
    assert _putzen(davor + "Look: ```python\nprint(1)") == davor + "Look: "


def test_denkbloecke_werden_nie_gesprochen():
    assert _putzen("<think>secret plan</think>The answer is yes, of course.") == (
        "\n\nThe answer is yes, of course."
    )
    assert _putzen("Visible part here. <think>still thinking") == "Visible part here. "


def test_tabellen_werden_zu_aufzaehlungen():
    gesprochen = _putzen("| Name | Size |\n|---|---|\n| a.txt | 2 KB |")
    assert "|" not in gesprochen and "---" not in gesprochen
    assert "Name, Size" in gesprochen and "a.txt, 2 KB" in gesprochen


def test_geschnitten_wird_am_satzende_und_an_der_leerzeile():
    script = "The first sentence is here. The second one follows!\n\nA new paragraph starts"
    ergebnis = _schneiden(script)
    assert ergebnis["stuecke"] == ["The first sentence is here.", "The second one follows!"]
    # The unfinished last sentence waits for more text.
    assert script[ergebnis["bis"]:].strip() == "A new paragraph starts"


def test_ein_kurzes_stueck_haengt_am_naechsten():
    """The floor: pieces under 20 characters are carried into the next."""
    ergebnis = _schneiden("Yes. Of course. That works well for you.", fertig=True)
    assert ergebnis["stuecke"] == ["Yes. Of course. That works well for you."]


def test_am_ende_geht_der_rest_als_letztes_stueck():
    ergebnis = _schneiden("One finished sentence here. And a tail without end", fertig=True)
    assert ergebnis["stuecke"] == ["One finished sentence here.", "And a tail without end"]


def test_waehrend_des_schreibens_entstehen_dieselben_stuecke_wie_am_stueck():
    """Fed chunk by chunk the way an answer streams in, the pieces handed out
    are exactly the pieces of the finished text — nothing twice, nothing
    lost, no code."""
    antwort = (
        "Sure, here is how it works. First you install it.\n\n"
        "```bash\nnpm install. then more\n```\n\n"
        "Then you **run** it with [the script](http://a.b). That is all there is to it!"
    )
    skript = f"""
const antwort = {json.dumps(antwort)};
let gelesen = 0; const alle = [];
for (let i = 1; i <= antwort.length; i += 7) {{
  const r = stueckeSchneiden(sprechtextPutzen(antwort.slice(0, i)), gelesen, false);
  gelesen = r.bis; alle.push(...r.stuecke);
}}
const r = stueckeSchneiden(sprechtextPutzen(antwort), gelesen, true);
alle.push(...r.stuecke);
const amStueck = stueckeSchneiden(sprechtextPutzen(antwort), 0, true).stuecke;
console.log(JSON.stringify({{ alle, amStueck }}));
"""
    ergebnis = _lauf(skript)
    assert ergebnis["alle"] == ergebnis["amStueck"], ergebnis
    assert not any("npm" in s or "**" in s for s in ergebnis["alle"]), ergebnis


def test_nach_einer_aenderung_hinter_dem_gelesenen_wird_neu_ausgerichtet():
    """The emphasis rule removes a star only once its partner arrives —
    behind text already cut. The count is set again on the end of what was
    cut, so the next piece neither repeats nor starts mid-word."""
    alt = "It costs 5 * 3 euros. Then more"
    gelesen = len("It costs 5 * 3 euros. ")
    neu = "It costs 5  3 euros. Then more  text follows here now."
    stand = _js(f"neuAusrichten({json.dumps(alt)}, {gelesen}, {json.dumps(neu)})")
    assert stand["script"] == neu
    assert neu[stand["gelesen"]:] == "Then more  text follows here now."


def test_ohne_anker_wird_das_alte_script_weitergelesen():
    stand = _js('neuAusrichten("First sentence is here. Rest", 24, "Something else entirely.")')
    assert stand == {"script": "First sentence is here. Rest", "gelesen": 24}


def test_das_erste_stueck_endet_am_ersten_komma_nach_zwanzig_zeichen():
    """The voice starts on the first clause; every further piece ends at a
    sentence's end as before."""
    script = "Well, here is how this works in practice, and then more follows. A second sentence ends here. Tail"
    ergebnis = _schneiden(script)
    assert ergebnis["stuecke"] == [
        "Well, here is how this works in practice,",
        "and then more follows.",
        "A second sentence ends here.",
    ]
    assert script[ergebnis["bis"]:].strip() == "Tail"


def test_ein_komma_vor_dem_zwanzigsten_zeichen_schneidet_nicht():
    ergebnis = _schneiden("Yes, of course it does, and that is exactly the point. More text here follows", fertig=False)
    # "Yes," is far short; the next comma stands at 23 characters.
    assert ergebnis["stuecke"] == ["Yes, of course it does,", "and that is exactly the point."]


def test_ein_komma_in_einer_zahl_schneidet_nicht():
    ergebnis = _schneiden("The price is 3,50 euros for the whole thing, so please keep that in mind. And more", fertig=False)
    assert ergebnis["stuecke"] == ["The price is 3,50 euros for the whole thing,", "so please keep that in mind."]


def test_nach_dem_ersten_stueck_schneidet_ein_komma_nicht_mehr():
    """`ab` > 0 is a later piece: the comma rule is the first piece's only."""
    script = "First piece is long enough here. Then comes a clause, which goes on and on, until the sentence ends. Tail"
    erstes = _schneiden(script)
    assert erstes["stuecke"][0] == "First piece is long enough here."
    assert erstes["stuecke"][1] == "Then comes a clause, which goes on and on, until the sentence ends."
    spaeter = _schneiden(script, ab=len("First piece is long enough here. "))
    assert spaeter["stuecke"] == ["Then comes a clause, which goes on and on, until the sentence ends."]


def test_beim_schreiben_entsteht_das_erste_stueck_am_komma_wie_am_stueck():
    antwort = "Sure thing, I can explain that to you in a few words, so listen closely. It is simple."
    skript = f"""
const antwort = {json.dumps(antwort)};
let gelesen = 0; const alle = [];
for (let i = 1; i <= antwort.length; i += 3) {{
  const r = stueckeSchneiden(antwort.slice(0, i), gelesen, false);
  gelesen = r.bis; alle.push(...r.stuecke);
}}
const r = stueckeSchneiden(antwort, gelesen, true);
alle.push(...r.stuecke);
console.log(JSON.stringify({{ alle, amStueck: stueckeSchneiden(antwort, 0, true).stuecke }}));
"""
    ergebnis = _lauf(skript)
    assert ergebnis["alle"] == ergebnis["amStueck"], ergebnis
    assert ergebnis["alle"][0] == "Sure thing, I can explain that to you in a few words,"
