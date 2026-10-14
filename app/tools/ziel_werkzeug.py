"""The goal tool — `goal`.

A goal is not read out of prose. The model says it plainly, by calling this
tool, and the call carries WHAT is being reported — so the user does not get
"goal reached" but the thing itself: the sender and the subject, the number,
the path.

Three decisions worth naming, because each was made against something:

* **It works everywhere, not only in a scheduled run.** Any conversation can
  be given a task that can be finished, and "we are done, and here is why"
  is worth saying in a chat exactly as much as at three in the morning. A
  cron-only tool would have been a second mechanism for the same sentence.
* **The model reports on itself — there is no checker.** This is the simple
  build, chosen deliberately and first. A second build (an independent run
  that judges the answer against the goal) can later be set up NEXT to this
  one without changing the field or the tool: the goal stays free text on
  the entry, and this call stays the one door a report comes through.
* **The proof belongs in the report, not in a second required field.** A
  good goal names what makes it recognisable — "an unread mail from Müller
  in the inbox, name the sender and the subject" rather than "mail from
  Müller is there". Teaching that in the description costs nothing and
  survives the switch to the checking build, because no goal has to be
  rewritten for it.

The report is announced the same way a finished schedule is
(``app/cronmeldung.py``): a sound and a system notification — and, since
02.09., through the same one gate as well (``app/cronablauf.mitteilen``), so
that a schedule set to ``deliver = 'log'`` is quiet here too. In a chat there
is no entry to ask, and there the report announces itself as it always did.
Wiring it to a cron entry — a goal per entry, announcing only when it is met
— is a separate step and deliberately not here.
"""

from __future__ import annotations

import asyncio
import logging
import unicodedata
from typing import Any

from app import cronmeldung
from app.tools.mcp_client import MCPWerkzeug

log = logging.getLogger(__name__)

SERVER_NAME = "goal"
WERKZEUG_NAME = "goal"

# Long enough for a sentence that names its own evidence, short enough that
# nobody delivers a report as a document — the text is shown as a system
# notification, which cuts anything longer off anyway.
MAX_LAENGE = 500

# Newline and tab are the only control characters a report can legitimately
# carry. The rest of the "invisible" Unicode categories are either a
# formatting trick (zero-width joiners, direction overrides, a BOM) or a
# control code with no business in a stored text. Deliberately the same rule
# as the schedule's task text (``app/tools/cronjob.py``, ``_bereinigt``) and
# for the same reason: a page the model read could otherwise plant something
# nobody would ever see. WHOEVER CHANGES ONE READS THE OTHER.
_STEUERZEICHEN_ERLAUBT = {"\n", "\t"}
_UNSICHTBARE_KATEGORIEN = {"Cf", "Cc", "Co", "Cs"}

# What the model is told once the report is out. It says "you can stop here"
# on purpose: without it a model that has just reported keeps working on a
# task it has itself declared finished.
GEMELDET = "Goal completion reported. You can stop here."

# And what it is told when it calls a second time in the same run.
#One run announces once: a report is a sound and a
# system notification, and three of them for one finding is the very flood a
# goal exists to prevent. The description already says "call it once" — this
# is what happens when it is not followed, and it is a refusal rather than a
# silent swallow so the model can see that nothing went out.
SCHON_GEMELDET = (
    "Goal completion has already been reported in this run, and the user has been notified. "
    "This call sent no notification; each run reports only once. Any additional information "
    "should have been included in the first report."
)


class ZielVerboten(Exception):
    """The call cannot be reported in this shape — nothing was announced."""


def werkzeug_beschreibung() -> MCPWerkzeug:
    return MCPWerkzeug(
        name=WERKZEUG_NAME,
        beschreibung=(
            "Reports that a goal you were given has been reached. Call it "
            "once, when the thing you were asked to watch for or to achieve "
            "has actually happened — the user is told immediately, and you "
            "can stop.\n"
            "The report IS the message the user gets, so write what was "
            "found, not that something was found: name the evidence — the "
            "sender and the subject, the measured number, the path of the "
            "file, the line that changed. 'Goal reached' on its own tells "
            "nobody anything.\n"
            "Do not call it for a goal that is not met yet, and do not call "
            "it to announce progress. If nothing happened, finish quietly."
        ),
        schema={
            "type": "object",
            "properties": {
                "report": {
                    "type": "string",
                    "description": (
                        "Describe what was achieved in the user's language, including "
                        f"evidence, in no more than {MAX_LAENGE} characters."
                    ),
                },
            },
            "required": ["report"],
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


def bericht(argumente: dict[str, Any]) -> str:
    """The report as it may be shown, or a refusal.

    Public because two places need the very same text and must not each
    clean it their own way: the execution below, and the run that puts the
    finished mark into the stream (``app/api/v1/generierung.py``).

    Refuses rather than trims, like the memory tool: a model that got a
    thousand characters through would learn that a thousand is fine, and the
    notification would show the first line of it.
    """
    text = _bereinigt(str(argumente.get("report") or ""))
    if not text:
        raise ZielVerboten(
            "No report provided. State what was achieved and how it can be verified. This "
            "text is shown to the user."
        )
    if len(text) > MAX_LAENGE:
        raise ZielVerboten(
            f"The report is too long ({len(text)} characters; maximum: {MAX_LAENGE}). Provide "
            "a single sentence stating the result and its evidence, not a document."
        )
    return text


async def ausfuehren(
    argumente: dict[str, Any], *, schon_gemeldet: bool = False,
    cronjobs_repo: Any | None = None, cronjob_id: str | None = None,
) -> str:
    """Announces the report. Returns what the model is told about it.

    ``schon_gemeldet`` is whether this run already got a report out. The
    caller holds that answer, not this module: it belongs to one run, and a
    process-wide memory of which runs have reported would be state that
    outlives the thing it describes. Checked before the report itself is
    read — the reason this call is refused is that it is the second one,
    whatever it happens to carry.

    ``cronjob_id`` and ``cronjobs_repo`` say WHERE this call is running, and
    they come from the caller for the same reason every other such value does
    (``app/tools/registry.py``): a run's own schedule may not be something
    the model's arguments can name.

    Both are how ``deliver = 'log'`` finally reaches this report too (02.09.).
    Six notifications pass the one gate in ``app/cronablauf.py``; this was the
    seventh and passed none of them, so an entry that asked to be quiet still
    rang and still played a sound the moment its run reported a goal.

    The gate alone cannot decide it, and that is why the branch is here rather
    than there: a goal is reported in a chat exactly as much as at three in
    the morning (see the module note above), and a chat has no entry at all.
    The gate reads "no entry" as "silent" — right for a schedule, wrong for
    everywhere else. So the entry is looked up only when there IS one, and
    without one the report is announced the way it always was. Not a second
    reading of ``deliver``: that question is asked once, in the gate.
    """
    if schon_gemeldet:
        raise ZielVerboten(SCHON_GEMELDET)
    text = bericht(argumente)
    log.info(
        "Goal reported: %s", text,
        extra={"ereignis": "ziel_gemeldet", "bericht": text},
    )
    if cronjob_id and cronjobs_repo is not None:
        # Imported here, not at the top: app/cronablauf.py imports THIS
        # module, and the other direction would close the circle. The same
        # way app/api/v1/generierung.py reaches auftrag_anstossen.
        from app import cronablauf

        # A deleted entry falls to silent, which is what the gate already
        # says about a row that is gone: there is nothing left to speak for.
        await cronablauf.mitteilen(
            cronjobs_repo.holen(cronjob_id), text, erfolgreich=True
        )
        return GEMELDET
    # Blocking (a subprocess for the sound, one for the notification), so it
    # goes off the event loop — the same way the schedule's own announcement
    # is called.
    await asyncio.to_thread(cronmeldung.melden, text, erfolgreich=True)
    return GEMELDET
