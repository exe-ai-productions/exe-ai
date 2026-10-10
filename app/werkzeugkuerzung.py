"""Shortening old tool results in the request that is about to go out — the
first step against a window that is filling up, and the only one that needs
no model and no waiting.

What makes a long run heavy is almost never its conversation: it is what the
tools printed. Ten file reads and a handful of commands are a hundred
thousand characters that mattered for one round each and are dead weight
afterwards. Folding them costs a model request and blurs everything else in
the middle along with them; replacing them with one line costs nothing and
happens instantly.

So this runs BEFORE the fold, at the same place the pressure on the window is
read (``app/kontextdruck.py``): first this, and only where the window is
still too full afterwards does a model summarize anything
(``app/verdichtung.py``).

Three rules hold it together:

* **Only the request, never the rows.** A chat's messages and a job's steps
  stay exactly as they are — this works on the message list that is about to
  be sent, so what the reader sees keeps every character. Which results a run
  replaced is kept AS a note in its row (the kinds in ``ERSETZUNGEN``), never
  the replacement itself: the next request (``app/verlaufsbau.py``) hands the
  model the same sentences the run sent.
* **A call and its result stay together.** No message is ever removed, only
  its content replaced: a tool result without the assistant call that asked
  for it is invalid history, and Anthropic answers it with a 400.
* **The protected end keeps its own text.** It is the same boundary the fold
  keeps word for word (``verdichtung.geschuetztes_ende``) — the model's own
  working memory, which is exactly what must not turn into a placeholder.
  Asked of that one function and not rebuilt here: a boundary one message off
  the fold's would blank a result the round that just ran produced, and the
  model would read its own fresh call as having returned nothing.

Inside that protected end one thing still happens: an exact copy of a newer
result points at it instead of carrying the same bytes twice. Nothing is
lost, because what the pointer refers to is in the request in full — and it
is in the protected end too, so the second pass can never come along and
clear it.

A second thing reaches into the protected end for a reason of its own: a
retired picture is replaced wherever it stands, boundary or not, because a
picture ten rounds old is exactly as old as one just outside the boundary —
nothing here keeps its bytes on the window's account a moment longer than it
has to.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import PurePath

from app import dokumentablage, kontextdruck, tokenmass, werkzeugbild
from app.providers import ChatNachricht

# Results shorter than this are left alone. A short result usually IS the
# answer — a number, a path, "ok" — so a placeholder would save nothing while
# costing the model the only line it had.
MINDESTZEICHEN = 200

# What stands where an old result stood, and where an exact copy of a newer
# one stood. Both are read by a model and nothing else, so they are English
# here and not in ``app/locales`` — and a model that has met them elsewhere
# reads them without being told.
#
# Both are far shorter than MINDESTZEICHEN, which is what makes a second pass
# over an already shortened list a no-op: nothing has to remember what it
# already did, because what it did is under the floor.
PLATZHALTER = "[Old tool output cleared to save context space]"
DOPPELT = "[Duplicate tool output — same content as a more recent call]"

# The two kinds, by the name a ROW remembers them under. A run that cleared
# a result writes the kind into its row (`app/api/v1/generierung.py`, the
# closing write), and the rebuild hands the model the same sentence again
# (`app/verlaufsbau.py`): the request after an answer reads like the request
# inside it, which is the whole point of clearing once instead of twice. The
# window keeps every character either way — only the prompt is shortened.
ERSETZUNGEN: dict[str, str] = {
    "platzhalter": PLATZHALTER,
    "doppelt": DOPPELT,
}


def gewicht(nachrichten: list[ChatNachricht]) -> int:
    """What a message list weighs in TOKENS.

    Tokens, because that is the currency the pressure on the window is read
    in (app/kontextdruck.py): the saving used to be counted in characters
    and subtracted from a reading in tokens, and after the change to
    measured tokens that mixture would have made every prune look four
    times as good as it was — no fold would ever have fired again.
    """
    return sum(
        tokenmass.tokens(nachricht.content)
        + kontextdruck.bild_tokens(len(nachricht.alle_bild_urls()))
        for nachricht in nachrichten
    )


def zeichen(nachrichten: list[ChatNachricht]) -> int:
    """What a message list weighs in characters.

    Only the tests still ask this; the program reads :func:`gewicht`. Kept
    because the two are the same sum in two currencies and a reader who has
    to compare them wants both in one place.

    Asked before and after :func:`kuerzen` by both callers, so the pressure
    on the window can be read again against what was actually saved instead
    of against a second estimate of the same thing.

    A picture weighs what the house prices one at (``app/kontextdruck.py``,
    the same call the fold trigger and the answer's own ceiling make): read
    by its text alone, a request that had just dropped five pictures
    reported saving nothing at all.
    """
    return sum(
        len(nachricht.content or "")
        + kontextdruck.bild_zeichen(len(nachricht.alle_bild_urls()))
        for nachricht in nachrichten
    )


# How many pictures a tool read stay in the request, counted from the newest.
# Three are what a model still refers back to, and every one before them
# costs a full picture's worth of window for a round nobody is looking at
# any more.
WERKZEUGBILDER_BEHALTEN = 3

# What stands where a picture was. The sentence after it is the note a
# document too large to travel already carries (``app/dokumentablage.py``,
# ``nachlesehinweis``), so there is one way of saying "it is still there,
# read it again".
BILD_ENTFERNT = (
    "[An image this tool read was removed here to save context space.]"
)


def _bildnachricht(nachricht: ChatNachricht) -> bool:
    """Whether this message carries pictures a TOOL read.

    Told apart from a user's own attachment by where the pictures came from
    (``app/werkzeugbild.py`` fills ``werkzeugbilder``), not by the text:
    a user's own uploads stay untouched, because a picture somebody attached
    themselves is part of what they asked.
    """
    return bool(nachricht.werkzeugbilder) and bool(nachricht.alle_bild_urls())


def _ohne_bild(nachricht: ChatNachricht) -> ChatNachricht:
    """The same message with its pictures retired and said out loud."""
    hinweise = "".join(
        dokumentablage.nachlesehinweis(pfad) for pfad in nachricht.werkzeugbilder
    )
    return replace(
        nachricht, bild_url=None, bild_urls=[], content=f"{BILD_ENTFERNT}{hinweise}"
    )


def _kuerzbar(nachricht: ChatNachricht) -> str | None:
    """The content of a tool result worth shortening, or ``None``.

    ``None`` for everything that is not a tool result and for one that is
    already at or under the floor — a placeholder written by an earlier pass
    included.
    """
    if nachricht.role != "tool":
        return None
    inhalt = nachricht.content or ""
    if len(inhalt) < MINDESTZEICHEN:
        return None
    return inhalt


def kuerzen(
    nachrichten: list[ChatNachricht], geschuetzt_ab: int
) -> tuple[list[ChatNachricht], int]:
    """``(nachrichten, count)`` with old tool results replaced by a line.

    ``geschuetzt_ab`` is where the protected end begins — what
    ``verdichtung.geschuetztes_ende`` answers for the same list and the same
    budget the fold would use. Everything from there on keeps its own text.

    Returns the INPUT list unchanged together with ``0`` where nothing was
    shortened, so a caller can tell "nothing to do" from "done" by the count
    alone and never has to compare lists.

    Two passes, on the two sides of that one boundary:

    1. **Exact copies inside the protected end**, walked from the newest
       message backwards. The newest copy keeps its text and every older one
       points at it. Only here, and that is what makes it safe: what the
       pointer refers to is protected too, so the second pass cannot clear it
       out from under the pointer. Ahead of the boundary a copy needs no
       pointer anyway — it is about to become a placeholder.
    2. **Everything old**, ahead of the protected end only. A result that has
       been in the history for many rounds has done its work; what the model
       needs from it by now is that a call happened and that its output is
       gone, which is what the placeholder says.

    A message is only ever rewritten, never dropped: the call that asked for
    a result and the result itself have to travel together.
    """
    if not nachrichten:
        return nachrichten, 0
    grenze = max(0, min(geschuetzt_ab, len(nachrichten)))
    neu = list(nachrichten)
    anzahl = 0

    # The contents themselves rather than a digest of them: they are already
    # in memory in this very list, so a hash buys no room and can collide,
    # where a comparison of the strings cannot.
    gesehen: set[str] = set()
    for stelle in range(len(neu) - 1, grenze - 1, -1):
        inhalt = _kuerzbar(neu[stelle])
        if inhalt is None:
            continue
        if inhalt in gesehen:
            neu[stelle] = replace(neu[stelle], content=DOPPELT)
            anzahl += 1
        gesehen.add(inhalt)

    for stelle in range(grenze):
        if _kuerzbar(neu[stelle]) is None:
            continue
        neu[stelle] = replace(neu[stelle], content=PLATZHALTER)
        anzahl += 1

    # The pictures a tool read, oldest first — everything before the newest
    # ``WERKZEUGBILDER_BEHALTEN`` of them, counted per PICTURE rather than per
    # message: a round that reads several into one message must not let that
    # message's single position hide them all from the cut. On the request
    # only, never on a row. The protected end does not apply here — a
    # picture ten rounds old is old wherever it sits, and what replaces it
    # says where to read it again.
    bildinstanzen = [
        (stelle, index)
        for stelle, n in enumerate(neu)
        if _bildnachricht(n)
        for index in range(len(n.werkzeugbilder))
    ]
    ausgemustert_je_nachricht: dict[int, set[int]] = {}
    for stelle, index in bildinstanzen[: max(0, len(bildinstanzen) - WERKZEUGBILDER_BEHALTEN)]:
        ausgemustert_je_nachricht.setdefault(stelle, set()).add(index)
        anzahl += 1

    # A message loses only its retired pictures — the ones a round left
    # beside it keep their introduction (``EINLEITUNG``), by the short name
    # the result itself was read under (a path's own last part — the same
    # name ``app/tools/datei_lesen.py`` hands to ``modellbild`` beside the
    # full path). Retiring the last one is the special case already covered by
    # ``_ohne_bild``, kept as is rather than folded in here: an empty picture
    # list is not "a shorter version of the sentence", it is the sentence
    # that names no picture at all.
    ausgemusterte_ergebnisse: set[int] = set()
    for stelle, indices in ausgemustert_je_nachricht.items():
        nachricht = neu[stelle]

        # The round's own image-announcing results, in the same order this
        # message's own pictures were collected in (``modellbild`` in
        # ``app/api/v1/generierung.py`` and ``auftraege.py`` fills both lists
        # together, call by call). Matched by POSITION, not by path: the same
        # file can be read twice in one round, and pairing by path would take
        # the promise from the kept instance's result along with the retired
        # one's.
        #
        # Read against the INPUT list, not ``neu``: the two passes above
        # this one already rewrite a tool result's content — a duplicate or
        # an old one — and a result rewritten before this pass runs would no
        # longer match ``gelesener_bildpfad``, dropping out of the count and
        # shifting every index after it onto the wrong result.
        for zurueck in range(stelle - 1, -1, -1):
            aufrufe = nachrichten[zurueck].werkzeugaufrufe or []
            if not aufrufe:
                continue
            namen = {a.id: a.name for a in aufrufe}
            ergebnis_stellen = []
            for stelle2 in range(zurueck + 1, stelle):
                original = nachrichten[stelle2]
                kennung = original.werkzeugaufruf_id
                if kennung not in namen or original.role != "tool":
                    continue
                if werkzeugbild.gelesener_bildpfad(namen[kennung], original.content):
                    ergebnis_stellen.append(stelle2)
            for index in indices:
                if index < len(ergebnis_stellen):
                    ausgemusterte_ergebnisse.add(ergebnis_stellen[index])
            break

        behalten = [i for i in range(len(nachricht.werkzeugbilder)) if i not in indices]
        if not behalten:
            neu[stelle] = _ohne_bild(nachricht)
            continue
        hinweise = "".join(
            dokumentablage.nachlesehinweis(nachricht.werkzeugbilder[i]) for i in sorted(indices)
        )
        einleitung = werkzeugbild.EINLEITUNG.format(
            namen=", ".join(PurePath(nachricht.werkzeugbilder[i]).name for i in behalten)
        )
        neu[stelle] = replace(
            nachricht,
            bild_url=None,
            bild_urls=[nachricht.bild_urls[i] for i in behalten],
            werkzeugbilder=[nachricht.werkzeugbilder[i] for i in behalten],
            content=f"{einleitung}{BILD_ENTFERNT}{hinweise}",
        )

    # A picture that leaves the request takes the promise out of its own
    # result. The message says the picture was removed while the result next
    # to it still says "is attached below … Say what you see in it now" — two
    # sentences about one picture in one request, and the promise is the
    # false one. What goes in is the bare placeholder, not another copy of
    # the note — the path already stands in the message beside it
    # (``_ohne_bild`` or the partial replacement above, ``BILD_ENTFERNT`` plus
    # the note). A round with no such message — ``verlaufsbau.py`` rebuilding
    # a history from stored rows, never this pass — is the one place the note
    # belongs on the result itself, and keeps it there untouched.
    for stelle in ausgemusterte_ergebnisse:
        neu[stelle] = replace(neu[stelle], content=werkzeugbild.NICHT_MEHR_DABEI)

    if not anzahl:
        return nachrichten, 0
    return neu, anzahl
