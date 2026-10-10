"""One reading of a provider's refusal: was the model's context full — and,
where it was, everything that refusal has to teach, written down before the
caller does anything else with it.

Three calls used to stand side by side at every place a provider error is
caught: the question itself (``app/kontextvoll.py``) and the two halves of
the request that learn from the same sentence — the window it did not fit
into (``app/fenstergroesse.py``) and the output limit it named, if it named
one (``app/antwortgrenze.py``). Four call sites had to be kept in step by
hand, and one of them was once left with only the first of the two learners
until it was found and fixed separately; a fifth would have to remember all
three again from scratch.

Here they are one call, for the chat path and the job path alike, so a
caller gets all of them or none.
"""

from __future__ import annotations

from app import antwortgrenze, fenstergroesse, kontextvoll


def fenster_voll(
    repositories, zustand, fehler: BaseException, zug: antwortgrenze.Zug | None = None
) -> bool:
    """True where this error says the request was too long for the model —
    its context was full, or the answer's length is more than the model
    takes (two separate signals, ``kontextvoll.bei_fehler`` and
    ``kontextvoll.output_cap_error``; ``kontextvoll.abhilfe`` cures both) —
    and then both halves of it have learned from the refusal by the time
    the answer comes back. Which of the two it was is asked of
    ``kontextvoll.output_cap_error`` where an ending is named.

    ``zug`` is the refused request's own holder for the output limit
    (``app/antwortgrenze.py``), handed in where that request is about to be
    sent again; without one the request is over and the limit binds nobody.

    Order does not matter and neither learner needs anything the other
    reads: each takes its own number out of the refusal and does nothing at
    all where that number is not in it. Which is why both are called on
    every full window rather than one of them being picked here — what the
    refusal names is what gets learned.

    False is the ordinary error, untouched: nothing is learned from a
    sentence that was never about a full context or the answer's length.
    """
    if not (kontextvoll.bei_fehler(fehler) or kontextvoll.output_cap_error(fehler)):
        return False
    fenstergroesse.aus_fehler_lernen(repositories, zustand, fehler)
    antwortgrenze.aus_fehler_lernen(repositories, zustand, fehler, zug)
    return True
