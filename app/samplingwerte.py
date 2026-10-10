"""Sampling values a model refuses, taken out of a request just before it
goes out.

Some models answer a request that carries a sampling value with HTTP 400 —
not because the value is out of range, but because the model does not take
it at all. A setting saved for the endpoint, or a value a caller always sets,
would then fail every request to that model. The value is dropped here and
nothing else changes: the controls in the interface stay as they are, since
they exist per endpoint and not per model.

The rule is keyed on the MODEL NAME, never on the dialect. llama.cpp, mlx and
every other local server speak the OpenAI protocol too, so a rule on the
dialect would reach them; their models do not carry the names below, so they
keep every value without anything being built for them.

* Claude: the list keeps the families that still ACCEPT the values, and every
  other Claude model refuses them. New releases share no naming pattern, so a
  list of the modern ones would go stale and quietly send the next model down
  the old path with values it answers with 400 — the same reasoning the
  thinking levels already follow (``app/daten/denkstufen.yaml``).
* OpenAI's gpt-5 family and the o-series refuse temperature, top_p and both
  penalties; a seed goes through. Measured against the live API with a gpt-5
  model: 400 naming each of the four, 200 for the seed.
* Kimi and Moonshot models manage temperature on the server; it is left out.
* Arcee Trinity Large Thinking runs at a fixed temperature of 0.5.
* A Claude generation whose thinking runs on a manual token budget (rather
  than an effort level) refuses any temperature but 1 while that budget is
  really in the finished body, so the temperature is set to 1 beside that
  budget switch, in the same request.
"""

from __future__ import annotations

import re
from typing import Any

# Claude families that still take temperature, top_p and top_k: the older
# generations with manual thinking, and the 4.6 generation.
CLAUDE_MIT_SAMPLING = (
    "claude-3",
    "claude-opus-4-0", "claude-opus-4.0", "claude-opus-4-1", "claude-opus-4.1",
    "claude-sonnet-4-0", "claude-sonnet-4.0",
    "claude-opus-4-2025", "claude-sonnet-4-2025",
    "claude-opus-4-5", "claude-opus-4.5", "claude-sonnet-4-5", "claude-sonnet-4.5",
    "claude-haiku-4-5", "claude-haiku-4.5",
    "claude-opus-4-6", "claude-opus-4.6", "claude-sonnet-4-6", "claude-sonnet-4.6",
)
CLAUDE_ABGELEHNT = ("temperature", "top_p", "top_k")
OPENAI_ABGELEHNT = ("temperature", "top_p", "presence_penalty", "frequency_penalty")
ARCEE_TEMPERATUR = 0.5
ANTHROPIC_BUDGET_TEMPERATUR = 1

# o1, o3-mini, o4-mini, ... — the letter and a digit at the start of the name.
_O_SERIE = re.compile(r"o\d")
# A Claude model id: "claude-…" on its own, or behind a vendor prefix
# ("anthropic/claude-…", "anthropic.claude-…"). Not the word anywhere in a
# name: local fine-tunes are often named after the model they were distilled
# from ("…-Claude-Opus-Distill"), and those run on a local server that takes
# every value.
_CLAUDE = re.compile(r"(?:^|[/.])claude-")


def bereinigen(koerper: dict[str, Any]) -> None:
    """Takes out of the finished request body what its model refuses, in
    place. A body without a model name is left as it is."""
    modell = str(koerper.get("model") or "").strip().lower()
    # Without a vendor prefix: "moonshotai/kimi-k2" is still a Kimi model.
    kurz = modell.rsplit("/", 1)[-1]
    if _CLAUDE.search(modell) and not any(familie in modell for familie in CLAUDE_MIT_SAMPLING):
        abgelehnt: tuple[str, ...] = CLAUDE_ABGELEHNT
    elif kurz.startswith("gpt-5") or _O_SERIE.match(kurz):
        abgelehnt = OPENAI_ABGELEHNT
    elif kurz == "kimi" or kurz.startswith("kimi-"):
        abgelehnt = ("temperature",)
    else:
        abgelehnt = ()
    for name in abgelehnt:
        koerper.pop(name, None)
    if kurz == "trinity-large-thinking":
        koerper["temperature"] = ARCEE_TEMPERATUR
    # Read from the FINISHED body rather than carried in from the switch
    # that first built it: a retry that lowers the ceiling can turn a
    # manual thinking budget back off (app/denkschalter.py, mit_deckel),
    # and by then this is the one place left that still sees both the
    # model name and the budget's final state together.
    denken = koerper.get("thinking")
    if (
        _CLAUDE.search(modell)
        and isinstance(denken, dict)
        and denken.get("budget_tokens") is not None
    ):
        koerper["temperature"] = ANTHROPIC_BUDGET_TEMPERATUR
