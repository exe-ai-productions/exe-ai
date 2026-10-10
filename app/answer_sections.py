"""The order an answer happened in: thinking, tools and text as sections.

The window draws a streamed answer from the sections it builds while the
events arrive (frontend/src/App.svelte: ``textAnhaengen``, ``endThinking``,
``werkzeugAnhaengen``). A stored answer had only one joined thinking string,
so after a reload thinking -> tool -> thinking became one entry above the
tools, without a length. This records the same sections from the same
events, by the same rules, and the row keeps them in its metrics under
``sections``; the window rebuilds its entries from them
(frontend/src/teile/Nachricht.svelte, ``storedSections``).

Only lengths are kept, never the text a second time: the text is in the
row's ``content`` and ``reasoning``. Lengths count UTF-16 code units, the
unit the window slices strings with, so a character outside the basic plane
does not shift every section after it.

One deviation from the window: a call that only has a result (refused
before it was announced) gets a section here, where the live window draws
none — after a reload it is shown, because the model saw its result.

A stored section is one of
``{"kind": "reasoning", "length", "begin_ms", "end_ms"?}``,
``{"kind": "content", "length"}`` and ``{"kind": "tool", "call_id"}``.
"""

from __future__ import annotations

import json
import logging
import time

# Events that add a tool entry to the answer, as the window adds one.
TOOL_EVENTS = frozenset({"tool_call", "user_ask"})
# Events that do not end a thinking stretch: the thinking itself and the
# speed reading that arrives while it runs.
NOT_AN_END = frozenset({"reasoning", "denktempo"})

log = logging.getLogger(__name__)


def utf16_length(text: str) -> int:
    """The length JavaScript gives the same string.

    ``surrogatepass``: a lone surrogate is one unit there too, and a display
    aid must never raise inside the run that feeds it.
    """
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


class SectionLog:
    """The sections of one answer, fed with every event the stream sends.

    A display aid: nothing in here may end the run that feeds it or cost the
    row its answer. An event it cannot read is logged and the order is given
    up — the row is then stored without one and drawn the old way.
    """

    def __init__(self) -> None:
        self._sections: list[dict] = []
        # A list, not a set: calls without an id all share the empty one.
        self._waiting: list[str] = []
        self._wrote_visible = False
        self._broken = False

    def record(self, line: str) -> None:
        """Take one event line of the stream (``data: {...}``) into account."""
        if self._broken or not line.startswith("data:"):
            return
        try:
            self._record(line)
        except Exception:
            log.exception("Answer order given up at an unreadable event")
            self._broken = True

    def _record(self, line: str) -> None:
        try:
            event = json.loads(line[len("data:"):].strip())
        except ValueError:
            return
        if not isinstance(event, dict):
            return
        kind = event.get("typ")
        at = event.get("zeitpunkt_ms")
        last = self._sections[-1] if self._sections else None
        # A thinking stretch ends with the first event that is not thinking,
        # at that event's own time.
        if (
            kind not in NOT_AN_END
            and last
            and last["kind"] == "reasoning"
            and last.get("end_ms") is None
        ):
            last["end_ms"] = at
        if kind in ("reasoning", "content"):
            text = event.get("text") or ""
            # The model writes again: every result of the round before is in.
            self._waiting.clear()
            if kind == "content" and text.strip():
                self._wrote_visible = True
            length = utf16_length(text)
            if last and last["kind"] == kind:
                last["length"] += length
                # Thinking that goes on after a passing event is one stretch.
                last.pop("end_ms", None)
            else:
                entry: dict = {"kind": kind, "length": length}
                if kind == "reasoning":
                    entry["begin_ms"] = at
                self._sections.append(entry)
            return
        if kind not in TOOL_EVENTS and kind != "tool_result":
            return
        # A call without an id still has its place, as the window gives it
        # one; its stored entry carries the same empty id.
        call_id = event.get("aufruf_id")
        if not isinstance(call_id, str):
            call_id = ""
        # A call that never announced itself — a task or a question refused
        # before it was put — only has its result. Its log entry is stored
        # all the same, so it gets its place here, where the result came.
        # Matched against the calls of this round still waiting for a
        # result, not against every id seen: a server without ids numbers
        # each round from zero.
        if kind in TOOL_EVENTS:
            self._sections.append({"kind": "tool", "call_id": call_id})
            self._waiting.append(call_id)
        elif kind == "tool_result":
            if call_id in self._waiting:
                self._waiting.remove(call_id)
            else:
                self._sections.append({"kind": "tool", "call_id": call_id})

    def stored(
        self, content: str, reasoning: str | None, *, final: bool, promoted: bool = False
    ) -> list[dict] | None:
        """The sections as the row keeps them, or None when they do not
        describe the strings being stored.

        ``promoted``: the run thought and ended without writing a visible
        character, and its closing thought became the answer
        (app/reasoning.denktext_als_antwort). The sections follow that one
        swap: the thinking keeps what the stored thinking still holds, the
        streamed text stays unless it was blank (the swap drops it then),
        and the lifted thought is one closing text section — what the window
        draws when the answer arrives (App.svelte, ``liftAnswer``). Any
        other mismatch would cut the strings in the wrong places, so the row
        then keeps none and the window draws it the old way.

        ``final``: at the closing write a stretch still open ends there. An
        intermediate save leaves it open — it has not ended, and a row read
        after a crash must not claim it did.
        """
        if self._broken or not self._sections:
            return None
        try:
            return self._stored(content, reasoning, final=final, promoted=promoted)
        except Exception:
            log.exception("Answer order not stored")
            return None

    def _stored(
        self, content: str, reasoning: str | None, *, final: bool, promoted: bool
    ) -> list[dict] | None:
        sections = [dict(section) for section in self._sections]
        # Only the closing write ends a stretch that is still open — before
        # the lift, which may put the answer behind it. Mid-run the row keeps
        # the ends events set — real times, the last one seen — and invents
        # none.
        last = sections[-1]
        if final and last["kind"] == "reasoning" and last.get("end_ms") is None:
            last["end_ms"] = round(time.time() * 1000)
        content_length = utf16_length(content)
        reasoning_length = utf16_length(reasoning or "")
        if promoted:
            sections = self._lifted(sections, content_length, reasoning_length)
        if not self._adds_up(sections, content_length, reasoning_length):
            return None
        return sections

    @staticmethod
    def _adds_up(sections: list[dict], content_length: int, reasoning_length: int) -> bool:
        totals = {"reasoning": 0, "content": 0}
        for section in sections:
            if section["kind"] in totals:
                totals[section["kind"]] += section["length"]
        return (
            bool(sections)
            and totals["content"] == content_length
            and totals["reasoning"] == reasoning_length
        )

    def _lifted(
        self, sections: list[dict], content_length: int, reasoning_length: int
    ) -> list[dict]:
        left = reasoning_length
        drawn = 0
        kept: list[dict] = []
        for section in sections:
            if section["kind"] == "content":
                # Blank streamed text is not kept by the swap.
                if not self._wrote_visible:
                    continue
                drawn += section["length"]
            if section["kind"] != "reasoning":
                kept.append(section)
                continue
            take = min(left, section["length"])
            left -= take
            # A stretch keeps its times when cut, as the window keeps them;
            # one left empty is dropped, as the window drops it.
            if take:
                kept.append({**section, "length": take})
        if content_length > drawn:
            kept.append({"kind": "content", "length": content_length - drawn})
        return kept
