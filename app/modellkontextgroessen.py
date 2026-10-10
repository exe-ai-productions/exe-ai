"""Context window sizes for models that will not report their own.

A local server is asked directly (``Provider.kontextgroesse`` — llama.cpp
answers via ``/props``, for instance), and Anthropic's model list now names
``max_input_tokens`` per model, which is asked before this table is ever
consulted. What is left for the table is the rest: a pinned snapshot the
provider no longer lists, and every OpenAI-compatible service whose model
list carries no size at all. Kept in its own module so it stays a one-line
edit rather than a change buried in provider code.

The entry for Claude is the OLD generation's 200,000 and stays that number.
Raising it to the million the current models have would only swap one guess
for another: the substring matches both generations, and the models that
really have a million are exactly the ones the list already answers for.

Looked up by substring rather than the full model id: a vendor ships several
dated snapshots of the same family (``claude-sonnet-5``,
``claude-sonnet-5-20260101``, ...), and pinning every one by hand would fall
out of date the day a new snapshot ships.

Asked only for a best-effort guess. A model not listed here yields ``None``
— the caller (``app/fenstergroesse.py``) falls through to its own fallback
rather than treating a gap in this table as "no window at all".
"""

from __future__ import annotations

# Substring in the (lowercased) model id -> context window in tokens.
BEKANNTE_MODELLE: tuple[tuple[str, int], ...] = (
    ("claude", 200_000),
)


def nachschlagen(modellname: str | None) -> int | None:
    """The known context size for this model, or ``None`` if it is not listed."""
    if not modellname:
        return None
    name = modellname.lower()
    for teilstring, groesse in BEKANNTE_MODELLE:
        if teilstring in name:
            return groesse
    return None
