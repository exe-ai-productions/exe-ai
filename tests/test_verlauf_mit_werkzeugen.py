"""An earlier answer that used tools goes back to the model as calls and
results, not as prose alone.

Fed back as its text only, the model saw its own work as narration with
gaps and, from the second answer on, narrated instead of calling — measured
2026-09-09 with a 9B model: 22 real calls in the first answer, none in any
answer after it, empty fences where the calls should have been. Every
other client keeps the calls in the history; this one stripped them.

The shape is the providers' protocol: one assistant turn carrying the
calls, one result per call, ids that match. Results are capped. A
background run's report row — an assistant row with a tool entry the model
never called — stays a plain message.
"""

from __future__ import annotations

import json
from pathlib import Path

from app import faltbitte
from app.config import EndpointConfig
from app.providers import ChatNachricht
from app.providers.anthropic import AnthropicProvider
from app.providers.base import Generierungsanfrage
from app.providers.openai_kompatibel import OpenAIKompatiblerProvider
from app.verlaufsbau import (
    VERLAUF_ERGEBNIS_ZEICHEN,
    _verlauf_bauen,
    werkzeuge_fuer_die_faltung,
    werkzeuggewicht,
)

WURZEL = Path(__file__).resolve().parents[1]


def _chat_mit_werkzeugantwort(client, chat_id, *, content="Erledigt.", werkzeuge=None):
    repositories = client.app.state.repositories
    repositories.messages.speichern(chat_id=chat_id, role="user", content="Bau mir das.")
    repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content=content, zustand="fertig",
        stats={"werkzeuge": werkzeuge if werkzeuge is not None else [
            {"name": "read_file", "argumente": {"path": "a.py"}, "ergebnis": "print(1)", "fehlgeschlagen": False},
            {"name": "run_command", "argumente": {"command": "ls"}, "ergebnis": "a.py", "fehlgeschlagen": False},
        ]},
    )
    return repositories, repositories.chats.holen(chat_id)


def test_die_aufrufe_stehen_als_zuege_im_verlauf(client, chat_id):
    repositories, chat = _chat_mit_werkzeugantwort(client, chat_id)
    verlauf = _verlauf_bauen(chat, repositories, "SYS")
    assert [n.role for n in verlauf] == ["system", "user", "assistant", "tool", "tool"]
    antwort = verlauf[2]
    assert antwort.content == "Erledigt."
    assert [a.name for a in antwort.werkzeugaufrufe] == ["read_file", "run_command"]
    assert antwort.werkzeugaufrufe[0].argumente == {"path": "a.py"}
    # Each result answers its own call, by id.
    assert verlauf[3].werkzeugaufruf_id == antwort.werkzeugaufrufe[0].id
    assert verlauf[4].werkzeugaufruf_id == antwort.werkzeugaufrufe[1].id
    assert verlauf[3].content == "print(1)"
    assert len({a.id for a in antwort.werkzeugaufrufe}) == 2


def test_eine_runde_mit_ask_user_verliert_ihren_text_nicht(client, chat_id):
    """A round that opens with a question to the USER goes back as it went out.

    The run sent the question as a call in its round's assistant turn —
    together with the words the model wrote before it — and the user's
    answer as that call's result. The rebuild sends the same: the round's
    words, the question as a call under the server's id, the answer as its
    result, and no sentence in front of the rounds.
    """
    repositories, chat = _chat_mit_werkzeugantwort(
        client,
        chat_id,
        content="Ich frage kurz nach.",
        werkzeuge=[
            {"name": "ask_user", "argumente": {"question": "Welche Datei?"},
             "ergebnis": "a.py", "fehlgeschlagen": False, "kennung": "call_1",
             "runde": 0, "text": "Ich frage kurz nach."},
            {"name": "read_file", "argumente": {"path": "a.py"},
             "ergebnis": "print(1)", "fehlgeschlagen": False, "kennung": "call_2",
             "runde": 1},
        ],
    )
    verlauf = _verlauf_bauen(chat, repositories, "SYS")

    assert [n.role for n in verlauf] == [
        "system", "user", "assistant", "tool", "assistant", "tool"
    ]
    frage = verlauf[2]
    assert frage.content == "Ich frage kurz nach."
    assert [(a.id, a.name, a.argumente) for a in frage.werkzeugaufrufe] == [
        ("call_1", "ask_user", {"question": "Welche Datei?"})
    ]
    assert (verlauf[3].werkzeugaufruf_id, verlauf[3].content) == ("call_1", "a.py")
    assert [a.name for a in verlauf[4].werkzeugaufrufe] == ["read_file"]
    # Question and answer stand once, and only as call and result.
    assert not any("You asked" in (n.content or "") for n in verlauf)


def test_eine_runde_ohne_eigene_worte_laesst_keine_leere_zeile_stehen(client, chat_id):
    """A round that is nothing but the question still is a turn: the call.

    The question goes back as the call it was, so the round carries a call
    even without words of its own, and no assistant turn stands empty — the
    one that ends the request that follows (`_verlauf_bauen`). The wire's
    own parts beside the question travel with that turn.
    """
    repositories, chat = _chat_mit_werkzeugantwort(
        client,
        chat_id,
        content="",
        werkzeuge=[
            {"name": "ask_user", "argumente": {"question": "Welche Datei?"},
             "ergebnis": "a.py", "fehlgeschlagen": False, "runde": 0,
             "denkteile": [{"type": "reasoning", "encrypted_content": "x"}]},
            {"name": "read_file", "argumente": {"path": "a.py"},
             "ergebnis": "print(1)", "fehlgeschlagen": False, "runde": 1},
        ],
    )
    verlauf = _verlauf_bauen(chat, repositories, "SYS")

    assert all(
        n.content or n.werkzeugaufrufe for n in verlauf if n.role == "assistant"
    )
    assert [a.name for n in verlauf for a in n.werkzeugaufrufe] == ["ask_user", "read_file"]


def test_eine_zeile_ohne_rundenmarken_traegt_die_frage_als_satz(client, chat_id):
    """Silence probe: a row from before the round marks has no round to put
    the call in. Its question stays the sentence in front of its text, and
    goes back as no call."""
    repositories, chat = _chat_mit_werkzeugantwort(
        client,
        chat_id,
        content="Gelesen.",
        werkzeuge=[
            {"name": "ask_user", "argumente": {"question": "Welche Datei?"},
             "ergebnis": "a.py", "fehlgeschlagen": False},
            {"name": "read_file", "argumente": {"path": "a.py"},
             "ergebnis": "print(1)", "fehlgeschlagen": False},
        ],
    )
    verlauf = _verlauf_bauen(chat, repositories, "SYS")

    antwort = verlauf[2]
    assert antwort.content.startswith("[You asked: Welche Datei? — the user answered: a.py]")
    assert [a.name for a in antwort.werkzeugaufrufe] == ["read_file"]


def _ereignisse(text: str) -> list[dict]:
    """The SSE events of one answer, in order."""
    return [
        json.loads(zeile.removeprefix("data: ").strip())
        for zeile in text.splitlines()
        if zeile.startswith("data: ")
    ]


def test_das_fenster_sieht_das_ergebnis_gekuerzt(client, chat_id):
    """The WINDOW reads a result cut at the ceiling, like the model does.

    A tool that answers longer than `WERKZEUGERGEBNIS_GRENZE` — an MCP server
    of somebody else cuts nothing — would otherwise carry its whole answer
    into the chat. The cut stands once, where the result arises
    (`app/api/v1/generierung.py`); beside it is the model's own copy, and
    THAT one is what the existing tests watch. This is the window's copy,
    which no test held: without the cut the event carries all ~30,000
    characters.
    """
    from app.api.v1.generierung import WERKZEUGERGEBNIS_GRENZE
    from tests.conftest import provider_setzen
    from tests.test_werkzeugrunden_verlauf import _EinAufruf, _Vielwerk

    client.app.state.werkzeuge = _Vielwerk()
    client.app.state.config.features.mcp = True
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    provider_setzen(client, _EinAufruf("viel"))

    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Lies mal."},
    )

    ergebnis = next(e for e in _ereignisse(antwort.text) if e["typ"] == "tool_result")
    assert len(ergebnis["text"]) == WERKZEUGERGEBNIS_GRENZE


def test_ein_langes_ergebnis_wird_gekappt(client, chat_id):
    repositories, chat = _chat_mit_werkzeugantwort(client, chat_id, werkzeuge=[
        {"name": "run_command", "argumente": {"command": "cat log"}, "ergebnis": "x" * 2000, "fehlgeschlagen": False},
    ])
    verlauf = _verlauf_bauen(chat, repositories, "SYS")
    ergebnis = verlauf[-1].content
    assert ergebnis.startswith("x" * VERLAUF_ERGEBNIS_ZEICHEN)
    assert ergebnis.endswith("[truncated]")
    assert len(ergebnis) < 2000


def test_eine_antwort_nur_aus_aufrufen_bleibt_ein_werkzeugzug(client, chat_id):
    """No text at all is a normal shape for a tool answer — it must not fall
    into the "[This turn produced no content.]" replacement."""
    repositories, chat = _chat_mit_werkzeugantwort(client, chat_id, content="")
    verlauf = _verlauf_bauen(chat, repositories, "SYS")
    assert verlauf[2].role == "assistant"
    assert verlauf[2].content == ""
    assert len(verlauf[2].werkzeugaufrufe) == 2
    assert "produced no content" not in verlauf[2].content


def test_ein_leeres_ergebnis_wird_benannt(client, chat_id):
    repositories, chat = _chat_mit_werkzeugantwort(client, chat_id, werkzeuge=[
        {"name": "run_command", "argumente": {"command": "true"}, "ergebnis": "", "fehlgeschlagen": False},
    ])
    verlauf = _verlauf_bauen(chat, repositories, "SYS")
    assert verlauf[-1].content == faltbitte.OHNE_AUSGABE


def test_die_berichtszeile_eines_hintergrundlaufs_bleibt_prosa(client, chat_id):
    """The model never called that entry — it reads the report."""
    repositories = client.app.state.repositories
    repositories.messages.speichern(chat_id=chat_id, role="user", content="Installier.")
    repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="[background run #3 finished: npm install]",
        art="werkzeugmeldung",
        stats={"werkzeuge": [{"name": "run_command", "argumente": {"command": "npm install", "background": True},
                              "ergebnis": "added 70 packages", "lauf_nummer": 3, "exit_code": 0}]},
    )
    chat = repositories.chats.holen(chat_id)
    verlauf = _verlauf_bauen(chat, repositories, "SYS")
    # Told to the model as the user's side, never as its own words: fed back
    # as assistant text it took the report's shape for its own and wrote
    # reports of its own making.
    assert [n.role for n in verlauf] == ["system", "user", "user"]
    assert verlauf[2].werkzeugaufrufe == []
    assert "background run #3" in verlauf[2].content


def test_beide_anbieter_koennen_den_verlauf_senden(client, chat_id):
    """The shape is the protocol — OpenAI wants tool_calls and tool
    messages, Anthropic tool_use and tool_result blocks — and both builders
    take what the history hands them."""
    repositories, chat = _chat_mit_werkzeugantwort(client, chat_id)
    anfrage = Generierungsanfrage(nachrichten=_verlauf_bauen(chat, repositories, "SYS"))

    offen = OpenAIKompatiblerProvider(EndpointConfig.model_validate(
        {"id": "o", "name": "o", "base_url": "http://mock.invalid/v1"}
    ))
    koerper = offen._koerper_bauen(anfrage)
    kennungen = [a["id"] for a in koerper["messages"][2]["tool_calls"]]
    assert koerper["messages"][3]["tool_call_id"] == kennungen[0]
    assert koerper["messages"][4]["tool_call_id"] == kennungen[1]

    anthropic = AnthropicProvider(EndpointConfig.model_validate({
        "id": "a", "provider": "anthropic", "base_url": "https://api.anthropic.com/v1",
        "parameter_dialect": "anthropic", "api_key_env": "TEST_ANTHROPIC_KEY",
    }))
    koerper = anthropic._koerper_bauen(anfrage)
    bloecke = koerper["messages"][1]["content"]
    assert [b["type"] for b in bloecke] == ["text", "tool_use", "tool_use"]
    ergebnisse = koerper["messages"][2]["content"]
    assert [b["type"] for b in ergebnisse] == ["tool_result", "tool_result"]
    assert ergebnisse[0]["tool_use_id"] == bloecke[1]["id"]


def _anthropic():
    return AnthropicProvider(EndpointConfig.model_validate({
        "id": "a", "provider": "anthropic", "base_url": "https://api.anthropic.com/v1",
        "parameter_dialect": "anthropic", "api_key_env": "TEST_ANTHROPIC_KEY",
    }))


def test_ohne_werkzeugangebot_gehen_die_aufrufe_als_text(client, chat_id):
    """A request whose messages carry tool calls but whose body names no
    tools is refused by Anthropic ("must define tools"): a chat that once
    used tools failed on every turn after the tools were switched off or
    the model swapped for one without them. Without the offer the answer
    travels as its text, the way it did before."""
    repositories, chat = _chat_mit_werkzeugantwort(client, chat_id)
    verlauf = _verlauf_bauen(chat, repositories, "SYS", werkzeuge=False)
    assert [n.role for n in verlauf] == ["system", "user", "assistant"]
    assert verlauf[2].werkzeugaufrufe == []
    # As text, not dropped: what the tools answered is what the
    # conversation was built on.
    assert verlauf[2].content.endswith("Erledigt.")
    assert '- read_file {"path": "a.py"} → print(1)' in verlauf[2].content
    assert '- run_command {"command": "ls"} → a.py' in verlauf[2].content

    koerper = _anthropic()._koerper_bauen(Generierungsanfrage(nachrichten=verlauf))
    assert "tools" not in koerper
    for nachricht in koerper["messages"]:
        inhalt = nachricht["content"]
        assert not isinstance(inhalt, list) or all(
            b["type"] not in ("tool_use", "tool_result") for b in inhalt
        )


def test_die_antwort_reicht_ihr_angebot_an_den_verlauf_durch():
    """Pinned at the source: the offer is read out BEFORE the history is
    built, and the history is told whether there is one."""
    quelle = (WURZEL / "app/api/v1/generierung.py").read_text(encoding="utf-8")
    assert quelle.find("angebot = (") < quelle.find("nachrichten = _verlauf_bauen(")
    assert "werkzeuge=bool(angebot)," in quelle
    assert "if angebot:\n        anfrage.werkzeuge = angebot" in quelle


def test_ein_bild_nach_werkzeugergebnissen_wird_in_den_nutzerzug_gefaltet(client, chat_id):
    """A picture sent right after an answer that used tools follows that
    answer's results — a user turn for Anthropic — and two user turns in a
    row are rejected whatever the first one was made of. The image and
    its text join the results' turn."""
    repositories, chat = _chat_mit_werkzeugantwort(client, chat_id)
    verlauf = _verlauf_bauen(chat, repositories, "SYS")
    verlauf.append(ChatNachricht(
        role="user", content="Und das hier?", bild_urls=["data:image/png;base64,QUJD"],
    ))
    koerper = _anthropic()._koerper_bauen(Generierungsanfrage(nachrichten=verlauf))
    assert [m["role"] for m in koerper["messages"]] == ["user", "assistant", "user"]
    letzte = koerper["messages"][-1]["content"]
    assert [b["type"] for b in letzte] == ["tool_result", "tool_result", "image", "text"]
    assert letzte[2]["source"] == {"type": "base64", "media_type": "image/png", "data": "QUJD"}


def test_das_werkzeuggewicht_zaehlt_aufrufe_und_gekappte_ergebnisse(client, chat_id):
    """What compaction adds to a row's text for its calls: the arguments
    as they travel, the result as far as the history keeps it, nothing for
    a question to the user (that is in the text already), and nothing at
    all for a report row — the model never called that one."""
    repositories, chat = _chat_mit_werkzeugantwort(client, chat_id, werkzeuge=[
        {"name": "run_command", "argumente": {"command": "cat log"}, "ergebnis": "x" * 2000, "fehlgeschlagen": False},
        {"name": "ask_user", "argumente": {"question": "Wirklich?"}, "ergebnis": "ja", "fehlgeschlagen": False},
    ])
    zeile = repositories.messages.auflisten(chat_id=chat_id)[-1]
    # The cut result AS IT TRAVELS, its "…[truncated]" mark included: the
    # weight is read off the same reading the turns are built from
    # (`_ergebnis_im_verlauf`), so the number cannot drift from what the
    # request actually carries.
    verlauf = _verlauf_bauen(chat, repositories, "SYS")
    gesendet = next(n for n in verlauf if n.role == "tool")
    assert werkzeuggewicht(zeile) == len('{"command": "cat log"}') + len(gesendet.content)
    assert len(gesendet.content) > VERLAUF_ERGEBNIS_ZEICHEN
    bericht = repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="[report]", art="werkzeugmeldung",
        stats={"werkzeuge": [{"name": "run_command", "argumente": {"command": "ls"}, "ergebnis": "a"}]},
    )
    assert werkzeuggewicht(bericht) == 0
    assert werkzeuggewicht(repositories.messages.auflisten(chat_id=chat_id)[0]) == 0


def test_eine_frage_mit_rundenmarke_zaehlt_und_faltet_als_aufruf(client, chat_id):
    """A question that goes back as a call weighs as one and reaches the
    compaction request as one: the row's text no longer carries it, so the
    weight and the fold have to — once."""
    repositories, chat = _chat_mit_werkzeugantwort(client, chat_id, content="Gut.", werkzeuge=[
        {"name": "ask_user", "argumente": {"question": "Wirklich?"}, "ergebnis": "ja",
         "fehlgeschlagen": False, "runde": 0, "kennung": "call_1", "text": ""},
    ])
    zeile = repositories.messages.auflisten(chat_id=chat_id)[-1]

    assert werkzeuggewicht(zeile) == len('{"question": "Wirklich?"}') + len("ja")
    faltung = werkzeuge_fuer_die_faltung(zeile, "Gut.")
    assert faltung.count("Wirklich?") == 1
    assert "ja" in faltung


def test_die_faltung_liest_dasselbe_ergebnis_weiter(client, chat_id):
    """One reading of one tool result, for the prompt and for the fold.

    Since the call ran, no prompt of this chat has shown the model more
    than VERLAUF_ERGEBNIS_ZEICHEN of it, so a summary asked to write down
    more would be asked to write down what nobody in the chat ever saw.
    The whole result stays in the row either way, one card away.
    """
    repositories, chat = _chat_mit_werkzeugantwort(client, chat_id, werkzeuge=[
        {"name": "run_command", "argumente": {"command": "cat log"}, "ergebnis": "Q" * 20_000},
    ])
    zeile = repositories.messages.auflisten(chat_id=chat_id)[-1]

    verlauf = _verlauf_bauen(chat, repositories, "SYS")
    assert verlauf[-1].content.count("Q") == VERLAUF_ERGEBNIS_ZEICHEN

    fuer_die_faltung = werkzeuge_fuer_die_faltung(zeile, "Erledigt.")
    assert fuer_die_faltung.count("Q") == VERLAUF_ERGEBNIS_ZEICHEN
    # The prompt's own note, not the wider one the request keeps for a job
    # (app/faltbitte.py): the result never reached that ceiling.
    assert "…[truncated]" in fuer_die_faltung
    assert faltbitte.ERGEBNIS_VERMERK not in fuer_die_faltung
    assert fuer_die_faltung.endswith("Erledigt.")


def test_die_faltung_traegt_das_ergebnis_wie_der_prompt(client, chat_id):
    """The very same characters in both, cut once (app/verlaufsbau.py).

    Two cutters for one result would let the request drift from the prompt
    the next time one of them is touched, and the drift shows up as a
    summary written about text no prompt ever carried.
    """
    repositories, chat = _chat_mit_werkzeugantwort(client, chat_id, werkzeuge=[
        {"name": "run_command", "argumente": {"command": "cat log"},
         "ergebnis": "ANFANG" + "Q" * 25_000 + "ENDE"},
    ])
    zeile = repositories.messages.auflisten(chat_id=chat_id)[-1]

    im_prompt = _verlauf_bauen(chat, repositories, "SYS")[-1].content
    assert im_prompt in werkzeuge_fuer_die_faltung(zeile, "Erledigt.")
    assert "ENDE" not in im_prompt


def test_eine_berichtszeile_bekommt_auch_in_der_faltung_keinen_werkzeugblock(client, chat_id):
    """A finished background run's report row carries a tool entry the model
    never called — the same set `werkzeuggewicht` weighs at zero."""
    repositories = client.app.state.repositories
    bericht = repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="[report]", art="werkzeugmeldung",
        stats={"werkzeuge": [{"name": "run_command", "argumente": {"command": "ls"}, "ergebnis": "a"}]},
    )
    assert werkzeuge_fuer_die_faltung(bericht, "[report]") == "[report]"


def test_das_werkzeuggewicht_zaehlt_ein_leeres_ergebnis_mit(client, chat_id):
    """A call that came back empty weighs what the request really carries for
    it: the sentence the turns write, not nothing.

    Read as zero, every empty tool result made the middle look lighter than
    the request is — the fold trigger counted the one thing the request
    spends a sentence on as free. Weighed against the built request and not
    against the sentence alone: only that way does the test fall when the
    two drift apart again.
    """
    repositories, chat = _chat_mit_werkzeugantwort(
        client,
        chat_id,
        werkzeuge=[
            {
                "name": "run_command",
                "argumente": {"command": "true"},
                "ergebnis": "",
                "fehlgeschlagen": False,
            },
        ],
    )
    zeile = repositories.messages.auflisten(chat_id=chat_id)[-1]
    verlauf = _verlauf_bauen(chat, repositories, "SYS")
    gesendet = next(n for n in verlauf if n.role == "tool")

    assert gesendet.content == faltbitte.OHNE_AUSGABE
    assert werkzeuggewicht(zeile) == len('{"command": "true"}') + len(
        gesendet.content
    )


def test_ein_gefuelltes_ergebnis_wiegt_wie_vorher(client, chat_id):
    """Silence test: a result that has text weighs its own text and nothing
    on top."""
    repositories, chat = _chat_mit_werkzeugantwort(
        client,
        chat_id,
        werkzeuge=[
            {
                "name": "run_command",
                "argumente": {"command": "true"},
                "ergebnis": "ok",
                "fehlgeschlagen": False,
            },
        ],
    )
    zeile = repositories.messages.auflisten(chat_id=chat_id)[-1]
    verlauf = _verlauf_bauen(chat, repositories, "SYS")
    gesendet = next(n for n in verlauf if n.role == "tool")

    assert gesendet.content == "ok"
    assert werkzeuggewicht(zeile) == len('{"command": "true"}') + len("ok")
