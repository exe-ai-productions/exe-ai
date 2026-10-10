"""The thinking switch: detection and where the stage lands in a request."""

from __future__ import annotations

from types import SimpleNamespace

from app import denkbudget, kontextvoll
from app.denkschalter import (
    AUS_VORGABE,
    MINDEST_BUDGET,
    aus_wort,
    ausschalten,
    mit_deckel,
    zusatz,
)
from app.providers.base import Generierungsanfrage
from app.discovery import denkschalter_im_template, denkwoerter_im_template


def _zustand(config_thinking=None, erkannt=False, dialekt="llama_cpp"):
    caps = SimpleNamespace(thinking=config_thinking)
    endpunkt = SimpleNamespace(
        capabilities=caps,
        parameter_dialect=dialekt,
        base_url="http://127.0.0.1:9/v1",
        modell=None,
    )
    return SimpleNamespace(
        endpunkt=endpunkt,
        gemeldeter_name=None,
        faehigkeiten_erkannt=(
            {
                "thinking": {
                    "supports_reasoning_effort": None,
                    "vorlage_variablen": ["enable_thinking"],
                }
            }
            if erkannt
            else {}
        ),
    )


def test_ausschalten_nimmt_die_denklaenge_nur_neben_einem_schalter():
    """Thinking off for a request made from another one: the switch, and
    the other request's parameters without the thinking length that would
    contradict it. The caller's own parameters stay as they were."""
    parameter = {"reasoning_budget": 2048, "top_k": 40}
    schalter, ohne = ausschalten(_zustand(erkannt=True), parameter)
    assert schalter == {"reasoning_effort": "none"}
    assert ohne == {"top_k": 40}
    assert parameter == {"reasoning_budget": 2048, "top_k": 40}


def test_das_erkannte_wort_der_vorlage_geht_hinaus():
    """The template said what its variable is called, and that name is what
    is sent. It used to be found and then dropped: every request set
    `enable_thinking`, so a model whose template reads `thinking` got a
    variable its template never mentions — it kept thinking, and a
    compaction burned its ceiling in the trace."""
    zustand = _zustand(erkannt=True)
    zustand.faehigkeiten_erkannt["thinking"]["vorlage_variablen"] = ["thinking"]
    assert zusatz("on", zustand) == {"chat_template_kwargs": {"thinking": True}}
    mlx = _zustand(erkannt=True, dialekt="mlx")
    mlx.faehigkeiten_erkannt["thinking"]["vorlage_variablen"] = ["thinking"]
    assert zusatz("off", mlx) == {"chat_template_kwargs": {"thinking": False}}


def test_ohne_erkanntes_wort_bleibt_der_hausname():
    """The silence probe: a template that names `enable_thinking` gets
    exactly that, as before — nothing about the common case moves."""
    zustand = _zustand(erkannt=True)
    assert zusatz("on", zustand) == {"chat_template_kwargs": {"enable_thinking": True}}


def test_ausschalten_ohne_schalter_aendert_nichts():
    """No switch for this model: nothing is sent, and the length stays —
    there is nothing for it to contradict."""
    parameter = {"reasoning_budget": 2048}
    schalter, ohne = ausschalten(_zustand(erkannt=False), parameter)
    assert schalter == {}
    assert ohne is parameter


def test_template_erkennung():
    assert denkschalter_im_template("{% if enable_thinking %}…{% endif %}") is True
    assert denkschalter_im_template("nichts dergleichen") is False
    assert denkschalter_im_template("") is False


def test_die_suche_kennt_mehr_als_ein_wort():
    """One string was too narrow a question: a template that spells its
    switch `thinking`, one that takes a `reasoning_effort` and one that only
    reacts to `/no_think` all mean the model can be asked to think."""
    assert denkwoerter_im_template("{% if enable_thinking %}") == ["enable_thinking", "thinking"]
    assert denkwoerter_im_template("Reasoning: {{ reasoning_effort }}") == [
        "reasoning_effort"
    ]
    assert denkwoerter_im_template("write /no_think to stop") == ["/no_think"]
    assert denkwoerter_im_template("nothing of the sort") == []


def test_zusatz_nur_wenn_geschaltet_und_schaltbar():
    # Not toggled -> send nothing along, no matter what the endpoint can do.
    assert zusatz(None, _zustand(erkannt=True)) == {}
    # Toggled, but the endpoint can't -> don't guess.
    assert zusatz(False, _zustand(erkannt=False)) == {}
    # Toggled and natively detected -> a real shutdown, in the field
    # llama.cpp itself reads.
    assert zusatz(False, _zustand(erkannt=True)) == {"reasoning_effort": "none"}


def test_config_gewinnt_immer():
    # An explicit no in the config beats the detection (safety rule).
    assert zusatz(True, _zustand(config_thinking=False, erkannt=True)) == {}
    # An explicit yes applies even without detection.
    assert zusatz(True, _zustand(config_thinking=True, erkannt=False)) == {
        "chat_template_kwargs": {"enable_thinking": True}
    }
    # And a hand-written list of stages is a list of stages.
    zustand = _zustand(config_thinking=["off", "low", "high"])
    assert zusatz("high", zustand) == {"reasoning_effort": "high"}


# --- A lowered ceiling takes the thinking budget down with it -------------


def test_ein_gesenkter_deckel_zieht_das_budget_mit():
    """The API this concerns wants the budget SMALLER than the ceiling. A
    retry that goes out with less room and the old, larger budget is refused
    for the budget — a refusal no "too long" wording matches, so nothing
    would retry it again. It used to come down to the ceiling less one; the
    retry's answer keeps its own reserve now, same as a fresh request's."""
    gesenkt = mit_deckel({"thinking": {"type": "enabled", "budget_tokens": 63_999}}, 8_000)
    assert gesenkt["thinking"] == {
        "type": "enabled",
        "budget_tokens": 8_000 - denkbudget.ANTWORT_RESERVE,
    }


def test_nie_nach_oben():
    """A deliberately small budget stays small. The split takes the lesser
    of what the stage wants and what the ceiling leaves, so a ceiling with
    room to spare never stretches a budget to fill it."""
    gesenkt = mit_deckel({"thinking": {"type": "enabled", "budget_tokens": 2_000}}, 64_000)
    assert gesenkt["thinking"] == {"type": "enabled", "budget_tokens": 2_000}


def test_unter_dem_mindestbudget_geht_die_anfrage_ohne_denken_raus():
    """Below what the API accepts as a budget there is no budget to send.
    The one request goes out without a thinking pass rather than being
    refused — the same rule the switch resolves a fresh request by."""
    gesenkt = mit_deckel(
        {"thinking": {"type": "enabled", "budget_tokens": 63_999}}, MINDEST_BUDGET
    )
    assert gesenkt["thinking"] == {"type": AUS_VORGABE}


def test_schweigeprobe_ohne_budget_bleibt_alles_wie_es_war():
    """Every other shape a provider reads a stage in says nothing about a
    ceiling, so nothing is touched — thinking switched off, a depth, a plain
    effort word, or no thinking at all."""
    for vorher in (
        {},
        {"thinking": {"type": "disabled"}},
        {"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}},
        {"reasoning_effort": "high"},
        {"chat_template_kwargs": {"enable_thinking": True}},
    ):
        assert mit_deckel(dict(vorher), 8_000) == vorher


def test_die_gesenkte_anfrage_laesst_das_original_in_ruhe():
    """The lowered ceiling holds for the copy it was worked out for. The
    request it was copied from keeps its own numbers — including its
    budget, which used to be the same dictionary object. The copy's number
    is what the lowered ceiling leaves beside the answer's reserve,
    not that ceiling less one."""
    anfrage = Generierungsanfrage(
        nachrichten=[],
        max_tokens=64_000,
        zusatz={"thinking": {"type": "enabled", "budget_tokens": 63_999}},
    )
    kopie = kontextvoll.mit_grenze(anfrage, 8_000, _zustand())

    assert kopie.max_tokens == 8_000
    assert kopie.zusatz["thinking"]["budget_tokens"] == 8_000 - denkbudget.ANTWORT_RESERVE
    assert anfrage.max_tokens == 64_000
    assert anfrage.zusatz["thinking"]["budget_tokens"] == 63_999


def test_ein_kleineres_budget_wird_nie_groesser_gezogen():
    """The budget found here was worked out for a LARGER ceiling and is
    normally the larger of the two. A deliberately small one must not be
    stretched to fill a ceiling that just shrank — that would leave the
    answer with the single token this rule exists to prevent."""
    gesenkt = mit_deckel({"thinking": {"type": "enabled", "budget_tokens": 2_000}}, 8_000)
    assert gesenkt["thinking"]["budget_tokens"] == 2_000


def test_auch_das_unberuehrte_zusatzfeld_kommt_als_kopie_zurueck():
    """A copy of the request that shares this dictionary with the original
    is not a copy — and the caller builds one precisely to spare the
    request it was made from."""
    vorher = {"reasoning_effort": "high"}
    nachher = mit_deckel(vorher, 8_000)
    assert nachher == vorher
    assert nachher is not vorher


# --- The off word belongs to the model, not to this module ------------------


def _anthropisch(stufen):
    """An Anthropic endpoint whose model reports its own off word.

    `aus_wort` travels in the capability block the provider itself sends, so
    a second provider spelling off differently needs no code change — that
    is the whole point of the catalogue.
    """
    name = "claude-opus-4-5"
    endpunkt = SimpleNamespace(
        capabilities=SimpleNamespace(thinking=stufen),
        parameter_dialect="anthropic",
        base_url="https://api.anthropic.com/v1",
        modell=name,
    )
    return SimpleNamespace(
        endpunkt=endpunkt, gemeldeter_name=name, faehigkeiten_erkannt={}
    )


def test_das_aus_wort_kommt_aus_dem_katalog():
    """One origin for the word: what `zusatz(False, …)` sends is what
    `aus_wort` reports, so the two cannot drift apart."""
    zustand = _anthropisch(None)
    assert zusatz(False, zustand, modell="claude-opus-4-5") == {
        "thinking": {"type": aus_wort(zustand, modell="claude-opus-4-5")}
    }


def test_mit_deckel_nimmt_das_uebergebene_aus_wort():
    """A provider whose off word is not `disabled` gets ITS word, not the
    fallback — the retry is refused otherwise, for a reason no wording here
    would recognise."""
    gesenkt = mit_deckel(
        {"thinking": {"type": "enabled", "budget_tokens": 63_999}},
        MINDEST_BUDGET,
        "none",
    )
    assert gesenkt["thinking"] == {"type": "none"}


def test_ohne_aus_wort_bleibt_die_vorgabe():
    """The silence probe: a caller that has nothing to say gets the word
    this module documents, exactly as before."""
    gesenkt = mit_deckel(
        {"thinking": {"type": "enabled", "budget_tokens": 63_999}}, MINDEST_BUDGET
    )
    assert gesenkt["thinking"] == {"type": AUS_VORGABE}


# --- The budget branch, unchanged --------------------------------------------


def test_ein_schalter_modell_bekommt_weiter_sein_budget():
    """Where the catalogue row says budget, `on` resolves to a token budget.

    Left exactly as it was: whether a CHOSEN depth should
    reach such a model instead is a separate question — the 4.5
    generation this row was written for answers `output_config.effort` with
    a 400, so honouring the depth would trade a lying control for a refused
    request."""
    zustand = _anthropisch(["off", "on"])
    gebaut = zusatz("on", zustand, modell="claude-opus-4-5", max_tokens=64_000)
    assert gebaut["thinking"]["type"] == "enabled"
    assert gebaut["thinking"]["budget_tokens"] > 0
    assert "output_config" not in gebaut


# --- The word that goes INTO the text --------------------------------------


MINIMAX = "https://api.minimax.io/v1"


def _minimax_m3(refused=()):
    from app.config import Capabilities, EndpointConfig

    endpoint = EndpointConfig(
        id="m", base_url=MINIMAX, parameter_dialect="openai",
        capabilities=Capabilities(thinking=None),
    )
    return SimpleNamespace(endpunkt=endpoint, gemeldeter_name="MiniMax-M3", faehigkeiten_erkannt={})


def test_route_fields_alone_are_no_switch():
    """The route field M3 always gets says nothing about thinking: with no
    switch left to send, nothing is switched off and the thinking length
    stays, and a refusal is not blamed on a stage."""
    from app import denkablehnung
    from app.denkschalter import ausschalten, carries_switch
    from app.providers import ProviderFehler

    state = _minimax_m3()
    route_only, parameter = ausschalten(
        state, {"reasoning_budget": 512}, abgelehnt=["off", "on"]
    )
    assert route_only == {"reasoning_split": True}
    assert parameter == {"reasoning_budget": 512}
    route = {"reasoning_split": True}
    assert not carries_switch(route_only, route)
    error = ProviderFehler("x", status=400, rohtext='{"error": {"param": "reasoning_effort"}}')
    assert denkablehnung.lernen(None, "m", error, route_only, "off", route=route) is False


def test_a_switch_beside_route_fields_stays_a_switch():
    """Silence probe: off for M3 is still off, beside the route field."""
    from app.denkschalter import ausschalten, carries_switch

    off, parameter = ausschalten(_minimax_m3(), {"reasoning_budget": 512})
    assert off == {"thinking": {"type": "disabled"}, "reasoning_split": True}
    assert parameter == {}
    assert carries_switch(off, {"reasoning_split": True})




def test_off_on_llama_cpp_is_the_field_the_server_reads():
    """Thinking off on llama.cpp goes out as `reasoning_effort: "none"`,
    also for a template that only reacts to `/no_think` in the text; the
    message text is never touched. "On" keeps the template's own switch."""
    for words in (["enable_thinking"], ["/no_think"], ["thinking"]):
        state = _zustand(erkannt=True)
        state.faehigkeiten_erkannt["thinking"]["vorlage_variablen"] = words
        assert zusatz("off", state) == {"reasoning_effort": "none"}, words
    state = _zustand(erkannt=True)
    state.faehigkeiten_erkannt["thinking"]["vorlage_variablen"] = ["/no_think"]
    assert zusatz("on", state) == {"chat_template_kwargs": {"enable_thinking": True}}


def test_mlx_keeps_its_template_switch():
    """Silence probe: an MLX server is switched off by its template
    variable, as before."""
    assert zusatz("off", _zustand(erkannt=True, dialekt="mlx")) == {
        "chat_template_kwargs": {"enable_thinking": False}
    }



def test_a_route_field_of_one_provider_is_a_switch_of_another(monkeypatch):
    """Whether a field is only a route field is asked of the requested
    model: a provider that names its switch like another provider's route
    field still has its thinking length taken off beside it."""
    from app import denkstufen
    from app.config import Capabilities, EndpointConfig
    from app.denkschalter import ausschalten

    real = denkstufen.anbieter_eintrag

    def renamed(name):
        entry = dict(real(name) or {})
        if entry.get("schalter") == "enable_thinking":
            entry["schalter"] = "reasoning_split"
        return entry

    monkeypatch.setattr(denkstufen, "anbieter_eintrag", renamed)
    qwen = SimpleNamespace(
        endpunkt=EndpointConfig(
            id="q", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            parameter_dialect="openai", capabilities=Capabilities(thinking=None),
        ),
        gemeldeter_name="qwen3.8-max",
        faehigkeiten_erkannt={},
    )
    switch, parameters = ausschalten(qwen, {"reasoning_budget": 512})
    assert switch == {"reasoning_split": False}
    assert parameters == {}


def test_the_quietest_stage_reads_the_one_scale():
    """The order the quietest stage and the fallback depth read is one."""
    from app import denkstufen

    assert denkstufen.SCALE == tuple(s for s in denkstufen.STUFEN if s != "on")
    assert denkstufen.SCALE[0] == "off"



def test_the_route_is_named_the_way_the_request_is():
    """No model name, only the one the server reports: the route fields a
    refusal is read against are the ones the request carried."""
    from app.config import Capabilities, EndpointConfig
    from app.denkschalter import route_for

    m3 = SimpleNamespace(
        endpunkt=EndpointConfig(
            id="m", base_url="https://api.minimax.io/v1", parameter_dialect="openai",
            capabilities=Capabilities(thinking=None),
        ),
        gemeldeter_name="MiniMax-M3",
        faehigkeiten_erkannt={},
    )
    assert route_for(m3) == {"reasoning_split": True}
    assert zusatz(None, m3) == route_for(m3)
    assert route_for(m3, modell="other-model") == {}
