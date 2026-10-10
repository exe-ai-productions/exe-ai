"""How long a fold stays away from the model after one failed, and when
automatic folding gives up for a while.

A fold that failed says something about the very next fold: the model that
could not write a summary a second ago will not write one a second later,
and every attempt costs the answer behind it a full request's wait. So a
failure books a pause, and inside that pause NO fold request goes to a model
at all — not the automatic one and not the forced one. The forced path folds
nothing then either and leaves the history as it is: "forced" here means
"otherwise no answer comes at all", not "the user asked for it", and the
model has just demonstrated it cannot summarize.

Two failed folds in a row switch automatic folding off for that chat or
run. Not for good — the transcript keeps growing, and a stretch that could
not be summarized then can be summarizable later. After
``WIEDERAUFNAHME_SEKUNDEN`` of being blocked, exactly one automatic attempt
is let through — and it is spent by a request that really goes to a model,
not by the check that asks whether folding is allowed. If that one attempt
fails again, the block is back at once, and a success clears everything.

All of it in memory, one entry per key (a chat id, or a run id). A restart
clears it deliberately: a pause is a fact about right now, and a program
that starts up must not inherit "the model was broken" from the one before
it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

# Which pause a failure earns. Two of them, and no ladder: a rising ladder
# would have to tell a timeout from any other network error, and by the time
# a failure reaches us it no longer is one — the provider layer wraps every
# transport error, timeouts included, into one error carrying a status and
# raw text (app/providers/openai_kompatibel.py, app/providers/base.py). A
# ladder built on a distinction that is not there would simply be the long
# pause under another name.
#
# An empty, cut-off or unreadable answer, or a stream that broke off: the
# request went out and something came back, so the next one is worth trying
# soon.
KURZ = "kurz"
PAUSE_KURZ = 30.0
# Everything else, a timeout included. No rising ladder for timeouts, for
# the reason above. The cost is known and accepted: a server that hangs is
# asked again every 60 seconds instead of ever more rarely.
LANG = "lang"
PAUSE_LANG = 60.0

PAUSEN = {KURZ: PAUSE_KURZ, LANG: PAUSE_LANG}

# How many emergency folds in a row switch automatic folding off.
NOTFAELLE_BIS_STOPP = 2

# How long that block lasts before one single automatic attempt is let
# through again.
WIEDERAUFNAHME_SEKUNDEN = 300.0

# The clock, as an attribute rather than a call, so a test can hand in its
# own time instead of sleeping through five minutes of it. Monotonic: this
# measures elapsed time and nothing else, and a clock the user sets back
# must not stretch a pause into a quarter of an hour.
uhr = time.monotonic


@dataclass
class _Stand:
    """What is known about one key right now."""

    # Emergency folds in a row. A real summary puts it back to zero.
    notfaelle: int = 0
    # No fold request goes to a model before this moment.
    pause_bis: float = 0.0
    # When the one attempt after the block is due. Armed lazily on the first
    # blocked check that happens with no pause running, so the five minutes
    # are counted from when the block actually started holding something up.
    wiederaufnahme_bis: float = 0.0
    # The one attempt is earned and not spent yet. It is spent by a fold
    # request that really goes to a model (``versuch_verbraucht``), never by
    # the check that merely asks whether folding is allowed: a turn that
    # checks and then folds nothing — no middle, or a middle too small to be
    # worth replacing — never found out whether the model can summarize
    # again, and lifting the block on it would end the block without a single
    # question having been asked.
    #
    # The check deliberately never spends it: the block is about a model
    # that cannot summarize, and only a request can tell us whether that is
    # still true.
    versuch_frei: bool = False
    # Set when the block just engaged, cleared by the answer that shows the
    # notice. The answer it happened in is the one that says so — including
    # the answer where the block engages again after its one attempt.
    hinweis_offen: bool = False


_staende: dict[str, _Stand] = {}


def _stand(schluessel: str) -> _Stand:
    return _staende.setdefault(schluessel, _Stand())


def notfall(schluessel: str, art: str | None, *, jetzt: float | None = None) -> bool:
    """Books one emergency fold: the pause for ``art``, one more in the row.

    ``art`` is the failure class the request came back as. ``None`` stands
    for an emergency that never asked a model — it happened INSIDE a running
    pause, so it learned nothing new about the model and the pause stays
    exactly as long as it already was. Re-arming it would make a pause look
    as if it grew with every fold, which is the one thing the two fixed
    lengths above are there to rule out.

    Returns whether THIS one switched automatic folding off — the signal the
    running answer needs to show the notice once.
    """
    jetzt = uhr() if jetzt is None else jetzt
    stand = _stand(schluessel)
    stand.notfaelle += 1
    if art is not None:
        stand.pause_bis = jetzt + PAUSEN.get(art, PAUSE_LANG)
    # A new block starts its window from scratch: the one attempt is earned
    # by five minutes of being blocked, not by five minutes that passed
    # while something else was going on. An attempt that was standing ready
    # goes with it — this failure is the fresh evidence it was there to
    # gather.
    stand.wiederaufnahme_bis = 0.0
    stand.versuch_frei = False
    greift = stand.notfaelle >= NOTFAELLE_BIS_STOPP
    if stand.notfaelle == NOTFAELLE_BIS_STOPP:
        # The notice belongs to the answer the block ENGAGES in, once per
        # block — not to every emergency fold that happens while it already
        # holds. After the one attempt the row goes back to one, so the next
        # emergency lands on this number again and the notice stands again.
        stand.hinweis_offen = True
    return greift


def erfolg(schluessel: str) -> None:
    """A real summary went through: nothing about the last failure holds any
    more."""
    _staende.pop(schluessel, None)


def freigeben(schluessel: str) -> None:
    """Drops counter and pause for one key.

    The switch a manual compaction reaches for, built here with the rest of
    this state rather than cut in from outside later: after it the very next
    fold asks a model again, whatever stood here a moment ago. Nothing calls
    it for a live chat yet — a restart and a deleted chat are the only ways
    the block lifts early today, and the manual command that will call it is
    its own piece of work.
    """
    _staende.pop(schluessel, None)


def pausiert(schluessel: str, *, jetzt: float | None = None) -> bool:
    """Whether NO fold request may go to a model for this key right now.

    Read by the forced path, which asks no model and folds nothing instead of
    waiting — a forced fold happens because the answer cannot go out
    otherwise.
    """
    stand = _staende.get(schluessel)
    if stand is None:
        return False
    return (uhr() if jetzt is None else jetzt) < stand.pause_bis


def automatik_gesperrt(schluessel: str, *, jetzt: float | None = None) -> bool:
    """Whether automatic folding is off for this key right now.

    True while a pause runs — the automatic path simply does nothing then,
    it is not the path that cannot wait — and true once
    ``NOTFAELLE_BIS_STOPP`` emergency folds have happened in a row, until
    ``WIEDERAUFNAHME_SEKUNDEN`` of that block have passed. Then one attempt
    stands ready and this says so for as long as nobody takes it: asking
    does not take it, only a request that goes out does
    (``versuch_verbraucht``). A second emergency puts the block straight
    back, a success clears it.
    """
    stand = _staende.get(schluessel)
    if stand is None:
        return False
    jetzt = uhr() if jetzt is None else jetzt
    if jetzt < stand.pause_bis:
        # Still inside the pause. Nothing is armed here: the five minutes
        # are counted from the first check the block itself holds up.
        return True
    if stand.notfaelle < NOTFAELLE_BIS_STOPP:
        return False
    if stand.versuch_frei:
        # Earned and still unspent. Answered the same way every time it is
        # asked: a turn that goes on to fold nothing has to find the attempt
        # still standing on the next one.
        return False
    if stand.wiederaufnahme_bis <= 0.0:
        stand.wiederaufnahme_bis = jetzt + WIEDERAUFNAHME_SEKUNDEN
        return True
    if jetzt < stand.wiederaufnahme_bis:
        return True
    stand.versuch_frei = True
    return False


def versuch_verbraucht(schluessel: str) -> None:
    """Spends the one attempt after the block — called where a fold request
    really goes to a model, on the chat path and on the job path alike.

    Nothing to do where no attempt stands ready: a request inside a running
    block is the forced path's, which never asks whether folding is allowed,
    and it must not shorten a block it was never subject to.

    Spending it drops the row to one, exactly as the check used to do: the
    request now on its way decides what happens next. Comes back an
    emergency, ``notfall`` lifts the row to ``NOTFAELLE_BIS_STOPP`` again and
    the block is back with its notice; comes back a summary, ``erfolg``
    clears everything.
    """
    stand = _staende.get(schluessel)
    if stand is None or not stand.versuch_frei:
        return
    stand.versuch_frei = False
    stand.wiederaufnahme_bis = 0.0
    stand.notfaelle = NOTFAELLE_BIS_STOPP - 1


def hinweis_faellig(schluessel: str) -> bool:
    """Whether the answer running right now carries the "compaction failed"
    notice — asked once, and answered yes only for the answer the block
    engaged in."""
    stand = _staende.get(schluessel)
    if stand is None or not stand.hinweis_offen:
        return False
    stand.hinweis_offen = False
    return True
