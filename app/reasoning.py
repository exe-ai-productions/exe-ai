"""Separate the chain of thought from the actual answer text.

Models deliver their chain of thought in three different formats. The
frontend should not have to know about any of this — here every stream is
split into the same two kinds: ``content`` and ``reasoning``.

    native   The server delivers its own field ``delta.reasoning``
             (Gemma 4). Then there is nothing to do here, the provider
             already separates it.
    harmony  Markers in the text: <|channel|>analysis<|message|> … <|end|>
             (GPT-OSS).
    think    <think> … </think> (Magistral, Qwen, DeepSeek-R1).

The parser works chunk by chunk, because during streaming a marker can be
torn apart between two packets. A text ending that could be the start of a
marker is therefore held back until it is clear what it becomes.

One correction of that split made at the end of a run lives here too: a
thought the model never wrote out, which is the answer all the same
(:func:`denktext_als_antwort`).
"""

from __future__ import annotations

from typing import Iterable, Literal

from app import antwortende

Sorte = Literal["content", "reasoning"]

# Marker -> state afterwards. "drop" means: discard the text (control
# plumbing of the format that is neither answer nor chain of thought).
_MARKER: dict[str, list[tuple[str, str]]] = {
    "think": [
        ("<think>", "reasoning"),
        ("</think>", "content"),
    ],
    "harmony": [
        ("<|channel|>analysis<|message|>", "reasoning"),
        ("<|channel|>commentary<|message|>", "reasoning"),
        ("<|channel|>final<|message|>", "content"),
        ("<|end|>", "drop"),
        ("<|return|>", "drop"),
        ("<|start|>", "drop"),
    ],
}


class ReasoningParser:
    """Splits a text stream into answer and chain of thought."""

    def __init__(self, format: str = "none") -> None:
        self.format = format if format in _MARKER else "none"
        self._marker = _MARKER.get(self.format, [])
        self._max_marker = max((len(m) for m, _ in self._marker), default=0)
        self._zustand: str = "content"
        self._rest = ""

    # --- public interface ------------------------------------------------

    def feed(self, text: str) -> list[tuple[Sorte, str]]:
        """Accepts one chunk and returns finished pieces."""
        if not text:
            return []
        if self.format == "none":
            return [("content", text)]

        self._rest += text
        return self._verarbeiten(halte_rest_zurueck=True)

    def finish(self) -> list[tuple[Sorte, str]]:
        """At the end of the stream: emit everything held back."""
        if self.format == "none" or not self._rest:
            rest, self._rest = self._rest, ""
            return [("content", rest)] if rest and self.format == "none" else []
        return self._verarbeiten(halte_rest_zurueck=False)

    # --- Internals -------------------------------------------------------

    def _verarbeiten(self, *, halte_rest_zurueck: bool) -> list[tuple[Sorte, str]]:
        stuecke: list[tuple[Sorte, str]] = []

        while True:
            treffer_position = -1
            treffer_marker = ""
            treffer_zustand = ""
            for marker, zustand in self._marker:
                position = self._rest.find(marker)
                if position != -1 and (treffer_position == -1 or position < treffer_position):
                    treffer_position, treffer_marker, treffer_zustand = position, marker, zustand

            if treffer_position == -1:
                break

            self._ausgeben(stuecke, self._rest[:treffer_position])
            self._rest = self._rest[treffer_position + len(treffer_marker) :]
            self._zustand = treffer_zustand

        if halte_rest_zurueck:
            behalten = self._zurueckzuhalten(self._rest)
            if behalten:
                self._ausgeben(stuecke, self._rest[:-behalten])
                self._rest = self._rest[-behalten:]
            else:
                self._ausgeben(stuecke, self._rest)
                self._rest = ""
        else:
            self._ausgeben(stuecke, self._rest)
            self._rest = ""

        return _zusammenfassen(stuecke)

    def _ausgeben(self, stuecke: list[tuple[Sorte, str]], text: str) -> None:
        if text and self._zustand in ("content", "reasoning"):
            stuecke.append((self._zustand, text))  # type: ignore[arg-type]

    def _zurueckzuhalten(self, text: str) -> int:
        """How many characters at the end could be the start of a marker?"""
        grenze = min(len(text), self._max_marker - 1)
        for laenge in range(grenze, 0, -1):
            schwanz = text[-laenge:]
            if any(marker.startswith(schwanz) for marker, _ in self._marker):
                return laenge
        return 0


def _zusammenfassen(stuecke: Iterable[tuple[Sorte, str]]) -> list[tuple[Sorte, str]]:
    """Merge consecutive pieces of the same kind."""
    ergebnis: list[tuple[Sorte, str]] = []
    for sorte, text in stuecke:
        if ergebnis and ergebnis[-1][0] == sorte:
            ergebnis[-1] = (sorte, ergebnis[-1][1] + text)
        else:
            ergebnis.append((sorte, text))
    return ergebnis


def trennen(text: str, format: str) -> tuple[str, str]:
    """Convenient route for complete text: returns (answer, chain of thought)."""
    parser = ReasoningParser(format)
    stuecke = parser.feed(text) + parser.finish()
    antwort = "".join(t for sorte, t in stuecke if sorte == "content")
    gedanke = "".join(t for sorte, t in stuecke if sorte == "reasoning")
    return antwort, gedanke


def paragraph_break(before: str, after: str) -> str:
    """The line breaks that leave exactly one blank line between two texts.

    The text of an answer comes in rounds: a round writes a sentence, calls a
    tool, and the next round writes on. Joined as they are, "Let me look."
    and a table that follows stand on one line, and the table is not drawn
    as one — Markdown only starts a new block after a blank line. So the
    text of a round is set one blank line below the text before it. Line
    breaks either side already brings count towards it: a text that ends
    with a blank line gets no second one. Nothing is added where either side
    has no visible character — there is nothing to keep apart.
    """
    if not before.strip() or not after.strip():
        return ""
    breaks = before[len(before.rstrip()):].count("\n")
    breaks += after[: len(after) - len(after.lstrip())].count("\n")
    return "\n" * max(0, 2 - breaks)


def denktext_als_antwort(
    antwort: str,
    gedanke: str,
    schlussgedanke: str,
    *,
    schlusstext: str,
    ende_grund: str | None,
    zustand: str,
) -> tuple[str, str]:
    """The answer and the chain of thought, after the one swap that is owed.

    A model that thinks and then answers writes the two into separate
    fields, and the window has a place for each. It can also think and then
    stop without a single visible character: the answer is there, it just
    was not written out, and an empty bubble says less than what the model
    produced. Then the thought the answer ENDED on becomes the answer —
    ``schlussgedanke`` is the thinking of the round the run ended in. The
    deliberation of the tool rounds before it keeps its own place: display,
    never context (``app/verlaufsbau.py``), and no answer either, because
    those rounds were about work that had already been done.

    Every other ending keeps the two apart. A run that was stopped or that
    failed is no finished answer however it ended, whatever word the last
    round that reported one left behind; and a length stop or a tool call
    says where the answer went in words of its own. Only an end the model
    chose counts (``app/antwortende.natuerliches_ende``), and only a closing
    round that never wrote one visible character.

    ``gedanke`` is the whole run's thinking, ``schlussgedanke`` its tail —
    both are filled chunk by chunk in the same branch
    (``app/api/v1/generierung.py``), so what is left over is exactly the
    thinking of the rounds before. ``antwort`` and ``schlusstext`` are cut
    the same way: the whole run's text and the text of the round it ended
    in. The closing round alone decides. A sentence an earlier tool round
    wrote before its call ("Let me look.") is no answer to the question —
    it stays where it stands, and the lifted thought follows it one blank
    line below, as every round's text follows the one before
    (``paragraph_break``).

    The request is not repeated to get a written answer: the thought becomes
    the answer once, and nothing is asked a second time.
    """
    if zustand != "fertig" or not antwortende.natuerliches_ende(ende_grund):
        return antwort, gedanke
    if schlusstext.strip() or not schlussgedanke.strip():
        return antwort, gedanke
    rest = gedanke[: len(gedanke) - len(schlussgedanke)]
    if not antwort.strip():
        return schlussgedanke, rest
    return antwort + paragraph_break(antwort, schlussgedanke) + schlussgedanke, rest
