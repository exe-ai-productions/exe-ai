"""The tools every run is offered, and the ones it is deliberately not.

Five places have to agree about the goal tool and the clock — the list the
settings window switches things off by, the offer to the model, the mark the
window paints, the tools window's list and the widening of a run's own tool
list. They read one table (``app/tools/registry.py``, ``EVER_OFFERED``), and
this is what holds them to it: an entry added there turns up in all five.

And the drawing tool: a run whose picture window stands at a family that
cannot draw from text is not offered it at all — not offered-and-refused.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.agenten import Agent
from app.api.v1.auftraege import widen_tools
from app.tools import registry as registry_modul
from app.tools.mcp_client import MCPWerkzeug


def _stub(name: str = "stub_tool", server: str = "stub"):
    """A tool module the way EVER_OFFERED carries them."""
    beschreibung = MCPWerkzeug(
        name=name,
        beschreibung="Reads nothing and writes nothing. Exists for one test.",
        schema={"type": "object", "properties": {}, "required": []},
        server=server,
    )
    return SimpleNamespace(
        WERKZEUG_NAME=name,
        SERVER_NAME=server,
        werkzeug_beschreibung=lambda *a, **k: beschreibung,
    )


def test_the_always_offered_tools_come_from_one_list(monkeypatch):
    """One entry in EVER_OFFERED, and all five readers know it.

    Falls over without the change: before it, every one of these places
    carried its own copy of the goal tool and the clock, and a name added to
    one of them was invisible to the others.
    """
    stub = _stub()
    monkeypatch.setattr(
        registry_modul, "EVER_OFFERED", (registry_modul.EverOffered(stub),)
    )
    reg = registry_modul.WerkzeugRegistry([], shell_an=True)

    # The list the settings window switches things off by …
    assert stub.WERKZEUG_NAME in reg.builtin_names()
    # … the offer to the model …
    angebot = [w["function"]["name"] for w in reg.als_openai_werkzeuge()]
    assert stub.WERKZEUG_NAME in angebot
    # … the mark the window paints …
    assert reg.server_von(stub.WERKZEUG_NAME) == stub.SERVER_NAME
    # … the tools window's own list …
    assert stub.WERKZEUG_NAME in [e["name"] for e in reg.uebersicht()]
    # … and the widening of a run's own list.
    agent = Agent(name="probe", prompt="Mach etwas.", werkzeuge=["read_file"])
    weit = widen_tools(agent, hat_ziel=False)
    assert stub.WERKZEUG_NAME in weit.werkzeuge
    assert "read_file" in weit.werkzeuge


def test_a_list_of_its_own_stays_untouched(monkeypatch):
    """The widening works on a copy: the agent itself keeps what it had."""
    agent = Agent(name="probe", prompt="Mach etwas.", werkzeuge=["read_file"])
    widen_tools(agent, hat_ziel=True)
    assert agent.werkzeuge == ["read_file"]


def test_the_offer_is_the_same_bytes_every_time():
    """Silence probe: two builds of the same registry offer the same list.

    The offer rides in every request of a run, and one that wobbles costs the
    server's cache of the whole prefix — so the table must not hand out
    anything that changes between two calls.
    """
    erste = registry_modul.WerkzeugRegistry([], shell_an=True)
    zweite = registry_modul.WerkzeugRegistry([], shell_an=True)
    assert erste.als_openai_werkzeuge() == zweite.als_openai_werkzeuge()
    assert erste.als_openai_werkzeuge() == erste.als_openai_werkzeuge()
    assert erste.builtin_names() == zweite.builtin_names()
    assert erste.uebersicht() == zweite.uebersicht()


# --- draw_image, where the window cannot draw from text --------------------


def _mit_fenster(familie: str):
    from app import image_families
    from app.tools.bild_werkzeug import FensterBild

    return registry_modul.WerkzeugRegistry(
        [],
        bild_zugang=("http://127.0.0.1:1/api/v1", Path("/tmp/bilder"), "schluessel"),
    ), FensterBild(image_families.get(familie), None)


def test_draw_image_is_not_offered_for_a_family_without_txt2img():
    """Falls over without the change: the tool used to be offered anyway and
    refused in three places — the description, the call and the skill."""
    from app.tools import bild_werkzeug

    wan, fenster = _mit_fenster("wan")
    namen = [w["function"]["name"] for w in wan.als_openai_werkzeuge(bild_fenster=fenster)]
    assert bild_werkzeug.WERKZEUG_NAME not in namen
    # The tools window may still list it — it shows what the tool CAN be, not
    # what one chat's window makes of it — and it stays switchable there.
    assert bild_werkzeug.WERKZEUG_NAME in wan.builtin_names()


def test_draw_image_is_offered_where_the_family_draws_from_text():
    """Silence probe, the other way round: SDXL keeps it, description and
    all — and twice read, the list is the same bytes."""
    from app.tools import bild_werkzeug

    sdxl, fenster = _mit_fenster("sdxl")
    namen = [w["function"]["name"] for w in sdxl.als_openai_werkzeuge(bild_fenster=fenster)]
    assert bild_werkzeug.WERKZEUG_NAME in namen
    zweite, fenster2 = _mit_fenster("sdxl")
    assert sdxl.als_openai_werkzeuge(bild_fenster=fenster) == zweite.als_openai_werkzeuge(
        bild_fenster=fenster2
    )


def test_a_configured_servers_declared_tool_is_not_unknown():
    """Silence probe for the start check: a tool of a server that is set up
    but not running right now is a name somebody configured, not a typo —
    only names that match nothing at all are refused."""
    from app.tools.registry import ServerEintrag

    reg = registry_modul.WerkzeugRegistry(
        [ServerEintrag(name="clock", enabled=False, allowed_tools=["get_time"])],
        shell_an=True,
    )
    assert "get_time" in reg.known_names()
    assert "erfunden" not in reg.known_names()


def test_the_count_reads_the_same_list(monkeypatch):
    """`anzahl` — the figure the start message and the protocol carry — is
    read off the table too, not from a number of its own.

    Falls over without the change: the number was hand-written (two), so a
    third row in the table would have been offered and never counted.
    """
    from app.tools import dateiwerkzeuge

    stub = _stub("stub_tool")
    monkeypatch.setattr(
        registry_modul,
        "EVER_OFFERED",
        (*registry_modul.EVER_OFFERED, registry_modul.EverOffered(stub)),
    )
    mit_shell = registry_modul.WerkzeugRegistry([], shell_an=True)
    assert mit_shell.anzahl == 3 + len(dateiwerkzeuge.NAMEN)
