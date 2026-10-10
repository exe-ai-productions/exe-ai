"""Folding a chat's settled middle away, before its next request is built.

``app/verdichtung.py`` does the same for a job, and the two differ in one
thing that decides everything else: a job holds its message list in memory
for the whole task, so it can rewrite that list and be done. A chat rebuilds
its list from the database on every single request — a fold that is not
written down there is undone by the next thing the user types. That is why
chats had no compaction at all while jobs have had one for a long time.

So this works on ROWS, not on the built prompt. The middle is chosen among
the chat's own messages, summarized, and the fold is recorded
(``messages.verdichten``): the folded rows stay where they are and stay
readable, and stop being sent because a summary now speaks for them. The
reader keeps every line, the model gets the summary.

That is also the shape Anthropic's own server-side compaction uses — a
compaction block sits in the message list and everything before it is
ignored. Every earlier message stays scrollable after a compaction.

Run BEFORE the request is built, once per answer. A single answer that runs
its context full WITHIN itself, over many tool rounds, is not this module's
case and never could be: those rounds live in memory and are not rows, so
there is nothing here to write a fold of them onto. They are handled where
they happen, in the round loop of ``app/api/v1/generierung.py`` — old tool
results are cleared from the request without a model
(``app/werkzeugkuerzung.py``), and where that is not enough the list in
memory is folded there, exactly the way a job folds its own
(``app/verdichtung.py``). There is no 90% net in the chat: the net is that
check plus the provider's own "too long" (``app/kontextvoll.py``), which
every round answers with a fold or a lower ceiling. The emergency handoff
(``app/zwischenstand.py``) belongs to jobs alone and no chat path calls it.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from collections.abc import Iterable

from app import (
    antwortgrenze,
    denkablehnung,
    denkschalter,
    dokumentablage,
    dokumentbudget,
    dokumentcache,
    faltbitte,
    faltpause,
    faltversuche,
    kontextdruck,
    verdichtung,
    verdichtungswahl,
)
from app.discovery import refusal_key
from app.events import Ereignisse, bus
from app.verlaufsbau import _als_modellnachricht, werkzeuge_fuer_die_faltung, werkzeuggewicht, zeilentext
from app.tools.hintergrund import laeufe
from app.providers import ChatNachricht, Generierungsanfrage

log = logging.getLogger(__name__)

# Chats whose last fold was asked for, answered, and came back no shorter
# than the middle it was meant to replace — together with the attempt that
# went nowhere.
#
# The job path has had this brake all along: `verdichtung.Ergebnis` carries
# `ohne_ersparnis` for exactly this, and the caller in
# ``app/api/v1/auftraege.py`` keeps it in a local for the rest of the run.
# A chat has no run to keep anything in. It is rebuilt from the database on
# every single request — the whole reason this module exists beside that one
# — so without a memory here the identical attempt goes out again on the
# very next turn, and the user waits behind it every time.
#
# What is remembered is WHICH attempt gained nothing, never that compaction
# is off. A chat grows: rows leave the verbatim tail and join the middle,
# and the moment the middle is a different middle the brake is gone by
# itself. That is the shape ``app/modellvorlauf.py`` uses for "already
# tried", where the memory is the due moment rather than a flag, and for the
# same reason — a brake that cannot notice the situation changing is a brake
# that never lets go.
#
# In memory, like that one and like the wake brake in
# ``app/hintergrundwecken.py``: it is a fact about right now, and a restart
# that changed the situation must not inherit an "already tried" from the
# one before it. One small entry per chat, written only on a turn where a
# real request came back and saved nothing, and dropped again as soon as a
# fold goes through.
_ohne_ersparnis: dict[str, tuple[str, int, int]] = {}


def _vergessen(chat_id: str) -> None:
    """Drops a deleted chat's brake and its fold pause along with its runs.

    Chat ids are not reused, so this leaks nothing dangerous — it keeps the
    dictionaries from growing for the life of the process over chats that no
    longer exist, the same hook the wake brake hangs on.
    """
    _ohne_ersparnis.pop(chat_id, None)
    faltpause.freigeben(chat_id)


laeufe.beim_vergessen(_vergessen)


# One more rule for the summarizing model, and only in a chat it applies to
# — a middle that carries documents.
#
# Their bodies do not travel into the compaction request (see
# ``vielleicht_verdichten``), so what the conversation ESTABLISHED from a
# document is the only thing about it a summary can carry across the fold.
# Asked for by name, because a summary of forty turns about a contract
# otherwise reads "the user asked about the contract" and keeps nothing.
DOKUMENTREGEL = """
The documents in this history are named by filename only; their text is not \
included here. Under the two headings above, record for each one what it \
was and what was established from it — after this compaction that is all \
that is left of it.
"""


def _mitte_suchen(
    zeilen: list,
    gewichte: list[str] | None = None,
    budget: int = verdichtung.LETZTE_ZEICHEN,
) -> list:
    """The rows a summary may replace — never the opening, never the tail,
    and never a stretch that is already nothing but summary.

    The opening says what the conversation was about and is three messages
    wide; the tail is the working memory and is measured as a token budget
    rather than a message count, because twenty messages can be two hundred
    tokens or two hundred thousand.

    ``gewichte`` is what each row weighs in the prompt — one entry per row,
    in the same order, built by the caller through the request builder
    itself. Deliberately NOT ``messages.content``: a document's text is not
    in that column, the row only POINTS at the document, and the text is
    prepended when the request is built. Measured on a chat of forty short
    turns each carrying a 24,000-character document, ``content`` said 700
    characters against a real prompt of 962,970 — the 80,000-character
    budget was never busted, the boundary came back 0, and the middle was
    empty every single turn. The chat that needed compaction most was the
    one chat that could never have it.

    Left out, the weights fall back to the ``content`` column — which is
    the right answer for a row that carries nothing but text and the wrong
    one for every other row. It is there for the boundary tests, which hand
    in stand-in rows made of text and nothing else, and it is safe here
    because this is private and has exactly one caller in the program: the
    function below, which has to build the weights anyway to measure the
    middle it picks — through ``zeilentext``, never through the column.
    """
    if gewichte is None:
        gewichte = [z.content or "" for z in zeilen]
    if len(zeilen) <= verdichtung.ERSTE_FEST:
        return []
    # The job's own boundary, asked with this chat's rows. It was a second
    # copy of the same walk, and a boundary written twice is a boundary that
    # drifts — which the tail-budget change would have caused here the
    # moment one of the two learned to keep the newest message.
    schwanz = verdichtung.schwanz_anfang(gewichte, budget)

    # Rows past the last real answer are UNREAD — no answer has responded to
    # them yet — and a run woken to read a report must not be handed a
    # summary of it. But only as far as the budget: protecting them outright
    # took the cap off entirely. Reports stack up without a wake of their
    # own — `_nachzuholen` holds CHAT IDS, so twenty commands finishing
    # during one answer make twenty rows and a single wake, and the wake
    # brake stops waking long before `hintergrundmeldung` stops writing.
    # Measured with two hundred stacked reports: 428,387 characters kept
    # verbatim where the budget says 102,955, and compaction could no longer
    # bring the context down at all.
    #
    # The one boundary above already does exactly that, and for every row
    # alike: the unread stretch is protected whole while it fits and cut
    # from the front when it does not, so the newest reports — the ones a
    # wake is actually about — survive either way. Nine lines used to sit
    # here that looked for the last real answer and walked `schwanz_anfang`
    # a SECOND time over `zeilen[ungelesen_ab:]`, folding the result in with
    # a `min`. They could not move the boundary: both walks add the same
    # texts from the same end against the same budget, so the same row `s`
    # busts it, and the slice merely renames it — `u + min(s - u + 1,
    # n - u - 1)` is `min(s + 1, n - 1)`, which is what the global walk had
    # already returned. Their own guard, `ungelesen_ab < schwanz`, ruled out
    # the only shape in which `s` could have fallen outside the slice at
    # all. Measured before they went: 45,110 histories, the guard entered
    # 10,798 times, not one changed boundary.
    #
    # Removed rather than kept as documentation. They read as a protection
    # while giving none, and the next person to raise `LETZTE_TOKENS` would
    # have trusted them to catch this case.
    mitte = zeilen[verdichtung.ERSTE_FEST : schwanz]

    # And a stretch that is nothing but summary is not a middle. Reproduced
    # with three rows, one 4 KB summary and a 200 KB message: the tail keeps
    # the newest row however big it is, so the boundary lands directly
    # behind the summary and the middle is that summary alone. Summarizing
    # it again shortens it a little every turn — thinner and vaguer each
    # time, and passing the saving check each time BECAUSE it got thinner —
    # while the message that is actually filling the context is pinned and
    # can never be reached. There is no unfolded history in such a stretch,
    # so there is nothing there to win.
    #
    # A middle holding a summary AND real rows is a different matter and
    # stays foldable: the new summary takes the old one in with it, which is
    # what `messages.verdichten` is built to allow.
    if all((z.art or "nachricht") == "verdichtung" for z in mitte):
        return []
    return mitte


def _dokumente_der_mitte(mitte: list, repositories) -> list:
    """The documents hanging on the rows about to be folded — each named
    once, however many rows carry it, in the order they were attached."""
    gefunden: dict[str, object] = {}
    for zeile in mitte:
        for kennung in zeile.dokument_ids():
            if kennung in gefunden:
                continue
            dokument = dokumentcache.holen(repositories, kennung)
            if dokument and dokument.extracted_text:
                gefunden[kennung] = dokument
    return list(gefunden.values())


def _dokumentnachweis(dokumente: list) -> str:
    """The sentence the summary carries about the documents it displaces.

    A summary speaks FOR the rows it folded, and for a row of words that is
    a fair trade. For a row carrying a document it is not: the text was
    never in the row and is not in the summary either, so folding that row
    takes it out of the prompt for good.

    Written by us and not left to the model, because it is the one part
    that must not depend on a summary coming out well: the model is asked
    to record what was ESTABLISHED from a document (``DOKUMENTREGEL``), and
    this line records that the document itself has left — which is exactly
    the thing an answer built on a half-remembered contract would never
    say. Same shape as the truncation notice the request builder writes
    when a document is too big to travel whole: say it out loud, with
    numbers, in both directions.
    """
    # One sentence per document, joined by a space. Joined by a comma, the
    # note a document carries — it ends in a full stop and begins with a
    # space (``app/dokumentablage.py``) — ran into the next name as
    # "…lines., "b.pdf" (200 characters) The file itself is…". Same words,
    # different seams.
    teile = " ".join(
        f'"{dokument.filename}" ({len(dokument.extracted_text or "")} characters).'
        + dokumentablage.nachlesehinweis(dokument.pfad, dokument.pages)
        for dokument in dokumente
    ).strip()
    return (
        f"{_NOTE_START} {teile} "
        f"Their text travelled with every request until this compaction and "
        f"does not any more. They are still attached to this conversation "
        f"and still readable in the chat — say so, and ask for what you "
        f"need, {_NOTE_END}"
    )


# How the sentence above begins and ends, fixed, so a later fold can find
# it again word for word inside a summary it takes into its middle. The
# summaries already stored carry exactly this wording: change it, and a fold
# over one of them no longer finds its sentence.
_NOTE_START = "[Documents attached in the stretch summarized above:"
_NOTE_END = "rather than answering as if you still had their wording.]"
# No second start inside one match: a model that begins the sentence in its
# own words and never finishes it must not have its prose taken for ours.
_NOTE = re.compile(
    re.escape(_NOTE_START)
    + r"(?:(?!" + re.escape(_NOTE_START) + r").)*?"
    + re.escape(_NOTE_END),
    re.DOTALL,
)


def _earlier_document_notes(mitte: list) -> list[str]:
    """The document sentences earlier folds nailed to the summaries in this
    middle — each once, word for word, in the order they stand.

    A summary row carries no documents of its own: its ``dokumente`` field
    would bring the folded text straight back into the request
    (``app/verlaufsbau.py``). So ``_dokumente_der_mitte`` finds nothing on
    it, and a second fold over it used to drop the first one's sentence
    without a word. The sentence is what the row does carry, and the new
    summary speaks for the old one — so it carries the sentence on.
    """
    return document_notes_in(
        zeile.content
        for zeile in mitte
        if (zeile.art or "nachricht") == "verdichtung"
    )


def document_notes_in(texte: Iterable[str | None]) -> list[str]:
    """Every document sentence an earlier fold wrote into these texts — each
    once, word for word, in the order they stand.

    The one reader of that sentence for both folds: the rows path above hands
    in its summary rows, the fold of a request in memory (app/verdichtung.py)
    the summaries of its middle, which arrive there as plain messages with
    no ``art`` and no ``dokumente`` of their own.
    """
    notes: list[str] = []
    for text in texte:
        for treffer in _NOTE.finditer(text or ""):
            if treffer.group(0) not in notes:
                notes.append(treffer.group(0))
    return notes


def append_document_notes(content: str, earlier: list[str], documents: list) -> str:
    """``content`` with the document sentences nailed to it: the ones earlier
    folds wrote (``earlier``, word for word) first, then the one for the
    ``documents`` this fold displaces. The one place every fold — of rows,
    during a run, in memory — adds them.
    """
    notes = list(earlier)
    if documents:
        notes.append(_dokumentnachweis(documents))
    for note in notes:
        # A model that copied an earlier sentence into its summary has
        # already carried it; a second copy says nothing more.
        if note not in content:
            content = f"{content}\n\n{note}"
    return content


def _mitte_wirklich(
    mitte: list, dokumente: list, repositories, dokumentplan: dict | None
) -> int:
    """What the middle really puts into a prompt — the one measure a fold of
    this chat is judged by.

    Judged against this and not against the weights the boundary was drawn
    with. Two readings, both from what a request really carries:

    * A row's tool calls travel back as calls and capped results
      (app/verlaufsbau.py, ``werkzeuggewicht``), on top of its text.
    * A document counts as what the plan for this request sends of it
      (app/dokumentbudget.py): the whole text where it fits and stays under
      the ceiling of half that window, nothing where it does not or
      where the plan says nothing about it. Both wrong readings
      have been seen. Judged against the whole body, a 3 KB summary "saved" a
      factor of two hundred on a middle whose real contribution it barely
      undercut, and the chat folded again on every turn while the user waited
      behind each request. Counted as nothing, a middle of five short rows
      and one big document weighed two thousand characters, a
      three-thousand-character summary "saved nothing", and the chat could
      never fold again while every turn kept paying for the document.
    """
    return sum(
        len(zeilentext(z, repositories, volltext_mitschicken=False))
        + werkzeuggewicht(z)
        for z in mitte
    ) + sum(
        dokumentbudget.beitrag_zeichen(d, dokumentplan)
        for d in dokumente
    )


def _bittetext(zeile, repositories) -> str:
    """One row as the compaction request carries it: what it said, and what
    its tools were asked and answered.

    The document bodies stay out — named and measured instead, see the
    request below and ``app/verlaufsbau.py`` — while the tool log comes in,
    with the far wider ceilings a compaction request may spend on it
    (``app/faltbitte.py``). Both are the same decision seen from two sides:
    the summarizer is shown the CONVERSATION, and a tool result is part of
    that conversation while an attached file is not.
    """
    return werkzeuge_fuer_die_faltung(
        zeile, zeilentext(zeile, repositories, volltext_mitschicken=False)
    )


async def vielleicht_verdichten(
    *,
    zustand,
    repositories,
    chat,
    endpoint_id: str,
    modellname: str,
    vorheriger_stand: int | None,
    neu_tokens: int = 0,
    dokumentplan: dict | None = None,
    eingestellte_grenze: int | None = None,
) -> str | None:
    """Folds the chat's middle if it is ABOUT TO grow past the threshold.

    ``vorheriger_stand`` is the last confirmed token total; ``neu_tokens``
    is what the caller already knows arrived since then — the message just
    saved and its attachments — because that is not in ``vorheriger_stand``
    yet and would otherwise go out uncounted on the very round it pushes the
    chat over the threshold (``app/kontextdruck.py``).

    ``dokumentplan`` is what the request being built will carry of each
    document (app/dokumentbudget.py); the rows are weighed with it, so the
    fold's saving is judged against the prompt that really goes out.

    Returns the id of the summary that was written, or ``None`` where
    nothing was done — no reading, no ceiling, below the threshold, no
    middle, a middle an earlier turn already failed to shrink, automatic
    folding switched off for this chat, or an answer that would not have
    been shorter than what it replaces.

    A summary the model could not write is one of them too: it is asked for
    once (app/faltversuche.py), nothing is folded, and the fold pause books
    the failure, so the next turn asks again once it has run out
    (app/faltpause.py). Nothing is lost either way — the rows stay where
    they are, folded or not, and stay readable.

    Rows are read through ``app.verlaufsbau.zeilentext`` — the one reading
    of what a row says to a model, shared with the request builder. This
    whole function used to read ``messages.content`` instead, which is not
    what a row says.
    """
    prozent = kontextdruck.prozent(vorheriger_stand, neu_tokens, zustand.context_tokens)
    if prozent is None:
        # A model whose context size nobody confirmed — a missing
        # `vorheriger_stand` no longer lands here, `kontextdruck.prozent`
        # counts it as zero instead (see its own docstring). A threshold
        # measured against a size that was guessed would fold a
        # conversation for no reason — the same rule the rest of the context
        # display follows.
        return None
    schwelle = verdichtungswahl.schwelle(
        repositories, modell=endpoint_id, chat=chat.id
    )
    # Measured against the window less a ceiling the user set: that many
    # tokens of it are reserved for the answer and are not there for the
    # history (app/kontextdruck.py).
    if not kontextdruck.ueber_der_schwelle(
        vorheriger_stand,
        neu_tokens,
        zustand.context_tokens,
        schwelle,
        eingestellte_grenze,
    ):
        return None
    # Asked here rather than at the top of the function: the five minutes
    # that earn one attempt back are counted from the first check the block
    # actually held up, and a turn that was never going to fold held nothing
    # up (app/faltpause.py). Asking does not spend that attempt either — a
    # turn that gets past here and then folds nothing leaves it standing for
    # the next one. Covers the pause as well — inside it no fold request goes
    # to a model at all, and this path is the one that can simply wait for
    # the next turn.
    if faltpause.automatik_gesperrt(chat.id):
        return None
    # The tail sized for THIS model: the fixed ceiling alone left a small
    # context with no middle at all, ever (see `verdichtung.schwanz_budget`).
    budget = verdichtung.schwanz_budget(zustand.context_tokens, schwelle)
    kennung, _ = await _falten(
        zustand=zustand,
        repositories=repositories,
        chat=chat,
        endpoint_id=endpoint_id,
        modellname=modellname,
        zeilen=repositories.messages.fuer_das_modell(chat_id=chat.id),
        budget=budget,
        dokumentplan=dokumentplan,
        bremse=True,
        erzwungen=False,
    )
    return kennung


async def erzwungen_verdichten(
    *,
    zustand,
    repositories,
    chat,
    endpoint_id: str,
    modellname: str,
    zeilen: list,
    budget: int,
    dokumentplan: dict | None = None,
) -> tuple[str | None, verdichtung.Ergebnis]:
    """Folds the chat's middle because the provider called the request too
    long — no threshold, no known context size needed, and past the brake.

    The provider's refusal is the reading here: whether the window is known
    or the percentage crossed anything no longer matters once the request
    has come back as not fitting. The brake is skipped for the same reason —
    it remembers that a middle did not shrink enough to be worth a request
    on an ordinary turn, and this turn cannot go out at all unless something
    shrinks.

    ``zeilen`` are the rows the refused request was built from, handed in
    rather than read here: by now the answer's own placeholder is a row of
    the chat too, and read fresh it would be the "newest message" the tail
    keeps instead of the question being answered.

    Inside a fold pause this path does not ask a model at all, and folds
    nothing (app/faltpause.py). "Forced" means "no answer comes out
    otherwise", not "the user wants this" — and the model has just shown it
    cannot write a summary, so waiting out the pause would only cost the
    answer the time and end here anyway.

    Returns the id of the summary written, or ``None`` where nothing was
    folded — no middle left, no saving, or no summary — together with what
    the fold did, in the form a job's fold answers it
    (``verdichtung.Ergebnis``): the loop over the fold steps reads the same
    two things on both ways, whether a step failed and whether a smaller one
    can still fold something.
    """
    return await _falten(
        zustand=zustand,
        repositories=repositories,
        chat=chat,
        endpoint_id=endpoint_id,
        modellname=modellname,
        zeilen=zeilen,
        budget=budget,
        dokumentplan=dokumentplan,
        bremse=False,
        erzwungen=True,
    )


def als_bitte(zeile, repositories) -> ChatNachricht:
    """One stored row as it enters the summarising request.

    The role comes from the ONE rule that knows it
    (``app/verlaufsbau._als_modellnachricht``), never from the stored field:
    a finished run's report is stored as an assistant row so the window files
    it with the answer, but the model never SAID it — the service did. Handed
    to the summarising model as the model's own words, it took the shape for
    its own and wrote reports of its own making. In the conversation it goes
    as the user's side, and it goes the same way into the fold.

    Both halves of that rule come along — the role AND the marker that says
    the service wrote it. A reader downstream (`app/grundprompt`) asks both:
    a row that is `user` without the marker looks like the user's own voice,
    and the environment block would be written into a report.

    Its own name so the way a row enters the fold can be read and checked
    without a whole fold — the rule itself stays where it is
    (`app/db/repositories/messages.ist_dienstbericht`, read by
    `app/verlaufsbau._als_modellnachricht`); this is only the way in.
    """
    rolle, kennzeichen = _als_modellnachricht(zeile)
    return ChatNachricht(
        role=rolle,
        content=_bittetext(zeile, repositories),
        service_report=kennzeichen,
    )


async def _falten(
    *,
    zustand,
    repositories,
    chat,
    endpoint_id: str,
    modellname: str,
    zeilen: list,
    budget: int,
    dokumentplan: dict | None,
    bremse: bool,
    erzwungen: bool,
) -> tuple[str | None, verdichtung.Ergebnis]:
    """The fold itself, once it has been decided that one is wanted.

    ``bremse`` says whether an attempt that already saved nothing for this
    very middle holds this one back. ``erzwungen`` says this fold is the
    only way the answer gets out at all, which is what decides what happens
    inside a fold pause: this path gets there and asks no model, the
    automatic one never gets here.

    The thinking stages this server has refused (app/denkablehnung.py) are
    read and written under ``refusal_key`` — the one list the model list and
    the chat's own turns use: the fold's "off" is not sent where it was
    refused before, and a refusal of it is written down there."""
    # What each row WEIGHS in the prompt this fold is meant to shrink,
    # built by the builder that writes that prompt — not ``messages.content``,
    # see `_mitte_suchen`. Without a plan a document is read as too large for
    # the window and costs nothing here (app/verlaufsbau.py): the same
    # reading a request without one gives it.
    gewichte = [
        zeilentext(z, repositories, dokumentplan=dokumentplan)
        for z in zeilen
    ]
    mitte = _mitte_suchen(zeilen, gewichte, budget)
    if not mitte:
        return None, verdichtung.Ergebnis(angewendet=False, keine_mitte=True)
    gewicht = dict(
        zip((z.id for z in zeilen), (len(g) for g in gewichte), strict=True)
    )

    # What this attempt IS: the model that would be asked, and how much
    # history it would be asked about. The model belongs in it because a
    # different model writes a different summary — switching models is the
    # situation changing, exactly as the chat growing is. Length as well as
    # count, because a row can be deleted and written again — a regenerated
    # answer leaves the count where it was and the history somewhere else.
    mitte_zeichen = sum(gewicht[z.id] for z in mitte)
    versuch = (modellname, len(mitte), mitte_zeichen)

    # A fold pause is running and this fold cannot wait for it: the model
    # failed a moment ago, so no request leaves the house and nothing is
    # folded (see `_nicht_falten`).
    if erzwungen and faltpause.pausiert(chat.id):
        return None, _nicht_falten(chat=chat, mitte=mitte, art=None)

    if bremse and _ohne_ersparnis.get(chat.id) == versuch:
        # Asked once for this exact middle already, and what came back was
        # not shorter than what it would have replaced. Asking again spends
        # the same request on the same answer, and the user waits behind it
        # — the very thing `ohne_ersparnis` stops on the job path.
        return None, verdichtung.Ergebnis(angewendet=False)

    # The documents that leave the prompt with this fold. Read before the
    # request goes out, because they shape both halves of it: the extra rule
    # below, and the sentence the summary carries afterwards.
    dokumente = _dokumente_der_mitte(mitte, repositories)

    # Said out loud before the request goes out: the window shows the
    # placeholder of the answer this fold is holding up, and it should say
    # what for. Over the program's own line (app/ereignisstrom.py), because
    # the answer's stream has not opened yet — this runs before it.
    await bus.veroeffentlichen(Ereignisse.VERDICHTUNG_LAEUFT, chat_id=chat.id)

    # Asked on a request built just for this, so the live conversation is
    # never touched until there is an answer to record — the same care
    # `verdichtung.verdichten` takes for a job.
    # The rows this request carries, built before the request so its own
    # ceiling can be worked out against them.
    #
    # Through `zeilentext`, not `z.content`: that is what puts a sentence
    # where a picture row would otherwise send a message with nothing in it
    # at all — which most OpenAI-compatible servers refuse, turning the whole
    # fold into a caught exception.
    #
    # The same builder that weighed the rows, asked the other way round:
    # weighed with the document bodies in, SENT with them out.
    #
    # Not a contradiction — two different questions. What a row costs is what
    # it costs, and only the full text answers that. What the summarizing
    # model needs is the conversation, and the bodies would drown it: the
    # middle measured above can be 840,000 characters of document, asked of a
    # model whose context is already past the compaction threshold. That
    # request fails, the failure is caught below as "did nothing", and the
    # chat silently never folds — this very defect, rebuilt from the other
    # side. So each document goes in named and measured, and `DOKUMENTREGEL`
    # asks for the one thing about it a summary can actually carry.
    #
    # The tool calls travel with the words, capped by `app/faltbitte.py`.
    # What a tool FOUND is most of what a long stretch of work was about; it
    # was weighed into the saving check all along (`werkzeuggewicht`), and a
    # summary written without it could not carry it — after the fold it was
    # out of every later prompt unless an answer had repeated it by hand.
    #
    # And the finished request gets its ceiling from the same module, before
    # the arithmetic below asks whether there is room to write a summary in:
    # measured against an uncapped request, that question answers "no room"
    # for exactly the long conversations the ceiling is there for.
    zusammenfassen = faltbitte.gedeckelt(
        [
            als_bitte(z, repositories)
            for z in mitte
        ]
        + [
            ChatNachricht(
                role="user",
                content=verdichtung.ANFRAGE_TEXT + (DOKUMENTREGEL if dokumente else ""),
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
            "Chat %s: no room for any of the history in a summary request "
            "(window %d), nothing is folded",
            chat.id,
            fenster,
        )
        return None, _nicht_falten(chat=chat, mitte=mitte, art=None)

    eingabe_tokens = antwortgrenze.eingabe_schaetzen(zusammenfassen)
    # A fold is its own request, same as a chat turn or a job round: the
    # number a refusal named belongs to the request it happened to, not to
    # whatever the summary asks next — so no request's holder is handed in
    # here, and only the model list speaks.
    deckel = antwortgrenze.geltender_deckel(zustand, modellname)
    anthropic = antwortgrenze.anthropic_draht(zustand)
    if antwortgrenze.reicht_nicht(
        None, deckel, fenster, eingabe_tokens, anthropic=anthropic
    ):
        # No room left to write a summary IN. The request would go out
        # carrying the bare edge as its ceiling, the model would answer it
        # with a token or two, and that is read below as "cut off at the
        # ceiling" — a fold that cost a full request and did not happen.
        # Nothing is asked and nothing is folded instead. No floor and no
        # second number: the question is whether the arithmetic leaves
        # anything at all.
        #
        # An unknown window lands here too, where it used to be the quietest
        # case of them all.
        log.warning(
            "Chat %s: no room to write a summary in (window %d, input %d), "
            "nothing is folded",
            chat.id,
            fenster,
            eingabe_tokens,
        )
        return None, _nicht_falten(chat=chat, mitte=mitte, art=None)

    # The refusals are kept under the id the model list reads them under
    # (app/discovery.py `refusal_key`), not under the chat's own spelling of
    # the model, or a refusal learned here would never reach the list.
    refusal_id = refusal_key(zustand, modellname)

    def switch_off() -> dict:
        """Thinking off for the summary request, without a switch this
        server has refused (read again for the one repeat below)."""
        return denkschalter.zusatz(
            False,
            zustand,
            modell=modellname,
            abgelehnt=denkablehnung.gemerkt(repositories.einstellungen, refusal_id),
        )

    anfrage = Generierungsanfrage(
        # The model has to be NAMED. A request built from scratch carries no
        # model, and an OpenAI-compatible server answers that with a 422 —
        # which this function catches and turns into "did nothing", so the
        # chat would simply never fold and nothing would say why. The job
        # path does not hit this because it copies the request it already
        # has; this one is built for the occasion.
        modell=modellname,
        # The same rule an answer follows (app/antwortgrenze.py), asked for
        # THIS request: never the answer's own ceiling, which is the user's
        # choice for ANSWERS — a tight one would cut the summary short, and a
        # cut summary is stored whole while what it left out is gone from the
        # prompt for good. On the OpenAI wire that means no number at all, and
        # the server decides; the summary an MLX server writes without one was
        # measured whole, thinking off, with the model's own default in
        # charge.
        max_tokens=antwortgrenze.aufloesen(
            None, deckel, fenster, eingabe_tokens, anthropic=anthropic
        ),
        # Thinking off wherever this model can be asked to
        # (app/denkschalter.py): a summary is a mechanical request whose
        # reasoning nobody reads, and a model that thinks spends the ceiling
        # on it before the summary is written. Not where this server has
        # refused the switch before.
        zusatz=switch_off(),
        nachrichten=zusammenfassen,
    )
    # The fold request is going out now. Where a block had one attempt
    # standing ready, this is what spends it — not the check in
    # `vielleicht_verdichten`, which cannot know whether a request follows it
    # (app/faltpause.py).
    faltpause.versuch_verbraucht(chat.id)
    try:
        # One request under two clocks; the pause is booked once from what
        # it came back with.
        text = await faltversuche.anfordern(zustand, anfrage)
    except Exception as fehler:  # noqa: BLE001 - a failed fold must not cost the answer
        if not denkablehnung.lernen(
            repositories.einstellungen, refusal_id, fehler, anfrage.zusatz, "off",
            route=denkschalter.route_for(zustand, modell=modellname),
        ):
            # Every other kind of failure, a timeout included: nothing is
            # folded, and the pause brakes the next turn from asking the same
            # broken model again at once.
            log.warning("Chat %s: fold failed", chat.id, exc_info=True)
            return None, _nicht_falten(chat=chat, mitte=mitte, art=faltpause.LANG)
        # The server refused the switch itself, and that refusal is now
        # written down: the same fold goes out once more at once, without
        # it (app/verdichtung.py does the same for a job's fold). Its failure
        # is booked once, as any failed fold is.
        anfrage = dataclasses.replace(anfrage, zusatz=switch_off())
        try:
            text = await faltversuche.anfordern(zustand, anfrage)
        except Exception:  # noqa: BLE001 - see above
            log.warning("Chat %s: fold failed again without the thinking switch", chat.id,
                        exc_info=True)
            return None, _nicht_falten(chat=chat, mitte=mitte, art=faltpause.LANG)
    if text is None:
        # Cut off at the ceiling: no summary, and not a hiccup either. The
        # saving brake is deliberately NOT set here — this is a failure, and
        # the pause is what keeps the next turn from asking again at once.
        log.warning("Chat %s: summary cut off at its ceiling", chat.id)
        return None, _nicht_falten(chat=chat, mitte=mitte, art=faltpause.KURZ)
    if not text:
        log.warning("Chat %s: summary came back empty", chat.id)
        return None, _nicht_falten(chat=chat, mitte=mitte, art=faltpause.KURZ)

    inhalt = f"{verdichtung.VORSPANN}\n\n{text}"
    # Nailed to the summary rather than trusted to it. Whatever the model
    # wrote above, the row that replaces this stretch now states which
    # documents stopped travelling with the conversation — the ones earlier
    # folds already named, passed on word for word, and those of this one.
    inhalt = append_document_notes(inhalt, _earlier_document_notes(mitte), dokumente)
    # Measured against what would actually replace the middle, preamble
    # included: without that, a chain of ever-thinner summaries keeps
    # "saving" inside the preamble's own width while the history grows.
    #
    # Like with like on both sides since the weights above changed. The
    # middle is what the builder makes of those rows; this is what the
    # builder will make of the row replacing them — a summary carries no
    # documents and no pictures, so its content IS its weight, the note
    # included.
    if len(inhalt) >= _mitte_wirklich(mitte, dokumente, repositories, dokumentplan):
        # A real request went out and a real answer came back, and it still
        # would not have shrunk anything — the one signal the brake is for,
        # and the only branch left that sets it. A failed summary is not
        # braked but paused, above; this one is not a failure, so the fold
        # is refused here exactly as it always was.
        _ohne_ersparnis[chat.id] = versuch
        # The MODEL answered, though — and the run of emergency folds is
        # about a model that cannot write a summary. Left standing, one
        # failure days apart from another would add up to "two in a row"
        # and switch automatic folding off.
        faltpause.erfolg(chat.id)
        log.info(
            "Chat %s: compaction saved nothing, not repeated for this middle "
            "part",
            chat.id,
        )
        return None, verdichtung.Ergebnis(angewendet=False, ohne_ersparnis=True)

    zusammenfassung = repositories.messages.verdichten(
        chat_id=chat.id, text=inhalt, ersetzte_ids=[z.id for z in mitte]
    )
    if zusammenfassung is None:
        return None, verdichtung.Ergebnis(angewendet=False)
    # The middle just collapsed into one row, so whatever the brake still
    # holds for this chat describes a stretch that no longer exists. It
    # could never match again — a matching one would have returned above —
    # but a brake nobody ever lifts is how a table becomes a leak.
    _ohne_ersparnis.pop(chat.id, None)
    # A real summary came back and went in: whatever an earlier failure left
    # standing — the pause, the run of emergency folds — describes a model
    # that is answering again.
    faltpause.erfolg(chat.id)
    log.info(
        "Chat %s compacted: %d rows summed up into one",
        chat.id,
        len(mitte),
        extra={"ereignis": "chat_verdichtet", "chat": chat.id, "zeilen": len(mitte)},
    )
    return zusammenfassung.id, verdichtung.Ergebnis(angewendet=True)


def faltung_nachtragen(
    *, chat, repositories, zusammenfassung: str, budget: int, ausser_id: str | None = None
) -> str | None:
    """A fold that happened INSIDE an answer, written down afterwards.

    From round 1 on a chat's answer carries tool rounds that are not rows and
    never will be; where the request still has to shrink, those fold in
    memory (``app/api/v1/generierung.py``, the way a job folds its own list —
    ``app/verdichtung.py``). Without a row that fold lasts for the one
    answer: the next message sends the unfolded stretches again and folds
    them anew — one request for the same result. So the summary the fold
    produced is recorded here, on the way the row path records its own
    (:func:`_falten`, ``messages.verdichten`` with the document note beside
    it): the rows it speaks for gain their pointer, stay readable, and the
    next request starts from the summary.

    The rows the fold covered are the ones between the pinned opening and
    ``ausser_id`` — this answer's own row, which the summary must PRECEDE —
    and the verbatim tail is cut off them the way every fold cuts it, with
    the same :func:`verdichtung.schwanz_anfang`. Only the rows are weighed
    here, not the rounds that are not rows: rows alone weigh less than the
    request they open, so this boundary protects MORE than the fold did and
    FEWER rows are marked. That is the safe side. A row that stays in the
    prompt although the summary also speaks for it says the same thing
    twice; a row behind the seam that the summary never covered would be
    lost.

    Returns the summary row's id, or ``None`` where nothing was written —
    the same handle the row path hands back, so the answer's own row can
    name its fold.
    """
    vor = []
    for zeile in repositories.messages.fuer_das_modell(chat_id=chat.id):
        if ausser_id is not None and zeile.id == ausser_id:
            break
        vor.append(zeile)
    mitte = vor[verdichtung.ERSTE_FEST :]
    if not mitte:
        return None
    # The verbatim tail, cut the way every fold cuts it — but over the ROWS,
    # and that is only half the truth. Two ends need no cut at all: where the
    # rows do not fill the tail (``0``) and where they fill it exactly, the
    # tail of the request lay in its ROUNDS — tools that are not rows — and
    # every row of this stretch was folded; cutting there would throw the
    # whole middle away. Only where the rows really reach into the tail AND
    # leave a part outside does the rows-only boundary part from the fold's,
    # and it then protects more than the fold did: marking FEWER rows is the
    # safe side. A row that stays in the prompt although the summary also
    # speaks for it says the same thing twice; a row behind the seam that the
    # summary never covered would be lost.
    gewichte = [zeilentext(z, repositories, dokumentplan=None) for z in mitte]
    anfang = verdichtung.schwanz_anfang(gewichte, budget)
    if 0 < anfang < len(mitte):
        mitte = mitte[:anfang]
    if not mitte:
        return None
    inhalt = zusammenfassung
    inhalt = append_document_notes(
        inhalt, _earlier_document_notes(mitte), _dokumente_der_mitte(mitte, repositories)
    )
    geschrieben = repositories.messages.verdichten(
        chat_id=chat.id, text=inhalt, ersetzte_ids=[z.id for z in mitte]
    )
    if geschrieben is None:
        return None
    log.info(
        "Chat %s: fold added during the run, %d rows summed up into one",
        chat.id,
        len(mitte),
    )
    return geschrieben.id


def _nicht_falten(*, chat, mitte: list, art: str | None) -> verdichtung.Ergebnis:
    """Leaves the chat's rows exactly as they are, because no summary came
    back.

    No row is written, no seam appears and nothing is marked: nothing was
    folded, so no document leaves the prompt either and nothing can go
    without a word. The next turn asks again once the pause has run out —
    that pause IS the retry. A summary that failed leaves the messages
    unchanged.

    The saving brake is not asked and not set: it is there so no pointless
    request goes out for a middle that was answered and did not shrink, and
    this one was not answered.

    The pause is booked only where a model was really asked and failed —
    ``art`` is the failure class read off that request. ``None`` stands for
    the ways that never asked one (a forced fold inside a running pause, and
    no room to write a summary in): nothing was learned about the model
    there, so nothing is booked and ``notfall`` stays unset — the same answer
    ``verdichtung._nicht_falten`` gives a job.
    """
    if art is None:
        return verdichtung.Ergebnis(angewendet=False)
    gesperrt = faltpause.notfall(chat.id, art)
    log.warning(
        "Chat %s: fold failed (%s pause booked), %d rows stay unfolded%s",
        chat.id,
        art,
        len(mitte),
        " — automatic folding is now off" if gesperrt else "",
        extra={"ereignis": "chat_faltung_gescheitert", "chat": chat.id},
    )
    return verdichtung.Ergebnis(angewendet=False, notfall=True)
