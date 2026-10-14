"""The thinking length: offered everywhere, locked where it does nothing.

The one knob that breaks the rule the rest of app/parameter.py keeps. So the
exception is nailed down here in both directions — it must appear for every
dialect, and it must be inert everywhere it is locked.
"""

from __future__ import annotations

import pytest

from app import (
    agentenmodellwahl, agentenserver, auftragdenklaengewahl, denkschalter, discovery, parameter,
)
from app.agenten import AgentDateiKaputt, agent_aus_text
from app.config import Capabilities
from app.i18n import t
from app.parameter import (
    DIALEKTE, GRUND_ALLGEMEIN, MODELL_OHNE_REASONING, pruefen, uebersetzen, unterstuetzte,
)
from app.providers import MockProvider, ProviderFehler, mock_endpunkt
from tests.conftest import agentenmodell_leer, lokaler_endpunkt, provider_setzen

NAME = "reasoning_budget"


def _eintrag(dialekt: str, sprache: str = "de") -> dict:
    for p in unterstuetzte(dialekt):
        wert = p.als_dict(sprache)
        if wert["name"] == NAME:
            return wert
    raise AssertionError(f"{dialekt} does not offer the thinking length")


# --- Offered everywhere ---------------------------------------------------


def test_jeder_dialekt_zeigt_den_regler():
    """The whole point of the exception: every menu has the same rows."""
    for dialekt in DIALEKTE:
        assert _eintrag(dialekt)["name"] == NAME


def test_er_steht_neben_der_antwortlaenge():
    namen = [p.name for p in unterstuetzte("llama_cpp") if p.gruppe == "sichtbar"]
    assert namen[namen.index("max_tokens") + 1] == NAME


def test_aktiv_nur_wo_er_wirkt():
    assert _eintrag("llama_cpp")["aktiv"] is True
    for dialekt in ("mlx", "openai", "anthropic"):
        assert _eintrag(dialekt)["aktiv"] is False, dialekt


def test_der_gesperrte_regler_sagt_warum_und_zwar_zweisprachig():
    for dialekt in ("mlx", "openai", "anthropic"):
        deutsch = _eintrag(dialekt, "de")["grund"]
        englisch = _eintrag(dialekt, "en")["grund"]
        assert deutsch and englisch, dialekt
        assert deutsch != englisch, dialekt


def test_ein_wirksamer_regler_traegt_keinen_grund():
    """A reason on a working knob would be an explanation of nothing."""
    assert _eintrag("llama_cpp")["grund"] is None


def test_die_uebrigen_parameter_bleiben_wie_sie_waren():
    """The exception is for ONE knob. Everything else still disappears where
    the dialect has no name for it."""
    namen = {p.name for p in unterstuetzte("anthropic")}
    assert "typical_p" not in namen
    assert "seed" not in namen


def test_das_kontextfenster_deckelt_ihn_wie_die_antwortlaenge():
    """Both are spent out of the same window."""
    eintrag = next(p for p in unterstuetzte("llama_cpp", 4096) if p.name == NAME)
    assert eintrag.maximum == 4096


# --- What the save path does with it ---------------------------------------


def test_auto_uebersteht_das_speichern():
    """-1 is Auto, not "below the smallest number" — a floor of 0 used to
    turn a stored -1 into a 0, which reads as "no thinking at all"."""
    assert pruefen({NAME: -1}) == {NAME: -1}


def test_aus_bleibt_aus():
    """The silence probe for the floor: 0 still means "no thinking", not Auto."""
    assert pruefen({NAME: 0}) == {NAME: 0}


def test_nichts_faellt_unter_auto():
    assert pruefen({NAME: -5}) == {NAME: -1}


def test_der_speicherweg_deckelt_am_kontextfenster():
    """The same number the display caps (test above): saving 200,000 at a
    window of 8,192 must not go through unchanged."""
    assert pruefen({"max_tokens": 200_000}, 8192) == {"max_tokens": 8192}
    assert pruefen({NAME: 200_000}, 8192) == {NAME: 8192}


def test_ohne_bekanntes_fenster_bleibt_die_zahl_wie_sie_war():
    """The silence probe: a caller that does not know the model's window
    (today's every call, until a caller starts passing one) keeps today's
    behaviour exactly."""
    assert pruefen({"max_tokens": 200_000}) == {"max_tokens": 200_000}


def test_ein_fenster_unter_der_eigenen_untergrenze_gewinnt_trotzdem():
    """The window is what actually fits, not a suggestion — a knob's own
    floor (max_tokens' 256) must not outrank a window smaller than that."""
    assert pruefen({"max_tokens": 300}, 100) == {"max_tokens": 100}


def test_auto_bleibt_auto_auch_mit_fenster():
    """The window narrows the ceiling, never the floor — Auto is below every
    window and stays Auto."""
    assert pruefen({NAME: -1}, 4096) == {NAME: -1}


# --- What actually gets sent ----------------------------------------------


def test_llama_cpp_bekommt_das_gemessene_feld():
    assert uebersetzen("llama_cpp", {NAME: 512}) == {"reasoning_budget_tokens": 512}


def test_ein_gesperrter_regler_sendet_nichts():
    """The silence probe. A locked knob is shown, never sent — and a stored
    value from a model that HAD it must not follow along to one that has
    not."""
    for dialekt in ("mlx", "openai", "anthropic"):
        assert uebersetzen(dialekt, {NAME: 512}) == {}, dialekt


def test_ein_nicht_angefasster_regler_sendet_nichts():
    """The second silence probe: nothing set, nothing sent, and the server
    keeps doing whatever it did before this knob existed."""
    assert uebersetzen("llama_cpp", {NAME: None}) == {}
    assert uebersetzen("llama_cpp", {}) == {}


def test_die_null_ist_ein_wert_und_kein_leerzeichen():
    """Zero means "do not think", which is a wish, not an absent one."""
    assert uebersetzen("llama_cpp", {NAME: 0}) == {"reasoning_budget_tokens": 0}


# --- The agent's own ------------------------------------------------------


def _agent(kopf: str):
    return agent_aus_text("pruef", f"---\n{kopf}\n---\n\nTu etwas.\n")


def test_der_agent_darf_eine_denklaenge_nennen():
    assert _agent("reasoning_budget: 2048").denklaenge == 2048


def test_ohne_angabe_hat_der_agent_keine_meinung():
    assert _agent("max_rounds: 3").denklaenge is None


def test_unsinn_im_agentenkopf_faellt_auf():
    with pytest.raises(AgentDateiKaputt):
        _agent("reasoning_budget: viel")
    with pytest.raises(AgentDateiKaputt):
        _agent("reasoning_budget: -2")


def test_auto_im_agentenkopf_ist_gueltig():
    """-1 is Auto, as in a chat — not a broken file."""
    assert _agent("reasoning_budget: -1").denklaenge == -1


def test_der_agentenkopf_schlaegt_die_einstellung(repos):
    repos.einstellungen.setzen("global", "parameter", {NAME: 256})
    assert auftragdenklaengewahl.aufgeloest(
        repos, modell="qwen", agent_wert=4096
    ) == 4096


def test_ohne_agentenwort_zaehlt_die_einstellung(repos):
    repos.einstellungen.setzen("modell:qwen", "parameter", {NAME: 768})
    assert auftragdenklaengewahl.aufgeloest(
        repos, modell="qwen", agent_wert=None
    ) == 768


def test_ein_gespeichertes_auto_kommt_als_auto_zurueck(repos):
    """-1 is Auto in the job path as in a chat, not "nothing"."""
    repos.einstellungen.setzen("global", "parameter", {NAME: -1})
    assert auftragdenklaengewahl.aufgeloest(
        repos, modell="qwen", agent_wert=None
    ) == -1


def test_ein_auto_des_agenten_schlaegt_die_einstellung(repos):
    repos.einstellungen.setzen("modell:qwen", "parameter", {NAME: 768})
    assert auftragdenklaengewahl.aufgeloest(
        repos, modell="qwen", agent_wert=-1
    ) == -1


def test_unter_auto_bleibt_alles_ungueltig():
    assert auftragdenklaengewahl.wahl_pruefen(-2) is None
    assert auftragdenklaengewahl.wahl_pruefen(-1) == -1


def test_sagt_niemand_etwas_geht_nichts_mit(repos):
    """The silence probe for the job path: an unset thinking length is not a
    zero, it is no field at all."""
    assert auftragdenklaengewahl.aufgeloest(
        repos, modell="qwen", agent_wert=None
    ) is None


# --- Backend AND model ----------------------------------------------------


def _regler(dialekt: str, reasoning: bool | None, sprache: str = "de") -> dict:
    """The same row, but with what the discovery knows about the model.

    ``None`` is the caller that knows nothing about a model — the eight
    places that ask for the list as such.
    """
    faehigkeiten = None if reasoning is None else {"reasoning": reasoning}
    for p in unterstuetzte(dialekt, None, faehigkeiten):
        wert = p.als_dict(sprache)
        if wert["name"] == NAME:
            return wert
    raise AssertionError(f"{dialekt} does not offer the thinking length")


def test_der_regler_folgt_backend_und_modell_zugleich():
    """The availability of the thinking length comes
    from the backend's ability AND the model's — one line per combination
    of the two."""
    # llama.cpp with a model that can think: the one active case.
    assert _regler("llama_cpp", True)["aktiv"] is True
    # llama.cpp with a model that cannot: locked, and the reason names the
    # MODEL.
    gesperrt = _regler("llama_cpp", False)
    assert gesperrt["aktiv"] is False
    assert gesperrt["grund"] == (
        "Dieses Modell unterstützt kein Reasoning. Daher lässt sich keine Denklänge einstellen."
    )
    # The three dialects whose wire carries no such number: locked with and
    # without reasoning in the model, and the reason names the SERVER.
    for dialekt in ("openai", "anthropic", "mlx"):
        for reasoning in (True, False):
            eintrag = _regler(dialekt, reasoning)
            assert eintrag["aktiv"] is False, dialekt
            assert eintrag["grund"] == (
                "Dieser Server unterstützt keine einstellbare Denklänge."
            ), dialekt


def test_die_beiden_gruende_sagen_verschiedenes():
    """Two reasons, two places to look — the wire or the model. A reader who
    is handed the wrong one looks in the wrong place."""
    assert _regler("llama_cpp", False)["grund"] != _regler("mlx", True)["grund"]


def test_der_modell_grund_steht_auch_englisch():
    assert _regler("llama_cpp", False, "en")["grund"] == (
        "This model does not support reasoning, so its thinking length cannot be configured."
    )


def test_ohne_wissen_ueber_das_modell_bleibt_alles_wie_bisher():
    """The silence probe for the eight call sites that know nothing about a
    model: they get exactly the list they got before."""
    for dialekt, aktiv in (("llama_cpp", True), ("mlx", False), ("openai", False)):
        assert _regler(dialekt, None)["aktiv"] is aktiv, dialekt


def test_ein_leeres_faehigkeiten_set_sperrt_nichts():
    """Two ways of saying nothing, and neither is a "no".

    A caller that hands in a set of capabilities without the key (the shape
    `Capabilities().model_dump()` has) has not claimed the model is unable
    to think — and locking there would grey the knob for a thinking model
    while naming the model as the culprit.
    """
    for leer in ({}, {"thinking": ["off", "high"]}, {"reasoning": None}):
        assert _regler("llama_cpp", None)["aktiv"] is True
        for p in unterstuetzte("llama_cpp", None, leer):
            if p.name == NAME:
                assert p.aktiv is True, leer



# --- The row the agent mask locks on --------------------------------------


# Both routes are asked in ONE language, said out loud rather than inherited
# from whatever the configuration stand-in happens to carry: the reason text
# travels with the answer, so a mismatch would be a test failure about the
# language and not about the rule.
DEUTSCH = {"Accept-Language": "de"}


def _listenreihe(client, kennung: str) -> dict:
    """The row the MODEL window draws its slider from, for one model."""
    for eintrag in client.get("/api/v1/models", headers=DEUTSCH).json():
        if eintrag["id"] == kennung:
            return next(p for p in eintrag["parameter"] if p["name"] == NAME)
    raise AssertionError(f"{kennung} is not in the model list")


async def _endpunkt_an(client, kennung: str, dialekt: str, faehigkeiten: Capabilities):
    """One of the two own servers, up and answering, with this dialect and
    these capabilities — the hand's answer about thinking among them."""
    await client.app.state.discovery.anmelden(
        mock_endpunkt(kennung, parameter_dialect=dialekt, capabilities=faehigkeiten)
    )


async def test_der_agentenkopf_bekommt_die_reihe_des_laufmodells(client):
    """The agent mask's field is locked by the very answer the
    model window's slider is locked by — not by a second one.

    The mask has no model pick (which model a run takes is said in the model
    window's field), so it asks ``/jobs/laufmodell`` with the tool switch it
    shows. The answer carries the thinking-length row for the model a run
    started NOW would take — held here against the model list's own row, in
    all three situations: field active, locked for the MODEL, locked for the
    SERVER.
    """
    lagen = (
        ("llama_cpp", True, True, None),
        ("llama_cpp", False, False, t(MODELL_OHNE_REASONING, "de")),
        ("mlx", True, False, t(GRUND_ALLGEMEIN, "de")),
    )
    for dialekt, denkt, aktiv, grund in lagen:
        faehigkeiten = Capabilities(streaming=True, tool_calls=True, thinking=denkt)
        await _endpunkt_an(client, agentenmodellwahl.HAUPTMODELL, dialekt, faehigkeiten)
        provider_setzen(
            client,
            MockProvider(
                mock_endpunkt(
                    agentenmodellwahl.HAUPTMODELL,
                    parameter_dialect=dialekt,
                    capabilities=faehigkeiten,
                )
            ),
            endpoint_id=agentenmodellwahl.HAUPTMODELL,
        )

        antwort = client.get("/api/v1/jobs/laufmodell", headers=DEUTSCH).json()
        reihe = antwort["denklaenge"]
        assert reihe is not None, dialekt
        assert reihe["name"] == NAME
        assert reihe["aktiv"] is aktiv, dialekt
        assert reihe["grund"] == grund, dialekt
        # The very row the model list hands out for this model — reason and
        # wording included, in the language of this request.
        assert reihe == _listenreihe(client, antwort["endpoint_id"]), dialekt


def test_der_agentenkopf_folgt_dem_werkzeugschalter(client):
    """The mask always sends the tool switch it is showing, and that switch
    is what decides whether a run goes through the agent server. The row must
    follow the model the run then lands on — not the one it would have taken
    without tools.
    """
    lokaler_endpunkt(
        client,
        MockProvider(
            mock_endpunkt(
                agentenserver.ENDPUNKT_ID, parameter_dialect="llama_cpp",
                capabilities=Capabilities(streaming=True, tool_calls=True, thinking=True),
            )
        ),
        endpoint_id=agentenserver.ENDPUNKT_ID,
    )
    # No hand pick in the model field: that one beats the agent server, and
    # this situation is about the agent server being taken at all.
    agentenmodell_leer(client)

    antwort = client.get(
        "/api/v1/jobs/laufmodell", params={"werkzeuge": "true"}, headers=DEUTSCH
    ).json()
    assert antwort["endpoint_id"] == agentenserver.ENDPUNKT_ID
    assert antwort["denklaenge"] == _listenreihe(client, antwort["endpoint_id"])


async def test_the_agent_head_reads_the_refusals_the_model_list_reads(client):
    """A run picked as a catalogue server alone (`test`) still reads the
    refused stages under the id the model list carries (`test:m`): a model
    that refused every stage it had is locked in the mask as in the list."""
    from app import denkablehnung

    faehigkeiten = Capabilities(streaming=True, tool_calls=True, thinking=True)
    await _endpunkt_an(client, "test", "llama_cpp", faehigkeiten)
    provider_setzen(
        client,
        MockProvider(mock_endpunkt("test", parameter_dialect="llama_cpp", capabilities=faehigkeiten)),
    )
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.modelle = ["m"]
    zustand.gemeldeter_name = "m"
    einstellungen = client.app.state.repositories.einstellungen
    for stufe in zustand.denkprofil("m").stufen:
        denkablehnung.merken(einstellungen, "test:m", stufe)

    antwort = client.get(
        "/api/v1/jobs/laufmodell", params={"endpoint_id": "test"}, headers=DEUTSCH
    ).json()
    assert antwort["endpoint_id"] == "test"
    assert antwort["denklaenge"]["aktiv"] is False
    assert antwort["denklaenge"] == _listenreihe(client, "test:m")


async def test_ohne_modell_sperrt_der_agentenkopf_nichts(client):
    """The silence probe: where nobody can say which model a run would take,
    the answer carries no row at all — and the field stays as it was.

    "Nobody could say" may not be read as "cannot think" (`app/parameter.py`):
    a locked field naming the model as the culprit would be the wrong answer.
    """
    agentenmodell_leer(client)
    for zustand in client.app.state.discovery.zustaende.values():
        zustand.erreichbar = False

    antwort = client.get("/api/v1/jobs/laufmodell").json()
    assert antwort["endpoint_id"] is None
    assert antwort["denklaenge"] is None


# --- The lock on the wire ---------------------------------------------------


class _Einstellungen:
    """Where a refusal is kept — one area per model, one list per area
    (app/denkablehnung.py). Only what the wire question reads."""

    def __init__(self, gemerkt: dict[tuple[str, str], object] | None = None):
        self.gemerkt = gemerkt or {}

    def holen(self, bereich: str, schluessel: str):
        return self.gemerkt.get((bereich, schluessel))


def _zustand(dialekt: str, denken: bool | None = True, *, id: str = "x"):
    """A REAL state — not a stand-in. The wire question reads the very
    capabilities the model list shows, so the two can only be held together
    by walking the same path they walk (app/discovery.py
    `_capabilities_aufloesen`)."""
    from app.config import Capabilities, EndpointConfig
    from app.discovery import EndpunktZustand

    endpunkt = EndpointConfig(
        id=id,
        base_url="http://127.0.0.1:9/v1",
        parameter_dialect=dialekt,
        capabilities=Capabilities(thinking=denken),
    )
    return EndpunktZustand(endpunkt=endpunkt, provider=None)


def _gesendet(zustand, werte: dict, einstellungen=None) -> dict:
    """What of these parameters actually goes out for this state."""
    return parameter.ohne_gesperrte_denklaenge(
        werte,
        freigegeben=discovery.denklaenge_erlaubt(zustand, "m", einstellungen),
    )


WERTE = {"reasoning_budget": 2048, "top_k": 40}


def test_ein_denkmodell_bekommt_die_denklaenge():
    assert _gesendet(_zustand("llama_cpp", True), WERTE) == WERTE


def test_ein_nicht_denkendes_modell_bekommt_sie_nicht():
    assert _gesendet(_zustand("llama_cpp", False), WERTE) == {"top_k": 40}


def test_ein_backend_ohne_zahlenbudget_bekommt_sie_nicht():
    """Even a stated zero stays home: the wire has no such field, and a
    number that goes nowhere is worse than none."""
    assert _gesendet(_zustand("openai", True), {"reasoning_budget": 0, "top_k": 40}) == {
        "top_k": 40
    }


def test_der_rueckwechsel_sendet_den_alten_wert_wieder():
    """The stored value is not touched — the same numbers go out again the
    moment a model with a usable thinking length is in use."""
    einmal: dict = dict(WERTE)
    assert _gesendet(_zustand("llama_cpp", False), einmal) == {"top_k": 40}
    assert einmal == WERTE, "the stored value was changed"
    assert _gesendet(_zustand("llama_cpp", True), einmal) == WERTE


def test_ohne_gespeicherten_wert_bleibt_alles_wie_es_war():
    """The silence probe: a request that never asked for a thinking length
    goes out unchanged, whatever the model can do."""
    for zustand in (_zustand("llama_cpp", True), _zustand("llama_cpp", False), _zustand("openai", True)):
        assert _gesendet(zustand, {"top_k": 40}) == {"top_k": 40}


def test_die_ablehnung_wird_unter_der_kennung_der_modellliste_gesucht():
    """A refused stage turns a switchable model into one that cannot think —
    but only where the list looks for it, which is `<endpoint>:<model>`.
    Read under the bare endpoint id, the refusal would never be found and
    the wire would send a length the window has already locked."""
    zustand = _zustand("llama_cpp", True)
    # A server with a catalogue: the list carries `<endpoint>:<model>`.
    zustand.modelle = ["m", "n"]
    abgelehnt = _Einstellungen({("modell:x:m", "denken_abgelehnt"): ["off", "on"]})

    assert discovery.denklaenge_erlaubt(zustand, "m", abgelehnt) is False
    assert discovery.denklaenge_erlaubt(zustand, "m") is True, (
        "without settings no refusal is read — the fold's reading"
    )


def test_a_server_without_catalogue_keeps_one_refusal_list():
    """A server that names no catalogue stands in the list under its
    endpoint id alone, and the fold and the chat write its refusals there.
    The thinking length used to look under `<endpoint>:<reported name>` and
    never found them — two lists for one server."""
    zustand = _zustand("llama_cpp", True)
    zustand.gemeldeter_name = "Example 35B"
    # What the fold wrote after the server refused its "off".
    abgelehnt = _Einstellungen({("modell:x", "denken_abgelehnt"): ["off", "on"]})
    assert discovery.denklaenge_erlaubt(zustand, "Example 35B", abgelehnt) is False
    # Silence probe: another server's list is its own.
    anderer = _zustand("llama_cpp", True, id="y")
    anderer.gemeldeter_name = "Example 35B"
    assert discovery.denklaenge_erlaubt(anderer, "Example 35B", abgelehnt) is True


def test_ein_anbieter_ohne_katalogmodell_bleibt_gesperrt():
    """A model nobody has entered — not even in the provider table — cannot
    be told to think, and the list locks its knob for the same reason.
    Measured against the real state, not against a stand-in: the answer
    comes from the same profile the window reads."""
    assert _gesendet(_zustand("llama_cpp", None), WERTE) == {"top_k": 40}


def test_ein_modell_das_immer_denkt_behaelt_die_denklaenge():
    """The neighbour case: a model that thinks and cannot be switched off has
    no locked knob, so its number travels. The catalogue names it by family
    (app/daten/denkstufen.yaml, `immer: true`) — the same row the window
    reads for its stage list."""
    zustand = _zustand("llama_cpp", None, id="y")

    assert discovery.denklaenge_erlaubt(zustand, "qwen3-thinking") is True
    assert discovery.denklaenge_erlaubt(zustand, "irgendwas") is False, (
        "the same endpoint, a name without a catalogue entry — the name decides"
    )


# --- The off switch and the length agree ------------------------------------


def test_ist_aus_erkennt_beide_formen():
    for wert in (False, "off", "OFF", " Off "):
        assert denkschalter.ist_aus(wert) is True


def test_ist_aus_verneint_alles_andere():
    for wert in (True, "on", "high", None):
        assert denkschalter.ist_aus(wert) is False


def test_ausschalten_reicht_die_ablehnung_durch():
    """``off`` itself can be a stage the provider has already
    refused — without threading ``abgelehnt`` through, ``ausschalten`` would
    offer that exact refused switch again."""
    zustand = _zustand("llama_cpp", True)
    frei, _ = denkschalter.ausschalten(zustand, {})
    abgelehnt, _ = denkschalter.ausschalten(zustand, {}, abgelehnt=["off"])
    assert frei != {}
    assert abgelehnt == {}


def _reasoning_gesetzt(client, budget: int = 2048) -> None:
    from app.db.repositories.einstellungen import GLOBAL

    client.app.state.repositories.einstellungen.setzen(
        GLOBAL, "parameter", {"reasoning_budget": budget}
    )


def _chat_senden(client, chat_id: str, **felder) -> None:
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Frage", **felder},
    )
    assert antwort.status_code == 200
    antwort.text  # drain the stream so the run finishes


def _denkendes_llama_cpp_setzen(client) -> MockProvider:
    """The test endpoint, put on the llama.cpp wire with a model that can
    think — the two things ``denklaenge_erlaubt`` asks for together.
    ``provider_setzen`` alone leaves the endpoint's own dialect
    and capabilities untouched (they live on ``zustand.endpunkt``, not on the
    provider it swaps in), so this sets that explicitly — the same way
    ``_anthropic_draht`` does in tests/test_antwortgrenze.py."""
    endpunkt = mock_endpunkt(
        "test",
        parameter_dialect="llama_cpp",
        capabilities=Capabilities(streaming=True, tool_calls=True, thinking=True),
    )
    provider = provider_setzen(client, MockProvider(endpunkt))
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.endpunkt = endpunkt
    zustand.context_tokens = 32_768
    return provider


def test_stufe_aus_nimmt_die_denklaenge_mit(client, chat_id):
    """Off and a stored thinking length used to go out
    together — two contradicting answers in one request. The chat now
    routes off through ``denkschalter.ausschalten``, the same way the fold
    already does (app/verdichtung.py)."""
    provider = _denkendes_llama_cpp_setzen(client)
    _reasoning_gesetzt(client)

    _chat_senden(client, chat_id, thinking="off")

    gesendet = provider.letzte_anfrage
    assert "reasoning_budget" not in gesendet.parameter
    assert gesendet.zusatz.get("reasoning_effort") == "none"


def test_jede_andere_stufe_behaelt_die_denklaenge(client, chat_id):
    """The silence probe: with no opinion about the stage, the stored length
    still travels exactly as before."""
    provider = _denkendes_llama_cpp_setzen(client)
    _reasoning_gesetzt(client)

    _chat_senden(client, chat_id)

    assert provider.letzte_anfrage.parameter.get("reasoning_budget") == 2048


# --- The lock at its call sites -------------------------------------------


def _gesperrtes_llama_cpp_setzen(client) -> MockProvider:
    """The test endpoint on the llama.cpp wire with a model that cannot
    think: the thinking length is locked there."""
    endpunkt = mock_endpunkt(
        "test",
        parameter_dialect="llama_cpp",
        capabilities=Capabilities(streaming=True, tool_calls=True, thinking=False),
    )
    provider = provider_setzen(client, MockProvider(endpunkt))
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.endpunkt = endpunkt
    zustand.context_tokens = 32_768
    return provider


def test_der_chat_sendet_eine_gesperrte_denklaenge_nicht(client, chat_id):
    """The lock is tested at the chat route, not only on its own: taken
    out of the chat path, this test fails."""
    provider = _gesperrtes_llama_cpp_setzen(client)
    _reasoning_gesetzt(client)

    _chat_senden(client, chat_id)

    assert provider.letzte_anfrage is not None
    assert "reasoning_budget" not in provider.letzte_anfrage.parameter


# --- A refused "off" is learned -------------------------------------------

ABLEHNUNG = "thinking: this parameter is not supported by this model"


def _ablehnendes_llama_cpp_setzen(client, denken: bool = True) -> None:
    """A llama.cpp model whose server refuses every request with a sentence
    naming thinking; ``denken`` says whether the model can think at all."""
    from app import denkablehnung

    assert denkablehnung.ist_ablehnung(400, ABLEHNUNG)

    endpunkt = mock_endpunkt(
        "test",
        parameter_dialect="llama_cpp",
        capabilities=Capabilities(streaming=True, tool_calls=True, thinking=denken),
    )

    class Ablehnend(MockProvider):
        async def streamen(self, anfrage):
            self.letzte_anfrage = anfrage
            raise ProviderFehler("abgelehnt", status=400, rohtext=ABLEHNUNG)
            yield  # pragma: no cover

    provider_setzen(client, Ablehnend(endpunkt))
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.endpunkt = endpunkt
    zustand.context_tokens = 32_768


@pytest.mark.parametrize("stufe", [False, "off"])
def test_eine_abgelehnte_stufe_aus_wird_gelernt(client, chat_id, stufe):
    """`False` is the older form of "off", not "no stage given": a refusal
    of it is written down like any other stage's."""
    from app import denkablehnung

    _ablehnendes_llama_cpp_setzen(client)

    _chat_senden(client, chat_id, thinking=stufe)

    assert denkablehnung.gemerkt(client.app.state.repositories.einstellungen, "test") == ["off"]


def test_ohne_gesendete_stufe_wird_nichts_gelernt(client, chat_id):
    """The silence probe: a refused request that carried no stage leaves the
    list alone. A model that can think is now sent its stored stage, or its
    default, when the window names none — so only one that cannot think
    still sends nothing."""
    from app import denkablehnung

    _ablehnendes_llama_cpp_setzen(client, denken=False)

    _chat_senden(client, chat_id)

    assert denkablehnung.gemerkt(client.app.state.repositories.einstellungen, "test") == []


def test_eine_stufe_ohne_gesendete_felder_wird_nicht_gelernt(client, chat_id):
    """A model that cannot think gets no fields for "high": the refusal is
    about something else and must not take the stage away."""
    from app import denkablehnung

    _ablehnendes_llama_cpp_setzen(client, denken=False)
    zustand = client.app.state.discovery.zustaende["test"]
    assert denkschalter.zusatz("high", zustand) == {}, "fields went out, the test proves nothing"

    _chat_senden(client, chat_id, thinking="high")

    assert denkablehnung.gemerkt(client.app.state.repositories.einstellungen, "test") == []


# --- The limits stand in one place -----------------------------------------


def test_the_thinking_limits_are_the_knobs_own():
    """Moving the knob's ceiling moves the job check with it: the settings
    clamp and ``wahl_pruefen`` name the same range. (``app/agenten.py``
    imports the same two names, so it reads them from here as well.)"""
    import dataclasses
    import importlib

    knob = parameter.NACH_NAME["reasoning_budget"]
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setitem(
                parameter.NACH_NAME,
                "reasoning_budget",
                dataclasses.replace(knob, maximum=5000),
            )
            reloaded = importlib.reload(auftragdenklaengewahl)
            assert parameter.pruefen({"reasoning_budget": 9999})["reasoning_budget"] == 5000
            assert reloaded.OBERGRENZE == 5000
            assert reloaded.wahl_pruefen(5000) == 5000
            assert reloaded.wahl_pruefen(5001) is None
    finally:
        importlib.reload(auftragdenklaengewahl)


def test_auto_off_and_the_ceiling_hold_as_before():
    """The silence probe: -1 is Auto, 0 is off, the ceiling is allowed and
    one above it is refused — in the clamp and in the job check alike."""
    ceiling = int(parameter.NACH_NAME["reasoning_budget"].maximum)
    for value in (-1, 0, ceiling):
        assert auftragdenklaengewahl.wahl_pruefen(value) == value
        assert parameter.pruefen({"reasoning_budget": value})["reasoning_budget"] == value
    assert auftragdenklaengewahl.wahl_pruefen(ceiling + 1) is None
    assert parameter.pruefen({"reasoning_budget": ceiling + 1})["reasoning_budget"] == ceiling
    assert (auftragdenklaengewahl.AUTO, auftragdenklaengewahl.OBERGRENZE) == (-1, ceiling)
