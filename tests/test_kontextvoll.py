"""A provider calling a request too long for the model's context.

Recognized in one place (app/kontextvoll.py) for a chat and a job alike,
folded and sent again up to three times, and after that the answer ends as
the error it is with the context-full flag the window turns into a heading.
Nothing is left out silently: every fold is a summary that says it is one.
"""

from __future__ import annotations

from types import SimpleNamespace

import json

import pytest

from app import (
    chatverdichtung,
    faltpause,
    fenstergroesse,
    grundprompt,
    kontextvoll,
    verdichtung,
)
from app.providers import MockProvider, ProviderFehler, mock_endpunkt
from app.providers.base import Stueck, Werkzeugaufruf
from tests.conftest import provider_setzen
from tests.test_auftraege_api import (
    UeberDerVerdichtungsschwelle, agent_schreiben, auf_ende_warten,
)

# Measured on llama.cpp: a 755-token prompt against --ctx-size 64 (256 per
# slot). HTTP 400, before the stream starts.
LLAMA = (
    '{"error":{"code":400,"message":"request (755 tokens) exceeds the available '
    'context size (256 tokens), try increasing it","type":"exceed_context_size_error",'
    '"n_prompt_tokens":755,"n_ctx":256}}'
)
# Anthropic's documented wording: 400 invalid_request_error, "prompt is too long".
ANTHROPIC = (
    '{"type":"error","error":{"type":"invalid_request_error",'
    '"message":"prompt is too long: 1000500 tokens > 1000000 maximum"}}'
)
# OpenAI: 400, code context_length_exceeded.
OPENAI = (
    '{"error":{"message":"This model\'s maximum context length is 4096 tokens. '
    'However, your messages resulted in 4239 tokens. Please reduce the length of '
    'the messages.","type":"invalid_request_error","param":"messages",'
    '"code":"context_length_exceeded"}}'
)
# oMLX's own check before a request is admitted: 400.
OMLX = '{"detail":"Prompt too long: 300000 tokens exceeds max context window of 262144 tokens"}'
# Anthropic's two shapes in ONE refusal: the input past the window, and the
# quoted sum of input and ceiling. Composed from the two wordings the module
# documents — it stands for the refusal whose words name the input beside
# numbers that quote the ceiling too.
ANTHROPIC_ZWEI_SAETZE = (
    '{"type":"error","error":{"type":"invalid_request_error","message":'
    '"prompt is too long: 250000 tokens > 200000 maximum. input length and '
    'max_tokens exceed context limit: 250000 + 8192 > 200000"}}'
)
# The input named without a number beside it, in the family's own words
# ("input is too long", as other servers word it). Not measured
# here — it stands for the refusals recognized as a full context only by
# what they name, which would otherwise end as a plain provider error.
EINGABE_ZU_LANG = '{"error":{"message":"Input is too long for requested model"}}'
# vLLM, where the answer's ceiling alone is past the window
# (vllm/renderers/params.py, TokenizeParams): 400, no input count at all.
VLLM_MAX_MODEL_LEN = (
    '{"object":"error","message":"max_tokens=16384 cannot be greater than '
    'max_model_len=8192. Please request fewer output tokens.",'
    '"type":"BadRequestError","param":null,"code":400}'
)


# --- Recognition -------------------------------------------------------------


@pytest.mark.parametrize("text", [LLAMA, ANTHROPIC, OPENAI, OMLX, VLLM_MAX_MODEL_LEN])
def test_jeder_gemessene_text_wird_erkannt(text):
    assert kontextvoll.ist_kontext_voll(400, text)


# vLLM's own prompt check (``vllm/v1/engine/input_processor``,
# ``_validate_prompt_len``): the window named only as "maximum model length".
VLLM_MAXIMUM_MODEL_LENGTH = (
    '{"object":"error","message":"The decoder prompt (length 9000) is longer than '
    'the maximum model length of 8192.","type":"BadRequestError","code":400}'
)


def test_vllm_maximum_model_length_is_a_full_context():
    assert kontextvoll.ist_kontext_voll(400, VLLM_MAXIMUM_MODEL_LENGTH)


def test_vllm_maximum_model_length_reads_no_number():
    # "... of 8192" is not one of the vLLM forms the window reader takes.
    fehler = ProviderFehler("Bad Request", status=400, rohtext=VLLM_MAXIMUM_MODEL_LENGTH)
    assert kontextvoll.grenze_aus_fehler(fehler) is None


@pytest.mark.parametrize(
    ("status", "text"),
    [
        (400, '{"error":{"message":"invalid_api_key"}}'),
        (400, '{"error":{"message":"Unsupported value: \'reasoning_effort\' does not support \'max\'"}}'),
        (400, '{"detail":"Prefill memory exceeded"}'),
        (401, '{"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}}'),
        (None, "Verbindung verweigert"),
        # A limit per minute is a rate limit however it is worded.
        (429, "Rate limit reached: too many tokens per minute, context length unaffected"),
        (429, VLLM_MAX_MODEL_LEN),
        (400, None),
    ],
)
def test_ein_fremder_fehler_wird_nicht_erkannt(status, text):
    assert not kontextvoll.ist_kontext_voll(status, text)


def test_der_koerper_zaehlt_auch_hinter_dem_satz():
    """The error's own sentence carries only the first 400 characters of the
    body; the pattern may sit further in."""
    rohtext = "x" * 600 + ANTHROPIC
    fehler = ProviderFehler(f"Claude antwortete mit 400: {rohtext[:400]}", status=400, rohtext=rohtext)
    assert kontextvoll.bei_fehler(fehler)


def test_ein_fehler_aus_dem_strom_ohne_koerper_wird_am_satz_erkannt():
    assert kontextvoll.bei_fehler(ProviderFehler("Claude: prompt is too long"))
    assert not kontextvoll.bei_fehler(ProviderFehler("Claude: Overloaded"))


def test_das_ende_halbiert_sich_je_faltung():
    assert [kontextvoll.faltbudget(80_000, n) for n in (1, 2, 3)] == [80_000, 40_000, 20_000]
    assert kontextvoll.faltbudget(1, 3) == 1


# --- Shared pieces for the two paths --------------------------------------


def _zu_lang(rohtext: str = LLAMA) -> ProviderFehler:
    return ProviderFehler(f"provider answered with 400: {rohtext}", status=400, rohtext=rohtext)


def _ablehnung(rohtext: str | list[str], nr: int) -> str:
    """The refusal for the ``nr``-th answer request: one text for all, or
    one per request with the last one repeated."""
    if isinstance(rohtext, str):
        return rohtext
    return rohtext[min(nr, len(rohtext)) - 1]


def _ist_faltung(anfrage) -> bool:
    letzte = anfrage.nachrichten[-1]
    return letzte.role == "user" and (letzte.content or "").startswith(verdichtung.ANFRAGE_TEXT)


def _groesse(anfrage) -> int:
    return sum(len(n.content or "") for n in anfrage.nachrichten)


def _faltschritte(monkeypatch, runde) -> list[tuple[int, bool]]:
    """Every forced fold step on a list in memory (a job's, or a chat's past
    its first round), as the answer requests ``runde()`` counts before it
    and whether the history had a middle at that step's budget."""
    schritte: list[tuple[int, bool]] = []
    echt = verdichtung.verdichten

    async def mitschreiben(zustand, anfrage, budget=verdichtung.LETZTE_ZEICHEN, **kwargs):
        if kwargs.get("erzwungen"):
            # Asked the way the fold asks it: past the pinned opening, up to
            # where the protected tail begins.
            nachrichten = anfrage.nachrichten
            anfang = verdichtung._nicht_hinter_werkzeugantwort(
                nachrichten, verdichtung.ERSTE_FEST, +1
            )
            mitte = (
                verdichtung.noetig(nachrichten, budget)
                and verdichtung.geschuetztes_ende(nachrichten, budget) > anfang
            )
            schritte.append((runde(), mitte))
        return await echt(zustand, anfrage, budget, **kwargs)

    monkeypatch.setattr(verdichtung, "verdichten", mitschreiben)
    return schritte


def _schritte_mit_mitte_je_runde(schritte: list[tuple[int, bool]]) -> dict[int, int]:
    """How many steps of each round had something to fold. Only a step that
    found no middle may be followed by another in the same round."""
    je_runde: dict[int, int] = {}
    for runde, mitte in schritte:
        if mitte:
            je_runde[runde] = je_runde.get(runde, 0) + 1
    return je_runde


def _zeilenfaltungen(monkeypatch) -> list[int]:
    """Every forced fold step of a chat's rows, as the budget it was asked
    with."""
    budgets: list[int] = []
    echt = chatverdichtung.erzwungen_verdichten

    async def mitschreiben(**kwargs):
        budgets.append(kwargs["budget"])
        return await echt(**kwargs)

    monkeypatch.setattr(chatverdichtung, "erzwungen_verdichten", mitschreiben)
    return budgets


# --- Chat --------------------------------------------------------------------


class ZuLangDannGut(MockProvider):
    """Refuses the first ``zu_lang`` answer requests as too long, then
    answers. Summary requests are answered, or fail when told to."""

    def __init__(
        self,
        *args,
        zu_lang: int,
        faltung_scheitert: bool = False,
        beim_falten=None,
        rohtext: str | list[str] = LLAMA,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.zu_lang = zu_lang
        self.rohtext = rohtext
        # The text of every answer request, joined — what the model was shown.
        self.texte: list[str] = []
        self.faltung_scheitert = faltung_scheitert
        # Called while a summary is being asked for — where a test presses stop.
        self.beim_falten = beim_falten
        self.faltungen = 0
        self.groessen: list[int] = []
        # The answer ceiling every answer request carried.
        self.grenzen: list[int | None] = []

    async def streamen(self, anfrage):
        if _ist_faltung(anfrage):
            self.faltungen += 1
            if self.beim_falten:
                self.beim_falten()
            if self.faltung_scheitert:
                raise ProviderFehler("connection refused")
            yield Stueck("content", text="summary")
            return
        self.groessen.append(_groesse(anfrage))
        self.grenzen.append(anfrage.max_tokens)
        self.texte.append("\n".join(n.content or "" for n in anfrage.nachrichten))
        if len(self.groessen) <= self.zu_lang:
            raise _zu_lang(_ablehnung(self.rohtext, len(self.groessen)))
        async for stueck in super().streamen(anfrage):
            yield stueck


def _langer_chat(client, chat_id: str, paare: int = 10) -> None:
    """Twenty rows of 8,000 characters: past the tail budget three times
    over, so there is a middle for every one of the three folds."""
    repositories = client.app.state.repositories
    je = verdichtung.LETZTE_ZEICHEN // 10
    for nr in range(paare):
        repositories.messages.speichern(
            chat_id=chat_id, role="user", content=f"question {nr} " + "x" * je
        )
        repositories.messages.speichern(
            chat_id=chat_id, role="assistant", content=f"answer {nr} " + "x" * je,
            zustand="fertig",
        )


def _anthropic_draht(client, kennung: str = "test") -> None:
    """Puts the endpoint on the ANTHROPIC wire. Only there does Auto still
    carry a number, so only there can the check before sending find that the
    input leaves no room for an answer (app/antwortgrenze.py). On the OpenAI
    wire nothing goes out but the request itself, and what does not fit comes
    back as the provider's own refusal."""
    zustand = client.app.state.discovery.zustaende[kennung]
    zustand.endpunkt = mock_endpunkt(kennung, provider="anthropic")


def _chat_mit(client, provider, eingetragen: bool = True, anthropic: bool = False):
    provider_setzen(client, provider)
    if anthropic:
        _anthropic_draht(client)
    # The window the discovery resolved stays in force. It used to be cleared
    # here to keep the threshold from ever firing, but a request's own ceiling
    # is now measured against the window (app/antwortgrenze.py) and there is
    # always one — the fallback sees to that (app/fenstergroesse.py). The
    # histories below sit far under the compaction threshold anyway, so every
    # fold in this file is still a FORCED one.
    #
    # And it is HELD there, the same way ``_auftrag`` holds the job's: the
    # refusals below carry llama.cpp's real numbers, and left to teach, a
    # 256-token window would land under every one of these histories
    # mid-run. A window smaller than the prompt it is measuring leaves no
    # room for an answer and none for a summary either, so no fold would
    # ever ask a model and nothing would be folded — which is
    # right at a real server and never happens at one, because no real
    # server offers 256 tokens to a chat of 160,000 characters. The test
    # about that very learning hands ``eingetragen=False``.
    if eingetragen:
        zustand = client.app.state.discovery.zustaende["test"]
        zustand.kontext_quelle = fenstergroesse.QUELLE_EINGETRAGEN
    return provider


def _senden(client, chat_id: str, **felder) -> list[dict]:
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Newest question", **felder},
    )
    assert antwort.status_code == 200
    return [
        json.loads(zeile[5:].strip())
        for zeile in antwort.text.splitlines()
        if zeile.startswith("data:")
    ]


def _antwort(client, chat_id: str) -> dict:
    return client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"][-1]


def test_chat_einmal_zu_lang_faltet_einmal_und_die_antwort_kommt(client, chat_id):
    provider = _chat_mit(client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=1))
    _langer_chat(client, chat_id)

    ereignisse = _senden(client, chat_id)

    assert provider.faltungen == 1
    assert len(provider.groessen) == 2
    assert provider.groessen[1] < provider.groessen[0]
    # The question being answered is never folded away.
    assert "Newest question" in (provider.letzte_anfrage.nachrichten[-1].content or "")
    assert "".join(e.get("text", "") for e in ereignisse if e["typ"] == "content") == "Hallo Welt"
    assert not [e for e in ereignisse if e["typ"] == "error"]
    assert ereignisse[-1]["typ"] == "done"
    assert ereignisse[-1]["verdichtet"]
    stats = _antwort(client, chat_id)["stats"]
    assert "kontextfenster_voll" not in stats
    assert "fehler" not in stats


def test_chat_viermal_zu_lang_faltet_dreimal_dann_die_karte(client, chat_id):
    provider = _chat_mit(client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=4))
    _langer_chat(client, chat_id)

    ereignisse = _senden(client, chat_id)

    assert provider.faltungen == 3
    assert len(provider.groessen) == 4
    assert provider.groessen == sorted(provider.groessen, reverse=True)
    assert len(set(provider.groessen)) == 4
    fehler = "".join(e.get("text", "") for e in ereignisse if e["typ"] == "error")
    assert "exceeds the available context size" in fehler
    antwort = _antwort(client, chat_id)
    assert antwort["stats"]["kontextfenster_voll"] is True
    assert "exceeds the available context size" in antwort["stats"]["fehler"]
    assert antwort["zustand"] == "fehler"


def test_chat_scheitert_die_faltung_eine_anfrage_dann_die_karte(client, chat_id, monkeypatch):
    """A dead fold server, the rows path after a refusal: the summary is
    asked for ONCE, nothing is folded, no further step follows — each would
    sit inside the pause — and the answer ends in the card."""
    provider = _chat_mit(
        client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=4, faltung_scheitert=True)
    )
    _langer_chat(client, chat_id)
    schritte = _zeilenfaltungen(monkeypatch)

    ereignisse = _senden(client, chat_id)

    assert len(schritte) == 1
    assert provider.faltungen == 1
    assert len(provider.groessen) == 1
    assert not _verdichtungen(client, chat_id)
    assert faltpause.pausiert(chat_id)
    assert ereignisse[-1]["typ"] == "done"
    assert _antwort(client, chat_id)["stats"]["kontextfenster_voll"] is True


def test_chat_scheitert_die_faltung_vor_dem_senden_eine_anfrage_dann_die_karte(
    client, chat_id, monkeypatch
):
    """A dead fold server, the rows path before sending: the input leaves no
    room for an answer, the summary is asked for once and fails, the request
    goes out with the smallest ceiling there is, and the refusal it comes
    back with ends the answer in the card."""
    provider = _chat_mit(
        client,
        ZuLangDannGut(mock_endpunkt("test"), zu_lang=4, faltung_scheitert=True),
        anthropic=True,
    )
    # Under the history, so nothing is left for an answer; over what the
    # summarizing request carries without the verbatim tail, so a model is
    # really asked.
    client.app.state.discovery.zustaende["test"].context_tokens = 40_000
    _langer_chat(client, chat_id)
    schritte = _zeilenfaltungen(monkeypatch)

    ereignisse = _senden(client, chat_id)

    # One step before sending, and none after the refusal: that one already
    # ended without a summary.
    assert len(schritte) == 1
    assert provider.faltungen == 1
    assert provider.grenzen == [1]
    assert not _verdichtungen(client, chat_id)
    assert ereignisse[-1]["typ"] == "done"
    assert _antwort(client, chat_id)["stats"]["kontextfenster_voll"] is True


def test_chat_ohne_mitte_kein_weiterer_versuch(client, chat_id):
    """A short chat has nothing between its opening and its tail: no summary
    is asked for, no second request goes out, the card comes straight away."""
    provider = _chat_mit(client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=4))

    _senden(client, chat_id)

    assert provider.faltungen == 0
    assert len(provider.groessen) == 1
    assert _antwort(client, chat_id)["stats"]["kontextfenster_voll"] is True


def test_chat_findet_die_erste_stufe_keine_mitte_faltet_die_naechste(client, chat_id):
    """With no known window the first step keeps the ceiling as its tail,
    and four long turns fit inside it whole. The half budget has a middle:
    one fold, one resend, and the answer comes."""
    provider = _chat_mit(client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=1))
    _langer_chat(client, chat_id, paare=4)

    ereignisse = _senden(client, chat_id)

    assert provider.faltungen == 1
    assert len(provider.groessen) == 2
    assert provider.groessen[1] < provider.groessen[0]
    assert "".join(e.get("text", "") for e in ereignisse if e["typ"] == "content") == "Hallo Welt"
    assert "kontextfenster_voll" not in _antwort(client, chat_id)["stats"]


def test_chat_stopp_waehrend_der_faltung_schickt_nicht_neu(client, chat_id):
    generierungen = client.app.state.generierungen
    provider = _chat_mit(
        client,
        ZuLangDannGut(
            mock_endpunkt("test"),
            zu_lang=4,
            beim_falten=lambda: generierungen.alle_im_chat_abbrechen(chat_id),
        ),
    )
    _langer_chat(client, chat_id)

    ereignisse = _senden(client, chat_id)

    assert provider.faltungen == 1
    assert len(provider.groessen) == 1
    assert ereignisse[-1]["abgebrochen"] is True
    assert _antwort(client, chat_id)["zustand"] == "abgebrochen"


def test_chat_ohne_zu_lang_faltet_nichts(client, chat_id):
    """Silence test: an ordinary answer on the same long chat folds nothing."""
    provider = _chat_mit(client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=0))
    _langer_chat(client, chat_id)

    ereignisse = _senden(client, chat_id)

    assert provider.faltungen == 0
    assert len(provider.groessen) == 1
    assert ereignisse[-1]["verdichtet"] is None
    assert "kontextfenster_voll" not in _antwort(client, chat_id)["stats"]


def _langer_chat_mit_block(client, chat_id: str, *, block_pair: int) -> str:
    """The same long chat, with the block on the user row of pair
    ``block_pair`` — pair 2 or later, or the row is in the pinned opening and
    no fold can take it.

    Written the way the request route writes it onto the turn it goes out
    with (app/api/v1/generierung.py): a turn that was the newest of its day
    keeps the block of that day, and from the next turn on it stands in the
    middle of the history — past the opening and past the tail a fold keeps
    verbatim, so a fold can take it.
    """
    _langer_chat(client, chat_id)
    repositories = client.app.state.repositories
    block = grundprompt.environment_block(client.app.state.config.app.timezone)
    zeilen = repositories.messages.fuer_das_modell(chat_id=chat_id)
    nutzer = [zeile for zeile in zeilen if zeile.role == "user"]
    repositories.messages.set_clock_sentence(nutzer[block_pair].id, block)
    return block


def test_a_fold_that_swallowed_the_block_sends_it_again(client, chat_id):
    """The fold takes the row that carried the block into its summary.

    The round sent again after it reads the day again — in front of the newest
    user turn, the question being answered, and on the row, so the next
    request hands that very turn back byte for byte
    (app/grundprompt.restore_environment_block, _restore_environment_block_on_rows)."""
    provider = _chat_mit(client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=1))
    block = _langer_chat_mit_block(client, chat_id, block_pair=2)

    _senden(client, chat_id)

    assert provider.faltungen == 1
    # The refused request carried it on the row of that day ...
    assert provider.texte[0].count(block) == 1
    # ... and the round sent again carries it again: the row is gone with the
    # fold, the question took it over, and it stands there exactly once.
    assert provider.texte[1].count(block) == 1
    assert provider.letzte_anfrage.nachrichten[-1].content.startswith(block)
    assert provider.letzte_anfrage.nachrichten[-1].content.endswith("Newest question")
    # The answer came, rather than ending in the context-full card.
    assert "kontextfenster_voll" not in _antwort(client, chat_id)["stats"]
    # On the row, not only in the request: the next request builds from the
    # rows, and it finds the block there — on that same turn, so it goes out
    # exactly as it went out a moment ago.
    zeilen = client.app.state.repositories.messages.fuer_das_modell(chat_id=chat_id)
    assert [
        row.stats.get("clock_sentence")
        for row in zeilen
        if row.stats.get("clock_sentence")
    ] == [block]

    _senden(client, chat_id)

    assert provider.texte[2].count(block) == 1
    assert f"{block}\n\nNewest question" in provider.texte[2]
    assert provider.letzte_anfrage.nachrichten[-1].content == "Newest question"


def test_a_fold_in_memory_that_swallowed_the_block_sends_it_again(client, chat_id):
    """The same cure for the fold a later tool round takes.

    It writes no row the block could be handed to, so it goes in front of the
    newest user turn in the request itself — the question being answered."""
    provider = _chat_mit(
        client, ZuLangNurInRundeZwei(mock_endpunkt("test"), zu_lang=0)
    )
    block = _langer_chat_mit_block(client, chat_id, block_pair=2)

    _senden(client, chat_id)

    assert provider.faltungen == 1
    # Both rounds before the fold carried it on the row of that day ...
    assert provider.texte[0].count(block) == 1
    assert provider.texte[1].count(block) == 1
    # ... and the round sent again carries it again — the fold took the turn
    # it stood in front of, the question took it over, and it stands there
    # exactly once, in front of the question's own words.
    assert provider.texte[2].count(block) == 1
    assert f"{block}\n\nNewest question" in provider.texte[2]


def test_a_fold_that_left_the_block_row_standing_sends_no_second_one(client, chat_id):
    """Silence test: the folded middle did not take the row that carries the
    block — it stands in the opening, where no fold reaches. It stays the
    only one, in front of its own turn; a second copy would say the same
    thing twice."""
    provider = _chat_mit(client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=1))
    block = _langer_chat_mit_block(client, chat_id, block_pair=0)

    _senden(client, chat_id)

    assert provider.faltungen == 1
    assert provider.texte[0].count(block) == 1
    # The round sent again carries it once as well, and in front of the same
    # turn as before: the row it belongs to is still there.
    assert provider.texte[1].count(block) == 1
    nutzer = [n for n in provider.letzte_anfrage.nachrichten if n.role == "user"]
    assert nutzer[0].content.startswith(block)
    assert not nutzer[-1].content.startswith(block)


def test_a_request_without_a_fold_keeps_the_block_it_had(client, chat_id):
    """Silence test: nothing folded, nothing moved. The newest user turn goes
    out with its block and with nothing else in front of it — the very bytes
    it would have gone out with before."""
    provider = _chat_mit(client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=0))
    _langer_chat(client, chat_id)
    block = grundprompt.environment_block(client.app.state.config.app.timezone)

    _senden(client, chat_id)

    assert provider.faltungen == 0
    assert provider.texte[0].count(block) == 1
    assert provider.letzte_anfrage.nachrichten[-1].content == (
        f"{block}\n\nNewest question"
    )


class ZuLangInRundeZwei(ZuLangDannGut):
    """Answers the first request with text and a tool call, and calls the
    second one — the next tool round of the same answer — too long."""

    async def streamen(self, anfrage):
        if _ist_faltung(anfrage):
            self.faltungen += 1
            if self.faltung_scheitert:
                raise ProviderFehler("connection refused")
            yield Stueck("content", text="summary")
            return
        self.groessen.append(_groesse(anfrage))
        if len(self.groessen) == 1:
            yield Stueck("content", text="Looking. ")
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[Werkzeugaufruf(id="w1", name="no_such_tool", argumente={})],
            )
            return
        raise _zu_lang()


def test_chat_zu_lang_erst_in_einer_spaeteren_runde_wird_auch_gefaltet(client, chat_id):
    """A later tool round gets the same cure as the first one — a fold
    in memory, rather than the card at once.

    Here the window a refusal just taught (256) leaves no room to write a
    summary in, so no model is asked and nothing is folded — and without a
    fold the card comes. The rows are untouched either way — a round's tool
    calls are not rows, and nothing is written down mid-answer."""
    # The one chat test about the LEARNING itself, so its window is left
    # free to be taught.
    provider = _chat_mit(
        client, ZuLangInRundeZwei(mock_endpunkt("test"), zu_lang=0), eingetragen=False
    )
    _langer_chat(client, chat_id)

    _senden(client, chat_id)

    # No summary was asked for: with a 256-token window there is no room to
    # write one, so nothing was folded.
    assert provider.faltungen == 0
    # Two requests: the first round and the refused second one. Nothing was
    # folded, so nothing is sent again.
    assert len(provider.groessen) == 2
    antwort = _antwort(client, chat_id)
    assert antwort["content"] == "Looking. "
    assert antwort["stats"]["kontextfenster_voll"] is True
    # Nothing of this was written down: the fold happened in the request only.
    assert not _verdichtungen(client, chat_id)
    # This later-round recognition learns too, the same as the first
    # round's (app/api/v1/generierung.py ~2066, the chat-side counterpart
    # of a job's later tool round).
    zustand = client.app.state.discovery.zustaende["test"]
    assert zustand.context_tokens == 256
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_GELERNT


def test_chat_scheitert_die_faltung_im_speicher_eine_anfrage_dann_die_karte(
    client, chat_id, monkeypatch
):
    """A dead fold server, a later tool round folding in memory: one summary
    request, nothing folded, no further step — it would sit inside the pause
    and only count an attempt — and the refused round ends the answer in the
    card."""
    provider = _chat_mit(
        client, ZuLangInRundeZwei(mock_endpunkt("test"), zu_lang=0, faltung_scheitert=True)
    )
    _langer_chat(client, chat_id)
    schritte = _faltschritte(monkeypatch, lambda: len(provider.groessen))

    _senden(client, chat_id)

    assert schritte == [(2, True)]
    assert provider.faltungen == 1
    assert len(provider.groessen) == 2
    assert faltpause.pausiert(chat_id)
    assert not _verdichtungen(client, chat_id)
    assert _antwort(client, chat_id)["stats"]["kontextfenster_voll"] is True


class ZuLangNurInRundeZwei(ZuLangDannGut):
    """Answers the first request with a tool call, calls the second one — the
    next tool round — too long ONCE, and answers the round sent again after
    the fold."""

    async def streamen(self, anfrage):
        if _ist_faltung(anfrage):
            self.faltungen += 1
            yield Stueck("content", text="summary")
            return
        self.groessen.append(_groesse(anfrage))
        self.texte.append("\n".join(n.content or "" for n in anfrage.nachrichten))
        if len(self.groessen) == 1:
            yield Stueck("content", text="Looking. ")
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[Werkzeugaufruf(id="w1", name="no_such_tool", argumente={})],
            )
            return
        if len(self.groessen) == 2:
            raise _zu_lang()
        yield Stueck("content", text="Done.")


def test_chat_faltet_im_speicher_und_nennt_das_verdraengte_dokument(client, chat_id):
    """A later tool round folds the request in memory, and the stretch it
    replaces carried a document: the request sent again says so with the
    note the fold of a chat's rows writes — the document does not leave
    without a word."""
    repositories = client.app.state.repositories
    provider = _chat_mit(client, ZuLangNurInRundeZwei(mock_endpunkt("test"), zu_lang=0))
    repositories.messages.speichern(chat_id=chat_id, role="user", content="question start")
    repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="answer start", zustand="fertig"
    )
    dokument = repositories.documents.speichern(
        chat_id=chat_id, filename="lagerliste.txt", extracted_text="L" * 3_000
    )
    repositories.messages.speichern(
        chat_id=chat_id, role="user", content="read this", dokumente=[dokument.id]
    )
    repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="read it", zustand="fertig"
    )
    _langer_chat(client, chat_id)

    _senden(client, chat_id)

    assert provider.faltungen == 1
    assert len(provider.texte) == 3
    assert "Documents attached in the stretch summarized above" not in provider.texte[1]
    nachher = provider.texte[2]
    assert "Documents attached in the stretch summarized above" in nachher
    assert '"lagerliste.txt" (3000 characters)' in nachher
    # Nothing was written down mid-answer: the rows are untouched.
    assert not _verdichtungen(client, chat_id)


def test_chat_ein_fremder_400er_wird_nicht_gefaltet(client, chat_id):
    provider = _chat_mit(
        client, MockProvider(mock_endpunkt("test"), fehler='400: {"error":{"message":"invalid_api_key"}}')
    )
    _langer_chat(client, chat_id)

    _senden(client, chat_id)

    assert provider.durchlaeufe == 1
    stats = _antwort(client, chat_id)["stats"]
    assert "invalid_api_key" in stats["fehler"]
    assert "kontextfenster_voll" not in stats


# --- Job ---------------------------------------------------------------------


class ZuLangImAuftrag(MockProvider):
    """``aufbau`` rounds of text and a tool call — enough history for three
    folds — then the next round is refused as too long ``zu_lang`` times
    before it answers."""

    def __init__(
        self,
        *args,
        zu_lang: int,
        aufbau: int = 8,
        text_laenge: int = 300,
        faltung_scheitert: bool = False,
        beim_falten=None,
        rohtext: str | list[str] = LLAMA,
        danach_werkzeug: bool = False,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.zu_lang = zu_lang
        self.rohtext = rohtext
        self.aufbau = aufbau
        self.text_laenge = text_laenge
        self.faltung_scheitert = faltung_scheitert
        self.beim_falten = beim_falten
        # The round that gets through asks for one more tool, so a later
        # round's request can be looked at too.
        self.danach_werkzeug = danach_werkzeug
        self.runden = 0
        self.faltungen = 0
        self.groessen: list[int] = []
        # The answer ceiling of every answer request, the build-up rounds too.
        self.grenzen: list[int | None] = []

    def _werkzeug(self):
        return Stueck(
            "tool_call",
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id=f"w{self.runden}", name="addieren", argumente={"a": self.runden, "b": 1}
                )
            ],
        )

    async def streamen(self, anfrage):
        if _ist_faltung(anfrage):
            self.faltungen += 1
            if self.beim_falten:
                self.beim_falten()
            if self.faltung_scheitert:
                raise ProviderFehler("connection refused")
            yield Stueck("content", text="summary")
            return
        self.runden += 1
        self.grenzen.append(anfrage.max_tokens)
        if self.runden <= self.aufbau:
            yield Stueck("content", text="y" * self.text_laenge)
            yield self._werkzeug()
            return
        if self.groessen and len(self.groessen) > self.zu_lang:
            # Past the round that got through: the run ends here.
            yield Stueck("content", text="done")
            return
        self.groessen.append(_groesse(anfrage))
        if len(self.groessen) <= self.zu_lang:
            raise _zu_lang(_ablehnung(self.rohtext, len(self.groessen)))
        if self.danach_werkzeug:
            yield self._werkzeug()
            return
        yield Stueck("content", text="done")


def _auftrag(
    client,
    config,
    provider,
    context_tokens: int | None = 2_500,
    eingetragen: bool = True,
    context_tokens_setzen: bool = True,
    anthropic: bool = False,
) -> dict:
    agent_schreiben(config, kopf="model: test\nmax_rounds: 20")
    provider_setzen(client, provider)
    if anthropic:
        _anthropic_draht(client)
    zustand = client.app.state.discovery.zustaende["test"]
    # A fixed test size, not a real discovery answer — marked "eingetragen"
    # so a "too long" refusal's own (unrelated) numbers cannot teach a
    # different window mid-run (app/fenstergroesse.py) and shift the fold
    # budget out from under the test.
    #
    # Big enough to hold this run's own prompt: a window UNDER it leaves no
    # room for an answer, and the round is folded before it is ever sent
    # (app/antwortgrenze.py, `reicht_nicht`) — which no real server ever
    # asks for, and which would put every test in this file on that one
    # path. Small enough all the same that the verbatim tail does not cover
    # the whole short history of a job, or there would be nothing to fold. A test of that very learning sets
    # ``eingetragen=False``; one of real discovery's own fallback sets
    # ``context_tokens_setzen=False`` too, to leave what it already resolved
    # (app/fenstergroesse.py) standing instead of overwriting it here.
    if context_tokens_setzen:
        zustand.context_tokens = context_tokens
    if eingetragen:
        zustand.kontext_quelle = fenstergroesse.QUELLE_EINGETRAGEN
    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Go"}
    ).json()["id"]
    return auf_ende_warten(client, kennung)


def _status(daten: dict) -> list[str]:
    return [s["inhalt"] for s in daten["schritte"] if s["typ"] == "status"]


def test_auftrag_faltet_mit_dem_ersatzwert_eines_unbekannten_modells(config, client):
    """A job on an endpoint whose window nobody could read gets the
    fallback (app/fenstergroesse.py, 128,000) from real discovery, and
    folds in place on it — where it used to never fold at all."""
    provider = UeberDerVerdichtungsschwelle(
        mock_endpunkt("test"), zusammenfassung="gerafft", tokens=2_000,
    )
    client.app.state.repositories.einstellungen.setzen("global", "verdichtung_schwelle", 1)

    daten = _auftrag(client, config, provider, context_tokens_setzen=False, eingetragen=False)

    zustand = client.app.state.discovery.zustaende["test"]
    assert zustand.context_tokens == fenstergroesse.ERSATZ
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_ERSATZ
    assert daten["state"] == "fertig"
    status_schritte = [s["inhalt"] for s in daten["schritte"] if s["typ"] == "status"]
    assert "Compacted the history to keep the context from filling up." in status_schritte


def test_auftrag_einmal_zu_lang_faltet_und_wiederholt_die_runde(config, client):
    provider = ZuLangImAuftrag(mock_endpunkt("test"), zu_lang=1)

    daten = _auftrag(client, config, provider)

    assert daten["state"] == "fertig"
    assert provider.faltungen == 1
    assert len(provider.groessen) == 2
    assert provider.groessen[1] < provider.groessen[0]
    # The first step's tail budget covers this short history whole, so it
    # folds nothing and moves straight on to the next, smaller one without
    # resending — the step the file's own test for that describes. One
    # refusal, one summary, one round sent again.
    assert [s for s in _status(daten) if "attempt 2/3" in s]
    # Silence test: a fold that went through reports no failure.
    assert not [s for s in _status(daten) if "fold failed" in s]


def test_auftrag_viermal_zu_lang_endet_nach_drei_faltungen_mit_kontext_voll(config, client):
    provider = ZuLangImAuftrag(mock_endpunkt("test"), zu_lang=4)

    daten = _auftrag(client, config, provider)

    assert daten["end_reason"] == "kontext_voll"
    # Three attempts all told, and the first is spent on a tail budget that
    # covers this short history whole: it folds nothing and steps down to
    # the next, smaller budget without resending. So two summaries, three
    # rounds — and then the card, which is what this test is about.
    assert provider.faltungen == 2
    assert len(provider.groessen) == 3
    assert len(set(provider.groessen)) == 3
    assert provider.groessen == sorted(provider.groessen, reverse=True)
    assert len([s for s in _status(daten) if "compacted the history" in s]) == 2


def test_auftrag_lernt_wenn_die_faltung_aufgibt(config, client):
    """Exhausting the fold attempts re-raises the same refusal up to
    the run's own outer handler (app/api/v1/auftraege.py, the one shared
    with a later tool round) — which learns from it too, the same as the
    round-retry loop's own recognition."""
    provider = ZuLangImAuftrag(mock_endpunkt("test"), zu_lang=4)

    # Real discovery's own fallback stands as the window: a reachable
    # endpoint always has one (app/fenstergroesse.py), and the request's own
    # ceiling is measured against it now.
    daten = _auftrag(
        client, config, provider, context_tokens_setzen=False, eingetragen=False
    )

    assert daten["end_reason"] == "kontext_voll"
    zustand = client.app.state.discovery.zustaende["test"]
    assert zustand.context_tokens == 256
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_GELERNT


def test_auftrag_scheitert_die_faltung_eine_anfrage_dann_kontext_voll(
    config, client, monkeypatch
):
    """A dead fold server, the refusal path: the summary is asked for once,
    nothing is folded, the status line says so once, no further step follows
    in that round, and the run ends as context-full.

    The window is raised with the history so the round still leaves room for
    an answer and this test stays on the refusal path it is about."""
    provider = ZuLangImAuftrag(
        mock_endpunkt("test"), zu_lang=4, faltung_scheitert=True, text_laenge=7_000
    )
    schritte = _faltschritte(monkeypatch, lambda: provider.runden)

    daten = _auftrag(client, config, provider, context_tokens=25_000)

    assert daten["end_reason"] == "kontext_voll"
    assert provider.faltungen == 1
    assert len(provider.groessen) == 1
    assert list(_schritte_mit_mitte_je_runde(schritte).values()) == [1]
    status = _status(daten)
    assert not [s for s in status if "compacted the history" in s]
    assert status.count("fold failed — the history stays unfolded") == 1


def test_auftrag_scheitert_die_faltung_vor_dem_senden_eine_anfrage_dann_kontext_voll(
    config, client, monkeypatch
):
    """A dead fold server, the check before sending: a round whose input
    leaves no room for an answer asks for the summary once, folds nothing,
    says so once, and goes out with the smallest ceiling there is — every
    round after it too, inside the pause, with one step that asks nothing —
    and the refusal ends the run as context-full."""
    provider = ZuLangImAuftrag(
        mock_endpunkt("test"), zu_lang=1, faltung_scheitert=True, text_laenge=1_500
    )
    schritte = _faltschritte(monkeypatch, lambda: provider.runden)

    daten = _auftrag(client, config, provider, anthropic=True)

    assert daten["end_reason"] == "kontext_voll"
    assert provider.faltungen == 1
    assert 1 in provider.grenzen
    je_runde = _schritte_mit_mitte_je_runde(schritte)
    assert len(je_runde) > 1
    assert set(je_runde.values()) == {1}
    status = _status(daten)
    assert not [s for s in status if "compacted the history" in s]
    assert status.count("fold failed — the history stays unfolded") == 1


def test_auftrag_zwei_fehlschlaege_vor_dem_senden_schliessen_die_sperre_mit_hinweis(
    config, client, monkeypatch
):
    """Two failed folds in a row on the check before sending — with no pause
    between the rounds, so the second round asks the model again — switch
    automatic folding off, and the run says so exactly once. After
    that the round-end path never runs again, so this is the only place the
    notice can stand."""
    monkeypatch.setitem(faltpause.PAUSEN, faltpause.LANG, 0.0)
    provider = ZuLangImAuftrag(
        mock_endpunkt("test"), zu_lang=1, faltung_scheitert=True, text_laenge=1_500
    )

    daten = _auftrag(client, config, provider, anthropic=True)

    assert provider.faltungen >= 2
    status = _status(daten)
    assert status.count("fold failed — the history stays unfolded") == provider.faltungen
    assert status.count("automatic folding stopped for this run") == 1


def test_auftrag_ohne_platz_fuer_die_zusammenfassung_ein_schritt_und_keine_zeile(
    config, client, monkeypatch
):
    """A window that leaves a summary request no room: no model is asked,
    nothing is booked, the status never says a fold failed — and each round
    takes ONE step, not all three: a smaller one would find the same no
    room."""
    provider = ZuLangImAuftrag(mock_endpunkt("test"), zu_lang=0, text_laenge=1_500)
    schritte = _faltschritte(monkeypatch, lambda: provider.runden)

    daten = _auftrag(client, config, provider, context_tokens=2_000, anthropic=True)

    assert daten["state"] == "fertig"
    assert provider.faltungen == 0
    assert faltpause.pausiert(daten["id"]) is False
    je_runde = _schritte_mit_mitte_je_runde(schritte)
    assert len(je_runde) > 1
    assert set(je_runde.values()) == {1}
    assert not [s for s in _status(daten) if "fold failed" in s]


class ZuLangOhneErsparnis(ZuLangImAuftrag):
    """Answers every summary request with a text longer than the whole
    history: the model answers, and the fold saves nothing."""

    async def streamen(self, anfrage):
        if _ist_faltung(anfrage):
            self.faltungen += 1
            yield Stueck("content", text="s" * 1_000_000)
            return
        async for stueck in super().streamen(anfrage):
            yield stueck


def test_auftrag_ohne_ersparnis_fragt_in_derselben_runde_nicht_noch_einmal(
    config, client, monkeypatch
):
    """A summary that saved nothing ends the round's folding: a smaller step
    would ask the model about the same history again and get the same
    nothing back. One summary request, and the refusal ends the run."""
    provider = ZuLangOhneErsparnis(mock_endpunkt("test"), zu_lang=4)
    schritte = _faltschritte(monkeypatch, lambda: provider.runden)

    daten = _auftrag(client, config, provider)

    assert daten["end_reason"] == "kontext_voll"
    assert provider.faltungen == 1
    assert list(_schritte_mit_mitte_je_runde(schritte).values()) == [1]


def test_auftrag_scheitert_die_faltung_am_rundenende_laeuft_der_lauf_weiter(config, client):
    """The round-end fold of a run past its threshold, with a summary that
    comes back empty: one request, nothing folded, the status line says so,
    and the run finishes."""
    provider = UeberDerVerdichtungsschwelle(
        mock_endpunkt("test"), zusammenfassung="", tokens=60_000
    )

    daten = _auftrag(client, config, provider, context_tokens=70_000)

    assert daten["state"] == "fertig"
    faltungen = [
        a for a in provider.alle_anfragen
        if a.nachrichten[-1].content == verdichtung.ANFRAGE_TEXT
    ]
    assert len(faltungen) == 1
    status = _status(daten)
    assert status.count("fold failed — the history stays unfolded") == 1
    assert "Compacted the history to keep the context from filling up." not in status


def test_auftrag_findet_die_erste_stufe_keine_mitte_faltet_eine_kleinere(config, client):
    """Three rounds of 1,000 characters against a 4,000-character first
    tail: nothing to fold there, and nothing is resent for it. A smaller
    step has a middle — one summary, one resend, and the run ends normally."""
    provider = ZuLangImAuftrag(mock_endpunkt("test"), zu_lang=1, aufbau=3, text_laenge=1000)

    daten = _auftrag(client, config, provider, context_tokens=2500)

    assert daten["state"] == "fertig"
    assert provider.faltungen == 1
    assert len(provider.groessen) == 2
    assert provider.groessen[1] < provider.groessen[0]
    status = _status(daten)
    assert not [s for s in status if "attempt 1/3" in s]
    assert [s for s in status if "attempt 2/3" in s or "attempt 3/3" in s]


def test_auftrag_stopp_waehrend_der_faltung_schickt_nicht_neu(config, client):
    generierungen = client.app.state.generierungen

    def stoppen():
        for lauf in generierungen.laufende():
            generierungen.abbrechen(lauf.id)

    provider = ZuLangImAuftrag(mock_endpunkt("test"), zu_lang=4, beim_falten=stoppen)

    daten = _auftrag(client, config, provider)

    assert daten["state"] == "abgebrochen"
    assert provider.faltungen == 1
    assert len(provider.groessen) == 1


def test_auftrag_ohne_zu_lang_faltet_nichts(config, client):
    provider = ZuLangImAuftrag(mock_endpunkt("test"), zu_lang=0)

    daten = _auftrag(client, config, provider)

    assert daten["state"] == "fertig"
    assert provider.faltungen == 0
    assert len(provider.groessen) == 1


# --- Fold, lower the ceiling, or the card ----------------------------------

# vLLM, current (vllm/renderers/params.py, _token_len_check): the requested
# completion counts into the limit, and the input is an exact count.
VLLM_ANTWORT_FUELLT = (
    '{"object":"error","message":"This model\'s maximum context length is 8192 tokens. '
    "However, you requested 8192 output tokens and your prompt contains 1200 input tokens, "
    'for a total of 9392 tokens. Please reduce the length of the input prompt or the number '
    'of requested output tokens.","type":"BadRequestError","code":400}'
)
VLLM_EINGABE_ZU_LANG = (
    '{"object":"error","message":"This model\'s maximum context length is 8192 tokens. '
    "However, you requested 1024 output tokens and your prompt contains 8000 input tokens, "
    'for a total of 9024 tokens. Please reduce the length of the input prompt or the number '
    'of requested output tokens.","type":"BadRequestError","code":400}'
)
# The same check where vLLM cut the prompt short while counting: the input
# is a floor, not a count.
VLLM_MINDESTENS = (
    '{"object":"error","message":"This model\'s maximum context length is 8192 tokens. '
    "However, you requested 8192 output tokens and your prompt contains at least 1 input "
    'tokens, for a total of at least 8193 tokens. Please reduce the length of the input '
    'prompt or the number of requested output tokens.","type":"BadRequestError","code":400}'
)
# vLLM 0.10 to 0.12 (vllm/entrypoints/openai/serving_engine.py, _validate_input).
VLLM_ZU_GROSS = (
    '{"object":"error","message":"\'max_tokens\' or \'max_completion_tokens\' is too large: '
    "8192. This model's maximum context length is 8192 tokens and your request has 1200 "
    'input tokens (8192 > 8192 - 1200).","type":"BadRequestError","param":null,"code":400}'
)
# The same, with an input that leaves nothing free for an answer.
VLLM_KEIN_PLATZ = VLLM_ZU_GROSS.replace("1200", "8150")
# vLLM up to 0.8 and the older OpenAI-format split of the same total.
ALT_ANTWORT_FUELLT = (
    '{"error":{"message":"This model\'s maximum context length is 4097 tokens. However, you '
    "requested 8297 tokens (200 in the messages, 8097 in the completion). Please reduce the "
    'length of the messages or completion.","code":"context_length_exceeded"}}'
)
# OpenRouter's split of the input into text and tools.
OPENROUTER = (
    '{"error":{"message":"This endpoint\'s maximum context length is 200000 tokens. However, '
    "you requested about 395000 tokens (150000 of text input, 40000 of tool input, 205000 in "
    'the output). Please reduce the length of either one.","code":400}}'
)
# The quoted sum alone, with an input past the window (Anthropic's wording,
# read by the second pattern of ``_GENANNTER_DECKEL``).
ANTHROPIC_SUMME_UEBER_FENSTER = (
    '{"type":"error","error":{"type":"invalid_request_error","message":'
    '"input length and max_tokens exceed context limit: 250000 + 8192 > 200000"}}'
)
# vLLM's newer check where the ceiling fills the window and the input alone
# is past it as well.
VLLM_EINGABE_UEBER_FENSTER = (
    '{"object":"error","message":"This model\'s maximum context length is 32768 tokens. '
    "However, you requested 32768 output tokens and your prompt contains 40000 input tokens, "
    'for a total of 72768 tokens. Please reduce the length of the input prompt or the number '
    'of requested output tokens.","type":"BadRequestError","code":400}'
)
# Recognized, but with no numbers to read.
OHNE_ZAHLEN ='{"error":{"message":"Request has too many tokens for this model"}}'


def _fehler(rohtext: str) -> ProviderFehler:
    return _zu_lang(rohtext)


@pytest.mark.parametrize(
    ("rohtext", "erwartet"),
    [
        # The answer's ceiling alone reaches the window: the window less the
        # input less 64 for this one request.
        (VLLM_ANTWORT_FUELLT, (kontextvoll.GRENZE, 8192 - 1200 - 64)),
        (VLLM_ZU_GROSS, (kontextvoll.GRENZE, 8192 - 1200 - 64)),
        (ALT_ANTWORT_FUELLT, (kontextvoll.GRENZE, 4097 - 200 - 64)),
        (OPENROUTER, (kontextvoll.GRENZE, 200000 - 150000 - 40000 - 64)),
        # Nothing left free for an answer.
        (VLLM_KEIN_PLATZ, (kontextvoll.KARTE, None)),
        (VLLM_ZU_GROSS.replace("1200", "8128"), (kontextvoll.KARTE, None)),
        (VLLM_ZU_GROSS.replace("1200", "8127"), (kontextvoll.GRENZE, 1)),
        # The numbers name an input past the window itself: only a fold helps.
        (ANTHROPIC_SUMME_UEBER_FENSTER, (kontextvoll.FALTEN, None)),
        (VLLM_EINGABE_UEBER_FENSTER, (kontextvoll.FALTEN, None)),
        # The input just inside the window still ends with the card or a
        # lowered ceiling.
        (ANTHROPIC_SUMME_UEBER_FENSTER.replace("250000", "195000"),
         (kontextvoll.GRENZE, 200000 - 195000 - 64)),
        (VLLM_EINGABE_UEBER_FENSTER.replace("40000", "32768"), (kontextvoll.KARTE, None)),
        # The answer's share is below the window: the input is what did not fit.
        (VLLM_EINGABE_ZU_LANG, (kontextvoll.FALTEN, None)),
        (VLLM_ZU_GROSS.replace("too large: 8192", "too large: 1024"), (kontextvoll.FALTEN, None)),
        (ALT_ANTWORT_FUELLT.replace("8097 in the completion", "1000 in the completion"),
         (kontextvoll.FALTEN, None)),
        (OPENROUTER.replace("205000 in the output", "5000 in the output"),
         (kontextvoll.FALTEN, None)),
        # A floor is not a count: read as no numbers.
        (VLLM_MINDESTENS, (kontextvoll.FALTEN, None)),
        # The prompt alone measured against the window.
        (LLAMA, (kontextvoll.FALTEN, None)),
        (ANTHROPIC, (kontextvoll.FALTEN, None)),
        (OMLX, (kontextvoll.FALTEN, None)),
        (OPENAI, (kontextvoll.FALTEN, None)),
        # No numbers at all: folded, nothing guessed.
        (OHNE_ZAHLEN, (kontextvoll.FALTEN, None)),
    ],
)
def test_abhilfe(rohtext, erwartet):
    assert kontextvoll.bei_fehler(_fehler(rohtext))
    assert kontextvoll.abhilfe(_fehler(rohtext)) == erwartet


VLLM_ENGINE_PROMPT = (
    '{"error":{"message":"The engine prompt length 40000 exceeds the max_model_len 32768. '
    'Please reduce prompt.","type":"invalid_request_error","param":"input","code":400}}'
)
VLLM_DECODER_PLUS_OUTPUT = (
    '{"object":"error","message":"The decoder prompt (length 8192) plus the number of '
    'requested output tokens (at least 1) is longer than the maximum model length of '
    '8192.","type":"BadRequestError","code":400}'
)


VLLM_ENCODER_PROMPT = (
    '{"object":"error","message":"The encoder prompt (length 5000) is longer than '
    'the maximum model length of 4096.","type":"BadRequestError","code":400}'
)
# Another refusal that mentions a prompt length without naming a full
# context: it must stay an ordinary error.
FOREIGN_PROMPT_LENGTH = (
    '{"error":{"message":"Invalid value for prompt length: must be a positive '
    'integer","type":"invalid_request_error"}}'
)


def test_a_foreign_prompt_length_refusal_is_not_a_full_context():
    assert not kontextvoll.ist_kontext_voll(400, FOREIGN_PROMPT_LENGTH)


@pytest.mark.parametrize(
    "rohtext", [VLLM_ENGINE_PROMPT, VLLM_MAXIMUM_MODEL_LENGTH, VLLM_ENCODER_PROMPT]
)
def test_vllm_input_named_folds_despite_a_set_length_filling_the_window(rohtext):
    """Both vLLM wordings name the PROMPT as what did not fit: a set answer
    length as large as the whole window does not turn them into the card."""
    error = _fehler(rohtext)

    assert kontextvoll.abhilfe(
        error, eingestellte_grenze=32_768, fenster=32_768
    ) == (kontextvoll.FALTEN, None)


def test_vllm_engine_wording_folds_and_still_reads_its_window():
    """The window read from the engine wording is still 32768 — the fold is
    decided by the words, not by a number that could not be read."""
    error = _fehler(VLLM_ENGINE_PROMPT)

    assert kontextvoll.grenze_aus_fehler(error) == 32768
    assert kontextvoll.abhilfe(
        error, eingestellte_grenze=65_536, fenster=200_000
    ) == (kontextvoll.FALTEN, None)


def test_vllm_decoder_form_with_output_is_left_to_the_numbers():
    """The second form of vLLM's prompt check names the requested output
    beside the prompt: it is left to the numbers, so a set length filling
    the window still ends at once."""
    error = _fehler(VLLM_DECODER_PLUS_OUTPUT)

    assert kontextvoll.ist_kontext_voll(400, VLLM_DECODER_PLUS_OUTPUT)
    assert kontextvoll.abhilfe(
        error, eingestellte_grenze=8192, fenster=8192
    ) == (kontextvoll.LIMIT_TOO_LARGE, None)


def _cut_like_the_provider(rohtext: str) -> ProviderFehler:
    """The error as the OpenAI-compatible provider builds it: the sentence
    carries only the first 400 characters of the body."""
    return ProviderFehler(
        f"provider answered with 400: {rohtext[:400]}", status=400, rohtext=rohtext
    )


def test_a_stated_output_limit_cut_off_in_the_sentence_is_read_from_the_body():
    tail = "exceeds model's maximum output tokens (8192)"
    rohtext = "x" * (400 - len(tail) + 2) + tail
    assert _cut_like_the_provider(rohtext).args[0].endswith("(819")

    assert kontextvoll.hersteller_deckel_aus_fehler(_cut_like_the_provider(rohtext)) == 8192


def test_numbers_cut_off_in_the_sentence_are_read_from_the_body():
    tail = "max_tokens: 8192 > context_window: 200000 - input_tokens: 195000"
    rohtext = "x" * (400 - len(tail) + 2) + tail
    fehler = _cut_like_the_provider(rohtext)
    assert fehler.args[0].endswith("input_tokens: 1950")

    assert kontextvoll.abhilfe(fehler) == kontextvoll.abhilfe(_fehler(tail))


def test_max_model_len_with_a_set_length_past_the_window_is_too_large():
    """vLLM's "cannot be greater than max_model_len" names the window and
    nothing else. A set answer length past it cannot be folded into room:
    the round ends at once, whatever window the endpoint resolved."""
    error = _fehler(VLLM_MAX_MODEL_LEN)

    assert kontextvoll.grenze_aus_fehler(error) == 8192
    assert kontextvoll.abhilfe(
        error, eingestellte_grenze=16_384, fenster=200_000
    ) == (kontextvoll.LIMIT_TOO_LARGE, None)


@pytest.mark.parametrize(
    ("rohtext", "grenze", "fenster"),
    [
        # oMLX: "Prompt too long: 300000 tokens exceeds max context window
        # of 262144 tokens".
        (OMLX, 262_144, 262_144),
        # llama.cpp: "request (755 tokens) exceeds the available context
        # size (256 tokens), try increasing it".
        (LLAMA, 1_000, 256),
        # OpenAI, older: "However, your messages resulted in 4239 tokens.
        # Please reduce the length of the messages."
        (OPENAI, 4096, 4096),
        # The same family without a number beside it.
        (EINGABE_ZU_LANG, 8192, 8192),
    ],
)
def test_a_refusal_that_names_the_input_folds(rohtext, grenze, fenster):
    """Refusals whose own words name the INPUT fold, whatever answer length
    somebody set: what did not fit is the input, and the card would send the
    user to a setting that was never the cause.

    Every case carries an answer length as large as the window its refusal
    names — the shape in which the answer-length card came before. The first
    was measured live against a running server: that refusal showed
    ``nachricht.antwortlaenge_zu_gross`` (``app/locales/de.json``) over a
    chat whose prompt was what overran.

    Recognized first, answered second: a wording the callers never take for
    a full context is never handed to ``abhilfe`` at all, so each of these
    has to pass ``bei_fehler`` — the gate both round loops ask before they
    fold (``app/ablehnungslernen.py``).
    """
    error = _fehler(rohtext)

    assert kontextvoll.bei_fehler(error)
    assert kontextvoll.abhilfe(
        error, eingestellte_grenze=grenze, fenster=fenster
    ) == (kontextvoll.FALTEN, None)


def test_a_refusal_that_names_the_input_folds_beside_a_ceiling():
    """The words are asked before the numbers, so a refusal that names the
    input folds before any number is read. Here the quoted sum
    (250000 + 8192 > 200000) counts an input past the window as well, which
    folds on its own too (``_senken``) — both readings point at the same
    cure. Composed of the two Anthropic wordings the module documents.
    """
    error = _fehler(ANTHROPIC_ZWEI_SAETZE)

    # Read as numbers alone, the quoted sum is (window, input, answer) with
    # the input past the window — the reading that folds as well.
    assert kontextvoll._zahlen(error, kontextvoll._GENANNTER_DECKEL) == (
        200_000,
        250_000,
        8192,
    )
    assert kontextvoll.abhilfe(
        error, eingestellte_grenze=250_000, fenster=200_000
    ) == (kontextvoll.FALTEN, None)


def test_jedes_eingabe_muster_steht_in_einem_gemessenen_satz():
    """No wording in the input list without a refusal that carries it: a
    pattern nothing matches is a rule that never runs, and the list decides
    both whether a refusal is recognized and how it is answered."""
    saetze = " ".join(
        [
            LLAMA, ANTHROPIC, OPENAI, OMLX, EINGABE_ZU_LANG,
            VLLM_ENGINE_PROMPT, VLLM_MAXIMUM_MODEL_LENGTH,
        ]
    ).lower()

    tot = [
        muster.pattern
        for muster in kontextvoll._EINGABE_GENANNT
        if muster.search(saetze) is None
    ]

    assert tot == []


def test_die_gesenkte_grenze_steht_auf_einer_kopie():
    from app.providers import Generierungsanfrage

    zustand = SimpleNamespace(
        endpunkt=SimpleNamespace(
            capabilities=SimpleNamespace(thinking=None),
            parameter_dialect="openai",
            base_url="http://127.0.0.1:9/v1",
            modell=None,
        ),
        gemeldeter_name=None,
        faehigkeiten_erkannt={},
    )
    anfrage = Generierungsanfrage(nachrichten=[], max_tokens=8192)
    assert kontextvoll.mit_grenze(anfrage, None, zustand) is anfrage
    kopie = kontextvoll.mit_grenze(anfrage, 100, zustand)
    assert kopie.max_tokens == 100
    assert anfrage.max_tokens == 8192
    assert kopie.nachrichten is anfrage.nachrichten


def _verdichtungen(client, chat_id: str) -> list:
    return [
        z for z in client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]
        if z.get("art") == "verdichtung"
    ]


def test_chat_antwortgrenze_fuellt_das_fenster_die_grenze_sinkt_statt_zu_falten(client, chat_id):
    """The refusal's numbers show the ceiling alone reaching the window: the
    same request goes once more with a lower ceiling, nothing is folded, and
    the answer comes."""
    provider = _chat_mit(
        client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=1, rohtext=VLLM_ZU_GROSS)
    )
    _langer_chat(client, chat_id)

    ereignisse = _senden(client, chat_id, max_tokens=8192)

    assert provider.faltungen == 0
    assert provider.grenzen == [8192, 8192 - 1200 - 64]
    # The same request, only the ceiling lowered.
    assert provider.groessen[0] == provider.groessen[1]
    assert "".join(e.get("text", "") for e in ereignisse if e["typ"] == "content") == "Hallo Welt"
    assert not _verdichtungen(client, chat_id)
    stats = _antwort(client, chat_id)["stats"]
    assert "kontextfenster_voll" not in stats
    assert "fehler" not in stats


def test_chat_kein_platz_fuer_eine_antwort_die_karte(client, chat_id):
    provider = _chat_mit(
        client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=4, rohtext=VLLM_KEIN_PLATZ)
    )
    _langer_chat(client, chat_id)

    _senden(client, chat_id, max_tokens=8192)

    assert provider.faltungen == 0
    assert len(provider.groessen) == 1
    assert not _verdichtungen(client, chat_id)
    assert _antwort(client, chat_id)["stats"]["kontextfenster_voll"] is True


@pytest.mark.parametrize("rohtext", [ANTHROPIC_SUMME_UEBER_FENSTER, VLLM_EINGABE_UEBER_FENSTER])
def test_chat_faltet_wenn_die_zahlen_die_eingabe_ueber_dem_fenster_nennen(
    client, chat_id, rohtext
):
    """The refusal's numbers count an input larger than the window it names:
    no ceiling could make room, so the round folds once, sends again and is
    answered — no card."""
    provider = _chat_mit(client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=1, rohtext=rohtext))
    _langer_chat(client, chat_id)

    ereignisse = _senden(client, chat_id, max_tokens=8192)

    assert provider.faltungen == 1
    assert len(provider.groessen) == 2
    assert "".join(e.get("text", "") for e in ereignisse if e["typ"] == "content") == "Hallo Welt"
    assert len(_verdichtungen(client, chat_id)) == 1
    assert "kontextfenster_voll" not in _antwort(client, chat_id)["stats"]


class ZuLangDannWerkzeug(ZuLangDannGut):
    """Refuses the first request, answers the one sent again with a tool
    call, and the next tool round with text."""

    async def streamen(self, anfrage):
        self.groessen.append(_groesse(anfrage))
        self.grenzen.append(anfrage.max_tokens)
        if len(self.groessen) == 1:
            raise _zu_lang(_ablehnung(self.rohtext, len(self.groessen)))
        if len(self.groessen) == 2:
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[Werkzeugaufruf(id="w1", name="no_such_tool", argumente={})],
            )
            return
        yield Stueck("content", text="after the tool")


def test_chat_die_gesenkte_grenze_gilt_nur_fuer_die_erste_runde(client, chat_id):
    """The lowered ceiling never reaches the setting: the next tool round of
    the same answer asks with the ceiling the answer started with."""
    provider = _chat_mit(
        client, ZuLangDannWerkzeug(mock_endpunkt("test"), zu_lang=0, rohtext=VLLM_ZU_GROSS)
    )

    _senden(client, chat_id, max_tokens=8192)

    assert provider.grenzen == [8192, 8192 - 1200 - 64, 8192]
    assert _antwort(client, chat_id)["content"] == "after the tool"


def test_chat_grenze_und_faltung_teilen_sich_die_drei_versuche(client, chat_id):
    """A lower ceiling is one of the three attempts: after it, two folds are
    left, and the card comes when they do not help either. A fold frees
    room beside the input, and the lowered ceiling grows by it — here past
    the set length, so the sends after the folds carry the set length.

    The window is left wide on purpose: the refusals here are about the
    input, not about an answer length larger than the whole model — that
    case ends at once instead (``test_chat_eine_zu_grosse_eingestellte_laenge…``)."""
    provider = _chat_mit(
        client,
        ZuLangDannGut(
            mock_endpunkt("test"),
            zu_lang=4,
            rohtext=[VLLM_ZU_GROSS, OHNE_ZAHLEN, OHNE_ZAHLEN, OHNE_ZAHLEN],
        ),
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 200_000
    _langer_chat(client, chat_id)

    _senden(client, chat_id, max_tokens=8192)

    assert provider.faltungen == 2
    assert len(provider.groessen) == 4
    frei = 8192 - 1200 - 64
    assert provider.grenzen == [8192, frei, 8192, 8192]
    assert len(_verdichtungen(client, chat_id)) == 2
    assert _antwort(client, chat_id)["stats"]["kontextfenster_voll"] is True


def test_chat_faltet_wenn_die_eingabe_schuld_ist(client, chat_id):
    provider = _chat_mit(
        client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=1, rohtext=VLLM_EINGABE_ZU_LANG)
    )
    _langer_chat(client, chat_id)

    ereignisse = _senden(client, chat_id)

    assert provider.faltungen == 1
    assert len(provider.groessen) == 2
    assert "".join(e.get("text", "") for e in ereignisse if e["typ"] == "content") == "Hallo Welt"


def test_chat_ohne_zahlen_und_grenze_am_bekannten_fenster_endet_sofort(client, chat_id):
    """No numbers in the refusal, and the answer length somebody set is as
    large as the window this endpoint resolved: nothing is guessed — both
    numbers are known — and no fold can make room for an answer that fills
    the model on its own, so the round ends and says what to change."""
    provider = _chat_mit(
        client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=1, rohtext=OHNE_ZAHLEN)
    )
    # Window and ceiling are the same number, which is the whole point here:
    # the ceiling fills the window exactly. The number itself is this test's
    # own — large enough that the middle it folds can still have its summary
    # written inside the same window, which a window under the middle cannot
    # (app/chatverdichtung.py).
    fenster = 32_768
    client.app.state.discovery.zustaende["test"].context_tokens = fenster
    _langer_chat(client, chat_id)

    _senden(client, chat_id, max_tokens=fenster)

    # ONE summary — the ordinary threshold's, fired before the request went
    # out at all, because a ceiling that fills the whole window leaves the
    # history nothing. The refusal that follows is NOT answered
    # with another fold: the ceiling is what cannot fit.
    assert provider.faltungen == 1
    assert provider.grenzen == [fenster]
    assert _antwort(client, chat_id)["stats"]["antwortlaenge_zu_gross"] is True


def test_chat_eine_untergrenze_statt_einer_zahl_wird_gefaltet(client, chat_id):
    """A refusal that only says "at least Y input tokens" names no number
    this side can act on — so the history is folded. The set answer length
    has to stay well under the window for that: as large as the window, it
    is the answer length that cannot fit, and the round ends at once."""
    provider = _chat_mit(
        client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=1, rohtext=VLLM_MINDESTENS)
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 200_000
    _langer_chat(client, chat_id)

    _senden(client, chat_id, max_tokens=4_096)

    assert provider.faltungen == 1
    assert provider.grenzen == [4_096, 4_096]


def test_chat_eine_zu_grosse_eingestellte_laenge_endet_sofort(client, chat_id):
    """The answer length somebody set is as large as the model's whole
    window: no fold can make room for it, so the round stops at the first
    refusal and says what to change. Where a fold would have
    cost three summaries for nothing."""
    provider = _chat_mit(
        client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=4, rohtext=VLLM_MINDESTENS)
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 8_192
    _langer_chat(client, chat_id)

    _senden(client, chat_id, max_tokens=8_192)

    # One request, and after its refusal nothing more: no forced fold, no
    # lowered ceiling. (The one summary is the ordinary threshold's, fired
    # before the request went out — a ceiling that fills the window leaves
    # the history nothing.)
    assert len(provider.groessen) == 1
    assert provider.faltungen == 1
    stats = _antwort(client, chat_id)["stats"]
    assert stats["antwortlaenge_zu_gross"] is True
    assert stats.get("kontextfenster_voll") is not True


def test_chat_max_model_len_with_a_set_length_past_it_ends_at_once(client, chat_id):
    """vLLM refuses the set answer length with "cannot be greater than
    max_model_len": one request, no fold asked for, and the answer says the
    set length is too large. The endpoint's own window is left wide on
    purpose — the window that decides is the one the refusal names."""
    provider = _chat_mit(
        client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=4, rohtext=VLLM_MAX_MODEL_LEN)
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 200_000
    _langer_chat(client, chat_id)

    _senden(client, chat_id, max_tokens=16_384)

    assert len(provider.groessen) == 1
    assert provider.faltungen == 0
    stats = _antwort(client, chat_id)["stats"]
    assert stats["antwortlaenge_zu_gross"] is True
    assert stats.get("kontextfenster_voll") is not True


def test_chat_eine_kleinere_eingestellte_laenge_faltet_weiter(client, chat_id):
    """The silence probe: the same refusal with an answer length well under
    the window is an input problem, and the history is folded as before."""
    provider = _chat_mit(
        client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=1, rohtext=VLLM_MINDESTENS)
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 100_000
    _langer_chat(client, chat_id)

    _senden(client, chat_id, max_tokens=4_096)

    assert provider.faltungen == 1


def test_chat_ueber_der_lesegrenze_laesst_nach_der_faltung_nichts_heimlich_weg(client, chat_id):
    """Past the reading's cap of 500 rows the first request carries a gap
    notice where the oldest rows after the opening were left out. The fold
    brings the count back under the cap, and those rows come back: the
    request sent again carries them rather than dropping them without a
    word."""
    provider = _chat_mit(client, ZuLangDannGut(mock_endpunkt("test"), zu_lang=1))
    repositories = client.app.state.repositories
    for nr in range(260):
        repositories.messages.speichern(
            chat_id=chat_id, role="user", content=f"question {nr} " + "x" * 400
        )
        repositories.messages.speichern(
            chat_id=chat_id, role="assistant", content=f"answer {nr} " + "x" * 400,
            zustand="fertig",
        )

    ereignisse = _senden(client, chat_id)

    assert provider.faltungen == 1
    erste, zweite = provider.texte
    assert "not included here" in erste
    assert "answer 2 " not in erste
    assert "answer 2 " in zweite
    assert "Newest question" in zweite
    assert "".join(e.get("text", "") for e in ereignisse if e["typ"] == "content") == "Hallo Welt"


def test_auftrag_antwortgrenze_fuellt_das_fenster_die_grenze_sinkt_nur_fuer_die_runde(
    config, client
):
    """The round goes once more with a lower ceiling, nothing is folded, and
    the next round asks with the run's own ceiling again."""
    provider = ZuLangImAuftrag(
        mock_endpunkt("test"), zu_lang=1, rohtext=VLLM_ZU_GROSS, danach_werkzeug=True
    )

    daten = _auftrag(client, config, provider)

    assert daten["state"] == "fertig"
    assert provider.faltungen == 0
    frei = 8192 - 1200 - 64
    # Eight build-up rounds, the refused round, the round sent again, the
    # next one. Under "Auto" every one of those rounds works its ceiling out
    # against what it is actually sending, so they are NOT all the same
    # number — they shrink as the history grows. What this test is about is
    # the two at the end: the round sent again carries the ceiling the
    # refusal named, and the round after it is back on the run's own.
    assert len(provider.grenzen) == 11
    assert provider.grenzen[9] == frei
    assert provider.grenzen[10] != frei
    # Every other round carries NO number: Auto on the OpenAI wire leaves
    # the length to the server (app/antwortgrenze.py). Only the round sent
    # again after the refusal carries the one the refusal named.
    assert all(g is None for g in provider.grenzen[:9] + provider.grenzen[10:])
    status = _status(daten)
    assert [s for s in status if f"answer ceiling lowered to {frei} for this round (attempt 1/3)" in s]
    assert not [s for s in status if "compacted the history" in s]


def test_auftrag_eine_zu_grosse_eingestellte_laenge_endet_sofort(config, client):
    """A run whose agent head sets an answer length as large as the model's
    whole window: the first refusal ends it, with the reason that says what
    to change — no fold, no lowered ceiling."""
    agent_schreiben(config, kopf="model: test\nmax_rounds: 20\nmax_tokens: 2500")
    provider = ZuLangImAuftrag(mock_endpunkt("test"), zu_lang=4, rohtext=OHNE_ZAHLEN)
    provider_setzen(client, provider)
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = 2_500
    zustand.kontext_quelle = fenstergroesse.QUELLE_EINGETRAGEN

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Go"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["end_reason"] == "antwortlaenge_zu_gross"
    assert provider.faltungen == 0
    assert not [s for s in _status(daten) if "compacted the history" in s]


def test_job_max_model_len_with_a_set_length_past_it_ends_at_once(config, client):
    """The same refusal in a job: the first one ends the run with the
    reason that says what to change — no fold, no lowered ceiling."""
    agent_schreiben(config, kopf="model: test\nmax_rounds: 20\nmax_tokens: 16384")
    provider = ZuLangImAuftrag(mock_endpunkt("test"), zu_lang=4, rohtext=VLLM_MAX_MODEL_LEN)
    provider_setzen(client, provider)
    state = client.app.state.discovery.zustaende["test"]
    state.context_tokens = 200_000
    state.kontext_quelle = fenstergroesse.QUELLE_EINGETRAGEN

    job_id = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Go"}
    ).json()["id"]
    job = auf_ende_warten(client, job_id)

    assert job["end_reason"] == "antwortlaenge_zu_gross"
    assert provider.faltungen == 0
    assert len(provider.groessen) == 1
    lines = _status(job)
    assert not [s for s in lines if "compacted the history" in s or "ceiling lowered" in s]


def test_auftrag_kein_platz_fuer_eine_antwort_endet_mit_kontext_voll(config, client):
    provider = ZuLangImAuftrag(mock_endpunkt("test"), zu_lang=4, rohtext=VLLM_KEIN_PLATZ)

    daten = _auftrag(client, config, provider)

    assert daten["end_reason"] == "kontext_voll"
    assert provider.faltungen == 0
    assert len(provider.groessen) == 1
    status = _status(daten)
    assert not [s for s in status if "compacted the history" in s or "ceiling lowered" in s]


@pytest.mark.parametrize("rohtext", [ANTHROPIC_SUMME_UEBER_FENSTER, VLLM_EINGABE_UEBER_FENSTER])
def test_auftrag_faltet_wenn_die_zahlen_die_eingabe_ueber_dem_fenster_nennen(
    config, client, rohtext
):
    provider = ZuLangImAuftrag(mock_endpunkt("test"), zu_lang=1, rohtext=rohtext)

    daten = _auftrag(client, config, provider)

    assert daten["state"] == "fertig"
    assert provider.faltungen == 1
    assert [s for s in _status(daten) if "compacted the history" in s]


def test_auftrag_faltet_wenn_die_eingabe_schuld_ist(config, client):
    provider = ZuLangImAuftrag(mock_endpunkt("test"), zu_lang=1, rohtext=VLLM_EINGABE_ZU_LANG)

    daten = _auftrag(client, config, provider)

    assert daten["state"] == "fertig"
    assert provider.faltungen == 1


def test_auftrag_ohne_zahlen_faltet_auch_wenn_die_grenze_das_bekannte_fenster_fuellt(
    config, client
):
    """With no numbers in the refusal the round is folded, never lowered —
    whatever the ceiling stands at."""
    provider = ZuLangImAuftrag(mock_endpunkt("test"), zu_lang=1, rohtext=OHNE_ZAHLEN)

    daten = _auftrag(client, config, provider, context_tokens=2_500)

    assert daten["state"] == "fertig"
    assert provider.faltungen == 1
    # Nothing was lowered, only folded: no round carries a ceiling the
    # refusal named. Every one of them is "Auto" — inside the known window
    # rather than filling it, which is what the shipped default used to do
    # here (app/antwortgrenze.py) — and each is worked out against the
    # history that round is really sending, so they differ from each other.
    assert not [s for s in _status(daten) if "ceiling lowered" in s]
    # Auto on the OpenAI wire: no round carries a number at all.
    assert all(g is None for g in provider.grenzen)


def test_auftrag_ein_fremder_400er_wird_weder_gefaltet_noch_gesenkt(config, client, monkeypatch):
    """Silence test: a refusal that is not "too long" goes the outage way
    it always went — no fold, no lower ceiling."""
    from app import wiederversuch

    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    provider = ZuLangImAuftrag(
        mock_endpunkt("test"), zu_lang=1, aufbau=2,
        rohtext='{"error":{"message":"invalid_api_key"}}',
    )

    daten = _auftrag(client, config, provider)

    assert daten["end_reason"] != "kontext_voll"
    assert provider.faltungen == 0
    # Auto on the OpenAI wire carries no number, and nothing here was
    # lowered either: no round names a ceiling at all.
    assert all(g is None for g in provider.grenzen)
    status = _status(daten)
    assert not [s for s in status if "compacted the history" in s or "ceiling lowered" in s]


# --- A window that becomes unknown mid-run ------------------------------------


class FensterFaelltWeg(MockProvider):
    """Answers its first request with a tool call, and while it does the
    endpoint drops out: discovery leaves an unreachable endpoint without a
    window (app/discovery.py), and the server itself no longer takes a
    connection."""

    def __init__(self, *args, zustand, **kwargs):
        super().__init__(*args, **kwargs)
        self.zustand = zustand
        self.anfragen = 0

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.anfragen += 1
        if self.anfragen == 1:
            self.zustand.context_tokens = None
            yield Stueck("content", text="Looking. ")
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[Werkzeugaufruf(id="w1", name="no_such_tool", argumente={})],
            )
            return
        raise ProviderFehler("connection refused")


def test_chat_ein_fenster_das_mitten_in_der_antwort_wegfaellt_endet_als_ausfall(client, chat_id):
    """The next round of the answer works its ceiling out again against a
    window that is gone. That used to raise a TypeError out of the sum, and
    the second round never went out; an unknown window counts as none now,
    the round goes out and meets the outage like any other request."""
    zustand = client.app.state.discovery.zustaende["test"]
    provider = _chat_mit(client, FensterFaelltWeg(mock_endpunkt("test"), zustand=zustand))

    ereignisse = _senden(client, chat_id)

    assert "TypeError" not in json.dumps(ereignisse)
    assert provider.anfragen == 2
    antwort = _antwort(client, chat_id)
    assert "TypeError" not in json.dumps(antwort)
    assert [e["text"] for e in ereignisse if e["typ"] == "error"] == ["connection refused"]
    assert antwort["stats"]["fehler"] == "connection refused"


def test_auftrag_ein_fenster_das_mitten_im_lauf_wegfaellt_endet_als_ausfall(config, client, monkeypatch):
    """The same in a run: the round after the tool call no longer crashes on
    the missing window, it goes out and meets the outage."""
    from app import wiederversuch

    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    zustand = client.app.state.discovery.zustaende["test"]
    provider = FensterFaelltWeg(mock_endpunkt("test"), zustand=zustand)

    daten = _auftrag(client, config, provider)

    alles = json.dumps(daten["schritte"])
    assert "TypeError" not in alles
    assert daten["state"] == "unterbrochen"
    assert daten["end_reason"] == "anbieter_ausfall"
    assert provider.anfragen > 2
