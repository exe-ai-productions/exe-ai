"""The job transcript: one line that moves, instead of many that pile up.

The tool progress reaches the job stream as `tool_call_laeuft` events — the
chat path has forwarded them since WerkzeugFortschrittsDrossel, the job path
only learned it later. Measured on real runs: 36, 74 and 87 events for a
SINGLE tool call, because a model writing a long argument keeps at it for
minutes.

Written as a step each, those events would bury the very transcript they are
meant to make readable. So the first one opens a line and every later one
rewrites it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
ROUTE = WURZEL / "app" / "api" / "v1" / "auftraege.py"


def test_eine_zeile_wird_fortgeschrieben_statt_vervielfacht(repos):
    """87 events of one call leave ONE line — and it carries the last
    number, not the first."""
    auftrag = repos.auftraege.erstellen(user_id="benutzer", agent="a", auftrag="x")
    schritt = repos.auftraege.schritt_anlegen(
        auftrag.id, "werkzeug", "web_search — 0 Zeichen"
    )
    for zeichen in (36, 180, 640, 1_364, 2_272, 3_001):
        repos.auftraege.schritt_fortschreiben(
            schritt.id, f"web_search — {zeichen} Zeichen"
        )

    zeilen = repos.auftraege.schritte(auftrag.id)
    assert len(zeilen) == 1, [z.inhalt for z in zeilen]
    assert zeilen[0].inhalt == "web_search — 3001 Zeichen"
    assert zeilen[0].nummer == 1


def test_zwei_aufrufe_sind_zwei_zeilen(repos):
    """The id is per call: a second tool call gets its own line and its own
    number, and rewriting the first leaves the second alone."""
    auftrag = repos.auftraege.erstellen(user_id="benutzer", agent="a", auftrag="x")
    erster = repos.auftraege.schritt_anlegen(auftrag.id, "werkzeug", "read_file — 0 Zeichen")
    zweiter = repos.auftraege.schritt_anlegen(
        auftrag.id, "werkzeug", "run_command — 0 Zeichen"
    )

    repos.auftraege.schritt_fortschreiben(erster.id, "read_file — 512 Zeichen")
    repos.auftraege.schritt_fortschreiben(zweiter.id, "run_command — 64 Zeichen")

    zeilen = repos.auftraege.schritte(auftrag.id)
    assert [(z.nummer, z.inhalt) for z in zeilen] == [
        (1, "read_file — 512 Zeichen"),
        (2, "run_command — 64 Zeichen"),
    ]


def test_ohne_ereignis_entsteht_keine_zeile(repos):
    """Silence probe: a run whose tools never report gets no such line, and
    the steps it does write are untouched."""
    auftrag = repos.auftraege.erstellen(user_id="benutzer", agent="a", auftrag="x")
    repos.auftraege.schritt_anlegen(auftrag.id, "status", "laeuft")

    zeilen = repos.auftraege.schritte(auftrag.id)
    assert [z.typ for z in zeilen] == ["status"]
    assert not any(z.typ == "werkzeug" for z in zeilen)


def test_die_route_schreibt_den_fortschritt_in_das_protokoll():
    """The wiring, read off the route: the event branch has to call the
    transcript, or all of the above is a rule nobody applies."""
    quelle = ROUTE.read_text(encoding="utf-8")
    assert 'stueck.sorte == "tool_call_laeuft"' in quelle
    zweig = re.search(
        r'stueck\.sorte == "tool_call_laeuft"([\s\S]*?)elif stueck\.sorte ==',
        quelle,
    )
    assert zweig, "the branch no longer reads as expected"
    assert "fortschritt_protokollieren(stueck.daten, runde)" in zweig.group(1)
    # And the helper itself: one line per (index, name), opened once.
    assert "fortschrittszeilen.get(kennung)" in quelle
    assert "schritt_fortschreiben" in quelle


def test_die_fortschrittszeile_traegt_nur_name_und_zeichenzahl():
    """Never the argument: the chat shows its tail, a transcript is a log —
    and a log carrying half-written JSON stops being readable."""
    quelle = ROUTE.read_text(encoding="utf-8")
    rumpf = re.search(
        r"def fortschritt_protokollieren\(daten: dict, runde: int\)([\s\S]*?)\n\n    def ",
        quelle,
    )
    assert rumpf, "the helper no longer reads as expected"
    text = rumpf.group(1)
    assert "get('name')" in text or 'get("name")' in text
    assert "get('zeichen')" in text or 'get("zeichen")' in text
    # The word may stand in the docstring, which explains that the argument
    # stays out; what may not stand there is a READ of it.
    assert "get('argument')" not in text and 'get("argument")' not in text
    assert "'args'" not in text and '"args"' not in text


def test_die_kennung_kennt_die_runde():
    """The index is the call's position IN ITS ROUND, so every round numbers
    from zero again — and a key without the round would let the second
    `read_file` of a run keep rewriting the first one's line."""
    quelle = ROUTE.read_text(encoding="utf-8")
    assert 'kennung = f"{runde}:{daten.get(\'index\')}:{daten.get(\'name\') or \'\'}"' in quelle, (
        "the id no longer carries the round"
    )


def test_die_zeile_kommt_aus_dem_katalog():
    """The line is STORED and read back as it stands, so it cannot be
    translated later — it has to leave the catalogue already in the user's
    language (repo rule: interface texts live in the two catalogues)."""
    quelle = ROUTE.read_text(encoding="utf-8")
    rumpf = re.search(
        r"def fortschritt_protokollieren\(daten: dict, runde: int\)([\s\S]*?)\n\n    def ",
        quelle,
    )
    assert rumpf, "the helper no longer reads as expected"
    assert '"werkzeug.schreibt"' in rumpf.group(1)
    # And the key carries both halves of the sentence.
    katalog = json.loads(
        (WURZEL / "app" / "locales" / "en.json").read_text(encoding="utf-8")
    )
    satz = katalog["werkzeug"]["schreibt"]
    assert "{name}" in satz and "{zeichen}" in satz
