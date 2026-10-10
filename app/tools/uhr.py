"""The clock tool — `get_current_time`.

The clock used to ride in front of the newest user turn as a SENTENCE, and
only in a run that carried a tool firing at a time of its own. That sentence
named a minute, so it could not be read off the clock again: it had to be
written onto the row it went out with and handed back byte for byte, or the
server read the whole conversation behind it again
(``app/verlaufsbau._clock_sentence``). And it spoke in the user's own voice —
the model read "The current local date and time is …" as part of the request
and answered the clock instead of the question.

A tool has none of that trouble. Nothing about it moves between two
requests, so it can sit in the offer of every run with tools, and the model
asks when it actually needs a time instead of reading a stamp in every
message it has no use for. What stays at the front of the user turn is the
date and the zone (``app/grundprompt.environment_block``): the two things a
run needs even when it never asks, and both stable for a whole day.

What it answers is the shape the reference time server answers
(modelcontextprotocol/servers, ``get_current_time``): the zone's name, the
moment as an ISO 8601 stamp with its offset, and the day of the week.

The clock it reads is the alarm clock's own (``app/wecker.jetzt_in_zone``),
handed to this module as the configured zone. One clock, not two: a run that
works out "in ten minutes" has to land on the same moment the entry fires
at, whatever zone the machine itself stands in. The zone travels WITH the
reading for the same reason a schedule does — a bare wall-clock time is not
enough to compute anything from.
"""

from __future__ import annotations

import json
from typing import Any

from app.tools.mcp_client import MCPWerkzeug
from app.wecker import jetzt_in_zone, zone_name

SERVER_NAME = "clock"
WERKZEUG_NAME = "get_current_time"

# The day names are spelled out rather than read off ``strftime("%A")``: that
# one answers in the machine's own locale, and this text goes to a model that
# reads English everywhere else in the program.
_WEEKDAYS = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)


def werkzeug_beschreibung() -> MCPWerkzeug:
    return MCPWerkzeug(
        name=WERKZEUG_NAME,
        beschreibung=(
            "Reads the current time from this machine's clock, in the time "
            "zone this program is set to: the zone's name, the moment as an "
            "ISO 8601 stamp with its offset, and the day of the week.\n"
            "Nothing else you are given tells the current time of day. Call "
            "this before you work out any time relative to now, and never "
            "invent one.\n"
            "It takes no arguments and changes nothing."
        ),
        # No properties and no required list: the call carries nothing to get
        # wrong. Every other tool here wants something; this one is asked a
        # question with no parts.
        schema={"type": "object", "properties": {}},
        server=SERVER_NAME,
    )


def clock_reading(zeitzone: str | None) -> str:
    """The reading, as the model receives it.

    ``zeitzone`` is the configured zone; empty means the machine's own, the
    same fallback the alarm clock takes. The zone's NAME travels with it
    (``app/wecker.zone_name``) — the name its database gives it, never the
    abbreviation the clock itself reports, because a reading that cannot be
    computed with is no reading.
    """
    moment = jetzt_in_zone(zeitzone)
    return json.dumps(
        {
            "timezone": zone_name(zeitzone),
            "datetime": moment.isoformat(timespec="seconds"),
            "day_of_week": _WEEKDAYS[moment.weekday()],
        },
        ensure_ascii=False,
    )


async def ausfuehren(argumente: dict[str, Any], *, zeitzone: str | None = None) -> str:
    """Reads the clock. ``argumente`` is accepted and ignored on purpose:
    every caller in ``app/tools/registry.py`` hands the model's arguments in
    the same way, and a tool that took none would be the one exception there.
    """
    return clock_reading(zeitzone)
