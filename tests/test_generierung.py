"""Streaming proxy end to end.

These are the integration tests for the whole chain: request → proxy →
provider → response → database. The mock stands in for a real model server.
"""

from __future__ import annotations

import asyncio
import dataclasses
import http.server
import json
import logging
import re
import socket
import threading
import time

import pytest

from app import denkschalter, generationen
from app.events import Ereignisse, bus
from app.config import EndpointConfig
from app.generationen import Generierung
from app.providers import ProviderFehler
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Stueck
from app.providers.openai_kompatibel import OpenAIKompatiblerProvider
from tests.conftest import MitNutzung, provider_setzen


def _ereignisse(text: str) -> list[dict]:
    return [
        json.loads(zeile[5:].strip())
        for zeile in text.splitlines()
        if zeile.startswith("data:")
    ]


def _text_aus(ereignisse: list[dict], typ: str) -> str:
    return "".join(e.get("text", "") for e in ereignisse if e["typ"] == typ)


def _ohne_block(text: str) -> str:
    """A user turn as it goes out, without the date block in front of it.

    The block sits on the newest user turn of a request that would otherwise
    carry no date at all (app/grundprompt.environment_block). The
    tests below are about what the block sits IN FRONT OF — the instruction
    of a spoken turn and the words the user said — so they take it off
    first. The block itself is pinned in tests/test_grundprompt.py.

    Refuses instead of handing the text back unchanged: a helper that quietly
    returned what it was given would keep every assertion below green on a
    request whose only date carrier went missing — exactly what these tests
    are here to notice.
    """
    if not text.startswith("<environment_context>"):
        raise AssertionError(f"the date block is missing: {text[:80]!r}")
    return text.split("</environment_context>\n\n", 1)[-1]


def test_antwort_wird_gestreamt_und_gespeichert(client, chat_id):
    provider_setzen(client, MockProvider(haeppchen=["Guten ", "Tag"]))

    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Hallo"},
    )
    assert antwort.status_code == 200
    assert antwort.headers["content-type"].startswith("text/event-stream")

    ereignisse = _ereignisse(antwort.text)
    assert ereignisse[0]["typ"] == "start"
    assert ereignisse[0]["generation_id"]
    assert _text_aus(ereignisse, "content") == "Guten Tag"
    assert ereignisse[-1]["typ"] == "done"
    assert ereignisse[-1]["abgebrochen"] is False

    gespeichert = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]
    assert [n["role"] for n in gespeichert] == ["user", "assistant"]
    assert gespeichert[0]["content"] == "Hallo"
    assert gespeichert[1]["content"] == "Guten Tag"


def test_gedankengang_wird_getrennt_gespeichert(client, chat_id):
    """think tags: the reasoning must not end up in the answer bubble."""
    provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test", reasoning_format="think"),
            haeppchen=["<think>Ich überlege</think>", "Die Antwort"],
        ),
    )

    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Frage"},
    )
    ereignisse = _ereignisse(antwort.text)
    assert _text_aus(ereignisse, "reasoning") == "Ich überlege"
    assert _text_aus(ereignisse, "content") == "Die Antwort"

    nachricht = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"][1]
    assert nachricht["content"] == "Die Antwort"
    assert nachricht["reasoning"] == "Ich überlege"


def test_verlauf_wird_mitgeschickt(client, chat_id):
    provider = provider_setzen(client, MockProvider(haeppchen=["ok"]))
    client.put("/api/v1/system-prompt", json={"text": "Sei knapp."})
    client.post(f"/api/v1/chats/{chat_id}/messages", json={"content": "Erste Frage"})

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Zweite Frage"},
    )

    rollen = [n.role for n in provider.letzte_anfrage.nachrichten]
    inhalte = [n.content for n in provider.letzte_anfrage.nachrichten]
    # The user's prompt is a layer on the shipped one now, so it sits at the
    # end of the single system message instead of being the whole of it —
    # only the paragraph naming the chat's own folder stands behind it.
    before_folder = inhalte[0].split("\n\nThis conversation has a folder of its own")[0]
    assert rollen[0] == "system" and before_folder.endswith("Sei knapp.")
    assert "Erste Frage" in inhalte
    # The newest turn carries the date block in front of what was said
    # (app/grundprompt.environment_block) — the row in the
    # database keeps the words alone.
    assert inhalte[-1].startswith("<environment_context>")
    assert inhalte[-1].endswith("Zweite Frage")


def test_gespraechsanweisung_geht_nur_der_ausgehenden_nachricht_voran(client, chat_id):
    """The stored row keeps exactly what was said — only the copy going to
    the model carries the instruction in front of it."""
    provider = provider_setzen(client, MockProvider(haeppchen=["ok"]))

    client.post(
        "/api/v1/chat/completions",
        json={
            "chat_id": chat_id, "endpoint_id": "test",
            "content": "Wie spät ist es?", "gespraech": True,
        },
    )

    letzte = provider.letzte_anfrage.nachrichten[-1]
    assert letzte.role == "user"
    assert _ohne_block(letzte.content).startswith(
        "This is a spoken conversation."
    )
    assert letzte.content.endswith("Wie spät ist es?")

    gespeichert = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]
    assert gespeichert[0]["content"] == "Wie spät ist es?"


def _gespraech_senden(client, chat_id, *, dialekt, url, modell, gespraech=True, thinking=None):
    """One message to the test endpoint, dressed up as the named provider and
    model — the switch reads dialect, address and model name, nothing else."""
    provider = provider_setzen(client, MockProvider(haeppchen=["ok"]))
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.endpunkt = zustand.endpunkt.model_copy(
        update={"parameter_dialect": dialekt, "base_url": url, "modell": modell}
    )
    zustand.gemeldeter_name = modell
    # A stored thinking length, which a switched-off request must not carry.
    client.put(
        "/api/v1/settings/global/parameter", json={"wert": {"reasoning_budget": 2048}}
    )
    koerper = {"chat_id": chat_id, "endpoint_id": "test", "content": "Wie spät ist es?"}
    if gespraech:
        koerper["gespraech"] = True
    if thinking is not None:
        koerper["thinking"] = thinking
    client.post("/api/v1/chat/completions", json=koerper)
    return provider.letzte_anfrage, zustand


@pytest.mark.parametrize(
    ("dialekt", "url", "modell"),
    [
        ("llama_cpp", "http://127.0.0.1:9/v1", "Qwen3.6-35B-A3B"),
        ("openai", "https://api.openai.com/v1", "gpt-5.6"),
        ("anthropic", "https://api.anthropic.com/v1", "claude-sonnet-5"),
    ],
)
def test_ein_gespraech_geht_ohne_denken_hinaus(client, chat_id, dialekt, url, modell):
    """A spoken conversation does not think — the voice would wait silently
    through the whole trace. Off goes out in exactly the form the switch
    builds for this provider and model, and no thinking length beside it."""
    anfrage, zustand = _gespraech_senden(
        client, chat_id, dialekt=dialekt, url=url, modell=modell
    )
    erwartet, _ = denkschalter.ausschalten(zustand, {}, modell=modell)
    assert erwartet, "this model has a switch; the test would prove nothing without one"
    assert anfrage.zusatz == erwartet
    assert "reasoning_budget" not in anfrage.parameter


def test_ein_gespraech_schaltet_auch_eine_gewaehlte_stufe_aus(client, chat_id):
    """The chat is set to think hard; the spoken turn still goes out off."""
    anfrage, zustand = _gespraech_senden(
        client, chat_id, dialekt="openai", url="https://api.openai.com/v1",
        modell="gpt-5.6", thinking="high",
    )
    assert anfrage.zusatz == denkschalter.ausschalten(zustand, {}, modell="gpt-5.6")[0]


def test_ein_modell_ohne_aus_bekommt_im_gespraech_seine_kleinste_stufe(client, chat_id):
    """A model that cannot be switched off would otherwise think by its own
    default, usually its deepest: it gets the smallest stage it offers."""
    anfrage, zustand = _gespraech_senden(
        client, chat_id, dialekt="anthropic", url="https://api.anthropic.com/v1",
        modell="claude-fable-5-1",
    )
    assert anfrage.zusatz, "the smallest stage must produce fields"
    assert anfrage.zusatz == denkschalter.zusatz("low", zustand, modell="claude-fable-5-1")
    ereignisse = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]
    assert ereignisse[-1]["content"] == "ok"


def test_ein_modell_das_immer_denkt_bekommt_im_gespraech_nichts(client, chat_id):
    """Silence probe: a model with no stage at all gets nothing sent, and
    nothing goes wrong."""
    anfrage, _ = _gespraech_senden(
        client, chat_id, dialekt="openai", url="https://api.openai.com/v1", modell="gpt-4.1",
    )
    assert anfrage.zusatz == {}


def _refusing_once(rohtext: str):
    class RefusesOnce(MockProvider):
        def __init__(self):
            super().__init__(haeppchen=["ok"])
            self.anfragen: list = []

        async def streamen(self, anfrage):
            # A copy: the round sends the same request object again, changed.
            self.anfragen.append(dataclasses.replace(anfrage, zusatz=dict(anfrage.zusatz or {})))
            self.letzte_anfrage = anfrage
            if len(self.anfragen) == 1:
                raise ProviderFehler("refused", status=400, rohtext=rohtext)
            async for stueck in super().streamen(anfrage):
                yield stueck

    return RefusesOnce()


def _als_modell(client, dialekt: str, url: str, modell: str):
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.endpunkt = zustand.endpunkt.model_copy(
        update={"parameter_dialect": dialekt, "base_url": url, "modell": modell}
    )
    zustand.gemeldeter_name = modell
    return zustand


REFUSED_EFFORT = '{"error": {"message": "Unsupported value", "param": "reasoning_effort"}}'


def test_ein_abgelehntes_aus_im_gespraech_geht_einmal_ohne_denkfeld_neu_hinaus(client, chat_id):
    """The spoken turn's "off" is refused: written down, and the same turn
    goes out once more at once without a thinking field — the answer comes.
    The next spoken turn carries the smallest stage still allowed."""
    from app import denkablehnung

    server = provider_setzen(client, _refusing_once(REFUSED_EFFORT))
    zustand = _als_modell(client, "openai", "https://api.openai.com/v1", "gpt-5.6")
    koerper = {"chat_id": chat_id, "endpoint_id": "test", "content": "Hallo", "gespraech": True}
    client.post("/api/v1/chat/completions", json=koerper)

    assert len(server.anfragen) == 2
    assert server.anfragen[0].zusatz, "off must have gone out, or nothing was refused"
    assert server.anfragen[1].zusatz == {}
    ereignisse = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]
    assert ereignisse[-1]["content"] == "ok"
    abgelehnt = denkablehnung.gemerkt(client.app.state.repositories.einstellungen, "test")
    assert abgelehnt == ["off"]

    client.post("/api/v1/chat/completions", json=koerper)
    kleinste = denkschalter.quietest(zustand, modell="gpt-5.6", abgelehnt=abgelehnt)
    assert kleinste not in (None, "off")
    assert server.anfragen[-1].zusatz == denkschalter.zusatz(
        kleinste, zustand, modell="gpt-5.6", abgelehnt=abgelehnt
    )


def test_im_chat_bleibt_ein_abgelehntes_denkfeld_ohne_zweiten_versuch(client, chat_id):
    """Silence probe: a typed message keeps today's way — the refusal is
    written down and the answer ends with it, no second request."""
    server = provider_setzen(client, _refusing_once(REFUSED_EFFORT))
    _als_modell(client, "openai", "https://api.openai.com/v1", "gpt-5.6")
    client.post("/api/v1/chat/completions", json={
        "chat_id": chat_id, "endpoint_id": "test", "content": "Hallo", "thinking": "low",
    })
    assert len(server.anfragen) == 1


def test_a_chat_refusal_is_kept_where_the_model_list_reads_it(client, chat_id):
    """An older chat that names a catalogue server alone (`test`) writes the
    refusal under the id the model list reads (`test:gpt-5.6`), and its next
    turn leaves the refused stage out; another server's list stays empty."""
    from app import denkablehnung

    server = provider_setzen(client, _refusing_once(REFUSED_EFFORT))
    zustand = _als_modell(client, "openai", "https://api.openai.com/v1", "gpt-5.6")
    zustand.modelle = ["gpt-5.6"]
    koerper = {"chat_id": chat_id, "endpoint_id": "test", "content": "Hallo", "thinking": "low"}
    client.post("/api/v1/chat/completions", json=koerper)
    assert server.anfragen[0].zusatz, "the stage must have gone out, or nothing was refused"

    einstellungen = client.app.state.repositories.einstellungen
    assert denkablehnung.gemerkt(einstellungen, "test:gpt-5.6") == ["low"]
    assert denkablehnung.gemerkt(einstellungen, "test") == []
    assert denkablehnung.gemerkt(einstellungen, "anders") == []

    client.post("/api/v1/chat/completions", json=koerper)
    assert server.anfragen[-1].zusatz == {}


UNKNOWN_HOST = "http://127.0.0.1:9/v1"


def test_an_unknown_host_that_refuses_the_default_stage_gets_the_turn_once_more(
    client, chat_id
):
    """A host known only by the plain OpenAI field is sent `medium`, the
    default nobody picked; refused, the same turn goes out once more without
    the field and the answer comes."""
    from app import denkablehnung

    server = provider_setzen(client, _refusing_once(REFUSED_EFFORT))
    _als_modell(client, "openai", UNKNOWN_HOST, "irgendwas")
    client.post("/api/v1/chat/completions", json={
        "chat_id": chat_id, "endpoint_id": "test", "content": "Hallo",
    })

    assert len(server.anfragen) == 2
    assert server.anfragen[0].zusatz == {"reasoning_effort": "medium"}
    assert server.anfragen[1].zusatz == {}
    ereignisse = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]
    assert ereignisse[-1]["content"] == "ok"
    einstellungen = client.app.state.repositories.einstellungen
    assert "medium" in denkablehnung.gemerkt(einstellungen, "test")


class _RefusesEveryStage(MockProvider):
    """Refuses every request that carries a stage field; answers the rest."""

    def __init__(self):
        super().__init__(haeppchen=["ok"])
        self.zusaetze: list = []

    async def streamen(self, anfrage):
        self.zusaetze.append(dict(anfrage.zusatz or {}))
        if anfrage.zusatz:
            raise ProviderFehler("refused", status=400, rohtext=REFUSED_EFFORT)
        async for stueck in super().streamen(anfrage):
            yield stueck


def test_an_unknown_host_that_refused_the_default_gets_no_field_on_the_next_turn(
    client, chat_id
):
    """The refused default marks the whole plain field as refused: the next
    turn sends no stage at all and needs one request, not another repeat."""
    server = provider_setzen(client, _RefusesEveryStage())
    zustand = _als_modell(client, "openai", UNKNOWN_HOST, "irgendwas")
    koerper = {"chat_id": chat_id, "endpoint_id": "test", "content": "Hallo", "thinking": "medium"}
    client.post("/api/v1/chat/completions", json={**koerper, "thinking": None})
    assert server.zusaetze == [{"reasoning_effort": "medium"}, {}]

    # What the window sends next: the profile has no stage left, so none.
    einstellungen = client.app.state.repositories.einstellungen
    from app import denkablehnung

    profil = zustand.denkprofil("irgendwas", denkablehnung.gemerkt(einstellungen, "test"))
    assert profil.stufen == []
    server.zusaetze.clear()
    client.post("/api/v1/chat/completions", json={**koerper, "thinking": None})
    assert server.zusaetze == [{}]
    # A stale window that still sends the old default is not answered with a field either.
    server.zusaetze.clear()
    client.post("/api/v1/chat/completions", json=koerper)
    assert server.zusaetze == [{}]


def test_schweigeprobe_a_catalogue_host_refusing_one_stage_loses_only_that_one(
    client, chat_id
):
    from app import denkablehnung

    server = provider_setzen(client, _refusing_once(REFUSED_EFFORT))
    _als_modell(client, "openai", "https://api.openai.com/v1", "gpt-5.6")
    client.post("/api/v1/chat/completions", json={
        "chat_id": chat_id, "endpoint_id": "test", "content": "Hallo", "thinking": "low",
    })
    assert len(server.anfragen) == 1
    einstellungen = client.app.state.repositories.einstellungen
    assert denkablehnung.gemerkt(einstellungen, "test") == ["low"]


def test_schweigeprobe_an_unknown_host_that_takes_the_stage_gets_one_request(client, chat_id):
    class Counting(MockProvider):
        def __init__(self):
            super().__init__(haeppchen=["ok"])
            self.zusaetze: list = []

        async def streamen(self, anfrage):
            self.zusaetze.append(dict(anfrage.zusatz or {}))
            async for stueck in super().streamen(anfrage):
                yield stueck

    server = provider_setzen(client, Counting())
    _als_modell(client, "openai", UNKNOWN_HOST, "irgendwas")
    client.post("/api/v1/chat/completions", json={
        "chat_id": chat_id, "endpoint_id": "test", "content": "Hallo", "thinking": "medium",
    })
    assert server.zusaetze == [{"reasoning_effort": "medium"}]


def test_schweigeprobe_a_picked_stage_refused_by_an_unknown_host_is_not_sent_again(
    client, chat_id
):
    """A stage somebody picked stays theirs: refused, the turn ends on the
    provider's sentence, without a second request."""
    server = provider_setzen(client, _refusing_once(REFUSED_EFFORT))
    _als_modell(client, "openai", UNKNOWN_HOST, "irgendwas")
    client.put("/api/v1/settings/modell:test/denken", json={"wert": {"stufe": "medium"}})
    client.post("/api/v1/chat/completions", json={
        "chat_id": chat_id, "endpoint_id": "test", "content": "Hallo", "thinking": "medium",
    })
    assert len(server.anfragen) == 1


def test_ein_gespraech_ohne_schalter_lernt_keine_ablehnung(client, chat_id):
    """A spoken turn's stage is the program's, not the user's. Where the
    model has no stage nothing was sent, so a refusal naming thinking
    cannot be blamed on it — or the chat would lose the stage for good."""
    from app import denkablehnung

    rohtext = "thinking: this parameter is not supported by this model"
    assert denkablehnung.ist_ablehnung(400, rohtext)

    class Ablehnend(MockProvider):
        async def streamen(self, anfrage):
            self.letzte_anfrage = anfrage
            raise ProviderFehler("abgelehnt", status=400, rohtext=rohtext)
            yield  # pragma: no cover

    provider_setzen(client, Ablehnend())
    _als_modell(client, "openai", "https://api.openai.com/v1", "gpt-4.1")
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Hallo", "gespraech": True},
    )
    assert denkablehnung.gemerkt(client.app.state.repositories.einstellungen, "test") == []


def test_eine_getippte_nachricht_denkt_wie_der_chat(client, chat_id):
    """The silent case: without the conversation flag the chat's own stage
    goes out, as before."""
    anfrage, zustand = _gespraech_senden(
        client, chat_id, dialekt="openai", url="https://api.openai.com/v1",
        modell="gpt-5.6", gespraech=False, thinking="low",
    )
    assert anfrage.zusatz, "the stage must produce fields, or the test proves nothing"
    assert anfrage.zusatz == denkschalter.zusatz("low", zustand, modell="gpt-5.6")
    assert anfrage.zusatz != denkschalter.ausschalten(zustand, {}, modell="gpt-5.6")[0]


def test_a_message_without_a_stage_gets_the_one_stored_for_the_model(client, chat_id):
    """The window sends no stage until somebody sets one: the service fills
    in the one stored for the model itself, so a stored "off" holds from the
    first message on instead of the model's own default."""
    client.put("/api/v1/settings/modell:test/denken", json={"wert": {"stufe": "off"}})
    anfrage, zustand = _gespraech_senden(
        client, chat_id, dialekt="openai", url="https://api.openai.com/v1",
        modell="gpt-5.6", gespraech=False,
    )
    aus = denkschalter.ausschalten(zustand, {}, modell="gpt-5.6")[0]
    assert aus, "off must produce fields, or the test proves nothing"
    assert anfrage.zusatz == aus


def test_a_message_without_a_stage_and_nothing_stored_gets_the_default(client, chat_id):
    """Nothing stored: the model's own default goes out — what the window
    used to send in that case."""
    from app import denkstufen

    anfrage, zustand = _gespraech_senden(
        client, chat_id, dialekt="openai", url="https://api.openai.com/v1",
        modell="gpt-5.6", gespraech=False,
    )
    standard = denkstufen.standardstufe(zustand.denkprofil("gpt-5.6", []))
    assert standard
    assert anfrage.zusatz == denkschalter.zusatz(standard, zustand, modell="gpt-5.6")


def test_schweigeprobe_a_stage_the_user_picked_beats_the_stored_one(client, chat_id):
    """A stage the window sends is one somebody just set, and it wins."""
    client.put("/api/v1/settings/modell:test/denken", json={"wert": {"stufe": "off"}})
    anfrage, zustand = _gespraech_senden(
        client, chat_id, dialekt="openai", url="https://api.openai.com/v1",
        modell="gpt-5.6", gespraech=False, thinking="low",
    )
    assert anfrage.zusatz == denkschalter.zusatz("low", zustand, modell="gpt-5.6")


def test_schweigeprobe_a_spoken_turn_keeps_its_quietest_stage(client, chat_id):
    """A stored stage does not reach a spoken turn: it still goes out with
    the quietest stage the model allows."""
    client.put("/api/v1/settings/modell:test/denken", json={"wert": {"stufe": "high"}})
    anfrage, zustand = _gespraech_senden(
        client, chat_id, dialekt="openai", url="https://api.openai.com/v1",
        modell="gpt-5.6", gespraech=True,
    )
    assert anfrage.zusatz == denkschalter.ausschalten(zustand, {}, modell="gpt-5.6")[0]


def test_ohne_kennzeichen_keine_gespraechsanweisung(client, chat_id):
    """Schweigeprobe: a typed message carries nothing extra."""
    provider = provider_setzen(client, MockProvider(haeppchen=["ok"]))

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Wie spät ist es?"},
    )

    letzte = provider.letzte_anfrage.nachrichten[-1]
    assert _ohne_block(letzte.content) == "Wie spät ist es?"


def test_eine_unterbrochene_antwort_wird_dem_modell_gesagt(client, chat_id):
    """A turn after the voice was cut off tells the model so, in front of the
    conversation instruction — and only on its way out, never stored."""
    provider = provider_setzen(client, MockProvider(haeppchen=["ok"]))

    client.post(
        "/api/v1/chat/completions",
        json={
            "chat_id": chat_id, "endpoint_id": "test",
            "content": "Nein, anders.", "gespraech": True, "unterbrochen": True,
        },
    )

    letzte = provider.letzte_anfrage.nachrichten[-1]
    assert _ohne_block(letzte.content).startswith(
        "[Note: the user interrupted your previous spoken response before it finished.]\n\n"
        "This is a spoken conversation."
    )
    assert letzte.content.endswith("Nein, anders.")

    gespeichert = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]
    assert gespeichert[0]["content"] == "Nein, anders."


def test_ohne_gespraech_bleibt_die_unterbrechung_stumm(client, chat_id):
    """Schweigeprobe: the flag alone, on a typed message, adds nothing."""
    provider = provider_setzen(client, MockProvider(haeppchen=["ok"]))

    client.post(
        "/api/v1/chat/completions",
        json={
            "chat_id": chat_id, "endpoint_id": "test",
            "content": "Wie spät ist es?", "unterbrochen": True,
        },
    )

    assert _ohne_block(provider.letzte_anfrage.nachrichten[-1].content) == (
        "Wie spät ist es?"
    )


def test_ohne_unterbrechung_kein_hinweis(client, chat_id):
    """Schweigeprobe: an ordinary conversation turn carries no note."""
    provider = provider_setzen(client, MockProvider(haeppchen=["ok"]))

    client.post(
        "/api/v1/chat/completions",
        json={
            "chat_id": chat_id, "endpoint_id": "test",
            "content": "Wie spät ist es?", "gespraech": True,
        },
    )

    assert "interrupted" not in provider.letzte_anfrage.nachrichten[-1].content


def test_ein_geleertes_gespraechsfeld_faellt_auf_den_werkstext_zurueck(client, chat_id):
    client.put("/api/v1/settings/global/diktat", json={"wert": {"gespraechsanweisung": ""}})
    provider = provider_setzen(client, MockProvider(haeppchen=["ok"]))

    client.post(
        "/api/v1/chat/completions",
        json={
            "chat_id": chat_id, "endpoint_id": "test",
            "content": "Wie spät ist es?", "gespraech": True,
        },
    )

    letzte = provider.letzte_anfrage.nachrichten[-1]
    assert _ohne_block(letzte.content).startswith(
        "This is a spoken conversation."
    )


def test_eingestellte_parameter_werden_verwendet(client, chat_id):
    """What is set for the chat reaches the model — through the cascade now."""
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.put(
        f"/api/v1/settings/chat:{chat_id}/parameter",
        json={"wert": {"temperature": 0.42, "top_k": 17}},
    )
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "hi"},
    )
    assert provider.letzte_anfrage.temperature == 0.42
    assert provider.letzte_anfrage.parameter["top_k"] == 17

def test_parameter_der_anfrage_haben_vorrang(client, chat_id):
    provider = provider_setzen(client, MockProvider(haeppchen=["ok"]))
    client.patch(f"/api/v1/chats/{chat_id}", json={"temperature": 0.3})

    client.post(
        "/api/v1/chat/completions",
        json={
            "chat_id": chat_id,
            "endpoint_id": "test",
            "content": "Frage",
            "temperature": 1.1,
        },
    )
    assert provider.letzte_anfrage.temperature == 1.1


def test_modellwahl_bleibt_am_chat_haengen(client, chat_id):
    provider_setzen(client, MockProvider(haeppchen=["ok"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Frage"},
    )
    assert client.get(f"/api/v1/chats/{chat_id}").json()["endpoint_id"] == "test"


def test_ohne_content_wird_auf_dem_verlauf_weitergearbeitet(client, chat_id):
    """Foundation for "regenerate"."""
    provider = provider_setzen(client, MockProvider(haeppchen=["nochmal"]))
    client.post(f"/api/v1/chats/{chat_id}/messages", json={"content": "Frage"})

    client.post(
        "/api/v1/chat/completions", json={"chat_id": chat_id, "endpoint_id": "test"}
    )
    # The shipped instructions always travel, even with no user prompt set —
    # what is left of them still says answer in the user's language, do not
    # write files unasked, do not invent results.
    rollen = [n.role for n in provider.letzte_anfrage.nachrichten]
    inhalte = [n.content for n in provider.letzte_anfrage.nachrichten]
    assert rollen == ["system", "user"]
    assert inhalte[1] == "Frage"


def test_messwerte_landen_in_der_datenbank(client, chat_id):
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["a", "b", "c"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Frage"},
    )
    stats = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"][1]["stats"]
    assert stats["haeppchen"] == 3
    assert stats["endpunkt"] == "test"
    assert stats["abgebrochen"] is False


def test_gesamt_tokens_wird_aus_der_nutzung_normalisiert(client, chat_id):
    """The context display (frontend/src/lib/zustand.svelte.js) reads one
    field regardless of provider — an OpenAI-compatible server only hands
    back a raw `nutzung` block, so this is where it gets unified."""
    provider_setzen(
        client,
        MitNutzung(
            mock_endpunkt("test"),
            nutzung={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        ),
    )
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Frage"},
    )
    stats = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"][1]["stats"]
    assert stats["gesamt_tokens"] == 120


def test_ohne_brauchbare_nutzung_bleibt_gesamt_tokens_weg(client, chat_id):
    """No usage numbers anywhere in the stats chunk means nothing is
    invented — the field is simply absent, not zero."""
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Frage"},
    )
    stats = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"][1]["stats"]
    assert "gesamt_tokens" not in stats


def test_eine_halbe_nutzung_als_text_wird_kein_stand(client, chat_id):
    """A proxy that sends one half as a string: the field is there, so a gate
    asking only "is it there" let it through, the helper dropped the string
    and added up the other half alone — and 20 became the context standing
    of a chat that was at 12,000. Both halves have to be counts, or the
    reading is no standing at all."""
    provider_setzen(
        client,
        MitNutzung(
            mock_endpunkt("test"),
            nutzung={"prompt_tokens": "1500", "completion_tokens": 20},
        ),
    )
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Frage"},
    )
    zeile = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"][1]
    assert zeile["gesamt_tokens"] != 20
    assert zeile["gesamt_tokens"] is None


def test_die_geschichte_wird_je_antwort_einmal_gelesen(client, chat_id):
    """Three consumers used to read the model's history each for
    themselves before the first token: the estimate walked it backwards for
    one integer, the fold read it, the prompt read it again — up to five
    hundred rows parsed three times per answer, and per background wake.
    The integer is one query now, and the fold and the prompt share one
    read."""
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["a"]))
    repositories = client.app.state.repositories
    lesungen = []
    echt = repositories.messages.fuer_das_modell
    repositories.messages.fuer_das_modell = lambda **k: (lesungen.append(k), echt(**k))[1]

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Frage"},
    )
    assert len(lesungen) == 1, lesungen


def test_das_done_ereignis_nennt_den_schlusszustand(client, chat_id):
    """The window writes the closing state into its row from this word —
    the same one the server wrote into the column — instead of nulling the
    field and letting the bubble guess from the metrics blob."""
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["a"]))
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Frage"},
    )
    ereignisse = [
        json.loads(zeile[len("data: "):])
        for zeile in antwort.text.splitlines()
        if zeile.startswith("data: ")
    ]
    done = next(e for e in ereignisse if e.get("typ") == "done")
    assert done["zustand"] == "fertig"
    zeile = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"][1]
    assert zeile["zustand"] == "fertig"


# --- Error cases ---------------------------------------------------------


def test_unbekannter_chat_gibt_404(client):
    provider_setzen(client, MockProvider())
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": "gibtsnicht", "endpoint_id": "test", "content": "x"},
    )
    assert antwort.status_code == 404


def test_nicht_erreichbares_modell_gibt_503(client, chat_id):
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "abwesend", "content": "x"},
        headers={"Accept-Language": "de"},
    )
    assert antwort.status_code == 503
    assert "nicht erreichbar" in antwort.json()["detail"]


def test_unbekannter_endpunkt_gibt_404(client, chat_id):
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "phantasie", "content": "x"},
    )
    assert antwort.status_code == 404


def test_ohne_modellwahl_gibt_400(client, chat_id):
    antwort = client.post(
        "/api/v1/chat/completions", json={"chat_id": chat_id, "content": "x"}
    )
    assert antwort.status_code == 400


def test_fehler_des_anbieters_landet_im_strom_und_nicht_als_absturz(client, chat_id):
    provider_setzen(client, MockProvider(fehler="Modell ist explodiert"))

    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Frage"},
    )
    assert antwort.status_code == 200
    ereignisse = _ereignisse(antwort.text)
    assert any(e["typ"] == "error" for e in ereignisse)
    assert "explodiert" in _text_aus(ereignisse, "error")

    # The bubble is not left behind as a corpse — it is saved and flagged.
    nachricht = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"][1]
    assert nachricht["stats"]["fehler"] == "Modell ist explodiert"


# --- Cancellation --------------------------------------------------------


def test_stop_ohne_angaben_gibt_400(client):
    assert client.post("/api/v1/chat/stop", json={}).status_code == 400


def test_stop_einer_unbekannten_generierung_meldet_null(client):
    antwort = client.post("/api/v1/chat/stop", json={"generation_id": "gibtsnicht"})
    assert antwort.json() == {"abgebrochen": 0}


@pytest.mark.asyncio
async def test_abbruch_stoppt_den_strom_und_rettet_den_text(laufender_server):
    """The actual stop button: set the signal, the stream ends, the text is kept.

    Deliberately runs against a real uvicorn process. The ASGI test transport
    collects the entire response before handing it out — a cancellation in the
    middle of the stream could not be tested that way at all.
    """
    import httpx

    app, basis_adresse = laufender_server
    provider = MockProvider(
        mock_endpunkt("test"), haeppchen=[f"Teil{i} " for i in range(50)], verzoegerung=0.05
    )
    zustand = app.state.discovery.zustaende["test"]
    zustand.provider = provider
    zustand.erreichbar = True

    kopfzeilen = {"X-Sitzungsschluessel": app.state.sitzungsschluessel}
    async with httpx.AsyncClient(base_url=basis_adresse, timeout=30, headers=kopfzeilen) as client:
        chat_id = (await client.post("/api/v1/chats", json={"title": "Abbruch"})).json()["id"]

        gelesen: list[dict] = []
        generation_id = None
        async with client.stream(
            "POST",
            "/api/v1/chat/completions",
            json={"chat_id": chat_id, "endpoint_id": "test", "content": "Los"},
        ) as antwort:
            async for zeile in antwort.aiter_lines():
                if not zeile.startswith("data:"):
                    continue
                ereignis = json.loads(zeile[5:].strip())
                gelesen.append(ereignis)
                if ereignis["typ"] == "start":
                    generation_id = ereignis["generation_id"]
                elif ereignis["typ"] == "content" and len(gelesen) == 4:
                    await client.post(
                        "/api/v1/chat/stop", json={"generation_id": generation_id}
                    )

        assert gelesen[-1]["typ"] == "done"
        assert gelesen[-1]["abgebrochen"] is True
        # Cancelled well before the 50 chunks.
        assert provider.ausgegebene_haeppchen < 50
        # The provider noticed that the stream was closed.
        assert provider.abgebrochen is True

        nachrichten = (await client.get(f"/api/v1/chats/{chat_id}/messages")).json()["nachrichten"]
        assert nachrichten[1]["content"].startswith("Teil0")
        assert nachrichten[1]["content"] != ""
        assert nachrichten[1]["stats"]["abgebrochen"] is True


class _KeepaliveGegenstelle:
    """A stand-in model server, in the shape measured on oMLX
    (a recorded raw stream): one real answer
    piece, then nothing but bare keepalives — ``model: keepalive``, empty
    ``delta.content``, no ``finish_reason`` — for as long as the connection
    stays open. Runs on its own background thread (``mess-abbruchspieler34.py``'s
    own pattern), so its blocking writes never touch the test's event loop.
    """

    def __init__(self) -> None:
        self.verbindung_geschlossen = threading.Event()
        lauscher = socket.socket()
        lauscher.bind(("127.0.0.1", 0))
        self.port = lauscher.getsockname()[1]
        lauscher.close()
        gegenstelle = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def do_POST(self):
                laenge = int(self.headers.get("Content-Length") or 0)
                if laenge:
                    self.rfile.read(laenge)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                try:
                    self._paket({
                        "choices": [{"index": 0, "delta": {
                            "role": "assistant", "content": "Hallo",
                        }}],
                    })
                    while True:
                        time.sleep(0.02)
                        self._paket({
                            "id": "keepalive", "object": "chat.completion.chunk",
                            "created": 0, "model": "keepalive",
                            "choices": [{
                                "index": 0,
                                "delta": {"role": "assistant", "content": ""},
                                "finish_reason": None,
                            }],
                        })
                except OSError:
                    # The peer closed: a broken pipe or a reset on a POSIX
                    # system, "connection aborted" (WinError 10053) on
                    # Windows — every one of them is the closed connection
                    # this test waits for (measured: the aborted one is
                    # neither of the two named before, and the flag stayed
                    # unset).
                    gegenstelle.verbindung_geschlossen.set()

            def _paket(self, inhalt):
                stueck = f"data: {json.dumps(inhalt)}\n\n".encode()
                self.wfile.write(b"%x\r\n%s\r\n" % (len(stueck), stueck))
                self.wfile.flush()

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        # A future regression bringing back the bug this file's test guards
        # against would leave a handler thread writing forever with nothing
        # to ever fail its write — daemon, so it cannot also hang the test
        # process on top of the assertion itself failing.
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def schliessen(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.mark.asyncio
async def test_abbruch_stoppt_auch_einen_strom_aus_reinen_keepalives(laufender_server):
    """A plain ``async for`` only re-checks the stop signal between two
    pieces the provider actually sends — and a keepalive packet (empty
    ``delta.content``) parses to no piece at all
    (``app/providers/openai_kompatibel.py``). Measured on oMLX: the server
    kept sending nothing else for 125 seconds, the stop button did not end
    the answer, and only restarting the service did.

    Runs against the real SSE parser, not the dummy — a dummy has no
    packets to not-parse. Deliberately runs against a real uvicorn process,
    for the same reason as the sibling test above: the ASGI test transport
    collects the entire response before handing it out.
    """
    import httpx

    gegenstelle = _KeepaliveGegenstelle()
    try:
        app, basis_adresse = laufender_server
        zustand = app.state.discovery.zustaende["test"]
        zustand.provider = OpenAIKompatiblerProvider(
            EndpointConfig.model_validate({
                "id": "test", "name": "Test",
                "base_url": f"http://127.0.0.1:{gegenstelle.port}/v1",
                "parameter_dialect": "openai",
            })
        )
        zustand.erreichbar = True

        kopfzeilen = {"X-Sitzungsschluessel": app.state.sitzungsschluessel}
        async with httpx.AsyncClient(
            base_url=basis_adresse, timeout=30, headers=kopfzeilen
        ) as client:
            chat_id = (
                await client.post("/api/v1/chats", json={"title": "Keepalive"})
            ).json()["id"]

            async def lauf() -> list[dict]:
                gelesen: list[dict] = []
                generation_id = None
                async with client.stream(
                    "POST",
                    "/api/v1/chat/completions",
                    json={"chat_id": chat_id, "endpoint_id": "test", "content": "Los"},
                ) as antwort:
                    async for zeile in antwort.aiter_lines():
                        if not zeile.startswith("data:"):
                            continue
                        ereignis = json.loads(zeile[5:].strip())
                        gelesen.append(ereignis)
                        if ereignis["typ"] == "start":
                            generation_id = ereignis["generation_id"]
                        elif ereignis["typ"] == "content" and generation_id:
                            # Only the keepalives follow from here — today's
                            # bug means this stop is never even noticed, and
                            # the wait below is this test's own deadline for
                            # that: unlike the failure, it does not hang.
                            await client.post(
                                "/api/v1/chat/stop",
                                json={"generation_id": generation_id},
                            )
                return gelesen

            gelesen = await asyncio.wait_for(lauf(), timeout=8.0)

        assert gelesen[-1]["typ"] == "done"
        assert gelesen[-1]["abgebrochen"] is True

        frist = time.monotonic() + 5.0
        while (
            time.monotonic() < frist
            and not gegenstelle.verbindung_geschlossen.is_set()
        ):
            await asyncio.sleep(0.02)
        assert gegenstelle.verbindung_geschlossen.is_set()
    finally:
        gegenstelle.schliessen()


async def _fehlerhafte_quelle():
    if False:  # pragma: no cover - makes this an async generator
        yield Stueck("content", "")
    raise ProviderFehler("Verbindung weg")


@pytest.mark.asyncio
async def test_naechstes_stueck_verschluckt_keinen_anbieterfehler():
    """A stop pressed at (or a hair before) the moment the provider's
    stream itself breaks with a real error must not read back as an
    ordinary, user-initiated stop: the error is what happened, and hiding
    it behind ``abgebrochen`` would tell the run's own log nothing was
    ever wrong.
    """
    generierung = Generierung(id="g1", chat_id="c1", endpoint_id="test")
    generierung.signal.set()
    with pytest.raises(ProviderFehler):
        await generierung.naechstes_stueck(_fehlerhafte_quelle())


async def _einzelnes_stueck():
    yield Stueck("content", "Hallo")


@pytest.mark.asyncio
async def test_naechstes_stueck_liest_ein_zufaelliges_ende_nicht_als_abbruch():
    """A stop that happens to land in the very same tick the stream was
    ending on its own anyway must not turn a complete answer into an
    aborted one — unlike a stop that beats a piece which was still on its
    way, which does win that same kind of tie (the sibling assertion in
    ``test_abbruch_stoppt_auch_einen_strom_aus_reinen_keepalives``).
    """
    generierung = Generierung(id="g1", chat_id="c1", endpoint_id="test")
    quelle = _einzelnes_stueck()
    stueck, abbruch_hat_gewonnen = await generierung.naechstes_stueck(quelle)
    assert stueck is not None
    assert abbruch_hat_gewonnen is False

    generierung.signal.set()
    stueck, abbruch_hat_gewonnen = await generierung.naechstes_stueck(quelle)
    assert stueck is None
    assert abbruch_hat_gewonnen is False, "a stream that ended on its own is not an abort"


class _CountingEvent(asyncio.Event):
    """A stop signal that counts how often something starts waiting on it."""

    def __init__(self) -> None:
        super().__init__()
        self.waits = 0

    async def wait(self) -> bool:
        self.waits += 1
        return await super().wait()


def _open_tasks() -> list:
    return [
        task for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]


@pytest.mark.asyncio
async def test_a_long_answer_waits_for_the_stop_in_one_step_and_ends_it_with_the_run():
    """A step per piece was a new task for every piece of an answer: a long
    answer made thousands. One step stands for the whole run, made with its
    first piece and gone when the run ends."""
    run = Generierung(id="g1", chat_id="c1", endpoint_id="test")
    run.signal = _CountingEvent()

    async def many():
        for _ in range(300):
            yield Stueck("content", "x")

    source = many()
    count = 0
    while True:
        piece, stop_won = await run.naechstes_stueck(source)
        if piece is None:
            assert stop_won is False
            break
        count += 1
    assert count == 300
    assert run.signal.waits == 1
    # The wait for the stop is the only thing still open, until the run ends.
    assert len(_open_tasks()) == 1
    run.beenden()
    await asyncio.sleep(0)
    assert _open_tasks() == []


@pytest.mark.asyncio
async def test_a_stop_still_wins_over_a_piece_that_never_comes_after_many_pieces():
    """Silence probe: the one step does what a step per piece did."""
    run = Generierung(id="g1", chat_id="c1", endpoint_id="test")

    async def then_silence():
        for _ in range(5):
            yield Stueck("content", "x")
        await asyncio.sleep(3600)
        yield Stueck("content", "never")

    source = then_silence()
    for _ in range(5):
        piece, _won = await run.naechstes_stueck(source)
        assert piece is not None
    asyncio.get_running_loop().call_later(0.05, run.signal.set)
    piece, stop_won = await asyncio.wait_for(run.naechstes_stueck(source), timeout=5)
    assert piece is None
    assert stop_won is True
    run.beenden()
    await source.aclose()


@pytest.mark.asyncio
async def test_laufende_generierung_steht_bei_den_nachrichten(laufender_server):
    """C2: a window opening the chat cold — a reload, a fresh tab — has no
    memory of a run in progress at all. The messages route is where it finds
    out, mid-stream, from a second, unrelated connection — exactly the
    situation a reload leaves behind.
    """
    import httpx

    app, basis_adresse = laufender_server
    provider = MockProvider(
        mock_endpunkt("test"), haeppchen=[f"Teil{i} " for i in range(20)], verzoegerung=0.05
    )
    zustand = app.state.discovery.zustaende["test"]
    zustand.provider = provider
    zustand.erreichbar = True

    kopfzeilen = {"X-Sitzungsschluessel": app.state.sitzungsschluessel}
    async with httpx.AsyncClient(base_url=basis_adresse, timeout=30, headers=kopfzeilen) as client:
        chat_id = (await client.post("/api/v1/chats", json={"title": "Reload"})).json()["id"]

        generation_id = None
        gesehen = 0
        async with client.stream(
            "POST",
            "/api/v1/chat/completions",
            json={"chat_id": chat_id, "endpoint_id": "test", "content": "Los"},
        ) as antwort:
            async for zeile in antwort.aiter_lines():
                if not zeile.startswith("data:"):
                    continue
                ereignis = json.loads(zeile[5:].strip())
                if ereignis["typ"] == "start":
                    generation_id = ereignis["generation_id"]
                elif ereignis["typ"] == "content":
                    gesehen += 1
                    if gesehen == 4:
                        # A second connection, exactly what a reloaded window
                        # would open — not the one holding the run.
                        seite = (
                            await client.get(f"/api/v1/chats/{chat_id}/messages")
                        ).json()
                        assert seite["laufend"] == {
                            "generation_id": generation_id,
                            # WHICH row is being written. Without this a
                            # cold window had to deduce it — last row,
                            # assistant, no cancel mark — and anything the
                            # chat gained during the run matched that
                            # description too.
                            "message_id": seite["nachrichten"][1]["id"],
                        }
                        # And the row says for itself that it is live, so
                        # nothing has to go by position at all.
                        assert seite["nachrichten"][1]["zustand"] == "laeuft"
                        assert seite["nachrichten"][1]["art"] == "nachricht"
                        # The message is NOT the empty placeholder any more.
                        # It used to be — this line read `== ""` — back when
                        # the run wrote its answer only once, at the end, and
                        # a service that died in the middle left the row
                        # blank: on 31.08. an app swap cost a whole tool
                        # block and the answer text with it. The run now
                        # writes the state so far along the way
                        # (api/v1/generierung.py), so what stands here is
                        # whatever the last of those writes carried: a PREFIX
                        # of the answer, never empty, never the whole of it
                        # while the stream is still running.
                        teilstand = seite["nachrichten"][1]["content"]
                        assert teilstand, "the running placeholder is empty"
                        assert "".join(
                            f"Teil{i} " for i in range(20)
                        ).startswith(teilstand)

        # Finished by now — nothing left to reattach to.
        fertig = (await client.get(f"/api/v1/chats/{chat_id}/messages")).json()
        assert fertig["laufend"] is None


@pytest.mark.asyncio
async def test_wiederangehaengter_strom_traegt_den_ursprungszeitpunkt(laufender_server):
    """A reattach (``GET /api/v1/chat/stream/{generation_id}``) replays the
    whole history at once — every event must carry the moment it was first
    reported, not the moment of the replay. Otherwise a clock built on top
    of it (the frontend's running-time header) starts counting from the
    reattach instead of from when the piece actually happened.
    """
    import httpx

    app, basis_adresse = laufender_server
    provider = MockProvider(
        mock_endpunkt("test"), haeppchen=[f"Teil{i} " for i in range(20)], verzoegerung=0.05
    )
    zustand = app.state.discovery.zustaende["test"]
    zustand.provider = provider
    zustand.erreichbar = True

    kopfzeilen = {"X-Sitzungsschluessel": app.state.sitzungsschluessel}
    async with httpx.AsyncClient(base_url=basis_adresse, timeout=30, headers=kopfzeilen) as client:
        chat_id = (await client.post("/api/v1/chats", json={"title": "Reattach"})).json()["id"]

        generation_id = None
        erste_inhalt = None
        async with client.stream(
            "POST",
            "/api/v1/chat/completions",
            json={"chat_id": chat_id, "endpoint_id": "test", "content": "Los"},
        ) as antwort:
            async for zeile in antwort.aiter_lines():
                if not zeile.startswith("data:"):
                    continue
                ereignis = json.loads(zeile[5:].strip())
                if ereignis["typ"] == "start":
                    generation_id = ereignis["generation_id"]
                elif ereignis["typ"] == "content" and erste_inhalt is None:
                    erste_inhalt = ereignis
                    break  # leave the rest of the round running unattended

        assert generation_id is not None
        assert erste_inhalt is not None
        ursprungszeitpunkt = erste_inhalt["zeitpunkt_ms"]
        assert ursprungszeitpunkt is not None

        # A real pause — long enough that a timestamp taken at replay time
        # would visibly differ from the one taken when the piece first ran.
        await asyncio.sleep(0.5)

        wiedergespielt = None
        async with client.stream(
            "GET", f"/api/v1/chat/stream/{generation_id}"
        ) as antwort:
            async for zeile in antwort.aiter_lines():
                if not zeile.startswith("data:"):
                    continue
                ereignis = json.loads(zeile[5:].strip())
                if ereignis["typ"] == "content":
                    wiedergespielt = ereignis
                    break

        assert wiedergespielt is not None
        assert wiedergespielt["zeitpunkt_ms"] == ursprungszeitpunkt

        await client.post("/api/v1/chat/stop", json={"generation_id": generation_id})


@pytest.mark.asyncio
async def test_lebender_strom_traegt_dieselben_felder_wie_zuvor(laufender_server):
    """Silence probe: a live (non-replayed) read must still deliver the same
    events with the same fields in the same order as before — only with
    ``zeitpunkt_ms`` added. The added field alone must not shift, rename or
    drop anything the frontend already reads.
    """
    import httpx

    app, basis_adresse = laufender_server
    provider = MockProvider(mock_endpunkt("test"), haeppchen=["Guten ", "Tag"])
    zustand = app.state.discovery.zustaende["test"]
    zustand.provider = provider
    zustand.erreichbar = True

    kopfzeilen = {"X-Sitzungsschluessel": app.state.sitzungsschluessel}
    async with httpx.AsyncClient(base_url=basis_adresse, timeout=30, headers=kopfzeilen) as client:
        chat_id = (await client.post("/api/v1/chats", json={"title": "Live"})).json()["id"]

        gelesen: list[dict] = []
        async with client.stream(
            "POST",
            "/api/v1/chat/completions",
            json={"chat_id": chat_id, "endpoint_id": "test", "content": "Los"},
        ) as antwort:
            async for zeile in antwort.aiter_lines():
                if not zeile.startswith("data:"):
                    continue
                gelesen.append(json.loads(zeile[5:].strip()))

    typen = [e["typ"] for e in gelesen]
    assert typen == ["start", "content", "content", "stats", "done"]
    assert _text_aus(gelesen, "content") == "Guten Tag"
    for ereignis in gelesen:
        assert isinstance(ereignis["zeitpunkt_ms"], int)


@pytest.mark.asyncio
async def test_abbruch_ueber_chat_id_trifft_alle_laufenden(config):
    from app.generationen import Generierungsverwaltung

    verwaltung = Generierungsverwaltung()
    a = verwaltung.anmelden(chat_id="chat1", endpoint_id="test")
    b = verwaltung.anmelden(chat_id="chat1", endpoint_id="test")
    c = verwaltung.anmelden(chat_id="chat2", endpoint_id="test")

    assert verwaltung.alle_im_chat_abbrechen("chat1") == 2
    assert a.soll_abbrechen and b.soll_abbrechen
    assert not c.soll_abbrechen


@pytest.mark.asyncio
async def test_abgemeldete_generierung_laesst_sich_nicht_mehr_abbrechen():
    from app.generationen import Generierungsverwaltung

    verwaltung = Generierungsverwaltung()
    generierung = verwaltung.anmelden(chat_id="c", endpoint_id="e")
    verwaltung.abmelden(generierung.id)
    assert verwaltung.abbrechen(generierung.id) is False


# --- Metrics across tool rounds ------------------------------------------


def test_messwerte_summieren_token_und_erzeugungszeit_getrennt():
    """Two rounds with a tool run in between.

    The wait between the rounds — the tool plus processing the grown
    prompt — belongs in the total duration, but not in the speed.
    """
    from app.api.v1.generierung import _messwerte_mergen

    erste = {
        "dauer_sekunden": 4.0, "erzeugte_tokens": 30, "erzeugungs_sekunden": 1.0,
        "haeppchen": 30, "tempo_quelle": "server", "erstes_token_nach_sekunden": 3.0,
    }
    zweite = {
        "dauer_sekunden": 12.0, "erzeugte_tokens": 90, "erzeugungs_sekunden": 3.0,
        "haeppchen": 90, "tempo_quelle": "server", "erstes_token_nach_sekunden": 9.0,
    }
    zusammen = _messwerte_mergen(erste, zweite)

    assert zusammen["dauer_sekunden"] == 16.0        # honest: that's how long it took
    assert zusammen["erzeugungs_sekunden"] == 4.0
    assert zusammen["tokens_pro_sekunde"] == 30.0    # 120 tokens / 4 s
    assert zusammen["erstes_token_nach_sekunden"] == 3.0  # from the first round


def test_eine_ungenaue_runde_macht_die_ganze_zahl_ungenau():
    """The weaker of the two tiers names the sum.

    Stated with `geschaetzt` until the chunk tier stopped contributing
    tokens at all: a round that puts nothing into the sum has
    no say in what the sum counts, so the pair that does the naming is now
    `server` against `gemessen` — the rule itself is unchanged.
    """
    from app.api.v1.generierung import _messwerte_mergen

    zusammen = _messwerte_mergen(
        {"erzeugte_tokens": 10, "erzeugungs_sekunden": 1.0, "tempo_quelle": "server"},
        {"erzeugte_tokens": 10, "erzeugungs_sekunden": 1.0, "tempo_quelle": "gemessen"},
    )
    assert zusammen["tempo_quelle"] == "gemessen"


def test_erste_runde_wird_unveraendert_uebernommen():
    from app.api.v1.generierung import _messwerte_mergen

    neu = {"dauer_sekunden": 2.0, "tokens_pro_sekunde": 12.5}
    assert _messwerte_mergen({}, neu) == neu


# --- What the sum must not lift off again ---------------------------------
#
# Every round is judged for itself before it gets here, and a round that
# was judged unmeasurable must not become measurable by being added to
# other unmeasurable rounds. Twice this went wrong in the same expression,
# and both times the number that came back was the very one the floors were
# written for.


def _runde(tokens, sekunden, quelle="geschaetzt"):
    """One round of a tool answer, as the provider reports it."""
    return {
        "dauer_sekunden": 1.2, "haeppchen": tokens, "erzeugte_tokens": tokens,
        "erzeugungs_sekunden": sekunden, "tokens_pro_sekunde": None,
        "tempo_quelle": quelle, "erstes_token_nach_sekunden": 1.0,
    }


def test_drei_unmessbare_runden_ergeben_keine_messung():
    """The token floor let three rounds of one token through.

    Two rounds of one token each stayed below a count of three and were
    caught; the third lifted the count over the floor and the same 1000
    tok/s came back — three tokens over three milliseconds. What is wrong
    with that reading is the divisor, and no count of tokens sees it.
    """
    from app.api.v1.generierung import _messwerte_mergen

    zusammen = _messwerte_mergen(
        _messwerte_mergen(_runde(1, 0.001, "gemessen"), _runde(1, 0.001, "gemessen")),
        _runde(1, 0.001, "gemessen"),
    )
    assert zusammen["erzeugte_tokens"] == 3
    assert zusammen["erzeugungs_sekunden"] == 0.003
    assert zusammen["tokens_pro_sekunde"] is None  # 1000.0 before


def test_tokens_ohne_zeit_gehen_nicht_in_den_zaehler():
    """A round whose generation time rounded away keeps its count.

    The count is true and the window shows it. What it has no business
    doing is joining the numerator of the speed while its time is missing
    from the denominator: three rounds of one token, two of them without a
    measured time, divided three by the 0.002 s of the third and reported
    1500 tok/s — though every one of the three had reported no speed at all.
    """
    from app.api.v1.generierung import _messwerte_mergen

    zusammen = _messwerte_mergen(
        _messwerte_mergen(_runde(1, None, "gemessen"), _runde(1, None, "gemessen")),
        _runde(1, 0.002, "gemessen"),
    )
    assert zusammen["erzeugte_tokens"] == 3        # every token still counted
    assert zusammen["tempo_tokens"] == 1           # only one of them measured
    assert zusammen["tokens_pro_sekunde"] is None  # 1500.0 before


def test_die_paarung_gilt_auch_weit_ueber_den_grenzen():
    """And it is not the floors doing the work here.

    Two rounds of forty tokens whose time rounded away, beside one measured
    round of forty over two seconds: the count clears every floor and the
    time is long. The speed of what was measured is 20 per second; adding
    the unmeasured tokens to the numerator made it 60.
    """
    from app.api.v1.generierung import _messwerte_mergen

    zusammen = _messwerte_mergen(
        _messwerte_mergen(_runde(40, None, "gemessen"), _runde(40, None, "gemessen")),
        _runde(40, 2.0, "gemessen"),
    )
    assert zusammen["erzeugte_tokens"] == 120
    assert zusammen["erzeugungs_sekunden"] == 2.0
    assert zusammen["tokens_pro_sekunde"] == 20.0  # 60.0 before


def test_die_gemessene_zeit_des_servers_bleibt_auch_in_der_summe_stehen():
    """The floors are about OUR arithmetic and stand aside for a server.

    Two rounds the server itself timed, two tokens in five milliseconds
    each: under both floors, and still a fact — it counted at the source.
    """
    from app.api.v1.generierung import _messwerte_mergen

    zusammen = _messwerte_mergen(_runde(2, 0.005, "server"), _runde(2, 0.005, "server"))
    assert zusammen["tokens_pro_sekunde"] == 400.0


class _EinWerkzeug:
    """A registry offering exactly one tool, enough to see it travel."""

    def als_openai_werkzeuge(self, nur=None, shell_zeitgrenze=None, bild_fenster=None, **_options):
        return [{"type": "function", "function": {"name": "bash", "parameters": {}}}]

    def braucht_bestaetigung(self, name, argumente=None, ordner=None):
        return False

    def server_von(self, name):
        return "shell"


def _mit_werkzeugen(client):
    client.app.state.werkzeuge = _EinWerkzeug()
    client.app.state.config.features.mcp = True
    return provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Gut."]))


def test_ohne_die_faehigkeit_reist_kein_werkzeug_mit(client, chat_id):
    """The word decides, and while it is missing the request carries nothing.

    A server that has no /props to sniff resolves to "no", so no tool ever
    reaches the model — which is what leaves a model that knows the format
    anyway writing its call into the chat as plain text.
    """
    provider = _mit_werkzeugen(client)
    client.put("/api/v1/providers/test/capabilities", json={"tool_calls": False})

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Hallo"},
    )
    assert not provider.letzte_anfrage.werkzeuge


def test_mit_der_faehigkeit_reist_das_werkzeug_mit(client, chat_id):
    """And with the word set the very same request carries the tool."""
    provider = _mit_werkzeugen(client)
    client.put("/api/v1/providers/test/capabilities", json={"tool_calls": True})

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Hallo"},
    )
    namen = [w["function"]["name"] for w in provider.letzte_anfrage.werkzeuge]
    assert namen == ["bash"]


# --- The id the interface names for its own question ----------------------


def test_eine_mitgegebene_kennung_wird_die_id_der_gespeicherten_frage(client, chat_id):
    """The interface's own bubble and the row the service stores end up
    sharing one id: a reload racing the request then finds its own question
    already among the rows the service just named, instead of a second copy
    under a different id.
    """
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Hallo"]))
    client.post(
        "/api/v1/chat/completions",
        json={
            "chat_id": chat_id, "endpoint_id": "test", "content": "Hi",
            "nachricht_id": "eigen-abc1234",
        },
    )
    repositories = client.app.state.repositories
    frage = next(
        z for z in repositories.messages.auflisten(chat_id=chat_id) if z.role == "user"
    )
    assert frage.id == "eigen-abc1234"
    assert frage.content == "Hi"


def test_ohne_kennung_vergibt_der_dienst_wie_bisher_eine_eigene_id(client, chat_id):
    """Schweigeprobe: an older interface, or the CLI, sends no id at all —
    the service keeps assigning one itself, exactly as before this field
    existed."""
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Hallo"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Hi"},
    )
    repositories = client.app.state.repositories
    frage = next(
        z for z in repositories.messages.auflisten(chat_id=chat_id) if z.role == "user"
    )
    assert re.fullmatch(r"[0-9a-f]{32}", frage.id)


def test_eine_bereits_vergebene_kennung_bricht_die_anfrage_nicht(client, chat_id):
    """A retry that repeats the same id — a dropped response the interface
    resends, two ids that happen to collide — must not turn into a broken
    request: the row still gets saved, only under a fresh id of its own."""
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Hallo"]))
    erste = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "eins", "nachricht_id": "eigen-x"},
    )
    assert erste.status_code == 200
    zweite = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "zwei", "nachricht_id": "eigen-x"},
    )
    assert zweite.status_code == 200
    repositories = client.app.state.repositories
    fragen = [z for z in repositories.messages.auflisten(chat_id=chat_id) if z.role == "user"]
    assert [f.content for f in fragen] == ["eins", "zwei"]
    assert fragen[0].id == "eigen-x"
    assert fragen[1].id != "eigen-x"


def test_eine_luecke_foermige_kennung_wird_nicht_uebernommen(client, chat_id):
    """`_luecke` (app/db/repositories/messages.py) relies on the shape
    `luecke-<chat id>` never belonging to a real, stored row — a client
    naming that exact id must not be allowed to claim it."""
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Hallo"]))
    antwort = client.post(
        "/api/v1/chat/completions",
        json={
            "chat_id": chat_id, "endpoint_id": "test", "content": "Hi",
            "nachricht_id": f"luecke-{chat_id}",
        },
    )
    assert antwort.status_code == 200
    repositories = client.app.state.repositories
    frage = next(
        z for z in repositories.messages.auflisten(chat_id=chat_id) if z.role == "user"
    )
    assert frage.id != f"luecke-{chat_id}"


# --- The route and the function behind it ---------------------------------


async def test_eine_antwort_laesst_sich_ohne_anfrage_anstossen(config):
    """``antwort_anstossen`` is what makes a run startable from inside the
    service — the same split the job path has (``auftrag_anstossen`` beside
    ``auftrag_starten``).

    Going through HTTP to our own service is no way out and never was: such
    a run is bound to that connection, and ``_waechter`` cancels it the
    moment the connection goes. Here nothing is bound, and the answer still
    lands in the chat.
    """
    from app.api.v1.generierung import antwort_anstossen
    from app.api.v1.schemas import GenerierungAnfrage
    from app.main import app_erstellen

    app = app_erstellen(config)
    async with app.router.lifespan_context(app):
        zustand = app.state.discovery.zustaende["test"]
        zustand.provider = MockProvider(haeppchen=["Ohne ", "Anfrage"])
        zustand.erreichbar = True
        repositories = app.state.repositories
        chat = repositories.chats.erstellen(
            user_id="standard", title="t", endpoint_id="test"
        )

        lauf = await antwort_anstossen(
            app=app,
            daten=GenerierungAnfrage(chat_id=chat.id, content="Hallo"),
            repositories=repositories,
            discovery=app.state.discovery,
            generierungen=app.state.generierungen,
            user_id="standard",
            sprache="de",
        )
        await lauf.fertig.wait()

        letzte = repositories.messages.auflisten(chat_id=chat.id)[-1]
        assert letzte.content == "Ohne Anfrage"
        assert letzte.zustand == "fertig"


# --- The connection watchdog ----------------------------------------------


async def test_der_verbindungswaechter_wird_gehalten_bis_der_lauf_endet():
    """The watchdog has a reference for exactly as long as it is watching.

    Said plainly, because it is worth saying: this does not provoke a
    collection — a task cannot be made to vanish on cue. What it checks is
    the thing that prevents one, that the reference is there while the run
    is going and released when the run ends, which is what the loop's own
    weak reference does not give (app/events.py).

    The watchdog is what notices a browser that has gone while the run sits
    on a confirmation prompt writing nothing, so a run whose watchdog
    disappeared is a chat that keeps generating for a window nobody has open.
    """
    from app.api.v1.generierung import _wachen, _zusehen

    class OffeneVerbindung:
        """Just enough request for the watchdog: the browser is still there."""

        async def is_disconnected(self) -> bool:
            return False

    vorher = set(_wachen)
    lauf = Generierung(id="g-1", chat_id="c-1", endpoint_id="test")
    lauf.melden("erste Zeile")

    # The generator body — and with it the watchdog — starts on the first
    # step, not when `_zusehen` is called.
    strom = _zusehen(lauf, OffeneVerbindung())
    assert await strom.__anext__() == "erste Zeile"
    neu = _wachen - vorher
    assert len(neu) == 1, "the connection watchdog is not held"

    lauf.beenden()
    with pytest.raises(StopAsyncIteration):
        await strom.__anext__()
    # One tick of VERBINDUNG_PRUEFTAKT is what it takes the watchdog to see
    # that the run is over and end by itself.
    for _ in range(40):
        if not (neu & _wachen):
            break
        await asyncio.sleep(0.05)
    assert not (neu & _wachen), "the connection watchdog was never let go of"
    task = next(iter(neu))
    assert task.done() and not task.cancelled() and task.exception() is None


async def test_a_future_that_had_already_failed_gives_its_error_back(caplog):
    """The cleanup reads a future that had already settled instead of
    passing it over: its error is usually the reason the cleanup runs at
    all, and one nobody ever awaited would surface nowhere but the event
    loop's own report. It gives the error back rather than logging it — the
    caller knows whether it had a sibling."""
    schleife = asyncio.get_running_loop()
    fertig = schleife.create_future()
    fertig.set_exception(ProviderFehler("kaputt"))
    assert isinstance(await generationen.discard(fertig), ProviderFehler)


async def test_a_clean_future_gives_nothing_back(caplog):
    """Silence probe: one that ended without an error gives back nothing,
    and neither does one that was only cancelled."""
    schleife = asyncio.get_running_loop()
    gut = schleife.create_future()
    gut.set_result(True)
    abgebrochen = schleife.create_future()
    abgebrochen.cancel()
    assert await generationen.discard(gut) is None
    assert await generationen.discard(abgebrochen) is None


class _ModelNamingServer:
    """A stand-in model server that names the model that answered, in the one
    field the OpenAI answer object carries for it (``model``).

    ``model=None`` leaves that field out of every packet behind the opening
    one — a server that names nothing, the way some proxies answer. An empty
    string names one that is no name at all and must not become one.

    The opening packet is sent in the shape MEASURED on oMLX: a keepalive
    whose own ``model`` is the literal guard word, with an empty delta and
    no end (a recorded raw stream). A reader that
    keeps the first name it sees reads "keepalive" there and never the model
    that answered. Runs on a background thread like the keepalive stand-in
    above, so its blocking writes never touch the test's event loop.
    """

    def __init__(self, model: str | None) -> None:
        lauscher = socket.socket()
        lauscher.bind(("127.0.0.1", 0))
        self.port = lauscher.getsockname()[1]
        lauscher.close()

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def do_POST(self):
                laenge = int(self.headers.get("Content-Length") or 0)
                if laenge:
                    self.rfile.read(laenge)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                # The measured opening of an oMLX stream: a keepalive that
                # names the guard word itself as its `model`, with an empty
                # delta and no end. The real name stands only behind it
                # (a recorded raw stream) — sent
                # through `_roh`, so the name of this stand-in never lands in
                # the very packet that must not carry it.
                self._roh(
                    {
                        "id": "keepalive",
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": "keepalive",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"role": "assistant", "content": ""},
                                "finish_reason": None,
                            }
                        ],
                    }
                )
                for inhalt in ("Hallo", " Welt"):
                    self._paket(
                        {
                            "id": "1",
                            "object": "chat.completion.chunk",
                            "created": 1789522698,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": inhalt},
                                    "finish_reason": None,
                                }
                            ],
                        }
                    )
                self._paket(
                    {
                        "id": "1",
                        "object": "chat.completion.chunk",
                        "created": 1789522698,
                        "choices": [
                            {"index": 0, "delta": {}, "finish_reason": "stop"}
                        ],
                    }
                )
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()

            def _paket(self, inhalt: dict) -> None:
                if model is not None:
                    inhalt["model"] = model
                self._roh(inhalt)

            def _roh(self, inhalt: dict) -> None:
                stueck = f"data: {json.dumps(inhalt)}\n\n".encode()
                self.wfile.write(b"%x\r\n%s\r\n" % (len(stueck), stueck))
                self.wfile.flush()

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


async def _one_answer_against(
    server: _ModelNamingServer,
    running_server,
    asked_model: str | None,
    events: list[dict],
) -> None:
    """One plain answer against the stand-in server, and the events the
    service announced about it (collected into ``events``).

    The endpoint is the real ``test`` endpoint with its provider swapped for
    the one that speaks to the stand-in (the pattern the keepalive test uses);
    ``asked_model`` is what the request names, the way the endpoint's own
    model name reaches it (app/discovery.py, ``gemeldeter_name``).
    """
    import httpx

    app, base_url = running_server
    endpoint = EndpointConfig.model_validate({
        "id": "test",
        "name": "Test",
        "base_url": f"http://127.0.0.1:{server.port}/v1",
        "parameter_dialect": "openai",
        **({"modell": asked_model} if asked_model else {}),
    })
    zustand = app.state.discovery.zustaende["test"]
    zustand.provider = OpenAIKompatiblerProvider(endpoint)
    zustand.erreichbar = True
    # The name the endpoint answers to, the way the probe would have found it
    # (app/discovery.py, ``gemeldeter_name``): the stand-in server offers no
    # model list, so it is put there by hand. It is what the request names.
    zustand.gemeldeter_name = asked_model

    async def collect(**daten):
        events.append(daten)

    read: list[dict] = []
    bus.abonnieren(Ereignisse.ANTWORT_FERTIG, collect)
    try:
        headers = {"X-Sitzungsschluessel": app.state.sitzungsschluessel}
        async with httpx.AsyncClient(
            base_url=base_url, timeout=30, headers=headers
        ) as client:
            chat_id = (
                await client.post("/api/v1/chats", json={"title": "Model"})
            ).json()["id"]
            async with client.stream(
                "POST",
                "/api/v1/chat/completions",
                json={"chat_id": chat_id, "endpoint_id": "test", "content": "Los"},
            ) as antwort:
                async for zeile in antwort.aiter_lines():
                    if zeile.startswith("data:"):
                        read.append(json.loads(zeile[5:].strip()))
    finally:
        # In a `finally`: a failure above must not leave a collector on the
        # process-wide bus appending every later answer's payload to a list
        # that nobody will ever read again.
        bus.abbestellen(Ereignisse.ANTWORT_FERTIG, collect)
    assert read[-1]["typ"] == "done", read[-1]
    assert _text_aus(read, "content") == "Hallo Welt"


def _protocol_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("Answer from")]


@pytest.mark.parametrize(
    ("reported", "asked", "expected"),
    [
        # The server's own name wins over the one the endpoint answers to.
        ("MLX Assistant", "Qwen3-1.7B", "MLX Assistant"),
        # Silence probe: it names none, so the requested one stands there.
        (None, "Qwen3-1.7B", "Qwen3-1.7B"),
        # An empty name is no name — the requested one stands there instead,
        # and so is a name out of nothing but blanks.
        ("", "Qwen3-1.7B", "Qwen3-1.7B"),
        ("   ", "Qwen3-1.7B", "Qwen3-1.7B"),
        # Nobody names one: the line stays exactly what it always was,
        # rather than gaining a pair of empty brackets.
        (None, None, None),
        # A locally started mlx or llama.cpp reports its model as the folder
        # it was loaded from, and that folder carries the operator's name —
        # the line gets the display name, never the path (app/pfade.py).
        ("/Users/someone/models/Qwen3.6-27B", None, "Qwen3.6-27B"),
        # A name carrying a line break would forge a line in a text-format
        # log, where the value goes in verbatim (app/main.py); its whitespace
        # runs become single spaces.
        ("MLX\nAssistant", None, "MLX Assistant"),
    ],
)
async def test_the_protocol_names_the_model(laufender_server, caplog, reported, asked, expected):
    """A proof asked for one particular model has to show which one ran, and
    the endpoint's id only names the SERVER. The answer object carries the
    model that answered it; the protocol line takes the name from there, and
    the event beside it carries the same one
    (app/providers/openai_kompatibel.py, app/main.py)."""
    server = _ModelNamingServer(reported)
    events: list[dict] = []
    try:
        with caplog.at_level(logging.INFO, logger="app.main"):
            await _one_answer_against(server, laufender_server, asked, events)
    finally:
        server.close()

    assert [e.get("model") for e in events] == [expected]
    lines = _protocol_lines(caplog)
    assert len(lines) == 1, lines
    if expected is None:
        assert lines[0].startswith("Answer from test: ")
    else:
        assert lines[0].startswith(f"Answer from test ({expected}):")


def test_the_retry_without_a_stage_keeps_the_split_field(client, chat_id):
    """A spoken turn whose "off" is refused goes out once more without the
    switch — and still with the field M3's route always gets, which only
    says where the thinking is delivered."""
    server = provider_setzen(
        client, _refusing_once('{"error": {"message": "bad", "param": "thinking.type"}}')
    )
    _als_modell(client, "openai", "https://api.minimax.io/v1", "MiniMax-M3")
    client.post("/api/v1/chat/completions", json={
        "chat_id": chat_id, "endpoint_id": "test", "content": "Hello", "gespraech": True,
    })
    assert len(server.anfragen) == 2
    assert server.anfragen[0].zusatz == {
        "thinking": {"type": "disabled"}, "reasoning_split": True
    }
    assert server.anfragen[1].zusatz == {"reasoning_split": True}


def test_a_refused_substitute_stage_marks_the_field_refused(client, chat_id):
    """Stages low, medium, high on a host known only by the plain field;
    medium, stored, is refused and only medium joins the list. The next
    turn falls back to low, the program's choice and not a pick: refused
    too, the turn goes out once more without the field, and the whole field
    counts as refused."""
    from app import denkablehnung

    server = provider_setzen(client, _RefusesEveryStage())
    state = _als_modell(client, "openai", UNKNOWN_HOST, "some-model")
    client.put("/api/v1/settings/modell:test/denken", json={"wert": {"stufe": "medium"}})
    body = {"chat_id": chat_id, "endpoint_id": "test", "content": "Hello"}
    client.post("/api/v1/chat/completions", json={**body, "thinking": "medium"})
    client.post("/api/v1/chat/completions", json=body)

    assert server.zusaetze == [
        {"reasoning_effort": "medium"},
        {"reasoning_effort": "low"},
        {},
    ]
    settings = client.app.state.repositories.einstellungen
    refused = denkablehnung.gemerkt(settings, "test")
    assert {"high", "low", "medium"} <= set(refused)
    assert state.denkprofil("some-model", refused).stufen == []


def test_a_local_server_refusing_the_off_field_gets_the_turn_without_it(client, chat_id):
    """A spoken turn on a llama.cpp server goes out with thinking off as
    `reasoning_effort: "none"`; a server that refuses the field gets the
    same turn once more without it, and the answer comes."""
    server = provider_setzen(client, _refusing_once(REFUSED_EFFORT))
    state = _als_modell(client, "llama_cpp", "http://127.0.0.1:9/v1", "local")
    state.faehigkeiten_erkannt = {"thinking": {"vorlage_variablen": ["enable_thinking"]}}
    client.post("/api/v1/chat/completions", json={
        "chat_id": chat_id, "endpoint_id": "test", "content": "Hello", "gespraech": True,
    })
    assert [a.zusatz for a in server.anfragen] == [{"reasoning_effort": "none"}, {}]
    rows = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]
    assert rows[-1]["content"] == "ok"


def test_a_refusal_learns_what_was_sent_not_what_was_picked(client, chat_id, monkeypatch):
    """A spoken turn's "off" is refused and goes out once more without the
    field; the server refuses that request too. What the second refusal is
    held against is the request that really went out — it carried no stage,
    so nothing more is written down, although "off" was the stage picked."""
    from app import denkablehnung

    written: list = []
    original = denkablehnung.merken

    def spy(settings, model_id, stage):
        written.append(stage)
        return original(settings, model_id, stage)

    monkeypatch.setattr(denkablehnung, "merken", spy)

    class RefusesBoth(MockProvider):
        def __init__(self):
            super().__init__(haeppchen=["ok"])
            self.zusaetze: list = []

        async def streamen(self, anfrage):
            self.zusaetze.append(dict(anfrage.zusatz or {}))
            raise ProviderFehler("refused", status=400, rohtext=REFUSED_EFFORT)
            yield  # pragma: no cover - makes this an async generator

    server = provider_setzen(client, RefusesBoth())
    state = _als_modell(client, "llama_cpp", "http://127.0.0.1:9/v1", "local")
    state.faehigkeiten_erkannt = {"thinking": {"vorlage_variablen": ["enable_thinking"]}}
    client.post("/api/v1/chat/completions", json={
        "chat_id": chat_id, "endpoint_id": "test", "content": "Hello", "gespraech": True,
    })
    assert server.zusaetze == [{"reasoning_effort": "none"}, {}]
    assert written == ["off"]



class _LowersTheCeilingThenRefusesThinking(MockProvider):
    """The first request is refused for its answer length, naming a limit so
    small that no thinking budget fits beside it; the request that goes out
    then carries thinking switched off, and the server refuses that one for
    its thinking field. The third answers."""

    CEILING_REFUSAL = (
        '{"error":{"message":"<400> InternalError.Algo.InvalidParameter: Range of '
        'max_tokens should be [1, 1500]","type":"invalid_request_error"}}'
    )
    THINKING_REFUSAL = (
        '{"error":{"message":"Unsupported parameter: thinking",'
        '"type":"invalid_request_error","param":"thinking"}}'
    )

    def __init__(self):
        super().__init__(haeppchen=["ok"])
        self.sent: list = []

    async def streamen(self, anfrage):
        self.sent.append(
            dataclasses.replace(anfrage, zusatz=json.loads(json.dumps(anfrage.zusatz or {})))
        )
        if len(self.sent) == 1:
            raise ProviderFehler("refused", status=400, rohtext=self.CEILING_REFUSAL)
        if len(self.sent) == 2:
            raise ProviderFehler("refused", status=400, rohtext=self.THINKING_REFUSAL)
        async for stueck in super().streamen(anfrage):
            yield stueck


def test_a_refusal_after_a_lowered_ceiling_is_held_against_off_not_the_picked_stage(
    client, chat_id
):
    """"on" is the stage picked on a model with a thinking budget. A refused
    ceiling comes down so far that the request goes out with thinking off;
    that request is refused for its thinking field. What is written down is
    "off" — the stage that went out — and "on" stays on the list."""
    from app import denkablehnung

    provider = provider_setzen(client, _LowersTheCeilingThenRefusesThinking())
    _als_modell(client, "anthropic", "https://api.anthropic.com/v1", "claude-sonnet-4-5")
    client.post("/api/v1/chat/completions", json={
        "chat_id": chat_id, "endpoint_id": "test", "content": "Hello", "thinking": "on",
        "max_tokens": 8_192,
    })

    assert len(provider.sent) >= 2
    assert provider.sent[0].zusatz.get("thinking", {}).get("type") == "enabled"
    assert provider.sent[1].zusatz.get("thinking", {}).get("type") == "disabled", (
        "the lowered ceiling must have sent thinking off, or the case is not reached"
    )
    refused = denkablehnung.gemerkt(client.app.state.repositories.einstellungen, "test")
    assert refused == ["off"]


def test_silence_a_refusal_without_a_lowered_ceiling_is_held_against_the_sent_stage(
    client, chat_id
):
    """Nothing came down: the stage that went out is the stage picked, and a
    refusal of it is written down as before."""
    from app import denkablehnung

    class RefusesThinking(MockProvider):
        def __init__(self):
            super().__init__(haeppchen=["ok"])
            self.sent = 0

        async def streamen(self, anfrage):
            self.sent += 1
            if self.sent == 1:
                raise ProviderFehler(
                    "refused", status=400,
                    rohtext=_LowersTheCeilingThenRefusesThinking.THINKING_REFUSAL,
                )
            async for stueck in super().streamen(anfrage):
                yield stueck

    provider_setzen(client, RefusesThinking())
    _als_modell(client, "anthropic", "https://api.anthropic.com/v1", "claude-sonnet-4-5")
    client.post("/api/v1/chat/completions", json={
        "chat_id": chat_id, "endpoint_id": "test", "content": "Hello", "thinking": "on",
    })

    refused = denkablehnung.gemerkt(client.app.state.repositories.einstellungen, "test")
    assert refused == ["on"]


@pytest.mark.parametrize("stored", [{"an": True}, {"stufe": "turbo"}])
def test_an_old_or_unknown_stored_stage_counts_as_nothing_stored(client, chat_id, stored):
    """The older yes-form and a word off the scale name no stage: the
    default goes out as the program's choice, and refused, the turn goes out
    once more without the field."""
    server = provider_setzen(client, _RefusesEveryStage())
    _als_modell(client, "openai", UNKNOWN_HOST, "some-model")
    client.put("/api/v1/settings/modell:test/denken", json={"wert": stored})
    client.post("/api/v1/chat/completions", json={
        "chat_id": chat_id, "endpoint_id": "test", "content": "Hello",
    })
    assert server.zusaetze == [{"reasoning_effort": "medium"}, {}]



def test_a_stage_the_request_names_is_always_a_pick(client, chat_id):
    """Nothing stored, but the window names the default itself: that is
    somebody's pick, so a refusal ends the turn without a repeat and only
    that stage joins the list."""
    from app import denkablehnung

    server = provider_setzen(client, _RefusesEveryStage())
    _als_modell(client, "openai", UNKNOWN_HOST, "some-model")
    client.post("/api/v1/chat/completions", json={
        "chat_id": chat_id, "endpoint_id": "test", "content": "Hello", "thinking": "medium",
    })
    assert server.zusaetze == [{"reasoning_effort": "medium"}]
    settings = client.app.state.repositories.einstellungen
    assert denkablehnung.gemerkt(settings, "test") == ["medium"]
