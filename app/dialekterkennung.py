"""Telling an oMLX server by its own answer, so its thinking switch works.

An endpoint added in the window is entered under the ``openai`` dialect —
the one that fits a cloud provider and anything unknown. An oMLX server
behind such an entry answers every request, but it ignores the
``reasoning_effort`` that dialect writes: the switch is flipped, the model
goes on thinking, and a condensing request spends its whole ceiling on
reasoning nobody reads. Measured against a running server, the same request
took 68 seconds in the OpenAI wording and 5 in the MLX one.

So the discovery asks such an endpoint once, as soon as it answers, for
``/v1/models/status``. An oMLX server answers with one row per model it
holds, each naming the model family out of the model's own ``config.json``
(``config_model_type``) — the very rows the family lookup reads
(``OpenAIKompatiblerProvider.denkquellen``). No cloud provider serves that
route in that shape: a 404, an error page or any other shape leaves the
endpoint as it is.

What the answer changes lives in the running service only. The
configuration is the user's file and is never written from here, and a
dialect somebody set in it (``mlx``, ``llama_cpp``, ``anthropic``) is never
asked about and never overruled. This is the counterpart of
``app/dialektverdacht.py``, which only points at a mismatch: where the
server can be recognised for certain, the program follows it instead.
"""

from __future__ import annotations

from typing import Any, Final

# The dialect that gets the question: the default, and what the window
# writes for every endpoint it adds. Anything else was chosen by somebody.
GEFRAGTER_DIALEKT: Final = "openai"

# What such an endpoint counts as once its answer carries the fingerprint.
ERKANNTER_DIALEKT: Final = "mlx"


def ist_mlx_statusblatt(stand: Any) -> bool:
    """Whether a ``/v1/models/status`` answer has the shape only an oMLX
    server gives it.

    A list of model rows — bare, or wrapped in ``models`` or ``data`` the
    way the family lookup unwraps it — at least one of which names its id
    and its family. A message, a number, an empty list or rows without a
    family are somebody else's answer.
    """
    if isinstance(stand, dict):
        for huelle in ("models", "data"):
            if isinstance(stand.get(huelle), list):
                stand = stand[huelle]
                break
    if not isinstance(stand, list):
        return False
    return any(
        isinstance(zeile, dict)
        and isinstance(zeile.get("id"), str)
        and bool(zeile["id"].strip())
        and isinstance(zeile.get("config_model_type"), str)
        and bool(zeile["config_model_type"].strip())
        for zeile in stand
    )
