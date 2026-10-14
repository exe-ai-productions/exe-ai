"""Asking a model for a fold's summary — once, under two clocks.

One request, and what it comes back with is the outcome. Nothing is sent
again inside the same answer: a person waits behind it, and the pause
between two turns (app/faltpause.py) already is the retry — the next turn
asks again once it has run out. A summary that failed arms a cooldown and
leaves the conversation as it was.

Two clocks sit over the request: a request that receives nothing for
``STILLE_SEKUNDEN`` is abandoned, and one that keeps streaming ends after
``GESAMT_SEKUNDEN`` all the same. Without them a hanging server held the
fold for the provider's own request timeout while a person waited behind
the answer.

Nothing in here books a fold pause: the callers book it once, from the
outcome below.

One function for the chat and the job alike.

And one rule for every such side request: it carries the messages as text
and no tools (:func:`without_tools`). Offered the run's tools, a model can answer
it with a call instead of the text it was asked for; the reader takes text
only, so that answer counts as empty and the fold — or a job's handoff — is
lost. Kept here, at the one place the fold request goes out, so no caller
has to remember it.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from app import reasoning

if TYPE_CHECKING:
    from app.providers import Stueck

# A request that has received nothing for this long is abandoned. Anything
# the server streams counts as a sign of life.
STILLE_SEKUNDEN = 120.0
# The request ends after this long, however steadily it streams.
GESAMT_SEKUNDEN = 600.0

# The clock, as an attribute rather than a call, so a test can hand in its
# own instead of waiting through it.
uhr = time.monotonic


def messages_as_text(messages):
    """The messages as a side request carries them — one message per turn,
    with each answer's tool calls and their results written into it as text
    (``app/faltbitte.py``).

    A run's history holds tools the way a provider wants them back: the call
    on the assistant turn, the result in a message of its own, tied to it by
    id. That shape cannot travel without tools on offer — Anthropic refuses
    a request whose messages carry tool_use or tool_result blocks and that
    defines no tools — and it travelled to the summarizer whole besides: a
    result was sent WHOLE, so one command that printed a megabyte was the
    entire request and everything else in the stretch was crowded out of the
    model's window by it, and the pairing was left to whoever read the
    request — a middle that began behind its own call carried a result
    nothing explained.

    Folded into the turn that made the call, all of it goes at once — the
    call and what came back stand together, in the order they happened, and
    each is capped.

    A document a message carries is NAMED instead of sent
    (``app/verlaufsbau.py``, ``ohne_dokumentkoerper``) — the same view of it
    the fold of a chat's rows takes. Sent whole, one middle of document rows
    is hundreds of thousands of characters, asked of a model whose context
    is already past the threshold, and what gets capped away is the
    conversation rather than the document.
    """
    # Imported here: both modules sit above this one, and this one is read
    # by the fold module they in turn are read beside.
    from app import faltbitte, verlaufsbau
    from app.providers import ChatNachricht

    results = {
        message.werkzeugaufruf_id: message.content
        for message in messages
        if message.role == "tool" and message.werkzeugaufruf_id
    }
    return [
        ChatNachricht(
            role=message.role,
            content=faltbitte.werkzeug_fuer_bitte(
                [
                    (call.name, call.argumente, results.get(call.id))
                    for call in message.werkzeugaufrufe
                ],
                verlaufsbau.ohne_dokumentkoerper(
                    message.content or "", message.dokumente
                ),
            ),
            # Carried over rather than dropped. A message whose whole payload
            # is a picture would otherwise travel with nothing in it at all,
            # and most OpenAI-compatible servers refuse that.
            bild_url=message.bild_url,
            bild_urls=list(message.bild_urls),
        )
        for message in messages
        if message.role != "tool"
    ]


def without_tools(anfrage):
    """``anfrage`` as a side request goes out: offering no tools, and with
    no message in the shape only a request that offers tools may carry —
    the calls and their results written out as text (:func:`messages_as_text`).
    A copy: the run's own request keeps its tools and its messages."""
    nachrichten = getattr(anfrage, "nachrichten", None) or []
    toolish = any(
        n.role == "tool" or n.werkzeugaufrufe for n in nachrichten
    )
    if not getattr(anfrage, "werkzeuge", None) and not toolish:
        return anfrage
    return dataclasses.replace(
        anfrage,
        werkzeuge=[],
        nachrichten=messages_as_text(nachrichten) if toolish else list(nachrichten),
    )


class Stille(TimeoutError):
    """The request went silent, or ran out of time."""


class Gestoppt(Exception):
    """The person pressed stop while the request was running: nothing is
    folded, and nothing is booked — a stopped request says nothing about the
    model."""


async def read_stream(quelle, request: str) -> AsyncGenerator[Stueck, None]:
    """Every piece of a stream, read under the two clocks above.

    The one place a stream is read under them. One piece at a time; the wait
    for the next is capped at what is left of ``STILLE_SEKUNDEN`` and at what
    is left of ``GESAMT_SEKUNDEN``, whichever is nearer. It raises
    :class:`Stille` where either runs out, closes the stream either way, and
    says WHICH of the two clocks it was — ``ran out of time`` for the whole
    request, the silence and its limit for a server that stopped delivering.
    A message that named silence for a request the whole clock ended sent
    whoever read the protocol looking for a hung server that was delivering.

    ``request`` names the request in that line ("fold request", "image prompt
    request"): the reading is shared, the words a person reads belong to the
    caller.

    Waited for with ``wait_for``, as before this reader existed. Measured
    against replacing it with ``asyncio.timeout``, which turns exactly its
    own expiry into a ``TimeoutError`` and leaves any other cancellation
    alone: the test that presses stop while a fold is being asked for
    (`tests/test_kontextvoll.py::test_chat_stopp_waehrend_der_faltung_-
    schickt_nicht_neu`) then ends with a whole answer instead of an aborted
    one — the stop no longer reaches the fold. That exchange is not the
    reader's to make, so the wait stays as it was; what the old wait could
    cost is bounded by the whole clock, and the test that used to stand
    still for ten minutes now names its own ceiling (see the test).
    """
    ende = uhr() + GESAMT_SEKUNDEN
    try:
        while True:
            rest = ende - uhr()
            if rest <= 0:
                raise Stille(f"The {request} timed out.")
            # Which clock caps this wait: the whole request's, or the one for
            # silence. The wait itself cannot say it later — a rest of three
            # milliseconds times out before a piece that needs five, and that
            # is not a silent server.
            still = STILLE_SEKUNDEN <= rest
            frist = min(STILLE_SEKUNDEN, rest)
            try:
                stueck = await asyncio.wait_for(anext(quelle), frist)
            except StopAsyncIteration:
                break
            except TimeoutError as fehler:
                if still:
                    raise Stille(
                        f"No response from the server for {frist:.0f} s."
                    ) from fehler
                raise Stille(f"The {request} timed out.") from fehler
            yield stueck
    finally:
        # Every ``streamen`` owes this (app/providers/base.py): the stop
        # button depends on the connection really being closed.
        await quelle.aclose()


async def _bis_zum_stopp(
    stuecke: AsyncGenerator[Stueck, None], stopp: asyncio.Event | None
) -> AsyncGenerator[Stueck, None]:
    """The pieces of ``stuecke``, until ``stopp`` is set.

    The wait for the next piece is raced against the signal, so a server that
    sends nothing for minutes (a summary still being thought) is let go the
    moment stop is pressed — a plain loop would only look at the signal once
    a piece had arrived. The wait is cancelled and settled before anything
    closes the stream behind it, and the reader is closed either way.
    """
    if stopp is None:
        async for stueck in stuecke:
            yield stueck
        return
    wache = asyncio.ensure_future(stopp.wait())
    try:
        while True:
            naechstes = asyncio.ensure_future(anext(stuecke, None))
            try:
                await asyncio.wait({naechstes, wache}, return_when=asyncio.FIRST_COMPLETED)
                if wache.done():
                    raise Gestoppt()
                stueck = naechstes.result()
            finally:
                if not naechstes.done():
                    naechstes.cancel()
                # Settled, not just asked to end: the reader behind it counts
                # as running until its wait has unwound, and closing it
                # earlier fails.
                await asyncio.gather(naechstes, return_exceptions=True)
            if stueck is None:
                return
            yield stueck
    finally:
        wache.cancel()
        await asyncio.gather(wache, return_exceptions=True)
        await stuecke.aclose()


async def anfordern(zustand, anfrage, stopp: asyncio.Event | None = None) -> str | None:
    """The summary, asked for once, text only, on a request built just for
    this ask so the live conversation is never touched until there is an
    answer to splice in.

    ``stopp`` is the stop signal of whatever asks (the answer's run, a job's
    run, the claim a chat holds while it sets up): set while the request is
    running, the request is closed on the spot and :class:`Gestoppt` is
    raised — the model server is free at once instead of at the end of a
    summary nobody wants any more.

    Answers the summary, ``""`` for an empty answer, or ``None`` for one cut
    off at the ceiling: a cut summary would be stored whole and fold away
    rows it never got to speak for, so it is no summary. A request that
    ended by itself without one visible character thought its summary
    instead of writing it: the thinking is the summary then, the same swap
    chat and job make (``app/reasoning.denktext_als_antwort``) — otherwise a
    summary that is there would be booked as an empty answer and brake the
    next turn. Raises what the request raised, and :class:`Stille` where the
    server sent nothing for ``STILLE_SEKUNDEN`` or the request ran past
    ``GESAMT_SEKUNDEN``. The callers read those outcomes and book the fold
    pause from them.
    """
    text: list[str] = []
    gedanke: list[str] = []
    ende_grund: str | None = None
    abgeschnitten = False
    quelle = zustand.provider.streamen(without_tools(anfrage))
    async for stueck in _bis_zum_stopp(read_stream(quelle, "fold request"), stopp):
        if stueck.sorte == "content":
            text.append(stueck.text)
        elif stueck.sorte == "reasoning":
            gedanke.append(stueck.text)
        elif stueck.sorte == "stats":
            if stueck.daten.get("abgeschnitten"):
                abgeschnitten = True
            ende_grund = stueck.daten.get("ende_grund")
    if abgeschnitten:
        return None
    # "fertig" is the only state this request can be in here: a cut answer
    # returned above, a failure raises to the callers — what is left is a
    # request that ended on its own, and the stage's own check on the
    # ending decides the rest. One request, so its thinking is the whole
    # thinking; there is no earlier deliberation to hold back.
    geschrieben = "".join(text).strip()
    gedacht = "".join(gedanke).strip()
    antwort, _ = reasoning.denktext_als_antwort(
        geschrieben,
        gedacht,
        gedacht,
        schlusstext=geschrieben,
        ende_grund=ende_grund,
        zustand="fertig",
    )
    return antwort
