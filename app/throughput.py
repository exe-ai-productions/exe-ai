"""Tokens per second of the servers this program runs, read from their own counters.

Every llama-server started here carries ``--metrics`` (``Modellrunner.befehl``),
so ``GET /metrics`` answers with two counters that run from the start of the
server: ``llamacpp:tokens_predicted_total`` and
``llamacpp:tokens_predicted_seconds_total`` (the compute time of those tokens
only, idle time does not count). The average the server reports itself is a
mean since its last reset and cannot show a course, so the program reads the
two counters every few seconds and keeps the last five minutes of readings in
memory — nothing is stored, and a restart of the service starts the course
over.

From the readings:

* ``now`` — tokens over compute time of the latest stretch in which tokens
  were made, if that stretch is not older than the window;
* ``average`` — tokens over compute time across the whole window;
* ``history`` — the same rate for each of the last 30 slices of two seconds,
  0 where no token was made.

A counter that starts again at 0 (the server was restarted) ends the series:
no negative number, the readings begin anew. A server that is not running is
not asked, and a series without a single token in the window answers nothing
at all rather than an invented 0.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import threading
import time
from dataclasses import dataclass

import httpx

from app.modellrunner import Lauf

log = logging.getLogger(__name__)

# How often a running server is read.
INTERVAL_S = 2.0
# How much of the past a reading is kept for, and what the average spans.
WINDOW_S = 300.0
# The course shown beside the figures: 30 slices of two seconds.
SLICE_S = 2.0
SLICES = 30
# A server on this machine answers at once or not at all.
TIMEOUT_S = 1.5

# The runners of the program that take part, by the name the route uses and
# the attribute that holds the runner (app/main.py).
RUNNERS = {
    "model": "modellrunner",
    "agent": "agentenrunner",
    "cleanup": "sprachputzrunner",
    "speech": "sprachrunner",
}

_TOKENS = "llamacpp:tokens_predicted_total"
_SECONDS = "llamacpp:tokens_predicted_seconds_total"
_LINE = re.compile(r"^([A-Za-z_:][A-Za-z0-9_:]*)(?:\{[^}]*\})?\s+(\S+)")


def parse_counters(text: str) -> tuple[float, float] | None:
    """The two counters out of the server's ``/metrics`` text, or None when
    either is missing or unreadable."""
    found: dict[str, float] = {}
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        match = _LINE.match(line)
        if match is None or match.group(1) not in (_TOKENS, _SECONDS):
            continue
        try:
            found[match.group(1)] = float(match.group(2))
        except ValueError:
            return None
    if _TOKENS not in found or _SECONDS not in found:
        return None
    return found[_TOKENS], found[_SECONDS]


@dataclass(frozen=True)
class Reading:
    at: float
    tokens: float
    seconds: float


class Series:
    """The readings of one running server and what is told from them."""

    def __init__(self) -> None:
        self._readings: list[Reading] = []
        # The reading round writes on its own thread while a request reads:
        # a request must never see a list that is half cut.
        self._lock = threading.Lock()

    def add(self, at: float, tokens: float, seconds: float) -> None:
        """One reading of the two counters at the time ``at``."""
        with self._lock:
            last = self._readings[-1] if self._readings else None
            if last is not None and (tokens < last.tokens or seconds < last.seconds):
                # The counters began again: what was read before belongs to
                # another run of the server.
                self._readings.clear()
            self._readings.append(Reading(at, tokens, seconds))
            edge = at - WINDOW_S
            # One reading older than the window stays: it is the start of the
            # first stretch that lies inside it.
            while len(self._readings) > 1 and self._readings[1].at < edge:
                del self._readings[0]

    def clear(self) -> None:
        with self._lock:
            self._readings.clear()

    def _stretches(self, now: float) -> list[tuple[float, float, float, float]]:
        """(start time, end time, token delta, compute seconds delta) of each
        stretch between two readings that ends inside the window."""
        edge = now - WINDOW_S
        with self._lock:
            readings = list(self._readings)
        out = []
        for before, after in zip(readings, readings[1:], strict=False):
            if after.at < edge:
                continue
            out.append((before.at, after.at, after.tokens - before.tokens,
                        after.seconds - before.seconds))
        return out

    def figures(self, now: float) -> dict | None:
        """``now``, ``average`` and ``history`` as of the time ``now``, or
        None when no stretch inside the window made a token."""
        stretches = self._stretches(now)
        made = [s for s in stretches if s[2] > 0 and s[3] > 0]
        if not made:
            return None
        newest = made[-1]
        total_tokens = sum(s[2] for s in made)
        total_seconds = sum(s[3] for s in made)
        return {
            "now": newest[2] / newest[3],
            "average": total_tokens / total_seconds,
            "history": self._history(made, now),
        }

    @staticmethod
    def _history(made: list[tuple[float, float, float, float]], now: float) -> list[float]:
        """The rate in each of the last ``SLICES`` slices (a slice takes the
        stretches ending after its start and up to its end); the newest
        slice ends at ``now``."""
        first = now - SLICES * SLICE_S
        tokens = [0.0] * SLICES
        seconds = [0.0] * SLICES
        for _start, end, d_tokens, d_seconds in made:
            number = math.ceil((end - first) / SLICE_S) - 1
            if 0 <= number < SLICES:
                tokens[number] += d_tokens
                seconds[number] += d_seconds
        return [t / s if s > 0 else 0.0 for t, s in zip(tokens, seconds, strict=True)]


class Watch:
    """One series per runner, fed by ``sample``."""

    def __init__(self) -> None:
        self._series: dict[str, Series] = {name: Series() for name in RUNNERS}
        # The run each series belongs to: another run is another series.
        self._run: dict[str, Lauf] = {}

    def figures(self, name: str, now: float | None = None) -> dict | None:
        return self._series[name].figures(time.monotonic() if now is None else now)

    def sample(self, app, now: float | None = None) -> None:
        """One round: every running server is read, every other one's series
        is dropped. Blocking (an HTTP read), so the loop runs it off the
        event loop."""
        at = time.monotonic() if now is None else now
        for name, attribute in RUNNERS.items():
            runner = getattr(app.state, attribute, None)
            series = self._series[name]
            run: Lauf | None = runner.lauf() if runner is not None else None
            if runner is None or run is None:
                series.clear()
                self._run.pop(name, None)
                continue
            if self._run.get(name) is not run:
                series.clear()
                self._run[name] = run
            counters = _read(run.port, runner.schluessel)
            if counters is not None:
                series.add(at, *counters)


def _read(port: int, key: str | None) -> tuple[float, float] | None:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        reply = httpx.get(f"http://127.0.0.1:{port}/metrics", headers=headers, timeout=TIMEOUT_S)
    except httpx.HTTPError:
        return None
    if reply.status_code != 200:
        return None
    return parse_counters(reply.text)


async def watch(app, interval: float = INTERVAL_S) -> None:
    """Reads every ``interval`` seconds until cancelled. A failed round is
    logged and the next one goes on. The ``Watch`` itself stands in
    ``app.state.throughput`` from the start of the service, so a request
    never meets a service without one."""
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(app.state.throughput.sample, app)
        except Exception:  # noqa: BLE001 — one failed round must not end the watch
            log.exception("Throughput reading failed")
