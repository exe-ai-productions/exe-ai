"""The text shown while somebody still dictates (frontend/src/lib/diktatabgleich.js).

The recording is read again about once a second; a word is settled once
three readings in a row agree on it, the rest stays grey. Run in node, like
tests/test_sprechtext.py: what is asserted is what the real module returns.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")

MODUL = Path(__file__).resolve().parent.parent / "frontend/src/lib/diktatabgleich.js"


def _lesungen(*texte: str) -> list[dict]:
    """Feeds the readings one after the other and returns what each showed,
    together with whether the stretch was closed after it."""
    quelle = re.sub(r"^export ", "", MODUL.read_text(), flags=re.M)
    skript = f"""
let stand = neuerStand()
const aus = []
for (const text of {json.dumps(list(texte))}) {{
  const r = abgleichen(stand, text)
  stand = r.stand
  aus.push({{ fest: r.fest, unsicher: r.unsicher, zu: abgeschlossen(stand) }})
}}
console.log(JSON.stringify(aus))
"""
    lauf = subprocess.run(["node", "-e", f"{quelle}\n{skript}"], capture_output=True, text=True)
    assert lauf.returncode == 0, lauf.stderr
    return json.loads(lauf.stdout)


def _faellig(gehoert: bool, liest: bool, offen: bool = False, stille: int = 0) -> bool:
    quelle = re.sub(r"^export ", "", MODUL.read_text(), flags=re.M)
    werte = json.dumps({"gehoert": gehoert, "liest": liest, "offen": offen, "stilleLesungen": stille})
    skript = f"console.log(JSON.stringify(lesenFaellig({werte})))"
    lauf = subprocess.run(["node", "-e", f"{quelle}\n{skript}"], capture_output=True, text=True)
    assert lauf.returncode == 0, lauf.stderr
    return json.loads(lauf.stdout)


def test_drei_gleiche_lesungen_machen_woerter_fest_zwei_nicht():
    aus = _lesungen("Hallo wie", "Hallo wie geht", "Hallo wie geht es")
    # After two readings nothing is settled yet — all of it is grey.
    assert aus[1] == {"fest": "", "unsicher": "Hallo wie geht", "zu": False}
    # The third agrees with the two before on "Hallo wie": settled.
    assert aus[2]["fest"] == "Hallo wie"
    assert aus[2]["unsicher"] == "geht es"


def test_ein_geaendertes_ende_bleibt_unsicher():
    aus = _lesungen("Ich gehe nach Haus", "Ich gehe nach Hause", "Ich gehe nach Hamburg")
    assert aus[2]["fest"] == "Ich gehe nach"
    assert aus[2]["unsicher"] == "Hamburg"


def test_satzzeichen_und_gross_klein_trennen_kein_wort():
    aus = _lesungen("das ist gut", "Das ist gut.", "das ist, gut")
    assert aus[2]["fest"] == "das ist, gut"
    assert aus[2]["unsicher"] == ""


def test_ein_festes_wort_bleibt_fest_auch_wenn_eine_lesung_widerspricht():
    aus = _lesungen("eins zwei", "eins zwei", "eins zwei", "eins drei vier")
    assert aus[2]["fest"] == "eins zwei"
    assert aus[3]["fest"] == "eins zwei"
    assert aus[3]["unsicher"] == "vier"


def test_abgeschlossen_erst_wenn_drei_lesungen_nichts_offen_lassen():
    aus = _lesungen("ja genau", "ja genau", "ja genau")
    assert aus[2] == {"fest": "ja genau", "unsicher": "", "zu": True}
    # One short reading on its own closes nothing: it may have dropped words.
    kurz = _lesungen("ja genau so", "ja genau so", "ja genau")
    assert kurz[2]["fest"] == "ja genau"
    assert kurz[2]["zu"] is False


def test_in_stille_wird_nicht_nachgelesen():
    """The silence check: nothing heard and nothing left unsettled, no
    request; and never a second one while the first is still out."""
    assert _faellig(gehoert=True, liest=False) is True
    assert _faellig(gehoert=False, liest=False) is False
    assert _faellig(gehoert=True, liest=True) is False


def test_in_stille_hoechstens_drei_lesungen_fuer_das_offene_ende():
    """After the speaker stops, unsettled words still get their readings —
    that is what settles them and closes the stretch — but no more than
    three; with nothing unsettled, none at all."""
    assert _faellig(gehoert=False, liest=False, offen=True, stille=0) is True
    assert _faellig(gehoert=False, liest=False, offen=True, stille=2) is True
    assert _faellig(gehoert=False, liest=False, offen=True, stille=3) is False
    assert _faellig(gehoert=False, liest=True, offen=True, stille=0) is False


def test_eine_kurze_lesung_schliesst_nichts_und_macht_nichts_fest():
    """A reading with fewer words than are settled (a dropout) agrees with
    nothing: three of them in a row neither settle words nor close the
    stretch — the recording is not skipped past words never shown."""
    aus = _lesungen("eins zwei drei", "eins zwei drei", "eins zwei drei vier", "", "", "")
    assert aus[2]["fest"] == "eins zwei drei"
    assert aus[5]["fest"] == "eins zwei drei"
    assert aus[5]["zu"] is False
