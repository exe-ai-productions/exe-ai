"""Anthropic — its own provider, because its API is not OpenAI's.

Registering Anthropic under `openai_compatible` cannot work, and the
differences are not cosmetic:

* the route is `/v1/messages`, not `/v1/chat/completions`
* the key travels as `x-api-key`, not as `Authorization: Bearer`
* an `anthropic-version` header is mandatory
* the system prompt is a top-level field, not a message with role `system`
* `max_tokens` is required — leaving it out is an error, not a default
* tools have `input_schema` where OpenAI has `parameters`, and a tool result
  is a content block inside a user message rather than its own role
* the stream sends typed events (`content_block_delta`, `message_delta`)
  instead of choice deltas, and reasoning arrives as `thinking`, not as a
  parsed-out tag

What this file does is translate all of that in both directions, so the rest
of the terminal never learns that Anthropic is different.
"""

from __future__ import annotations

import json
import logging
import asyncio
import os
import time
from typing import Any, AsyncIterator

import httpx

from app import antwortende, samplingwerte
from app.config import EndpointConfig
from app.denkstufen import ist_wirt, wirt_von
from app.parameter import uebersetzen
from app.providers.base import (
    ChatNachricht,
    Generierungsanfrage,
    KontextDrossel,
    Provider,
    ProviderFehler,
    Stueck,
    Werkzeugaufruf,
    WerkzeugFortschrittsDrossel,
    kontext_stueck,
    provider_error,
    refusal_of,
    require_stream_end,
    zaehlung,
    zeitlimit,
)
# The speed is worked out by the OpenAI-compatible route's function, not by
# one of our own. Two providers doing their own arithmetic put two columns
# in one table that answer two different questions — which is what happened
# here: this file used to divide by the WHOLE duration, prompt processing
# and thinking included, while the other one had long since written down
# that the number means the answer alone. Sharing the function is the only
# way the two stay the same answer.
from app.providers.openai_kompatibel import display_model, tempo_ermitteln

log = logging.getLogger(__name__)

# The version the API expects. It is not optional: without the header the
# request is rejected.
API_VERSION = "2023-06-01"

# The mark that lets the server cache a request up to the block it sits on.
# Five minutes, the default life of a mark — no ``ttl`` field for it.
CACHE_MARKE = {"type": "ephemeral"}

# The two kinds of `thinking` object under which the model really thinks.
# Only these take a `display`; every "off" word (`disabled`, or what the
# catalogue keeps for a compatible server) says nothing is being thought,
# and a display for nothing is a field nobody asked for.
DENKEN_AN: tuple[str, ...] = ("enabled", "adaptive")

# The two content blocks that carry a round's thinking. Both go back exactly
# as received while the round's tool calls are answered — a changed or
# missing one is refused with a 400 — and neither ever carries a cache mark.
THINKING_BLOCKS: tuple[str, ...] = ("thinking", "redacted_thinking")

# What the API's 400 says when the thinking blocks handed back are refused:
# the signature is no longer valid (a key, a model or a day later) or the
# blocks are not what the server sent. The words that name the refusal, kept
# here once and compared in lower case.
THINKING_REFUSALS: tuple[str, ...] = (
    "`thinking` or `redacted_thinking` blocks in the latest assistant message cannot be modified",
    "invalid `signature` in `thinking` block",
)


def refuses_thinking_blocks(status: int | None, raw_text: str | None) -> bool:
    """Whether a refused request was refused over the thinking blocks it
    carried: a 400 whose text names one of ``THINKING_REFUSALS``. Any other
    400 is somebody else's problem and stays an error."""
    if status != 400 or not raw_text:
        return False
    text = raw_text.lower()
    return any(wording in text for wording in THINKING_REFUSALS)


# Anthropic's own host. The request for a readable summary goes there and
# nowhere else: a server that only speaks this dialect is somebody else's,
# and one that checks the `thinking` object strictly would refuse the field
# — a refusal that names `thinking` is then booked against the stage itself
# (app/denkablehnung.py). The host alone decides, never the path — one rule
# for both makers' own servers (app/denkstufen.py, `ist_wirt`).
WIRT_ANTHROPIC = "api.anthropic.com"


def ist_anthropic(wirt: str) -> bool:
    """Is this host Anthropic's own — the host itself or a real sub-domain?"""
    return ist_wirt(wirt=wirt, eigener=WIRT_ANTHROPIC)


# MiniMax's own hosts. Their Anthropic-shaped endpoint takes the cache marks
# for its own models — except MiniMax-M3, which caches by itself.
MINIMAX_HOSTS: tuple[str, ...] = ("api.minimax.io", "api.minimaxi.com")


def cache_marks_allowed(wirt: str, modell: str | None) -> bool:
    """May this request carry ``cache_control`` marks?

    Only where the field is known to be accepted on this wire: Anthropic's
    own host, a Claude model behind any Anthropic-shaped server, and
    MiniMax's own hosts for every model but M3. Any other
    server that speaks this dialect gets none: one that does not know the
    field answers the whole request with a 400.
    """
    name = (modell or "").lower()
    minimax = any(ist_wirt(wirt=wirt, eigener=eigener) for eigener in MINIMAX_HOSTS)
    if minimax and "minimax-m3" in name:
        return False
    return ist_anthropic(wirt) or "claude" in name or minimax


def _eingang_lesen(nutzung: dict[str, Any]) -> tuple[int | None, int | None]:
    """The whole prompt of a round, and what of it came from the cache.

    With caching, ``input_tokens`` counts only what came after the last
    mark — the part neither written to nor read from the cache. The prompt
    the context reading and the fold limit need is all three together;
    reading ``input_tokens`` alone would tell them a long conversation
    weighs a few dozen tokens. Without the cache fields it is
    ``input_tokens`` as before.
    """
    # Through `zaehlung` (app/providers/base.py), not `als_zahl`: a negative
    # number is not a count, and the share below divides by this sum — a
    # server reporting `input_tokens: -100000` would otherwise turn
    # 5000 cached tokens into "-5 %".
    eingang = zaehlung(nutzung.get("input_tokens"))
    geschrieben = zaehlung(nutzung.get("cache_creation_input_tokens"))
    gelesen = zaehlung(nutzung.get("cache_read_input_tokens"))
    if geschrieben or gelesen:
        eingang = (eingang or 0) + (geschrieben or 0) + (gelesen or 0)
    return eingang, gelesen


def _cache_anteil(eingang: int | None, gelesen: int | None) -> int | None:
    """How much of the whole prompt the cache already had, in whole percent —
    or ``None`` where this round named no cache reading.

    The whole prompt is all three halves together, the same sum
    ``_eingang_lesen`` builds: what came after the last cache mark, what was
    written to the cache and what was read out of it. Dividing by
    ``input_tokens`` alone would read a long cached conversation as a few
    percent (the docstring above says why).

    A real zero comes back as a zero: this wire names ``cache_read_…`` only
    when it means something, and "the cache had nothing" is a reading the
    window shows. Silence is for the round that named no cache at all — the
    difference the whole reading exists for.
    """
    if gelesen is None or not eingang:
        return None
    return round(gelesen * 100 / eingang)


class AnthropicProvider(Provider):
    def __init__(self, endpunkt: EndpointConfig, timeout: float = 600.0) -> None:
        super().__init__(endpunkt)
        self.timeout = timeout
        # The window sizes out of the model list, once. Discovery asks for
        # the context size on every pass until it gets an answer, so a
        # provider whose model is missing from the list would otherwise pay
        # for a fresh catalogue request forever. `None` = never asked; an
        # empty dict = asked, and the list said nothing usable.
        self._fenster: dict[str, int] | None = None
        # The other number the same list entry carries: how long an answer
        # from this model may be (``max_tokens``). Filled by the same
        # request, so asking for it costs nothing extra.
        self._antwortgrenzen: dict[str, int] = {}
        # One request at a time, so a second caller waits for the answer
        # instead of reading a cache that is not filled yet.
        self._fenster_schloss = asyncio.Lock()

    @property
    def _kopfzeilen(self) -> dict[str, str]:
        """Headers for every request.

        The key is never in config.yaml, only the NAME of its environment
        variable — same rule as everywhere else. It is read fresh each time,
        so a key changed in .env takes effect without a restart.
        """
        kopf = {
            "content-type": "application/json",
            "anthropic-version": API_VERSION,
        }
        name = self.endpunkt.api_key_env
        wert = os.getenv(name, "").strip() if name else ""
        if wert:
            kopf["x-api-key"] = wert
        return kopf

    # --- Sign of life and catalogue --------------------------------------

    async def erreichbar(self, timeout: float = 3.0) -> bool:
        self.letzter_grund = None
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=self._kopfzeilen) as client:
                antwort = await client.get(f"{self.endpunkt.base_url}/models")
            if antwort.status_code >= 400:
                # The address answers and refuses — a wrong key, a key that
                # belongs to no workspace — which is not the same as a dead
                # host. What Anthropic says about it is kept and logged.
                grund = refusal_of(antwort, self._kopfzeilen.get("x-api-key", ""))
                if grund is not None:
                    self.letzter_grund = grund[1]
                    self.ablehnung_melden(log, antwort.status_code, grund)
                elif antwort.status_code == 401:
                    log.info("Anthropic answers, but the key is rejected")
                return False
            self.ablehnung_vorbei()
            return True
        except (httpx.HTTPError, OSError):
            return False

    async def modelle_auflisten(self, timeout: float = 3.0) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=self._kopfzeilen) as client:
                antwort = await client.get(f"{self.endpunkt.base_url}/models?limit=100")
            if antwort.status_code >= 400:
                return []
            daten = antwort.json()
        except (httpx.HTTPError, OSError, ValueError):
            return []
        namen = []
        for eintrag in daten.get("data") or []:
            kennung = eintrag.get("id") if isinstance(eintrag, dict) else None
            if isinstance(kennung, str) and kennung.strip():
                namen.append(kennung.strip())
        return namen

    async def denkquellen(self, timeout: float = 3.0) -> dict[str, Any]:
        """What the model list says about thinking, per model.

        Since the list carries a ``capabilities`` block, the accepted depths
        no longer have to be maintained anywhere: ``effort.<stage>.supported``
        names them, ``thinking.types.adaptive.supported`` says whether the
        plain switch exists. The one thing the block never carries is
        whether the model also takes ``disabled``, and that stays the single
        row the catalogue keeps for this provider.
        """
        daten = None
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=self._kopfzeilen) as client:
                antwort = await client.get(f"{self.endpunkt.base_url}/models?limit=100")
            if antwort.status_code < 400:
                daten = antwort.json()
        except (httpx.HTTPError, OSError, ValueError):
            return {}
        if not isinstance(daten, dict):
            return {}
        je_modell: dict[str, Any] = {}
        for eintrag in daten.get("data") or []:
            if not isinstance(eintrag, dict):
                continue
            kennung = eintrag.get("id")
            caps = eintrag.get("capabilities")
            if isinstance(kennung, str) and isinstance(caps, dict):
                je_modell[kennung.strip()] = caps
        return {"anthropic": je_modell} if je_modell else {}

    async def modellname(self, timeout: float = 3.0) -> str | None:
        if self.endpunkt.modell:
            return self.endpunkt.modell
        namen = await self.modelle_auflisten(timeout)
        return namen[0] if namen else None

    async def _fenster_holen(self, timeout: float) -> dict[str, int]:
        """``max_input_tokens`` per model, out of the model list.

        The list has carried the number since the endpoint learned to report
        capabilities, and it is the same request the thinking stages already
        read. Fetched at most once per provider instance: discovery asks
        again on every pass until the context size is known, and a model
        that never turns up in the list must not cost a round trip each
        time.
        """
        if self._fenster is not None:
            return self._fenster
        # The lock, not just the check: filled in only once the answer is
        # parsed. Marking the cache as done BEFORE the await let a second
        # caller in during the request read an empty mapping, conclude the
        # list knows nothing, and fall back to the guessed table — the very
        # number this way of asking exists to replace.
        async with self._fenster_schloss:
            if self._fenster is not None:
                return self._fenster
            gefunden = await self._fenster_lesen(timeout)
            if gefunden is None:
                # Not remembered as an answer: a rejected key or a hiccup is
                # not the same as "the list has nothing for this model".
                return {}
            self._fenster, self._antwortgrenzen = gefunden
            return self._fenster

    async def _fenster_lesen(
        self, timeout: float
    ) -> tuple[dict[str, int], dict[str, int]] | None:
        """One request, both numbers: ``max_input_tokens`` per model and
        ``max_tokens`` beside it — the list's own words for "how much fits
        in" and "how much may come out". ``None`` when it did not answer —
        that is not a result."""
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=self._kopfzeilen) as client:
                antwort = await client.get(f"{self.endpunkt.base_url}/models?limit=100")
            if antwort.status_code >= 400:
                return None
            daten = antwort.json()
        except (httpx.HTTPError, OSError, ValueError):
            return None
        gelesen: dict[str, int] = {}
        grenzen: dict[str, int] = {}
        if not isinstance(daten, dict):
            return gelesen, grenzen
        for eintrag in daten.get("data") or []:
            if not isinstance(eintrag, dict):
                continue
            kennung = eintrag.get("id")
            if not isinstance(kennung, str):
                continue
            fenster = eintrag.get("max_input_tokens")
            if isinstance(fenster, int) and fenster > 0:
                gelesen[kennung.strip()] = fenster
            hoechste = eintrag.get("max_tokens")
            if isinstance(hoechste, int) and hoechste > 0:
                grenzen[kennung.strip()] = hoechste
        return gelesen, grenzen

    async def kontextgroesse(
        self, timeout: float = 3.0, modellname: str | None = None
    ) -> int | None:
        """The model's own window, asked of the provider rather than guessed.

        Two sources, in this order: a configured value (the base class
        already provides that check), then ``max_input_tokens`` out of the
        model list. The shipped table of known models is no longer asked
        here — ``app/fenstergroesse.py`` is the one place that falls through
        to it, after a learned value and before the fallback, and asking it
        from inside this "server" step would have let a pinned table entry
        outrank a size the provider had already learned from a refusal.

        Deliberately the bare ``endpunkt.modell`` field, not a resolved name
        from ``modelle_auflisten()``: an endpoint left to pick from the
        catalogue (no ``modell:`` set) has no one model whose window could be
        reported, and stays ``None`` rather than naming one of many.
        """
        konfiguriert = await super().kontextgroesse(timeout)
        if konfiguriert:
            return konfiguriert
        modell = self.endpunkt.modell
        if not modell:
            return None
        return (await self._fenster_holen(timeout)).get(modell.strip())

    async def context_per_model(self, timeout: float = 3.0) -> dict[str, int] | None:
        """``max_input_tokens`` of every model in the list — the catalogue's
        own window per model, where the endpoint as a whole has none.
        ``None`` while the list has not answered (a rejected key, a hiccup):
        ``_fenster_holen`` remembers only an answer."""
        windows = await self._fenster_holen(timeout)
        return dict(windows) if self._fenster is not None else None

    async def answer_limit_per_model(self, timeout: float = 3.0) -> dict[str, int] | None:
        """``max_tokens`` of every model in the same list, by model id.
        ``None`` while the list has not answered."""
        await self._fenster_holen(timeout)
        return dict(self._antwortgrenzen) if self._fenster is not None else None

    async def hoechste_antwort(
        self, timeout: float = 3.0, modellname: str | None = None
    ) -> int | None:
        """The model's own output limit, out of the same model list.

        The list names it ``max_tokens``, beside ``max_input_tokens``: "the
        maximum value for the max_tokens parameter when using this model".
        Asked of the provider instead of kept in a table — a table of output
        limits is wrong the day a model is added, and this API answers the
        question itself.

        Same model reading as the window next door: the bare configured
        field, because an endpoint left to pick from the catalogue has no one
        model whose limit could be reported.
        """
        modell = modellname or self.endpunkt.modell
        if not modell:
            return None
        await self._fenster_holen(timeout)
        return self._antwortgrenzen.get(modell.strip())

    # --- Translating a request -------------------------------------------

    @staticmethod
    def _werkzeuge_uebersetzen(werkzeuge: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """OpenAI tool definitions into Anthropic's shape.

        The registry speaks OpenAI everywhere, so the translation happens here
        rather than making every tool know two formats.
        """
        raus = []
        for w in werkzeuge:
            f = w.get("function") or {}
            if not f.get("name"):
                continue
            raus.append({
                "name": f["name"],
                "description": f.get("description", ""),
                "input_schema": f.get("parameters") or {"type": "object", "properties": {}},
            })
        return raus

    @staticmethod
    def _als_bloecke(inhalt: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
        """A message's content as a block list, whatever shape it came in.

        Folding two turns means concatenating their blocks; a plain string
        becomes its one text block first. An empty string folds to nothing
        rather than to an empty block, which the API refuses.
        """
        if isinstance(inhalt, list):
            return inhalt
        return [{"type": "text", "text": inhalt}] if inhalt else []

    @staticmethod
    def _tool_use_block(call: Werkzeugaufruf) -> dict[str, Any]:
        return {
            "type": "tool_use",
            "id": call.id,
            "name": call.name,
            "input": call.argumente or {},
        }

    def _round_content(self, n: ChatNachricht) -> list[dict[str, Any]]:
        """An assistant round with tool calls, as the blocks that go back.

        A round that thought goes back in the order the answer brought its
        blocks: each thinking block exactly as received, the round's text
        where its first text block stood, each tool call where it began.
        The API refuses the next round when a thinking block of the one
        being answered is missing, changed or moved. Only to Anthropic's own
        host — the signature is that server's, and another server that only
        speaks this dialect has no use for it. A call that never finished
        on the wire (the folder check cuts the stream as a call begins)
        stands at the end. A round without thinking is its text and then
        its calls, as before.
        """
        thinks = ist_anthropic(wirt_von(self.endpunkt.base_url)) and any(
            b.get("type") in THINKING_BLOCKS for b in n.anthropic_blocks
        )
        if not thinks:
            blocks = [{"type": "text", "text": n.content}] if n.content else []
            return blocks + [self._tool_use_block(c) for c in n.werkzeugaufrufe]

        pending = {c.id: c for c in n.werkzeugaufrufe}
        blocks = []
        text_placed = not n.content
        for block in n.anthropic_blocks:
            kind = block.get("type")
            if kind in THINKING_BLOCKS:
                blocks.append(dict(block))
            elif kind == "text" and not text_placed:
                blocks.append({"type": "text", "text": n.content})
                text_placed = True
            elif kind == "tool_use" and (call := pending.pop(block.get("id"), None)):
                if not text_placed:
                    blocks.append({"type": "text", "text": n.content})
                    text_placed = True
                blocks.append(self._tool_use_block(call))
        if not text_placed:
            blocks.append({"type": "text", "text": n.content})
        return blocks + [self._tool_use_block(c) for c in pending.values()]

    def _nachrichten_bauen(
        self, nachrichten: list[ChatNachricht]
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Splits the history into system prompt and messages.

        Anthropic keeps the system prompt out of the conversation; a message
        with role `system` would be rejected. Tool results are content blocks
        in a user message, which is why they are folded into the previous one
        instead of standing alone.
        """
        system: list[str] = []
        raus: list[dict[str, Any]] = []

        for n in nachrichten:
            if n.role == "system":
                if n.content:
                    system.append(n.content)
                continue

            if n.role == "tool":
                block = {
                    "type": "tool_result",
                    "tool_use_id": n.werkzeugaufruf_id or "",
                    "content": n.content or "",
                }
                # Several results in a row belong into one user message —
                # Anthropic rejects two user turns following each other.
                if raus and raus[-1]["role"] == "user" and isinstance(raus[-1]["content"], list):
                    raus[-1]["content"].append(block)
                else:
                    raus.append({"role": "user", "content": [block]})
                continue

            if n.role == "assistant" and n.werkzeugaufrufe:
                raus.append({"role": "assistant", "content": self._round_content(n)})
                continue

            if n.alle_bild_urls():
                # Anthropic wants the raw base64 plus its media type, where
                # OpenAI takes the whole data URL. One image block per
                # attachment, then the text.
                inhalt: list[dict[str, Any]] = []
                for url in n.alle_bild_urls():
                    kopf, _, rumpf = url.partition(",")
                    typ = kopf.removeprefix("data:").removesuffix(";base64") or "image/png"
                    inhalt.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": typ, "data": rumpf},
                    })
                if n.content:
                    inhalt.append({"type": "text", "text": n.content})
                # Folded into a user turn standing right before it, the same
                # rule as the two folds below: a picture sent right after an
                # answer that used tools follows that answer's results —
                # which are a user turn here — and two user turns in a row
                # are rejected whatever the first one was made of.
                if n.role == "user" and raus and raus[-1]["role"] == "user":
                    voriger = raus[-1]
                    if not isinstance(voriger["content"], list):
                        text = voriger["content"]
                        voriger["content"] = [{"type": "text", "text": text}] if text else []
                    voriger["content"].extend(inhalt)
                    continue
                raus.append({"role": n.role, "content": inhalt})
                continue

            if n.role == "user" and raus and raus[-1]["role"] == "user":
                # Same rule as the tool-result fold above, for a plain user
                # turn arriving right after one: two user turns in a row are
                # rejected here regardless of what the first one was made of
                # (a task message, folded tool results, ...).
                voriger = raus[-1]
                if not isinstance(voriger["content"], list):
                    text = voriger["content"]
                    voriger["content"] = [{"type": "text", "text": text}] if text else []
                if n.content:
                    voriger["content"].append({"type": "text", "text": n.content})
                continue

            raus.append({"role": n.role, "content": n.content or ""})

        # Anthropic rejects two ASSISTANT turns in a row just as it rejects
        # two user turns, and it rejects a conversation that OPENS on the
        # assistant. Both shapes are real here: a background command's
        # report is an assistant row right after an answer row, and chat
        # compaction slices the history's middle, which can start on
        # either role. Folded rather than refused — the text of both turns
        # is what matters, not that they arrived as two rows.
        gefaltet: list[dict[str, Any]] = []
        for eintrag in raus:
            if (
                gefaltet
                and eintrag["role"] == "assistant"
                and gefaltet[-1]["role"] == "assistant"
            ):
                voriger = gefaltet[-1]
                voriger["content"] = self._als_bloecke(voriger["content"]) + self._als_bloecke(
                    eintrag["content"]
                )
                continue
            gefaltet.append(eintrag)
        raus = gefaltet
        if raus and raus[0]["role"] == "assistant":
            # A middle that opens on the assistant is an excerpt, and the
            # API wants to be told so by a user turn — an empty marker, not
            # invented dialogue.
            raus.insert(0, {"role": "user", "content": "[Conversation excerpt continues below.]"})

        # An empty history would be rejected; better an empty turn than a 400.
        if not raus:
            raus.append({"role": "user", "content": ""})
        return ("\n\n".join(system) if system else None, raus)

    def _cache_marken_setzen(self, koerper: dict[str, Any]) -> None:
        """Marks where the server may cache the request up to — in the body
        that goes out, never in what is stored.

        Anthropic caches only what a request marks, and a mark sits on a
        block, never on a plain string: the system prompt goes out as one
        text block for that reason. One mark on it and one on each of the
        last three messages that have something to carry one — four is the
        most a request may hold. The system prompt holds still across a
        conversation, and the three newest messages let the next request
        find the longest prefix it shares with this one wherever the
        conversation grew. Five minutes, the default life of a mark, so no
        ``ttl`` field.
        """
        if isinstance(koerper.get("system"), str):
            koerper["system"] = [
                {"type": "text", "text": koerper["system"], "cache_control": dict(CACHE_MARKE)}
            ]
        # A thinking block never carries a mark: it sits on the last block of
        # a message that is not one, and a message of thinking alone carries
        # none.
        traeger: list[tuple[dict[str, Any], list[dict[str, Any]], int]] = []
        for nachricht in koerper["messages"]:
            bloecke = self._als_bloecke(nachricht["content"])
            stelle = next(
                (
                    i for i in range(len(bloecke) - 1, -1, -1)
                    if bloecke[i].get("type") not in THINKING_BLOCKS
                ),
                None,
            )
            if stelle is not None:
                traeger.append((nachricht, bloecke, stelle))
        for nachricht, bloecke, stelle in traeger[-3:]:
            nachricht["content"] = [
                *bloecke[:stelle],
                {**bloecke[stelle], "cache_control": dict(CACHE_MARKE)},
                *bloecke[stelle + 1:],
            ]

    def _koerper_bauen(self, anfrage: Generierungsanfrage) -> dict[str, Any]:
        system, nachrichten = self._nachrichten_bauen(anfrage.nachrichten)
        koerper: dict[str, Any] = {
            "model": anfrage.modell or self.endpunkt.modell or "",
            "messages": nachrichten,
            "stream": True,
            # Required, not optional — a missing limit is an error here. No
            # fallback beside it any more: a ceiling is resolved for every
            # request before it is built (app/antwortgrenze.py), and a
            # shipped number here would only be a second answer to a
            # question that already has one.
            "max_tokens": anfrage.max_tokens,
        }
        if system:
            koerper["system"] = system
        if anfrage.werkzeuge:
            werkzeuge = self._werkzeuge_uebersetzen(anfrage.werkzeuge)
            if werkzeuge:
                koerper["tools"] = werkzeuge

        eigene = dict(anfrage.parameter)
        if anfrage.temperature is not None:
            eigene["temperature"] = anfrage.temperature
        if anfrage.top_p is not None:
            eigene["top_p"] = anfrage.top_p
        uebersetzt = uebersetzen(self.endpunkt.parameter_dialect, eigene)
        # max_tokens is already set above and must not be overwritten by None.
        uebersetzt.pop("max_tokens", None)
        koerper.update(uebersetzt)
        koerper.update(anfrage.zusatz)
        # The thinking comes back as readable text, asked for by name. The
        # chat shows it live beside the answer, and a model that leaves the
        # display to its own default may hand back an empty block with only
        # a signature in it. A display the request already names is kept.
        # A new object, not the one in `zusatz`: that one belongs to the
        # request and is read again for the next round.
        denken = koerper.get("thinking")
        if (
            isinstance(denken, dict)
            and denken.get("type") in DENKEN_AN
            and ist_anthropic(wirt_von(self.endpunkt.base_url))
        ):
            koerper["thinking"] = {"display": "summarized", **denken}
        # Last, after everything that can set a value: what this model
        # refuses is taken out of the finished body (app/samplingwerte.py).
        samplingwerte.bereinigen(koerper)
        if cache_marks_allowed(wirt_von(self.endpunkt.base_url), koerper.get("model")):
            self._cache_marken_setzen(koerper)
        return koerper

    # --- Streaming --------------------------------------------------------

    async def streamen(self, anfrage: Generierungsanfrage) -> AsyncIterator[Stueck]:
        """The stream of one request — asked once more without the thinking
        blocks it handed back where the API refuses exactly those.

        A round of an answer that failed is asked again with the thinking
        its run had stored, and a signature that was valid then may be none
        any more: another key, another model, a day later. The refusal
        arrives as a 400 before the first packet, so nothing of the refused
        attempt has reached the caller. The request goes out once more with
        no thinking block in any message; where that one goes through, the
        blocks are gone from the messages for the rounds that follow, so
        none of them asks twice. No sentence for the person, no second
        wire: the same request, minus what was refused.
        """
        begun = False
        try:
            async for stueck in self._streamen_ab(anfrage, self._koerper_bauen(anfrage)):
                begun = True
                yield stueck
            return
        except ProviderFehler as fehler:
            if (
                begun
                or not refuses_thinking_blocks(fehler.status, fehler.rohtext)
                or not self._hands_back_thinking(anfrage)
            ):
                raise
            log.warning(
                "%s refused the thinking blocks handed back; asking once more without them: %s",
                self.name,
                (fehler.rohtext or "")[:200],
            )
        for nachricht in anfrage.nachrichten:
            nachricht.anthropic_blocks = []
        async for stueck in self._streamen_ab(anfrage, self._koerper_bauen(anfrage)):
            yield stueck

    def _hands_back_thinking(self, anfrage: Generierungsanfrage) -> bool:
        """Whether this request carries thinking blocks to Anthropic's own
        host — the only place they go back to (``_round_content``)."""
        return ist_anthropic(wirt_von(self.endpunkt.base_url)) and any(
            block.get("type") in THINKING_BLOCKS
            for nachricht in anfrage.nachrichten
            for block in nachricht.anthropic_blocks
        )

    async def _streamen_ab(
        self, anfrage: Generierungsanfrage, koerper: dict[str, Any]
    ) -> AsyncIterator[Stueck]:
        """Translates Anthropic's typed events into our chunks.

        The shape is different from OpenAI's: content arrives as
        `content_block_delta`, a tool call is assembled from `content_block_start`
        plus a series of `input_json_delta` fragments, and the token counts
        come in `message_start` and `message_delta`.
        """
        adresse = f"{self.endpunkt.base_url}/messages"

        beginn = time.monotonic()
        erstes_token_nach: float | None = None
        token_gezaehlt = 0
        # The chain of thought, counted separately from `token_gezaehlt`: the
        # live context reading below grows with it before `message_delta`
        # names a real `output_tokens` figure. Once that figure arrives it
        # already includes the chain of thought (see `denken_gesehen` below),
        # so this counter is only ever added where `ausgang` is still unset —
        # never together with it, or the thinking would count twice.
        denk_gezaehlt = 0
        # None until `message_start` names it: a zero would be a claim, and
        # the stats chunk below adds it into a total that the service takes
        # as whole — measured 12,000 of context turning into 120 on a
        # compatible server that sent no usage block.
        eingang: int | None = None
        # What of the prompt came out of the cache — None where the server
        # named nothing, so the stats say nothing rather than a zero.
        cache_gelesen: int | None = None
        # The share of it, in whole percent — the same reading goes out live
        # with `message_start` and stands in the stats below.
        cache_anteil: int | None = None
        # Which model answered, as the SERVER names it. `message_start`
        # carries the resolved id — a dated one where the request named an
        # alias — and it is the only place on this wire that says which
        # model ran (app/main.py, protocol line "Answer from …"). The same
        # reading the OpenAI-compatible route takes off its own answer, so
        # the two lines cannot say different things about the same fact.
        reported_model: str | None = None
        ausgang = 0
        # Whether this run thought at all. `output_tokens` counts the chain
        # of thought in with the answer and this API names no split, so
        # where a run thought, that count and the divisor beside it describe
        # two different stretches of time. `tempo_ermitteln` needs to be
        # told, so it can step down to the chunk count the same way it does
        # for a silent OpenAI-compatible server.
        denken_gesehen = False
        ende_grund: str | None = None
        # What Anthropic says about a refusal, beside the reason: the
        # category and an explanation, either of them `null` or missing.
        ablehnung_kategorie: str | None = None
        ablehnung_erklaerung: str | None = None
        # Tool calls under construction, by block index: their arguments
        # arrive as a string in pieces and are only valid JSON at the end.
        offene: dict[int, dict[str, Any]] = {}
        fertige: list[Werkzeugaufruf] = []
        # Thinking blocks under construction, by block index: the text and
        # the signature arrive in pieces, and the block goes out whole when
        # it closes (see `_round_content`).
        open_thinking: dict[int, dict[str, Any]] = {}
        drossel = WerkzeugFortschrittsDrossel()
        kontextdrossel = KontextDrossel()

        try:
            async with httpx.AsyncClient(
                timeout=zeitlimit(self.timeout, self.endpunkt.timeout_enabled),
                headers=self._kopfzeilen,
            ) as client:
                async with client.stream("POST", adresse, json=koerper) as antwort:
                    if antwort.status_code >= 400:
                        rohtext = (await antwort.aread()).decode("utf-8", "replace")
                        raise provider_error(
                            "fehler.anbieter_antwortet_mit",
                            status=antwort.status_code,
                            rohtext=rohtext,
                            name=self.name,
                            status_code=antwort.status_code,
                            text=rohtext[:400],
                        )

                    async for zeile in antwort.aiter_lines():
                        if not zeile.startswith("data:"):
                            continue
                        roh = zeile[5:].strip()
                        if not roh:
                            continue
                        try:
                            daten = json.loads(roh)
                        except ValueError:
                            continue

                        typ = daten.get("type")

                        if typ == "message_start":
                            kopf = daten.get("message") or {}
                            nutzung = kopf.get("usage") or {}
                            eingang, cache_gelesen = _eingang_lesen(nutzung)
                            served = kopf.get("model")
                            if isinstance(served, str) and served:
                                reported_model = served
                            # The share of this prompt the cache already had,
                            # right here: this wire names all three halves in
                            # its FIRST event, so waiting for the answer to be
                            # done would keep the number off the screen for
                            # the whole answer. It rides the event the other
                            # wires send their live reading under, carrying
                            # that one field alone — a server that names no
                            # cache sends nothing at all.
                            cache_anteil = _cache_anteil(eingang, cache_gelesen)
                            if cache_anteil is not None:
                                yield Stueck(
                                    sorte="denktempo",
                                    daten={"prompt_cache_percent": cache_anteil},
                                )

                        elif typ == "content_block_start":
                            block = daten.get("content_block") or {}
                            kind = block.get("type")
                            if kind == "thinking":
                                open_thinking[daten.get("index", 0)] = {
                                    "type": "thinking",
                                    "thinking": block.get("thinking") or "",
                                    "signature": block.get("signature") or "",
                                }
                            elif kind == "redacted_thinking":
                                # Arrives whole, sealed in `data`, and goes
                                # back exactly so.
                                open_thinking[daten.get("index", 0)] = dict(block)
                            elif kind in ("text", "tool_use"):
                                # Only the place: the text and the call go
                                # back from what the round kept of them.
                                yield Stueck(
                                    sorte="anthropic_block",
                                    daten={"block": {"type": kind, "id": block.get("id")}},
                                )
                            if kind == "tool_use":
                                index = daten.get("index", 0)
                                offene[index] = {
                                    "id": block.get("id") or "",
                                    "name": block.get("name") or "",
                                    "roh": "",
                                }
                                # The name is known right here — say so at
                                # once instead of staying silent until the
                                # whole argument has arrived.
                                if offene[index]["name"] and drossel.faellig(
                                    index, 0, time.monotonic()
                                ):
                                    yield Stueck(
                                        sorte="tool_call_laeuft",
                                        daten={
                                            "index": index,
                                            "name": offene[index]["name"],
                                            "zeichen": 0,
                                        },
                                    )

                        elif typ == "content_block_delta":
                            delta = daten.get("delta") or {}
                            art = delta.get("type")
                            if art == "text_delta":
                                text = delta.get("text") or ""
                                if text:
                                    if erstes_token_nach is None:
                                        erstes_token_nach = time.monotonic() - beginn
                                    token_gezaehlt += 1
                                    yield Stueck(sorte="content", text=text)
                            elif art == "thinking_delta":
                                # Reasoning arrives declared, so no tag has to
                                # be parsed out of the text as elsewhere.
                                gedanke = delta.get("thinking") or ""
                                if gedanke:
                                    # Deliberately no `erstes_token_nach` and
                                    # no `token_gezaehlt` count: the speed is
                                    # the speed of the ANSWER. `denken_gesehen`
                                    # is noted only so the count from `usage`
                                    # can be weighed against a divisor that
                                    # leaves the thinking out; `denk_gezaehlt`
                                    # is a second, separate count that only
                                    # feeds the live context reading below,
                                    # never the speed.
                                    #
                                    # No live speed reading is sent from here
                                    # either, unlike the OpenAI-compatible
                                    # route: this event carries
                                    # only the thought's text, no per-chunk
                                    # timing of its own the way llama.cpp's
                                    # `timings` block does — there is nothing
                                    # to read early. A limit of the protocol,
                                    # not an oversight.
                                    denken_gesehen = True
                                    denk_gezaehlt += 1
                                    yield Stueck(sorte="reasoning", text=gedanke)
                                thinking_block = open_thinking.get(daten.get("index", 0))
                                if thinking_block is not None:
                                    thinking_block["thinking"] += gedanke
                            elif art == "signature_delta":
                                thinking_block = open_thinking.get(daten.get("index", 0))
                                if thinking_block is not None:
                                    thinking_block["signature"] += delta.get("signature") or ""
                            elif art == "input_json_delta":
                                index = daten.get("index", 0)
                                offen = offene.get(index)
                                if offen is not None:
                                    offen["roh"] += delta.get("partial_json") or ""
                                    # Counts toward the speed: the model
                                    # generates tokens here just as with
                                    # visible text.
                                    if erstes_token_nach is None:
                                        erstes_token_nach = time.monotonic() - beginn
                                    token_gezaehlt += 1
                                    # Pure information — the call is still
                                    # only assembled at content_block_stop
                                    # and executed after the stream.
                                    if offen["name"] and drossel.faellig(
                                        index, len(offen["roh"]), time.monotonic()
                                    ):
                                        yield Stueck(
                                            sorte="tool_call_laeuft",
                                            daten={
                                                "index": index,
                                                "name": offen["name"],
                                                "zeichen": len(offen["roh"]),
                                            },
                                        )

                        elif typ == "content_block_stop":
                            thinking_block = open_thinking.pop(daten.get("index", 0), None)
                            if thinking_block is not None:
                                yield Stueck(sorte="anthropic_block", daten={"block": thinking_block})
                            offen = offene.pop(daten.get("index", 0), None)
                            if offen and offen["name"]:
                                try:
                                    argumente = json.loads(offen["roh"] or "{}")
                                except ValueError:
                                    argumente = {}
                                fertige.append(Werkzeugaufruf(
                                    id=offen["id"], name=offen["name"],
                                    argumente=argumente if isinstance(argumente, dict) else {},
                                ))

                        elif typ == "message_delta":
                            nutzung = daten.get("usage") or {}
                            # Through `zaehlung` like every other count: this
                            # number goes into the stats and into
                            # `gesamt_tokens`, and a server naming it as a
                            # string would end the whole round with a
                            # TypeError instead of a reading. A real zero
                            # falls back to what was counted here.
                            ausgang = zaehlung(nutzung.get("output_tokens")) or ausgang
                            # Why it stopped travels in the same event, one
                            # level up from the usage.
                            delta = daten.get("delta") or {}
                            if wort := delta.get("stop_reason"):
                                ende_grund = wort
                            # The refusal's own words travel next to it; a
                            # field that is `null`, missing or not text says
                            # nothing and leaves what an earlier event gave.
                            details = delta.get("stop_details")
                            if isinstance(details, dict):
                                kategorie = details.get("category")
                                erklaerung = details.get("explanation")
                                if isinstance(kategorie, str) and kategorie.strip():
                                    ablehnung_kategorie = kategorie.strip()
                                if isinstance(erklaerung, str) and erklaerung.strip():
                                    ablehnung_erklaerung = erklaerung.strip()

                        elif typ == "error":
                            fehler = daten.get("error") or {}
                            meldung = fehler.get("message")
                            raise provider_error(
                                "fehler.anbieter_meldung" if meldung
                                else "fehler.anbieter_meldung_leer",
                                name=self.name,
                                text=meldung or "",
                            )

                        # How full the context is, once per event and
                        # throttled. ONE place rather than one per branch:
                        # everything above that moves the reading — the
                        # prompt, answer text, and the tokens of a tool
                        # argument being written — has already moved it by
                        # the time this line is reached, and a single site
                        # cannot fall out of step with itself.
                        #
                        # This route is the exact one. `input_tokens` stands
                        # complete in `message_start`, which is the FIRST
                        # event of the stream, so the reading is right from
                        # the moment the answer begins instead of at its
                        # end. The output half is our own count — answer,
                        # tool arguments and, until `message_delta` names the
                        # real `output_tokens` figure, the chain of thought
                        # too (`denk_gezaehlt`) — and the round's stats chunk
                        # replaces it either way. Once `ausgang` is named it
                        # already covers the chain of thought by itself, so
                        # it is used alone and never added to `denk_gezaehlt`.
                        erzeugt_gelesen = ausgang or (token_gezaehlt + denk_gezaehlt)
                        if eingang and kontextdrossel.faellig(
                            eingang, erzeugt_gelesen, time.monotonic()
                        ):
                            yield kontext_stueck(eingang, True, erzeugt_gelesen)

        except ProviderFehler:
            raise
        except (httpx.HTTPError, OSError) as fehler:
            raise provider_error(
                "fehler.anbieter_nicht_erreichbar", name=self.name, detail=fehler
            ) from fehler

        # A stream that simply ends — the body closes, whether or not a
        # `message_stop` said goodbye — without a single `message_delta`
        # having named its `stop_reason` (the rule: `require_stream_end`).
        # In this protocol the reason travels in `message_delta`, and a
        # goodbye without a reason names none. Checked before any assembled
        # tool call is handed out and before the stats.
        require_stream_end(ende_grund, self.name)
        ablehnung: dict[str, Any] = {}
        if antwortende.abgelehnt(ende_grund):
            log.warning(
                "%s declined to answer (%s): %s",
                display_model(reported_model or anfrage.modell),
                ablehnung_kategorie or "no category",
                ablehnung_erklaerung or "no explanation",
            )
            ablehnung["abgelehnt"] = True
            if ablehnung_erklaerung:
                ablehnung["ablehnung_erklaerung"] = ablehnung_erklaerung

        if fertige:
            yield Stueck(sorte="tool_call", werkzeugaufrufe=fertige)

        dauer = time.monotonic() - beginn
        tokens = ausgang or token_gezaehlt
        yield Stueck(sorte="stats", daten={
            "dauer_sekunden": round(dauer, 3),
            "tokens": tokens,
            # How many chunks the answer came in. Reported for the same
            # reason the OpenAI-compatible route reports it: the merge over
            # tool rounds adds it up, and a field only one of the two
            # providers fills is a column that empties itself depending on
            # who answered.
            "haeppchen": token_gezaehlt,
            # The speed, and the counts the speed is made of, worked out by
            # the shared function — see the import at the top of this file.
            # `output_tokens` goes in under the name that function knows it
            # by, and it is the same quantity: everything the model wrote.
            #
            # What comes back is three things this file used to get wrong.
            # The divisor is the writing of the ANSWER instead of the whole
            # request, so a long prompt no longer presses the number down
            # (measured on a large prompt with a short answer: 9.23 tok/s
            # where the answer itself ran at 40). `erzeugte_tokens` and
            # `erzeugungs_sekunden` come out named the way the merge in
            # `app/api/v1/generierung.py` reads them, so an answer over
            # several tool rounds keeps its speed instead of losing it
            # entirely. And the source says which of the tiers the number
            # came from — `gemessen` or `geschaetzt` — rather than naming
            # the vendor, which said nothing about how good the reading is
            # and ranked below every real tier for exactly that reason.
            **tempo_ermitteln(
                zeitmessung=None,
                nutzung={"completion_tokens": ausgang},
                haeppchen=token_gezaehlt,
                dauer=dauer,
                erstes_token_nach=erstes_token_nach,
                denken_gesehen=denken_gesehen,
            ),
            # After the spread, not before: `input_tokens` stands complete
            # in `message_start` and this route knows it exactly, while the
            # shared function only ever sees what was handed to it under
            # `usage` — which here is the output half alone.
            "prompt_tokens": eingang,
            "gesamt_tokens": eingang + tokens if eingang is not None else None,
            # Only where the server named it: a zero would claim a miss.
            **({"cache_tokens": cache_gelesen} if cache_gelesen is not None else {}),
            # The same number the running answer sent, under the name every
            # route uses for it — the finished answer's own reading, so the
            # window shows one figure and not two. `message_start` names both
            # halves and nothing later changes them, so this is that reading
            # and not a second one.
            **(
                {"prompt_cache_percent": cache_anteil}
                if cache_anteil is not None
                else {}
            ),
            "erstes_token_nach_sekunden": (
                round(erstes_token_nach, 3) if erstes_token_nach is not None else None
            ),
            # `max_tokens` is this API's word for the ceiling being reached;
            # the reading of it is the same one every other backend gets.
            "ende_grund": ende_grund,
            "abgeschnitten": antwortende.abgeschnitten(ende_grund),
            "kontextfenster_voll": antwortende.kontextfenster_voll(ende_grund),
            # A refusal is its own reading, with the explanation Anthropic
            # gave for it where it gave one: the window says that nothing
            # is coming and why, instead of showing an empty answer.
            **ablehnung,
            # The model that answered. A wire that names none leaves the one
            # this request asked for; neither is ever an empty name, and
            # neither is ever a path (``display_model``). Beside the endpoint
            # above because the two answer different questions — which
            # server, and which model on it.
            "modell": display_model(reported_model or anfrage.modell),
        })
