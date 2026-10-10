"""The prompt preparation: the picture window's "Enhance" button and
``draw_image`` ask one route, which writes the prompt with the chosen
server and the instruction of the picture model's family."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.bildprompt import (
    ANWEISUNG_NEGATIV,
    ANWEISUNGEN,
    LESER,
    MAX_EINGABE,
    PromptFehler,
    _saeubern,
    nachricht,
    verbessern,
)
from app import bildaufbereitung, faltversuche, generationen, image_families
from app.i18n import t
from app.providers import ProviderFehler
from app.providers.base import Stueck
from app.providers.mock import MockProvider
from tests.conftest import provider_setzen


def test_prompt_wird_umgeschrieben(client: TestClient):
    provider_setzen(
        client,
        MockProvider(haeppchen=["red bicycle, ", "morning light, 50mm"]),
    )
    antwort = client.post("/api/v1/bild/prompt", json={"prompt": "ein rotes Fahrrad", "familie": "sdxl"})
    assert antwort.status_code == 200
    assert antwort.json()["prompt"] == "red bicycle, morning light, 50mm"


def test_ohne_erreichbares_modell_503(client: TestClient, monkeypatch):
    # Patched instead of flags flipped: the background check would mark the
    # dummy reachable again between the two lines of this test.
    monkeypatch.setattr(client.app.state.discovery, "aufloesen", lambda kennung: None)
    antwort = client.post("/api/v1/bild/prompt", json={"prompt": "ein rotes Fahrrad", "familie": "sdxl"})
    assert antwort.status_code == 503


def test_leerer_prompt_wird_abgewiesen(client: TestClient):
    provider_setzen(client, MockProvider())
    assert client.post("/api/v1/bild/prompt", json={"prompt": "", "familie": "sdxl"}).status_code == 422


def test_zu_langer_prompt_erreicht_das_modell_nicht(client: TestClient):
    provider_setzen(client, MockProvider())
    antwort = client.post(
        "/api/v1/bild/prompt", json={"prompt": "a" * (MAX_EINGABE + 1), "familie": "sdxl"}
    )
    assert antwort.status_code == 502


def test_modellfehler_wird_als_502_gemeldet(client: TestClient):
    provider_setzen(client, MockProvider(fehler="server weg"))
    antwort = client.post("/api/v1/bild/prompt", json={"prompt": "ein rotes Fahrrad", "familie": "sdxl"})
    assert antwort.status_code == 502


def test_leere_antwort_gilt_als_fehler(client: TestClient):
    provider_setzen(client, MockProvider(haeppchen=["  ", "\n"]))
    antwort = client.post("/api/v1/bild/prompt", json={"prompt": "ein rotes Fahrrad", "familie": "sdxl"})
    assert antwort.status_code == 502


@pytest.mark.parametrize(
    "roh,erwartet",
    [
        ('"red bicycle, morning light"', "red bicycle, morning light"),
        ("red bicycle, morning light.", "red bicycle, morning light"),
        ("  red bicycle  ", "red bicycle"),
        ("`red bicycle`", "red bicycle"),
    ],
)
def test_umrahmung_wird_entfernt(roh: str, erwartet: str):
    assert _saeubern(roh) == erwartet


async def test_verbessern_weist_leeren_prompt_ab():
    with pytest.raises(PromptFehler):
        await verbessern(MockProvider(), None, "   ")


async def test_anweisung_steht_als_systemnachricht_vorne():
    """The instruction has to reach the model, not just the module."""

    class Merker(MockProvider):
        def __init__(self):
            super().__init__(haeppchen=["ok"])
            self.gesehen = None

        def streamen(self, anfrage):
            self.gesehen = anfrage
            return super().streamen(anfrage)

    merker = Merker()
    await verbessern(merker, None, "ein rotes Fahrrad", anweisung=ANWEISUNGEN["sdxl"])
    assert merker.gesehen.nachrichten[0].role == "system"
    assert merker.gesehen.nachrichten[0].content == ANWEISUNGEN["sdxl"]
    assert merker.gesehen.nachrichten[1].content == "ein rotes Fahrrad"


# --- The user's own style addition ----------------------------------------


class _Merker(MockProvider):
    """Keeps every request it was handed, so each system message can be read.

    A list and not one field: the route asks twice when there is a negative
    prompt, and the question below is which of the two carried the style.
    """

    def __init__(self):
        super().__init__(haeppchen=["ok"])
        self.anfragen = []

    @property
    def gesehen(self):
        return self.anfragen[-1] if self.anfragen else None

    def streamen(self, anfrage):
        self.anfragen.append(anfrage)
        return super().streamen(anfrage)


# --- The fold's two clocks hold the request -----------------------------------


class _Silent(MockProvider):
    """Nothing but keepalives: no piece arrives. Remembers whether its
    stream was closed."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed = False

    async def streamen(self, anfrage):
        try:
            await asyncio.sleep(3600)
            yield
        finally:
            self.closed = True


class _Endless(MockProvider):
    """Streams on and on, a piece every few milliseconds."""

    async def streamen(self, anfrage):
        while True:
            await asyncio.sleep(0.005)
            yield Stueck("content", text="red ")


def test_a_silent_stream_ends_with_502_and_is_closed(client: TestClient, monkeypatch):
    monkeypatch.setattr(faltversuche, "STILLE_SEKUNDEN", 0.05)
    provider = provider_setzen(client, _Silent())
    answer = client.post("/api/v1/bild/prompt", json={"prompt": "ein rotes Fahrrad", "familie": "sdxl"})
    assert answer.status_code == 502
    assert answer.json()["detail"] == t("bild.prompt_fehlgeschlagen", "de")
    assert provider.closed


class _EndlessClosing(MockProvider):
    """Streams on and on; remembers whether its stream was closed."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed = 0

    async def streamen(self, anfrage):
        try:
            while True:
                await asyncio.sleep(0.005)
                yield Stueck("content", text="red ")
        finally:
            self.closed += 1


def test_the_image_prompt_reads_its_stream_through_the_fold_s_loop(client: TestClient, monkeypatch):
    """The two clocks and the reading of a stream stand once
    (app/faltversuche.read_stream); the image prompt request uses that loop and
    keeps only its own view of an error piece. A stream read beside it would
    leave one of the two clocks unguarded — which is how the two loops came
    apart in the first place."""
    gelesen: list[str] = []
    echt = faltversuche.read_stream

    async def counting(quelle, was):
        gelesen.append(was)
        async for stueck in echt(quelle, was):
            yield stueck

    monkeypatch.setattr(faltversuche, "read_stream", counting)
    monkeypatch.setattr(faltversuche, "GESAMT_SEKUNDEN", 0.05)
    provider_setzen(client, _EndlessClosing())
    answer = client.post("/api/v1/bild/prompt", json={"prompt": "ein rotes Fahrrad", "familie": "sdxl"})
    assert gelesen == ["image prompt request"]
    assert answer.status_code == 502


def test_the_image_route_ends_its_siblings_through_the_shared_place(client, monkeypatch):
    """Both requests end through the one place the runs use
    (app/generationen.discard). A cancel/gather of its own beside it was a
    second way to end a sibling — and that one dropped whatever the sibling
    carried."""
    gerufen: list[object] = []
    echt = generationen.discard

    async def counting(future):
        gerufen.append(future)
        return await echt(future)

    monkeypatch.setattr(generationen, "discard", counting)
    monkeypatch.setattr(faltversuche, "STILLE_SEKUNDEN", 0.05)
    monkeypatch.setattr(faltversuche, "GESAMT_SEKUNDEN", 1.0)
    provider_setzen(client, _Silent())
    answer = client.post(
        "/api/v1/bild/prompt", json={"prompt": "ein rotes Fahrrad", "familie": "sdxl", "negativ": "blur"}
    )
    assert answer.status_code == 502
    assert len(gerufen) == 2


def test_a_stream_past_the_total_clock_ends_with_502(client: TestClient, monkeypatch):
    monkeypatch.setattr(faltversuche, "GESAMT_SEKUNDEN", 0.1)
    provider = provider_setzen(client, _EndlessClosing())
    answer = client.post("/api/v1/bild/prompt", json={"prompt": "ein rotes Fahrrad", "familie": "sdxl"})
    assert answer.status_code == 502
    assert answer.json()["detail"] == t("bild.prompt_fehlgeschlagen", "de")
    assert provider.closed == 1


def test_a_failing_prompt_takes_its_negative_request_along(client: TestClient, monkeypatch):
    """Prompt and avoid-list run side by side; the one that fails ends the
    other, which would otherwise hold its stream open under its own clock."""

    class _OneSilent(_EndlessClosing):
        async def streamen(self, anfrage):
            if "Fahrrad" in anfrage.nachrichten[-1].content:
                await asyncio.sleep(3600)
                yield Stueck("content", text="never")
                return
            async for stueck in super().streamen(anfrage):
                yield stueck

    monkeypatch.setattr(faltversuche, "STILLE_SEKUNDEN", 0.05)
    # The whole clock too, and not only the silence one: a start that cannot
    # end the silent stream at 0.05 s must not be able to hold this test for
    # the shipped ten minutes — it did exactly that twice in a full run.
    monkeypatch.setattr(faltversuche, "GESAMT_SEKUNDEN", 1.0)
    provider = provider_setzen(client, _OneSilent())
    answer = client.post(
        "/api/v1/bild/prompt", json={"prompt": "ein rotes Fahrrad", "familie": "sdxl", "negativ": "blur"}
    )
    assert answer.status_code == 502
    assert provider.closed == 1


# --- The "off" of the rewrite and the server's refusals ------------------


def _openai_setzen(client: TestClient, provider) -> None:
    """The test endpoint as OpenAI with a model whose "off" goes out as a field."""
    provider_setzen(client, provider)
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.endpunkt = zustand.endpunkt.model_copy(
        update={"parameter_dialect": "openai", "base_url": "https://api.openai.com/v1",
                "modell": "gpt-5.6"}
    )
    zustand.gemeldeter_name = "gpt-5.6"


REFUSAL = '{"error": {"message": "Unsupported value", "param": "reasoning_effort"}}'


def test_a_refused_off_is_written_down_and_asked_once_more_without_it(client: TestClient):
    from app import denkablehnung

    class RefusesOnce(MockProvider):
        def __init__(self):
            super().__init__(haeppchen=["ein rotes Fahrrad, Studiolicht"])
            self.zusaetze: list = []

        async def streamen(self, anfrage):
            self.zusaetze.append(dict(anfrage.zusatz or {}))
            if len(self.zusaetze) == 1:
                raise ProviderFehler("refused", status=400, rohtext=REFUSAL)
            async for stueck in super().streamen(anfrage):
                yield stueck

    server = RefusesOnce()
    _openai_setzen(client, server)
    antwort = client.post("/api/v1/bild/prompt", json={"prompt": "ein rotes Fahrrad", "familie": "sdxl"})
    assert antwort.status_code == 200
    assert len(server.zusaetze) == 2
    assert server.zusaetze[0], "the off must have gone out, or nothing was refused"
    assert server.zusaetze[1] == {}
    einstellungen = client.app.state.repositories.einstellungen
    # Under the list's id for a server without catalogue: the endpoint alone.
    assert denkablehnung.gemerkt(einstellungen, "test") == ["off"]

    merker = _Merker()
    _openai_setzen(client, merker)
    assert client.post("/api/v1/bild/prompt", json={"prompt": "ein rotes Fahrrad", "familie": "sdxl"}).status_code == 200
    assert not merker.gesehen.zusatz


def test_without_a_refusal_the_off_goes_out_as_before(client: TestClient):
    """Silence probe: nothing written down, the switch travels; another
    error writes nothing."""
    from app import denkablehnung

    merker = _Merker()
    _openai_setzen(client, merker)
    assert client.post("/api/v1/bild/prompt", json={"prompt": "ein rotes Fahrrad", "familie": "sdxl"}).status_code == 200
    assert merker.gesehen.zusatz

    class Down(MockProvider):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def streamen(self, anfrage):
            self.calls += 1
            raise ProviderFehler("down", status=400, rohtext="invalid_api_key")
            yield  # pragma: no cover

    down = Down()
    _openai_setzen(client, down)
    assert client.post("/api/v1/bild/prompt", json={"prompt": "ein rotes Fahrrad", "familie": "sdxl"}).status_code == 502
    assert down.calls == 1
    assert denkablehnung.gemerkt(client.app.state.repositories.einstellungen, "test") == []


# --- One instruction per family, the facts in the user's message -------------


def test_every_family_that_draws_from_text_has_exactly_one_instruction():
    zeichnend = {f.name for f in image_families.FAMILIES if "txt2img" in f.tasks}
    assert set(ANWEISUNGEN) == zeichnend
    gelistet = [name for namen in LESER.values() for name in namen]
    assert sorted(gelistet) == sorted(zeichnend)


def _vorbereiten(client: TestClient, **koerper) -> _Merker:
    merker = _Merker()
    provider_setzen(client, merker)
    antwort = client.post("/api/v1/bild/prompt", json={"prompt": "ein Leuchtturm", **koerper})
    assert antwort.status_code == 200, antwort.text
    return merker


def test_an_sdxl_model_writes_with_the_sdxl_instruction_and_its_facts(client: TestClient):
    client.patch("/api/v1/settings/global/bildmodellwerte",
                 json={"wert": {"juggernaut.safetensors": {"trigger": "jgnt", "hinweis": "likes rain"}}})
    merker = _vorbereiten(client, modell="juggernaut.safetensors", familie="sdxl",
                          stil="watercolour", cfg=7)
    system, nutzer = merker.gesehen.nachrichten
    assert system.content == ANWEISUNGEN["sdxl"]
    assert "juggernaut.safetensors (SDXL)" in nutzer.content
    assert "jgnt" in nutzer.content and "likes rain" in nutzer.content
    assert "watercolour" in nutzer.content
    # The request comes last, after every fact.
    assert nutzer.content.endswith("ein Leuchtturm")


def test_krea_2_writes_with_its_own_instruction(client: TestClient):
    merker = _vorbereiten(client, familie="krea2")
    assert merker.gesehen.nachrichten[0].content == ANWEISUNGEN["krea2"]


def test_a_rewritten_instruction_is_used_and_reset_brings_the_works_text_back(client: TestClient):
    client.patch("/api/v1/settings/global/bildaufbereitung",
                 json={"wert": {"anweisungen": {"sdxl": "Only tags."}}})
    assert _vorbereiten(client, familie="sdxl").gesehen.nachrichten[0].content == "Only tags."
    client.patch("/api/v1/settings/global/bildaufbereitung",
                 json={"wert": {"anweisungen": {"sdxl": None}}})
    assert _vorbereiten(client, familie="sdxl").gesehen.nachrichten[0].content == ANWEISUNGEN["sdxl"]


def test_at_cfg_1_no_negative_prompt_comes_back(client: TestClient):
    merker = _Merker()
    provider_setzen(client, merker)
    antwort = client.post("/api/v1/bild/prompt", json={
        "prompt": "ein Leuchtturm", "negativ": "blur", "familie": "flux", "cfg": 1,
    })
    assert antwort.status_code == 200
    assert antwort.json()["negativ"] == ""
    # One request only: the negative was not written over at all.
    assert len(merker.anfragen) == 1
    assert "ignores a negative prompt" in merker.gesehen.nachrichten[1].content


def test_above_cfg_1_the_negative_is_tidied_on_its_own(client: TestClient):
    merker = _Merker()
    provider_setzen(client, merker)
    client.post("/api/v1/bild/prompt", json={
        "prompt": "ein Leuchtturm", "negativ": "Unschärfe", "familie": "sdxl", "cfg": 7,
    })
    anweisungen = [anfrage.nachrichten[0].content for anfrage in merker.anfragen]
    assert ANWEISUNG_NEGATIV in anweisungen


def test_without_a_style_no_style_line_and_the_same_request_is_the_same_message():
    """The silence probe: a fact that is not there is not sent empty."""
    erste = nachricht("a lighthouse", datei="a.gguf", familie="Flux")
    zweite = nachricht("a lighthouse", datei="a.gguf", familie="Flux")
    assert erste == zweite
    assert "style" not in erste
    assert "trigger" not in erste
    assert "negative" not in erste


def test_a_family_that_does_not_draw_from_text_is_refused(client: TestClient):
    merker = _Merker()
    provider_setzen(client, merker)
    antwort = client.post("/api/v1/bild/prompt", json={"prompt": "x", "familie": "wan"})
    assert antwort.status_code == 422
    assert merker.anfragen == []


def test_the_model_server_is_asked_when_it_is_chosen(client: TestClient, monkeypatch):
    gefragt = []
    echt = client.app.state.discovery.aufloesen
    monkeypatch.setattr(
        client.app.state.discovery, "aufloesen",
        lambda kennung: gefragt.append(kennung) or echt("test"),
    )
    provider_setzen(client, _Merker())
    client.patch("/api/v1/settings/global/bildaufbereitung", json={"wert": {"verbesserer": "modell"}})
    client.post("/api/v1/bild/prompt", json={"prompt": "x", "familie": "sdxl"})
    assert gefragt == ["runner"]


def test_a_chosen_cloud_model_is_asked_by_its_id(client: TestClient):
    merker = _Merker()
    provider_setzen(client, merker)
    client.patch("/api/v1/settings/global/bildaufbereitung", json={"wert": {"verbesserer": "kennung:test"}})
    assert client.post("/api/v1/bild/prompt", json={"prompt": "x", "familie": "sdxl"}).status_code == 200
    assert len(merker.anfragen) == 1


def test_a_clean_up_server_that_does_not_run_is_refused(client: TestClient):
    merker = _Merker()
    provider_setzen(client, merker)
    client.patch("/api/v1/settings/global/bildaufbereitung", json={"wert": {"verbesserer": "putzmodell"}})
    antwort = client.post("/api/v1/bild/prompt", json={"prompt": "x", "familie": "sdxl"})
    assert antwort.status_code == 503
    assert merker.anfragen == []


def test_the_check_keeps_only_known_servers_and_families():
    assert bildaufbereitung.wahl_pruefen({"verbesserer": "irgendwas"}) == {}
    assert bildaufbereitung.wahl_pruefen({"anweisungen": {"nope": "x", "sdxl": "y"}}) == {
        "anweisungen": {"sdxl": "y"},
    }


def test_the_block_reads_every_family_with_its_works_text(client: TestClient):
    client.patch("/api/v1/settings/global/bildaufbereitung",
                 json={"wert": {"anweisungen": {"flux": "Mine."}}})
    daten = client.get("/api/v1/bild/prompt/aufbereitung").json()
    assert daten["verbesserer"] == "agent"
    assert daten["anweisungen"]["flux"] == "Mine."
    assert daten["ab_werk"]["flux"] == ANWEISUNGEN["flux"]
    assert daten["anweisungen"]["sdxl"] == ANWEISUNGEN["sdxl"]
    assert set(daten["leser"]) == {"clip", "t5", "llm"}


def test_the_block_offers_the_cloud_models_and_keeps_a_chosen_one():
    """The block's server list: the three servers of this program, every
    model of the list that is not local, and a chosen cloud id that has left
    the list — read from the component's source, the way the house checks
    its other windows' wiring."""
    from pathlib import Path

    quelle = (
        Path(__file__).resolve().parents[1] / "frontend" / "src" / "teile" / "Promptaufbereitung.svelte"
    ).read_text(encoding="utf-8")
    for wert in ("'agent'", "'modell'", "'putzmodell'"):
        assert f"wert: {wert}" in quelle
    assert "m.group !== 'local'" in quelle
    assert "ids.unshift(gewaehlt)" in quelle
