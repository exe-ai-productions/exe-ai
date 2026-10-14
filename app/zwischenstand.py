"""The handoff a job writes itself when its context is almost full.

At 400 rounds over many files the context runs full, guaranteed — and until
now that killed the run outright: ``ProviderFehler`` caught after the fact,
whatever text happened to exist so far as the report, done. This module lets
a run notice EARLY (a round's own token reading, measured by the provider
and read as a share through ``app/kontextdruck.py`` like the context bar and
the fold trigger, crossing ``SCHWELLE_PROZENT``) and, with room still left to ask, get the
model to write a short status instead: what the task was, what is done, what
is next. The job then sets itself a cron entry (``app/tools/cronjob.py``)
a couple of minutes out and ends cleanly — the next run starts
with a genuinely empty context and picks the status up as its task.

Hardening: the "done" list is counted after every handoff, and a chain that
stops growing for three restarts in a row is a run going in circles, not one
making progress — it ends with a report instead of scheduling another
restart. ``MAX_NEUSTARTS`` is a second, absolute backstop, independent of
that count: a heuristic can be gamed, a hard ceiling cannot.

``nach_neustart_fortsetzen`` reuses the same restart machinery
for a cause neither of the two above: a plain service restart, with the run
mid-round when it happened. A run's status is by then already on its own
``auftraege`` row — written after every round, not only at this module's own
90% trigger — so the same cron entry, the same ``basisaufgabe``, and the same
``MAX_NEUSTARTS`` ceiling apply to it too, without reconstructing anything
from the transcript.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app import antwortgrenze, faltversuche, kontextvoll, reasoning
from app.agentendock import eintragsname
from app.providers import ChatNachricht

log = logging.getLogger(__name__)

# Leaves enough room for this one extra request-and-answer to still fit —
# waiting for a higher share risks the handoff itself no longer fitting,
# which is exactly the failure this module exists to avoid.
SCHWELLE_PROZENT = 90.0

# Three restarts with no growth in the done list: not a slow task, a stuck one.
OHNE_FORTSCHRITT_GRENZE = 3

# An absolute ceiling on restarts for one task chain, regardless of what the
# done-list count says — the count is read off the model's own words, and a
# run that pads it a little each time would otherwise never stop.
MAX_NEUSTARTS = 10

PUFFER_MINUTEN = 2

ANFRAGE_TEXT = """\
Your context is almost full. Do not call any more tools — write a short \
status instead, in exactly this shape:

## Task
One line: what this job was asked to do.

## Done
- One bullet per step you actually finished. Be specific — a fresh run with \
no memory of this conversation has to pick up from these lines alone.

## Next
What to do next, specific enough to act on immediately.
"""

# The heading under which a handoff names the files this run promised to the
# agent dock and never got there. Written
# into the continuation's task text, and read back out of it by the run that
# opens with that text — one thing doing both jobs.
#
# It is deliberately NOT a column on ``cronjobs`` beside ``notiz`` and the
# goal. A column could only make the continuation END badly; it could not
# make it DELIVER, because nothing would ever tell the model about the file.
# The chain would then fail on every further run for a delivery nobody was
# asked to repeat. Here the memory and the instruction are the same sentence:
# the run is told what it still owes, in the very text it is handed, and if
# it does not deliver, the ending says so.
#
# The shape is the "## Done" list's own, read back the same way
# (``erledigt_zaehlen``): a heading, one ``-`` bullet per name.
#
# But a block a model can also WRITE carries state, so the shape alone is not
# enough — the reader has to be able to tell OUR block from a sentence that
# merely looks like it. Three things do that, and all three were measured
# failing before they existed:
#
#   * The block ends at the first line that is not a bullet. A firing glues
#     the note and the goal on AFTER the task
#     (``app/cronablauf.py``), separated by a blank line and with no heading
#     of their own — so a note written as a list ("Reported so far:\n- mail
#     from A") used to be read as two more owed files. They were unpayable,
#     the chain failed on every restart, and the entry was switched off at
#     ``fehlergrenze``. That is a postbox job, the program's main case.
#   * The sentence below must stand right under the heading. A heading on its
#     own is something a model writes while talking about its own delivery.
#   * Only the LAST such block counts, never the union of all of them. The
#     genuine one is appended last, after the model's status text; a block
#     the model put in that status can no longer add a name.
OFFENE_ABLAGE_KOPF = "## Not delivered"

OFFENE_ABLAGE_SATZ = (
    "The previous run attempted to deliver these files to the agent dock, but the shelf "
    "rejected them. Delivery remains outstanding. Before finishing, deliver each file again "
    "using deliver_file with the same name."
)


@dataclass
class Entscheidung:
    """Whether the chain gets one more restart, and the counters to store."""

    weiter: bool
    erledigt_anzahl: int
    ohne_fortschritt: int
    neustarts: int


def erledigt_zaehlen(text: str) -> int:
    """How many "Done" bullets the handoff carries.

    Counts lines between the ``## Done`` heading and the next ``## `` one (or
    the end of the text) that start with ``-`` — the same shape asked for in
    ``ANFRAGE_TEXT``, read back out.
    """
    zeilen = text.splitlines()
    anzahl = 0
    im_abschnitt = False
    for zeile in zeilen:
        kopf = zeile.strip()
        if kopf.lower().startswith("## "):
            im_abschnitt = kopf.lower() == "## done"
            continue
        if im_abschnitt and kopf.startswith("-"):
            anzahl += 1
    return anzahl


def entscheiden(vorheriger, erledigt_anzahl: int) -> Entscheidung:
    """The next step for this chain, from the previous cron entry (``None``
    for a task's very first handoff — nothing to compare against yet, so it
    never counts as a stall on its own)."""
    alte_anzahl = vorheriger.erledigt_anzahl if vorheriger else None
    alter_ohne_fortschritt = vorheriger.ohne_fortschritt if vorheriger else 0
    alte_neustarts = vorheriger.neustarts if vorheriger else 0

    fortschritt = alte_anzahl is None or erledigt_anzahl > alte_anzahl
    ohne_fortschritt = 0 if fortschritt else alter_ohne_fortschritt + 1
    neustarts = alte_neustarts + 1

    weiter = ohne_fortschritt < OHNE_FORTSCHRITT_GRENZE and neustarts < MAX_NEUSTARTS
    return Entscheidung(
        weiter=weiter,
        erledigt_anzahl=erledigt_anzahl,
        ohne_fortschritt=ohne_fortschritt,
        neustarts=neustarts,
    )


def bald(config) -> str:
    """A daily time a couple of minutes out, in ``app.timezone`` — the same
    reading the alarm clock itself uses (app/wecker.py)."""
    name = config.app.timezone
    jetzt = datetime.now(ZoneInfo(name)) if name else datetime.now().astimezone()
    termin = jetzt + timedelta(minutes=PUFFER_MINUTEN)
    return f"{termin.hour:02d}:{termin.minute:02d}"


def ist_kette(cronjob) -> bool:
    """Whether this cron entry belongs to a restart chain and may be
    overwritten or switched off automatically (a chain
    always creates its own entry, never one a person made themselves).
    ``basisaufgabe`` is the mark — a chain sets it on its own first handoff,
    and nothing else in the program ever does."""
    return cronjob is not None and bool(cronjob.basisaufgabe)


def urspruengliche_aufgabe(vorheriger, task: str) -> str:
    """The chain's real original task — the one line every handoff has to
    work out, said once instead of at each of the three places that write a
    continuation (the context-full handoff and the provider outage in
    app/api/v1/auftraege.py, and the service restart below).

    Carried on the entry once it exists, never re-derived from the run's own
    text: from the second restart on that text is already the previous
    handoff's wrapped version, and re-wrapping it would grow the opening
    message with every restart.

    For a FIRST handoff there is nothing carried yet and the run's own text
    is the answer — with one exception, and it is what this function exists
    for. A firing glues things onto the entry's task before handing it to
    the run (app/cronablauf.py): the goal instruction, and the
    note from the previous run. The chain entry carries both on
    its own row, so both are appended to every one of ITS firings too, and
    taking the run's text here would put them in twice — once inside the
    "Original task:" line, once appended after it. With a note, the copy
    inside the original task is also the OLD note, so the run would be
    handed two contradicting versions of its own state.

    Which is why the test is the shape of the text rather than a list of
    the fields that can be appended: whatever a firing glues on, it glues on
    AFTER the entry's own task, so a run text that starts with that task is
    the wrapped form and the column is the unwrapped one. A later field
    appended at firing time is covered without this having to be touched.
    """
    if vorheriger is None:
        return task
    if vorheriger.basisaufgabe:
        return vorheriger.basisaufgabe
    if task.startswith(vorheriger.task):
        return vorheriger.task
    return task


def zielfelder(vorheriger) -> dict:
    """The goal a chain entry inherits from the entry it continues.

    Without this the continuation had no goal at all: ``ziel_verbuchen``
    (app/cronablauf.py) left immediately on a ``ziel`` of ``None``, so the
    run that actually found the thing stamped nothing and switched nothing
    off — and since a goal on the entry is also what puts the ``goal`` tool
    into a run's list at all (app/api/v1/auftraege.py), a continuation
    running as an agent whose own ``tools:`` leaves it out could not even
    have reported.
    """
    if vorheriger is None:
        return {"ziel": None, "ziel_stilllegen": False}
    return {"ziel": vorheriger.ziel, "ziel_stilllegen": vorheriger.ziel_stilllegen}


def kettenfelder(vorheriger, auftrag_id: str) -> dict:
    """Everything a FRESH continuation entry inherits from the entry whose
    work it takes over — the goal above, plus the two things that were
    missing and that a chain cannot work without.

    ``auftrag_id`` is the run that hands the work on. It only matters where
    there is no entry to inherit from — see ``ursprung_id`` below.

    ``einmalig``: a one-off entry has exactly one run, and the announcement
    that says so when nothing was found hangs off that flag
    (app/cronablauf.py). A continuation created without it is a standing
    entry as far as that check is concerned, so the one-off it continues
    ends in silence and the order simply vanishes — the very ending the flag
    exists to prevent. The ``datum`` of a one-off is deliberately NOT
    inherited: it names a day that has already come, and pinned to it the
    continuation would never be due again.

    ``ursprung_id``: which entry this is a continuation OF. Without it
    nothing the chain learns or reaches ever reaches the entry a person
    made. Passed through rather than pointing at the immediate predecessor,
    so a continuation of a continuation still names the real origin — one
    hop, always, however long the chain gets.

    A run somebody started by hand has no entry at all, and then the run
    itself is what a person made: the continuation names ``auftrag_id``.
    Left empty, the run and its continuation were two pieces of work — the
    reports list showed the started run as a context overflow and the
    result on a row of its own (``werk_von``, app/api/v1/schemas.py). Every
    reader that looks the id up as a cron entry (app/cronablauf.py,
    app/tools/cron_notiz.py) finds none for a run and carries on exactly as
    it did with no origin.

    ``notiz`` and ``notiz_am``: the note the entry has been keeping — the state of the work, and the only part of it a run is handed as
    fact rather than as prose. It travels FORWARD here, the direction the
    work itself travels. Without it a continuation opens with an empty
    memory: the mails already reported are reported again on the very run
    that was supposed to carry on from them, which is the loss the cron note
    exists to prevent. Worst at a provider outage, where the handoff text
    is nothing but "the model server was unreachable" and carries no state
    of its own at all. The note is inherited with the moment it was
    WRITTEN, not with the moment of this handoff: re-stamping it would tell
    the continuation the note is newer than it is, and everything in
    between would count as seen.

    A note read out of the entry's own row is also the reason the block
    lands in the task text exactly once: what a firing appends comes AFTER
    the entry's task (app/cronablauf.py), and ``urspruengliche_aufgabe``
    strips that wrapping off before it becomes the continuation's
    ``basisaufgabe``.

    ``fehlergrenze``: how many failed runs in a row this work is allowed,
   and how many quiet runs pass before the goal says nobody has
    reported anything. Both counts run on the continuation now,
    so a chain created without it answers to the default of 5 whatever the
    person set — an entry told "give up after 1" quietly gets five tries
    the moment its work is handed on.

    ``deliver``: whether the end of a run is announced at all.
    Somebody who set "announce" wants to hear about the work, and the run
    that finishes the work is very often the CONTINUATION, not the run that
    was asked for. Left behind at the default of 'log', the answer being
    waited for arrives in silence — the same quiet loss as the note and the
    failure limit above.

    And because it travels, the run that hands the work on stays quiet:
    ``melde_wenn_faellig`` (app/cronablauf.py) is told about the handoff and
    says nothing for it, so one piece of work carried over any number of
    restarts is announced exactly once — by whichever run ends it.
    """
    felder = zielfelder(vorheriger)
    if vorheriger is None:
        return {
            **felder,
            "einmalig": False,
            "ursprung_id": auftrag_id,
            "notiz": None,
            "notiz_am": None,
            "fehlergrenze": None,
            "deliver": "log",
        }
    return {
        **felder,
        "einmalig": vorheriger.einmalig,
        "ursprung_id": vorheriger.ursprung_id or vorheriger.id,
        "notiz": vorheriger.notiz,
        "notiz_am": vorheriger.notiz_am,
        "fehlergrenze": vorheriger.fehlergrenze,
        "deliver": vorheriger.deliver,
    }


def offene_ablagen_text(namen) -> str:
    """The block naming what a run still owes the agent dock, or an empty
    string when it owes nothing. Sorted, so the same set reads the same way
    twice and a test can name it.

    The names go through the shelf's own ``eintragsname``, so what is written
    here is one line per file and exactly the name a tile carries — a name
    can neither break the list apart nor name a file the shelf would store
    under something else.
    """
    liste = sorted({n for n in (eintragsname(x) for x in namen) if n})
    if not liste:
        return ""
    zeilen = "\n".join(f"- {n}" for n in liste)
    return f"{OFFENE_ABLAGE_KOPF}\n{OFFENE_ABLAGE_SATZ}\n{zeilen}"


def _ablage_bloecke(aufgabe: str) -> list[tuple[int, int, set[str]]]:
    """Every genuine debt block in a text: where it starts, where it ends,
    and the names in it. In the order they appear.

    A block is the heading, the sentence right under it, and the bullets that
    follow WITHOUT a gap. Anything else — a bare heading, a heading with
    prose under it, bullets after a blank line — is somebody talking, not
    this program writing.
    """
    zeilen = (aufgabe or "").splitlines()
    gefunden: list[tuple[int, int, set[str]]] = []
    i = 0
    while i < len(zeilen):
        if zeilen[i].strip() != OFFENE_ABLAGE_KOPF:
            i += 1
            continue
        if i + 1 >= len(zeilen) or zeilen[i + 1].strip() != OFFENE_ABLAGE_SATZ:
            i += 1
            continue
        namen: set[str] = set()
        ende = i + 2
        while ende < len(zeilen) and zeilen[ende].strip().startswith("-"):
            name = eintragsname(zeilen[ende].strip()[1:])
            if name:
                namen.add(name)
            ende += 1
        gefunden.append((i, ende, namen))
        i = ende
    return gefunden


def offene_ablagen_lesen(aufgabe: str) -> set[str]:
    """The names back out of a task text a continuation was handed.

    The failure this closes: ``ablage_offen`` was a local in the run, so
    a context overflow ended run 1 correctly and run 2 opened knowing
    nothing — delivered nothing, ended "fertig", and the schedule booked a
    success for a file that never arrived.

    The LAST genuine block, not the union of everything that looks like one.
    A handoff appends the block after the model's own status text, and a
    firing glues note and goal on after that (``app/cronablauf.py``) — so the
    only block this program wrote is the last one, and a model that writes
    the heading into its status can neither invent a debt nor, by naming a
    file the same way twice, quietly settle one. See the note at
    ``OFFENE_ABLAGE_KOPF`` for the three rules and what each of them cost.
    """
    bloecke = _ablage_bloecke(aufgabe)
    return set(bloecke[-1][2]) if bloecke else set()


def ohne_ablagebloecke(text: str) -> str:
    """The same text with every debt block cut back out of it.

    Two jobs, and they are the same job. The running job stores its own debt
    on its row behind its status (``mit_offenen_ablagen``), and the resumed
    run is handed a freshly built block — without this it would carry the
    list twice, once as a stale copy inside the status it is shown, the very
    "two contradicting versions of its own state" ``urspruengliche_aufgabe``
    exists to prevent.

    And it is what makes the block honest. Every piece of a task text that a
    MODEL wrote goes through here before it is glued in — the status, the
    original task line, the note and the goal (``app/cronablauf.py``). After
    that the only block left in the text is the one this program appended
    itself, so a run cannot invent a debt for its continuation by writing the
    heading and the sentence into its own prose. Scrubbing rather than
    escaping, because the block is an instruction from the program and a
    model quoting it is not one.
    """
    bloecke = _ablage_bloecke(text)
    if not bloecke:
        return text or ""
    zeilen = (text or "").splitlines()
    behalten: list[str] = []
    stand = 0
    for anfang, ende, _ in bloecke:
        behalten.extend(zeilen[stand:anfang])
        stand = ende
    behalten.extend(zeilen[stand:])
    return "\n".join(behalten).strip("\n")


def mit_offenen_ablagen(text: str, namen) -> str:
    """A text with the debt block behind it — the one way the block is ever
    written, so the handoff and the running job's own saved status put it in
    the same place and in the same shape."""
    block = offene_ablagen_text(namen)
    if not block:
        return text or ""
    return f"{text}\n\n{block}" if text else block


def naechste_aufgabe(urspruenglich: str, zwischenstand: str, offene_ablagen=()) -> str:
    """The task text the resumed run opens with — the status, not the
    original wording alone, so a genuinely empty context still knows both
    what the job was and where it stood.

    ``offene_ablagen`` are the deliveries this run promised and never got
    onto the shelf. They are appended rather than folded into the status,
    because the status is the model's own prose and this is a fact the run
    knows for certain. Built fresh from the live set at every handoff and
    never copied out of the previous task, exactly as ``basisaufgabe`` keeps
    the original sentence from being wrapped twice.

    And the two pieces of model prose that go INTO the text are scrubbed of
    anything block-shaped first (``ohne_ablagebloecke``), so the appended one
    is the only one there is. Otherwise a run whose status happened to carry
    the heading and the sentence handed its continuation a debt this program
    never recorded — a file nobody was ever asked to deliver, failing every
    further run of the chain until ``fehlergrenze`` switched the entry off.
    """
    text = (
        f"Continue this job. Original task: {ohne_ablagebloecke(urspruenglich)}\n\n"
        f"Status from the previous run:\n\n{ohne_ablagebloecke(zwischenstand)}"
    )
    return mit_offenen_ablagen(text, offene_ablagen)


def nach_neustart_fortsetzen(config, repositories, *, nur_eigene: bool = False) -> int:
    """Schedules a resumption for every job a hard restart cut off mid-run
    — not only the ones that already belonged to a restart
    chain. Call right after the start-up clean-up of the job repository has
    moved them from running to interrupted.

    Each job already carries its own status from the periodic write during
    the run (``AuftragRepository.zwischenstand_setzen``) — nothing here
    reconstructs anything from the transcript. The restart ceiling is the
    same ``MAX_NEUSTARTS`` the context-full handoff and the provider-outage
    retry already answer to, read off the SAME cron entry when this job's
    chain already has one (``Auftrag.cronjob_id``) — a chain does not get a
    second, independent budget just because the cause of this restart was
    different from the one before it.

    ``nur_eigene`` is handed straight on to the query: beside a second,
    living service on the same data folder only our own jobs may be picked
    up (``AuftragRepository.unterbrochene_mit_zwischenstand``).

    Returns how many were scheduled to run again.
    """
    geplant = 0
    for auftrag in repositories.auftraege.unterbrochene_mit_zwischenstand(
        nur_eigene=nur_eigene
    ):
        if fortsetzung_planen(config, repositories, auftrag):
            geplant += 1
    return geplant


def fortsetzung_planen(config, repositories, auftrag, zusatz: str = "") -> bool:
    """Schedules ONE job to carry on from its own status. True if it will.

    Lifted out of the loop above because a second occasion needs exactly
    this: a run that stopped on a question, was cut off by a restart, and is
    answered afterwards (``app/api/v1/auftraege.py``). The answer must not
    be thrown away because the process that asked is gone — so it is handed
    to the continuation the same way the status is.

    ``zusatz`` is that answer, appended to the status as one more paragraph.
    Empty for the restart case, which has nothing to add.
    """
    vorheriger = (
        repositories.cronjobs.holen(auftrag.cronjob_id)
        if auftrag.cronjob_id else None
    )
    neustarts = (vorheriger.neustarts if vorheriger else 0) + 1
    # Marks this row handled, whichever way it goes below — otherwise
    # the next service start finds the exact same row again through
    # ``unterbrochene_mit_zwischenstand`` and plans a second resumption
    # (or a second ceiling hit) for a restart that already happened.
    repositories.auftraege.zwischenstand_setzen(auftrag.id, None)
    if neustarts >= MAX_NEUSTARTS:
        # Only a chain's own entry stops here — a person's
        # own schedule (basisaufgabe unset) is never the ceiling's to
        # switch off, whatever the count says.
        if vorheriger is not None and ist_kette(vorheriger):
            repositories.cronjobs.aktiv_setzen(vorheriger.id, False)
        return False

    basis = urspruengliche_aufgabe(vorheriger, auftrag.auftrag)
    # What the cut-off run still owed the agent dock — from BOTH sides.
    # The opening text carries what this run inherited as a continuation. The saved status
    # carries what this run itself was refused: the running job writes
    # the debt onto its own row the moment it changes
    # (``app/api/v1/auftraege.py``), for the same reason it writes its
    # status after every round. Reading only the opening text lost two
    # thirds of it — a first run that lost a file and was then cut off
    # came back owing nothing, and ended "fertig" for a file that never
    # arrived, which is the very hole the debt was built to close.
    status = auftrag.zwischenstand or ""
    schuld = offene_ablagen_lesen(auftrag.auftrag) | offene_ablagen_lesen(status)
    if zusatz:
        status = f"{status}\n\n{zusatz}".strip()
    neue_aufgabe = naechste_aufgabe(basis, status, schuld)
    zeitplan = bald(config)
    if vorheriger is not None and ist_kette(vorheriger):
        # Only a chain's own entry is adopted — a schedule a person
        # made themselves keeps its own text, time and state; a fresh
        # chain entry is created below instead.
        ziel_id = vorheriger.id
        repositories.cronjobs.aktualisieren(
            ziel_id, task=neue_aufgabe, zeitplan=zeitplan, basisaufgabe=basis,
            # Armed again in the same breath as the new task: a chain
            # that inherited ``einmalig`` switched itself off when it
            # fired, and this row is the one that has to run next.
            aktiv=True,
        )
    else:
        ziel_id = repositories.cronjobs.erstellen(
            agent=auftrag.agent, task=neue_aufgabe, zeitplan=zeitplan,
            herkunft="agent", basisaufgabe=basis,
            **kettenfelder(vorheriger, auftrag.id),
        ).id
    repositories.cronjobs.fortschritt_setzen(
        ziel_id,
        erledigt_anzahl=vorheriger.erledigt_anzahl if vorheriger else None,
        ohne_fortschritt=vorheriger.ohne_fortschritt if vorheriger else 0,
        neustarts=neustarts,
    )
    return True


async def anfordern(
    zustand, anfrage, eingestellte_grenze: int | None, generierung
) -> str | None:
    """Asks the model for the handoff, as one more, final round. Whatever
    tool calls it returns anyway are ignored — a round already this close to
    the limit gets no more actions, only text.

    Read the way the round itself reads (``generierung.naechstes_stueck``,
    app/generationen.py): a server that sends nothing but keepalives would
    otherwise hold a plain ``async for`` open for good, and the stop button
    would never land. None when a stop ended it — then nothing is handed
    off.

    And under the two clocks of the fold and the image prompt request
    (``app/faltversuche.read_stream``): the race against the stop button
    only helps a run somebody watches. An unattended job whose server sends
    nothing but keepalives never gets a stop, so the round ends once the
    server has gone silent for ``STILLE_SEKUNDEN`` or the request has run
    past ``GESAMT_SEKUNDEN``. It ends the way a failed fold does
    (``app/verdichtung.py``): the clock's own line in the log, and nothing
    to hand off — ``""``, the answer the caller already ends the job on as a
    full context. Raised on to the caller, the silence ended the job as an
    unexpected failure with a stack trace.

    A round that ended by itself without one visible character thought its
    handoff instead of writing it: the thinking is the handoff then, the
    same swap the chat and the job make at the end of a run
    (``app/reasoning.denktext_als_antwort``) — without it a handoff that is
    there would count as none and the job as failed.

    Sent with the largest answer ceiling that still fits beside the
    transcript (``app/antwortgrenze.py`` ``hoechste_passende``), capped by
    ``eingestellte_grenze`` where one is set but never simply carrying it:
    the trigger above fires at ``SCHWELLE_PROZENT`` of the WHOLE window, so
    the round's ordinary ceiling — which a full window already leaves no
    room beside — is exactly what this one request cannot afford to repeat.
    """
    anfrage.nachrichten.append(ChatNachricht(role="user", content=ANFRAGE_TEXT))
    grenze = antwortgrenze.hoechste_passende(
        eingestellte_grenze,
        antwortgrenze.geltender_deckel(zustand, anfrage.modell),
        zustand.context_tokens or 0,
        antwortgrenze.eingabe_schaetzen(anfrage.nachrichten, anfrage.werkzeuge),
    )
    anfrage = kontextvoll.mit_grenze(anfrage, grenze, zustand)
    text: list[str] = []
    gedanke: list[str] = []
    ende_grund: str | None = None
    quelle = zustand.provider.streamen(anfrage)
    # Both closed, the stream even where closing the reader raises: the
    # reader closes the stream it was reading, but a stop that won before
    # the reader ever ran leaves it unstarted, and closing an unstarted
    # reader does not reach the stream behind it.
    try:
        async with contextlib.aclosing(quelle), contextlib.aclosing(
            faltversuche.read_stream(quelle, "handoff request")
        ) as pieces:
            while True:
                stueck, abbruch = await generierung.naechstes_stueck(pieces)
                if stueck is None:
                    if abbruch:
                        return None
                    break
                if stueck.sorte == "content":
                    text.append(stueck.text)
                elif stueck.sorte == "reasoning":
                    gedanke.append(stueck.text)
                elif stueck.sorte == "stats":
                    ende_grund = stueck.daten.get("ende_grund")
    except faltversuche.Stille as error:
        log.warning("Handoff not received: %s", error)
        return ""
    # "fertig" is the only state this round can be in here: a stop button
    # ended it above (None), a failure raises to the caller — what is left
    # is a round that ended on its own, and the stage's own check on the
    # ending decides the rest. One round, so its thinking is the whole
    # thinking; there is no earlier deliberation to hold back.
    geschrieben = "".join(text).strip()
    gedacht = "".join(gedanke).strip()
    handoff, _ = reasoning.denktext_als_antwort(
        geschrieben,
        gedacht,
        gedacht,
        schlusstext=geschrieben,
        ende_grund=ende_grund,
        zustand="fertig",
    )
    return handoff
