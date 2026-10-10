"""How much thinking fits beside an answer of a given length.

One provider counts the thinking trace against the same ceiling the visible
answer is written under: on the Anthropic wire ``thinking.budget_tokens``
comes out of ``max_tokens``, and the API refuses a budget that is not
smaller than that ceiling. Handing it the ceiling less one satisfies the
API and starves the answer — the model thinks until the ceiling is spent
and the reply that was asked for never gets written.

So the split lives here, once, and it answers exactly one question: given a
ceiling and the budget a stage would like, what may go out? Two callers ask
it — the switch that builds a fresh request and the one that rebuilds an
existing one under a lowered ceiling (``app/denkschalter.py``) — and they
have to agree, because a request travels through both.

Whether the answer is large enough to send at all is the provider's rule,
not this arithmetic: a result below ``denkschalter.MINDEST_BUDGET`` means
the request goes out with no thinking pass rather than being refused.
"""

from __future__ import annotations

# What the visible answer keeps for itself, whatever the thinking wants.
# The ceiling is not raised to make that room: it is bound to the room the
# context actually leaves, and raising it would loop — too large a ceiling,
# a refusal, a lowering, a raise again. So the budget gives way, and the
# answer keeps a fixed floor beside a trace of any size.
ANTWORT_RESERVE = 4096

# What `on` asks for where a model reads a budget rather than a depth: the
# middle of the scale, the same budget as `medium` in :data:`STUFENBUDGETS`.
# The three models this concerns know only `off` and `on` by DEFAULT
# here (`app/daten/denkstufen.yaml`) — a hand entry or a capability block can
# offer them a full scale instead, see :data:`STUFENBUDGETS` for that case.
# It lives in code rather than in the catalogue because the catalogue
# already says the translation takes it from a module constant — one place,
# not two.
STUFENBUDGET = 8000

# What a chosen stage asks for, where a model reads a budget rather than a
# depth and offers more than `off`/`on` — a hand entry or a capability block
# can put `app/daten/denkstufen.yaml`'s own `off`/`on` row aside the same way
# any other model's stage list can. A stage without a row here falls back to
# :data:`STUFENBUDGET`, which keeps `on` and every stage this table does not
# name at that middle budget. `low` to `xhigh` double from one stage to the
# next; `minimal` and `max` are Anthropic's floor and ceiling for a manual
# budget (platform.claude.com/docs/en/build-with-claude/extended-thinking).
STUFENBUDGETS = {
    "minimal": 1024,
    "low": 4000,
    "medium": 8000,
    "high": 16000,
    "xhigh": 32000,
    "max": 32000,
}


def teilen(wunsch: int, max_tokens: int | None) -> int:
    """The thinking budget that may go out beside an answer capped at
    ``max_tokens``, given the ``wunsch`` this stage would like.

    ``min`` of the two, so it is **never upwards**: a request carrying a
    deliberately small budget keeps it when the ceiling is large, and a
    budget worked out for a larger ceiling shrinks when that ceiling does.

    No ceiling at all reads as no room. The result is then far below what
    the provider accepts, which is the same answer as "no thinking here" —
    the caller's existing floor catches it without a second branch.

    The result can be zero or negative where the ceiling is smaller than the
    reserve; that is not a number to send, and no caller sends it. It is
    left as it is so the caller can say in its log how much room there
    actually was.
    """
    return min(wunsch, (max_tokens or 0) - ANTWORT_RESERVE)
