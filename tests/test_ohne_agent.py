"""A scheduled task with no agent (app/ohne_agent.py): what the run may do."""

from __future__ import annotations

from app import helper, ohne_agent
from app.agenten import agent_aus_text


class Registry:
    def __init__(self, names):
        self._names = names

    def namen(self):
        return list(self._names)


def test_der_lauf_hat_die_freigegebenen_werkzeuge_ohne_die_gesperrten():
    names = ["web_search", "run_command", *sorted(helper.BLOCKED_TOOLS)]
    agent = ohne_agent.agent(Registry(names))
    assert agent.werkzeuge == ["web_search", "run_command"]
    assert not set(agent.werkzeuge) & helper.BLOCKED_TOOLS


def test_der_lauf_hat_keine_ordner_und_keine_eigene_anweisung():
    agent = ohne_agent.agent(Registry(["web_search"]))
    assert agent.ordner == []
    assert agent.prompt == ""
    assert agent.name == ohne_agent.NAME


def test_der_name_steht_fuer_den_lauf_ohne_agent():
    agent = helper.agent_named(ohne_agent.NAME, {}, None, Registry(["web_search"]))
    assert agent is not None
    assert agent.werkzeuge == ["web_search"]
    # Silence test: a name that stands for nothing stays nothing.
    assert helper.agent_named("verschwunden", {}, None, Registry([])) is None


def test_eine_datei_unter_dem_namen_der_markierung_laeuft_nie_als_sie_selbst():
    """The marker is resolved before any file: an agent file carrying its
    name never runs in its place."""
    datei = agent_aus_text(ohne_agent.NAME, "---\ntools: []\n---\n\nPrompt.\n")
    agent = helper.agent_named(
        ohne_agent.NAME, {ohne_agent.NAME: datei}, None, Registry(["web_search"])
    )
    assert agent is not datei
    assert agent.werkzeuge == ["web_search"]


def test_die_gesperrten_werkzeuge_werden_hart_abgewiesen():
    """Not offered, and refused all the same when called — whatever the
    rule file says about agents' own lists."""
    for name in helper.BLOCKED_TOOLS:
        assert helper.refused_call(ohne_agent.NAME, name)
    # Silence test: an approved tool, and a named agent, are not refused here.
    assert helper.refused_call(ohne_agent.NAME, "web_search") is None
    assert helper.refused_call("recherche", sorted(helper.BLOCKED_TOOLS)[0]) is None
