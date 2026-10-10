"""When a server sends its whole chain of thought a second time, as the answer.

A local MLX server stopped at its token ceiling WHILE STILL THINKING closes
the stream with one last packet whose ``content`` is the complete chain of
thought it has streamed so far — character for character what already
travelled in the dedicated ``reasoning`` / ``reasoning_content`` field.

Measured against that server: a run stopped mid-thought delivered 275
characters of thinking in eight pieces and then a single content piece of
exactly those 275 characters, ``finish_reason`` ``length``. The same
question with room to finish delivered 1520 characters of thinking and 1557
entirely different characters of answer, and a run stopped AFTER the
thinking was done delivered 1722 characters of thinking and 351 characters
of a real, half-written answer. So the flush happens in one case only: the
ceiling is reached before the thinking ends.

Taken as an answer, that flush is the worst outcome a ceiling can have. The
user is shown the entire chain of thought AS the answer, there is no answer
underneath it, and nothing says that anything was cut off. Dropped, the
answer stays empty — and an empty answer that stopped at the ceiling is
precisely what the cut-off notice exists to explain (``app/antwortende.py``,
``stats.abgeschnitten``).

The rule is deliberately narrow, so nothing but that flush can meet it:

* only text the server itself labelled as thinking counts — a server that
  marks its thinking with tags inside ``content`` (``app/reasoning.py``)
  keeps no second copy anywhere and can never match;
* only while the answer is still empty, so a real answer already under way
  is never touched;
* and only a piece equal to the WHOLE of that thinking. Not a prefix: the
  thinking measured above begins with a newline, and so does many an
  answer.
* thinking that is nothing but whitespace does not count as thinking at
  all. A trace of one newline and an answer whose first piece is that same
  newline are the same two characters, and no rule can tell them apart —
  so nothing is taken from an answer over a trace that said nothing.

What the user is shown afterwards is an answer with no text and the flag
that says it stopped at the ceiling; the window draws both of the lines it
has for that (``frontend/src/teile/Nachricht.svelte``).
"""

from __future__ import annotations


class Wache:
    """Watches one stream for its thinking coming back as an answer."""

    def __init__(self) -> None:
        self._denken: list[str] = []
        self._antwort_begonnen = False

    def denken(self, text: str) -> None:
        """One piece the server delivered in its own thinking field."""
        if text:
            self._denken.append(text)

    def antwort(self, text: str) -> None:
        """One piece that really is answer text, and is going out as such."""
        if text:
            self._antwort_begonnen = True

    def ist_wiederholung(self, text: str) -> bool:
        """Whether this content piece is the thinking arriving a second time.

        False as soon as any answer text has gone out: from there on the
        model is writing, and what it writes is its own.
        """
        if self._antwort_begonnen or not text:
            return False
        denken = "".join(self._denken)
        if not denken.strip():
            return False
        return text == denken
