"""A round that wrote no answer text takes no part in the speed.

A round that only calls a tool produces a handful of tokens, and a server
times them in milliseconds: the same few tokens over a few milliseconds is
thousands per second, and added to the speed of the rounds that did write,
it showed "6400 tok/s" under an answer written at 49. The speed of an answer
is the speed of its text.

The round's own counts stay in its stats (the tokens it produced, how long
it ran); only its share in the speed goes, and with it the name of whoever
measured that share.

A run that was stopped is such a round as a whole: what was counted before
the stop is not a stretch anybody timed to its end, so the stored stats of a
stopped answer carry no speed either.
"""

from __future__ import annotations


def without_tempo(round_stats: dict) -> dict:
    """``round_stats`` as a round of a speed that is no one's: no tokens and
    no seconds to put into the sum, no rate of its own, no source."""
    return {
        **round_stats,
        "tempo_tokens": None,
        "tempo_sekunden": None,
        "tokens_pro_sekunde": None,
        "tempo_quelle": None,
    }
