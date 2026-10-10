"""Compacting a long-running job's own history in place — an
addition beside the context-full handoff (``app/zwischenstand.py``), not a
replacement for it: that one is the crash-recovery restart, and it stays
exactly as it is — nothing here touches a cronjob. This lets a run that is
merely getting long keep working in the SAME pass instead.

The threshold sits well below the handoff's own 90%: early enough that
there is still plenty of room for the summarizing request itself, and for
the round that triggered the check to actually run again afterward.

The first few messages and the most recent stretch stay word for word —
the opening (what the job was actually asked to do) and the model's own
immediate working memory are exactly what a summary would blur. Only the
middle, everything already settled, gets folded into one.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass

from app import (
    antwortgrenze,
    denkablehnung,
    denkschalter,
    faltbitte,
    faltpause,
    faltversuche,
    kontextdruck,
)
from app.providers import ChatNachricht
from app.tokenmass import ZEICHEN_JE_TOKEN_ROH

log = logging.getLogger(__name__)

# No threshold of its own any more. Where a run compacts is one number for
# the whole house, and it lives in the settings cascade
# (``app/verdichtungswahl.py``) so it can be set per model and per chat.
# Two constants for one decision is how a chat and a job end up compacting
# at different moments for no reason anyone chose.

ERSTE_FEST = 3

# How much of the recent conversation stays word for word, measured in
# TOKENS rather than in messages. Twenty messages can be two hundred tokens
# or two hundred thousand — the count says nothing about how much room the
# tail actually takes, which is the only thing that matters here.
LETZTE_TOKENS = 20_000

# Tokens are what the budget is in; characters are what THIS module counts,
# and the ratio between them is the rough one (app/tokenmass.py).
#
# Deliberately not measured, and that is a known gap: for a Cyrillic history
# the flat four makes the verbatim tail about twice as long as it is meant
# to be. Closing it means weighing the whole fold in tokens — a rework of
# the chat compaction that reaches 66 tests, left for a change of its own.
LETZTE_ZEICHEN = LETZTE_TOKENS * ZEICHEN_JE_TOKEN_ROH


def schwanz_budget(context_tokens: int | None, schwelle_prozent: float) -> int:
    """How many characters the verbatim tail may hold for THIS model.

    ``LETZTE_ZEICHEN`` is a ceiling, not a rule: it is the right tail for a
    model with a hundred thousand tokens of room and far too much for one
    with eight thousand. Measured on a 16k-context model with the shipped
    80% threshold: the threshold is reached at some 52,000 characters of
    history, the fixed budget of 80,000 covered all of it, the boundary came
    back 0, and the middle was empty on every single turn — the setting
    promised compaction and the chat ran straight into the context-full
    handoff instead.

    So the tail is capped at HALF of what the history weighs when the
    threshold fires: at that moment at least half of the history is middle,
    and there is something to fold whatever the model's size and whatever
    the threshold. For a large model the ceiling wins and nothing changes.

    A model whose context size nobody confirmed keeps the ceiling; the
    caller has already refused to compact against a guessed size.
    """
    if not context_tokens or context_tokens <= 0 or schwelle_prozent <= 0:
        return LETZTE_ZEICHEN
    bei_schwelle = context_tokens * ZEICHEN_JE_TOKEN_ROH * schwelle_prozent / 100
    return max(1, min(LETZTE_ZEICHEN, int(bei_schwelle // 2)))

# What a summary announces itself as, wherever one is written. One string,
# because a chat and a job putting the same thing differently is two ways of
# saying one thing.
VORSPANN = "[Earlier steps of this conversation, summarized to save space]"

ANFRAGE_TEXT = """\
Summarize the conversation so far into a short status the run can keep \
working from. This is NOT the end of the task — you are not finished, you \
are compacting the history so it keeps fitting. Write:

## Done
- One bullet per step you actually finished so far. Be specific — this \
replaces the messages it was written from.

## Working notes
Anything not finished yet that matters for what comes next — a half-read \
file, a plan, numbers you will need again.

Nothing else. No preamble, no sign-off.
"""


def _nicht_hinter_werkzeugantwort(nachrichten: list[ChatNachricht], ab: int, richtung: int) -> int:
    """Moves ``ab`` by ``richtung`` (+1 or -1) until it does not land on a
    'tool' message — a tool result with no assistant call in the same kept
    stretch is invalid history for most providers. Always grows the pinned
    side it belongs to, never the middle that gets summarized away."""
    while 0 <= ab < len(nachrichten) and nachrichten[ab].role == "tool":
        ab += richtung
    return ab


def nachrichtengewicht(nachricht: ChatNachricht) -> int:
    """What one message weighs in the character currency of this module.

    Its text and its pictures — the picture priced by the one estimate
    everything else uses (``app/kontextdruck.py``, ``bild_zeichen``). Read by
    its text alone, the boundary of the verbatim tail was drawn as if a round
    that read five pictures had cost nothing.
    """
    return len(nachricht.content or "") + kontextdruck.bild_zeichen(
        len(nachricht.alle_bild_urls())
    )


def schwanz_anfang(inhalte: list[str], budget: int = LETZTE_ZEICHEN) -> int:
    """Where the verbatim tail begins — walked backwards until the budget is
    used up. ``budget`` is what :func:`schwanz_budget` answers for the model
    in hand; the ceiling stands in where nobody asked.

    Texts and not messages, so a chat's rows and a job's message list can ask
    the same question of the same function. One boundary written twice is a
    boundary that drifts.

    The message that busts the budget is NOT kept: a single huge tool result
    would otherwise pin itself and everything after it, and the tail would
    be one message wide exactly when the history is at its largest.

    **Except the newest one.** Busting the budget all by itself, that rule
    returned the length of the list — an EMPTY tail, with the middle running
    all the way to the final message. Measured: a user attaches an 80 KB
    file, and the question they just typed is summarized away before it is
    ever answered. Attaching a large file has to stay possible, so the tail
    keeps the newest message however big it is.
    """
    return _schwanz_ab_gewichten([len(t or "") for t in inhalte], budget)


def _schwanz_ab_gewichten(gewichte: list[int], budget: int) -> int:
    """The same walk, with what each message WEIGHS in hand rather than its
    text — so a picture can weigh what it costs without a copy of anything."""
    if not gewichte:
        return 0
    zeichen = 0
    for stelle in range(len(gewichte) - 1, -1, -1):
        zeichen += gewichte[stelle]
        if zeichen > budget:
            return min(stelle + 1, len(gewichte) - 1)
    return 0


def _schwanz_anfang(nachrichten: list[ChatNachricht], budget: int = LETZTE_ZEICHEN) -> int:
    """The same boundary, asked with messages in hand — pictures included
    (:func:`nachrichtengewicht`)."""
    return _schwanz_ab_gewichten([nachrichtengewicht(n) for n in nachrichten], budget)


def geschuetztes_ende(nachrichten: list[ChatNachricht], budget: int = LETZTE_ZEICHEN) -> int:
    """The first index of the stretch that keeps its own text, in full.

    :func:`schwanz_anfang` alone is not that index: where it lands inside a
    round's tool results, everything from the assistant call that made them
    down to the boundary would be treated as settled, and a tool result whose
    call is no longer in the kept stretch is invalid history — Anthropic
    answers it with a 400. So the boundary walks back over a trailing run of
    tool results and stops on the assistant turn that owns them, which joins
    the protected side.

    Asked by the fold for where its middle ends and by
    ``app/werkzeugkuerzung.py`` for what it may not touch. One boundary,
    because two of them drift: a prune that reached one message further than
    the fold protects would blank a result the round that just ran produced.
    """
    return _nicht_hinter_werkzeugantwort(nachrichten, _schwanz_anfang(nachrichten, budget), -1)


def noetig(nachrichten: list[ChatNachricht], budget: int = LETZTE_ZEICHEN) -> bool:
    """Whether there is a genuine middle to compact at all — a history whose
    tail budget already covers everything past the pinned opening has
    nothing in between to summarize."""
    return _schwanz_anfang(nachrichten, budget) > ERSTE_FEST


@dataclass(frozen=True)
class Ergebnis:
    """What one call actually did.

    ``angewendet`` is the plain "did it change anything" a caller usually
    wants. ``ohne_ersparnis`` is only set when a real request went out and
    came back with a real answer that still was not shorter than what it
    would have replaced — the caller's cue to stop trying for the rest of
    THIS run, not just this once: the degenerate boundary case below already
    resolves itself as the transcript keeps growing, but a summary that does
    not shrink anything keeps landing on the same non-degenerate boundary
    every round, costing a request each time for nothing.

    ``notfall`` says a model WAS asked for the summary and none came back —
    and NOTHING was folded. It never comes with ``angewendet``. A way that
    asked no model at all (a running pause, no room to write a summary in)
    does not set it: nothing failed there. The callers read it for the
    status line, so a run that goes on unfolded can be read back.

    ``keine_mitte`` says there was nothing to fold at this budget: the
    verbatim tail covers the history whole. It is the one ending after which
    a smaller step can still fold something, and the fold loops step down on
    it and on nothing else. After a failure, inside a pause, with no room to
    write a summary in, or after a summary that saved nothing, the next step
    would ask about the same history again and end the same way.
    """

    angewendet: bool
    ohne_ersparnis: bool = False
    notfall: bool = False
    keine_mitte: bool = False


def _bitte_nachrichten(nachrichten: list[ChatNachricht]) -> list[ChatNachricht]:
    """The middle as the compaction request carries it — one message per
    turn, tool calls and their results written into it as text. The one
    rewrite every side request uses (``app/faltversuche.py``,
    ``messages_as_text``)."""
    return faltversuche.messages_as_text(nachrichten)


def _ersetzte_laenge(nachrichten: list[ChatNachricht], anfang: int, ende: int) -> int:
    """What the middle weighs — the one measure this module judges a fold by.

    A message's text, and the arguments of its tool calls: those travel in
    ``werkzeugaufrufe``, never in ``content``, and a write call carrying a
    file weighs its file. Read the way the chat reads a row's calls
    (``app/verlaufsbau.py``, ``werkzeuggewicht``) — the JSON of the
    arguments — so both paths measure a middle by the same rule. Weighed by
    text alone, a middle of such calls looked a few dozen characters wide,
    and a summary that replaced tens of thousands was refused as saving
    nothing.
    """
    return sum(
        len(nachricht.content or "")
        + sum(
            len(json.dumps(aufruf.argumente or {}, ensure_ascii=False, default=str))
            for aufruf in nachricht.werkzeugaufrufe
        )
        for nachricht in nachrichten[anfang:ende]
    )


def _dokumentregel() -> str:
    """The one extra rule a request whose middle carries documents gets.

    The chat's rows path owns the wording (``app/chatverdichtung.py``,
    ``DOKUMENTREGEL``); this path asks for it rather than writing a second
    one. Imported inside the function because that module imports this one.
    """
    from app import chatverdichtung

    return chatverdichtung.DOKUMENTREGEL


def _dokumente_der_mitte(nachrichten: list[ChatNachricht]) -> list:
    """The documents the messages of the middle carry — each named once,
    however many messages carry it, in the order they were attached."""
    gefunden: dict[str, object] = {}
    for nachricht in nachrichten:
        for dokument in nachricht.dokumente:
            gefunden.setdefault(dokument.id, dokument)
    return list(gefunden.values())


def _nicht_falten(schluessel: str, art: str | None) -> Ergebnis:
    """Leaves the history exactly as it is, because no summary came back.

    Nothing takes the middle's place — no text is written in for it — so
    nothing leaves the request that a summary does not speak for. The next
    fold asks again once the pause has run out: that pause IS the retry. A
    summary that failed leaves the messages unchanged.

    The pause is booked only where a model was really asked and failed —
    ``art`` is the failure class the caller read off that request. ``None``
    stands for the ways here that never asked one (a forced fold inside a
    running pause, and no room to write a summary in): nothing was learned
    about the model there, so nothing is booked and ``notfall`` stays unset.
    """
    if art is not None:
        gesperrt = faltpause.notfall(schluessel, art)
        log.warning(
            "Fold for %s failed (%s pause booked), the history stays unfolded%s",
            schluessel,
            art,
            " — automatic folding is now off" if gesperrt else "",
        )
    return Ergebnis(angewendet=False, notfall=art is not None)


async def verdichten(
    zustand,
    anfrage,
    budget: int = LETZTE_ZEICHEN,
    *,
    schluessel: str,
    erzwungen: bool = False,
    einstellungen=None,
    endpoint_id: str | None = None,
) -> Ergebnis:
    """Summarizes everything between the first ``ERSTE_FEST`` messages and
    the verbatim tail of ``anfrage.nachrichten`` into one, in place.
    ``budget`` sizes the tail for the model in hand (:func:`schwanz_budget`).

    ``schluessel`` names the run for the fold pause (app/faltpause.py) — the
    same role a chat id plays on the chat side. ``erzwungen`` says the round
    cannot go out at all unless something shrinks: that path is not held
    back by a block, but inside a running pause it asks no model either.

    A summary that fails — an exception, an empty answer, one cut off at the
    ceiling — is asked for once (app/faltversuche.py) and folds nothing: the
    history stays as it was, the pause is booked, and ``Ergebnis.notfall``
    says so. The exception is caught here all the same — left to run into
    the caller's outer handler, it would end a whole run over one summary.
    Where the round still does not fit, the caller ends it in the
    context-full card.

    ``einstellungen`` and ``endpoint_id`` name the list of thinking stages
    this server has refused (app/denkablehnung.py) — the one list a chat and
    a job both read and write. Callers hand in ``refusal_key``
    (app/discovery.py), the id the model list reads it under. The fold reads
    it before it switches thinking off, and writes to it when the server
    refuses that switch.

    The request's parameters arrive as the run built them, with a thinking
    length already dropped where the knob is locked for this model (the
    chat and the job both filter before any fold sees the request); the
    fold takes them as they are.
    """
    nachrichten = anfrage.nachrichten
    if not noetig(nachrichten, budget):
        return Ergebnis(angewendet=False, keine_mitte=True)

    anfang = _nicht_hinter_werkzeugantwort(nachrichten, ERSTE_FEST, +1)
    ende = max(geschuetztes_ende(nachrichten, budget), anfang)
    if ende <= anfang:
        return Ergebnis(angewendet=False, keine_mitte=True)

    if not erzwungen and faltpause.automatik_gesperrt(schluessel):
        # Automatic folding is off for this run, or a pause is running. The
        # round-end check simply skips; it is not the path that cannot wait.
        return Ergebnis(angewendet=False)
    if erzwungen and faltpause.pausiert(schluessel):
        # Forced, inside a pause: the model failed a moment ago, so no
        # request goes out and nothing is folded. Nothing new was learned
        # about the model, so nothing is booked either.
        return _nicht_falten(schluessel, art=None)

    # The middle with its tool calls capped, and the whole request under one
    # ceiling — both from ``app/faltbitte.py``, so a chat and a run send the
    # summarizer the same shapes and the same sizes. Capped HERE and not
    # further down in `faltversuche.anfordern`, where the chat path also passes: the
    # arithmetic on the next line asks whether the window leaves room to
    # write a summary in, and measured against an uncapped request it
    # answers "no room" for exactly the long histories the ceiling exists
    # for — they would never be folded, without a model ever having been
    # asked.
    # The documents the middle carries. Read before the request is built,
    # because they shape both halves of it: the extra rule below, and the
    # sentence the summary carries afterwards — exactly as on the rows path.
    dokumente = _dokumente_der_mitte(nachrichten[anfang:ende])
    # The summary request offers no tools, so its ceiling is measured
    # without them — as on the rows path (app/chatverdichtung.py): the
    # summary call carries the messages alone. Offered the run's tools, a
    # model could answer the request with a call instead of a summary; the
    # fold reads only text, so that answer counts as empty and the fold is
    # lost.
    zusammenfassen = faltbitte.gedeckelt(
        _bitte_nachrichten(nachrichten[:ende])
        + [
            ChatNachricht(
                role="user",
                content=ANFRAGE_TEXT + (_dokumentregel() if dokumente else ""),
            )
        ],
        zustand.context_tokens,
    )
    fenster = zustand.context_tokens or 0
    if zusammenfassen is None:
        # Once the summary's own room is set aside, the window holds not one
        # character of the history: the request would ask for a summary of
        # nothing. The same way out as no room below — nothing asked, nothing
        # folded, nothing booked — but decided on its own, because a request
        # that small leaves the arithmetic below plenty of room.
        log.warning(
            "Fold for %s: no room for any of the history in a summary request "
            "(window %d), nothing is folded",
            schluessel,
            fenster,
        )
        return _nicht_falten(schluessel, art=None)
    eingabe_tokens = antwortgrenze.eingabe_schaetzen(zusammenfassen)
    # A fold is its own request, same as a chat turn or a job round: the
    # number a refusal named belongs to the request it happened to, not to
    # whatever the summary asks next — so no request's holder is handed in
    # here, and only the model list speaks.
    deckel = antwortgrenze.geltender_deckel(zustand, anfrage.modell)
    anthropic = antwortgrenze.anthropic_draht(zustand)
    if antwortgrenze.reicht_nicht(
        None, deckel, fenster, eingabe_tokens, anthropic=anthropic
    ):
        # There is no room left to write a summary IN. Asking anyway would
        # send a request whose ceiling is the bare edge, and the model would
        # answer it with a token or two — read here as "cut off at the
        # ceiling", which is a fold that did not happen and a round that
        # still does not fit. This is the very moment the forced path is
        # called for: the round came back too long, so the input already
        # fills the window. Nothing is asked and nothing is folded, and
        # where the round cannot go out, the caller ends it in the card. No
        # floor, no second number: the question is whether the arithmetic
        # leaves anything, and it does not.
        #
        # An unknown window lands here too. It used to be the quietest case
        # of all — no window meant a ceiling of the bare edge and a summary
        # nobody could write, with nothing saying so.
        log.warning(
            "Fold for %s: no room to write a summary in (window %d, input %d), "
            "nothing is folded",
            schluessel,
            fenster,
            eingabe_tokens,
        )
        # Nothing was learned about the model — it was never asked — so
        # nothing is booked, exactly as inside a running pause
        # (app/faltpause.py).
        return _nicht_falten(schluessel, art=None)

    # Thinking off wherever this model can be asked to (app/denkschalter.py),
    # whatever the run itself asked for: the summary is a mechanical request
    # whose reasoning nobody reads. The run's thinking length stays with the
    # run — sent beside the switch, it would contradict it. A switch this
    # server has already refused is not sent again.
    merkt = einstellungen is not None and bool(endpoint_id)
    def switch_off() -> tuple[dict, dict]:
        """Thinking off for the summary request, without a switch this
        server has refused (read again for the one repeat below)."""
        return denkschalter.ausschalten(
            zustand,
            # A dictionary of its own: where no switch goes out, ausschalten
            # hands its input back, and the fold's parameters must never be a
            # second name for the run's — a later edit to either would reach
            # the other.
            dict(anfrage.parameter or {}),
            modell=anfrage.modell,
            abgelehnt=denkablehnung.gemerkt(einstellungen, endpoint_id) if merkt else (),
        )

    ohne_denken, parameter = switch_off()
    zwischenanfrage = dataclasses.replace(
        anfrage,
        nachrichten=zusammenfassen,
        # No tools — taken off where every fold request goes out
        # (app/faltversuche.py `without_tools`); the ceiling above is
        # already measured without them.
        # The same rule an answer follows (app/antwortgrenze.py), asked for
        # THIS request: never the run's own ceiling, which is the user's
        # choice for ANSWERS — a summary cut off by it would be stored as if
        # it were whole, and whatever it did not get to say goes with the rows
        # it replaced. On the OpenAI wire that means no number at all: the
        # compaction call goes out with NO max_tokens.
        max_tokens=antwortgrenze.aufloesen(
            None, deckel, fenster, eingabe_tokens, anthropic=anthropic
        ),
        parameter=parameter,
        zusatz=ohne_denken,
    )
    # The fold request is going out now. Where a block had one attempt
    # standing ready, this is what spends it — not the check above, which
    # cannot know whether anything is ever asked (app/faltpause.py).
    faltpause.versuch_verbraucht(schluessel)
    try:
        # One request under two clocks; the pause below is booked once from
        # what it came back with.
        text = await faltversuche.anfordern(zustand, zwischenanfrage)
    except Exception as fehler:  # noqa: BLE001 - a failed fold must not end the run
        route = denkschalter.route_for(zustand, modell=anfrage.modell)
        if not (
            merkt
            and denkablehnung.lernen(
                einstellungen, endpoint_id, fehler, ohne_denken, "off", route=route
            )
        ):
            # Caught here rather than left to the caller: at the round's end
            # this used to run straight into the run's outer handlers and
            # stop it, over a summary. Nothing is folded instead, and the
            # round goes on.
            log.warning("Fold for %s failed", schluessel, exc_info=True)
            return _nicht_falten(schluessel, art=faltpause.LANG)
        # The server refused the switch itself, and that refusal is now
        # written down: the same fold goes out once more at once, without
        # it, the way a side request is repeated without a refused
        # parameter. Any other failure gets no second request.
        ohne_denken, parameter = switch_off()
        zwischenanfrage = dataclasses.replace(
            zwischenanfrage, parameter=parameter, zusatz=ohne_denken
        )
        try:
            text = await faltversuche.anfordern(zustand, zwischenanfrage)
        except Exception:  # noqa: BLE001 - see above
            log.warning("Fold for %s failed again without the thinking switch", schluessel,
                        exc_info=True)
            return _nicht_falten(schluessel, art=faltpause.LANG)
    if text is None:
        # Cut off at the ceiling: no usable summary. Booked as a failure
        # rather than as "gained nothing" — a ceiling that is too tight will
        # be too tight for the next request as well.
        log.warning("Compaction for %s cut off at the answer ceiling", schluessel)
        return _nicht_falten(schluessel, art=faltpause.KURZ)
    if not text:
        log.warning("Compaction for %s answered empty", schluessel)
        return _nicht_falten(schluessel, art=faltpause.KURZ)

    zusammenfassung = ChatNachricht(
        role="user",
        # Text only, no ``dokumente``: the sentence below is what speaks for
        # the documents, exactly as on a summary row of the rows path. A
        # later fold that takes this summary into ITS middle carries that
        # sentence on word for word; carried in the field as well, the same
        # documents were named a second time in that fold's own sentence.
        content=f"{VORSPANN}\n\n{text}",
        # Marked as a summary by its kind, the way a summary row is.
        compacted_summary=True,
    )
    # A chat folding its request in memory displaces the documents its
    # messages carry, and the summary says so with the very note the fold of
    # a chat's rows nails to its summary — one sentence, one function. The
    # sentences earlier summaries in this middle carry go first, word for
    # word: a summary row from the database carries no ``dokumente``, only
    # its sentence, and this summary now speaks for it. Only summaries are
    # read — the messages marked as one (``compacted_summary``), as the rows
    # path reads only its summary rows, and never by the preamble at the
    # start of the text, which a clock sentence in front of it hides — so a
    # tool result or a user message quoting that sentence is never taken
    # for one. A document named both by an earlier summary and in this
    # middle is named twice, as on the rows path. A job's history holds no document and
    # no such sentence, so nothing is added there. Imported here and not at
    # the top: that module imports this one, and its definitions read this
    # module's names while it loads.
    from app import chatverdichtung

    zusammenfassung.content = chatverdichtung.append_document_notes(
        zusammenfassung.content,
        chatverdichtung.document_notes_in(
            nachricht.content
            for nachricht in nachrichten[anfang:ende]
            if nachricht.compacted_summary
        ),
        dokumente,
    )

    # Compared against the message that would actually replace the middle,
    # not the raw model answer — the fixed preamble above is real length
    # too, and without it here a chain of ever-thinner summaries can keep
    # "saving" inside that preamble's own width while the history quietly
    # grows.
    if len(zusammenfassung.content) >= _ersetzte_laenge(nachrichten, anfang, ende):
        # The fold is refused, but the MODEL answered — and the run of
        # emergency folds is about a model that cannot write a summary.
        # Left standing, one failure days apart from another would add up
        # to "two in a row" and switch automatic folding off.
        faltpause.erfolg(schluessel)
        return Ergebnis(angewendet=False, ohne_ersparnis=True)
    anfrage.nachrichten[:] = nachrichten[:anfang] + [zusammenfassung] + nachrichten[ende:]
    # A real summary went in: whatever an earlier failure left standing —
    # the pause, the run of emergency folds — describes a model that is
    # answering again.
    faltpause.erfolg(schluessel)
    return Ergebnis(angewendet=True)
