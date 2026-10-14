"""Provider for everything that speaks the OpenAI interface.

This covers: mlx_lm.server, mlx_vlm.server, llama.cpp (llama-server),
Ollama, vLLM and the cloud providers with an OpenAI-compatible API.

Two quirks from practice are baked in here:

  * ``mlx_lm.server`` interprets the ``model`` field as a HuggingFace id and
    answers a short name with 404. For such servers the field is omitted as
    long as the server reports no id.
  * The servers deliver the chain of thought differently: as its own field
    (``delta.reasoning`` or ``delta.reasoning_content``) or as markers in
    the text. Both are brought to the same output here.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import logging
import re
import time
from typing import Any, AsyncIterator, Protocol, TypeVar

import httpx

from app import (
    answer_limit_resend,
    antwortende,
    denkdopplung,
    dialekterkennung,
    dialektverdacht,
    samplingwerte,
)
from app.config import EndpointConfig
from app.denkstufen import wirt_von
from app.kontextverbrauch import als_zahl
from app.parameter import uebersetzen
from app.pfade import ist_pfad, pfad_zu_anzeigename
from app.providers import openai_responses
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
    zaehlung,
    provider_error,
    require_stream_end,
    zeitlimit,
)
from app.reasoning import ReasoningParser

log = logging.getLogger(__name__)


# Below these, a speed says nothing. There are two of them because two
# separate errors make the number unreadable — one sitting in the counter,
# one in the divisor — and neither guard catches the other's case.
#
# Both live here rather than beside the division, because the division
# happens twice: once per round in this file, and once more over the summed
# rounds in `app/api/v1/generierung.py`. A floor written in one of the two
# is a floor the other one lifts again — measured, with the same 1000 tok/s
# coming back for any answer that took more than one round.


# The COUNTER. Below this many tokens the count is systematically too high
# for the stretch of time beside it.
#
# What is measured is the span from the FIRST token to the last, so the
# writing of that first one happened before the span opened and is not in
# it. The numerator counts n tokens, the denominator holds n-1 tokens'
# worth of writing, and the reading comes out too high by n/(n-1): twice
# over at two tokens, half again at three, four percent at twenty-five. No
# length of elapsed time takes that error away, which is why the second
# floor cannot stand in for this one.
KLEINSTE_MESSBARE_MENGE = 3

# The DIVISOR. Below this many seconds the timing is too coarse to divide
# by, however many tokens stand over it.
#
# Both ends of the span are moments read off `time.monotonic()`, and the
# number that goes out is rounded to three places — the window shows those
# three places and the division has to agree with what it shows (see
# `erzeugungs_sekunden` below). So the divisor carries half a millisecond
# of uncertainty no matter how long it is, and what that costs depends only
# on how SHORT it is: one percent at fifty milliseconds, ten percent at
# five, fifty percent at one. Under a twentieth of a second the rounding of
# our own number moves the answer by more than the last digit it is printed
# to.
#
# Measured, and the reason this floor exists at all: one chunk written in
# 1.169 s with the first token at 1.168 s leaves a thousandth of a second
# of generating, and one divided by that reads as 1000 tokens per second.
# The token floor above never caught that and never could — three rounds of
# one token each add up to three tokens over three milliseconds, clear the
# count, and report the same 1000 again.
KLEINSTE_MESSBARE_ZEIT = 0.05


def _denk_tokens(nutzung: dict[str, Any]) -> int | None:
    """How many of the completion tokens were thinking, where it is reported.

    The OpenAI convention carries it under
    ``usage.completion_tokens_details.reasoning_tokens``. ``None`` where the
    server says nothing — which is the honest answer, not a guess: without
    the split there is no way to know, and inventing a share would be worse
    than leaving the number whole.

    ``None`` and ``0`` are two different answers on purpose. "Nothing was
    thought" is a statement about the run; "nothing is being said" is one
    about the server, and only the second leaves the count unusable beside
    a divisor that keeps the thinking out.
    """
    einzelheiten = nutzung.get("completion_tokens_details")
    if not isinstance(einzelheiten, dict):
        return None
    # A negative number is not a small count, it is nonsense — and now that
    # ``None`` carries a meaning of its own, clamping it to zero would let a
    # broken field pass itself off as "nothing was thought".
    return zaehlung(einzelheiten.get("reasoning_tokens"))


def _tempo_zahl(wert: Any) -> float | None:
    """A speed a model server states outright, or ``None``.

    Not a count, so not ``zaehlung``: this one is a rate with a fraction.
    Same boundary rule, though — the value is the server's, and a ``NaN``,
    an infinity or a negative rate is a number ``json.loads`` accepts and
    nothing here can use.
    """
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    if not math.isfinite(wert) or wert <= 0:
        return None
    return round(float(wert), 2)


# The OpenAI model families that refuse ``max_tokens`` and take the answer
# limit only as ``max_completion_tokens`` — whoever serves them. Behind a
# proxy or a gateway the host is somebody else's; the model is still the
# same, and it refuses the old name there as well.
COMPLETION_TOKEN_FAMILIES: tuple[str, ...] = ("gpt-4o", "gpt-4.1", "gpt-5", "o1", "o3", "o4")


def wants_completion_tokens(model: str | None) -> bool:
    """Does a model of this name take the answer limit only under the newer
    name? Asked of the name without a vendor prefix, so ``openai/gpt-5-mini``
    counts like ``gpt-5-mini``; a name that merely contains a family's does
    not count."""
    name = (model or "").strip().lower().rsplit("/", 1)[-1]
    return name.startswith(COMPLETION_TOKEN_FAMILIES)


def display_model(wert: str | None) -> str | None:
    """The model as it may be written down — and never an empty name.

    Three things wrong with a name taken straight off a server's answer. It
    can BE a path: a locally started mlx or llama.cpp reports its model as
    the folder it was loaded from, and that folder carries the operator's
    name (``app/pfade.py``). This is the reading side, where such a name is
    about to be stored, answered over the API and written into the log — the
    three places the model picker's own name is kept clean for; the server
    itself still gets the unchanged id.

    It can carry whitespace, and a name with a line break in it would forge
    a line in a text-format log — the value goes in there verbatim
    (app/main.py). Every run of whitespace becomes one space, which also
    makes the name below what it is.

    And it can be missing, which is not a name but the absence of one — a
    line reading "Answer from omlx ()" would look like a fact and say
    nothing, and so would one naming a single blank. The caller decides what
    stands there instead.
    """
    if not wert:
        return None
    wert = " ".join(wert.split())
    if not wert:
        return None
    return pfad_zu_anzeigename(wert) if ist_pfad(wert) else wert


def whole_prompt(timings: object, usage: object) -> int | None:
    """The whole prompt as the server counted it — or ``None`` where it named
    only a part of it.

    ``usage.prompt_tokens`` is the whole prompt wherever a server sends it.
    Without it, llama.cpp's ``timings`` count the prompt in two halves:
    ``prompt_n``, what had to be read in fresh, and ``cache_n``, what stood
    in the cache. Only their sum is the prompt (measured: 524 + 977 = 1501);
    ``prompt_n`` alone leaves the cached part out and is a floor, which is
    not this function's answer. One reader for the live reading and for the
    round's stats, so the number under a running answer and the one it
    ends with are counted the same way."""
    if isinstance(usage, dict) and (reported := zaehlung(usage.get("prompt_tokens"))):
        return reported
    if isinstance(timings, dict):
        fresh = zaehlung(timings.get("prompt_n"))
        cached = zaehlung(timings.get("cache_n"))
        if fresh is not None and cached is not None and fresh + cached:
            return fresh + cached
    return None


def tempo_ermitteln(
    *,
    zeitmessung: dict[str, Any] | None,
    nutzung: dict[str, Any] | None,
    haeppchen: int,
    dauer: float,
    erstes_token_nach: float | None,
    denken_gesehen: bool = False,
    whole_prompt_tokens: int | None = None,
) -> dict[str, Any]:
    """Calculates the generation speed the way the model servers do themselves.

    The same formula applies everywhere — generated tokens divided by the
    pure **generation time**. Prompt processing is explicitly outside of it:
    it gets its own number via ``erstes_token_nach_sekunden`` and is never
    included. Before, the total duration went into the denominator, so the
    reported number sank the longer the chat got — on the first call after a
    model start it was off by a factor of 48 (measured against mlx_vlm and
    llama.cpp).

    Three sources, best first:

      * ``server``    — the ``timings`` block from llama.cpp/mlx. Tokens and
        generation time come from the machine where it happened.
      * ``gemessen``  — ``usage.completion_tokens`` (the truth counted by the
        server's tokenizer) against our own timing.
      * ``geschaetzt`` — just counted chunks. A chunk is not necessarily a
        token; that is why this tier is named the way it is.

    ``erstes_token_nach`` is the moment the ANSWER started, not the moment
    anything at all started: the caller withholds it while a chain of
    thought is still running. It anchors the divisor, so what is measured
    here is the writing of the answer — the thinking before it sits outside
    the measurement the same way the prompt processing does.

    ``denken_gesehen`` says whether this run thought at all. The divisor
    cannot show that by itself — a late first token looks the same whether
    a long prompt or a long think came before it — and the ``gemessen``
    tier needs to know, because its counter can only follow the divisor out
    of the thinking where the server names the split.
    """
    zeitmessung = zeitmessung or {}
    nutzung = nutzung or {}

    # What we can measure ourselves: everything after the first token. If
    # that moment is missing, nothing arrived anyway. Never below zero,
    # and zero is a real reading: on a clock that counts in steps of
    # about 16 ms (Windows), a one-chunk answer can stamp the same moment
    # for its first token and for the end of the run — an answer written
    # in no measurable time, not one that took the whole run.
    eigene_erzeugungszeit = dauer
    if erstes_token_nach is not None:
        eigene_erzeugungszeit = max(0.0, dauer - erstes_token_nach)

    denk_tokens = _denk_tokens(nutzung)
    # Whether `completion_tokens` can be brought onto the same definition as
    # the divisor at all. It can where the server names the split, and it
    # can where nothing was thought, because then there is nothing to take
    # off. Everything else is a run that thought behind a silent server.
    nutzung_passt_zum_teiler = denk_tokens is not None or not denken_gesehen

    tokens: int | None = None
    erzeugungszeit: float | None = None
    quelle = "geschaetzt"

    # Every count below is read through `zaehlung`, never through a bare
    # `int()`: these fields are the server's, and a NaN or an infinity in
    # one of them is a number `json.loads` accepts and `int()` refuses.
    vorhergesagt = zaehlung(zeitmessung.get("predicted_n"))
    gezaehlt = zaehlung(nutzung.get("completion_tokens"))
    # A speed the server states OUTRIGHT: measured on llama.cpp
    # (`predicted_per_second`, 78.85 beside 51 tokens in 634 ms) and named
    # `generation_tokens_per_second` by an mlx server. It WINS over dividing
    # the server's own pair ourselves — same measurement, but rounded once
    # where it happened instead of twice on the way out, and it is the number
    # the server writes into its journal, so the window and the log can be
    # held against each other.
    genannt = _tempo_zahl(zeitmessung.get("predicted_per_second")) or _tempo_zahl(
        nutzung.get("generation_tokens_per_second")
    ) or _tempo_zahl(zeitmessung.get("generation_tokens_per_second"))
    if vorhergesagt and zeitmessung.get("predicted_ms"):
        tokens = vorhergesagt
        erzeugungszeit = float(zeitmessung["predicted_ms"]) / 1000
        quelle = "server"
    elif gezaehlt and nutzung_passt_zum_teiler:
        # The answer's tokens, which is not the same as everything the model
        # produced: `completion_tokens` counts the chain of thought in with
        # it, and the divisor beside it does not — it starts at the moment
        # the ANSWER started. Where the split is missing and the run thought
        # anyway, the two count different stretches of time, and nothing
        # here can join them: measured against an mlx server, 163 tok/s
        # stood where the server itself reported 17 to 26.
        #
        # Nothing is estimated to close that gap. This tier simply drops out
        # and the chunk count below takes over — it counts answer chunks and
        # only those, so it stands on the divisor's own definition, and it
        # says in its name that a chunk is not a token. An estimate that
        # admits to being one beats a real token count over the wrong
        # stretch of time.
        # Never below zero: a server that reports more thinking than it
        # reports tokens is contradicting itself, and a negative count would
        # travel on into the window as a number nobody can read.
        tokens = max(0, gezaehlt - (denk_tokens or 0))
        erzeugungszeit = eigene_erzeugungszeit
        quelle = "gemessen"
    elif haeppchen:
        tokens = haeppchen
        erzeugungszeit = eigene_erzeugungszeit

    # Which tier the TOKEN COUNT came from, kept apart from the name of the
    # number below. The two part company as soon as a server states a rate
    # outright, and reading the name where the tier was meant exported a
    # chunk count as summable tokens — one layer up.
    zaehlstufe = quelle

    # A speed the server stated is a SERVER reading, even where no pair of
    # numbers came with it to divide: it was counted and timed where it
    # happened.
    #
    # But only where it measures the SAME STRETCH as what stands beside it.
    # On the `gemessen` tier this side has the answer's own tokens against
    # its own clock, and the rate the server states covers the whole
    # generation, the chain of thought included — substituting the one for
    # the other put a whole-generation figure under "measured over the
    # writing of the answer", and left the merge recomputing a
    # different quantity from the pair for any answer of more than one
    # round. So it stands in on the server tier, where it is the same
    # measurement rounded once instead of twice, and on the chunk tier,
    # where this side has nothing at all.
    genannte = genannt if zaehlstufe != "gemessen" else None
    if genannte:
        quelle = "server"

    # How big the prompt was is told by `usage` — and completely — or by
    # the caller, who read both halves of the round's `timings`
    # (``whole_prompt``). `prompt_n` alone only counts what really had to be
    # newly processed; in an ongoing chat the rest sits in the cache and is
    # missing there (measured: 524 instead of 1501 with 977 cached), so it
    # is the last resort.
    prompt_tokens = (
        whole_prompt_tokens
        or zaehlung(nutzung.get("prompt_tokens"))
        or zaehlung(zeitmessung.get("prompt_n"))
    )

    # Rounded first, divided afterwards — the window and the division have to
    # be looking at the same number, otherwise the two do not add up on
    # screen. And a round that rounds to 0.0 s is not a short stretch of
    # time, it is none: its tokens would all fall on nothing. Found in the
    # database, all of them beside `erzeugungs_sekunden` of 0.0: 23617,
    # 10797, 6904 tok/s.
    erzeugungs_sekunden = round(erzeugungszeit or 0, 3) or None

    # A handful of tokens is not a measurement of speed, and neither is a
    # handful of milliseconds. Both floors have to hold: they guard the two
    # ends of the same division against two errors that have nothing to do
    # with each other, and either one alone leaves the other's case
    # reporting nonsense (the reasons are written out at the constants).
    #
    # A floor on the RESULT would be a number this file invented, and it
    # refuses that everywhere else. So the speed simply is not reported —
    # the duration and the wait for the first token are still true and still
    # go out.
    #
    # And only where the number is OURS. A server saying "two tokens in a
    # hundred milliseconds" counted at the source and stamped no moment we
    # could have got wrong, so neither error applies to it: its twenty per
    # second is a fact, however few tokens and however few milliseconds it
    # counts.
    #
    # And never out of counted CHUNKS. A chunk is not a token — the tier says
    # so in its own name — and with speculative decoding one carries several:
    # measured on an mlx server with MTP, 156 chunks over 19.3 s were reported
    # as 8.06 tok/s while the same answer's own numbers said 64.42, a factor of
    # eight. The tier stays as the last resort for the duration
    # and the wait for the first token, both of which are true whatever a
    # chunk holds; what it cannot say is a speed, so it says none. Better
    # nothing than a number that is wrong.
    genug = bool(tokens) and (
        zaehlstufe == "server"
        or (
            zaehlstufe != "geschaetzt"
            and tokens >= KLEINSTE_MESSBARE_MENGE
            and (erzeugungs_sekunden or 0) >= KLEINSTE_MESSBARE_ZEIT
        )
    )

    # Real tokens over the real seconds they took, or neither. The pair is
    # what the rounds of an answer are summed from, so both halves have to
    # come off the same stretch of time and the same tier — the seconds of a
    # round whose chunks were dropped stayed in the divisor on their own and
    # reported 2.56 tok/s for an answer that ran at 78.85.
    zaehlbar = bool(tokens) and zaehlstufe != "geschaetzt"

    return {
        "erzeugte_tokens": tokens,
        # The same count, but only where it really counted TOKENS. This is
        # the one that may be summed over the rounds of an answer
        # (`app/api/v1/generierung.py`): a chunk count added into a
        # numerator whose denominator is real seconds is the eightfold
        # error, one layer further up.
        "tempo_tokens": tokens if zaehlbar else None,
        # Its other half. Summed beside the tokens and divided only
        # afterwards; a round that contributes no tokens contributes no
        # seconds either.
        "tempo_sekunden": erzeugungs_sekunden if zaehlbar else None,
        "erzeugungs_sekunden": erzeugungs_sekunden,
        "prompt_tokens": prompt_tokens if prompt_tokens else None,
        # A speed the server states itself wins over our own division of its
        # own pair. It is the same measurement, but done where it happened
        # and rounded once instead of twice — measured on llama.cpp with
        # speculative decoding: 51 tokens and 634.131 ms divide to 80.42,
        # while the server reports 78.85 for the same answer and writes that
        # number into its journal. The window has to be able to say the same
        # thing as the log, or the two cannot be held against each other.
        "tokens_pro_sekunde": (
            genannte
            if genannte
            else (
                round(tokens / erzeugungs_sekunden, 2)
                if genug and erzeugungs_sekunden
                else None
            )
        ),
        "tempo_quelle": quelle if tokens or genannte else None,
    }


def einlesen_ermitteln(
    zeitmessung: dict[str, Any] | None, nutzung: dict[str, Any] | None
) -> dict[str, Any]:
    """What of the prompt came out of the server's cache, and how long the
    rest took to read in — only the fields the server actually named.

    * ``cache_tokens`` — llama-server's own ``timings.cache_n``, or the
      OpenAI form ``usage.prompt_tokens_details.cached_tokens`` where
      ``timings`` names no cache. The server's own count wins over the
      OpenAI form even when it is a 0: measured, one server reports
      ``cached_tokens`` as 0 on every request, and a 0 beside a ``cache_n``
      of 977 is a missing word, not a miss.
    * ``eingelesen_tokens`` and ``einlese_sekunden`` — llama-server's
      ``timings.prompt_n`` and ``timings.prompt_ms``: the part that had to be
      read in fresh, and its time.

    A server that names none of it gets none of it in its stats, not a zero:
    a zero would claim the cache missed.
    """
    # `isinstance`, not truthiness alone: this reads a field straight off a
    # server's packet, and `{"timings": "on"}` is a shape a proxy can send —
    # `or {}` would keep the string and the `.get` below would end the whole
    # round with an AttributeError.
    #
    # The names read here are the same ones the round's stand reads
    # (`_PromptStand`) — a new spelling belongs in both readers.
    zeitmessung = zeitmessung if isinstance(zeitmessung, dict) else {}
    cache = zaehlung(zeitmessung.get("cache_n"))
    if cache is None:
        einzelheiten = nutzung.get("prompt_tokens_details") if isinstance(nutzung, dict) else None
        cache = zaehlung(einzelheiten.get("cached_tokens")) if isinstance(einzelheiten, dict) else None
    eingelesen = zaehlung(zeitmessung.get("prompt_n"))
    dauer = _dauer_ms(zeitmessung.get("prompt_ms"))
    raus: dict[str, Any] = {}
    if cache is not None:
        raus["cache_tokens"] = cache
    if eingelesen is not None:
        raus["eingelesen_tokens"] = eingelesen
    if dauer is not None:
        raus["einlese_sekunden"] = round(dauer / 1000, 3)
    return raus


def _prompt_cache_percent(
    zeitmessung: dict[str, Any] | None, nutzung: dict[str, Any] | None = None
) -> int | None:
    """How much of the prompt the server already had, in whole percent — or
    ``None`` where nothing named a cache level.

    The cached half comes from ``einlesen_ermitteln`` above — the reader
    that knows the servers' names for it, the same names the round's stand
    reads (`_PromptStand`). What it is a share OF depends on the shape it
    arrived in, and the two shapes are not the same number:

    * With ``usage`` the server names the whole prompt beside the cached
      half, and those two divide.
    * Without it, llama.cpp's ``timings`` names the two halves — ``cache_n``
      and ``prompt_n`` — and only their sum is the prompt. Dividing the
      cached half by ``prompt_tokens`` there would be wrong by a wide
      margin wherever ``prompt_tokens`` falls back to ``prompt_n``, the
      freshly-read half alone (see ``tempo_ermitteln``): measured, 977 of
      1501 cached read as 186 %.

    A server that names one half and nothing else leaves this silent rather
    than wrong.
    """
    teile = einlesen_ermitteln(zeitmessung, nutzung)
    gelesen = teile.get("cache_tokens")
    if gelesen is None:
        return None
    frisch = teile.get("eingelesen_tokens")
    nenner = (
        gelesen + frisch
        if frisch is not None
        else zaehlung((nutzung or {}).get("prompt_tokens"))
    )
    if not nenner:
        return None
    return round(gelesen * 100 / nenner)


def _cache_share(
    zeitmessung: dict[str, Any] | None, nutzung: dict[str, Any] | None
) -> dict[str, Any]:
    """The finished answer's cache share for its stats — under the same key
    the running answer sends it under, so one reading has one name whoever
    computed it. Nothing where the server named no cache."""
    anteil = _prompt_cache_percent(zeitmessung, nutzung)
    return {} if anteil is None else {"prompt_cache_percent": anteil}


def _dauer_ms(wert: object) -> float | None:
    """A duration in milliseconds off a server's packet, or None — `json.loads`
    accepts a literal NaN or Infinity, and neither is a duration anything here
    can use, whatever field it travels under."""
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    if not math.isfinite(wert) or wert < 0:
        return None
    return float(wert)


_Num = TypeVar("_Num", int, float)


def _successor(alt: _Num | None, neu: _Num | None) -> _Num | None:
    """The value that stands after one packet's word: the newer one — except
    a zero where a value already stands (the one exception `_PromptStand`
    explains)."""
    if neu is None:
        return alt
    if neu == 0 and alt is not None:
        return alt
    return neu


class _PromptStand:
    """What the round has said so far about the prompt — one field per word,
    each keeping the last value it was named with; a packet that names a word
    not at all leaves the standing one alone.

    The one exception is a zero arriving where a value already stands: the
    halves of a prompt are constants of its request, so a later 0 beside a
    980 is a hole in the wire, not news — taken, it would wipe the running
    share and let the number vanish exactly when the answer ends (measured:
    a late `timings {prompt_n: 0, cache_n: 0}` turned a standing 98 into
    silence). A zero that comes FIRST is kept: a real miss is a real "0 %".

    The two readings of the cache share come from this one stand: the number
    under the running answer and the number in the round's stats. Read off
    each packet alone they were not the same number — a closing packet that
    names only ``usage`` pulled the running share down, and a server whose
    ``predicted_*`` pair never arrived in one piece left the finished share
    out although the running one had stood there all along (measured against
    a stub server sending such packets: 98, 90, 98).

    The halves have two spellings on the wire and both are kept: llama.cpp's
    ``timings`` names ``cache_n``, ``prompt_n`` and ``prompt_ms``, the OpenAI
    ``usage`` names the whole prompt and the cached part of it. Which of the
    two cache spellings wins is decided where they divide —
    ``einlesen_ermitteln``.

    The views hand exactly that out in the shapes the share readers already
    understand (``einlesen_ermitteln``, ``_prompt_cache_percent``,
    ``_cache_share``), so nothing there needed a second way of reading. The
    round's stats read the views too: one stand, one set of numbers, so
    ``cache_tokens`` and ``prompt_cache_percent`` can never contradict each
    other. The names read here are the same ones ``einlesen_ermitteln``
    reads for one packet — a new spelling belongs in both readers.
    """

    def __init__(self) -> None:
        self.cache_n: int | None = None
        self.prompt_n: int | None = None
        self.prompt_ms: float | None = None
        self.prompt_tokens: int | None = None
        self.cached_tokens: int | None = None

    def note(self, zeitmessung: object, nutzung: object) -> None:
        """One packet's word on the prompt — every field it named, kept."""
        if isinstance(zeitmessung, dict):
            self.cache_n = _successor(self.cache_n, zaehlung(zeitmessung.get("cache_n")))
            self.prompt_n = _successor(self.prompt_n, zaehlung(zeitmessung.get("prompt_n")))
            self.prompt_ms = _successor(self.prompt_ms, _dauer_ms(zeitmessung.get("prompt_ms")))
        if isinstance(nutzung, dict):
            self.prompt_tokens = _successor(
                self.prompt_tokens, zaehlung(nutzung.get("prompt_tokens"))
            )
            einzelheiten = nutzung.get("prompt_tokens_details")
            if isinstance(einzelheiten, dict):
                self.cached_tokens = _successor(
                    self.cached_tokens, zaehlung(einzelheiten.get("cached_tokens"))
                )

    @property
    def timings(self) -> dict[str, float]:
        """The prompt's words in the ``timings`` shape — empty while the
        round named none."""
        raus: dict[str, float] = {}
        if self.cache_n is not None:
            raus["cache_n"] = self.cache_n
        if self.prompt_n is not None:
            raus["prompt_n"] = self.prompt_n
        if self.prompt_ms is not None:
            raus["prompt_ms"] = self.prompt_ms
        return raus

    @property
    def usage(self) -> dict[str, Any]:
        """The whole prompt and its cached part in the ``usage`` shape —
        empty while the round named none."""
        raus: dict[str, Any] = {}
        if self.prompt_tokens is not None:
            raus["prompt_tokens"] = self.prompt_tokens
        if self.cached_tokens is not None:
            raus["prompt_tokens_details"] = {"cached_tokens": self.cached_tokens}
        return raus


def _denktempo_wert(messung: dict[str, Any] | None) -> float | None:
    """A live speed while the model thinks or writes the answer, or ``None``.

    Deliberately not routed through ``tempo_ermitteln``: that function
    anchors on ``erstes_token_nach``, the moment the ANSWER starts, and has
    no notion of a speed for the stretch before it. This reads the server's
    own outright figure for the current instant instead — the same field
    ``tempo_ermitteln`` prefers for the finished answer, just read early and
    without a divisor of our own.

    ``None`` where the server has said nothing usable yet: a request without
    ``timings_per_token`` (`_koerper_bauen`), or a server that does not
    support it at all. Nothing here estimates in that case — the caller
    leaves the reading as it was.

    Held to the same two floors as the block below before it is trusted for
    the finished answer, ``KLEINSTE_MESSBARE_MENGE`` and
    ``KLEINSTE_MESSBARE_ZEIT`` — a live reading is read mid-stream, on
    purpose, before the round has had the chance to accumulate the way the
    end-of-round figure always has by the time anything reads it. Measured
    on mlx: the same field jumps from zero via 6 up to 14625 tok/s over the
    first few chunks before it settles, `predicted_n`/`predicted_ms` present
    and non-zero throughout — presence alone does not mean the sample is
    large enough yet.
    """
    if not isinstance(messung, dict):
        return None
    vorhergesagt = zaehlung(messung.get("predicted_n"))
    dauer_ms = messung.get("predicted_ms")
    # The same boundary `_tempo_zahl` guards below: `json.loads` accepts a
    # literal NaN or Infinity, and neither is a duration anything here can
    # use, whatever field it travels under.
    if (
        isinstance(dauer_ms, bool)
        or not isinstance(dauer_ms, (int, float))
        or not math.isfinite(dauer_ms)
    ):
        return None
    if not vorhergesagt or vorhergesagt < KLEINSTE_MESSBARE_MENGE:
        return None
    if dauer_ms / 1000 < KLEINSTE_MESSBARE_ZEIT:
        return None
    return _tempo_zahl(messung.get("predicted_per_second"))


class _DenktempoDrossel:
    """How often a live speed reading may go out, while thinking and while
    the answer is written.

    Its own class rather than a second use of ``KontextDrossel``: that one's
    parameters are named and typed for a context reading (a prompt size and
    a token count), and a speed in tenths of a token per second is neither —
    reusing it would mean passing the speed through a slot called
    ``prompt_tokens``, which reads correctly today only because both happen
    to be throttled the same way, and breaks silently the day either one
    changes for its own reason.
    """

    def __init__(self, mindestabstand: float = 0.5) -> None:
        self.mindestabstand = mindestabstand
        self._zeitpunkt = 0.0
        self._letzter_wert: float | None = None

    def faellig(self, wert: float, jetzt: float) -> bool:
        """Whether this reading may go out — and notes it as gone out."""
        if wert == self._letzter_wert:
            return False
        if self._letzter_wert is not None and jetzt - self._zeitpunkt < self.mindestabstand:
            return False
        self._zeitpunkt, self._letzter_wert = jetzt, wert
        return True


class _AnteilDrossel:
    """How often a cache share may go out: whenever it says something new.

    The other way round than the speed beside it, and deliberately so: a
    speed moves with every packet and is therefore held back by time, while a
    share is a property of the prompt — a second reading of the same number
    adds nothing, and one that differs is news however fast it arrives. One
    throttle for both would either hide a change or repeat a standing number
    on every packet.
    """

    def __init__(self) -> None:
        self._letzter_wert: int | None = None

    def faellig(self, wert: int) -> bool:
        """Whether this reading may go out — and notes it as gone out."""
        if wert == self._letzter_wert:
            return False
        self._letzter_wert = wert
        return True


class _WerkzeugSammler:
    """Reassembles streamed tool calls.

    The servers do not send a call in one piece but in fragments: id and
    name in the first packet, the arguments spread character by character
    over the following ones ("{", "\\"ort\\":\\"", "Berlin", "\\"", "}"). It is
    held together via the ``index`` field. Only when the stream ends is the
    call complete — nothing may be executed before that.
    """

    def __init__(self) -> None:
        self._teile: dict[int, dict[str, str]] = {}

    def aufnehmen(self, rohaufrufe: list[dict[str, Any]]) -> list[int]:
        """Takes fragments in and reports which calls grew because of them.

        The return value is pure information: it exists so the stream can say
        something about a call while its argument is still being written. What
        is complete, and when, is still decided by ``fertige_aufrufe`` alone.
        """
        beruehrt: list[int] = []
        for rohaufruf in rohaufrufe:
            index = rohaufruf.get("index", 0)
            eintrag = self._teile.setdefault(index, {"id": "", "name": "", "argumente": ""})
            if kennung := rohaufruf.get("id"):
                eintrag["id"] = kennung
            funktion = rohaufruf.get("function") or {}
            if name := funktion.get("name"):
                eintrag["name"] = name
            if (argumente := funktion.get("arguments")) is not None:
                eintrag["argumente"] += argumente
            if index not in beruehrt:
                beruehrt.append(index)
        return beruehrt

    def stand(self, index: int) -> tuple[str, int]:
        """Name and characters arrived so far for one call under construction."""
        eintrag = self._teile.get(index)
        if eintrag is None:
            return "", 0
        return eintrag["name"], len(eintrag["argumente"])

    @property
    def leer(self) -> bool:
        return not self._teile

    def fertige_aufrufe(self) -> list[Werkzeugaufruf]:
        aufrufe: list[Werkzeugaufruf] = []
        for index, eintrag in sorted(self._teile.items()):
            if not eintrag["name"]:
                continue
            rohargumente = eintrag["argumente"].strip() or "{}"
            try:
                argumente = json.loads(rohargumente)
            except json.JSONDecodeError:
                log.warning(
                    "Tool call '%s' has unreadable arguments: %r",
                    eintrag["name"],
                    rohargumente[:200],
                )
                argumente = {}
            if not isinstance(argumente, dict):
                argumente = {"wert": argumente}
            aufrufe.append(
                Werkzeugaufruf(
                    id=eintrag["id"] or f"aufruf_{index}",
                    name=eintrag["name"],
                    argumente=argumente,
                )
            )
        return aufrufe


# "Never asked", told apart from a ``None`` that means "asked, and no route
# had a number to give".
_UNGEFRAGT = object()

# A model on this machine may stay silent for many minutes while it reads a
# long prompt before the first word comes, so its read timeout is wider than
# the 600 s of a cloud endpoint.
LOCAL_READ_TIMEOUT = 1800.0


class _Paketquelle(Protocol):
    """What both wires have in common: one event in, the packets it is worth.

    The chat wire's events ARE the packets, one for one. The Responses wire
    reports each item on its own and is translated first
    (app/providers/openai_responses.py).
    """

    def pakete(self, ereignis: dict[str, Any]) -> tuple[dict[str, Any], ...]: ...


class _Durchreiche:
    """The chat wire: nothing to translate."""

    def pakete(self, ereignis: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        return (ereignis,)


_DURCHREICHE: _Paketquelle = _Durchreiche()


def _statusname(zeile: dict[str, Any]) -> str:
    """What a status row calls its model. Two spellings are in the wild."""
    return str(zeile.get("id") or zeile.get("model") or "")


def _status_unwrapped(data: Any) -> Any:
    """A status answer with its wrapper opened: the rows come as a list, as
    a mapping of model name to row, or inside ``models`` or ``data`` beside
    other figures (a memory ceiling, a load estimate)."""
    if isinstance(data, dict):
        for wrapper in ("models", "data"):
            if isinstance(data.get(wrapper), list):
                return data[wrapper]
    return data


def _status_rows(data: Any) -> list[tuple[str, dict[str, Any]]]:
    """Every status row with the name it carries, in either shape."""
    data = _status_unwrapped(data)
    if isinstance(data, dict):
        return [(str(name), row) for name, row in data.items() if isinstance(row, dict)]
    if isinstance(data, list):
        return [(_statusname(row), row) for row in data if isinstance(row, dict)]
    return []


def _ollama_name(name: Any) -> str:
    """An Ollama model name with its tag spelt out. Names take the form
    ``model:tag`` and a missing tag means ``latest``, so ``llama3.2`` and
    ``llama3.2:latest`` are one model. A colon before the last slash belongs
    to a host's port, not to a tag."""
    name = str(name or "").strip()
    if name and name.rfind(":") <= name.rfind("/"):
        return f"{name}:latest"
    return name


class OpenAIKompatiblerProvider(Provider):
    def __init__(self, endpunkt: EndpointConfig, timeout: float = 600.0) -> None:
        super().__init__(endpunkt)
        self.timeout = timeout
        # The context size out of the server's own routes, once. Discovery
        # asks again on every pass for as long as the answer is unknown, and
        # the search below costs up to three requests — so an endpoint that
        # carries the number nowhere would pay all three on every pass for
        # the life of the process, against a metered API in the cloud case.
        # The search only runs for a reachable endpoint, so a ``None`` here
        # is the server's own answer, not an outage.
        self._kontext: Any = _UNGEFRAGT
        # Whether OpenAI has refused the thinking summary for this endpoint
        # (app/providers/openai_responses.py, `lehnt_zusammenfassung_ab`).
        # Held here and nowhere else: discovery keeps one provider per
        # endpoint, so the next request to it goes out without the summary
        # straight away, until the service starts again.
        self._ohne_zusammenfassung = False
        # And WHICH model that answer belongs to. A multi-model server names
        # the one it is currently running, and swapping it changes the window
        # — so the remembered answer is only good for the name it was found
        # under. Without this the endpoint would carry the size of whatever
        # happened to be loaded at the first look, for ever.
        self._kontext_fuer: str | None = None
        # Whether the number the last call to ``kontextgroesse`` returned is
        # one that is not kept because loading the model changes it.
        self._kontext_vorlaeufig = False
        # Whether the answers seen along the way carry a local serving
        # stack's fingerprints (app/dialektverdacht.py). Noted while the
        # context search is already reading them, never fetched for its own
        # sake — the question is worth no request of its own.
        self._ortsspuren = False
        # One search at a time, so a second caller waits for the answer
        # instead of setting off the same three requests beside it.
        self._kontext_schloss = asyncio.Lock()
        # The output limit out of the model list, remembered exactly like the
        # context size above and for the same reason — the answer belongs to
        # the model it was found under, and "the list names none" is an
        # answer worth keeping so the request is not repeated every pass.
        self._antwortgrenze: Any = _UNGEFRAGT
        self._antwortgrenze_fuer: str | None = None
        self._antwortgrenze_schloss = asyncio.Lock()

    @property
    def _kopfzeilen(self) -> dict[str, str]:
        """Access key, in case the endpoint demands one.

        The key is never in config.yaml, only the NAME of its environment
        variable. It is read fresh on every request — so a key changed in
        .env takes effect without a restart.

        If the variable is missing, requests go out without the header and
        the provider answers with 401. That is intentional: a silent
        workaround would be worse than a clear error message.
        """
        name = self.endpunkt.api_key_env
        if not name:
            return {}
        wert = os.getenv(name, "").strip()
        return {"Authorization": f"Bearer {wert}"} if wert else {}

    # --- Reachability ----------------------------------------------------

    async def erreichbar(self, timeout: float = 3.0) -> bool:
        adresse = f"{self.endpunkt.base_url}{self.endpunkt.health_path}"
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=self._kopfzeilen) as client:
                antwort = await client.get(adresse)
            # 401/403 means: the server is up but will not let us in —
            # usually a missing or wrong key. Reporting that as "reachable"
            # would be a lie: the endpoint would appear in the model picker
            # and fail on every request. Better honestly unreachable.
            if antwort.status_code in (401, 403):
                return False
            return antwort.status_code < 500
        except (httpx.HTTPError, OSError):
            return False

    async def modellname(self, timeout: float = 3.0) -> str | None:
        """What the model is called on the server — the server itself is asked.

        The same address that is already queried for the sign of life
        ({base_url}{health_path}, i.e. /v1/models); before, the answer was
        just thrown away.

        Two formats occur:

        * {"data": [{"id": ...}]} — the usual OpenAI layout, this is how
          mlx_lm.server answers.
        * {"models": [{"name": ...}]} — this is how llama-server answers.

        **File paths are deferred, not discarded.** mlx_lm.server often
        reports the same model twice: once under its id and once under the
        path in the HuggingFace cache — then the clean id wins.
        mlx_vlm.server, on the other hand, sometimes reports **only one**
        entry, and that is the path to the locally loaded model (not a
        HuggingFace cache path, but for example
        ``/Users/you/models/Qwen3.6-27B-MLX-8bit``). If there were no
        fallback tier here, ``modellname()`` would find nothing,
        ``anfrage.modell`` would stay empty, the ``model`` field would be
        omitted from the request — and mlx_vlm.server, unlike mlx_lm.server,
        strictly requires it and answers without it with 422.

        **The return value here is always the full, unchanged id** — even
        when it is a path. Tested: mlx_vlm.server accepts in the ``model``
        field only exactly what it reported itself; a shortened name is
        misunderstood as a HuggingFace repo and fails. The shortening for
        the UI (the full path would reveal the local user name) therefore
        happens NOT here but exclusively at display time in
        ``EndpunktZustand.anzeigename`` (``discovery.py``) — the server
        always gets the original.
        """
        adresse = f"{self.endpunkt.base_url}{self.endpunkt.health_path}"
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=self._kopfzeilen) as client:
                antwort = await client.get(adresse)
            if antwort.status_code >= 400:
                return None
            daten = antwort.json()
        except (httpx.HTTPError, OSError, ValueError):
            return None

        eintraege = daten.get("data") or daten.get("models") or []
        if not isinstance(eintraege, list):
            return None
        pfad_rueckfall: str | None = None
        for eintrag in eintraege:
            if not isinstance(eintrag, dict):
                continue
            kennung = eintrag.get("id") or eintrag.get("name") or eintrag.get("model")
            if not isinstance(kennung, str) or not kennung.strip():
                continue
            kennung = kennung.strip()
            if ist_pfad(kennung):
                if pfad_rueckfall is None:
                    pfad_rueckfall = kennung
                continue
            return kennung
        return pfad_rueckfall

    async def modelle_auflisten(self, timeout: float = 3.0) -> list[str]:
        """Every model the server reports, in the order it reports them.

        Same address as the sign of life. A local server names the one model
        it has loaded; a provider in the cloud names its whole catalogue.
        Paths are dropped here, unlike in `modellname`: they are how a local
        server refers to its own file, never something to choose from a list.
        """
        adresse = f"{self.endpunkt.base_url}{self.endpunkt.health_path}"
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=self._kopfzeilen) as client:
                antwort = await client.get(adresse)
            if antwort.status_code >= 400:
                return []
            daten = antwort.json()
        except (httpx.HTTPError, OSError, ValueError):
            return []

        eintraege = daten.get("data") or daten.get("models") or []
        if not isinstance(eintraege, list):
            return []
        namen: list[str] = []
        for eintrag in eintraege:
            if not isinstance(eintrag, dict):
                continue
            kennung = eintrag.get("id") or eintrag.get("name") or eintrag.get("model")
            if not isinstance(kennung, str) or not kennung.strip():
                continue
            kennung = kennung.strip()
            if ist_pfad(kennung) or kennung in namen:
                continue
            namen.append(kennung)
        return namen

    async def _json_holen(self, adresse: str, timeout: float) -> Any | None:
        """One GET, and nothing but the parsed answer or ``None``.

        Every source below is supplementary: a server that does not know the
        route answers 404, and a 404 is an answer, not a fault.
        """
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=self._kopfzeilen) as client:
                antwort = await client.get(adresse)
            if antwort.status_code != 200:
                return None
            return antwort.json()
        except (httpx.HTTPError, OSError, ValueError):
            return None

    @staticmethod
    def _zahl(wert: Any) -> int | None:
        """A context size out of a model list — a positive count or nothing."""
        zahl = als_zahl(wert)
        return zahl if zahl is not None and zahl > 0 else None

    def _modelleintrag(
        self, daten: Any, modellname: str | None = None
    ) -> dict[str, Any] | None:
        """The entry of the model this endpoint means, out of a model list.

        Three readings in this order, and the first that lands wins:

        1. the configured name — the explicit statement. A name that was set
           and did NOT match ends the search: the single-entry shortcut below
           is "nobody said which one, so the only one must be it", and it
           holds only while nobody said. A pinned name that misses means the
           server is serving something other than the endpoint thinks, and
           falling through would hand back that other model's numbers under
           this endpoint's name with nothing downstream able to tell.
        2. the name the SERVER reports for itself. This is what a multi-model
           server needs: a list of thirty entries and no configured name went
           through both older readings and came out empty, so the window
           stayed blank while the number sat in the list all along. A miss
           here does fall through — this name is the program's own
           observation, not somebody's declaration.
        3. exactly one entry in the list — the single-server case.

        Otherwise nothing. Nothing is invented at any step.
        """
        eintraege = (daten or {}).get("data") if isinstance(daten, dict) else None
        if not isinstance(eintraege, list):
            return None
        passende = [e for e in eintraege if isinstance(e, dict)]
        gesucht = (self.endpunkt.modell or "").strip()
        if gesucht:
            for eintrag in passende:
                if str(eintrag.get("id") or "") == gesucht:
                    return eintrag
            return None
        gemeldet = (modellname or "").strip()
        if gemeldet:
            for eintrag in passende:
                if str(eintrag.get("id") or "") == gemeldet:
                    return eintrag
        return passende[0] if len(passende) == 1 else None

    def ortsspuren(self) -> bool:
        return self._ortsspuren

    def kontext_vorlaeufig(self) -> bool:
        return self._kontext_vorlaeufig

    async def kontextgroesse(
        self, timeout: float = 3.0, modellname: str | None = None
    ) -> int | None:
        """Queries the context size from the server.

        A configured value wins. Then three sources are asked in turn, and
        the first number ends the search:

        1. ``/props`` — llama.cpp answers it with ``n_ctx``.
        2. ``/v1/models`` — the vLLM convention puts ``max_model_len`` on
           every entry, and an MLX multi-model server carries it there too.
           This is why a server with no ``/props`` at all was showing an
           empty context bar: the number was there, nobody asked for it.
        3. ``/v1/models/status`` — the same server's own status route names
           ``max_context_window`` per model.

        Nothing is invented anywhere along the way: where no source carries
        a number, there is none, and the window shows no percentage rather
        than a made-up one.

        ``/props`` sits at the root, not under ``/v1`` — hence the version
        segment is cut off.

        ``modellname`` is what the server reports it is currently running,
        which is the only way a multi-model endpoint with no configured name
        can be found in a list of thirty.

        The search runs at most once per model, its "there is no number"
        remembered along with a number: discovery asks again on every pass
        until it knows, and three requests per pass for ever is what a server
        carrying the number nowhere used to cost. Once per MODEL, not once
        per provider — swapping the model on the server changes the window,
        and an answer kept past that swap would be somebody else's number.

        One kind of answer is not kept: one that changes with the loading.
        LM Studio names a model that is not loaded with the most it can take,
        and loaded it has a smaller window; Ollama's list of running models
        is empty before the first chat. Those hold for this pass only, and
        the next one asks again.
        """
        # A number that is entered or kept is final: whatever an earlier
        # search of another model found provisional says nothing about it.
        if self.endpunkt.context_tokens:
            self._kontext_vorlaeufig = False
            return self.endpunkt.context_tokens
        gefragt_fuer = (modellname or "").strip() or None
        if self._kontext is not _UNGEFRAGT and self._kontext_fuer == gefragt_fuer:
            self._kontext_vorlaeufig = False
            return self._kontext
        # The lock, not just the check above: filled in only once the search
        # is through, so a second caller during it waits for the answer
        # rather than starting the same three requests beside it.
        async with self._kontext_schloss:
            if self._kontext is _UNGEFRAGT or self._kontext_fuer != gefragt_fuer:
                zahl, merken = await self._kontext_suchen(timeout, gefragt_fuer)
                # What is not kept is provisional: discovery asks again on
                # the next pass, so the loaded model's own window replaces it.
                self._kontext_vorlaeufig = not merken
                if not merken:
                    return zahl
                self._kontext = zahl
                self._kontext_fuer = gefragt_fuer
            else:
                self._kontext_vorlaeufig = False
            return self._kontext

    async def _kontext_suchen(
        self, timeout: float, modellname: str | None = None
    ) -> tuple[int | None, bool]:
        """The sources, asked in turn: the number (``None`` when none carries
        one) and whether it may be kept — ``False`` for an answer that
        changes once the model is loaded."""
        wurzel = re.sub(r"/v\d+$", "", self.endpunkt.base_url)
        daten = await self._json_holen(f"{wurzel}/props", timeout)
        if isinstance(daten, dict):
            wert = (daten.get("default_generation_settings") or {}).get("n_ctx") or daten.get(
                "n_ctx"
            )
            if (zahl := self._zahl(wert)) is not None:
                return zahl, True

        liste = await self._json_holen(f"{self.endpunkt.base_url}/models", timeout)
        self._ortsspuren = self._ortsspuren or dialektverdacht.spuren_lesen(liste, None)
        eintrag = self._modelleintrag(liste, modellname)
        if eintrag is not None:
            if (zahl := self._zahl(eintrag.get("max_model_len"))) is not None:
                return zahl, True
            # Finding the ROW is not finding the NUMBER. A bare entry carrying
            # nothing but an id says only that the model exists, and the
            # status route beside it is where such a server keeps the size.
            # Stopping here used to make that third source unreachable for
            # every server whose list names its models without measuring
            # them, which is the ordinary shape once the reported name is
            # read: the row is now almost always found.

        stand = await self._json_holen(f"{self.endpunkt.base_url}/models/status", timeout)
        self._ortsspuren = self._ortsspuren or dialektverdacht.spuren_lesen(None, stand)
        eintrag = self._statuseintrag(stand, modellname)
        if eintrag is not None:
            if (zahl := self._zahl(eintrag.get("max_context_window"))) is not None:
                return zahl, True

        # LM Studio's own model list: the window the model was loaded with,
        # otherwise the most it can take. Its OpenAI-shaped list beside it
        # names no size at all.
        lmstudio = await self._json_holen(f"{wurzel}/api/v0/models", timeout)
        eintrag = self._modelleintrag(lmstudio, modellname)
        if eintrag is not None:
            # A model that is not loaded names the most it can take, which is
            # no promise of the window it will have once it is loaded.
            not_loaded = str(eintrag.get("state") or "").strip().lower() == "not-loaded"
            for feld in ("loaded_context_length", "max_context_length"):
                if (zahl := self._zahl(eintrag.get(feld))) is not None:
                    return zahl, not not_loaded

        # Ollama's running models: the window the loaded one was started
        # with. Its /v1/models carries no size either. Only the row of the
        # model asked for — /api/ps lists whatever happens to be loaded, and
        # the one row there may well be another model's. Compared with the
        # tag spelt out: /api/ps names "llama3.2:latest" where "llama3.2"
        # was asked for.
        running = await self._json_holen(f"{wurzel}/api/ps", timeout)
        rows = running.get("models") if isinstance(running, dict) else None
        wanted = _ollama_name(self.endpunkt.modell or modellname)
        for row in rows if isinstance(rows, list) else []:
            if (
                wanted
                and isinstance(row, dict)
                and wanted in (_ollama_name(row.get("model")), _ollama_name(row.get("name")))
            ):
                return self._zahl(row.get("context_length")), True
        # A list that answered and does not name the model: it is not loaded
        # yet, and the row comes with the first chat. A server with no such
        # route at all gave no list, and that "no number" is kept.
        return None, not isinstance(rows, list)

    async def context_per_model(self, timeout: float = 3.0) -> dict[str, int] | None:
        """The window of every model the list names: ``max_model_len`` on
        each entry, else ``max_context_window`` on its status row — the same
        two sources, in the same order, the search for one model reads.
        ``None`` when the list itself did not answer."""
        listing = await self._json_holen(f"{self.endpunkt.base_url}/models", timeout)
        if listing is None:
            return None
        windows: dict[str, int] = {}
        entries = listing.get("data") if isinstance(listing, dict) else None
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            model_id = str(entry.get("id") or "").strip()
            if model_id and (number := self._zahl(entry.get("max_model_len"))) is not None:
                windows[model_id] = number
        status = await self._json_holen(f"{self.endpunkt.base_url}/models/status", timeout)
        for model_id, row in _status_rows(status):
            model_id = model_id.strip()
            if model_id and model_id not in windows:
                if (number := self._zahl(row.get("max_context_window"))) is not None:
                    windows[model_id] = number
        return windows

    # What a model list calls the longest answer it allows, in the order the
    # field names appeared in the wild. Read as a list rather than as one
    # name because the same list route is served by providers that each
    # picked a different word for it; the first one an entry carries wins.
    _ANTWORTFELDER = ("max_completion_tokens", "max_output_tokens", "max_tokens")

    async def answer_limit_per_model(self, timeout: float = 3.0) -> dict[str, int] | None:
        """The longest answer of every model the list names, read from each
        entry under the same field names as for one model. ``None`` when the
        list itself did not answer."""
        listing = await self._json_holen(f"{self.endpunkt.base_url}/models", timeout)
        if listing is None:
            return None
        limits: dict[str, int] = {}
        entries = listing.get("data") if isinstance(listing, dict) else None
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            model_id = str(entry.get("id") or "").strip()
            if not model_id:
                continue
            for feld in self._ANTWORTFELDER:
                if (number := self._zahl(entry.get(feld))) is not None:
                    limits[model_id] = number
                    break
        return limits

    async def hoechste_antwort(
        self, timeout: float = 3.0, modellname: str | None = None
    ) -> int | None:
        """The longest answer this model allows, out of the model list.
        ``/props`` is not asked: it describes a whole server rather than one
        model. Nor is oMLX's status row: the ``max_tokens`` there is the
        length the server's profile uses when a request names none, and a
        request may ask for more — a default, not a limit. Where the list
        names none, the answer is unlimited as far as this side knows, and
        the context window alone decides what fits (``app/antwortgrenze.py``).
        """
        gefragt_fuer = (modellname or "").strip() or None
        if self._antwortgrenze is not _UNGEFRAGT and self._antwortgrenze_fuer == gefragt_fuer:
            return self._antwortgrenze
        async with self._antwortgrenze_schloss:
            if (
                self._antwortgrenze is _UNGEFRAGT
                or self._antwortgrenze_fuer != gefragt_fuer
            ):
                self._antwortgrenze = await self._antwortgrenze_suchen(timeout, gefragt_fuer)
                self._antwortgrenze_fuer = gefragt_fuer
            return self._antwortgrenze

    async def _antwortgrenze_suchen(
        self, timeout: float, modellname: str | None = None
    ) -> int | None:
        """The model list, read once. ``None`` where it names no limit."""
        liste = await self._json_holen(f"{self.endpunkt.base_url}/models", timeout)
        eintrag = self._modelleintrag(liste, modellname)
        if eintrag is not None:
            for feld in self._ANTWORTFELDER:
                if (zahl := self._zahl(eintrag.get(feld))) is not None:
                    return zahl
        return None

    def _statuseintrag(
        self, daten: Any, modellname: str | None = None
    ) -> dict[str, Any] | None:
        """The status row of the model this endpoint means.

        The route answers as a list, as a mapping of model name to row, or
        wrapped in ``models`` or ``data`` — all of those shapes are in the
        wild, and picking the row is the same job in each. The wrapped ones
        carry more than the rows (a memory ceiling, a load estimate), so the
        wrapper has to be opened before anything is counted.

        The same three readings in the same order as the model list next
        door: configured name, then the name the server reports, then the
        single row. The two searches have to agree, or the answer would
        depend on which route happened to carry the number.
        """
        daten = _status_unwrapped(daten)
        gesucht = (self.endpunkt.modell or "").strip()
        gemeldet = (modellname or "").strip()
        if isinstance(daten, dict):
            if gesucht:
                zeile = daten.get(gesucht)
                return zeile if isinstance(zeile, dict) else None
            if gemeldet and isinstance(daten.get(gemeldet), dict):
                return daten[gemeldet]
            zeilen = [z for z in daten.values() if isinstance(z, dict)]
        elif isinstance(daten, list):
            zeilen = [z for z in daten if isinstance(z, dict)]
            if gesucht:
                for zeile in zeilen:
                    if _statusname(zeile) == gesucht:
                        return zeile
                return None
            if gemeldet:
                for zeile in zeilen:
                    if _statusname(zeile) == gemeldet:
                        return zeile
        else:
            return None
        # The single-row shortcut says "nobody named one, so the only one must
        # be it". A configured name that missed has already returned above; a
        # reported name that missed falls through to here on purpose, being
        # the program's own observation rather than somebody's statement.
        return zeilen[0] if len(zeilen) == 1 else None

    async def denkquellen(self, timeout: float = 3.0) -> dict[str, Any]:
        """The model family an MLX server names for itself, per model.

        ``/v1/models/status`` carries ``config_model_type`` for every model
        it holds — the very ``model_type`` out of the model's own
        ``config.json``, which is also the key the family table is written
        in. So one table serves this server, llama.cpp's architecture
        metadatum and a plain file name alike, and no hand switch is needed
        for a family that is already listed.

        Per model, not one for the address: such a server holds a whole
        shelf, and a Llama that cannot think sits on it beside a Qwen that
        can. One answer for all of them would be wrong for most.

        Only asked where a chat template cannot answer instead: a server
        that serves ``/props`` has already said everything this could add.
        """
        if self.endpunkt.parameter_dialect != "mlx":
            return {}
        stand = await self._json_holen(f"{self.endpunkt.base_url}/models/status", timeout)
        familien: dict[str, str] = {}
        # Where each model's files lie (``model_path``): its chat template
        # is there, and on this machine it can be read (app/discovery.py).
        paths: dict[str, str] = {}
        for model_id, row in _status_rows(stand):
            model_id = model_id.strip()
            if not model_id:
                continue
            # A model is listed under its alias where it has one: the family
            # and the files belong to that name as much as to the id.
            names = [model_id]
            alias = row.get("model_alias")
            if isinstance(alias, str) and alias.strip():
                names.append(alias.strip())
            for name in names:
                if isinstance(row.get("config_model_type"), str):
                    familien[name] = str(row["config_model_type"])
                if isinstance(row.get("model_path"), str) and row["model_path"].strip():
                    paths[name] = row["model_path"].strip()
        sources: dict[str, Any] = {}
        if familien:
            sources["familien"] = familien
        if paths:
            sources["template_paths"] = paths
        return sources

    async def mlx_erkennen(self, timeout: float = 3.0) -> bool | None:
        """Whether this address is an oMLX server (app/dialekterkennung.py).

        One GET of ``/v1/models/status``, the route ``denkquellen`` reads the
        model families from. Any answer that is not that server's — a 404,
        an error page, another shape — is a no. ``None`` only when nothing
        answered at all: a timeout says nothing about the server, and the
        discovery asks again on its next pass.
        """
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=self._kopfzeilen) as client:
                antwort = await client.get(f"{self.endpunkt.base_url}/models/status")
        except (httpx.HTTPError, OSError):
            return None
        if antwort.status_code != 200:
            return False
        try:
            stand = antwort.json()
        except ValueError:
            return False
        return dialekterkennung.ist_mlx_statusblatt(stand)

    # --- Streaming -------------------------------------------------------

    @staticmethod
    def _nachricht_bauen(nachricht: ChatNachricht) -> dict[str, Any]:
        eintrag: dict[str, Any] = {"role": nachricht.role, "content": nachricht.content}
        bild_urls = nachricht.alle_bild_urls()
        if bild_urls:
            # OpenAI image format: content becomes an array of text and
            # images, one part per image. The text part is dropped when
            # nothing was typed — an empty text confuses some servers.
            teile: list[dict[str, Any]] = []
            if nachricht.content:
                teile.append({"type": "text", "text": nachricht.content})
            for url in bild_urls:
                teile.append({"type": "image_url", "image_url": {"url": url}})
            eintrag["content"] = teile
        if nachricht.werkzeugaufrufe:
            eintrag["tool_calls"] = [
                {
                    "id": aufruf.id,
                    "type": "function",
                    "function": {
                        "name": aufruf.name,
                        "arguments": json.dumps(aufruf.argumente, ensure_ascii=False),
                    },
                }
                for aufruf in nachricht.werkzeugaufrufe
            ]
        if nachricht.werkzeugaufruf_id:
            eintrag["tool_call_id"] = nachricht.werkzeugaufruf_id
        # The round's own items for the Responses wire; the chat route takes
        # them out again before anything is sent (`streamen`).
        if nachricht.reasoning_items:
            eintrag[openai_responses.DENKTEILE] = nachricht.reasoning_items
        if nachricht.message_items:
            eintrag[openai_responses.TEXTTEILE] = nachricht.message_items
        return eintrag

    def _koerper_bauen(self, anfrage: Generierungsanfrage) -> dict[str, Any]:
        koerper: dict[str, Any] = {
            "messages": [self._nachricht_bauen(n) for n in anfrage.nachrichten],
            "stream": True,
        }
        if self.endpunkt.send_usage_option:
            # Without this request most servers send no token counts while
            # streaming — and the context display would stay empty.
            koerper["stream_options"] = {"include_usage": True}
        if self.endpunkt.parameter_dialect == "llama_cpp":
            # llama.cpp keeps `timings` off every chunk but the last unless
            # asked — measured on a llama.cpp server: without this flag the chain of
            # thought streams with no `timings` block at all, and with it
            # every chunk carries one, `predicted_n` growing from the first
            # thought onward. This is what lets a live speed be read out
            # while the model is still thinking.
            koerper["timings_per_token"] = True
        if anfrage.werkzeuge:
            koerper["tools"] = anfrage.werkzeuge
            koerper["tool_choice"] = "auto"
        # Only send what is actually set — otherwise null values override the
        # server's defaults.
        # First the three main values, then everything else — both under our
        # own names, translated into the backend's dialect. What the server
        # does not know is dropped instead of making it reject with an error.
        eigene = dict(anfrage.parameter)
        if anfrage.temperature is not None:
            eigene["temperature"] = anfrage.temperature
        if anfrage.top_p is not None:
            eigene["top_p"] = anfrage.top_p
        if anfrage.max_tokens is not None:
            eigene["max_tokens"] = anfrage.max_tokens
        koerper.update(uebersetzen(self.endpunkt.parameter_dialect, eigene))
        # OpenAI's newer chat models reject max_tokens and expect
        # max_completion_tokens. Two things say a request reaches one: the
        # HOST is OpenAI's own — every current model there accepts the new
        # name — or the MODEL is of a family that refuses the old one,
        # whoever serves it (`wants_completion_tokens`). Every other
        # request keeps max_tokens, the name other OpenAI-compatible servers
        # want. The host is asked as a host: a proxy whose path carries
        # `api.openai.com` and a server named `api.openai.com.example.net`
        # are somebody else's machine, and there only the model can ask for
        # the new name. Which address is OpenAI's own is read once, for this
        # rewrite and for the route to its other wire
        # (app/providers/openai_responses.py).
        wirt = wirt_von(self.endpunkt.base_url)
        if "max_tokens" in koerper and (
            openai_responses.ist_openai(wirt) or wants_completion_tokens(anfrage.modell)
        ):
            koerper["max_completion_tokens"] = koerper.pop("max_tokens")
        # Only when the server has reported an id. Without one the field is
        # dropped: llama.cpp ignores it anyway, and mlx_lm.server answers an
        # invented id with 404.
        if anfrage.modell:
            koerper["model"] = anfrage.modell
        koerper.update(anfrage.zusatz)
        # Last, after everything that can set a value: what this model
        # refuses is taken out of the finished body (app/samplingwerte.py).
        samplingwerte.bereinigen(koerper)
        return koerper

    async def _pakete(
        self, antwort: httpx.Response, leser: _Paketquelle
    ) -> AsyncIterator[dict[str, Any]]:
        """The packets of one stream, in the one shape the reader below knows.

        Both wires are read here: the chat wire already sends that shape, the
        Responses wire sends events that are translated first
        (app/providers/openai_responses.py). Reading them in one place is what
        lets the speed, the context reading, the tool assembly and the "a
        stream names its end" guard stay written once for both.
        """
        async for zeile in antwort.aiter_lines():
            if not zeile or not zeile.startswith("data:"):
                continue
            nutzlast = zeile[5:].strip()
            if nutzlast == "[DONE]":
                break
            try:
                ereignis = json.loads(nutzlast)
            except json.JSONDecodeError:
                log.warning("Unreadable packet from %s: %r", self.id, nutzlast[:200])
                continue
            for paket in leser.pakete(ereignis):
                failure = self._stream_error(paket)
                if failure is not None:
                    raise failure
                yield paket

    def _stream_error(self, paket: dict[str, Any]) -> ProviderFehler | None:
        """The error a packet carries instead of a piece of the answer.

        A server that fails in the middle of a stream cannot answer with a
        status any more: the 200 is long sent. It writes one last packet
        with an ``error`` object — ``code``, ``message``, ``type`` — and
        closes the stream without naming an end. Read as an ordinary packet
        it holds no choice, so it passed unnoticed, and all the round could
        say was that the stream reported no ending.

        It ends the stream in the form of a refused request instead, the
        one sentence both come from: the object's code where the status
        stands, its message as the text. None for every packet without one.
        """
        error = paket.get("error")
        if not error:
            return None
        if isinstance(error, dict):
            code = error.get("code")
            kind = error.get("type")
            message = error.get("message") or kind or json.dumps(error, ensure_ascii=False)
        else:
            code, kind, message = None, None, error
        return provider_error(
            "fehler.anbieter_antwortet_mit",
            # A status only where the server gave a number: a code in words
            # is shown in its place below, but is no HTTP status to act on.
            status=code if isinstance(code, int) and not isinstance(code, bool) else None,
            name=self.name,
            status_code=code if code not in (None, "") else (kind or "error"),
            text=str(message)[:400],
            # The packet as it came, the way a refused request carries its
            # body: the `type` ("exceed_context_size_error") is what says a
            # full context where the sentence names no context at all.
            rohtext=json.dumps(paket, ensure_ascii=False),
        )

    async def _oeffnen(
        self,
        client: httpx.AsyncClient,
        adresse: str,
        koerper: dict[str, Any],
        antwortenweg: bool,
    ) -> httpx.Response:
        """The open stream of one request — or the error that ends it.

        Two cases are answered by sending again, each exactly once:

        * OpenAI refusing the thinking summary on its Responses API (a 400
          naming ``summary``, which the documentation ties to an unverified
          organisation). The same request then goes out once more without
          the summary; when that one goes through, this endpoint sends none
          from now on.
        * A server refusing ``max_tokens`` on the chat route (a 400 naming
          the field: a newer model under a name of its own). The same
          request then goes out once more with the same limit as
          ``max_completion_tokens``. Nothing is remembered: every request
          goes out first as it always did.

        Raised before the first packet, so nothing of the refused attempt has
        reached the caller.
        """
        antwort = await client.send(client.build_request("POST", adresse, json=koerper), stream=True)
        if antwort.status_code < 400:
            return antwort
        rohtext = (await antwort.aread()).decode("utf-8", "replace")
        await antwort.aclose()
        # The two refusals cannot meet: the old limit field exists on the
        # chat route only, the summary on the Responses route only.
        again: dict[str, Any] | None = None
        summary_refused = False
        if answer_limit_resend.refused_max_tokens(antwort.status_code, rohtext, koerper):
            log.warning(
                "%s refused max_tokens; asking once more with max_completion_tokens: %s",
                self.name,
                rohtext[:200],
            )
            again = answer_limit_resend.with_completion_tokens(koerper)
        elif antwortenweg and openai_responses.lehnt_zusammenfassung_ab(
            antwort.status_code, rohtext, koerper
        ):
            log.warning(
                "%s refused the thinking summary; asking once more without it: %s",
                self.name,
                rohtext[:200],
            )
            again = openai_responses.ohne_zusammenfassung(koerper)
            summary_refused = True
        if again is not None:
            antwort = await client.send(
                client.build_request("POST", adresse, json=again), stream=True
            )
            if antwort.status_code < 400:
                if summary_refused:
                    # Remembered only once the request without it went
                    # through: a 400 that merely mentions the word must not
                    # take the summary away for good.
                    self._ohne_zusammenfassung = True
                return antwort
            rohtext = (await antwort.aread()).decode("utf-8", "replace")
            await antwort.aclose()
        raise provider_error(
            "fehler.anbieter_antwortet_mit",
            status=antwort.status_code,
            rohtext=rohtext,
            name=self.name,
            status_code=antwort.status_code,
            text=rohtext[:400],
        )

    async def streamen(self, anfrage: Generierungsanfrage) -> AsyncIterator[Stueck]:
        koerper = self._koerper_bauen(anfrage)
        # A request to OpenAI's own host with a thinking stage or tools goes
        # over its Responses API — the body above, rebuilt in the shape the
        # other wire reads — and everything else stays on the chat route
        # (app/providers/openai_responses.py).
        antwortleser: _Paketquelle = _DURCHREICHE
        antwortenweg = openai_responses.antwortenroute(wirt_von(self.endpunkt.base_url), koerper)
        if antwortenweg:
            koerper = openai_responses.koerper_umbauen(
                koerper, zusammenfassung=not self._ohne_zusammenfassung
            )
            adresse = f"{self.endpunkt.base_url}/responses"
            antwortleser = openai_responses.Leser()
        else:
            adresse = f"{self.endpunkt.base_url}/chat/completions"
            # Items only the other wire reads; no chat server knows them.
            for nachricht in koerper["messages"]:
                nachricht.pop(openai_responses.DENKTEILE, None)
                nachricht.pop(openai_responses.TEXTTEILE, None)
        log.info("%s: request goes to %s", self.name, adresse)
        parser = ReasoningParser(
            self.endpunkt.reasoning_format
            if self.endpunkt.reasoning_format != "native"
            else "none"
        )
        # A server stopped at the ceiling mid-thought sends its whole chain
        # of thought once more as the answer; this notices that one piece
        # and nothing else (app/denkdopplung.py).
        wache = denkdopplung.Wache()

        beginn = time.monotonic()
        erstes_token_nach: float | None = None
        token_gezaehlt = 0
        # The chain of thought, counted separately from `token_gezaehlt`:
        # the live context reading below grows with it, the speed at the end
        # never does — one counter cannot answer both.
        denk_gezaehlt = 0
        # Whether anything was thought at all — in either of the two shapes.
        # Nothing is counted with it; it only tells the speed below that
        # `usage.completion_tokens` covers a stretch the divisor does not.
        denken_gesehen = False
        nutzung: dict[str, Any] = {}
        zeitmessung: dict[str, Any] = {}
        ende_grund: str | None = None
        # Which model answered, as the SERVER names it. The OpenAI answer
        # object carries a `model` field for exactly this ("The model used
        # for the chat completion"), one server may serve several, and the
        # endpoint's own id names the SERVER and not the model — a proof
        # asked for one particular model has nothing to show without this
        # (app/main.py, protocol line "Answer from …"). Taken from the first
        # packet that names one, so a stream that repeats it 400 times is
        # read once.
        reported_model: str | None = None
        # The prompt as the SERVER counted it, for the live context reading
        # below. Read out of every `timings` block, not only out of the
        # complete one collected above: mlx sends the block on every chunk,
        # and this half of it is usable long before `predicted_*` is.
        #
        # A floor, never a prompt size — see the reading below.
        prompt_gezaehlt: int | None = None
        # What this round has said about the prompt's halves, packet for
        # packet. The live cache share and the finished one both read THIS,
        # so the number under the running answer and the number in the
        # stats are the same one (`_PromptStand`).
        stand = _PromptStand()
        sammler = _WerkzeugSammler()
        drossel = WerkzeugFortschrittsDrossel()
        kontextdrossel = KontextDrossel()
        # How often the live speed of the chain of thought may go out, and
        # how often the cache share beside it — two readings, two conditions
        # (see _AnteilDrossel).
        denktempodrossel = _DenktempoDrossel()
        anteildrossel = _AnteilDrossel()

        def _denktempo_falls_faellig(
            messung: dict[str, Any] | None,
            worte: bool = True,
        ) -> Stueck | None:
            # ONE place rather than one per branch, the same reasoning as
            # the context reading below: this is called exactly once per
            # packet, and the two readings inside keep their own conditions
            # and their own throttles. `worte` says whether the packet
            # produced thinking or answer text — the SPEED is a reading of
            # words being written and is held back where there were none,
            # while the cache share is a property of the prompt and goes out
            # for any packet that names it.
            daten: dict[str, Any] = {}
            denkwert = _denktempo_wert(messung) if worte else None
            if denkwert is not None and denktempodrossel.faellig(denkwert, time.monotonic()):
                daten["tokens_pro_sekunde"] = denkwert
                daten["tempo_quelle"] = "server"
            # And what the server already had of this prompt, in the same
            # breath: read off the round's stand, not off this one packet —
            # a packet that names no half must not change a number that
            # stands, and the finished answer's own share is read off the
            # same stand when the round ends (`_cache_share` below). Its OWN
            # condition, not the speed's: a server that names a share but no
            # usable speed still has something to say under the running
            # answer, and one that names no cache says nothing at all.
            cache_anteil = _prompt_cache_percent(stand.timings, stand.usage)
            if cache_anteil is not None and anteildrossel.faellig(cache_anteil):
                daten["prompt_cache_percent"] = cache_anteil
            return Stueck(sorte="denktempo", daten=daten) if daten else None

        try:
            async with httpx.AsyncClient(
                timeout=zeitlimit(
                    self.timeout,
                    self.endpunkt.timeout_enabled,
                    LOCAL_READ_TIMEOUT if self.endpunkt.group == "local" else None,
                ),
                headers=self._kopfzeilen,
            ) as client:
                antwort = await self._oeffnen(client, adresse, koerper, antwortenweg)
                async with contextlib.aclosing(antwort):
                    async for paket in self._pakete(antwort, antwortleser):
                        # Whether THIS packet carried words — thinking or
                        # answer text. The cache share below goes out for
                        # every packet that names one; the SPEED only where
                        # words were produced, the reading it had before the
                        # share joined it: a packet of tool-argument deltas
                        # is not the answer moving.
                        worte_gesehen = False
                        if teil := paket.get(openai_responses.TEILPAKET):
                            # A finished item for the next round; it says
                            # nothing the reading below would count.
                            yield Stueck("response_item", daten={"eintrag": teil})
                            continue
                        if verbrauch := paket.get("usage"):
                            nutzung = verbrauch

                        # llama.cpp and mlx include their own timing
                        # (`timings`) — not an OpenAI standard, but the best
                        # source there is: only the server itself knows how
                        # long the pure generating took, without the prompt
                        # processing before it. Only the complete block at
                        # the end is taken; mlx sends an interim value on
                        # every chunk, and it jumps from zero via 6 up to
                        # 14625 tok/s (measured).
                        messung = paket.get("timings")
                        if (
                            isinstance(messung, dict)
                            and messung.get("predicted_n")
                            and messung.get("predicted_ms")
                        ):
                            zeitmessung = messung
                        # The prompt half of the same block, taken without
                        # that condition — it is filled from the first chunk
                        # on, while `predicted_*` only becomes usable later.
                        if isinstance(messung, dict):
                            prompt_gezaehlt = (
                                zaehlung(messung.get("prompt_n")) or prompt_gezaehlt
                            )
                        # And the round's stand, from this same packet: every
                        # word about the prompt it named, kept for the
                        # readings below and for the round's stats.
                        stand.note(messung, nutzung)

                        auswahl = (paket.get("choices") or [{}])[0]
                        # Why the server stopped. It arrives on the last
                        # chunk of a choice and is empty on every one before
                        # it, so the last one that says anything is the
                        # answer. Kept for the metrics below, where the run
                        # reads it — nothing else in the stream needs it.
                        if wort := auswahl.get("finish_reason"):
                            ende_grund = wort
                        delta = auswahl.get("delta") or {}

                        # Which model the server says answered, taken from a
                        # packet that carries something the answer SAYS —
                        # text, a tool call, the round's end — and never from
                        # one that says nothing. Measured on oMLX, a stream
                        # opens with a keepalive whose own `model` is the
                        # literal guard word: `{"created": 0, "model":
                        # "keepalive", "delta": {"role": "assistant",
                        # "content": ""}}`, and the real name stands only in
                        # the packets behind it (measured on a recorded raw
                        # stream). A reader keeping the first
                        # name it sees therefore latches onto the guard's own
                        # word and never reaches the name this field exists
                        # for. Read once: the first real packet has it.
                        if reported_model is None and (
                            delta.get("content")
                            or delta.get("tool_calls")
                            or auswahl.get("finish_reason")
                        ):
                            benannt = paket.get("model")
                            if isinstance(benannt, str) and benannt:
                                reported_model = benannt

                        # Dedicated field for the chain of thought (Gemma 4 and others).
                        gedanke = delta.get("reasoning") or delta.get("reasoning_content")
                        if gedanke:
                            # Deliberately never counted into `token_gezaehlt`,
                            # the speed's own counter. The speed says how fast
                            # the ANSWER was written, and thinking is not the
                            # answer — a model that thinks for a minute and
                            # then writes three lines quickly did write those
                            # three lines quickly, and the number under them
                            # has to say so. `denk_gezaehlt` below counts it
                            # for the context reading instead, which is a
                            # different question: how full the window is
                            # right now.
                            #
                            # The first-token moment is left alone for the
                            # same reason, and it matters just as much as the
                            # count: it is the anchor of the divisor
                            # (``tempo_ermitteln`` measures from it to the
                            # end of the stream). Were the first chunk of
                            # thinking to stamp it, the whole time spent
                            # thinking would land in the denominator and
                            # press the speed down again — with the counting
                            # already corrected, and no longer visibly so.
                            #
                            # This is also what the Anthropic route does with
                            # its ``thinking_delta``, and what the frontend
                            # does with the live bar, which measures only the
                            # answer text.
                            denken_gesehen = True
                            denk_gezaehlt += 1
                            wache.denken(gedanke)
                            yield Stueck("reasoning", gedanke)
                            worte_gesehen = True

                        # Tool calls arrive in pieces — collect first. What
                        # goes out here is only a sign of life with name and
                        # length; the call itself is still assembled below,
                        # after the stream, and only then executed.
                        if rohaufrufe := delta.get("tool_calls"):
                            beruehrt = sammler.aufnehmen(rohaufrufe)
                            # Counts toward the speed: the model generates
                            # tokens here just as with visible text. Without
                            # this the speed display stands still for minutes
                            # while a long argument is being written.
                            if erstes_token_nach is None:
                                erstes_token_nach = time.monotonic() - beginn
                            token_gezaehlt += 1
                            jetzt = time.monotonic()
                            for index in beruehrt:
                                name, zeichen = sammler.stand(index)
                                if name and drossel.faellig(index, zeichen, jetzt):
                                    yield Stueck(
                                        "tool_call_laeuft",
                                        daten={
                                            "index": index,
                                            "name": name,
                                            "zeichen": zeichen,
                                        },
                                    )

                        inhalt = delta.get("content")
                        if inhalt and wache.ist_wiederholung(inhalt):
                            # Not an answer: the whole chain of thought
                            # again, flushed into `content` because the
                            # ceiling was reached before the thinking ended
                            # (app/denkdopplung.py). Left out entirely, so
                            # the answer stays empty and the cut-off notice
                            # is what the user is shown.
                            log.info(
                                "%s: the server repeated its whole chain of thought "
                                "as the answer (%d characters), dropped",
                                self.name,
                                len(inhalt),
                            )
                            inhalt = None
                        if inhalt:
                            # The other shape the chain of thought comes in:
                            # not a field of its own but markers inside the
                            # very same ``content``, which only the parser can
                            # tell apart (<think> tags, Harmony channels).
                            # That is why the chunk is split FIRST and counted
                            # afterwards, by what came out of the split.
                            # Counting it before, as it used to be, would
                            # count a chunk carrying nothing but thinking as
                            # answer text — and every server that speaks in
                            # markers would keep letting the thinking push the
                            # speed, however carefully the dedicated field
                            # above is spared.
                            teile = parser.feed(inhalt)
                            if any(sorte == "content" for sorte, _ in teile):
                                if erstes_token_nach is None:
                                    erstes_token_nach = time.monotonic() - beginn
                                token_gezaehlt += 1
                            if any(sorte == "reasoning" for sorte, _ in teile):
                                denken_gesehen = True
                                denk_gezaehlt += 1
                            for sorte, text in teile:
                                if sorte == "content":
                                    wache.antwort(text)
                                if sorte in ("content", "reasoning"):
                                    worte_gesehen = True
                                yield Stueck(sorte, text)
                        # The live speed and the cache share of this prompt,
                        # once per packet — after the text of this packet has
                        # gone out, so the reading stands beside the words it
                        # belongs to. ONE place rather than one per branch,
                        # the same reasoning as the context reading below: the
                        # two halves have their own conditions and their own
                        # throttles inside, and a packet that carries nothing
                        # but the `usage` names the share just as well as one
                        # carrying text.
                        if denktempo := _denktempo_falls_faellig(
                            messung, worte_gesehen
                        ):
                            yield denktempo

                        # How full the context is, once per packet and
                        # throttled. ONE place rather than one per branch:
                        # everything above that moves the reading — answer
                        # text, the tokens of a tool argument being written,
                        # and the chain of thought — has already moved it by
                        # the time this line is reached. The window fills up
                        # with what the model is thinking too, so the reading
                        # counts it; the speed above never does.
                        #
                        # Which prompt figure this is depends on what the
                        # server said, and the difference is carried out to
                        # the caller instead of being flattened:
                        #
                        #   * ``usage.prompt_tokens`` — the server's own
                        #     complete count. Cloud servers only send it in
                        #     the very last packet, so this is what the last
                        #     reading of a round is made of, not the first.
                        #   * ``timings.prompt_n`` plus ``timings.cache_n`` —
                        #     llama.cpp, from the first chunk on. The two
                        #     halves are the freshly read part and the part
                        #     that came from the cache, and only their sum is
                        #     the prompt (measured: 524 + 977 = 1501). Named
                        #     both, the server has counted the whole prompt.
                        #   * ``timings.prompt_n`` alone — counts only what
                        #     really had to be PROCESSED: in an ongoing chat
                        #     the cached part is missing. So it is handed
                        #     over as a floor and never as a prompt size,
                        #     and the caller raises it with what it knows.
                        #   * neither — ``None``, and the caller estimates.
                        #     A guess made here would be indistinguishable
                        #     from a count.
                        prompt_gemeldet = whole_prompt(stand.timings, stand.usage)
                        prompt_genau = bool(prompt_gemeldet)
                        prompt = prompt_gemeldet if prompt_genau else prompt_gezaehlt
                        erzeugt_gelesen = token_gezaehlt + denk_gezaehlt
                        if (prompt or erzeugt_gelesen) and kontextdrossel.faellig(
                            prompt, erzeugt_gelesen, time.monotonic()
                        ):
                            yield kontext_stueck(prompt, prompt_genau, erzeugt_gelesen)

            # A stream that ends — with ``[DONE]`` or with the connection
            # closing — without a single packet naming a ``finish_reason``
            # (the rule: ``require_stream_end``). Measured on an
            # mlx server whose model was unloaded while it was writing: the
            # abort arrived as ordinary ``delta.content`` ("[Error: Request
            # aborted …]"), with no ``finish_reason``, no ``usage`` and no
            # HTTP error, so the half answer was stored as a whole one and a
            # fold put that sentence in place of the conversation it
            # replaced.
            require_stream_end(ende_grund, self.name)

            # What the parser held back for fear of a torn marker comes out
            # here. It is emitted and not counted, exactly as before: those
            # characters belong to a chunk that was already weighed above
            # when it arrived, so counting them a second time would make the
            # last packet of a stream count twice.
            for sorte, text in parser.finish():
                if sorte == "reasoning":
                    denken_gesehen = True
                yield Stueck(sorte, text)

            # Only now are the arguments complete and allowed to be executed.
            if not sammler.leer:
                aufrufe = sammler.fertige_aufrufe()
                if aufrufe:
                    yield Stueck("tool_call", werkzeugaufrufe=aufrufe)

        except asyncio.CancelledError:
            # Either a stop won the race against the next packet
            # (Generierung.naechstes_stueck) or a fold's own silence timeout
            # gave up on it (app/faltversuche.py) — either way the
            # ``async with`` blocks above are unwinding right now and will
            # close the connection to the server as they do, whatever it
            # was still sending.
            log.info("%s: connection closed, the wait for the next packet was cancelled", self.name)
            raise
        except ProviderFehler:
            raise
        except httpx.HTTPError as fehler:
            raise provider_error(
                "fehler.anbieter_nicht_erreichbar", name=self.name, detail=fehler
            ) from fehler

        dauer = time.monotonic() - beginn
        yield Stueck(
            "stats",
            daten={
                "dauer_sekunden": round(dauer, 3),
                "erstes_token_nach_sekunden": (
                    round(erstes_token_nach, 3) if erstes_token_nach is not None else None
                ),
                "haeppchen": token_gezaehlt,
                **tempo_ermitteln(
                    zeitmessung=zeitmessung,
                    nutzung=nutzung,
                    haeppchen=token_gezaehlt,
                    dauer=dauer,
                    erstes_token_nach=erstes_token_nach,
                    denken_gesehen=denken_gesehen,
                    # The prompt's size from the round's stand — the reader
                    # the live reading uses, on the same input. The closing
                    # block alone may name a speed and not the halves.
                    whole_prompt_tokens=whole_prompt(stand.timings, stand.usage),
                ),
                **einlesen_ermitteln(stand.timings, stand.usage),
                **_cache_share(stand.timings, stand.usage),
                # What the context count at the round's end needs and the
                # speed must not take: whether `prompt_tokens` above is the
                # whole prompt (the reader the live readings use), and every
                # token the model produced — the server's own count where it
                # names one, else the answer's and the thinking's pieces,
                # which is what the live reading counts. `erzeugte_tokens`
                # keeps its meaning for the speed.
                "prompt_genau": bool(whole_prompt(stand.timings, stand.usage)),
                "kontext_erzeugte_tokens": (
                    zaehlung(zeitmessung.get("predicted_n"))
                    or (token_gezaehlt + denk_gezaehlt)
                    or None
                ),
                "nutzung": nutzung or None,
                "endpunkt": self.id,
                # The model that answered. A server that names none leaves
                # the one this request asked for; neither is ever an empty
                # name, and neither is ever a path (``display_model`` above).
                "modell": display_model(reported_model or anfrage.modell),
                # Why it stopped, and the one reading of it the window
                # needs. A round that ends in a tool call reports that here
                # too; the run keeps the LAST round's word, which is the
                # only one that describes the finished answer.
                "ende_grund": ende_grund,
                "abgeschnitten": antwortende.abgeschnitten(ende_grund),
                "kontextfenster_voll": antwortende.kontextfenster_voll(ende_grund),
            },
        )
