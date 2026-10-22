"""The thinking stage an agent file names (``reasoning_effort``).

A run of the agent asks for the stage through the same switch a chat does,
so the two cannot send different fields for the same stage. A file that names
no stage sends no thinking field, as before.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import denkschalter
from app.agenten import AgentDateiKaputt, agent_aus_text
from app.config import Capabilities
from app.providers import MockProvider
from tests.conftest import provider_setzen
from tests.test_auftraege_api import agent_schreiben, auf_ende_warten

MASK = Path(__file__).resolve().parent.parent / "frontend" / "src" / "teile" / "Agentenmaske.svelte"


def _agent(header: str):
    return agent_aus_text("probe", f"---\n{header}\n---\n\nDu bist ein Test.\n")


def _as_openai(client, model: str = "gpt-5.6"):
    """The test endpoint, dressed up as the named model of a provider whose
    switch carries stages — the switch reads dialect, address and model name."""
    state = client.app.state.discovery.zustaende["test"]
    state.endpunkt = state.endpunkt.model_copy(
        update={
            "parameter_dialect": "openai",
            "base_url": "https://api.openai.com/v1",
            "modell": model,
        }
    )
    state.gemeldeter_name = model
    return state


def _run_job(client, config, header: str, provider: MockProvider) -> list:
    agent_schreiben(config, kopf=f"model: test\nmax_rounds: 3\n{header}")
    provider = provider_setzen(client, provider)
    job_id = client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Los"}).json()["id"]
    assert auf_ende_warten(client, job_id)["state"] == "fertig"
    assert provider.alle_anfragen
    return provider.alle_anfragen


# --- The file ---------------------------------------------------------------


def test_an_agent_file_may_name_a_thinking_stage():
    assert _agent("reasoning_effort: high").thinking_stage == "high"


def test_the_stage_is_read_in_lower_case():
    assert _agent("reasoning_effort: Medium").thinking_stage == "medium"


def test_a_bare_off_in_the_header_is_the_word_and_not_a_truth_value():
    assert _agent("reasoning_effort: off").thinking_stage == "off"
    assert _agent("reasoning_effort: on").thinking_stage == "on"


def test_without_the_field_the_agent_has_no_opinion():
    assert _agent("max_rounds: 3").thinking_stage is None


def test_an_empty_field_says_nothing_like_a_missing_one():
    assert _agent("reasoning_effort:").thinking_stage is None
    assert _agent('reasoning_effort: ""').thinking_stage is None


@pytest.mark.parametrize("word", ["hihg", "5", "[high]"])
def test_an_unknown_word_is_caught_when_the_file_is_read(word):
    with pytest.raises(AgentDateiKaputt) as error:
        _agent(f"reasoning_effort: {word}")
    assert "reasoning_effort" in str(error.value)


def test_the_field_is_not_reported_as_unknown(caplog):
    _agent("reasoning_effort: low")
    assert "reasoning_effort" not in caplog.text


def test_the_agent_list_names_the_stage_and_the_form_saves_it(client, config):
    agent_schreiben(config)
    reply = client.put(
        "/api/v1/agents/recherche/fields", json={"reasoning_effort": "high"}
    )
    assert reply.status_code == 200, reply.text
    content = Path(config.app.agenten_verzeichnis, "recherche.md").read_text(encoding="utf-8")
    assert 'reasoning_effort: "high"' in content
    listing = {a["name"]: a for a in client.get("/api/v1/agents").json()}
    assert listing["recherche"]["reasoning_effort"] == "high"
    # An explicit null takes it away again, the way the form says "Auto".
    client.put("/api/v1/agents/recherche/fields", json={"reasoning_effort": None})
    listing = {a["name"]: a for a in client.get("/api/v1/agents").json()}
    assert listing["recherche"]["reasoning_effort"] is None


def test_the_form_refuses_a_nonsense_word_before_writing(client, config):
    agent_schreiben(config)
    reply = client.put(
        "/api/v1/agents/recherche/fields", json={"reasoning_effort": "hihg"}
    )
    assert reply.status_code == 422


def test_the_mask_carries_the_stage_in_its_own_field(client):
    source = MASK.read_text(encoding="utf-8")
    assert "reasoning_effort: thinkingStage || null" in source
    assert "thinkingStage = quelle?.reasoning_effort ?? ''" in source
    assert "<Auswahlfeld bind:wert={thinkingStage}" in source


# --- The run ----------------------------------------------------------------


def test_a_job_sends_the_same_fields_as_a_chat_at_the_same_stage(
    client, config, chat_id
):
    """Both ways in one test: the job's rounds and a chat's turn, for the same
    stage on the same model, carry the very same request fields."""
    state = _as_openai(client)
    expected = denkschalter.zusatz("low", state, modell="gpt-5.6")
    assert expected, "this model has a stage; the test would prove nothing without one"

    rounds = _run_job(client, config, "reasoning_effort: low", MockProvider(haeppchen=["ok"]))
    assert all(request.zusatz == expected for request in rounds)

    chat = provider_setzen(client, MockProvider(haeppchen=["ok"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Hallo", "thinking": "low"},
    )
    assert chat.letzte_anfrage.zusatz == expected


def test_a_job_without_the_field_sends_no_thinking_field(client, config):
    """Silence probe: nothing is named, so nothing goes out — not even the
    route fields a chat carries."""
    _as_openai(client)
    rounds = _run_job(client, config, "max_tokens: 4000", MockProvider(haeppchen=["ok"]))
    assert all(request.zusatz == {} for request in rounds)


def test_a_stage_the_model_lacks_behaves_as_in_a_chat(client, config, chat_id):
    """A model with no stage at all: the job goes through, with exactly what
    the chat sends for the same word."""
    _as_openai(client, model="gpt-4.1")

    rounds = _run_job(client, config, "reasoning_effort: high", MockProvider(haeppchen=["ok"]))

    chat = provider_setzen(client, MockProvider(haeppchen=["ok"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Hallo", "thinking": "high"},
    )
    assert all(request.zusatz == chat.letzte_anfrage.zusatz for request in rounds)


def test_off_in_the_agent_takes_the_thinking_length_out_of_the_job(client, config):
    """Off beside a thinking length would be two contradicting answers: the
    switch goes out and the length stays home, like in a chat."""
    state = client.app.state.discovery.zustaende["test"]
    state.endpunkt = state.endpunkt.model_copy(
        update={
            "parameter_dialect": "llama_cpp",
            "base_url": "http://127.0.0.1:9/v1",
            "capabilities": Capabilities(streaming=True, tool_calls=True, thinking=True),
        }
    )
    expected, _ = denkschalter.ausschalten(state, {}, modell=state.endpunkt.modell)
    assert expected, "this model has a switch; the test would prove nothing without one"

    rounds = _run_job(
        client,
        config,
        "reasoning_budget: 2048\nreasoning_effort: off",
        MockProvider(haeppchen=["ok"]),
    )
    assert all(request.zusatz == expected for request in rounds)
    assert all("reasoning_budget" not in request.parameter for request in rounds)
