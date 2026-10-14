"""The cache share of an answer that took several rounds.

Each round of a tool loop reads its whole prompt again, and the server's
cache answers for it alone: the first round of a chat usually reads
everything fresh, the second finds almost all of it standing. The share
under the finished answer used to be the last round's, which sat beside a
waiting time that was the first round's — "70 s to the first character, 99 %
from the cache", two readings of two different rounds.

Here the share is the cached tokens over all the tokens read, summed over
every round that named its cache. A round that named none takes no part:
a zero would claim a miss.
"""

from __future__ import annotations

from typing import Any


def _count(value: Any) -> int | None:
    """A token count off a stats dict, or None where there is none."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def cache_halves(stats: dict) -> tuple[int, int] | None:
    """What one round (or a sum of rounds) read from the cache and what it
    read fresh, or ``None`` where it named no cache.

    The fresh half is the server's own word where it names one (llama.cpp's
    ``prompt_n``); otherwise it is the whole prompt minus the cached part —
    the form an OpenAI-compatible or Anthropic round arrives in, where
    ``prompt_tokens`` is the whole prompt beside the cached count.
    """
    cache = _count(stats.get("cache_tokens"))
    if cache is None:
        return None
    fresh = _count(stats.get("eingelesen_tokens"))
    if fresh is None:
        whole = _count(stats.get("prompt_tokens"))
        if whole is None or whole < cache:
            return None
        fresh = whole - cache
    return cache, fresh


def cache_over_rounds(alt: dict, neu: dict) -> dict:
    """The fields that stand over the summed stats of two rounds: the two
    halves added up, the seconds the fresh half took, and the share of the
    whole. Nothing where neither round named a cache — the stats keep what
    they have.
    """
    # Only a round that named its cache is in the sum — its seconds as well.
    named = [(r, h) for r in (alt, neu) if (h := cache_halves(r)) is not None]
    if not named:
        return {}
    cache = sum(h[0] for _, h in named)
    fresh = sum(h[1] for _, h in named)
    over: dict[str, Any] = {"cache_tokens": cache, "eingelesen_tokens": fresh}
    if cache + fresh:
        over["prompt_cache_percent"] = round(cache * 100 / (cache + fresh))
    seconds = [
        s
        for s in (r.get("einlese_sekunden") for r, _ in named)
        if isinstance(s, (int, float)) and not isinstance(s, bool)
    ]
    if seconds:
        over["einlese_sekunden"] = round(sum(seconds), 3)
    return over
