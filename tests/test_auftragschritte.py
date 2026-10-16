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


# --- The agent rows at an answer's line stand in columns -------------------

MESSAGE = WURZEL / "frontend" / "src" / "teile" / "Nachricht.svelte"


def _rule(css: str, selector: str) -> str:
    """The declarations of the one rule that opens with this selector."""
    opener = f"\n  {selector} {{"
    assert css.count(opener) == 1, selector
    return css.split(opener, 1)[1].split("}", 1)[0]


def _width(rule: str, name: str) -> int:
    """The characters a rule keeps room for (`width: 16ch`)."""
    found = re.search(rf"\n\s*{name}: (\d+)ch;", rule)
    assert found, (name, rule)
    return int(found.group(1))


def test_the_agent_row_stands_in_columns():
    """An answer is only as wide as its widest row. A clock that gained a
    digit or a last tool with a longer name widened the agent's row, and
    with it moved the state, "Transkript" and the failure marks at the far
    end of every row; from row to row each piece began where the name
    before it happened to end. Now the name's cell is as wide as the
    longest name among the answer's agents, and the clock's and the
    state's cells keep a width of their own and are there in every row."""
    markup, css = MESSAGE.read_text("utf-8").split("<style>", 1)
    row = markup.split('<div class="ereignis helper">', 1)[1].split("\n          </div>", 1)[0]

    # Every name of the answer's agents lies in the name's cell.
    assert "{#each agentNames as other (other)}" in row
    assert '<span class="agent-name-room" aria-hidden="true">{other}</span>' in row
    # The cells stand whether or not the agent's run is known, in this order.
    time = "<span class=\"agent-time\">{job ? agentRuntime(job) : ''}</span>"
    places = [row.index(piece) for piece in (
        '<span class="agent-name">', time, '<span class="agent-status">',
    )]
    assert places == sorted(places)
    # No word of its own at the far end: the whole row is the way to the card.
    assert "agent-transcript" not in row
    status = row.split('<span class="agent-status">', 1)[1].split("</button>", 1)[0]
    assert "agent-step" in status and "agent-state" in status

    name = _rule(css, ".agent-name")
    assert "display: inline-grid" in name
    assert "grid-area: 1 / 1" in _rule(css, ".agent-name > span")
    room = _rule(css, ".agent-name-room")
    assert "visibility: hidden" in room and "height: 0" in room

    clock = _rule(css, ".agent-time")
    assert "flex: none" in clock and "tabular-nums" in clock
    assert _width(clock, "min-width") > 0
    state = _rule(css, ".agent-status")
    # It gives way in an answer narrower than the row, and nowhere else.
    assert "flex:" not in state and "min-width: 0" in state
    assert "text-overflow: ellipsis" in state
    assert "var(--schrift-fest)" in state
    assert _width(state, "width") > 0


def test_the_columns_fit_what_the_program_itself_shows(client, config):
    """The two widths are measured, not chosen: the state's column holds the
    longest name among the program's own tools whole, and the clock's the
    longest clock a run inside an agent's own time limit can show."""
    from app.agenten import STANDARD_MINUTEN
    from app.tools.aufbau import registry_bauen

    css = MESSAGE.read_text("utf-8").split("<style>", 1)[1]
    tools = registry_bauen(client.app, config).namen()
    assert tools, "the program offers no tools to measure"
    assert max(len(name) for name in tools) <= _width(_rule(css, ".agent-status"), "width")
    assert len(f"{int(STANDARD_MINUTEN)}:59") <= _width(_rule(css, ".agent-time"), "min-width")


def test_the_readings_under_the_answer_and_the_helper_row_stay_as_they_are():
    """Silence probe: the readings under the answer still stand in the fixed
    face, and the helper's row is the loose row it was — no grid; what it
    lost is the word at its far end."""
    css = MESSAGE.read_text("utf-8").split("<style>", 1)[1]
    assert _rule(css, ".messung").split() == "font-family: var(--schrift-fest);".split()
    row = _rule(css, ".agent-row")
    assert "display: flex" in row and "gap: 8px" in row
    assert ".agent-transcript" not in css
