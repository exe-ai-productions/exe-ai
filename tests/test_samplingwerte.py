"""Sampling values a model refuses never reach the wire.

Checked on the finished request body of both providers, the one thing a model
server actually reads — keyed on the model name, so a local server speaking
the OpenAI protocol keeps every value it was given.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app import denkschalter
from app.config import EndpointConfig
from app.providers.anthropic import AnthropicProvider
from app.providers.base import ChatNachricht, Generierungsanfrage
from app.providers.openai_kompatibel import OpenAIKompatiblerProvider

# Every value a test hands over is set here, by the test — none of them is a
# default anything relies on.
TEMPERATUR = 0.3
TOP_P = 0.8
TOP_K = 20
STRAFE = 0.4
SEED = 7


def _anfrage(modell: str) -> Generierungsanfrage:
    return Generierungsanfrage(
        nachrichten=[ChatNachricht(role="user", content="Hello")],
        modell=modell,
        max_tokens=1000,
        temperature=TEMPERATUR,
        top_p=TOP_P,
        parameter={
            "top_k": TOP_K,
            "presence_penalty": STRAFE,
            "frequency_penalty": STRAFE,
            "seed": SEED,
        },
    )


def _anthropic(modell: str) -> dict[str, Any]:
    endpunkt = EndpointConfig.model_validate({
        "id": "anthropic",
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "parameter_dialect": "anthropic",
    })
    return AnthropicProvider(endpunkt)._koerper_bauen(_anfrage(modell))


def _openai(modell: str, basis: str = "https://api.openai.com/v1", dialekt: str = "openai") -> dict[str, Any]:
    endpunkt = EndpointConfig.model_validate(
        {"id": "wolke", "base_url": basis, "parameter_dialect": dialekt}
    )
    return OpenAIKompatiblerProvider(endpunkt)._koerper_bauen(_anfrage(modell))


# --- Anthropic ----------------------------------------------------------------


@pytest.mark.parametrize(
    "modell", ["claude-sonnet-4-5", "claude-sonnet-4-5-20250929", "claude-opus-4-6", "claude-3-7-sonnet"]
)
def test_eine_familie_die_sampling_nimmt_behaelt_die_werte(modell):
    koerper = _anthropic(modell)
    assert koerper["temperature"] == TEMPERATUR
    assert koerper["top_p"] == TOP_P
    assert koerper["top_k"] == TOP_K


def test_ein_neues_claude_modell_bekommt_kein_sampling():
    koerper = _anthropic("claude-opus-5")
    assert not {"temperature", "top_p", "top_k"} & koerper.keys()
    assert koerper["max_tokens"] == 1000


def test_ein_unbekanntes_claude_modell_gilt_als_neu():
    """The core of the list that keeps the OLD families: a model nobody has
    written down yet refuses the values too, instead of quietly getting them."""
    koerper = _anthropic("claude-erfunden-9")
    assert not {"temperature", "top_p", "top_k"} & koerper.keys()


# --- OpenAI ---------------------------------------------------------------------


@pytest.mark.parametrize("modell", ["gpt-5.6", "gpt-5.6-luna", "o3-mini", "o1"])
def test_gpt5_und_die_o_serie_bekommen_weder_sampling_noch_strafen(modell):
    koerper = _openai(modell)
    assert not {"temperature", "top_p", "presence_penalty", "frequency_penalty"} & koerper.keys()
    # What the model does take stays.
    assert koerper["seed"] == SEED
    assert koerper["max_completion_tokens"] == 1000


def test_der_umbenannte_name_haengt_am_wirt_nicht_am_pfad():
    """The second half of the same finding: `api.openai.com` was searched in
    the whole address, so a proxy at `https://proxy.test/api.openai.com/v1`
    had `max_tokens` renamed to `max_completion_tokens` — and every request
    to it refused, because that server wants the old name."""
    koerper = _openai("gpt-5.6", basis="https://proxy.test/api.openai.com/v1")
    assert koerper["max_tokens"] == 1000
    assert "max_completion_tokens" not in koerper


def test_ein_name_der_nur_so_anfaengt_ist_nicht_der_wirt():
    """`api.openai.com.example.net` is somebody else's machine. Matched as a
    piece of the host, it got the rename and answered 400."""
    koerper = _openai("gpt-5.6", basis="https://api.openai.com.example.net/v1")
    assert koerper["max_tokens"] == 1000
    assert "max_completion_tokens" not in koerper


def test_am_echten_wirt_wird_weiter_umbenannt():
    """The silence test: OpenAI itself keeps the new name, with or without a
    scheme in front of it — and so does a real sub-domain of it."""
    assert _openai("gpt-5.6")["max_completion_tokens"] == 1000
    assert _openai("gpt-5.6", basis="api.openai.com/v1")["max_completion_tokens"] == 1000
    assert _openai(
        "gpt-5.6", basis="https://eu.api.openai.com/v1"
    )["max_completion_tokens"] == 1000


def test_ein_lokales_modell_ueber_den_openai_dialekt_behaelt_alles():
    """The silence test: the rule is keyed on the model name, never on the
    dialect, so a local server keeps every value it was given."""
    koerper = _openai("Qwen3.5-9B", basis="http://127.0.0.1:8080/v1", dialekt="llama_cpp")
    assert koerper["temperature"] == TEMPERATUR
    assert koerper["top_p"] == TOP_P
    assert koerper["top_k"] == TOP_K
    assert koerper["presence_penalty"] == STRAFE
    assert koerper["frequency_penalty"] == STRAFE
    koerper = _openai("Qwen3.5-9B", basis="http://127.0.0.1:8000/v1")
    assert koerper["temperature"] == TEMPERATUR
    assert koerper["presence_penalty"] == STRAFE


@pytest.mark.parametrize(
    "modell", ["Qwen3-14B-Claude-Opus-4.7-Reasoning-Distill", "qwen3-8b-claude-distill-gguf"]
)
def test_ein_lokales_modell_mit_claude_im_namen_behaelt_alles(modell):
    """A fine-tune named after the model it learned from is not that model."""
    koerper = _openai(modell, basis="http://127.0.0.1:8080/v1", dialekt="llama_cpp")
    assert koerper["temperature"] == TEMPERATUR
    assert koerper["top_p"] == TOP_P
    assert koerper["top_k"] == TOP_K


@pytest.mark.parametrize("modell", ["anthropic/claude-opus-5", "anthropic.claude-opus-5-v1:0"])
def test_ein_claude_modell_hinter_einem_anbieterpraefix_bekommt_kein_sampling(modell):
    koerper = _openai(modell, basis="https://openrouter.ai/api/v1")
    assert not {"temperature", "top_p"} & koerper.keys()


def test_ohne_modellnamen_bleibt_alles():
    endpunkt = EndpointConfig.model_validate({"id": "lokal", "base_url": "http://127.0.0.1:8080/v1"})
    anfrage = _anfrage("")
    anfrage.modell = None
    koerper = OpenAIKompatiblerProvider(endpunkt)._koerper_bauen(anfrage)
    assert "model" not in koerper
    assert koerper["temperature"] == TEMPERATUR


# --- Kimi and Arcee ---------------------------------------------------------------


@pytest.mark.parametrize("modell", ["kimi-k2-turbo-preview", "moonshotai/kimi-k2"])
def test_kimi_bekommt_keine_temperatur(modell):
    koerper = _openai(modell, basis="https://api.moonshot.ai/v1")
    assert "temperature" not in koerper
    assert koerper["top_p"] == TOP_P


@pytest.mark.parametrize("modell", ["trinity-large-thinking", "arcee-ai/trinity-large-thinking"])
def test_arcee_trinity_thinking_laeuft_mit_fester_temperatur(modell):
    koerper = _openai(modell, basis="https://openrouter.ai/api/v1")
    assert koerper["temperature"] == 0.5
    anfrage = _anfrage(modell)
    anfrage.temperature = None
    endpunkt = EndpointConfig.model_validate({"id": "wolke", "base_url": "https://openrouter.ai/api/v1"})
    assert OpenAIKompatiblerProvider(endpunkt)._koerper_bauen(anfrage)["temperature"] == 0.5


# --- Anthropic budget thinking forces temperature 1 --------------------------


def _budget_zustand(modell: str) -> SimpleNamespace:
    endpunkt = SimpleNamespace(
        capabilities=SimpleNamespace(thinking=["off", "on"]),
        parameter_dialect="anthropic",
        base_url="https://api.anthropic.com/v1",
        modell=modell,
    )
    return SimpleNamespace(endpunkt=endpunkt, gemeldeter_name=modell, faehigkeiten_erkannt={})


def _anthropic_mit_denken(modell: str, stufe: str, max_tokens: int = 64_000) -> dict[str, Any]:
    endpunkt = EndpointConfig.model_validate({
        "id": "anthropic",
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "parameter_dialect": "anthropic",
    })
    anfrage = _anfrage(modell)
    anfrage.max_tokens = max_tokens
    anfrage.zusatz = denkschalter.zusatz(
        stufe, _budget_zustand(modell), modell=modell, max_tokens=max_tokens
    )
    return AnthropicProvider(endpunkt)._koerper_bauen(anfrage)


@pytest.mark.parametrize("modell", ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"])
def test_budget_denken_erzwingt_temperatur_eins_trotz_eigener_einstellung(modell):
    """Anthropic refuses any other temperature beside a manual thinking
    budget with a 400 — whatever a caller set (TEMPERATUR, not 1)."""
    koerper = _anthropic_mit_denken(modell, "on")
    assert koerper["thinking"]["type"] == "enabled"
    assert koerper["thinking"]["budget_tokens"] > 0
    assert koerper["temperature"] == 1


def test_denken_aus_behaelt_die_eingestellte_temperatur():
    koerper = _anthropic_mit_denken("claude-sonnet-4-5", "off")
    assert koerper["thinking"]["type"] != "enabled"
    assert koerper["temperature"] == TEMPERATUR


def test_ein_zu_kleiner_deckel_schaltet_denken_ab_und_behaelt_die_temperatur():
    """The silence probe: a ceiling that pushes the budget
    below MINDEST_BUDGET sends the request without a thinking pass — and
    without the temperature override that pass would have needed."""
    koerper = _anthropic_mit_denken(
        "claude-sonnet-4-5", "on", max_tokens=denkschalter.MINDEST_BUDGET
    )
    assert koerper["thinking"]["type"] != "enabled"
    assert koerper["temperature"] == TEMPERATUR


def test_ein_gesenkter_deckel_der_denken_abschaltet_behaelt_die_temperatur():
    """The context-overflow retry (app/kontextvoll.py) rebuilds the extra
    fields with mit_deckel on the ALREADY-BUILT dict, not through zusatz()
    again — if the shrunk budget then falls below MINDEST_BUDGET, thinking
    turns off for this one retry, and the override that came with it must
    not survive alongside it."""
    modell = "claude-sonnet-4-5"
    zustand = _budget_zustand(modell)
    gebaut = denkschalter.zusatz("on", zustand, modell=modell, max_tokens=64_000)
    gesenkt = denkschalter.mit_deckel(
        gebaut, denkschalter.MINDEST_BUDGET, denkschalter.aus_wort(zustand, modell=modell)
    )
    endpunkt = EndpointConfig.model_validate({
        "id": "anthropic",
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "parameter_dialect": "anthropic",
    })
    anfrage = _anfrage(modell)
    anfrage.zusatz = gesenkt
    koerper = AnthropicProvider(endpunkt)._koerper_bauen(anfrage)
    assert koerper["thinking"]["type"] != "enabled"
    assert koerper["temperature"] == TEMPERATUR


def test_ein_modell_auf_dem_openai_draht_behaelt_die_eingestellte_temperatur():
    """The silence probe on the other wire: the Anthropic dialect is the
    only one whose thinking switch ever carries a token budget
    (app/denkschalter.py, zusatz() routes on dialect) — reached through an
    OpenAI-compatible endpoint, the very same stage never builds one, so
    nothing here forces its temperature."""
    modell = "claude-sonnet-4-5"
    zustand = _budget_zustand(modell)
    zustand.endpunkt.parameter_dialect = "openai"
    gebaut = denkschalter.zusatz("on", zustand, modell=modell, max_tokens=64_000)
    assert "budget_tokens" not in (gebaut.get("thinking") or {})

    endpunkt = EndpointConfig.model_validate(
        {"id": "wolke", "base_url": "https://api.anthropic.com/v1", "parameter_dialect": "openai"}
    )
    anfrage = _anfrage(modell)
    anfrage.zusatz = gebaut
    koerper = OpenAIKompatiblerProvider(endpunkt)._koerper_bauen(anfrage)
    assert koerper["temperature"] == TEMPERATUR
