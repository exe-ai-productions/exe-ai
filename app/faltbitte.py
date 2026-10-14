"""What the "summarize this" request carries, and how wide it may get.

A fold asks a model to replace a settled stretch of the conversation with a
short status. Two callers build that request — ``app/chatverdichtung.py``
for a chat, ``app/verdichtung.py`` for a job — and the words of the turns
were not all of what those turns were: the tools an answer called, and what
those tools returned, either never reached the summarizer at all (the chat)
or reached it whole, with one result able to be the entire request (the
job). What a tool FOUND is most of what a long stretch of work is about, so
a summary written without it could not carry it, and after the fold it was
gone from every later prompt unless an answer had repeated it by hand.

So the calls travel, and because a single result can be megabytes they
travel capped: one ceiling on each call's arguments and result, and one over
the whole request.

The rule that holds for every cut in here: **nothing is shortened without
saying so.** Every cut leaves a visible note in the text, so the model reads
a gap as a gap instead of as the end of the matter. What is shortened is
only ever what the SUMMARIZER is shown — a chat's rows stay in the database
and stay readable behind the seam either way. A run's history is the one
copy there is (``app/verdichtung.py`` rewrites it in place), so there the
note is all that is left of what went.

The ceiling on a result in here is what a JOB's request meets: there the
messages in the store carry the results whole, and the request is written
from those. A chat hands its results in already cut to what its own
prompts carry (``app/verlaufsbau.py``, ``VERLAUF_ERGEBNIS_ZEICHEN``), which
is far less — and rightly so: since the call ran, no prompt of that chat
has shown the model more than that, so a summary cannot be asked to write
down what nobody in the chat ever saw. Both hand in one shape, and the
ceilings here are the roof over it, not a second cut of the same text.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from app import antwortgrenze, kontextvoll
from app.providers import ChatNachricht
from app import tokenmass

# A call's arguments.
# Shortened from the END only: arguments say what was ASKED FOR, and the
# front of them is the path, the pattern, the command — a write call's
# kilobytes of file content sit behind that and say nothing a summary needs.
ARGUMENTE_MAX = 1_500
ARGUMENTE_KOPF = 1_200

# What one call returned. Shortened from the MIDDLE: a long output says what
# it is at the top and how it ended at the bottom, and the end is where the
# error, the exit code and the last line are.
ERGEBNIS_MAX = 6_000
ERGEBNIS_KOPF = 4_000
ERGEBNIS_FUSS = 1_500

# The whole request at most — some 40,000 tokens at the house proxy. Without
# it a long conversation asks a model to summarize more than that model can
# read at all: the request is refused or answered with nothing, and the fold
# that was supposed to bring the context down fails on every turn.
#
# The UPPER bound, not the ceiling every model gets: where the window holds
# less, the window lowers it (:func:`deckel`). One fixed number for every
# model sent a small model a request too large for it, and the fold then
# asked nobody at all. The smaller of the two wins — the same reading the
# answer's own ceiling takes (``app/antwortgrenze.py``): the most that fits
# goes out.
BITTE_MAX = 160_000

# The room in the window the summary keeps for itself, in tokens: a share of
# the window, never below the floor and never above the ceiling.
# Without it a request given "everything that fits" fills the window to the
# brim, and the summary it asks for has a single token left to be written in.
RESERVE_MIN = 2_000
RESERVE_MAX = 10_000
RESERVE_ANTEIL = 0.05
# Of what is left after the note, the share kept from the front. Slightly
# less than half, because the recent end of a stretch carries more of what
# is still being worked on than its opening does.
KOPFANTEIL = 0.45

# What a shortened piece ends with, or carries in its middle, so the model
# can tell a cut from a text that simply stopped there.
ARGUMENTE_VERMERK = "…[truncated]"
ERGEBNIS_VERMERK = "\n…[truncated]…\n"
BITTE_VERMERK = (
    "\n\n…[Summary input truncated: {ausgelassen} characters were omitted from the middle to "
    "limit the request size.]…\n\n"
)

# The line above an answer's tool block. Read from here by the ordinary
# request without tools as well (``app/verlaufsbau.py``,
# ``_werkzeuge_als_text``) rather than spelled twice: the block means the
# same thing in both, and a model that has learned to read one reads the
# other.
KOPFZEILE = "[Tool calls made while composing this response and their results]"

# What stands where a call returned nothing at all — an empty result is a
# result, and a bare arrow reads like a call that never finished.
OHNE_AUSGABE = "[no output]"


def _argumente(argumente: Any) -> str:
    """A call's arguments as text, shortened from the end."""
    text = (
        json.dumps(argumente, ensure_ascii=False)
        if isinstance(argumente, dict)
        else "{}"
    )
    if len(text) > ARGUMENTE_MAX:
        text = text[:ARGUMENTE_KOPF] + ARGUMENTE_VERMERK
    return text


def _ergebnis(ergebnis: Any) -> str:
    """What a call returned, shortened from the middle."""
    text = ergebnis if isinstance(ergebnis, str) else ""
    if len(text) > ERGEBNIS_MAX:
        text = text[:ERGEBNIS_KOPF] + ERGEBNIS_VERMERK + text[-ERGEBNIS_FUSS:]
    return text.strip() or OHNE_AUSGABE


def werkzeug_fuer_bitte(
    werkzeuge: Sequence[tuple[str, Any, Any]], inhalt: str
) -> str:
    """An answer's tool calls, with what came back, above its own text.

    ``werkzeuge`` is one ``(name, arguments, result)`` triple per call, in
    the order the calls were made. That is the one form both ways can hand
    in: a chat reads them out of the stored tool log of the row
    (``app/verlaufsbau.py``), a job out of the messages of the request it is
    already holding (``app/verdichtung.py``), and neither shape belongs in
    here.

    A call and its result stand in ONE line, in the order they happened, so
    nothing has to be paired up again by whoever reads this — which is the
    failure the job path had: its result travelled in a message of its own,
    and a middle that began behind the call carried a result nothing
    explained.

    Answers ``inhalt`` unchanged where there was no call, so a caller can
    ask for every row without knowing which ones used tools.
    """
    zeilen = [
        f"- {name} {_argumente(argumente)} → {_ergebnis(ergebnis)}"
        for name, argumente, ergebnis in werkzeuge
        if name
    ]
    if not zeilen:
        return inhalt
    block = KOPFZEILE + "\n" + "\n".join(zeilen)
    return f"{block}\n\n{inhalt}" if inhalt else block


def reserve(fenster: int) -> int:
    """The tokens of ``fenster`` the summary keeps free for itself."""
    return max(RESERVE_MIN, min(int(fenster * RESERVE_ANTEIL), RESERVE_MAX))


def deckel(
    fenster: int | None,
    mitreisend: list[ChatNachricht],
) -> int:
    """How many TOKENS of history the compaction request may carry.

    What the window really holds once
    the summary's :func:`reserve`, the margin every request keeps
    (``kontextvoll.SICHERHEITSABSTAND``) and whatever else travels in the
    same request are set aside. ``mitreisend`` is that rest as messages —
    the ask, and the pictures of the history. The request offers no tools,
    so none are weighed. The rest is weighed by
    ``antwortgrenze.eingabe_schaetzen``, the very estimate the request's own
    ceiling is worked out with afterwards, so the summary is left exactly the
    reserve and not one token of it goes to the history.

    An unknown window (an endpoint that stopped answering) leaves
    :data:`BITTE_MAX` standing, as it always did. Never below zero.
    """
    if fenster is None:
        return BITTE_MAX
    passt = (
        fenster
        - reserve(fenster)
        - kontextvoll.SICHERHEITSABSTAND
        - antwortgrenze.eingabe_schaetzen(mitreisend)
    )
    return max(0, passt)


def deckel_zeichen(text: str, passt_tokens: int) -> int:
    """``passt_tokens`` turned into a length for THIS text.

    Measured on the text in hand instead of assumed: ASCII runs about four
    characters to the token, Cyrillic about two (app/tokenmass.py). A flat
    four here cut a Russian history to twice the tokens it was allowed, and
    the request the ceiling exists to keep inside the window went out over
    it. One corrective pass after the cut, because the note :func:`deckeln`
    writes into the seam costs tokens of its own.
    """
    if passt_tokens <= 0 or not text:
        return 0
    je_token = len(text) / max(1, tokenmass.tokens(text))
    grenze = min(BITTE_MAX, int(passt_tokens * je_token))
    for _ in range(3):
        gewicht = tokenmass.tokens(deckeln(text, grenze))
        if gewicht <= passt_tokens or grenze <= 0:
            break
        grenze = int(grenze * passt_tokens / gewicht) - 1
    return max(0, grenze)


def deckeln(text: str, grenze: int = BITTE_MAX) -> str:
    """``text`` at most ``grenze`` characters, cut from the middle and saying
    how much it left out.

    The front and the end survive: the front says what the conversation was
    about, the end is what is still being worked on. What goes is the
    middle of the middle, and the note in its place names the number of
    characters, so the model reads the seam instead of reading two halves as
    one continuous history.
    """
    if len(text) <= grenze:
        return text
    # The note's own width depends on the number printed inside it, and that
    # number depends on the note's width. Estimated once from the whole
    # length and rebuilt once, which settles it: the second pass can only
    # move the count by the digits of the note itself, and the result is
    # never over the ceiling because the note is measured before the halves
    # are cut.
    ausgelassen = len(text)
    kopf = fuss = 0
    for _ in range(2):
        vermerk = BITTE_VERMERK.format(ausgelassen=ausgelassen)
        rest = max(grenze - len(vermerk), 0)
        kopf = int(rest * KOPFANTEIL)
        fuss = rest - kopf
        ausgelassen = max(len(text) - kopf - fuss, 0)
    return (
        text[:kopf].rstrip()
        + BITTE_VERMERK.format(ausgelassen=ausgelassen)
        + (text[-fuss:].lstrip() if fuss else "")
    )


def gedeckelt(
    nachrichten: list[ChatNachricht],
    fenster: int | None,
) -> list[ChatNachricht] | None:
    """The finished compaction request, never wider than :func:`deckel` for
    ``fenster``, or ``None`` where not one character of the history fits.

    ``None`` means no model is to be asked. Once the note saying what was
    left out has taken its width, a request with no history left in it would
    ask for a summary of nothing, and that summary would replace the middle.
    Answered here, where the ceiling is worked out, and not by the caller's
    "no room" arithmetic: a request that small leaves that arithmetic plenty
    of room.

    The last message is the ask — "summarize this" — on both ways, and it
    is never touched: it is what the request is FOR, it is short, and a
    model reading a cut instruction writes something else than a summary.
    Only the history in front of it is bounded.

    Under the ceiling the list is handed back as it came — untouched, not
    rebuilt — so a request that was never too large is exactly the request
    the caller built.

    Over it, there is no keeping the message borders and the ceiling both:
    what has to go is a stretch in the middle, and it does not stop politely
    at a border. So the history is written out with its roles into one
    text, that text is cut (:func:`deckeln`), and it travels as the one
    ``user`` message in front of the ask.

    Called by each way right after it has assembled its messages, and
    deliberately not further down in ``faltversuche.anfordern``, where both
    ways also meet: before the request goes out, each of them works out
    whether the window leaves room to write a summary at all
    (``app/antwortgrenze.py``). Measured against the UNCAPPED length, that
    arithmetic answers "no room" for exactly the conversations this ceiling
    exists for — a long history on a large model — and the fold would ask
    no model and fold nothing.
    """
    if not nachrichten:
        return nachrichten
    *verlauf, frage = nachrichten
    bilder = [url for n in verlauf for url in n.alle_bild_urls()]
    passt_tokens = deckel(
        fenster,
        [frage, ChatNachricht(role="user", content="", bild_urls=bilder)],
    )
    ganz = "\n\n".join(
        f"[{(n.role or '').upper()}]: {n.content or ''}" for n in verlauf
    )
    grenze = (
        BITTE_MAX if fenster is None else deckel_zeichen(ganz, passt_tokens)
    )
    if len(ganz) <= grenze:
        return nachrichten
    if grenze <= len(BITTE_VERMERK.format(ausgelassen=len(ganz))):
        # The note alone fills the ceiling: what :func:`deckeln` would hand
        # back is the note and nothing of the history.
        return None
    return [
        ChatNachricht(
            role="user",
            content=deckeln(ganz, grenze),
            # The pictures come along. They are not text and survive no
            # collapse into text, so dropping them here would mean the same
            # history reaches the summarizer with its pictures below the
            # ceiling and without them above it — one shape behaving two
            # ways, and the silent half is the one nobody would notice.
            bild_urls=bilder,
        ),
        frage,
    ]
