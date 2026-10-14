"""What each row of a chat weighs where a fold draws the boundary of the
verbatim tail.

The boundary is a walk backwards from the newest row until a budget in
characters is used up (``verdichtung.tail_start_from_weights``). It used to
walk over the rows' TEXT alone, so a picture counted as the sentence that
stands in for it when a row says nothing in words, and the tool log not at
all: a chat of twenty pictures and one line of words weighed a few hundred
characters, never passed the budget, and never folded while the request it
opens filled the window.

Here a row weighs what the request that carries it weighs:

* its words, documents read the way the request sends them
  (``zeilentext`` with the plan for this request);
* its pictures at the price a picture costs, or the sentence that goes
  instead where the model cannot see (``picture_weight``);
* its tool log in the shape the offer gives it (``werkzeuggewicht``).

The saving check of the same fold reads the rows through ``row_weight``,
which carries the same pictures and the same tool log.
"""

from __future__ import annotations

from app.verlaufsbau import (
    _ersatzsatz,
    picture_weight,
    werkzeuggewicht,
    zeilentext,
)


def fold_row_weights(
    rows: list,
    repositories,
    *,
    document_plan: dict | None,
    offers_tools: bool = True,
    vision: bool = True,
    pictures: set[int] | None = None,
    tool_log: bool = True,
) -> list[int]:
    """One weight per row, in characters, in the order of ``rows``.

    ``document_plan`` is what the request being built carries of each
    document; without one a document is read as too large for the request
    and weighs only its name, the reading a request without a plan gives it.
    ``offers_tools`` and ``vision`` say what that request offers and whether
    the model sees; ``pictures`` are the tool log entries whose pictures ride
    along again (``tool_pictures_of_rows``). ``tool_log`` says whether the
    tool log counts at all: a caller that has to stay inside what a fold of
    messages weighs (``verdichtung.nachrichtengewicht``) leaves it out.

    A row that says nothing in words and carries a picture weighs the
    picture and not the sentence for an empty row as well: the request sends
    the picture and no sentence.
    """
    weights: list[int] = []
    for row in rows:
        words = zeilentext(row, repositories, dokumentplan=document_plan)
        if words == _ersatzsatz(row):
            # Nothing was said in words: the reading below is the one of the
            # request, where a picture stands for the row on its own.
            picture_chars = picture_weight(row, "", vision)
            if picture_chars:
                words = ""
        else:
            picture_chars = picture_weight(row, words, vision)
        weights.append(
            len(words)
            + picture_chars
            + (werkzeuggewicht(row, offers_tools, pictures) if tool_log else 0)
        )
    return weights
