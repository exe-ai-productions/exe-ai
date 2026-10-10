"""Every side request goes out with the messages and no tools: a fold's
summary request and a job's handoff request alike (app/faltversuche.py
``without_tools``).

Offered the run's tools, a model can answer such a request with a call
instead of the text it was asked for. The reader takes text only, so the
answer counted as empty: the fold was lost, and a job's handoff ended the
run as failed.
"""

from __future__ import annotations

import copy

from app import faltversuche, zwischenstand
from app.providers import Generierungsanfrage, MockProvider, mock_endpunkt
from app.providers.base import ChatNachricht
from tests.conftest import provider_setzen
from tests.test_auftraege_api import (
    HANDOFF_ZWEI_PUNKTE,
    NahezuVollerKontext,
    agent_schreiben,
    auf_ende_warten,
)
from tests.test_auftraege_api import mcp_client as _mcp_client

mcp_client = _mcp_client


class _RecordingAtSend(NahezuVollerKontext):
    """Notes, at the moment of sending, whether a request was the handoff
    and which tools it offered — the run's list of messages is shared and
    mutated afterwards, so it cannot be read back later."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sent: list[tuple[bool, list]] = []
        self.handoff_requests: list = []

    async def streamen(self, anfrage):
        last = anfrage.nachrichten[-1]
        handoff = last.role == "user" and last.content == zwischenstand.ANFRAGE_TEXT
        self.sent.append((handoff, list(anfrage.werkzeuge or [])))
        if handoff:
            self.handoff_requests.append(copy.deepcopy(anfrage))
        else:
            # The first round stays well under the handoff, so the history
            # the handoff carries holds a tool call and its result.
            rounds = sum(1 for was_handoff, _ in self.sent if not was_handoff)
            self.tokens = 100 if rounds == 1 else 950
        async for piece in super().streamen(anfrage):
            yield piece


def test_the_job_handoff_goes_out_without_tools(config, mcp_client):
    agent_schreiben(config, kopf="model: test\ntools: [addieren]")
    provider = provider_setzen(
        mcp_client, _RecordingAtSend(mock_endpunkt("test"), handoff_text=HANDOFF_ZWEI_PUNKTE)
    )
    mcp_client.app.state.discovery.zustaende["test"].context_tokens = 1000

    job_id = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    data = auf_ende_warten(mcp_client, job_id)

    assert data["end_reason"] == "kontext_voll"
    handoffs = [tools for handoff, tools in provider.sent if handoff]
    rounds = [tools for handoff, tools in provider.sent if not handoff]
    assert handoffs
    assert all(tools == [] for tools in handoffs)
    # Schweigeprobe: the run's own rounds keep their tools.
    assert rounds and all(rounds)

    # And no message in the shape only a request offering tools may carry:
    # the calls and their results went out as text.
    handoff = provider.handoff_requests[0]
    assert all(n.role != "tool" and not n.werkzeugaufrufe for n in handoff.nachrichten)
    assert any("addieren" in (n.content or "") for n in handoff.nachrichten)

    # As the two wires write it: Anthropic refuses tool_use / tool_result
    # blocks without tools, and an OpenAI-style server a tool role.
    from app.config import EndpointConfig
    from app.providers.anthropic import AnthropicProvider
    from app.providers.openai_kompatibel import OpenAIKompatiblerProvider

    anthropic = AnthropicProvider(EndpointConfig.model_validate({
        "id": "anthropic", "provider": "anthropic",
        "base_url": "https://api.anthropic.com/v1", "parameter_dialect": "anthropic",
        "api_key_env": "TEST_ANTHROPIC_KEY",
    }))._koerper_bauen(handoff)
    blocks = [
        block
        for message in anthropic["messages"]
        if isinstance(message["content"], list)
        for block in message["content"]
    ]
    assert "tools" not in anthropic
    assert not any(b.get("type") in {"tool_use", "tool_result"} for b in blocks)

    openai = OpenAIKompatiblerProvider(EndpointConfig.model_validate(
        {"id": "local", "name": "local", "base_url": "http://127.0.0.1:9/v1"}
    ))._koerper_bauen(handoff)
    assert "tools" not in openai
    assert all(m["role"] != "tool" and not m.get("tool_calls") for m in openai["messages"])


class _Recording(MockProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sent: list = []

    async def streamen(self, anfrage):
        self.sent.append(anfrage)
        async for piece in super().streamen(anfrage):
            yield piece


async def test_the_fold_request_drops_tools_wherever_it_comes_from():
    """The rule sits at the one place a fold request goes out: a caller
    that hands one in with tools still sends none."""
    provider = _Recording(mock_endpunkt("test"), haeppchen=["summary"])
    state = type("State", (), {"provider": provider})()
    tools = [{"type": "function", "function": {"name": "addieren"}}]
    request = Generierungsanfrage(
        modell="m",
        nachrichten=[ChatNachricht(role="user", content="fold")],
        werkzeuge=tools,
    )

    text = await faltversuche.anfordern(state, request)

    assert text == "summary"
    assert provider.sent[0].werkzeuge == []
    # The caller's request keeps its tools: only the copy went out without.
    assert request.werkzeuge == tools


def test_silent_a_request_without_tools_is_handed_back_as_it_is():
    request = Generierungsanfrage(modell="m", nachrichten=[])
    assert faltversuche.without_tools(request) is request
