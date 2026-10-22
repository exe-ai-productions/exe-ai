"""Tor 3 (app/berechtigungen.py) — the judgment, and the two holes it closes.

Most tests call ``berechtigungen.urteil`` directly with an explicit
``Regeldatei``, so they never touch disk. A few go through the real
``WerkzeugRegistry`` to prove the hook inside ``ausfuehren`` actually fires —
not only the pure function in isolation.
"""

from __future__ import annotations

import json

import pytest

from app import berechtigungen
from app.agenten import Agent
from app.berechtigungsregeln import Regeldatei, laden
from app.tools import WerkzeugRegistry, WerkzeugVerboten


def _agent(werkzeuge: list[str], berechtigungen: dict[str, str] | None = None) -> Agent:
    return Agent(
        name="testagent", prompt="Du bist ein Testagent.", werkzeuge=werkzeuge,
        berechtigungen=berechtigungen or {},
    )


# --- Hole A: a path outside the shared folders ------------------------------


def test_dateiwerkzeug_innerhalb_des_ordners_laeuft(tmp_path):
    urteil = berechtigungen.urteil(
        "read_file", {"path": "notiz.md"}, [str(tmp_path)], "agent",
        agent=_agent(["read_file"]), regeln=Regeldatei(),
    )
    assert urteil.antwort == "ja"


def test_agent_ausserhalb_des_ordners_bekommt_nein(tmp_path):
    """Hole A: without this, a job reached any path at all."""
    outside = str(tmp_path.parent / "elsewhere" / "hosts")  # beside the share, on this system
    urteil = berechtigungen.urteil(
        "read_file", {"path": outside}, [str(tmp_path)], "agent",
        agent=_agent(["read_file"]), regeln=Regeldatei(),
    )
    assert urteil.antwort == "nein"
    assert outside in urteil.grund
    assert str(tmp_path) in urteil.grund


def test_chat_ausserhalb_des_ordners_bleibt_fragen(tmp_path):
    """Today's chat behaviour must not change: outside still just asks."""
    urteil = berechtigungen.urteil(
        "read_file", {"path": "/etc/hosts"}, [str(tmp_path)], "chat",
        regeln=Regeldatei(),
    )
    assert urteil.antwort == "fragen"


def test_ausserhalb_der_ordner_ist_je_herkunft_einstellbar(tmp_path):
    """A user who trusts their agents can flip this back to 'ja'."""
    regeln = Regeldatei()
    regeln.ausserhalb_der_ordner["agent"] = "ja"
    urteil = berechtigungen.urteil(
        "read_file", {"path": "/etc/hosts"}, [str(tmp_path)], "agent",
        agent=_agent(["read_file"]), regeln=regeln,
    )
    assert urteil.antwort == "ja"


# --- Hole B: a tool the agent never named -----------------------------------


def test_agent_ohne_werkzeug_in_der_liste_bekommt_nein(tmp_path):
    """Hole B: offering already filtered this out, but a run older than the
    filter — or a model that ignores it — must be refused at execution too.
    """
    urteil = berechtigungen.urteil(
        "read_file", {"path": "notiz.md"}, [str(tmp_path)], "agent",
        agent=_agent(["web_search"]), regeln=Regeldatei(),
    )
    assert urteil.antwort == "nein"
    assert "read_file" in urteil.grund
    assert "web_search" in urteil.grund


def test_agent_ohne_tools_feld_ist_von_loch_b_nicht_betroffen(tmp_path):
    """tools: left out (werkzeuge is None, not []) means every
    approved tool runs — Hole B has nothing to compare against."""
    urteil = berechtigungen.urteil(
        "read_file", {"path": "notiz.md"}, [str(tmp_path)], "agent",
        agent=_agent(None), regeln=Regeldatei(),
    )
    assert urteil.antwort == "ja"


def test_chat_kennt_keine_werkzeugliste(tmp_path):
    """The tools: restriction is an agent concept — a chat has none."""
    urteil = berechtigungen.urteil(
        "read_file", {"path": "notiz.md"}, [str(tmp_path)], "chat",
        regeln=Regeldatei(),
    )
    assert urteil.antwort == "ja"


def test_nur_was_der_agent_nennt_ist_abschaltbar():
    regeln = Regeldatei()
    regeln.nur_was_der_agent_nennt = False
    urteil = berechtigungen.urteil(
        "web_search", {}, [], "agent", agent=_agent([]), regeln=regeln,
    )
    assert urteil.antwort == "ja"


# --- niemals: applies in every mode, to both origins ------------------------


def test_niemals_blockiert_den_agenten():
    regeln = Regeldatei()
    regeln.niemals = ("rm -rf /",)
    urteil = berechtigungen.urteil(
        "run_command", {"command": "rm -rf / --no-preserve-root"}, [], "agent",
        agent=_agent(["run_command"]), regeln=regeln,
    )
    assert urteil.antwort == "nein"
    assert "rm -rf /" in urteil.grund


def test_niemals_blockiert_auch_den_chat():
    regeln = Regeldatei()
    regeln.niemals = ("rm -rf /",)
    urteil = berechtigungen.urteil(
        "run_command", {"command": "rm -rf /"}, [], "chat", regeln=regeln,
    )
    assert urteil.antwort == "nein"


def test_niemals_greift_nicht_ohne_treffer():
    regeln = Regeldatei()
    regeln.niemals = ("rm -rf /",)
    urteil = berechtigungen.urteil(
        "run_command", {"command": "ls -la"}, [], "chat", regeln=regeln,
    )
    assert urteil.antwort == "ja"


# --- An agent cannot be asked, whatever the source of the "fragen" --------


def test_statisch_bestaetigen_bleibt_fragen_im_chat():
    urteil = berechtigungen.urteil(
        "notion_create_page", {}, [], "chat", regeln=Regeldatei(),
        statisch_bestaetigen=True,
    )
    assert urteil.antwort == "fragen"


def test_statisch_bestaetigen_wird_beim_agenten_zu_nein():
    urteil = berechtigungen.urteil(
        "notion_create_page", {}, [], "agent", agent=_agent(["notion_create_page"]),
        regeln=Regeldatei(), statisch_bestaetigen=True,
    )
    assert urteil.antwort == "nein"


def test_regeln_dict_uebersteuert_den_standard():
    regeln = Regeldatei()
    regeln.regeln["notion_create_page"] = "nein"
    urteil = berechtigungen.urteil(
        "notion_create_page", {}, [], "chat", regeln=regeln,
    )
    assert urteil.antwort == "nein"


# --- The rule file itself ---------------------------------------------------


def test_erststart_kopiert_die_vorlage():
    """First use: berechtigungen.json does not exist yet, so the shipped
    example is copied in — same pattern as mcp_servers.json."""
    regeln = laden()
    assert regeln.kaputt is None
    assert regeln.standard == {"chat": "ja", "agent": "ja"}
    assert regeln.ausserhalb_der_ordner == {"chat": "fragen", "agent": "nein"}


def test_die_vorlage_erklaert_den_wert_fragen():
    """The shipped example says what the third answer does.

    "ja" and "nein" say themselves; "fragen" does not — it is the cautious
    one, and a file that only ever shows it as a value leaves the reader to
    work out what it costs. JSON has no comments, so the sentence is a field
    of its own, first in the file, and the loader has no rule by that name:
    it must stay a note and change nothing.
    """
    from app.berechtigungsregeln import beispiel_pfad

    rohdaten = json.loads(beispiel_pfad().read_text(encoding="utf-8"))
    hinweis = rohdaten["hinweis"]
    assert "fragen" in hinweis and "cautious" in hinweis, hinweis
    # The dialog's own question, word for word. English, because this file
    # ships with the program.
    assert 'Run "tool"?' in hinweis, hinweis
    assert "ausgeführt werden?" not in hinweis, hinweis
    # The silence probe: the note is not a setting. Read as one, the file
    # says exactly what it said without it — every field, not only two.
    regeln = laden(beispiel_pfad())
    assert regeln.kaputt is None
    assert regeln.standard == {"chat": "ja", "agent": "ja"}
    assert regeln.innerhalb_der_ordner == {"chat": "ja", "agent": "ja"}
    assert regeln.ausserhalb_der_ordner == {"chat": "fragen", "agent": "nein"}
    assert regeln.niemals == ()
    assert "read_file" in regeln.dateiwerkzeuge and "run_command" in regeln.dateiwerkzeuge
    assert not hasattr(regeln, "hinweis")


def test_kaputte_regeldatei_faellt_auf_die_grundregel_zurueck(tmp_path):
    pfad = tmp_path / "berechtigungen.json"
    pfad.write_text("{kaputtes json", encoding="utf-8")
    regeln = laden(pfad)
    assert regeln.kaputt is not None
    # The hard-wired fallback: shared folders run, everything else asks/refuses.
    assert regeln.standard == {"chat": "ja", "agent": "ja"}
    assert regeln.ausserhalb_der_ordner["agent"] == "nein"


def test_regeldatei_mit_falschem_wert_wird_ignoriert(tmp_path):
    """A typo like 'jaein' must not silently become the standard — it is
    dropped and the built-in default takes over."""
    pfad = tmp_path / "berechtigungen.json"
    pfad.write_text(json.dumps({"standard": "jaein"}), encoding="utf-8")
    regeln = laden(pfad)
    assert regeln.kaputt is None
    assert regeln.standard == {"chat": "ja", "agent": "ja"}


def test_ein_unhashbarer_wert_stuerzt_nicht_ab_sondern_wird_ignoriert(tmp_path):
    """A nested object where a plain answer belongs is dropped like any
    other invalid value — not a crash in the check meant to catch it."""
    pfad = tmp_path / "berechtigungen.json"
    pfad.write_text(
        json.dumps({"regeln": {"web_search": ["ja", "nein"]}}), encoding="utf-8"
    )
    regeln = laden(pfad)
    assert regeln.kaputt is None
    assert regeln.regeln == {}


def test_dateien_als_falsche_form_stuerzt_nicht_ab(tmp_path):
    """The nested sections (dateien, regeln) must not crash the loader on
    their own — only the caller's broad except should not be what saves it."""
    from app.berechtigungsregeln import _regeldatei_aus

    for kaputt in (
        {"dateien": ["werkzeuge", "x"]},
        {"dateien": "kein objekt"},
        {"dateien": {"innerhalb_der_ordner": ["chat", "fragen"]}},
        {"regeln": ["a", "b"]},
    ):
        ergebnis = _regeldatei_aus(kaputt)
        assert ergebnis.standard == {"chat": "ja", "agent": "ja"}


# --- An agent's own permissions: — narrowing only ---------------------------


def test_agent_kann_ein_werkzeug_enger_stellen(tmp_path):
    regeln = Regeldatei()  # standard: ja for both origins
    urteil = berechtigungen.urteil(
        "web_search", {}, [], "agent",
        agent=_agent(["web_search"], {"web_search": "nein"}), regeln=regeln,
    )
    assert urteil.antwort == "nein"
    assert "web_search" in urteil.grund
    assert "permissions" in urteil.grund


def test_agent_kann_ein_erlaubtes_werkzeug_nicht_lockern(tmp_path):
    """The whole point: 'permissions: {tool: ja}' must have no effect when
    the rule file already says 'nein' — an agent cannot grant itself more."""
    regeln = Regeldatei()
    regeln.regeln["web_search"] = "nein"
    urteil = berechtigungen.urteil(
        "web_search", {}, [], "agent",
        agent=_agent(["web_search"], {"web_search": "ja"}), regeln=regeln,
    )
    assert urteil.antwort == "nein"


def test_agent_kann_pfad_regeln_nicht_lockern(tmp_path):
    """Not just the generic fallback — the load-bearing path branch (Hole A)
    is just as immune to a looser agent-level override."""
    ordner = tmp_path / "geteilt"
    ordner.mkdir()
    regeln = Regeldatei()
    regeln.ausserhalb_der_ordner["agent"] = "nein"
    urteil = berechtigungen.urteil(
        "read_file", {"path": "/etc/hosts"}, [str(ordner)], "agent",
        agent=_agent(["read_file"], {"read_file": "ja"}), regeln=regeln,
    )
    assert urteil.antwort == "nein"


def test_agent_verschaerfung_zu_fragen_wird_beim_agenten_zu_nein(tmp_path):
    regeln = Regeldatei()
    urteil = berechtigungen.urteil(
        "web_search", {}, [], "agent",
        agent=_agent(["web_search"], {"web_search": "fragen"}), regeln=regeln,
    )
    assert urteil.antwort == "nein"


def test_permissions_wirkt_nicht_im_chat(tmp_path):
    """permissions: is an agent concept — it has nothing to tighten in a
    chat, which has no Agent object at all."""
    regeln = Regeldatei()
    urteil = berechtigungen.urteil("web_search", {}, [], "chat", regeln=regeln)
    assert urteil.antwort == "ja"


def test_ungenanntes_werkzeug_bleibt_bei_loch_b_egal_was_permissions_sagt(tmp_path):
    """A tool outside tools: is refused by Hole B before permissions: is
    even consulted — listing it there does not somehow un-ban it."""
    regeln = Regeldatei()
    urteil = berechtigungen.urteil(
        "web_search", {}, [], "agent",
        agent=_agent(["read_file"], {"web_search": "ja"}), regeln=regeln,
    )
    assert urteil.antwort == "nein"
    assert "tool list" in urteil.grund


# --- End to end: the hook really lives inside ausfuehren() ------------------


@pytest.mark.asyncio
async def test_registry_ausfuehren_lehnt_ungenanntes_werkzeug_beim_agenten_ab(tmp_path):
    registry = WerkzeugRegistry(
        [], shell_an=True, berechtigungen_pfad=tmp_path / "berechtigungen.json"
    )
    with pytest.raises(WerkzeugVerboten) as ausnahme:
        await registry.ausfuehren(
            "read_file", {"path": "notiz.md"}, ordner=[str(tmp_path)],
            herkunft="agent", agent=_agent(["web_search"]),
        )
    assert "read_file" in str(ausnahme.value)


@pytest.mark.asyncio
async def test_registry_ausfuehren_lehnt_pfad_ausserhalb_beim_agenten_ab(tmp_path):
    ordner = tmp_path / "geteilt"
    ordner.mkdir()
    registry = WerkzeugRegistry(
        [], shell_an=True, berechtigungen_pfad=tmp_path / "berechtigungen.json"
    )
    with pytest.raises(WerkzeugVerboten) as ausnahme:
        await registry.ausfuehren(
            "read_file", {"path": "/etc/hosts"}, ordner=[str(ordner)],
            herkunft="agent", agent=_agent(["read_file"]),
        )
    assert "outside the shared folders" in str(ausnahme.value)


@pytest.mark.asyncio
async def test_registry_ausfuehren_laesst_genanntes_werkzeug_im_ordner_laufen(tmp_path):
    ordner = tmp_path / "geteilt"
    ordner.mkdir()
    (ordner / "notiz.md").write_text("hallo", encoding="utf-8")
    registry = WerkzeugRegistry(
        [], shell_an=True, berechtigungen_pfad=tmp_path / "berechtigungen.json"
    )
    ergebnis = await registry.ausfuehren(
        "read_file", {"path": "notiz.md"}, ordner=[str(ordner)],
        herkunft="agent", agent=_agent(["read_file"]),
    )
    assert "hallo" in ergebnis


@pytest.mark.asyncio
async def test_registry_braucht_bestaetigung_meldet_nur_fragen_nicht_nein(tmp_path):
    """A 'nein' call must not show up as 'needs confirmation' — it is a
    straight refusal, not a question (see Registry.braucht_bestaetigung)."""
    registry = WerkzeugRegistry(
        [], shell_an=True, berechtigungen_pfad=tmp_path / "berechtigungen.json"
    )
    # Outside the folders, for a chat, this is 'fragen' — True.
    assert registry.braucht_bestaetigung(
        "read_file", {"path": "/etc/hosts"}, [str(tmp_path)]
    ) is True
    # Inside them, nothing to ask about.
    assert registry.braucht_bestaetigung(
        "read_file", {"path": "notiz.md"}, [str(tmp_path)]
    ) is False


async def test_bestaetigungsgrund_hat_einen_text_auch_ohne_pfad_ausserhalb(tmp_path):
    """Restricted mode (or an operator's own per-tool rule) can land on
    'fragen' for a path INSIDE the shared folders — bestaetigungsgrund's own
    path check finds nothing there and must not fall back to None, or the
    confirmation prompt goes out with no reason at all."""
    pfad = tmp_path / "berechtigungen.json"
    pfad.write_text(
        json.dumps({"dateien": {"innerhalb_der_ordner": {"chat": "fragen"}}}),
        encoding="utf-8",
    )
    registry = WerkzeugRegistry([], shell_an=True, berechtigungen_pfad=pfad)
    ordner = [str(tmp_path)]
    assert registry.braucht_bestaetigung("read_file", {"path": "notiz.md"}, ordner) is True
    grund = registry.bestaetigungsgrund("read_file", {"path": "notiz.md"}, ordner)
    assert grund is not None
    assert grund[0] == "werkzeug.grund_bestaetigung"


def test_die_zugriffslage_liest_die_regeln_je_herkunft():
    """The two words the prompt says come from the rules the gate applies —
    and for an agent, "asks" outside is "no", the gate's own reading."""
    from app.berechtigungen import zugriffslage

    regeln = Regeldatei()
    assert zugriffslage("chat", regeln) == ("ja", "fragen")
    assert zugriffslage("agent", regeln) == ("ja", "nein")
    regeln.innerhalb_der_ordner["chat"] = "fragen"
    regeln.ausserhalb_der_ordner["chat"] = "nein"
    assert zugriffslage("chat", regeln) == ("fragen", "nein")


# --- The memory: no mode has a say -------------------------------------------


@pytest.mark.parametrize("herkunft", ["chat", "agent"])
@pytest.mark.parametrize("modus", ["fragen", "nein"])
def test_the_memory_tool_asks_in_no_mode_and_in_no_run(herkunft, modus):
    """Saving, changing and deleting an entry ask nothing — in the manual
    mode, in a job where "ask" would turn into "no", and in the strictest
    standard alike."""
    regeln = Regeldatei(standard={"chat": modus, "agent": modus})
    urteil = berechtigungen.urteil(
        "memory_save", {"remove": "Tee"}, [], herkunft,
        agent=_agent(["memory_save"]) if herkunft == "agent" else None, regeln=regeln,
    )
    assert urteil.antwort == "ja"


def test_silence_another_tool_still_follows_the_mode():
    regeln = Regeldatei(standard={"chat": "fragen", "agent": "fragen"})
    assert berechtigungen.urteil(
        "some_other_tool", {}, [], "chat", regeln=regeln,
    ).antwort == "fragen"


def test_a_rule_the_user_wrote_for_the_memory_tool_still_wins():
    regeln = Regeldatei(regeln={"memory_save": "nein"})
    assert berechtigungen.urteil(
        "memory_save", {"text": "x", "kind": "fact"}, [], "chat", regeln=regeln,
    ).antwort == "nein"


def test_an_agent_can_still_tighten_the_memory_tool_for_itself():
    urteil = berechtigungen.urteil(
        "memory_save", {"text": "x", "kind": "fact"}, [], "agent",
        agent=_agent(["memory_save"], {"memory_save": "nein"}), regeln=Regeldatei(),
    )
    assert urteil.antwort == "nein"
