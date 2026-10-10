"""Between two rounds of a chat answer or a job run: report the context,
clear old tool results, report again, fold — one step for both.

A round's own tool results are in the history the moment the round ends and
in none of its readings, so this is the first moment the next request can be
weighed at all. The chat and the job ask the same questions here, in the same
order, and used to ask them in two copies that had already drifted apart (one
reported where a reading of the round stood, the other where any reading
stood). This is the one step every caller shares.

What differs between the two callers is only what they do with each step's
outcome — the chat sends it to the window and remembers which results it
cleared, the job writes it into its own transcript — so the step hands its
outcomes back as they happen (:func:`between_rounds`) and does nothing else
with them.

The readings it reports are measured against the WHOLE window, as the
context bar shows it (``app/kontextdruck.py`` ``stand``). The trigger itself
measures the same total against the window less an answer length somebody
set (``kontextdruck.ueber_der_schwelle``): with a set length, the bar can
stand below the threshold's own share when a fold fires.
"""

from __future__ import annotations

import dataclasses
from typing import Any, AsyncIterator

from app import antwortgrenze, kontextdruck, tokenmass, verdichtung, werkzeugkuerzung
from app.kontextverbrauch import Kontextstand
from app.providers import ChatNachricht


@dataclasses.dataclass
class Cleared:
    """Old tool results were replaced by a line in the request: ``count``
    of them, saving ``saved`` tokens. ``before`` and ``after`` are the
    request's messages either side, in the same order."""

    count: int
    saved: int
    before: list[ChatNachricht]
    after: list[ChatNachricht]


@dataclasses.dataclass
class Folded:
    """A model was asked to fold the request's middle; ``result`` is what
    ``verdichtung.verdichten`` answered."""

    result: verdichtung.Ergebnis


def new_tokens(nachrichten: list[ChatNachricht], appended_from: int) -> int:
    """What the messages from ``appended_from`` on weigh — the round's own
    tool results, appended after the round's last reading was taken.

    A picture a tool read weighs what every other picture weighs
    (``app/kontextdruck.py``): counted by its text alone it would add a line
    and a half to the reading while adding thousands of tokens to the
    request, and the fold would not fire.
    """
    return sum(
        tokenmass.tokens(nachricht.content)
        + kontextdruck.bild_tokens(len(nachricht.alle_bild_urls()))
        for nachricht in nachrichten[appended_from:]
    )


async def between_rounds(
    zustand,
    anfrage,
    *,
    last_reading: int | None,
    appended_from: int,
    threshold: float,
    set_limit: int | None,
    fold_allowed: bool,
    key: str,
    settings: Any,
    endpoint_id: str,
) -> AsyncIterator[Kontextstand | Cleared | Folded]:
    """The step between two rounds, its outcomes handed back as they happen.

    ``last_reading`` is the last total known for the request — the
    provider's count of the round just ended, or what an earlier report
    raised it to. Only where one stands is a reading reported: the round's
    results alone are not a context reading. ``appended_from`` is where the
    round's own tool results begin in ``anfrage.nachrichten``.

    In this order — the first always, each after it only where the request
    still stands at or above ``threshold``:

    1. The total the trigger weighs, as a share of the whole window (a
       :class:`Kontextstand`).
    2. Old tool results cleared, in the request alone (:class:`Cleared`) —
       and the reading again, less what that saved.
    3. Where still too full, ``fold_allowed`` and a middle to fold: a model
       folds the request in memory (:class:`Folded`). Where it did, the
       request is weighed again and that reading follows — the reading
       before the fold described the longer request, and the next answer
       would otherwise fold again at once over a number that is gone.

    ``anfrage.nachrichten`` is changed in place by steps 2 and 3. Every
    reading is an estimate: the caller reports it at the live pace and
    estimates on from it.
    """
    window = zustand.context_tokens
    added = new_tokens(anfrage.nachrichten, appended_from)
    if last_reading is not None:
        reading = kontextdruck.stand(last_reading, added, window)
        if reading is not None:
            yield reading
    if not kontextdruck.ueber_der_schwelle(last_reading, added, window, threshold, set_limit):
        return
    # The tail sized for this model, not the fixed ceiling: on a small
    # context the ceiling covers the whole history and nothing below could
    # ever be reached.
    budget = verdichtung.schwanz_budget(window, threshold)
    # Step one, and no model asked: what the tools of earlier rounds printed
    # is replaced by a line in the REQUEST (app/werkzeugkuerzung.py).
    after, count = werkzeugkuerzung.kuerzen(
        anfrage.nachrichten,
        verdichtung.geschuetztes_ende(anfrage.nachrichten, budget),
    )
    saved = 0
    if count:
        # What it saved, measured on the list rather than estimated a second
        # way, and taken off the same estimate the trigger was read from: the
        # characters are gone from the request whether they sat in this
        # round's own results or in an older round the last reading counted.
        before = list(anfrage.nachrichten)
        saved = werkzeugkuerzung.gewicht(before) - werkzeugkuerzung.gewicht(after)
        anfrage.nachrichten[:] = after
        yield Cleared(count=count, saved=saved, before=before, after=list(after))
        if last_reading is not None:
            reading = kontextdruck.stand(last_reading, added - saved, window)
            if reading is not None:
                yield reading
    if not (
        fold_allowed
        and kontextdruck.ueber_der_schwelle(
            last_reading, added - saved, window, threshold, set_limit
        )
        and verdichtung.noetig(anfrage.nachrichten, budget)
    ):
        return
    result = await verdichtung.verdichten(
        zustand,
        anfrage,
        budget,
        schluessel=key,
        einstellungen=settings,
        endpoint_id=endpoint_id,
    )
    yield Folded(result=result)
    if result.angewendet:
        reading = kontextdruck.stand(
            antwortgrenze.eingabe_schaetzen(anfrage.nachrichten, anfrage.werkzeuge),
            0,
            window,
        )
        if reading is not None:
            yield reading
