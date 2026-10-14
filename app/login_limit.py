"""The brake on wrong passwords.

A service that demands a password stands in a network, and a sign-in that
answers every wrong password at once lets a list of words be tried through.
So failed sign-ins are counted — for all callers together, because an
address is cheap to change — and held to two a minute and twelve an hour.
At a limit the sign-in answers without comparing anything, the right
password included, until the oldest failure counted has left its window. A
right password is never counted.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

# How many failed sign-ins fit into how many seconds. Every line holds.
LIMITS: tuple[tuple[int, float], ...] = ((2, 60.0), (12, 3600.0))


class LimitReached(Exception):
    """A limit is reached: nothing was compared."""


class LoginLimit:
    """Counts the failed sign-ins of one service."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._failures: deque[float] = deque()
        # The route runs in a thread pool: without the lock, attempts sent
        # at once would all be compared before the first failure counts.
        self._lock = threading.Lock()

    def attempt(self, right: Callable[[], bool]) -> bool:
        """What ``right`` says about this attempt, a failure counted — or
        ``LimitReached`` at a limit, with ``right`` never asked."""
        with self._lock:
            now = self._clock()
            longest = max(seconds for _, seconds in LIMITS)
            while self._failures and self._failures[0] <= now - longest:
                self._failures.popleft()
            for count, seconds in LIMITS:
                if sum(moment > now - seconds for moment in self._failures) >= count:
                    raise LimitReached
            if right():
                return True
            self._failures.append(now)
            return False
