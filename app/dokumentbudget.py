"""How much of a chat's documents one request may carry — decided by the
model in hand, not by a number somebody wrote into the code.

A document used to travel whole up to a fixed 24,000 characters and, past a
fixed 15,000, as six fixed sections that fit the question. Both numbers
were guesses that had nothing to do with the model: a model with a window
of a million tokens got the same eight pages as one with eight thousand,
and a question like "summarize this" got six passages that happened to
resemble the word "summarize".

What the big services do is simpler, and it is what this module does:

* Fits the document into the model's context window, and stays under a
  ceiling of half that window for the documents of one request together
  (``DOKUMENT_OBERGRENZE_ANTEIL`` below)? Then it goes whole. That
  is what Claude does with a 200k window and Gemini with a million.
* Does it not fit, or would it cross that ceiling? Then nothing travels.
  The model is told the document is there and how big it is, not shown a
  fraction of it — a partial reading would look like the whole and never
  say so.

The budget is the window minus what the request already carries: the
answer's own ceiling, the system text and the rows of the conversation,
and a reserve for the difference between counted characters and the
model's tokens. Several documents share it, the newest first — the one the
user just attached is the one the question is most likely about.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.tokenmass import tokens as tokenmass_tokens

# Characters per token is the house proxy (app/tokenmass.py); the reserve
# covers what that proxy gets wrong on German text, markup and numbers, and
# leaves room for the request's own scaffolding.
RESERVE_ANTEIL = 0.2

# The answer's ceiling is a ceiling, not a reservation: a model server
# clamps it to what is left of the window anyway. Held back in full it would
# leave a small window with no room for any document at all — a ceiling set
# by hand can be the whole window of a small model. So at most a quarter of
# the window is kept free for a ceiling somebody named.
#
# An unnamed one holds nothing back at all: "Auto" IS what is left over
# (app/antwortgrenze.py), so reserving a share for it would take room away
# from the documents and give it back to the same answer twice. The reserve
# above stays either way — it covers the character-to-token proxy, not the
# answer.
ANTWORT_ANTEIL_HOECHSTENS = 0.25

# A document this short travels whole even past the budget: naming it would
# cost the request about as much as sending it. In tokens now, like the
# budget beside it — the same thousand characters it used to mean, at the
# rough ratio that was in force when the number was picked.
IMMER_GANZ_TOKENS = 250

# However free the window looks, the documents of one request never weigh
# more than half of it — a second, model-independent limit that catches the
# character-per-token proxy above guessing wrong: that proxy once let a
# document through the server then priced at 308,703 tokens against a window
# of 262,144.
DOKUMENT_OBERGRENZE_ANTEIL = 0.5


@dataclass(frozen=True)
class Anteil:
    """What one document contributes to a request.

    ``ganz``: the whole text travels. Otherwise the document is only named
    — the request has no room left for it.
    """

    ganz: bool

    def tokens(self, gewicht: int) -> int:
        """What this contribution costs the request, at most."""
        return gewicht if self.ganz else 0


def budget_tokens(
    context_tokens: int, max_tokens: int | None, belegt_tokens: int = 0
) -> int:
    """How many TOKENS of documents this request may carry.

    Tokens and no longer characters: the old form multiplied the free
    tokens by a flat four and compared the answer against a character
    count. As measured, that let a 600-page PDF through whose
    text the server then priced at 308,703 tokens against a window of
    262,144 — the user saw the provider's raw refusal instead of the card
    that says "document too large". What a text weighs is now measured
    (app/tokenmass.py) instead of divided.

    ``belegt_tokens`` is what the request holds before any document: the
    system text, the conversation's rows AND the tool definitions that go
    out with every request — 7,688 tokens for the shipped offer, as
    measured, and the one part the old reckoning left out entirely.
    Part of the window is kept free for the answer as well.
    ``context_tokens`` is never unknown by the time this is called:
    discovery resolves a window (app/fenstergroesse.py) before an endpoint
    counts as reachable.
    """
    antwort = min(
        max(0, int(max_tokens or 0)), int(context_tokens * ANTWORT_ANTEIL_HOECHSTENS)
    )
    frei_tokens = int(context_tokens * (1 - RESERVE_ANTEIL)) - antwort
    verbleibend = max(0, frei_tokens - max(0, belegt_tokens))
    return min(verbleibend, int(context_tokens * DOKUMENT_OBERGRENZE_ANTEIL))


def verteilen(dokumente, budget: int) -> dict[str, Anteil]:
    """Shares the budget among the documents, in the order handed in — the
    caller passes the newest first.

    A document that fits into what is left goes whole — and so does one no
    heavier than ``IMMER_GANZ_TOKENS``, whatever is left. One that does not
    fit is only named.
    """
    plan: dict[str, Anteil] = {}
    rest = max(0, budget)
    for dokument in dokumente:
        gewicht = tokenmass_tokens(dokument.extracted_text)
        if gewicht <= rest or gewicht <= IMMER_GANZ_TOKENS:
            plan[dokument.id] = Anteil(ganz=True)
            rest = max(0, rest - gewicht)
            continue
        plan[dokument.id] = Anteil(ganz=False)
    return plan


def beitrag(dokument, plan: dict[str, Anteil] | None) -> int:
    """What a document costs the request under ``plan`` — for whoever weighs
    a prompt before it is built.

    Whole documents count at their real length, everything else at zero —
    a document only named, one the plan says nothing about, or no plan at
    all (a caller with no documents in hand at all) costs the request
    nothing.
    """
    gewicht = tokenmass_tokens(dokument.extracted_text)
    anteil = (plan or {}).get(dokument.id)
    return anteil.tokens(gewicht) if anteil is not None else 0


def beitrag_zeichen(dokument, plan: dict[str, Anteil] | None) -> int:
    """The same contribution, in characters.

    For the one reader that weighs a history in characters because it CUTS
    one (app/chatverdichtung.py's middle against the summary offered for
    it). Mixed currencies here were what stopped the fold firing at all: a
    middle counted in characters with its documents counted in tokens reads
    a quarter of its real weight.
    """
    laenge = len(dokument.extracted_text or "")
    anteil = (plan or {}).get(dokument.id)
    return laenge if anteil is not None and anteil.ganz else 0
