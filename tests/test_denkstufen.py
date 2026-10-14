"""Thinking stages: where the answer comes from, and where it lands.

Five sources answer "which depths does this model have", and the order they
answer in is the whole design: a hand entry beats everything, then what a
provider says about itself, then what a local server gives away, then the
catalogue by model, then the catalogue by provider alone. Each of those has
a line here, plus the case that all of them stay silent.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx

from app import denkablehnung, denkbudget, denkschalter, denkstufen
from app.denkschalter import fuer_antworten, zusatz
from app.config import Capabilities, EndpointConfig
from app.providers.openai_kompatibel import OpenAIKompatiblerProvider

WURZEL = Path(__file__).resolve().parent.parent


def _endpunkt(dialekt="openai", url="http://127.0.0.1:9/v1", thinking=None, modell=None):
    return EndpointConfig(
        id="x",
        base_url=url,
        modell=modell,
        parameter_dialect=dialekt,
        capabilities=Capabilities(thinking=thinking),
    )


def _zustand(endpunkt, name=None, erkannt=None):
    return SimpleNamespace(
        endpunkt=endpunkt, gemeldeter_name=name, faehigkeiten_erkannt=erkannt or {}
    )


def _vorlage(*woerter, effort=None, effort_werte=None):
    return {
        "thinking": {
            "supports_reasoning_effort": effort,
            "vorlage_variablen": list(woerter),
            "effort_werte": effort_werte,
        }
    }


ANTHROPIC = "https://api.anthropic.com/v1"
OPENAI = "https://api.openai.com/v1"


# --- 1: one line per source ------------------------------------------------


def test_hand_gewinnt_ueber_alles():
    """An entry in the configuration is somebody who knows their model. It
    beats every detection, the same safety rule vision and tools follow."""
    endpunkt = _endpunkt(url=OPENAI, thinking=["off", "low"], modell="gpt-5.6")
    profil = denkstufen.stufen_fuer(endpunkt, "gpt-5.6", _vorlage("enable_thinking"))
    assert profil.stufen == ["off", "low"]
    assert profil.quelle == "hand"
    # And an explicit no is a no, whatever the catalogue holds.
    aus = denkstufen.stufen_fuer(_endpunkt(url=OPENAI, thinking=False), "gpt-5.6")
    assert aus.art == "nie"
    assert aus.quelle == "hand"


def test_anbieter_sagt_es_selbst():
    """Anthropic's model list carries the accepted depths per model, so
    nothing has to be maintained for it."""
    caps = {
        "claude-sonnet-5": {
            "thinking": {"supported": True, "types": {"adaptive": {"supported": True}}},
            "effort": {
                "supported": True,
                "low": {"supported": True},
                "medium": {"supported": True},
                "high": {"supported": True},
                "xhigh": {"supported": False},
                "max": {"supported": False},
            },
        }
    }
    profil = denkstufen.stufen_fuer(
        _endpunkt("anthropic", ANTHROPIC), "claude-sonnet-5", {"anthropic": caps}
    )
    assert profil.quelle == "anbieter"
    assert profil.stufen == ["off", "low", "medium", "high"]


def test_anbieter_ohne_aus_behaelt_die_katalogzeile():
    """The one thing the capability block never says is whether `disabled`
    is allowed — that stays the catalogue's single row for this provider."""
    caps = {
        "claude-fable-5-1": {
            "thinking": {"supported": True, "types": {"adaptive": {"supported": True}}},
            "effort": {"supported": True, "high": {"supported": True}},
        }
    }
    profil = denkstufen.stufen_fuer(
        _endpunkt("anthropic", ANTHROPIC), "claude-fable-5-1", {"anthropic": caps}
    )
    assert "off" not in profil.stufen


def test_vorlage_sagt_es():
    """A local server gives its own template away, and the words in it say
    whether there is a switch or a scale."""
    endpunkt = _endpunkt("llama_cpp")
    schalter = denkstufen.stufen_fuer(endpunkt, "irgendwas.gguf", _vorlage("enable_thinking"))
    assert schalter.art == "schalter"
    assert schalter.quelle == "vorlage"
    stufen = denkstufen.stufen_fuer(endpunkt, "irgendwas.gguf", _vorlage(effort=True))
    assert stufen.art == "stufen"
    assert stufen.stufen == ["off", "low", "medium", "high"]


def test_ein_gemeldetes_flag_verliert_nicht_gegen_die_eigenen_werte():
    """`supports_reasoning_effort: true` says there is a scale; it must not
    override the actual words the same answer names for it."""
    endpunkt = _endpunkt("llama_cpp")
    profil = denkstufen.stufen_fuer(
        endpunkt, "irgendwas.gguf", _vorlage(effort=True, effort_werte=["xhigh", "medium", "low"])
    )
    assert profil.stufen == ["off", "low", "medium", "xhigh"]
    assert "high" not in profil.stufen


def test_eine_vorlage_reicht_ihre_eigenen_stufen_roh_durch():
    """A model that meets `max` offers `max` — the catalogue's guess for the
    matched pattern (`reasoning_effort` → low/medium/high) never enters it
    once the template names its own words."""
    endpunkt = _endpunkt("llama_cpp")
    profil = denkstufen.stufen_fuer(
        endpunkt, "irgendwas.gguf", _vorlage("reasoning_effort", effort_werte=["max"])
    )
    assert profil.stufen == ["off", "max"]
    assert profil.quelle == "vorlage"


def test_schweigeprobe_die_vorlage_bekommt_keine_stufe_dazu():
    """Three stages stay three: the catalogue adds none of its own."""
    endpunkt = _endpunkt("llama_cpp")
    profil = denkstufen.stufen_fuer(
        endpunkt,
        "irgendwas.gguf",
        _vorlage("reasoning_effort", effort_werte=["low", "medium", "high"]),
    )
    assert profil.stufen == ["off", "low", "medium", "high"]


def test_eine_vorlage_stufe_ausserhalb_des_wortschatzes_faellt_nicht_weg():
    """A stage nobody has named in the vocabulary yet is offered anyway,
    after the known ones — not quietly cut."""
    endpunkt = _endpunkt("llama_cpp")
    profil = denkstufen.stufen_fuer(
        endpunkt,
        "irgendwas.gguf",
        _vorlage("reasoning_effort", effort_werte=["low", "adaptive"]),
    )
    assert profil.stufen == ["off", "low", "adaptive"]
    assert profil.nativ["adaptive"] == "adaptive"


def test_die_vorlage_gewinnt_ueber_die_familienzeile():
    """The measured case: `qwen3` in the family table knows only `off`/`on`,
    but this model's own template accepts `xhigh`, `medium`, `low` — the
    template wins, `high` never appears (measured against
    Qwen3.8-27B-GSQ-RCO-IQ3_S.gguf)."""
    endpunkt = _endpunkt("llama_cpp")
    profil = denkstufen.stufen_fuer(
        endpunkt,
        "Qwen3.8-27B-GSQ-RCO-IQ3_S.gguf",
        _vorlage(
            "reasoning_effort", "enable_thinking", "thinking",
            effort_werte=["xhigh", "medium", "low"],
        ),
    )
    assert profil.stufen == ["off", "low", "medium", "xhigh"]
    assert "high" not in profil.stufen
    assert profil.quelle == "vorlage"


def test_eine_eigene_none_in_den_werten_verdoppelt_off_nicht():
    """A template whose own enumeration already spells the off position out
    (`none`, folded onto `off`) must not end up with `off` twice."""
    endpunkt = _endpunkt("llama_cpp")
    profil = denkstufen.stufen_fuer(
        endpunkt,
        "irgendwas.gguf",
        _vorlage("reasoning_effort", effort_werte=["none", "low", "medium", "high"]),
    )
    assert profil.stufen == ["off", "low", "medium", "high"]
    assert profil.stufen.count("off") == 1


def test_ein_getippter_hand_eintrag_verliert_seinen_tippfehler():
    """The hand source is somebody who read the vocabulary, not a model
    naming a stage of its own — a typo there is dropped, not sent to a
    provider as a broken value."""
    endpunkt = _endpunkt(url=OPENAI, thinking=["off", "meidum"], modell="gpt-5.6")
    profil = denkstufen.stufen_fuer(endpunkt, "gpt-5.6")
    assert profil.stufen == ["off"]
    assert "meidum" not in profil.stufen


def test_eine_verbotene_aus_stellung_bleibt_verboten_wenn_die_vorlage_gewinnt(monkeypatch):
    """A family row that refuses the off position (`aus: false`) must keep
    refusing it even where its plain switch loses to a template naming real
    depths — the override widens what is offered, not what is allowed."""
    monkeypatch.setattr(
        denkstufen,
        "familie_nachschlagen",
        lambda *kandidaten: {"stufen": ["off", "on"], "standard": "on", "aus": False},
    )
    endpunkt = _endpunkt("llama_cpp")
    profil = denkstufen.stufen_fuer(
        endpunkt,
        "irgendwas.gguf",
        _vorlage("reasoning_effort", effort_werte=["low", "medium", "high"]),
    )
    assert "off" not in profil.stufen
    assert profil.stufen == ["low", "medium", "high"]


def test_immer_an_kommt_aus_dem_familienkatalog():
    """No text search can find a model that always thinks: its template
    carries no switch. The family table is what catches those."""
    endpunkt = _endpunkt("llama_cpp")
    assert denkstufen.stufen_fuer(
        endpunkt, "DeepSeek-R1-Distill-Qwen-7B", _vorlage()
    ).art == "immer"
    # And the family a server names for itself hits the same table.
    # Per model: such a server holds a whole shelf, and a Llama that cannot
    # think sits on it beside a Qwen that can.
    regal = {"familien": {"eins": "qwen3_5", "zwei": "llama"}}
    assert denkstufen.stufen_fuer(_endpunkt("mlx"), "eins", regal).stufen == ["off", "on"]
    assert denkstufen.stufen_fuer(_endpunkt("mlx"), "zwei", regal).art == "nie"


def test_ein_gemeldeter_diffusionsname_bekommt_kein_denken():
    """A name an MLX server reports for itself, and the one row that says
    the catalogue KNOWS it cannot think — rather than saying nothing and
    landing on "no thinking" because nobody was asked.

    `art` alone proves nothing here — a name nobody knows ends at "no
    thinking" as well. The difference is WHO said so: a row in the family
    table answers as `vorlage`, an unanswered name as `unbekannt`. That is
    the whole content of this line, and it is what falls away without it.

    The silence test sits in the same breath on purpose: the new row must
    not swallow the family beside it. `gemma4` can be switched, and a name
    carrying both words has to keep its two stages."""
    regal = {"familien": {"eins": "diffusion_gemma", "zwei": "gemma4"}}
    profil = denkstufen.stufen_fuer(_endpunkt("mlx"), "eins", regal)
    assert profil.art == "nie"
    assert profil.quelle == "vorlage"
    assert denkstufen.stufen_fuer(_endpunkt("mlx"), "zwei", regal).stufen == ["off", "on"]


def test_katalog_trifft_ueber_den_modellnamen():
    profil = denkstufen.stufen_fuer(_endpunkt(url=OPENAI), "gpt-5.1-2026-01-01")
    assert profil.quelle == "katalog"
    assert profil.stufen == ["off", "low", "medium", "high"]
    assert profil.nativ["off"] == "none"


def test_laengster_praefix_gewinnt():
    """`gpt-5` and `gpt-5.4-pro` both fit `gpt-5.4-pro`, and the longer one
    is the one that was written for it."""
    profil = denkstufen.stufen_fuer(_endpunkt(url=OPENAI), "gpt-5.4-pro")
    assert profil.stufen == ["medium", "high", "xhigh"]


def test_unbekanntes_modell_bekommt_die_anbieter_vereinigung():
    """A model nobody has entered yet keeps a control that works. Not exact
    — but never a dead button, and a stage it refuses is reported."""
    profil = denkstufen.stufen_fuer(_endpunkt(url=OPENAI), "gpt-9-turbo-schnell")
    assert profil.quelle == "unbekannt"
    assert profil.stufen == ["off", "minimal", "low", "medium", "high", "xhigh", "max"]


def test_wo_niemand_etwas_sagt_kann_das_modell_nicht_denken():
    profil = denkstufen.stufen_fuer(
        _endpunkt(dialekt="llama_cpp", url="http://ganz-woanders/v1"), "irgendwas"
    )
    assert profil.art == "nie"
    assert profil.stufen == []


def test_an_unknown_openai_host_is_offered_the_openai_field_with_medium():
    """A host no catalogue entry knows still speaks the OpenAI dialect: its
    field's stages are offered, `medium` where nobody picked one."""
    endpunkt = _endpunkt(url="http://ganz-woanders/v1")
    profil = denkstufen.stufen_fuer(endpunkt, "irgendwas")
    assert profil.stufen == ["off", "low", "medium", "high"]
    assert denkstufen.standardstufe(profil) == "medium"
    assert zusatz("medium", _zustand(endpunkt, "irgendwas"), modell="irgendwas") == {
        "reasoning_effort": "medium"
    }


def test_schweigeprobe_a_known_model_that_cannot_think_stays_so():
    profil = denkstufen.stufen_fuer(_endpunkt(url=OPENAI), "gpt-4.1")
    assert profil.art == "nie"


# --- 2: the catalogue file itself ------------------------------------------


def test_katalogdatei_haelt_sich_an_den_wortschatz():
    """Every stage word in the file is one the program knows, no model is
    listed twice, and every provider group names its source."""
    kat = denkstufen.katalog()
    erlaubt = set(denkstufen.STUFEN) | {denkstufen.AUS_ROH}
    quelltext = denkstufen.KATALOGDATEI.read_text(encoding="utf-8").splitlines()

    def stufen_pruefen(wo, zeile):
        for wort in zeile.get("stufen") or ():
            assert wort in erlaubt, f"{wo}: {wort!r} is not in the vocabulary"
        standard = zeile.get("standard")
        assert standard is None or standard in erlaubt, f"{wo}: {standard!r}"

    for name, zeile in kat["familien"].items():
        stufen_pruefen(f"familie {name}", zeile)

    for name, eintrag in kat["anbieter"].items():
        stufen_pruefen(f"anbieter {name}", eintrag)
        modelle = eintrag.get("modelle") or {}
        assert len(modelle) == len({m.lower() for m in modelle}), f"{name}: model listed twice"
        for modell, zeile in modelle.items():
            stufen_pruefen(f"{name}/{modell}", zeile)
        # A group without a source line is a claim nobody can check.
        stelle = next(i for i, z in enumerate(quelltext) if z.strip() == f"{name}:")
        kopf = "\n".join(quelltext[stelle : stelle + 8])
        assert "Source" in kopf or "source" in kopf, f"{name}: source line missing"


def test_alle_wirte_zeigen_auf_bekannte_anbieter():
    kat = denkstufen.katalog()
    for wirt, name in kat["wirte"].items():
        assert name in kat["anbieter"], f"{wirt} points at {name}, which does not exist"


# --- 3: the translator, one line per dialect -------------------------------


def test_uebersetzer_je_dialekt():
    anthropic = _zustand(_endpunkt("anthropic", ANTHROPIC), "claude-sonnet-5")
    assert zusatz("off", anthropic) == {"thinking": {"type": "disabled"}}
    assert zusatz("xhigh", anthropic) == {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "xhigh"},
    }

    openai = _zustand(_endpunkt(url=OPENAI), "gpt-5.6-sol")
    assert zusatz("off", openai) == {"reasoning_effort": "none"}
    assert zusatz("low", openai) == {"reasoning_effort": "low"}


def test_fuer_antworten_laesst_ein_vorhandenes_reasoning_stehen():
    """The stage object of the other wire carries more than its `effort` — a
    summary, an include. Written over whole, they would disappear from a
    request nobody asked to change."""
    assert fuer_antworten({"reasoning_effort": "high"}) == {"reasoning": {"effort": "high"}}
    assert fuer_antworten({"reasoning_effort": "high", "reasoning": {"summary": "auto"}}) == {
        "reasoning": {"summary": "auto", "effort": "high"}
    }
    # Nothing to translate: the fields come back unchanged — and as a copy, so
    # a caller building its request around them cannot reach into this one.
    ohne = {"temperature": 0.4}
    kopie = fuer_antworten(ohne)
    assert kopie == ohne and kopie is not ohne

    glm = _zustand(_endpunkt(url="https://api.z.ai/api/paas/v4"), "glm-5.2")
    assert zusatz("off", glm) == {"thinking": {"type": "disabled"}}
    assert zusatz("high", glm) == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }

    qwen = _zustand(
        _endpunkt(url="https://dashscope.aliyuncs.com/compatible-mode/v1"), "qwen3.8-max"
    )
    assert zusatz("off", qwen) == {"enable_thinking": False}
    assert zusatz("on", qwen) == {"enable_thinking": True}

    lokal = _zustand(_endpunkt("llama_cpp"), "x.gguf", _vorlage("enable_thinking"))
    assert zusatz("off", lokal) == {"reasoning_effort": "none"}
    mlx = _zustand(_endpunkt("mlx"), "x", {"familien": {"x": "qwen3_5"}})
    assert zusatz("on", mlx) == {"chat_template_kwargs": {"enable_thinking": True}}


def test_kimi_k3_bekommt_kein_thinking_objekt():
    """It always thinks and answers the switch object with an error, so the
    depth travels alone."""
    kimi = _zustand(_endpunkt(url="https://api.kimi.ai/v1"), "kimi-k3")
    assert zusatz("max", kimi) == {"reasoning_effort": "max"}


def test_wo_aus_verboten_ist_wird_nichts_gesendet():
    """The picture-prompt rewrite and the watcher ask for "no thinking" on
    every model. Where a model refuses to be switched off, that request has
    to leave without a field rather than with one that answers 400."""
    fable = _zustand(_endpunkt("anthropic", ANTHROPIC), "claude-fable-5-1")
    assert zusatz(False, fable) == {}
    # And where it is allowed, the older boolean still means the same thing.
    sonnet = _zustand(_endpunkt("anthropic", ANTHROPIC), "claude-sonnet-5")
    assert zusatz(False, sonnet) == {"thinking": {"type": "disabled"}}


def test_die_alte_generation_bekommt_ein_budget():
    """That generation wants a token budget rather than a depth. It used to
    get the ceiling less one, which satisfied the API and left the visible
    answer a single token; now the stage asks for its own
    budget and the answer keeps a reserve of its own, so a wide ceiling
    yields the stage's number rather than the ceiling's."""
    opus45 = _zustand(_endpunkt("anthropic", ANTHROPIC), "claude-opus-4-5")
    assert zusatz("on", opus45, max_tokens=64_000) == {
        "thinking": {"type": "enabled", "budget_tokens": denkbudget.STUFENBUDGET}
    }


def test_ein_knapper_deckel_teilt_statt_die_antwort_zu_verhungern():
    """Where the ceiling is too small for the whole stage budget, what is
    left after the answer's reserve goes to the thinking — never more.
    The reserve stays with the answer either way."""
    opus45 = _zustand(_endpunkt("anthropic", ANTHROPIC), "claude-opus-4-5")
    deckel = denkbudget.ANTWORT_RESERVE + denkbudget.STUFENBUDGET - 1_000
    assert zusatz("on", opus45, max_tokens=deckel) == {
        "thinking": {"type": "enabled", "budget_tokens": deckel - denkbudget.ANTWORT_RESERVE}
    }


def test_ein_zu_kleiner_deckel_laesst_diese_anfrage_ohne_denken():
    """Anthropic wants at least 1,024 tokens of budget. Where the ceiling
    leaves less BESIDE the answer's reserve, this one request goes out with
    thinking off rather than being refused for a number that cannot be sent.
    The edge moved up by the reserve: it used to sit at the
    minimum plus one, it now sits at the minimum plus the reserve."""
    opus45 = _zustand(_endpunkt("anthropic", ANTHROPIC), "claude-opus-4-5")
    kleinster = denkbudget.ANTWORT_RESERVE + denkschalter.MINDEST_BUDGET
    assert zusatz("on", opus45, max_tokens=kleinster - 1) == {"thinking": {"type": "disabled"}}
    assert zusatz("on", opus45, max_tokens=kleinster) == {
        "thinking": {"type": "enabled", "budget_tokens": denkschalter.MINDEST_BUDGET}
    }
    # And where no ceiling reaches this at all.
    assert zusatz("on", opus45) == {"thinking": {"type": "disabled"}}


def test_die_antwort_behaelt_ihre_reserve():
    """Whatever "Auto" resolves to, the thinking leaves the visible answer
    at least its reserve — checked across the whole band a ceiling can land
    in. This used to only ask for "below the ceiling", which the
    ceiling less one also satisfied while starving the answer."""
    opus45 = _zustand(_endpunkt("anthropic", ANTHROPIC), "claude-opus-4-5")
    for deckel in (5_120, 12_000, 64_000, 128_000, 1_000_000):
        koerper = zusatz("on", opus45, max_tokens=deckel)
        assert deckel - koerper["thinking"]["budget_tokens"] >= denkbudget.ANTWORT_RESERVE


def test_die_neue_generation_denkt_weiter_ohne_zahl():
    """Silence test: the generation with an effort scale gets no budget at
    all, whatever the ceiling."""
    sonnet = _zustand(_endpunkt("anthropic", ANTHROPIC), "claude-sonnet-5")
    assert zusatz("medium", sonnet, max_tokens=64_000) == {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "medium"},
    }


def test_jede_stufe_bekommt_ihr_eigenes_budget():
    """Before this, every stage above `off` fell through to the same 8,000
    tokens — `low` and `max` thought equally long. A hand entry reaches the
    depths the catalogue does not offer for this generation
    (`app/daten/denkstufen.yaml` names only `off`/`on` here), and each stage
    now asks for its own row in the table instead."""
    opus45 = _zustand(
        _endpunkt(
            "anthropic",
            ANTHROPIC,
            thinking=["off", "on", "minimal", "low", "medium", "high", "xhigh", "max"],
        ),
        "claude-opus-4-5",
    )
    for stufe, erwartet in denkbudget.STUFENBUDGETS.items():
        koerper = zusatz(stufe, opus45, max_tokens=64_000)
        assert koerper == {"thinking": {"type": "enabled", "budget_tokens": erwartet}}
    # Silence test: `on` and `off` are untouched by the new table.
    assert zusatz("on", opus45, max_tokens=64_000) == {
        "thinking": {"type": "enabled", "budget_tokens": denkbudget.STUFENBUDGET}
    }
    assert zusatz("off", opus45, max_tokens=64_000) == {"thinking": {"type": "disabled"}}


def test_eine_gewaehlte_stufe_teilt_sich_auch_unter_einem_knappen_deckel():
    """The split in `app/denkbudget.py` applies to whichever stage was
    chosen, not only the old `on` fallback: `high` wants 16,000, a ceiling of
    8,000 leaves only what the answer's reserve does not take."""
    opus45 = _zustand(
        _endpunkt("anthropic", ANTHROPIC, thinking=["off", "high"]), "claude-opus-4-5"
    )
    assert zusatz("high", opus45, max_tokens=8_000) == {
        "thinking": {"type": "enabled", "budget_tokens": 3_904}
    }


# --- 4: the older stored shape ---------------------------------------------


def test_altwert_liest_sich_als_stellung():
    from app import denkenwahl

    profil = denkstufen.stufen_fuer(_endpunkt(url=OPENAI), "gpt-5.1")
    assert denkenwahl.aufgeloest({"an": False}, profil) == "off"
    assert denkenwahl.aufgeloest({"an": True}, profil) == profil.standard or "medium"


# --- 5: a refused stage ----------------------------------------------------


def test_ablehnung_wird_gemerkt_und_verschwindet_aus_der_liste():
    assert denkablehnung.ist_ablehnung(400, json.dumps({"error": {
        "message": "Unsupported value: 'reasoning_effort' does not support 'max' with this model.",
        "type": "invalid_request_error", "param": "reasoning_effort", "code": "unsupported_value",
    }}))
    profil = denkstufen.stufen_fuer(
        _endpunkt(url=OPENAI), "gpt-5.6-sol", abgelehnt=["max", "xhigh"]
    )
    assert "max" not in profil.stufen
    assert "xhigh" not in profil.stufen
    assert "high" in profil.stufen
    # A stage nobody offers any more cannot be the default either.
    assert profil.standard in profil.stufen


def test_schweigeprobe_ein_fehler_ohne_feldnamen_merkt_nichts():
    """Every other 400 also arrives here — a wrong key, a full context, a
    provider having a bad day. Blaming the stage for those would empty a
    working list one entry at a time."""
    assert not denkablehnung.ist_ablehnung(400, "invalid_api_key: the key is wrong")
    assert not denkablehnung.ist_ablehnung(500, "reasoning_effort exploded")
    assert not denkablehnung.ist_ablehnung(None, None)


def test_a_field_name_inside_a_model_id_is_no_refusal_of_the_stage():
    """"kimi-k2-thinking" and "qwen/qwen3-thinking" are model ids: a 400 about
    something else that names the model must not lock a stage."""
    for text in (
        "Model kimi-k2-thinking does not support image input",
        "The model kimi-k2-thinking is not supported when using this account",
        "qwen/qwen3-thinking does not support tools",
        "This does not support image input: kimi-k2-thinking.",
    ):
        assert not denkablehnung.ist_ablehnung(400, text), text


def test_a_field_name_standing_alone_is_still_a_refusal_next_to_a_model_id():
    """Silence probe: the field named on its own keeps counting, dotted or
    not, even when the same text also carries a model id."""
    assert denkablehnung.ist_ablehnung(
        400, "kimi-k2-thinking: adaptive thinking is not supported on this model"
    )
    assert denkablehnung.ist_ablehnung(
        400, "chat_template_kwargs.enable_thinking: Extra inputs are not permitted"
    )
    assert denkablehnung.ist_ablehnung(400, "Unsupported parameter: reasoning_effort")
    assert denkablehnung.ist_ablehnung(400, json.dumps({"error": {
        "message": "kimi-k2-thinking rejected the request", "param": "reasoning_effort",
    }}))


def test_only_an_error_that_blames_the_thinking_field_is_a_refusal():
    """A field name in the text is not enough: the error has to point at it
    as the thing refused, or one foreign 400 locks "off" for the server."""
    # Anthropic about the history, not about the switch.
    assert not denkablehnung.ist_ablehnung(
        400,
        "messages.1.content.0: `thinking` or `redacted_thinking` blocks in the latest "
        "assistant message cannot be modified.",
    )
    # A context error that happens to mention the effort somewhere.
    assert not denkablehnung.ist_ablehnung(400, "Prompt too long; effort was medium")
    # An OpenAI error object that points at another field.
    assert not denkablehnung.ist_ablehnung(400, json.dumps({"error": {
        "message": "Invalid 'max_tokens': thinking budget too large",
        "param": "max_tokens",
    }}))
    # Refusals: the switch named next to a refusing word, the param, the
    # mandatory route.
    assert denkablehnung.ist_ablehnung(400, "adaptive thinking is not supported on this model")
    assert denkablehnung.ist_ablehnung(422, json.dumps({"error": {"param": "reasoning_effort"}}))
    assert denkablehnung.ist_ablehnung(400, "Reasoning is mandatory for this endpoint")
    assert denkablehnung.ist_ablehnung(
        422, "output_config.effort: Extra inputs are not permitted"
    )
    # A `param` pointing at a thinking block in the history, not the switch.
    assert not denkablehnung.ist_ablehnung(400, json.dumps({"error": {
        "message": "invalid content", "param": "messages[3].thinking",
    }}))
    assert denkablehnung.ist_ablehnung(400, json.dumps({"error": {"param": "reasoning.effort"}}))
    # A `param` that points at the history decides, whatever the words say.
    assert not denkablehnung.ist_ablehnung(400, json.dumps({"error": {
        "message": "thinking blocks are not supported in this position",
        "param": "messages[3].thinking",
    }}))
    # A `param` path into the history behind a prefix, the thinking LENGTH
    # and the summary are no refusal of the stage either.
    for param in ("body.messages.3.thinking", "/messages/3/thinking", "reasoning_budget",
                  "reasoning.summary"):
        assert not denkablehnung.ist_ablehnung(
            400, json.dumps({"error": {"param": param, "message": "not supported"}})
        ), param
    assert denkablehnung.ist_ablehnung(
        400, json.dumps({"error": {"param": "output_config.effort"}})
    )
    assert denkablehnung.ist_ablehnung(400, json.dumps({"error": {"param": "reasoning"}}))
    # A proxy that writes "None" into the field: the text decides.
    assert denkablehnung.ist_ablehnung(400, json.dumps({"error": {
        "message": "reasoning_effort is not supported for this model", "param": "None",
    }}))
    # Prose around the words: a sentence ending, a link.
    assert denkablehnung.ist_ablehnung(400, "thinking is not supported for this input.")
    assert denkablehnung.ist_ablehnung(
        400, "adaptive thinking is not supported on this model. See https://docs.anthropic.com/en/api/messages."
    )
    # The switch the local servers read.
    assert denkablehnung.ist_ablehnung(400, json.dumps({"error": {
        "message": "parameter.enable_thinking must be set to false", "param": "enable_thinking",
    }}))


def test_three_more_ways_of_refusing_the_stage_count():
    """A refused value, a schema refusing the value's shape and a tagged
    union that knows none of the tags all blame the stage field."""
    for text in (
        "Unsupported value: reasoning_effort 'max' is not supported with this model.",
        "thinking.type: Input should be 'enabled' or 'disabled'",
        "thinking: Input tag 'adaptive' found using 'type' does not match any of the expected tags",
    ):
        assert denkablehnung.ist_ablehnung(400, text), text


def test_schweigeprobe_the_new_words_without_a_stage_field_are_no_refusal():
    assert not denkablehnung.ist_ablehnung(400, "max_tokens: Input should be greater than 0")
    assert not denkablehnung.ist_ablehnung(400, "Unsupported value: temperature 2.5")


def test_vllm_param_at_the_top_of_the_error_object_counts():
    """vLLM writes `param` beside the message, not inside an `error` object."""
    assert denkablehnung.ist_ablehnung(400, json.dumps({
        "object": "error", "message": "invalid value", "type": "BadRequestError",
        "param": "reasoning_effort", "code": 400,
    }))
    assert denkablehnung.ist_ablehnung(400, json.dumps({
        "object": "error", "message": "invalid value",
        "param": "chat_template_kwargs.enable_thinking", "code": 400,
    }))


def test_a_validation_error_is_blamed_on_its_loc_not_on_the_echoed_body():
    """FastAPI/pydantic echo the request as `input`: the stage field's name
    is in the text even when the error is about a message."""
    body = {"model": "m", "reasoning_effort": "medium", "messages": [{"content": 1}]}
    assert not denkablehnung.ist_ablehnung(422, json.dumps({"detail": [{
        "type": "string_type", "loc": ["body", "messages", 0, "content"],
        "msg": "Input should be a valid string", "input": body,
    }]}))
    assert denkablehnung.ist_ablehnung(422, json.dumps({"detail": [{
        "type": "literal_error", "loc": ["body", "reasoning_effort"],
        "msg": "Input should be 'low' or 'high'", "input": "medium",
    }]}))


def test_keys_inside_the_thinking_object_that_are_no_stage_are_no_refusal():
    """`thinking.display` and `thinking.budget_tokens` are about how and how
    long, not about the stage — refusing them must not cost a stage."""
    for param in ("thinking.display", "thinking.budget_tokens"):
        assert not denkablehnung.ist_ablehnung(400, json.dumps({"error": {
            "message": "not supported", "param": param,
        }})), param
    assert not denkablehnung.ist_ablehnung(
        400, "thinking.budget_tokens: Input should be greater than or equal to 1024"
    )
    assert denkablehnung.ist_ablehnung(400, json.dumps({"error": {"param": "thinking.type"}}))


def test_the_stage_fields_come_from_the_catalogue():
    felder = denkstufen.stage_fields()
    for name in ("reasoning_effort", "thinking", "enable_thinking"):
        assert name in felder


def test_the_quietest_stage_is_a_depth_before_on():
    """"on" names no depth — the model thinks at its default — so a model
    with depths gets its smallest depth, and "on" only stands where nothing
    else does."""
    from types import SimpleNamespace

    def state():
        return SimpleNamespace(endpunkt=_endpunkt(url=OPENAI), gemeldeter_name=None,
                               faehigkeiten_erkannt={})

    profile = denkstufen.stufen_fuer(_endpunkt(url=OPENAI), "gpt-5.6")
    assert "off" in profile.stufen
    assert denkschalter.quietest(state(), modell="gpt-5.6") == "off"
    without_off = denkschalter.quietest(state(), modell="gpt-5.6", abgelehnt=["off"])
    assert without_off not in (None, "off", "on")
    assert without_off == next(
        s for s in denkstufen.STUFEN if s in profile.stufen and s not in ("off", "on")
    )


def test_abgelehnte_liste_behaelt_auch_unbekannte_woerter():
    """A refused stage is not checked against the closed vocabulary: the
    provider can reject a word the catalogue never named."""
    assert denkablehnung.liste_pruefen(["max", "MAX", "adaptive"]) == ["max", "adaptive"]
    assert denkablehnung.liste_pruefen(["quatsch"]) == ["quatsch"]
    assert denkablehnung.liste_pruefen([""]) is None
    assert denkablehnung.liste_pruefen("max") is None


def test_merken_nimmt_auch_ein_unbekanntes_wort():
    """`schalter_pruefen`/`liste_pruefen` open the same door on write: a
    stage `merken` is told to record is not second-guessed against the
    vocabulary either."""

    class _Attrappe:
        def __init__(self):
            self.gespeichert = {}

        def holen(self, bereich, schluessel):
            return self.gespeichert.get((bereich, schluessel))

        def setzen(self, bereich, schluessel, wert):
            self.gespeichert[(bereich, schluessel)] = wert

    einstellungen = _Attrappe()
    assert denkablehnung.merken(einstellungen, "x", "adaptive") == ["adaptive"]
    assert denkablehnung.gemerkt(einstellungen, "x") == ["adaptive"]


# --- 6: the context size, three sources in order ---------------------------


def _provider(handler, **felder):
    endpunkt = _endpunkt(dialekt="mlx", **felder)
    return OpenAIKompatiblerProvider(endpunkt), httpx.MockTransport(handler)


async def _mit_transport(monkeypatch, provider, transport):
    echter = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: echter(transport=transport, **kw)
    )
    return await provider.kontextgroesse(1.0)


async def test_kontextgroesse_kommt_aus_max_model_len(monkeypatch):
    """A server without /props was showing an empty context bar although the
    number sat in its model list all along."""
    gefragt: list[str] = []

    def handler(request):
        gefragt.append(request.url.path)
        if request.url.path.endswith("/props"):
            return httpx.Response(404)
        if request.url.path.endswith("/v1/models"):
            return httpx.Response(
                200, json={"data": [{"id": "mein-modell", "max_model_len": 262144}]}
            )
        return httpx.Response(200, json={"models": [{"id": "mein-modell"}]})

    provider, transport = _provider(handler, modell="mein-modell")
    assert await _mit_transport(monkeypatch, provider, transport) == 262144
    # The model list answered. Knocking on the status route as well would be
    # a second request for a question that is already settled.
    assert not any(p.endswith("/models/status") for p in gefragt)


async def test_ohne_quelle_bleibt_die_zahl_leer(monkeypatch):
    """Nothing is invented: no number anywhere means no percentage in the
    window, which is better than a made-up one."""

    def handler(request):
        return httpx.Response(404)

    provider, transport = _provider(handler, modell="mein-modell")
    assert await _mit_transport(monkeypatch, provider, transport) is None


async def test_die_familie_kommt_aus_dem_statusblatt(monkeypatch):
    """`config_model_type` is the model's own `model_type`, which is also
    the key the family table is written in — one table for three sources."""

    def handler(request):
        return httpx.Response(
            200,
            json={
                "models": [
                    {"id": "mein-modell", "config_model_type": "qwen3_5"},
                ]
            },
        )

    provider, transport = _provider(handler, modell="mein-modell")
    echter = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: echter(transport=transport, **kw)
    )
    assert await provider.denkquellen(1.0) == {"familien": {"mein-modell": "qwen3_5"}}


# --- 7: the window ---------------------------------------------------------


def test_the_mode_chip_wears_only_the_modes_own_colours():
    """The permission mode's chip carries one colour, its lamp's: Auto red,
    Manual green, Restricted yellow. Blue stays free for "running", where it
    belongs."""
    quelle = (WURZEL / "frontend/src/teile/Eingabeleiste.svelte").read_text(encoding="utf-8")
    assert "const MODE_COLOUR = { auto: 'rot', manuell: 'gruen', restricted: 'gelb' }" in quelle


def test_die_stufenwoerter_stehen_in_beiden_katalogen():
    for sprache in ("de", "en"):
        katalog = json.loads(
            (WURZEL / f"app/locales/{sprache}.json").read_text(encoding="utf-8")
        )
        stufen = katalog["denken"]["stufe"]
        assert set(stufen) == set(denkstufen.STUFEN)
        assert katalog["denken"]["immer"] and katalog["denken"]["nie"]


# --- 8: the host table -----------------------------------------------------


def test_meta_wird_ueber_seinen_wirt_gefunden():
    """Meta's rows used to be unreachable: the catalogue carried the models
    but no host row, and the provider is read from the base_url host alone."""
    endpunkt = _endpunkt(url="https://api.meta.ai/v1", modell="muse-spark")
    assert denkstufen.anbieter_schluessel(endpunkt) == "meta"
    profil = denkstufen.stufen_fuer(endpunkt, "muse-spark")
    assert profil.stufen == ["minimal", "low", "medium", "high", "xhigh"]
    assert "off" not in profil.stufen


def test_ein_unbekannter_wirt_bleibt_ohne_anbieter():
    """The silence test: a host no row names stays plain OpenAI, and adding
    Meta must not widen that."""
    assert denkstufen.anbieter_schluessel(_endpunkt(url="https://api.example.org/v1")) is None


def test_ein_laengerer_wirt_erbt_die_zeile_nicht():
    """The finding: a catalogue row was searched anywhere inside the host, so
    `api.openai.com.example` inherited OpenAI's row just because its name
    happened to occur somewhere in a longer one. A row is now anchored to a
    dot boundary — the whole host, its tail, or a whole segment — so a host
    that merely CONTAINS the name no longer matches."""
    endpunkt = _endpunkt(url="https://api.openai.com.example/v1")
    assert denkstufen.anbieter_schluessel(endpunkt) is None


def test_die_absolute_schreibweise_bleibt_derselbe_wirt():
    """`api.openai.com.` (a trailing dot: the absolute-FQDN spelling,
    meaning exactly the same host) must still match — the dot boundary the
    fix above anchors to must not read the root's own dot as a boundary
    that makes this a DIFFERENT, longer host."""
    endpunkt = _endpunkt(url="https://api.openai.com./v1")
    assert denkstufen.anbieter_schluessel(endpunkt) == "openai"


def test_ein_wirt_im_pfad_ist_kein_wirt():
    """The finding: the row was searched in the WHOLE address. A proxy at
    `https://proxy.test/api.openai.com/v1` was read as OpenAI and handed its
    model OpenAI's thinking switches — decided by a path anybody may
    choose. So only the host is compared."""
    endpunkt = _endpunkt(url="https://proxy.test/api.openai.com/v1")
    assert denkstufen.anbieter_schluessel(endpunkt) is None


def test_die_drei_teilstueck_zeilen_finden_ihren_wirt_weiter():
    """The silence test that decides HOW this is built: three catalogue rows
    are deliberately only PARTS of a host (`dashscope`, `aliyuncs`,
    `moonshot`, app/daten/denkstufen.yaml). Comparing the host for equality
    would switch all three off without a word — so a dotless row still
    matches a whole dot-delimited segment of the host (`dashscope` inside
    `dashscope.aliyuncs.com`), just never a mere substring of one
    (`notdashscope.com` does not match `dashscope`)."""
    for url, erwartet in (
        ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen"),
        ("https://api.moonshot.cn/v1", "kimi"),
        ("https://api.openai.com/v1", "openai"),
        ("https://generativelanguage.googleapis.com/v1beta", "google"),
        ("http://127.0.0.1:8095/v1", None),
    ):
        assert denkstufen.anbieter_schluessel(_endpunkt(url=url)) == erwartet, url


def test_eine_adresse_ohne_schema_hat_trotzdem_einen_wirt():
    """A hand writes `api.openai.com/v1` into a configuration file, and it
    still keeps its row — it is only the parser that cannot see a host
    without `//` in front of it. Handing the whole string back instead
    would have let the path back in through the side door."""
    assert denkstufen.wirt_von("api.openai.com/v1") == "api.openai.com"
    assert denkstufen.anbieter_schluessel(_endpunkt(url="api.openai.com/v1")) == "openai"
    # And the hole stays shut without a scheme too.
    assert denkstufen.wirt_von("proxy.test/api.openai.com/v1") == "proxy.test"
    assert denkstufen.anbieter_schluessel(_endpunkt(url="proxy.test/api.openai.com/v1")) is None
    # Nothing readable stays nothing — and matched no row before either.
    assert denkstufen.wirt_von("") == ""
    assert denkstufen.wirt_von("/v1") == ""


def test_the_switch_name_comes_from_the_profile(monkeypatch):
    """The NAME of a plain switch is the provider's business and comes out of
    its profile; its place is the top of the body, where an SDK merges
    `extra_body` too. No request carries a key literally called
    `extra_body`."""
    qwen = _zustand(
        _endpunkt(url="https://dashscope.aliyuncs.com/compatible-mode/v1"), "qwen3.8-max"
    )
    assert zusatz("on", qwen) == {"enable_thinking": True}
    assert zusatz("off", qwen) == {"enable_thinking": False}
    assert "extra_body" not in denkstufen.anbieter_eintrag("qwen")

    echt = denkstufen.anbieter_eintrag

    def anders_genannt(name):
        eintrag = dict(echt(name) or {})
        if eintrag.get("schalter") == "enable_thinking":
            eintrag["schalter"] = "thinking_on"
        return eintrag

    # One module object, one patch: `denkschalter.denkstufen` IS `denkstufen`.
    monkeypatch.setattr(denkstufen, "anbieter_eintrag", anders_genannt)
    assert zusatz("on", qwen) == {"thinking_on": True}


def test_ein_feldname_mit_punkt_bleibt_die_objektform():
    """The silence probe for the branch above: `thinking.type` names a field
    INSIDE an object and must not be read as a plain switch called
    "thinking.type"."""
    glm = _zustand(_endpunkt(url="https://api.z.ai/api/paas/v4"), "glm-5.2")
    assert zusatz("off", glm) == {"thinking": {"type": "disabled"}}
    assert zusatz("high", glm) == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }


def test_eine_familienzeile_nimmt_dem_template_den_namen_nicht_weg():
    """The family row answers which STAGES a model has. What its template
    calls the thinking variable is a different question, and the template
    already answered it — the two models the catalogue names as carriers of
    the bare `thinking` both stand in `familien`, so a word written into the
    stage branch alone reached everybody except them."""
    tief = _zustand(
        _endpunkt("llama_cpp"),
        "DeepSeek-V3.1-Terminus-Q4_K_M",
        _vorlage("thinking"),
    )
    assert denkstufen.stufen_fuer(
        tief.endpunkt, tief.gemeldeter_name, tief.faehigkeiten_erkannt
    ).quelle == "vorlage"
    assert zusatz("on", tief) == {"chat_template_kwargs": {"thinking": True}}


def test_eine_abgelehnte_stufe_nimmt_den_namen_nicht_mit():
    """A single refusal at the server used to bring the defect back: the
    profile was rebuilt field by field and the name was not among them."""
    zustand = _zustand(_endpunkt("mlx"), "irgendwas-9b", _vorlage("thinking"))
    assert zusatz("off", zustand, abgelehnt=["on"]) == {
        "chat_template_kwargs": {"thinking": False}
    }


def test_eine_tiefe_faellt_neben_dem_schalter_nicht_weg(monkeypatch):
    """A profile that offers stages AND names a plain switch gets both — the
    object form two branches down has always done that, and the switch form
    silently dropped the depth."""
    echt = denkstufen.anbieter_eintrag

    def mit_tiefe(name):
        eintrag = dict(echt(name) or {})
        if eintrag.get("schalter") == "enable_thinking":
            eintrag["feld"] = "reasoning_effort"
            eintrag["stufen"] = ["off", "on", "low", "high"]
        return eintrag

    monkeypatch.setattr(denkstufen, "anbieter_eintrag", mit_tiefe)
    qwen = _zustand(
        _endpunkt(url="https://dashscope.aliyuncs.com/compatible-mode/v1"), "unbekannt-9b"
    )
    assert zusatz("high", qwen) == {
        "enable_thinking": True,
        "reasoning_effort": "high",
    }


def test_kolibri_offers_its_four_stages():
    """Kolibri-1 reports `general.architecture: kolibri1`; its template reads
    `reasoning_effort` with none, low, medium and high."""
    regal = {"familien": {"kolibri": "kolibri1"}}
    profil = denkstufen.stufen_fuer(_endpunkt("llama_cpp"), "kolibri", regal)
    assert profil.stufen == ["off", "low", "medium", "high"]
    assert profil.standard == "high"


def test_a_family_beside_kolibri_keeps_its_stages():
    """Silence probe: the row next to it is untouched."""
    regal = {"familien": {"muse": "muse-glimmer"}}
    profil = denkstufen.stufen_fuer(_endpunkt("llama_cpp"), "muse", regal)
    assert profil.stufen[-1] == "xhigh"


# --- A template read from the model's own folder (oMLX) -------------------

QWEN38_TEMPLATE = (
    "{%- if enable_thinking is undefined or enable_thinking is true %}\n"
    "    {%- set resolved_reasoning_effort = reasoning_effort|default('xhigh') %}\n"
    "    {%- if resolved_reasoning_effort not in ('xhigh', 'medium', 'low') %}\n"
    "        {{- raise_exception('Unexpected reasoning effort') }}\n"
    "    {%- endif %}\n"
    "{%- endif %}\n"
)
QWEN35_TEMPLATE = "{%- if enable_thinking is defined and enable_thinking is false %}{%- endif %}\n"


def _mlx_catalogue(tmp_path):
    """An oMLX shelf of two `qwen3_5` models: one whose template takes depths,
    one with the plain switch — read the way discovery reads them."""
    from app.discovery import templates_read

    for name, text in (("deep", QWEN38_TEMPLATE), ("plain", QWEN35_TEMPLATE)):
        (tmp_path / name).mkdir()
        (tmp_path / name / "chat_template.jinja").write_text(text, encoding="utf-8")
    templates = templates_read({
        "Qwen3.8-27B": str(tmp_path / "deep"),
        "Qwen3.5-4B": str(tmp_path / "plain"),
        "elsewhere": str(tmp_path / "not-on-this-machine"),
    })
    return {"familien": {"Qwen3.8-27B": "qwen3_5", "Qwen3.5-4B": "qwen3_5"}, "templates": templates}


def test_the_model_s_own_template_names_its_depths(tmp_path):
    """The family row knows only on/off; the template in the model's folder
    takes low, medium and xhigh, and it is the model's own answer."""
    erkannt = _mlx_catalogue(tmp_path)
    assert "elsewhere" not in erkannt["templates"]
    profil = denkstufen.stufen_fuer(_endpunkt(dialekt="mlx"), "Qwen3.8-27B", erkannt)
    assert set(profil.stufen) == {"off", "low", "medium", "xhigh"}
    assert profil.quelle == "vorlage"


def test_a_template_without_depths_keeps_the_switch(tmp_path):
    """Silence probe: Qwen3.5-4B's template has only the switch — on/off as
    before."""
    erkannt = _mlx_catalogue(tmp_path)
    profil = denkstufen.stufen_fuer(_endpunkt(dialekt="mlx"), "Qwen3.5-4B", erkannt)
    assert profil.stufen == ["off", "on"]


def test_a_depth_travels_in_the_template_kwargs_under_mlx(tmp_path):
    """Under `mlx` the depth goes to the template beside the switch set on;
    "off" stays the switch alone, which is what a fold sends."""
    from app.denkschalter import zusatz

    erkannt = _mlx_catalogue(tmp_path)
    zustand = _zustand(_endpunkt(dialekt="mlx"), "Qwen3.8-27B", erkannt)
    assert zusatz("medium", zustand, modell="Qwen3.8-27B") == {
        "chat_template_kwargs": {"enable_thinking": True, "reasoning_effort": "medium"}
    }
    assert zusatz("off", zustand, modell="Qwen3.8-27B") == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


# --- Provider values the reference agent keeps ------------------------------

DEEPSEEK = "https://api.deepseek.com/v1"
ZAI = "https://api.z.ai/api/paas/v4"
XAI = "https://api.x.ai/v1"
MINIMAX = "https://api.minimax.io/v1"


def _profile(url, model):
    return denkstufen.stufen_fuer(_endpunkt(url=url), model)


def test_deepseek_v4_offers_four_depths():
    for model in ("deepseek-v4-pro", "deepseek-v4-flash", "deepseek-flash"):
        profile = _profile(DEEPSEEK, model)
        assert profile.stufen == ["off", "low", "medium", "high", "max"], model
        assert profile.quelle == "katalog", model
        assert profile.standard == "high", model
    tief = _zustand(_endpunkt(url=DEEPSEEK), "deepseek-v4-pro")
    assert zusatz("medium", tief) == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "medium",
    }
    assert zusatz("off", tief) == {"thinking": {"type": "disabled"}}


def test_deepseek_flash_hits_the_catalogue():
    """The public id without a version marker used to hit no row and fell
    back to the provider's union with `quelle: unbekannt`."""
    profile = _profile(DEEPSEEK, "deepseek-flash")
    assert profile.quelle == "katalog"
    assert profile.als_dict()["standard"] == "high"


def test_glm_5_2_offers_only_what_acts_differently():
    profile = _profile(ZAI, "glm-5.2")
    assert profile.stufen == ["off", "high", "max"]
    glm = _zustand(_endpunkt(url=ZAI), "glm-5.2")
    assert zusatz("off", glm) == {"thinking": {"type": "disabled"}}
    assert zusatz("high", glm) == {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}
    assert zusatz("max", glm) == {"thinking": {"type": "enabled"}, "reasoning_effort": "max"}
    assert zusatz("low", glm) == {}


def test_glm_5_3_always_thinks():
    profile = _profile(ZAI, "glm-5.3")
    assert profile.stufen == ["low", "high", "max"]
    glm = _zustand(_endpunkt(url=ZAI), "glm-5.3")
    assert zusatz("off", glm) == {}
    assert zusatz("low", glm) == {"thinking": {"type": "enabled"}, "reasoning_effort": "low"}


def test_glm_from_4_5_stays_a_switch():
    """Silence probe: the switch generation is untouched."""
    for model in ("glm-4.5", "glm-4.6", "glm-5", "glm-5.1"):
        assert _profile(ZAI, model).stufen == ["off", "on"], model


def test_grok_stage_only_where_the_provider_takes_it():
    assert _profile(XAI, "grok-4.6").stufen == ["low", "medium", "high", "xhigh"]
    assert _profile(XAI, "grok-4.5").stufen == ["low", "medium", "high"]
    assert _profile(XAI, "grok-3-mini").stufen == ["low", "medium", "high"]
    assert _profile(XAI, "grok-4.20-multi-agent").stufen == ["low", "medium", "high"]
    assert _profile(XAI, "grok-4.3").stufen == ["off", "low", "medium", "high"]
    # Any other Grok model thinks on its own and refuses the field.
    profile = _profile(XAI, "grok-4.20")
    assert profile.stufen == [] and profile.art == denkstufen.ALWAYS
    assert zusatz("high", _zustand(_endpunkt(url=XAI), "grok-4.20")) == {}


def test_minimax_m3_splits_thinking_on_its_route():
    m3 = _zustand(_endpunkt(url=MINIMAX), "MiniMax-M3")
    assert zusatz("on", m3) == {"thinking": {"type": "adaptive"}, "reasoning_split": True}
    assert zusatz("off", m3) == {"thinking": {"type": "disabled"}, "reasoning_split": True}


def test_minimax_m3_elsewhere_has_no_split():
    """Silence probe: the field belongs to one route of the provider. The
    same model at another address of the same host, or at a sub-domain of
    it, goes out as before."""
    for url in ("https://api.minimax.io/v2", "https://eu.api.minimax.io/v1"):
        m3 = _zustand(_endpunkt(url=url), "MiniMax-M3")
        assert zusatz("on", m3) == {"thinking": {"type": "adaptive"}}, url


def test_qwen_mistral_kimi_google_stay_as_they_are():
    """Silence probe for the provider rows above."""
    assert _profile("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3.8-max").stufen == [
        "off",
        "on",
    ]
    assert _profile("https://api.mistral.ai/v1", "mistral-small").stufen == ["off", "high"]
    assert _profile("https://api.kimi.ai/v1", "kimi-k3").stufen == ["low", "high", "max"]
    assert _profile(
        "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.6-flash"
    ).stufen == ["minimal", "low", "medium", "high"]


def test_a_codex_model_never_offers_minimal():
    """Whichever row or list a Codex model inherits its stages from, the
    Responses API refuses `minimal` for it."""
    gpt5_codex = _profile(OPENAI, "gpt-5-codex")
    assert "minimal" not in gpt5_codex.stufen
    assert gpt5_codex.stufen == ["low", "medium", "high"]
    assert "minimal" not in _profile(OPENAI, "codex-mini-latest").stufen


def test_gpt_5_keeps_minimal():
    """Silence probe: the models the documentation gives `minimal` keep it."""
    for model in ("gpt-5", "gpt-5-mini", "gpt-5-nano"):
        assert _profile(OPENAI, model).stufen == ["minimal", "low", "medium", "high"], model
    assert _profile(OPENAI, "gpt-5").standard == "medium"


def test_minimax_m3_splits_thinking_without_a_stage():
    """The split says where the thinking is delivered, not whether there is
    any: it goes out with no stage picked, and with a stage this model does
    not offer, so the thinking never lands in the answer text."""
    m3 = _zustand(_endpunkt(url=MINIMAX), "MiniMax-M3")
    assert zusatz(None, m3) == {"reasoning_split": True}
    assert zusatz("high", m3) == {"reasoning_split": True}
    assert zusatz("on", m3, abgelehnt=["on"]) == {"reasoning_split": True}
    assert zusatz(None, _zustand(_endpunkt(url=MINIMAX), "minimax/MiniMax-M3")) == {
        "reasoning_split": True
    }


def test_an_m3_variant_gets_the_split():
    """A variant finds the model's row the way every lookup does, by the
    longest prefix, and with it the route's field."""
    variant = _zustand(_endpunkt(url=MINIMAX), "MiniMax-M3-highspeed")
    assert zusatz("on", variant) == {"thinking": {"type": "adaptive"}, "reasoning_split": True}
    assert zusatz(None, variant) == {"reasoning_split": True}


def test_a_non_reasoning_grok_does_not_always_think():
    profile = _profile(XAI, "grok-4.20-0309-non-reasoning")
    assert profile.art == denkstufen.NEVER
    # Its undated alias, which the provider documents beside it.
    assert _profile(XAI, "grok-4.20-non-reasoning").art == denkstufen.NEVER
    assert _profile(XAI, "grok-4.20").art == denkstufen.ALWAYS


def test_a_provider_prefix_finds_the_same_row():
    """The stage lookup and the route fields read a model name the same way:
    a provider prefix in front of it changes nothing."""
    plain = _profile("https://api.minimax.io/v1", "MiniMax-M3")
    prefixed = _profile("https://api.minimax.io/v1", "minimax/MiniMax-M3")
    assert prefixed.quelle == plain.quelle == "katalog"
    assert prefixed.stufen == plain.stufen
    assert denkstufen.model_key(" minimax/MiniMax-M3 ") == "minimax-m3"


# --- a template that sits in tokenizer_config.json -------------------------


def _config_only_catalogue(tmp_path, chat_template, *, bom: bool = False):
    """A shelf of one model whose folder has no `chat_template.jinja`, only a
    `tokenizer_config.json` with the given `chat_template` field."""
    from app.discovery import templates_read

    folder = tmp_path / "cfg"
    folder.mkdir()
    text = json.dumps({"chat_template": chat_template, "model_max_length": 1024})
    (folder / "tokenizer_config.json").write_text(
        ("﻿" if bom else "") + text, encoding="utf-8"
    )
    templates = templates_read({"Qwen3.8-27B": str(folder)})
    return {"familien": {"Qwen3.8-27B": "qwen3_5"}, "templates": templates}


def test_a_template_only_in_the_tokenizer_config_names_its_depths(tmp_path):
    detected = _config_only_catalogue(tmp_path, QWEN38_TEMPLATE)

    profile = denkstufen.stufen_fuer(_endpunkt(dialekt="mlx"), "Qwen3.8-27B", detected)

    assert set(profile.stufen) == {"off", "low", "medium", "xhigh"}
    assert profile.quelle == "vorlage"


def test_a_list_of_named_templates_gives_the_default_one(tmp_path):
    named = [
        {"name": "tool_use", "template": QWEN35_TEMPLATE},
        {"name": "default", "template": QWEN38_TEMPLATE},
    ]
    detected = _config_only_catalogue(tmp_path, named)

    profile = denkstufen.stufen_fuer(_endpunkt(dialekt="mlx"), "Qwen3.8-27B", detected)

    assert set(profile.stufen) == {"off", "low", "medium", "xhigh"}


def test_a_tokenizer_config_with_a_byte_order_mark_reads_the_same(tmp_path):
    detected = _config_only_catalogue(tmp_path, QWEN38_TEMPLATE, bom=True)

    profile = denkstufen.stufen_fuer(_endpunkt(dialekt="mlx"), "Qwen3.8-27B", detected)

    assert set(profile.stufen) == {"off", "low", "medium", "xhigh"}


def test_silence_a_template_without_depths_in_the_config_keeps_the_switch(tmp_path):
    detected = _config_only_catalogue(tmp_path, QWEN35_TEMPLATE)

    profile = denkstufen.stufen_fuer(_endpunkt(dialekt="mlx"), "Qwen3.8-27B", detected)

    assert profile.stufen == ["off", "on"]
