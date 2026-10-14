"""What a failed answer had done before the model call it died in.

The arrow under a failed answer asks that call again (app/answer_redo.py),
and the run goes on in the same row. For that the row is read back here:

* what is KEPT — every tool round that was finished, with the text and the
  thinking that came before its calls. What the failed call itself had
  begun to write is not part of it: that call is asked again and writes its
  round anew;
* the row as the request carries it (``carried``) — the kept part alone,
  for the history builder (app/verlaufsbau.py, ``answer_turns``);
* the kept part as the stream's events (``events``), sent right behind the
  run's ``start``. The window empties the row at ``start`` and is handed
  all of it again, the order of the answer is counted from the same events
  (app/answer_sections.py), and a window that attaches later finds them in
  the run's replay buffer — one way for the three of them.

Nothing here writes: the row stays as it stands until the repeated call has
brought something (app/api/v1/generierung.py).
"""

from __future__ import annotations

import dataclasses
from typing import Any

from app import verlaufsbau


@dataclasses.dataclass(frozen=True)
class Kept:
    """The part of a failed answer its repeated call builds on."""

    content: str
    reasoning: str
    # The entries of the row's tool log, in the order the calls were made.
    calls: list[dict[str, Any]]
    # The stored sections that lie in the kept part (app/answer_sections.py),
    # or None where the row has none that describe it — then the kept part
    # is drawn in the fixed order a row without sections is drawn in.
    sections: list[dict[str, Any]] | None
    # The number the repeated call's round carries: one past the last round
    # the log names, so the rounds of the run stay apart in the log.
    next_round: int


def _utf16(text: str) -> bytes:
    return text.encode("utf-16-le", "surrogatepass")


def _cut(text: str, units: int) -> str:
    """The first ``units`` UTF-16 code units of ``text`` — the unit stored
    section lengths count in."""
    return _utf16(text)[: 2 * units].decode("utf-16-le", "surrogatepass")


def _usable_sections(stats: dict, content: str, reasoning: str) -> list[dict] | None:
    """The row's stored sections, where they describe its two strings
    exactly; None otherwise. The window applies the same test before it
    draws from them (frontend/src/teile/Nachricht.svelte, ``storedSections``)."""
    sections = stats.get("sections")
    if not isinstance(sections, list) or not sections:
        return None
    totals = {"content": 0, "reasoning": 0}
    for section in sections:
        if not isinstance(section, dict):
            return None
        kind = section.get("kind")
        if kind == "tool":
            if not isinstance(section.get("call_id"), str):
                return None
            continue
        length = section.get("length")
        if kind not in totals or type(length) is not int or length < 0:
            return None
        totals[kind] += length
    if totals["content"] != len(_utf16(content)) // 2:
        return None
    if totals["reasoning"] != len(_utf16(reasoning)) // 2:
        return None
    return sections


def _text_of_the_rounds(calls: list[dict], content: str) -> str:
    """The kept text of a row without usable sections: up to where its
    stored rounds end in it, found the way the history builder finds them
    (app/verlaufsbau.py, ``_werkzeugzuege``). A row whose rounds cannot be
    found in its text — one from before rounds were stored among them —
    keeps all of it, the way that builder then sends all of it."""
    if not any("runde" in call for call in calls):
        return content
    end = verlaufsbau.rounds_end(calls, content)
    return content if end is None else content[:end]


def _call_id(call: dict) -> str:
    """The id a stored call was made under; calls without one share the
    empty id, as their sections do (app/answer_sections.py)."""
    stored = call.get("kennung")
    return stored if isinstance(stored, str) else ""


def kept(row) -> Kept:
    """Reads the kept part off a failed answer's row."""
    stats = row.stats or {}
    log = stats.get("werkzeuge")
    calls = [call for call in log if isinstance(call, dict)] if isinstance(log, list) else []
    content = row.content or ""
    reasoning = row.reasoning or ""
    rounds = [call["runde"] for call in calls if type(call.get("runde")) is int]
    # A row whose calls carry no round number goes back as one turn; the
    # repeated call is still a later round than that turn.
    next_round = max(rounds) + 1 if rounds else (1 if calls else 0)

    sections = _usable_sections(stats, content, reasoning)
    if sections is not None:
        # Up to the last call the log holds a result for. A call the run
        # died in has its section and no entry; the text in front of it
        # belongs to a round the log does not hold, and goes with it.
        waiting = [_call_id(call) for call in calls]
        last_call = -1
        for at, section in enumerate(sections):
            if section["kind"] == "tool" and section["call_id"] in waiting:
                waiting.remove(section["call_id"])
                last_call = at
        inside = sections[: last_call + 1]
        return Kept(
            content=_cut(content, sum(s["length"] for s in inside if s["kind"] == "content")),
            reasoning=_cut(
                reasoning, sum(s["length"] for s in inside if s["kind"] == "reasoning")
            ),
            calls=calls,
            sections=inside,
            next_round=next_round,
        )
    if not calls:
        # No finished round: everything the row holds is what the failed
        # call had begun, and that call is asked again.
        return Kept(content="", reasoning="", calls=[], sections=None, next_round=0)
    return Kept(
        content=_text_of_the_rounds(calls, content),
        # Without sections nothing says where the failed call's thinking
        # began, so none of it is dropped.
        reasoning=reasoning,
        calls=calls,
        sections=None,
        next_round=next_round,
    )


def carried(row, part: Kept):
    """The row as the repeated request carries it: the kept part alone."""
    return dataclasses.replace(
        row, content=part.content, stats={**(row.stats or {}), "werkzeuge": part.calls}
    )


def _call_events(call: dict, at: int | None) -> list[dict]:
    """One finished call the way the run reported it: the call, then its
    result."""
    call_id = _call_id(call)
    stamp = {} if at is None else {"zeitpunkt_ms": at}
    result = {
        "typ": "tool_result",
        "name": call.get("name"),
        "aufruf_id": call_id,
        "fehlgeschlagen": bool(call.get("fehlgeschlagen")),
        # A row from before results were stored has none to say. It is a
        # finished call all the same, and an absent text would be read as
        # one that is still running.
        "text": call["ergebnis"] if isinstance(call.get("ergebnis"), str) else "",
        "bild": call.get("bild"),
        "dauer_sekunden": call.get("dauer_sekunden"),
        **stamp,
    }
    for extra in ("lauf_nummer", "auftrag_id"):
        if call.get(extra) is not None:
            result[extra] = call[extra]
    return [
        {
            "typ": "tool_call",
            "name": call.get("name"),
            "server": call.get("server") or "",
            "argumente": call.get("argumente"),
            "aufruf_id": call_id,
            **stamp,
        },
        result,
    ]


def events(part: Kept, goal: str | None = None) -> list[dict]:
    """The kept part as stream events, in the order the answer happened in.

    Each event is the dict the stream sends, ``typ`` included. A thinking
    stretch keeps the times it was stored with: its event carries the
    moment it began and the event behind it the moment it ended, which is
    how the stretch got those times in the first place. An event without a
    stored time carries none and gets the moment it is sent.

    ``goal`` is the report of a goal the run had reached; it closes the
    list, as it is no part of the order.
    """
    out: list[dict] = []
    waiting = list(part.calls)

    def take(call_id: str) -> dict | None:
        for at, call in enumerate(waiting):
            if _call_id(call) == call_id:
                return waiting.pop(at)
        return None

    if part.sections is None:
        if part.reasoning:
            out.append({"typ": "reasoning", "text": part.reasoning})
    else:
        content_at = reasoning_at = 0
        content_units = _utf16(part.content)
        reasoning_units = _utf16(part.reasoning)
        # The time the next event carries: where a thinking stretch ended.
        ended: int | None = None
        for section in part.sections:
            kind = section["kind"]
            if kind == "reasoning":
                until = reasoning_at + 2 * section["length"]
                text = reasoning_units[reasoning_at:until].decode("utf-16-le", "surrogatepass")
                reasoning_at = until
                begin = section.get("begin_ms")
                event: dict = {"typ": "reasoning", "text": text}
                if type(begin) is int:
                    event["zeitpunkt_ms"] = begin
                elif ended is not None:
                    event["zeitpunkt_ms"] = ended
                out.append(event)
                end = section.get("end_ms")
                ended = end if type(end) is int else None
                continue
            at = ended
            ended = None
            if kind == "content":
                until = content_at + 2 * section["length"]
                text = content_units[content_at:until].decode("utf-16-le", "surrogatepass")
                content_at = until
                event = {"typ": "content", "text": text}
                if at is not None:
                    event["zeitpunkt_ms"] = at
                out.append(event)
                continue
            # A call the row holds no result for — the run died while it was
            # going — is no finished call and is not drawn again.
            call = take(section["call_id"])
            if call is not None:
                out.extend(_call_events(call, at))
    # Calls no section stands for: all of them in a row without sections,
    # none otherwise.
    for call in waiting:
        out.extend(_call_events(call, None))
    if part.sections is None and part.content:
        out.append({"typ": "content", "text": part.content})
    if goal:
        out.append({"typ": "ziel", "report": goal})
    return out
