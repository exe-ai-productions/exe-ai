"""Retry timing for a provider outage mid-run.

A model server dying mid-run used to end the run outright — one
``ProviderFehler``, however transient, cost the whole night's work. This
gives a round several more tries, each waiting longer than the last, before
it gives up and hands the run off the same way a full context does
(app/zwischenstand.py) instead of ending "gescheitert".
"""

from __future__ import annotations

VERSUCHE = 5
# Doubles each time, capped — a dead server is checked on again and again,
# not hammered, and not left for minutes before the first retry either.
GRUNDABSTAND_SEKUNDEN = 5.0
HOECHSTABSTAND_SEKUNDEN = 60.0


def abstand(versuch: int) -> float:
    """How long to wait before retry number ``versuch`` (1-based)."""
    return min(GRUNDABSTAND_SEKUNDEN * (2 ** (versuch - 1)), HOECHSTABSTAND_SEKUNDEN)
