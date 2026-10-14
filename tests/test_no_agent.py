"""A scheduled task with no agent (app/no_agent.py): what the run may do."""

from __future__ import annotations

from app import helper, no_agent
from app.agenten import agent_aus_text


class Registry:
    def __init__(self, names):
        self._names = names

    def namen(self):
        return list(self._names)


def test_der_lauf_hat_die_freigegebenen_werkzeuge_ohne_die_gesperrten():
    names = ["web_search", "run_command", *sorted(helper.BLOCKED_TOOLS)]
    agent = no_agent.agent(Registry(names))
    # The schedule's own note stays with it: the four blocked ones are the
    # questions, the memory, schedules and further runs.
    assert agent.werkzeuge == ["web_search", "run_command", "cron_note"]
    assert not set(agent.werkzeuge) & helper.BLOCKED_WITHOUT_AGENT
    assert helper.BLOCKED_WITHOUT_AGENT == helper.BLOCKED_TOOLS - {"cron_note"}


def test_a_run_without_agent_may_keep_its_note_where_a_helper_may_not():
    assert helper.refused_call(no_agent.NAME, "cron_note") is None
    # Silence probe: a helper stays held to the whole list, the note included.
    assert helper.refused_call("helper", "cron_note") == helper.NOT_FOR_HELPERS
    assert "cron_note" in helper.BLOCKED_TOOLS


def test_der_lauf_hat_keine_ordner_und_keine_eigene_anweisung():
    agent = no_agent.agent(Registry(["web_search"]))
    assert agent.ordner == []
    assert agent.prompt == ""
    assert agent.name == no_agent.NAME


def test_der_name_steht_fuer_den_lauf_ohne_agent():
    agent = helper.agent_named(no_agent.NAME, {}, None, Registry(["web_search"]))
    assert agent is not None
    assert agent.werkzeuge == ["web_search"]
    # Silence test: a name that stands for nothing stays nothing.
    assert helper.agent_named("verschwunden", {}, None, Registry([])) is None


def test_eine_datei_unter_dem_namen_der_markierung_laeuft_nie_als_sie_selbst():
    """The marker is resolved before any file: an agent file carrying its
    name never runs in its place."""
    datei = agent_aus_text(no_agent.NAME, "---\ntools: []\n---\n\nPrompt.\n")
    agent = helper.agent_named(
        no_agent.NAME, {no_agent.NAME: datei}, None, Registry(["web_search"])
    )
    assert agent is not datei
    assert agent.werkzeuge == ["web_search"]


def test_die_gesperrten_werkzeuge_werden_hart_abgewiesen():
    """Not offered, and refused all the same when called — whatever the
    rule file says about agents' own lists."""
    for name in helper.BLOCKED_WITHOUT_AGENT:
        assert helper.refused_call(no_agent.NAME, name)
    # Silence test: an approved tool, and a named agent, are not refused here.
    assert helper.refused_call(no_agent.NAME, "web_search") is None
    assert helper.refused_call("recherche", sorted(helper.BLOCKED_TOOLS)[0]) is None


# --- What the run actually gets ---------------------------------------------


def test_a_run_without_agent_gets_no_folders_not_even_the_dock(config, client, monkeypatch):
    """The module says it names no folders and none are added: neither the
    dock nor the picture folder a run otherwise gets behind its own."""
    import asyncio
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    from app import dokumentablage
    from app.api.v1 import auftraege
    from app.providers import MockProvider, mock_endpunkt
    from tests.conftest import provider_setzen
    from tests.test_helper import PromptSeen
    from tests.test_auftraege_api import auf_ende_warten

    seen = PromptSeen()
    monkeypatch.setattr(auftraege, "grundprompt", seen)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["done"]))
    repositories = client.app.state.repositories
    repositories.cronjobs.erstellen(
        agent=no_agent.NAME, task="Kaffee", zeitplan="12:00", herkunft="chat"
    )
    # An agent of its own, fired beside it, is the silence probe.
    (Path(config.app.agenten_verzeichnis)).mkdir(parents=True, exist_ok=True)
    (Path(config.app.agenten_verzeichnis) / "eigener.md").write_text(
        "---\n---\n\nPrompt.\n", encoding="utf-8"
    )
    repositories.cronjobs.erstellen(
        agent="eigener", task="Tee", zeitplan="12:00", herkunft="chat"
    )
    morgen = datetime.now(timezone.utc).replace(
        hour=13, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)

    asyncio.run(client.app.state.wecker.einmal_pruefen(jetzt=morgen))
    for job in client.get("/api/v1/jobs").json():
        auf_ende_warten(client, job["id"])

    dock, pictures = dokumentablage.program_folders(config)
    # One run with no folder at all, and the named agent's with the program's
    # two behind it.
    folders = sorted(tuple(call["ordner"]) for call in seen.calls)
    assert folders == [(), (dock, pictures)]
