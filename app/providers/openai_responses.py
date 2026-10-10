"""The second wire to OpenAI's own host: the Responses API.

A request to ``api.openai.com`` that carries a thinking stage or tools goes
over ``/v1/responses``; a plain chat with neither, and every other host, stays
on ``/v1/chat/completions``. Only this wire returns a summary of the model's
thinking, the chat route refuses function tools beside ``reasoning_effort``
with a 400, and it keeps working for plain chats as the provider's
compatibility mode.

Two things live here, and only these two:

  * what such a request looks like on the wire (:func:`koerper_umbauen`) — the
    messages become ``input`` items, the tools lose their nesting, the ceiling
    is called ``max_output_tokens``, and the thinking stage moves from a
    top-level field into ``reasoning.effort``. The last of these is asked of
    ``app/denkschalter.py``, which is where a provider's spelling of a stage
    belongs;
  * how such a stream is read (:class:`Leser`) — its events are turned into the
    packet shape the reader in ``app/providers/openai_kompatibel.py`` already
    understands, so speed, context reading, tool assembly and the "a stream
    names its end" guard stay written once for both wires.
"""

from __future__ import annotations

import logging
from typing import Any

from app import denkschalter
from app.denkstufen import ist_wirt
from app.providers.base import provider_error, zaehlung

log = logging.getLogger(__name__)

# OpenAI's own host. Both wires ask about the HOST, and neither about the
# whole address: a proxy at ``https://proxy.test/api.openai.com/v1`` is
# somebody else's machine and keeps the chat route, exactly as it keeps the
# parameter names it was written for. What matches is the host, or a real
# sub-domain of it, and nothing else.
WIRT_OPENAI = "api.openai.com"

# The stage that switches thinking off on this wire — the word the catalogue
# keeps for OpenAI (``app/daten/denkstufen.yaml``).
AUS = "none"

# What a request with a thinking stage asks to get back: the thinking as a
# sealed item that a later request can hand back unread.
VERSIEGELT = "reasoning.encrypted_content"

# The two events that carry a chain of thought on this wire. Servers differ in
# which of them they send: ``summary`` is the documented one, a few send the
# raw text instead.
DENKEREIGNISSE: tuple[str, ...] = (
    "response.reasoning_summary_text.delta",
    "response.reasoning_text.delta",
)

# The phases of a message item whose text is the model narrating between its
# steps, not the answer: it goes out as thinking. Text with no phase, or with
# ``final_answer``, stays the answer.
NARRATION_PHASES: tuple[str, ...] = ("commentary", "analysis")

# The phase whose text becomes the answer of a round that ends without one.
COMMENTARY = "commentary"


def ist_openai(wirt: str) -> bool:
    """Is this host OpenAI's own?

    The host itself or a real sub-domain of it, and nothing else. ``api.openai
    .com.example.net`` is somebody else's machine; it reads as a name that
    merely contains OpenAI's (``app/denkstufen.py``, ``ist_wirt``).
    """
    return ist_wirt(wirt=wirt, eigener=WIRT_OPENAI)


def antwortenroute(wirt: str, koerper: dict[str, Any]) -> bool:
    """Does this request go over the Responses API?

    OpenAI's own host, and either a thinking stage or a tool that can really
    be sent. A stage needs this wire because only here does the thinking come
    back as a summary; a tool goes the same way so that one turn never
    switches wires between its rounds: every tool-using request to OpenAI
    takes the Responses API. A plain chat with neither stays on
    ``/v1/chat/completions``, the provider's compatibility mode.

    Asked of the FINISHED body, not of a setting: what decides the route is
    what really goes out, and a stage this model's profile does not offer never
    reaches the body at all.
    """
    return ist_openai(wirt) and (
        _sendbare_werkzeuge(koerper) or denkschalter.traegt_stufe(koerper)
    )


def _sendbare_werkzeuge(koerper: dict[str, Any]) -> bool:
    """Does this body carry a tool the other wire can actually send?

    A tool without a name cannot be called, and ``_werkzeugliste`` leaves it
    out — so a list made only of such tools is no reason to take this wire.
    What the route is decided on is what would really go out, not the count
    it stands in.
    """
    return any(
        isinstance(werkzeug, dict) and (werkzeug.get("function") or {}).get("name")
        for werkzeug in koerper.get("tools") or []
    )


def koerper_umbauen(koerper: dict[str, Any], zusammenfassung: bool = True) -> dict[str, Any]:
    """The same request in the shape ``/v1/responses`` reads.

    Built from the FINISHED chat body rather than from the request beside it:
    by then what the model refuses is already out of it
    (``app/samplingwerte.py``), the ceiling already stands under the name
    OpenAI wants, and the thinking stage already carries the word this
    provider spells. Only the SHAPE changes here — no value is decided twice.

    Dropped: ``stream_options``. It exists to make the chat wire report token
    counts at all, and this wire reports them in its closing event anyway.

    ``zusammenfassung`` is False once OpenAI has refused the thinking summary
    for this endpoint (:func:`lehnt_zusammenfassung_ab`): the request then
    goes out without ``reasoning.summary`` and the stage still applies.
    """
    umgebaut = dict(koerper)
    umgebaut.pop("stream_options", None)
    umgebaut["input"] = _eingabe(umgebaut.pop("messages", []))
    # Nothing is kept on OpenAI's side: every item a later round needs is sent
    # again by this request. Stored, a response would be kept there for
    # 30 days.
    umgebaut["store"] = False
    werkzeuge = _werkzeugliste(umgebaut.get("tools") or [])
    if werkzeuge:
        umgebaut["tools"] = werkzeuge
    else:
        # No tool left that this wire can send: an empty list and a
        # `tool_choice` with nothing to choose from are left out.
        umgebaut.pop("tools", None)
        umgebaut.pop("tool_choice", None)
    for alt in ("max_completion_tokens", "max_tokens"):
        if (deckel := umgebaut.pop(alt, None)) is not None:
            umgebaut["max_output_tokens"] = deckel
            break
    # Last, so it sees every field: the chat body carries the extra fields at
    # its top level (they are merged in when it is built), and the stage is one
    # of them. The call copies what it does not know.
    umgebaut = denkschalter.fuer_antworten(umgebaut)
    # This wire keeps the chain of thought to itself unless a summary is asked
    # for, and the chat shows the thinking live beside the answer. `auto` is
    # the most detailed summary the model offers; a summary the request
    # already names is kept. Not for `none`: a stage that switches thinking
    # off has nothing to summarise.
    denken = umgebaut.get("reasoning")
    if isinstance(denken, dict) and denken.get("effort") not in (None, AUS):
        if zusammenfassung:
            umgebaut["reasoning"] = {"summary": "auto", **denken}
        # The thinking itself comes back sealed, so that the next tool round
        # of the same turn can hand it back: with `store: false` the server
        # keeps no copy of its own.
        umgebaut["include"] = [VERSIEGELT]
    return umgebaut


def ohne_zusammenfassung(koerper: dict[str, Any]) -> dict[str, Any]:
    """The same finished body without ``reasoning.summary`` — for the one
    repeat after OpenAI refused the summary. Everything else stays."""
    umgebaut = dict(koerper)
    denken = umgebaut.get("reasoning")
    if isinstance(denken, dict) and "summary" in denken:
        umgebaut["reasoning"] = {k: v for k, v in denken.items() if k != "summary"}
    return umgebaut


def lehnt_zusammenfassung_ab(status: int, rohtext: str, koerper: dict[str, Any]) -> bool:
    """Did OpenAI refuse the thinking summary of this request?

    A 400 whose error names the ``summary`` field, for a body that asked for
    one. The documentation says a summary may need a verified organisation but
    names no error text, so the field is what is read, not a word like
    "verified". A 400 about any other field is no reason to drop the summary.
    """
    denken = koerper.get("reasoning")
    return (
        status == 400
        and isinstance(denken, dict)
        and "summary" in denken
        and "summary" in rohtext
    )


def _eingabe(nachrichten: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The chat messages as ``input`` items.

    A plain message is one item. The other two shapes are items of their own
    type, standing BESIDE the messages rather than inside them — a call
    (``function_call``) and its result (``function_call_output``) — so one chat
    row can become several items here, and the call's id is what ties them
    together.
    """
    eintraege: list[dict[str, Any]] = []
    for nachricht in nachrichten:
        if kennung := nachricht.get("tool_call_id"):
            eintraege.append(
                {
                    "type": "function_call_output",
                    "call_id": kennung,
                    "output": _fliesstext(nachricht.get("content")),
                }
            )
            continue
        if aufrufe := nachricht.get("tool_calls"):
            # The round's own items first, in this order: its sealed
            # thinking, then its text items with their `phase`, then the
            # calls. Without the thinking a stateless request loses what the
            # model thought before it called.
            eintraege.extend(_zurueck(eintrag) for eintrag in nachricht.get(DENKTEILE) or [])
            texteintraege = [_zurueck(eintrag) for eintrag in nachricht.get(TEXTTEILE) or []]
            eintraege.extend(texteintraege)
            # Whatever the row said beside its calls keeps its place, in front
            # of them: that is the order the round happened in. Already there
            # when its text items stand in for it.
            inhalt = _teile(nachricht.get("content"), str(nachricht.get("role") or ""))
            if inhalt and not texteintraege:
                eintraege.append({"role": nachricht.get("role") or "assistant", "content": inhalt})
            eintraege.extend(
                {
                    "type": "function_call",
                    "call_id": str(aufruf.get("id") or ""),
                    "name": str((aufruf.get("function") or {}).get("name") or ""),
                    "arguments": str((aufruf.get("function") or {}).get("arguments") or "{}"),
                }
                for aufruf in aufrufe
            )
            continue
        if inhalt := _teile(nachricht.get("content"), str(nachricht.get("role") or "")):
            eintraege.append({"role": nachricht.get("role") or "user", "content": inhalt})
    return eintraege


# The keys under which a chat message carries its round's items to
# :func:`_eingabe`. The chat route never sends them.
DENKTEILE = "reasoning_items"
TEXTTEILE = "message_items"


def rundenteile(
    teile: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """A round's collected items, split into the two fields of its assistant
    message (``ChatNachricht.reasoning_items``, ``message_items``) — the one
    place the chat and the job loop both ask."""
    return (
        [t for t in teile if t.get("type") == "reasoning"],
        [t for t in teile if t.get("type") == "message"],
    )


def _zurueck(eintrag: dict[str, Any]) -> dict[str, Any]:
    """An item of an earlier round, as it goes back out: without ``id`` and
    ``status`` and otherwise unchanged. With ``store: false`` the server
    answers an id it was never asked to keep with 404."""
    return {k: v for k, v in eintrag.items() if k not in ("id", "status")}


def _teile(inhalt: Any, rolle: str) -> list[dict[str, Any]]:
    """One message's content, as the parts this wire knows.

    Text is ``input_text`` on everything the model READS and ``output_text`` on
    an assistant row: the two are not interchangeable there. An image is
    ``input_image`` with its address as a plain string, not the nested object
    the chat wire takes.

    A message whose parts come out empty is left out entirely by the caller —
    an empty content list is what this wire answers with 400.
    """
    if isinstance(inhalt, str):
        return [{"type": _textsorte(rolle), "text": inhalt}] if inhalt else []
    teile: list[dict[str, Any]] = []
    for teil in inhalt or []:
        if not isinstance(teil, dict):
            continue
        sorte = str(teil.get("type") or "")
        if sorte == "text":
            if text := teil.get("text"):
                teile.append({"type": _textsorte(rolle), "text": str(text)})
        elif sorte == "image_url":
            adresse = teil.get("image_url")
            if isinstance(adresse, dict):
                adresse = adresse.get("url")
            if adresse:
                teile.append({"type": "input_image", "image_url": str(adresse)})
            else:
                log.warning("A picture without an address stays out of the request: %r", teil)
    return teile


def _textsorte(rolle: str) -> str:
    """Which text part this role reads — the API rejects the other one."""
    return "output_text" if rolle == "assistant" else "input_text"


def _fliesstext(inhalt: Any) -> str:
    """A tool result as plain text, which is what a ``function_call_output``
    carries. Rows of our own history may hold parts instead of a string; their
    text is joined, and nothing else about them is passed on."""
    if isinstance(inhalt, str):
        return inhalt
    return "\n".join(
        str(teil.get("text"))
        for teil in (inhalt or [])
        if isinstance(teil, dict) and teil.get("text")
    )


def _werkzeugliste(werkzeuge: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The tools in this wire's shape: the function IS the tool, there is no
    ``function`` object inside it. Same name, same description, same
    parameters — only the nesting goes. A tool without a name is dropped: this
    wire has no way to call it, and sending it anyway would be an entry nobody
    can use."""
    liste: list[dict[str, Any]] = []
    for werkzeug in werkzeuge:
        funktion = (werkzeug or {}).get("function") or {}
        if not funktion.get("name"):
            continue
        liste.append(
            {
                "type": "function",
                "name": funktion["name"],
                "description": funktion.get("description") or "",
                "parameters": funktion.get("parameters")
                or {"type": "object", "properties": {}},
            }
        )
    return liste


# --- Reading the stream -----------------------------------------------------


class Leser:
    """One ``/v1/responses`` stream, read as the packets the chat reader knows.

    This wire reports each item on its own: a text fragment, a piece of a tool
    argument, then the summary of the finished response. The reader in
    ``app/providers/openai_kompatibel.py`` expects the chat wire's shape — one
    ``choices[0].delta`` per packet, a closing ``finish_reason``, the usage
    beside it — and everything it does with a packet is worth exactly as much
    here. So the shape is translated instead of the reader doubled.
    """

    def __init__(self) -> None:
        # The chat shape keys a tool call by an integer `index`; this wire names
        # its items by id and by position at once. The number is handed out in
        # the order the calls appear, which is all the assembler needs to keep
        # them apart; which of the two names stands for it is remembered below.
        self._nummern: dict[Any, int] = {}
        self._naechste = 0
        # Whether any thinking text has gone out yet on this stream, and
        # whether a new summary part has opened since — the blank line
        # between parts is owed only between two parts that both have text.
        self._gedacht = False
        self._neuer_teil = False
        # The phase of each message item, under its id and its position. A
        # text delta names no phase of its own, only the item it belongs to;
        # the item said its phase when it opened. The last one opened answers
        # a delta that names neither.
        self._phases: dict[Any, str | None] = {}
        self._last_phase: str | None = None
        # The commentary text of this round, one entry per item, held back
        # while it is open whether it is the answer: a round that ends on
        # commentary alone, with no call, has it as its answer and shows it
        # once, there. Whether any answer text or call went out decides it.
        self._commentary: dict[Any, str] = {}
        self._answered = False
        self._called = False

    def pakete(self, ereignis: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        """What one event of this stream is worth, in the other shape."""
        art = str(ereignis.get("type") or "")
        if art == "response.output_text.delta":
            phase = self._phase_of(ereignis)
            if phase in NARRATION_PHASES:
                delta = ereignis.get("delta")
                if phase == COMMENTARY and not (self._answered or self._called):
                    if isinstance(delta, str) and delta:
                        key = ereignis.get("item_id", ereignis.get("output_index"))
                        self._commentary[key] = self._commentary.get(key, "") + delta
                    return ()
                # Other narration closes the commentary held so far, the
                # same way new summary text does below.
                return self._held_then_thought(delta)
            return self._answer(ereignis.get("delta"))
        if art == "response.refusal.delta":
            # A refusal is the model's answer, not a missing one: the chat
            # wire sends the same sentence as ordinary content, and left out
            # here it would reach the window as an empty answer with a clean
            # "stop" under it.
            return self._answer(ereignis.get("delta"))
        if art in DENKEREIGNISSE:
            # New thinking closes the commentary held so far: it goes out
            # first, as the thinking it turned out to be, and the new text
            # starts a paragraph of its own after it.
            return self._held_then_thought(ereignis.get("delta"))
        if art == "response.reasoning_summary_part.added":
            self._neuer_teil = True
            return ()
        if art == "response.output_item.added":
            self._remember_phase(ereignis)
            return self._aufruf_beginnt(ereignis)
        if art == "response.output_item.done":
            return _fertiger_teil(ereignis.get("item"))
        if art == "response.function_call_arguments.delta":
            return self._aufruf_waechst(ereignis)
        if art in ("response.completed", "response.incomplete"):
            response = ereignis.get("response") or {}
            return (*self._commentary_as_answer(response), _schlusspaket(art, response))
        if art in ("response.failed", "error"):
            # Commentary still held back is dropped with the round: a round
            # that failed has no answer it could be, and no text of a
            # failed turn is kept.
            # The wire's name is this module's own; the message and code
            # inside it are the server's words and travel unchanged. Built
            # from the catalogue so the person in the window reads it in
            # their language (app/providers/base.py), the model in English.
            meldung = _fehlertext(ereignis)
            raise provider_error(
                "fehler.anbieter_meldung" if meldung else "fehler.anbieter_meldung_leer",
                name="Responses",
                text=meldung,
            )
        # Everything else — the bookkeeping this wire sends around each item —
        # carries nothing the reader below uses.
        return ()

    def _answer(self, delta: Any) -> tuple[dict[str, Any], ...]:
        """A piece of the answer text, and a note that the round has one.
        Commentary held back until now was not the answer, so it goes out
        first, as the thinking it is."""
        packets = _textpaket(delta)
        if not packets:
            return ()
        self._answered = True
        return (*self._held_commentary_as_thought(), *packets)

    def _held_commentary(self) -> str:
        """The commentary held back so far, its items a paragraph apart, and
        nothing held any more."""
        text = "\n\n".join(t.strip() for t in self._commentary.values() if t.strip())
        self._commentary = {}
        return text

    def _held_commentary_as_thought(self) -> tuple[dict[str, Any], ...]:
        return self._thought(self._held_commentary())

    def _held_then_thought(self, delta: Any) -> tuple[dict[str, Any], ...]:
        """New thinking text, with the commentary held so far sent out
        first as the thinking it turned out to be; the new text then starts
        a paragraph of its own after it."""
        held = self._held_commentary_as_thought()
        if held:
            self._neuer_teil = True
        return (*held, *self._thought(delta))

    def _commentary_as_answer(self, response: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        """The round's commentary as its answer — only where the round ended,
        finished or cut off, with no answer text and no call; otherwise it
        goes out as the thinking it is. Either way it is shown once."""
        if self._answered or self._called or _ruft_werkzeug(response):
            return self._held_commentary_as_thought()
        return self._answer(self._held_commentary())

    def _thought(self, delta: Any) -> tuple[dict[str, Any], ...]:
        """A piece of thinking text — a summary's or a narrating message's."""
        if not isinstance(delta, str) or not delta:
            return ()
        # A summary arrives in parts, each with its own heading, and the
        # text events carry no break between them. The first text of a
        # part that follows earlier text starts with a blank line —
        # otherwise one part's last sentence runs straight into the next
        # one's heading. Put in front of real text rather than sent on
        # its own: a part that stays empty leaves nothing behind, and no
        # packet goes out that the model never wrote. Counted by what
        # went out, not by the part's number: that starts again at 0 for
        # every reasoning item.
        if self._neuer_teil and self._gedacht:
            delta = "\n\n" + delta
        self._neuer_teil = False
        self._gedacht = True
        return _denkpaket(delta)

    def _remember_phase(self, event: dict[str, Any]) -> None:
        """Remember the phase a message item opens with. A narrating item is
        a new part of the thinking: its first text starts on its own
        paragraph after thinking that went out before it."""
        item = event.get("item") or {}
        raw = item.get("phase") if item.get("type") == "message" else None
        phase = str(raw).strip().lower() if raw else None
        for key in (item.get("id"), event.get("output_index")):
            if key is not None:
                self._phases[key] = phase
        self._last_phase = phase
        if phase in NARRATION_PHASES:
            self._neuer_teil = True

    def _phase_of(self, event: dict[str, Any]) -> str | None:
        """The phase of the item a text delta belongs to."""
        for key in (event.get("item_id"), event.get("output_index")):
            if key is not None and key in self._phases:
                return self._phases[key]
        return self._last_phase

    def _aufruf_beginnt(self, ereignis: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        """A tool call opens: this is where its name and id are said. The
        arguments follow in pieces and are collected by the reader, exactly as
        on the chat wire."""
        eintrag = ereignis.get("item") or {}
        if eintrag.get("type") != "function_call":
            return ()
        self._called = True
        nummer = self._nummer(ereignis, eintrag)
        return (
            *self._held_commentary_as_thought(),
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": nummer,
                                    "id": str(eintrag.get("call_id") or eintrag.get("id") or ""),
                                    "function": {
                                        "name": str(eintrag.get("name") or ""),
                                        "arguments": str(eintrag.get("arguments") or ""),
                                    },
                                }
                            ]
                        },
                    }
                ]
            },
        )

    def _aufruf_waechst(self, ereignis: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        """The next piece of a tool argument. A piece carries no name, so it is
        matched to its call by the same number the opening event got."""
        stueck = ereignis.get("delta")
        if not isinstance(stueck, str) or not stueck:
            return ()
        nummer = self._nummer(ereignis)
        return (
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {"index": nummer, "function": {"arguments": stueck}}
                            ]
                        },
                    }
                ]
            },
        )

    def _nummer(self, ereignis: dict[str, Any], eintrag: dict[str, Any] | None = None) -> int:
        """Which `index` this item goes by in the other shape.

        A call is named twice on this wire, and which name an event carries
        depends on the event: the opening one holds the id inside its ``item``,
        while every piece of the argument names it as ``item_id`` — and this
        wire calls the position explicitly optional rather than the id. So
        BOTH are remembered for one call: whichever arrives first gives it its
        number, and every event carrying either name lands on it again. Read
        as two separate keys, the name of a call and its arguments land under
        two numbers, the assembler drops the nameless one, and the tool runs
        with no arguments at all.

        A server that names its items with neither leaves nothing to tell two
        calls apart; their pieces fall under one number, the same assumption
        the chat wire makes of a missing ``index``.
        """
        kennung = eintrag.get("id") if isinstance(eintrag, dict) else None
        schluessel = [
            name for name in (kennung, ereignis.get("item_id"), ereignis.get("output_index"))
            if name is not None
        ]
        nummer = next((self._nummern[name] for name in schluessel if name in self._nummern), None)
        if nummer is None:
            nummer = self._naechste
            self._naechste += 1
        for name in schluessel:
            self._nummern[name] = nummer
        return nummer


# The key of the one packet shape the chat wire does not have: a finished
# item the next tool round hands back (`_eingabe`).
TEILPAKET = "response_item"


def _fertiger_teil(eintrag: Any) -> tuple[dict[str, Any], ...]:
    """A finished item worth keeping for the next round of the same turn.

    Sealed thinking (a ``reasoning`` item with ``encrypted_content``; one
    without it cannot be handed back, so it is skipped) and the
    model's own text items with their ``phase``. Everything else — a call, for
    one — reaches the round by the chat shape already.
    """
    if not isinstance(eintrag, dict):
        return ()
    art = eintrag.get("type")
    if art == "reasoning" and eintrag.get("encrypted_content"):
        return ({TEILPAKET: dict(eintrag)},)
    if art == "message" and eintrag.get("role", "assistant") == "assistant":
        texte = [
            {"type": "output_text", "text": str(teil.get("text") or "")}
            for teil in eintrag.get("content") or []
            if isinstance(teil, dict) and teil.get("type") == "output_text"
        ]
        if not texte:
            return ()
        textteil: dict[str, Any] = {"type": "message", "role": "assistant", "content": texte}
        if phase := eintrag.get("phase"):
            textteil["phase"] = phase
        return ({TEILPAKET: textteil},)
    return ()


def _textpaket(text: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(text, str) or not text:
        return ()
    return ({"choices": [{"index": 0, "delta": {"content": text}}]},)


def _denkpaket(text: Any) -> tuple[dict[str, Any], ...]:
    """A piece of the chain of thought, under the field the reader above knows
    as thinking — counted nowhere, exactly as there."""
    if not isinstance(text, str) or not text:
        return ()
    return ({"choices": [{"index": 0, "delta": {"reasoning": text}}]},)


def _schlusspaket(art: str, antwort: dict[str, Any]) -> dict[str, Any]:
    """The chat wire's closing packet: why the round ended, which model
    answered, and the usage beside it. Without it the reader treats the
    stream as one that broke off mid-answer — which is exactly what it is.

    The model is a top-level field here, as it is on the chat wire, because
    the reader reads it there (``app/providers/openai_kompatibel.py``): this
    wire says it in ``response.model``, and left out of the translation the
    protocol would name the endpoint alone on this route while naming the
    model on the other. The closing event is where the response object is
    complete — the same place the end reason and the usage come from.
    """
    return {
        "model": antwort.get("model"),
        "choices": [{"index": 0, "delta": {}, "finish_reason": _endegrund(art, antwort)}],
        "usage": _nutzung(antwort.get("usage")),
    }


def _endegrund(art: str, antwort: dict[str, Any]) -> str:
    """Why it ended, in the word the chat wire would have used.

    The reader decides two things by it: whether the answer ran into a length
    limit (``app/antwortende.py`` reads the word) and whether the stream named
    its end at all.
    """
    if art == "response.incomplete":
        # The reason this wire gives is already a word that module knows
        # (`max_output_tokens`); an unknown one stays as it is and counts as
        # "not cut off" there. Nothing is invented for it — least of all a
        # length end, which would put a claim about the ceiling under an
        # answer whose cut-off reason the server never named ("unknown counts
        # as NOT cut off", app/antwortende.py).
        einzelheiten = antwort.get("incomplete_details")
        grund = einzelheiten.get("reason") if isinstance(einzelheiten, dict) else None
        return str(grund) if grund else "incomplete"
    return "tool_calls" if _ruft_werkzeug(antwort) else "stop"


def _ruft_werkzeug(antwort: dict[str, Any]) -> bool:
    """Whether a finished response hands a call over instead of an answer."""
    ausgabe = antwort.get("output")
    if not isinstance(ausgabe, list):
        return False
    return any(
        isinstance(eintrag, dict) and eintrag.get("type") == "function_call"
        for eintrag in ausgabe
    )


def _nutzung(roh: Any) -> dict[str, Any]:
    """The usage of the closing event, under the names the reader reads.

    It reads ``prompt_tokens``, ``completion_tokens``, the thinking split
    under ``completion_tokens_details`` and the cache reading under
    ``prompt_tokens_details``; this wire calls the same numbers
    ``input_tokens``, ``output_tokens``, ``output_tokens_details`` and
    ``input_tokens_details``. Renamed here rather than taught to it twice.

    Every field passes through ``zaehlung`` while it is renamed: a string, a
    negative number or a boolean under one of these names is not a count, and
    carried on it would stand under the finished answer and in the context
    reading as one. Left out rather than set to 0 — a zero would claim a
    cache miss that nobody measured.
    """
    if not isinstance(roh, dict):
        return {}
    nutzung: dict[str, Any] = {}
    for ziel, quelle in (
        ("prompt_tokens", "input_tokens"),
        ("completion_tokens", "output_tokens"),
        ("total_tokens", "total_tokens"),
    ):
        if (zahl := zaehlung(roh.get(quelle))) is not None:
            nutzung[ziel] = zahl
    # The nested blocks, through the same table: a section of this wire is a
    # section of the other one under a different name, one field in each.
    # What of the prompt the server already had is one of them — under this
    # wire's name it is a reading like any other, and it is what the cache
    # share under the answer is made of (app/providers/openai_kompatibel.py
    # `einlesen_ermitteln`); left unnamed, the share was simply missing on
    # this route.
    for ziel, quelle, feld in (
        ("completion_tokens_details", "output_tokens_details", "reasoning_tokens"),
        ("prompt_tokens_details", "input_tokens_details", "cached_tokens"),
    ):
        block = roh.get(quelle)
        if isinstance(block, dict) and (zahl := zaehlung(block.get(feld))) is not None:
            nutzung[ziel] = {feld: zahl}
    return nutzung


def _fehlertext(ereignis: dict[str, Any]) -> str:
    """What a failed response says about itself, with nothing added to it.

    Three shapes carry it, and all three are read: the event itself with
    ``code``/``message`` on top (``{"type": "error", …}``), an ``error``
    object, and a ``response`` object holding one. Reading only the last two
    turns the first into "without a reason" — and with it the message, the
    code, and everything the refusal readers in ``app/`` look for.
    """
    fehler: Any = ereignis.get("error") or ereignis.get("response") or ereignis
    if isinstance(fehler, dict) and isinstance(fehler.get("error"), dict):
        fehler = fehler["error"]
    text = fehler.get("message") if isinstance(fehler, dict) else None
    kennung = fehler.get("code") if isinstance(fehler, dict) else None
    if text and kennung:
        return f"{kennung}: {text}"
    return str(text or kennung or "")
