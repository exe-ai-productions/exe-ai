"""A no to a tool may carry the user's own words: what to do instead.

The permission box's last row sends them with the refusal. The tool must not
run, and the words must reach the model with it — a string arriving where a
yes or a no is expected must never pass for a yes.
"""

from __future__ import annotations

import asyncio

from app.api.v1.generierung import bestaetigen as confirm_route
from app.api.v1.schemas import BestaetigungAnfrage
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from tests.conftest import provider_setzen

WORDS = "Use the build script in the tools folder instead"


def _answer_once_asked(client, config, fields):
    """Answers through the real confirm route function once the prompt is
    up — it only exists while the request that asks for it is running."""
    manager = client.app.state.generierungen

    def attempt():
        for run in manager.laufende():
            for call_id in list(run.bestaetigungen):
                confirm_route(
                    BestaetigungAnfrage(generation_id=run.id, aufruf_id=call_id, **fields),
                    generierungen=manager,
                    config=config,
                )
                return True
        return False

    def tick():
        if not attempt():
            asyncio.get_running_loop().call_later(0.01, tick)

    asyncio.get_running_loop().call_later(0.01, tick)


class _AskingTool:
    """A tool that always asks first, and schedules the answer from inside
    `braucht_bestaetigung` — the one moment the prompt actually exists."""

    def __init__(self, client, config, fields):
        self.calls = []
        self._client = client
        self._config = config
        self._fields = fields

    def als_openai_werkzeuge(self, **_options):
        return [{"type": "function", "function": {"name": "terminal", "parameters": {}}}]

    def braucht_bestaetigung(self, name, argumente=None, ordner=None):
        _answer_once_asked(self._client, self._config, self._fields)
        return True

    def server_von(self, name):
        return ""

    def bestaetigungsgrund(self, name, argumente=None, ordner=None):
        return ""

    async def ausfuehren(self, name, argumente, bild_senke=None, **_context):
        self.calls.append((name, argumente))
        return "built"


def _run(client, config, chat_id, **fields):
    client.app.state.config.features.mcp = True
    tool = _AskingTool(client, config, fields)
    client.app.state.werkzeuge = tool
    provider = MockProvider(
        mock_endpunkt("test"),
        haeppchen=["ok"],
        werkzeugaufrufe=[
            Werkzeugaufruf(id="a1", name="terminal", argumente={"command": "npm run build"})
        ],
    )
    provider_setzen(client, provider)
    response = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "build it"},
    )
    assert response.status_code == 200
    return tool, provider, response


def _tool_result_for_model(provider):
    second_round = provider.alle_anfragen[1]
    return [n for n in second_round.nachrichten if n.role == "tool"][-1].content


def test_a_no_with_words_does_not_run_the_tool(config, client, chat_id):
    tool, _, _ = _run(client, config, chat_id, erlaubt=False, antwort=WORDS)
    assert tool.calls == []


def test_the_words_reach_the_model_with_the_refusal(config, client, chat_id):
    _, provider, _ = _run(client, config, chat_id, erlaubt=False, antwort=WORDS)
    result = _tool_result_for_model(provider)
    assert WORDS in result
    assert "terminal" in result


def test_a_plain_no_stays_a_plain_no(config, client, chat_id):
    """The silence probe: without words the refusal says what it always
    said, and the tool still does not run."""
    tool, provider, _ = _run(client, config, chat_id, erlaubt=False)
    assert tool.calls == []
    assert WORDS not in _tool_result_for_model(provider)


def test_a_yes_still_runs_the_tool(config, client, chat_id):
    tool, _, _ = _run(client, config, chat_id, erlaubt=True)
    assert tool.calls == [("terminal", {"command": "npm run build"})]
