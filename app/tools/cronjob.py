"""The cronjob tool — create/list/remove/pause/resume/update.

One general-purpose table of scheduled runs (app/db/repositories/cronjobs.py),
distinct from an agent's own single ``schedule:`` front-matter field
(app/wecker.py) — this is the "several independent standing reminders" case,
reachable from a chat, from the shipped ``/cronjob`` skill, or from an agent
setting its own. Firing always starts a job the same way no matter who set
the schedule (app/cronablauf.py) — one path instead of two.

Security, matching what the plan calls "not optional":

1. The task text is stripped of invisible/format characters before it is
   stored — a page an agent read could otherwise plant a poisoned standing
   instruction nobody would ever see.
2. An agent-originated call is pinned to the calling agent's own name and
   own entries: it can create, list, pause, resume or edit only its own
   schedule, and can never borrow a more privileged agent's identity or
   reach into someone else's. A chat call carries no such limit — a person
   is watching every call it makes.
3. Visibility and the on/off switch live in the settings window, not here —
   this module only stores what the interface later shows and toggles.
4. A schedule that starts a SCRIPT can only be created or changed
   from a chat, and an agent-originated call can neither reach such an entry
   nor set ``script`` on any other. This is the strictest of the four, and it
   has to be: a script runs with the user's full rights and never passes Tor 3
   (app/berechtigungen.py) — no tool name, no arguments, nobody to ask. Left
   open, the road reads: a page an agent reads talks it into writing itself a
   script entry, and code runs unattended past a gate that never saw it. The
   rest of that guard — which folder, which file, how long — lives in
   app/skriptlauf.py.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date as _Datum, datetime as _Datetime
from typing import Any
from zoneinfo import ZoneInfo

from app import skriptlauf, terminplan, zwischenstand
from app import agentenname, ohne_agent, reminder
from app.agenten import agenten_laden
from app.tools.mcp_client import MCPWerkzeug

SERVER_NAME = "cronjob"
WERKZEUG_NAME = "cronjob"

DELIVER_LOG = "log"
DELIVER_ANSAGE = "announce"

_DATUM_MUSTER = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Newline and tab are the only control characters a schedule's task text can
# legitimately carry — everything else in the "invisible" Unicode categories
# is either a formatting trick (zero-width joiners, direction overrides,
# a BOM) or a control code with no business in stored text.
_STEUERZEICHEN_ERLAUBT = {"\n", "\t"}
_UNSICHTBARE_KATEGORIEN = {"Cf", "Cc", "Co", "Cs"}
AKTIONEN = ("create", "list", "remove", "pause", "resume", "update")

# Said in one place because three checks say it: a separate day only means
# something next to a daily 'HH:MM'. A cron expression already carries which
# days it means, and an instant is a day and a time in one string — a second
# day beside either of them could only contradict it.
_NUR_MIT_TAGESZEIT = (
    "'date' only applies to a daily 'HH:MM' time — a cron expression or an "
    "instant 'YYYY-MM-DDTHH:MM' already says which day it means."
)

# How many failed runs in a row an entry may take before it stops trying.
#One is the smallest number that still means anything; above
# twenty a limit stops being a brake.
GRENZE_KLEINSTE = 1
GRENZE_GROESSTE = 20
_GRENZE_TEXT = (
    f"'max_failures' must be a whole number from {GRENZE_KLEINSTE} to "
    f"{GRENZE_GROESSTE}."
)

# The numbers the two range refusals name, for the sentence a person reads.
_GRENZE_WERTE = {"min": GRENZE_KLEINSTE, "max": GRENZE_GROESSTE}

# Said in one place because create and update both say it: the switch that
# stops an entry when its goal is reached means nothing without a goal to
# reach.
_NUR_MIT_ZIEL = (
    "'stop_when_reached' needs a 'goal' — set one in the same call, or use "
    "it on an entry that already has one."
)

# How long a script may run, per entry. One second is the smallest
# number that means anything; a day is where a limit stops being one — a
# schedule whose run may outlast a whole day would start overlapping itself.
SEKUNDEN_KLEINSTE = 1
SEKUNDEN_GROESSTE = 86_400
_SEKUNDEN_TEXT = (
    f"'max_seconds' must be a whole number from {SEKUNDEN_KLEINSTE} to "
    f"{SEKUNDEN_GROESSTE}."
)
_SEKUNDEN_WERTE = {"min": SEKUNDEN_KLEINSTE, "max": SEKUNDEN_GROESSTE}
_SEKUNDEN_NUR_MIT_SKRIPT = (
    "'max_seconds' belongs to a script entry — an agent run has its own "
    "limits."
)

# The refusal that carries the whole security of script entries. Worded as a
# reason rather than a rule: the caller is a model, and a model that is told
# WHY does not spend the next round looking for a way round it.
_NUR_AUS_DEM_CHAT = (
    "A schedule that runs a script can only be set up from a chat. An "
    "agent's own run cannot create one and cannot set or change 'script' — "
    "a script runs with the user's full rights and is not asked about "
    "before it starts, so a person has to have seen which file it is."
)
_SKRIPT_STATT_AGENT = (
    "A script entry runs a script instead of an agent — leave 'agent' and "
    "'task' out of the same call."
)
_KEIN_ZIEL_FUER_SKRIPT = (
    "A script entry cannot carry a 'goal': there is no model in it to report "
    "one. Its exit code is the answer — 0 is a good run, anything else a "
    "failed one."
)
_SKRIPT_NUR_TAUSCHEN = (
    "'script' can only be changed on an entry that already runs one. Create "
    "a new entry instead of turning an agent's schedule into a script."
)
_REMINDER_ALONE = (
    "A reminder shows its text and runs nothing — leave 'agent', 'script' "
    "and 'goal' out of the same call."
)
_KEINE_SKRIPTE = (
    "Scripts are not available here — this service has no scripts folder."
)


class CronjobVerboten(Exception):
    """The call was refused — nothing was stored or changed.

    English prose, because the reader is a model: this is a tool answer like
    every other one. A refusal that can reach a person through the mask
    (app/api/v1/cronjobs.py) carries a catalogue key alongside it
    (``schluessel``/``werte``), and the route shows that sentence in the
    reader's language. Only the refusals no mask can cause — an agent's own
    call, an unknown action — carry none. The key travels rather than being
    re-derived: by the time the route sees this, the original refusal is
    gone.
    """

    def __init__(
        self, text: str, *, schluessel: str | None = None, werte: dict | None = None
    ) -> None:
        self.schluessel = schluessel
        self.werte = werte or {}
        super().__init__(text)


def werkzeug_beschreibung(agenten: dict[str, Any] | None = None) -> MCPWerkzeug:
    return MCPWerkzeug(
        name=WERKZEUG_NAME,
        beschreibung=(
            "Manages schedules — entries that start a job, run a script or "
            "show a reminder, either on a recurring schedule until removed or "
            "once and then stop. "
            "Actions: "
            "'create' (needs 'time' and 'task'; 'once' true fires it a "
            "single time instead of repeating; 'date' additionally pins a "
            "one-off entry to an exact day — only valid together with "
            "'once' AND a daily 'HH:MM' time; without it a one-off still "
            "fires at the next occurrence of 'time'; 'agent' picks who "
            "runs it — from a chat any agent, from an agent's own call "
            "this is ignored and forced to itself), "
            "'list' (no further fields), 'remove'/'pause'/'resume' (need "
            "'id'), 'update' (needs 'id', plus whichever of "
            "'time'/'task'/'agent'/'once'/'date'/'notify'/'max_failures'/"
            "'goal'/'stop_when_reached'/'script'/'max_seconds' changes).\n"
            "Set 'reminder' true when the person only wants to be reminded: "
            "at the time, the system shows 'task' as a notification with a "
            "sound, once, and no model runs at all.\n"
            "Use 'script' INSTEAD of 'task' when the work is a script that "
            "already exists — a nightly backup, a sync, a cleanup. Such an "
            "entry starts no model at all, which is the point: loading a "
            "language model to say 'run the backup' costs minutes and gains "
            "nothing. It reports success by exit code, not by writing a "
            "report.\n"
            "An entry that keeps failing stops trying — see "
            "'max_failures'.\n"
            "Give it a 'goal' when the point is to wait for something to "
            "happen ('tell me when the mail from Taylor arrives'): the "
            "entry then stays silent run after run and speaks up only when "
            "the goal is actually met. Without a 'goal' it reports after "
            "every single run, which for anything checked often is a flood "
            "nobody reads.\n"
            "Called from inside an agent's own run, this only ever touches "
            "that agent's own entries — never another agent's, and it can "
            "never reassign an entry to a different agent."
        ),
        schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": list(AKTIONEN)},
                "id": {
                    "type": "string",
                    "description": "Which entry — for remove/pause/resume/update.",
                },
                "time": {
                    "type": "string",
                    "description": (
                        "When it fires, in one of three forms. A daily time, "
                        "24h 'HH:MM' — 'every day at 08:00'. A five-field "
                        "cron expression 'minute hour day-of-month month "
                        "day-of-week' — '*/15 * * * *' every fifteen "
                        "minutes, '0 * * * *' hourly, '0 9 * * 1-5' at 09:00 "
                        "on weekdays, '0 3 1 * *' at 03:00 on the first of "
                        "the month. Or one fixed instant "
                        "'YYYY-MM-DDTHH:MM' — '2030-06-01T09:00' means that "
                        "one moment and nothing after it. A cron expression "
                        "must not come due more often than once a minute."
                    ),
                },
                "task": {
                    "type": "string",
                    "description": (
                        "What the agent should do when this fires — or, for "
                        "a reminder, the text the notification shows."
                    ),
                },
                "reminder": {
                    "type": "boolean",
                    "description": (
                        "True for a reminder: no agent and no model, only "
                        "the notification with 'task' as its text."
                    ),
                },
                "agent": {
                    "type": "string",
                    # The names as they stand on disk, so nobody has to guess
                    # one. Both a wrong guess and the right word in the wrong
                    # case used to be refused with nothing but the rejected
                    # word back, and there was no way to ask what exists.
                    # Capitals are forgiven on the way in; the spelling here
                    # is the one that gets stored.
                    **({"enum": sorted(agenten, key=str.casefold)} if agenten else {}),
                    "description": (
                        "Which agent runs it. Leave out on create to run it "
                        "with no agent: the model that runs unattended, with "
                        "every approved tool except asking the user, the "
                        "memory, scheduling and starting further runs, and "
                        "with no folders.\n"
                        + (
                            f"Available: {agentenname.auswahl_satz(agenten)}."
                            if agenten
                            else ""
                        )
                    ),
                },
                "notify": {
                    "type": "boolean",
                    "description": (
                        "Whether firing should also show a system notification "
                        "with the task text and play a sound once the run ends. "
                        "Off by default — then a fired run only goes into its "
                        "own log.\n"
                        "An entry with a 'goal' is the exception: it reports "
                        "when the goal is reached whether or not this is set, "
                        "because that one report is the whole point of it. Set "
                        "this to false there to take even that away."
                    ),
                },
                "once": {
                    "type": "boolean",
                    "description": (
                        "Fire at 'time' a single time, then deactivate — for "
                        "a one-off entry ('in 10 minutes', 'today at 14:55') "
                        "instead of a standing recurring one. Off by default. "
                        "An instant 'time' already names a single moment and "
                        "needs this only to say so plainly."
                    ),
                },
                "date": {
                    "type": "string",
                    "description": (
                        "Exact day a 'once' entry is due, 'YYYY-MM-DD' — for "
                        "'remind me Friday at 9' where the next occurrence of "
                        "'time' alone would mean the wrong day. Only ever "
                        "valid next to a daily 'HH:MM' time: a cron "
                        "expression or an instant already says which day it "
                        "means. Rejected if it is in the past. On create, "
                        "only valid together with 'once'; on update, only on "
                        "an entry that is already 'once' or is turned into "
                        "one in the same call — never together with "
                        "switching 'once' off."
                    ),
                },
                "max_failures": {
                    "type": "integer",
                    "minimum": GRENZE_KLEINSTE,
                    "maximum": GRENZE_GROESSTE,
                    "description": (
                        "How many failed runs in a row switch this entry "
                        f"off, {GRENZE_KLEINSTE}-{GRENZE_GROESSTE}, 5 by "
                        "default. A run counts as failed only when it could "
                        "not do its work at all — the model was "
                        "unreachable, a tool was refused, the run broke "
                        "off. A run that went and looked and found nothing "
                        "worth reporting is a successful run and puts the "
                        "count back to zero. Raise it for something flaky, "
                        "lower it for something that should not be left "
                        "banging away."
                    ),
                },
                "goal": {
                    "type": "string",
                    "description": (
                        "What has to be true for this entry to be worth "
                        "reporting. With one set, a run that does not reach "
                        "it says nothing at all — no sound, no "
                        "notification — and only the run that does reaches "
                        "the user. Leave it out for a schedule that is "
                        "meant to report every time (a daily summary).\n"
                        "Name the evidence, not the wish: 'an unread mail "
                        "from Taylor in the inbox — name the sender and the "
                        "subject' rather than 'mail from Taylor is there'. "
                        "A goal that says how it is recognised is one the "
                        "run can check itself against.\n"
                        "On update, an empty string removes the goal."
                    ),
                },
                "script": {
                    "type": "string",
                    "description": (
                        "File name of a script in the scripts folder, run "
                        "INSTEAD of an agent — 'backup.sh'. Use it when the "
                        "work already exists as a script: no model is "
                        "started, no task text is needed, and the script's "
                        "exit code decides ('0' good, anything else a failed "
                        "run that counts towards 'max_failures'). A plain "
                        "file name and nothing else: no path, no '..', and "
                        "the file has to be in that folder and executable. "
                        "The user opens and edits that folder themselves — "
                        "its path is shown under the schedule list. Cannot "
                        "be combined with 'agent', 'task' or 'goal', and "
                        "can only be set from a chat, never from inside an "
                        "agent's own run."
                    ),
                },
                "max_seconds": {
                    "type": "integer",
                    "minimum": SEKUNDEN_KLEINSTE,
                    "maximum": SEKUNDEN_GROESSTE,
                    "description": (
                        "How many seconds the script may run before it is "
                        "stopped and the run counts as failed, "
                        f"{SEKUNDEN_KLEINSTE}-{SEKUNDEN_GROESSTE}. Leave it "
                        "out for the standard command limit; raise it for "
                        "something long, like a backup. Only for a 'script' "
                        "entry."
                    ),
                },
                "stop_when_reached": {
                    "type": "boolean",
                    "description": (
                        "Whether reaching the goal switches the entry off. "
                        "True for a one-time wait ('tell me when the mail "
                        "arrives' — once it has, there is nothing left to "
                        "watch), false for something that should keep "
                        "going (a daily check that reports on the days it "
                        "finds something). Off by default. Only valid "
                        "together with a 'goal'."
                    ),
                },
            },
            "required": ["action"],
        },
        server=SERVER_NAME,
    )


def _bereinigt(text: str) -> str:
    """Strips invisible/format/control characters — kept: an ordinary
    newline or tab, and everything a person could actually see."""
    return "".join(
        zeichen
        for zeichen in text
        if zeichen in _STEUERZEICHEN_ERLAUBT
        or unicodedata.category(zeichen) not in _UNSICHTBARE_KATEGORIEN
    ).strip()


def _aufgabe_bereinigt(wert: Any) -> str:
    """A task text on its way onto a cron row: invisible characters out
    (``_bereinigt``), and anything shaped like the agent dock's debt block
    out with them.

    The block — ``app/zwischenstand.py`` — is how a run tells its
    continuation which deliveries it still owes the shelf, and it is meant to
    be something only the program can write. Every OTHER piece of model prose
    that reaches a task text is already scrubbed of it: the status and the
    original task at the handoff (``naechste_aufgabe``), the note and the
    goal at firing time (``app/cronablauf.py``). The entry's own task was
    not, and a model writes that text itself — an agent setting its own
    schedule, or a chat call it talked somebody into.

    What that costs is the worst shape this hole has. A firing glues the
    entry's task in front of everything else, so a faked block there is the
    LAST genuine block of every single run of that entry: each one opens
    owing a file nobody recorded, cannot pay it, ends ``ablage_gescheitert``,
    and the entry counts its way to ``fehlergrenze`` and switches itself
    off. Not once — every run, until it is dead.

    After ``_bereinigt``, not before: the block is recognised by its heading
    and its sentence read literally, so it has to be looked for in the text
    as it will actually be stored, not in one that still carries a
    zero-width character in the middle of the heading.
    """
    return zwischenstand.ohne_ablagebloecke(_bereinigt(str(wert or "")))


def _grenze_pruefen(wert: Any) -> int | None:
    """The per-entry failure limit, or ``None`` when the caller said nothing
    about it — leaving the stored default in place rather than writing it a
    second time from here.

    ``bool`` is turned away on purpose although Python counts it as an
    ``int``: 'true' is not a number of runs, and a model that mixes the two
    up is better told so than handed a silent limit of one."""
    if wert is None:
        return None
    if isinstance(wert, bool) or not re.fullmatch(r"-?\d+", str(wert).strip()):
        raise CronjobVerboten(_GRENZE_TEXT, schluessel="cronjob_refusal.max_failures", werte=_GRENZE_WERTE)
    zahl = int(str(wert).strip())
    if not GRENZE_KLEINSTE <= zahl <= GRENZE_GROESSTE:
        raise CronjobVerboten(_GRENZE_TEXT, schluessel="cronjob_refusal.max_failures", werte=_GRENZE_WERTE)
    return zahl


def _sekunden_pruefen(wert: Any) -> int | None:
    """The per-entry time limit for a script, or ``None`` when the caller
    said nothing — leaving the shipped default in place instead of writing a
    copy of it into the row. ``bool`` is turned away for the same reason as
    in ``_grenze_pruefen``: 'true' is not a number of seconds."""
    if wert is None:
        return None
    if isinstance(wert, bool) or not re.fullmatch(r"-?\d+", str(wert).strip()):
        raise CronjobVerboten(_SEKUNDEN_TEXT, schluessel="cronjob_refusal.max_seconds", werte=_SEKUNDEN_WERTE)
    zahl = int(str(wert).strip())
    if not SEKUNDEN_KLEINSTE <= zahl <= SEKUNDEN_GROESSTE:
        raise CronjobVerboten(_SEKUNDEN_TEXT, schluessel="cronjob_refusal.max_seconds", werte=_SEKUNDEN_WERTE)
    return zahl


def _skript_pruefen(wert: Any, skripte_ordner, herkunft: str) -> str:
    """The script's file name, or a refusal — the two locks of script entries in the
    order they have to be asked in.

    WHO first: an agent-originated call is turned away before the file is so
    much as looked at. The answer must not depend on what is in the folder,
    or a run that reads a web page learns which scripts exist by trying
    names — and worse, a name that happens to be there would be the one call
    that gets through.

    WHAT second, and not here: which folder, which file, executable at all —
    that is app/skriptlauf.py's, and it is the same function the firing loop
    calls again at every single firing. One rule, asked twice, rather than a
    creation-time copy that drifts from the one that actually decides.
    """
    if herkunft != "chat":
        raise CronjobVerboten(_NUR_AUS_DEM_CHAT)
    if skripte_ordner is None:
        raise CronjobVerboten(_KEINE_SKRIPTE, schluessel="cronjob_refusal.no_scripts")
    try:
        return skriptlauf.geprueft(skripte_ordner(), str(wert or "")).name
    except skriptlauf.SkriptVerboten as fehler:
        raise CronjobVerboten(
            str(fehler), schluessel=fehler.schluessel, werte=fehler.werte
        ) from fehler


def _ziel_pruefen(wert: Any) -> str | None:
    """The goal text, cleaned the same way the task text is — it
    is stored, read back into the next run's task, and shown in the mask,
    so a page the model read must not be able to plant anything invisible
    in it. ``None`` means the caller said nothing about the goal; an empty
    string is the caller saying "remove it" and is answered by the update
    path, not here."""
    if wert is None:
        return None
    return _bereinigt(str(wert))


# A goal may be put on ANY agent. The first build
# refused one whose front matter's ``tools:`` left ``goal`` out, on the
# grounds that such an entry would watch in silence for ever — true at the
# time, and the wrong end to fix it from: it told the user about a wiring
# detail instead of wiring it. A run whose entry carries a goal is now
# offered the tool regardless of that list (app/api/v1/auftraege.py,
# app/tools/registry.py), so there is nothing left to refuse.


def _sorte(zeitplan: str) -> str | None:
    """Which of the three shapes a stored schedule is, or ``None`` if it is
    none of them. Used where an already-stored value is being reasoned about
    and a refusal would be the wrong answer — a row nobody can read is not
    the caller's fault, and the checks below simply do not apply to it."""
    try:
        return terminplan.sorte(zeitplan)
    except terminplan.TerminplanFehler:
        return None


def _ist_taeglich(zeitplan: str) -> bool:
    """Whether this schedule is the daily 'HH:MM' shape — the only one the
    separate ``date`` field belongs to. A cron expression already says which
    days it means, and an instant IS a day and a time."""
    return _sorte(zeitplan) == terminplan.SORTE_TAEGLICH


def _jetzt(zeitzone: str | None) -> _Datetime:
    """Now, as a wall clock in ``app.timezone`` — the one zone every stored
    schedule is read in (app/terminplan.py, app/wecker.py:134-138).

    Naive on purpose: the moments checked against it are naive too, and
    both mean local time in that zone. Read in the SERVER's zone instead,
    the two checks below compared two different clocks: on a UTC machine
    with ``app.timezone`` Europe/Berlin, 12:00 Berlin reads as 10:00, so an
    entry for 11:30 — half an hour gone in Berlin — was accepted and then
    sat there, confirmed, never firing; and the two hours ahead of the
    server's clock were turned away although they had not come yet.
   Without the setting the server's
    zone is the app's zone, and the two readings coincide."""
    if zeitzone:
        return _Datetime.now(ZoneInfo(zeitzone)).replace(tzinfo=None)
    return _Datetime.now()


def _zeitpunkt_pruefen(zeit: str, zeitzone: str | None) -> None:
    """Rejects an instant that has already gone by. Same reasoning as
    ``_datum_pruefen``: an entry whose one and only moment lies in the past
    would sit there confirmed and never fire, because nothing after it is
    ever due again."""
    if _Datetime.fromisoformat(zeit) < _jetzt(zeitzone):
        raise CronjobVerboten("'time' is in the past.", schluessel="cronjob_refusal.time_past")


def _zeit_pruefen(zeit: Any, zeitzone: str | None) -> str:
    """The schedule field, in any of the three shapes app/terminplan.py
    reads — a daily 'HH:MM', a five-field cron expression, or a fixed
    instant. Checked by that one module rather than by a second pattern
    here, so what can be stored and what can be read stay the same set."""
    zeit = str(zeit or "").strip()
    try:
        terminplan.sorte(zeit)
    except terminplan.TerminplanFehler as fehler:
        raise CronjobVerboten(
            f"'time' {fehler}.", schluessel="cronjob_refusal.time_unreadable"
        ) from fehler
    try:
        terminplan.abstand_pruefen(zeit)
    except terminplan.TerminplanFehler as fehler:
        # Readable, but it never comes due, or more often than the loop
        # can notice — two different things to go and change.
        grund = (
            "cronjob_refusal.time_never_due"
            if fehler.__cause__ is not None
            else "cronjob_refusal.time_too_often"
        )
        raise CronjobVerboten(f"'time' {fehler}.", schluessel=grund) from fehler
    if _sorte(zeit) == terminplan.SORTE_ZEITPUNKT:
        _zeitpunkt_pruefen(zeit, zeitzone)
    return zeit


def _datum_pruefen(datum: Any, zeit: str, zeitzone: str | None) -> str:
    """Rejects a past date — checked against the full moment ('date' plus
    'zeit'), not the date alone: today's date with an hour already gone is
    just as much in the past, and would otherwise sit there forever,
    confirmed and never firing (nothing after it is ever due again)."""
    datum = str(datum or "").strip()
    if not _DATUM_MUSTER.match(datum):
        raise CronjobVerboten("'date' must be 'YYYY-MM-DD'.", schluessel="cronjob_refusal.date_format")
    try:
        tag = _Datum.fromisoformat(datum)
    except ValueError as fehler:
        raise CronjobVerboten("'date' must be 'YYYY-MM-DD'.", schluessel="cronjob_refusal.date_format") from fehler
    stunde, minute = (int(teil) for teil in zeit.split(":"))
    if _Datetime(tag.year, tag.month, tag.day, stunde, minute) < _jetzt(zeitzone):
        raise CronjobVerboten("'date' is in the past.", schluessel="cronjob_refusal.date_past")
    return datum


def _haeufigkeit(zeitplan: str, einmalig: bool) -> str:
    """How often this entry comes due, in one word for the caller. An
    instant fires once whether or not ``once`` is set — it names a single
    moment — and a cron expression is anything but daily, so calling either
    of them 'daily' would be a plain untruth in the tool's own answer."""
    if einmalig or _sorte(zeitplan) == terminplan.SORTE_ZEITPUNKT:
        return "once"
    if _ist_taeglich(zeitplan):
        return "daily"
    return "recurring"


def _zielsatz(eintrag) -> str:
    """What the caller is told about this entry's goal, or nothing
    at all for an entry that has none. Spelled out rather than echoed as a
    flag, because "reports only when reached" is the behaviour change the
    caller has to be able to relay to the user in one line."""
    if not eintrag.ziel:
        return ""
    schluss = " and stops" if eintrag.ziel_stilllegen else ""
    return f", reports only when reached{schluss}: {eintrag.ziel!r}"


def _zeitpunkt(eintrag) -> str:
    """The full due moment for a message — just the time for a daily entry
    or a dateless one-off, date and time together once 'date' pins it down."""
    return f"{eintrag.datum} {eintrag.zeitplan}" if eintrag.datum else eintrag.zeitplan


def _holen_erlaubt(cronjob_id: Any, repo, herkunft: str, agent: Any | None):
    """The entry, or a refusal — worded the same whether it does not exist
    at all or simply is not the calling agent's to touch. An agent probing
    ids must not be able to tell the two apart."""
    cronjob_id = str(cronjob_id or "").strip()
    eintrag = repo.holen(cronjob_id) if cronjob_id else None
    # A script entry belongs to no agent, and no agent-originated call ever
    # reaches one — not to edit it, not to pause it, not to learn that it
    # exists. Its ``agent`` column carries a marker no agent file
    # can be called, so the name comparison below would already turn such a
    # call away; this line says it outright instead of leaning on that
    # coincidence, because a coincidence is not a lock.
    kein_skript = eintrag is None or not eintrag.skript
    eigenes = herkunft != "agent" or (
        kein_skript
        and agent is not None
        and eintrag is not None
        and eintrag.agent == agent.name
    )
    if eintrag is None or not eigenes:
        raise CronjobVerboten(f"No entry '{cronjob_id}'.", schluessel="fehler.cronjob_not_found")
    return eintrag


def _erstellen(argumente: dict[str, Any], repo, agenten_orte, herkunft: str, agent: Any | None, zeitzone: str | None, skripte_ordner=None) -> str:
    zeit = _zeit_pruefen(argumente.get("time"), zeitzone)

    # An entry is EITHER a script or an agent with a task, never a mixture.
    #Decided first, because everything below reads differently
    # for the two.
    skript = argumente.get("script")
    sekunden = _sekunden_pruefen(argumente.get("max_seconds"))
    if argumente.get("reminder"):
        # The third kind (app/reminder.py): words and a moment, nothing to run.
        if (
            skript is not None
            or argumente.get("agent") is not None
            or argumente.get("goal") is not None
            or argumente.get("stop_when_reached") is not None
            or sekunden is not None
        ):
            raise CronjobVerboten(_REMINDER_ALONE, schluessel="cronjob_refusal.reminder_alone")
        aufgabe = _aufgabe_bereinigt(argumente.get("task"))
        if not aufgabe:
            raise CronjobVerboten("'task' is empty — nothing to run.", schluessel="cronjob_refusal.task_empty")
        agentname: str | None = reminder.REMINDER_AGENT
        ziel, stilllegen = None, False
    elif skript is None:
        if sekunden is not None:
            raise CronjobVerboten(_SEKUNDEN_NUR_MIT_SKRIPT, schluessel="cronjob_refusal.seconds_only_script")
        aufgabe = _aufgabe_bereinigt(argumente.get("task"))
        if not aufgabe:
            raise CronjobVerboten("'task' is empty — nothing to run.", schluessel="cronjob_refusal.task_empty")

        # Read from disk only where an answer actually depends on it — a call
        # that names no agent has nothing to look up, and loading every agent
        # file for it would be a disk read per call.
        if herkunft == "agent":
            if agent is None:
                raise CronjobVerboten("No agent context for an agent-originated call.")
            agentname = agent.name
        else:
            gewuenscht = str(argumente.get("agent") or "").strip() or None
            if gewuenscht is not None:
                vorhandene = agenten_laden(*agenten_orte)
                # The name as it stands on disk, never as it was typed: two
                # spellings of one agent would otherwise become two entries.
                # Which spellings count as the same is decided once, in
                # app/agenten.py, so this door and the four others a name
                # passes through cannot answer it differently.
                agentname = vorhandene.echter_name(gewuenscht)
                if agentname is None:
                    raise CronjobVerboten(
                        agentenname.unbekannt_text(gewuenscht, vorhandene),
                        schluessel="fehler.agent_nicht_gefunden_beim_start",
                        werte={
                            "name": str(gewuenscht).strip(),
                            "verfuegbar": agentenname.namen_satz(vorhandene),
                        },
                    )
            else:
                agentname = ohne_agent.NAME

        ziel = _ziel_pruefen(argumente.get("goal"))
        stilllegen = bool(argumente.get("stop_when_reached"))
        if stilllegen and not ziel:
            raise CronjobVerboten(_NUR_MIT_ZIEL, schluessel="cronjob_refusal.stop_needs_goal")
    else:
        skript = _skript_pruefen(skript, skripte_ordner, herkunft)
        if argumente.get("task") is not None or argumente.get("agent") is not None:
            raise CronjobVerboten(_SKRIPT_STATT_AGENT, schluessel="cronjob_refusal.script_not_agent")
        if argumente.get("goal") is not None or argumente.get("stop_when_reached") is not None:
            raise CronjobVerboten(_KEIN_ZIEL_FUER_SKRIPT, schluessel="cronjob_refusal.script_no_goal")
        # The task column is NOT NULL and stays empty: a script entry has no
        # sentence a person wrote, and putting the file name in as one would
        # make the interface say the same thing twice.
        aufgabe = ""
        agentname = skriptlauf.SKRIPT_AGENT
        ziel, stilllegen = None, False

    grenze = _grenze_pruefen(argumente.get("max_failures"))
    # A goal entry is a promise to speak up: it says nothing run after run and
    # one thing when the goal is reached, and the confirmation handed back to
    # the caller says exactly that in words. So it carries the announcement
    # without being asked for it — an entry that watches for something and
    # then keeps the answer to itself is the one thing it must not be. Only an
    # explicit no takes it away again.
    #
    # For an entry without a goal 'notify' keeps its own meaning untouched:
    # there it decides whether EVERY run announces, which for anything checked
    # often is a flood nobody reads, so it stays off unless asked for.
    notify = argumente.get("notify")
    ansagen = bool(ziel) if notify is None else bool(notify)
    deliver = DELIVER_ANSAGE if ansagen else DELIVER_LOG
    einmalig = bool(argumente.get("once"))
    datum_arg = argumente.get("date")
    datum = None
    if datum_arg is not None:
        if not einmalig:
            raise CronjobVerboten("'date' only applies to a 'once' entry.", schluessel="cronjob_refusal.date_only_once")
        if not _ist_taeglich(zeit):
            raise CronjobVerboten(_NUR_MIT_TAGESZEIT, schluessel="cronjob_refusal.date_only_daily_time")
        datum = _datum_pruefen(datum_arg, zeit, zeitzone)

    eintrag = repo.erstellen(
        agent=agentname, task=aufgabe, zeitplan=zeit, herkunft=herkunft,
        deliver=deliver, einmalig=einmalig, datum=datum, fehlergrenze=grenze,
        ziel=ziel, ziel_stilllegen=stilllegen, skript=skript, zeitgrenze=sekunden,
    )
    haeufigkeit = _haeufigkeit(eintrag.zeitplan, eintrag.einmalig)
    # With a goal set, ``deliver`` no longer decides anything about an
    # ordinary run (app/cronablauf.py) — saying "announces on end" there
    # would promise the very flood the goal was set to stop.
    meldung = (
        ", announces on end" if deliver == DELIVER_ANSAGE and not ziel else ""
    )
    # Said back only when it was asked for: the default needs no mention,
    # and a number the caller chose does.
    grenzsatz = f", stops after {grenze} failed runs" if grenze is not None else ""
    zielsatz = _zielsatz(eintrag)
    # What runs: the script's name, or the agent's. Said the same way in both
    # cases, so a caller relaying the answer does not have to know which kind
    # of entry it just made.
    wer = f"script {eintrag.skript}" if eintrag.skript else eintrag.agent
    sekundensatz = f", stopped after {sekunden}s" if sekunden is not None else ""
    return f"Created — id {eintrag.id}, {wer} at {_zeitpunkt(eintrag)} {haeufigkeit}{meldung}{grenzsatz}{sekundensatz}{zielsatz}."


def _auflisten(repo, herkunft: str, agent: Any | None) -> str:
    eintraege = repo.auflisten()
    if herkunft == "agent":
        if agent is None:
            raise CronjobVerboten("No agent context for an agent-originated call.")
        eintraege = [e for e in eintraege if e.agent == agent.name]
    if not eintraege:
        return "No scheduled runs."
    return "\n".join(
        f"{e.id} — {'script ' + e.skript if e.skript else e.agent} at "
        f"{_zeitpunkt(e)} {_haeufigkeit(e.zeitplan, e.einmalig)}"
        f"{' (paused)' if not e.aktiv else ''}"
        # A script entry has no task text — its name IS what it does, and it
        # already stands two words earlier.
        + ("" if e.skript else f", task: {e.task!r}")
        for e in eintraege
    )


def _entfernen(argumente: dict[str, Any], repo, herkunft: str, agent: Any | None) -> str:
    eintrag = _holen_erlaubt(argumente.get("id"), repo, herkunft, agent)
    repo.loeschen(eintrag.id)
    return f"Removed — id {eintrag.id}."


def _umschalten(argumente: dict[str, Any], repo, herkunft: str, agent: Any | None, *, aktiv: bool) -> str:
    eintrag = _holen_erlaubt(argumente.get("id"), repo, herkunft, agent)
    repo.aktiv_setzen(eintrag.id, aktiv)
    return f"{'Resumed' if aktiv else 'Paused'} — id {eintrag.id}."


def _aktualisieren(argumente: dict[str, Any], repo, agenten_orte, herkunft: str, agent: Any | None, zeitzone: str | None, skripte_ordner=None) -> str:
    eintrag = _holen_erlaubt(argumente.get("id"), repo, herkunft, agent)

    # The two kinds stay apart after creation too: a script entry
    # never grows an agent, a task or a goal, and an agent's schedule never
    # turns into a script. Anything else would leave a row that is half of
    # each — and the half the firing loop reads first decides what runs.
    skript = argumente.get("script")
    if skript is not None:
        # The chat-only lock is asked inside, before the file is looked at.
        skript = _skript_pruefen(skript, skripte_ordner, herkunft)
        if not eintrag.skript:
            raise CronjobVerboten(_SKRIPT_NUR_TAUSCHEN, schluessel="cronjob_refusal.script_only_swap")
    sekunden = _sekunden_pruefen(argumente.get("max_seconds"))
    if reminder.is_reminder(eintrag):
        # A reminder keeps being one: its text may change, never into a run.
        if (
            argumente.get("agent") is not None
            or argumente.get("goal") is not None
            or argumente.get("stop_when_reached") is not None
            or sekunden is not None
        ):
            raise CronjobVerboten(_REMINDER_ALONE, schluessel="cronjob_refusal.reminder_alone")
    if eintrag.skript:
        if argumente.get("task") is not None or argumente.get("agent") is not None:
            raise CronjobVerboten(_SKRIPT_STATT_AGENT, schluessel="cronjob_refusal.script_not_agent")
        if argumente.get("goal") is not None or argumente.get("stop_when_reached") is not None:
            raise CronjobVerboten(_KEIN_ZIEL_FUER_SKRIPT, schluessel="cronjob_refusal.script_no_goal")
    elif sekunden is not None:
        raise CronjobVerboten(_SEKUNDEN_NUR_MIT_SKRIPT, schluessel="cronjob_refusal.seconds_only_script")

    once = argumente.get("once")
    einmalig = None if once is None else bool(once)
    # Turning 'once' back off must take a dated entry's fixed day down with
    # it — left behind, cronablauf.py would still be pinned to that single
    # past day forever, no matter what this response claims.
    datum_loeschen = einmalig is False

    zeit = argumente.get("time")
    if zeit is not None:
        zeit = _zeit_pruefen(zeit, zeitzone)
        behaelt_datum = eintrag.datum is not None and not datum_loeschen
        if behaelt_datum and not _ist_taeglich(zeit):
            # The entry keeps its pinned day, so the new schedule has to be
            # the shape a separate day belongs to. Turning 'once' off in the
            # same call clears the day and lifts this.
            raise CronjobVerboten(_NUR_MIT_TAGESZEIT, schluessel="cronjob_refusal.date_only_daily_time")
        if behaelt_datum and argumente.get("date") is None:
            # Left unchecked against an already-set 'datum', a bare 'time'
            # change reopens exactly the past-moment hole _datum_pruefen
            # closes at creation. Only the OLD datum
            # needs this guard — a 'date' arriving in the same call replaces
            # it outright and is checked against the new moment below.
            _datum_pruefen(eintrag.datum, zeit, zeitzone)

    datum_arg = argumente.get("date")
    datum = None
    if datum_arg is not None:
        if datum_loeschen:
            raise CronjobVerboten(
                "'date' and turning 'once' off in the same call contradict each other.",
                schluessel="cronjob_refusal.date_and_not_once",
            )
        # The schema's rule (datum only ever together with einmalig) has to
        # hold after this call too — not just for a freshly created entry,
        # so an entry left daily can't come out with a date the row itself
        # forbids.
        wird_einmalig = eintrag.einmalig if einmalig is None else einmalig
        if not wird_einmalig:
            raise CronjobVerboten(
                "'date' only applies to a 'once' entry — this one fires daily.",
                schluessel="cronjob_refusal.date_only_once",
            )
        wirksame_zeit = zeit if zeit is not None else eintrag.zeitplan
        if not _ist_taeglich(wirksame_zeit):
            raise CronjobVerboten(_NUR_MIT_TAGESZEIT, schluessel="cronjob_refusal.date_only_daily_time")
        datum = _datum_pruefen(datum_arg, wirksame_zeit, zeitzone)

    aufgabe = argumente.get("task")
    if aufgabe is not None:
        aufgabe = _aufgabe_bereinigt(aufgabe)
        if not aufgabe:
            raise CronjobVerboten("'task' is empty — nothing to run.", schluessel="cronjob_refusal.task_empty")

    neuer_agent = argumente.get("agent")
    # Same as in ``_erstellen``: from disk only where it is actually needed.
    if neuer_agent is not None:
        if herkunft == "agent":
            raise CronjobVerboten("An agent's own call cannot reassign 'agent'.")
        # Same rule as on create, and it is the same rule: an entry moved to
        # `Recherche` lands on the one agent, not beside it.
        vorhandene = agenten_laden(*agenten_orte)
        aufgeloest = vorhandene.echter_name(neuer_agent)
        if aufgeloest is None:
            raise CronjobVerboten(
                agentenname.unbekannt_text(neuer_agent, vorhandene),
                schluessel="fehler.agent_nicht_gefunden_beim_start",
                werte={
                    "name": str(neuer_agent).strip(),
                    "verfuegbar": agentenname.namen_satz(vorhandene),
                },
            )
        neuer_agent = aufgeloest

    notify = argumente.get("notify")
    deliver = None
    if notify is not None:
        deliver = DELIVER_ANSAGE if notify else DELIVER_LOG

    grenze = _grenze_pruefen(argumente.get("max_failures"))

    ziel = _ziel_pruefen(argumente.get("goal"))
    # An empty 'goal' is the caller saying "drop it" — the same shape the
    # empty string has everywhere else in this tool, and the only way to
    # take a goal back off an entry.
    ziel_loeschen = argumente.get("goal") is not None and not ziel
    stilllegen = argumente.get("stop_when_reached")
    stilllegen = None if stilllegen is None else bool(stilllegen)
    # What this entry's goal will be once this call is through — the check
    # below has to hold AFTER the update, not merely for an entry that
    # already looked right before it.
    ziel_danach = None if ziel_loeschen else (ziel or eintrag.ziel)
    if stilllegen and not ziel_danach:
        raise CronjobVerboten(_NUR_MIT_ZIEL, schluessel="cronjob_refusal.stop_needs_goal")

    eintrag = repo.aktualisieren(
        eintrag.id, agent=neuer_agent, task=aufgabe, zeitplan=zeit, deliver=deliver,
        einmalig=einmalig, datum=datum, datum_loeschen=datum_loeschen,
        fehlergrenze=grenze, ziel=ziel or None, ziel_loeschen=ziel_loeschen,
        ziel_stilllegen=stilllegen, skript=skript, zeitgrenze=sekunden,
    )
    haeufigkeit = _haeufigkeit(eintrag.zeitplan, eintrag.einmalig)
    # A fired one-off deactivates itself (app/cronablauf.py) rather than
    # being deleted — moving its date forward changes what it says, not
    # whether it will fire. Silent here, the caller has every reason to
    # believe the reschedule alone brings it back.
    #
    # Narrowed to that exact case on purpose: a chain entry going inactive
    # (``basisaufgabe`` set — app/zwischenstand.py, app/api/v1/auftraege.py)
    # is a deliberately engaged brake, not a stalled one-off, and pointing
    # at 'resume' there would advise lifting it.
    gefeuerter_einmaltermin = eintrag.einmalig and not eintrag.basisaufgabe
    hinweis = (
        " — still paused, call resume to arm it"
        if not eintrag.aktiv and gefeuerter_einmaltermin
        else ""
    )
    grenzsatz = f", stops after {grenze} failed runs" if grenze is not None else ""
    skriptsatz = f", runs {eintrag.skript}" if skript is not None else ""
    sekundensatz = f", stopped after {sekunden}s" if sekunden is not None else ""
    zielsatz = " — goal removed, reports after every run" if ziel_loeschen else _zielsatz(eintrag)
    return f"Updated — id {eintrag.id}, now {haeufigkeit}{grenzsatz}{skriptsatz}{sekundensatz}{zielsatz}{hinweis}."


async def ausfuehren(
    argumente: dict[str, Any],
    repo,
    agenten_orte,
    *,
    herkunft: str = "chat",
    agent: Any | None = None,
    zeitzone: str | None = None,
    skripte_ordner=None,
) -> str:
    """One call to the tool.

    ``skripte_ordner`` is a callable that answers "where do the scripts live
    right now" — a callable and not a path, because the folder can
    be moved from the interface while the service runs, and a path taken once
    at startup would have this checking a creation against a folder that is
    no longer the one the firing loop reads. ``None`` means this service has
    no scripts folder at all, and ``script`` is refused outright.
    """
    aktion = str(argumente.get("action") or "").strip()
    if aktion not in AKTIONEN:
        raise CronjobVerboten(
            f"Unknown action '{aktion}'. Use one of: {', '.join(AKTIONEN)}."
        )
    if aktion == "create":
        return _erstellen(
            argumente, repo, agenten_orte, herkunft, agent, zeitzone, skripte_ordner
        )
    if aktion == "list":
        return _auflisten(repo, herkunft, agent)
    if aktion == "remove":
        return _entfernen(argumente, repo, herkunft, agent)
    if aktion == "pause":
        return _umschalten(argumente, repo, herkunft, agent, aktiv=False)
    if aktion == "resume":
        return _umschalten(argumente, repo, herkunft, agent, aktiv=True)
    return _aktualisieren(
        argumente, repo, agenten_orte, herkunft, agent, zeitzone, skripte_ordner
    )
