"""The tool-mark catalogue must not have holes.

The mark in front of a tool row used to be guessed from the tool's name. That
worked for the names somebody had thought of and quietly failed for the rest —
a Notion call showed the gray fallback for weeks because the server had
started naming its tools `notion-search` instead of `API-post-search`.

The catalogue answers by SERVER now, and the server name is fixed in
mcp_servers.json. That only holds as long as both files agree, which is what
these tests check: every configured server has a mark, and every mark the
catalogue names is actually drawn. Whoever registers a new server without
giving it a mark finds out here instead of in a screenshot.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
KATALOG = WURZEL / "frontend/src/lib/werkzeugkatalog.js"
ZEICHNUNG = WURZEL / "frontend/src/teile/Werkzeugzeichen.svelte"
HOUSE_SIGNS = WURZEL / "frontend/src/teile/Hauszeichen.svelte"
SERVER_CATALOGUE = WURZEL / "frontend/src/lib/serverkatalog.js"
# The shipped list, not the user's own: theirs is git-ignored and holds
# whatever machines they added, which this repository never sees.
SERVER_DATEI = WURZEL / "mcp_servers.example.json"


def _katalog_text() -> str:
    return KATALOG.read_text(encoding="utf-8")


def _tabelle(name: str) -> str:
    """One name table of the catalogue, as its block of entries."""
    block = re.search(rf"{name}\s*=\s*\{{(.*?)\n\}}", _katalog_text(), re.S)
    assert block, f"{name} not found — was the catalogue rebuilt?"
    return block.group(1)


def _server_im_katalog() -> set[str]:
    """The server names the catalogue answers with a mark of their own: the
    registered ones and the house's own sources. The two stand apart because a
    registered server may carry the name of a built-in one."""
    namen = set()
    for tabelle in ("NACH_SERVER", "NACH_EINGEBAUT"):
        namen |= set(re.findall(r"^\s*([\w-]+):", _tabelle(tabelle), re.M))
    return namen


def _zeichen_im_katalog() -> set[str]:
    """Every mark the catalogue can return."""
    text = _katalog_text()
    namen = set(re.findall(r":\s*'([a-z_]+)'", text))
    namen |= set(re.findall(r"RUECKFALL\s*=\s*'([a-z]+)'", text))
    return namen


def _gezeichnete_zeichen() -> set[str]:
    """Every mark the component actually draws."""
    text = ZEICHNUNG.read_text(encoding="utf-8")
    gezeichnet = set(re.findall(r"zeichen === '([a-z]+)'", text))
    # The last branch is the fallback and carries no comparison.
    gezeichnet.add("winkel")
    return gezeichnet


def test_jeder_konfigurierte_server_hat_ein_zeichen():
    server = set(json.loads(SERVER_DATEI.read_text(encoding="utf-8"))["mcpServers"])
    fehlend = server - _server_im_katalog()
    assert not fehlend, (
        "These servers are in mcp_servers.example.json but not in the catalogue: "
        f"{sorted(fehlend)} — their tools would get the grey angle."
    )


def test_das_eingebaute_shell_werkzeug_steht_im_katalog():
    from app.tools import shell

    assert shell.SERVER_NAME in _server_im_katalog()


def _house_signs() -> set[str]:
    """Every standing sign the house draws."""
    return set(re.findall(r"zeichen === '([a-z_]+)'", HOUSE_SIGNS.read_text(encoding="utf-8")))


def test_jedes_zeichen_des_katalogs_wird_auch_gezeichnet():
    """A mark is drawn here as a tool mark, or it is one of the house's
    standing signs and the row hands it over. A name neither of the two
    draws would stand in the row as an empty box."""
    handed_over = _zeichen_im_katalog() - _gezeichnete_zeichen()
    fehlend = handed_over - _house_signs()
    assert not fehlend, (
        f"The catalogue names icons nobody draws: {sorted(fehlend)}"
    )
    assert handed_over, "no server names a standing sign any more — the branch below is dead"
    # The plain speech bubble is the house's sign for a chat; the bubble with
    # a question mark belongs to the one tool that asks and has its own name.
    assert "sprechblase" in handed_over, "a chat server would wear the mark of the tool that asks"
    assert "question" in _gezeichnete_zeichen()
    text = ZEICHNUNG.read_text(encoding="utf-8")
    branch = text.split("{:else if zeichen !== RUECKFALL}", 1)[1].split("{:else}", 1)[0]
    assert "<Hauszeichen {zeichen} />" in branch, "a standing sign is not handed to the house"
    assert 'class="zeichen sign" class:laeuft={animiert} class:werkzeug={istWerkzeug}' in branch


def test_kein_zeichen_liegt_ungenutzt_herum():
    """A drawn mark nobody can reach is dead weight — and usually a typo."""
    ungenutzt = _gezeichnete_zeichen() - _zeichen_im_katalog()
    assert not ungenutzt, (
        "These icons are drawn but never returned by the catalogue: "
        f"{sorted(ungenutzt)}"
    )


@pytest.mark.parametrize(
    "werkzeug,server,erwartet",
    [
        # The server decides, whatever the tool is called …
        ("egal_wie_das_heisst", "notion", "seite"),
        ("brandneues_werkzeug", "github", "verzweigung"),
        ("noch_nie_gesehen", "recraft", "bild"),
        # … except where a tool has earned its own mark.
        ("remove_background", "recraft", "freistellen"),
        ("run_command", "shell", "eingabe"),
        # Without a known server the pattern still catches the usual names.
        ("notion-search", "", "seite"),
        ("create_issue", "", "verzweigung"),
        ("send_email", "", "brief"),
        # And what nobody knows looks unknown.
        ("voellig_fremdes_ding", "", "winkel"),
        ("voellig_fremdes_ding", "unbekannter_server", "winkel"),
    ],
)
def test_zuordnung_haelt_sich_an_die_reihenfolge(werkzeug, server, erwartet):
    """Tool name beats server, server beats pattern, pattern beats fallback.

    Mirrors `zeichenFuer` from the catalogue. Kept in step by the tests above,
    which fail as soon as the two drift apart.
    """
    nach_werkzeug = dict(
        re.findall(r"^\s*([\w-]+):\s*'([a-z]+)',", _tabelle("NACH_WERKZEUG"), re.M)
    )
    nach_server = dict(
        re.findall(r"^\s*([\w-]+):\s*'([a-z_]+)',", _tabelle("NACH_SERVER"), re.M)
    )

    if werkzeug in nach_werkzeug:
        assert nach_werkzeug[werkzeug] == erwartet
    elif server and server in nach_server:
        assert nach_server[server] == erwartet
    else:
        # The pattern step: only the cases the parameters declare.
        muster = {
            "notion-search": "seite",
            "create_issue": "verzweigung",
            "send_email": "brief",
        }
        assert muster.get(werkzeug, "winkel") == erwartet


@pytest.mark.parametrize(
    "server,eingebaut,erwartet",
    [
        # The house's own sources draw their own mark …
        ("shell", True, "eingabe"),
        ("memory", True, "wolke"),
        ("skills", True, "buch"),
        # … and a registered server of the same name does not borrow it. A
        # server called "shell" beside the built-in shell would otherwise wear
        # the built-in's mark although it is not even switchable.
        ("shell", False, "winkel"),
        ("memory", False, "winkel"),
        ("skills", False, "winkel"),
        # A caller that cannot know the kind — a tool row in a chat — is told
        # by the name, as it always was: the house's table first.
        ("shell", None, "eingabe"),
        ("memory", None, "wolke"),
        ("skills", None, "buch"),
        # The sources that came later wear theirs too, and a server of the same
        # name still borrows nothing.
        ("image", True, "bild"),
        ("cronjob", True, "stopwatch"),
        ("goal", True, "flag"),
        ("dock", True, "seite"),
        ("clock", True, "clock"),
        ("image", False, "winkel"),
        ("cronjob", False, "winkel"),
        ("goal", False, "winkel"),
        ("dock", False, "winkel"),
        ("clock", False, "winkel"),
    ],
)
def test_die_art_der_quelle_entscheidet_ueber_das_zeichen(server, eingebaut, erwartet):
    """The kind decides, not the name — mirrored from ``zeichenFuer`` like the
    order test above, and kept in step by the same tables."""
    eigene = dict(
        re.findall(r"^\s*([\w-]+):\s*'([a-z]+)',", _tabelle("NACH_EINGEBAUT"), re.M)
    )
    fremde = dict(
        re.findall(r"^\s*([\w-]+):\s*'([a-z_]+)',", _tabelle("NACH_SERVER"), re.M)
    )

    # Without the kind the house's table is read first, exactly as in
    # `zeichenFuer` — the two tables carry no name twice, so the order only
    # decides the answer if a later wording ever stands in both.
    if eingebaut is None:
        tabelle = {**fremde, **eigene}
    else:
        tabelle = eigene if eingebaut else fremde
    assert tabelle.get(server, "winkel") == erwartet


def test_die_quellenzeile_zeichnet_die_art_der_quelle():
    """What the catalogue answers, the row has to ask for: the built-in source
    hands its kind over, a registered server draws the house's plug. Read from
    the source, because the difference is the branch itself — a picture of it
    is in the report."""
    text = (WURZEL / "frontend/src/teile/Werkzeuge.svelte").read_text(encoding="utf-8")

    assert "!quelle.eingebaut && LOGOS[quelle.kennung]" in text, "the mark applies to foreign ones only"
    assert "<Werkzeugzeichen server={quelle.kennung} eingebaut={true} />" in text
    assert '<Hauszeichen zeichen="plug"' in text


def _marks(pairs: list[list]) -> list[str]:
    """What the catalogue itself answers — run, not read. A pair is the tool
    name and the server; a third entry is the kind of the source."""
    frontend = WURZEL / "frontend"
    driver = frontend / f"marks-{os.getpid()}.pruefung.mjs"
    driver.write_text(
        "import { zeichenFuer } from './src/lib/werkzeugkatalog.js'\n"
        f"console.log('---REPORT---' + JSON.stringify({json.dumps(pairs)}"
        ".map(([name, server, kind]) => zeichenFuer(name, server, kind))))\n",
        encoding="utf-8",
    )
    try:
        run = subprocess.run(["node", driver.name], cwd=frontend, capture_output=True, text=True, timeout=60)
    finally:
        driver.unlink(missing_ok=True)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    return json.loads(run.stdout.split("---REPORT---", 1)[1].strip())


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")

# The servers the catalogue of servers offers beyond the first eight, each
# with the sign its tool rows wear.
CATALOGUE_SERVERS = {
    "slack": "sprechblase",
    "calendar": "stoppuhr",
    "drive": "ordner",
    "canva": "palette",
    "spotify": "sprache_welle",
    "todoist": "haken",
    "trello": "raster",
    "asana": "haken",
    "linear": "ordner",
    "clickup": "haken",
    "airtable": "raster",
    "vercel": "wolke",
    "sentry": "glocke",
}


@needs_node
def test_the_tools_that_had_the_grey_angle_wear_their_own_mark():
    """By name, so a chat that sees no server draws it too: the job start the
    agent, both schedule tools the stopwatch, the report the flag, the time
    the clock."""
    assert _marks([
        ["start_job", "shell"],
        ["start_job", ""],
        ["cronjob", ""],
        ["cron_note", ""],
        ["goal", ""],
        ["get_current_time", ""],
    ]) == ["agent", "agent", "stopwatch", "stopwatch", "flag", "clock"]


@needs_node
def test_the_built_in_sources_wear_their_marks_and_a_server_of_the_same_name_none():
    names = ["shell", "memory", "skills", "image", "cronjob", "goal", "dock", "clock"]
    built_in = _marks([["", name, True] for name in names])
    assert built_in == ["eingabe", "wolke", "buch", "bild", "stopwatch", "flag", "seite", "clock"]
    assert _marks([["", name, False] for name in names]) == ["winkel"] * len(names)


@needs_node
def test_silence_the_shell_mark_stays_with_run_command_and_an_unknown_tool_stays_unknown():
    """Nothing else took the mark of the shell, the folder tools kept theirs,
    and a tool nobody drew a mark for still looks unknown."""
    assert _marks([
        ["run_command", "shell", True],
        ["list_dir", "shell", True],
        ["create_folder", "shell", True],
        ["something_new", "", None],
        ["something_new", "somebodys_server", False],
    ]) == ["eingabe", "ordner", "ordner", "winkel", "winkel"]


@needs_node
def test_a_tool_of_a_catalogue_server_wears_the_sign_of_its_server():
    """Whatever such a server calls its tools: the row shows the server's
    sign and not the grey chevron of a tool nobody knows."""
    servers = sorted(CATALOGUE_SERVERS)
    assert _marks([["x", server] for server in servers]) == [CATALOGUE_SERVERS[server] for server in servers]


@needs_node
def test_the_first_servers_keep_their_marks_and_an_unknown_one_gets_none():
    """The silence check: nothing changes for the servers that had a mark,
    and a server nobody entered still falls through to the name patterns
    and, past them, to the chevron."""
    before = {
        "websuche": "globus",
        "searxng": "globus",
        "notion": "seite",
        "recraft": "bild",
        "github": "verzweigung",
        "gmail": "brief",
        "figma": "flaechen",
        "huggingface": "paket",
    }
    servers = sorted(before)
    assert _marks([["x", server] for server in servers]) == [before[server] for server in servers]
    assert _marks([["x", "somebody_elses"], ["create_issue", "somebody_elses"], ["x", ""]]) == [
        "winkel",
        "verzweigung",
        "winkel",
    ]


def test_every_server_of_the_server_catalogue_has_a_sign():
    """A server the settings offer by name must not reach the chat without a
    sign: whoever adds one to the catalogue of servers finds out here."""
    offered = set(re.findall(r"\{\s*name: '(\w+)'", SERVER_CATALOGUE.read_text(encoding="utf-8")))
    assert set(CATALOGUE_SERVERS) <= offered, "the test names a server the catalogue does not offer"
    missing = offered - _server_im_katalog()
    assert not missing, f"These servers are offered but wear the grey chevron: {sorted(missing)}"
