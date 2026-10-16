"""The values a picture server starts with for one model, set once.

A picture asks the server for start values of its own (the random source,
the weight type, the VAE format, the prediction type and the switches the
server takes only at its start). The window fills them from what the model's
family starts with (app/image_families.py) and what the user set for the
model itself (app/bildmodellwerte.py), and the draw route checks every one
through the validators of ``app/bildwahlen.py``.

The server's start by hand needs the same values, from the same places and
through the same validators — a server that was started with any other
would load the model once more with the first picture. They are read here,
once, for the one who starts it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app import bildmodellwerte, bildwahlen, image_families


@dataclass(frozen=True)
class ServerStart:
    """The start values of the server for one model, each as the draw route
    hands it to the server."""

    rng: str
    weight_type: str
    vae_format: str
    prediction: str
    # The picture's own switches the family starts with, by their key in
    # app/image_switches.py; the machine's memory block is not among them.
    switches: dict[str, Any] = field(default_factory=dict)


def lesen(repositories, family_name: str, model: str) -> ServerStart:
    """What a picture of ``model`` of this family (empty: not read) starts
    the server with."""
    start = image_families.start_values(family_name, model)
    own = bildmodellwerte.eigene(repositories, model) if model else {}
    return ServerStart(
        rng=bildwahlen.rng_pruefen(start.rng or None),
        # No family and no model names a weight type: the generator takes the
        # file's own, as a picture of the window with "Auto" does.
        weight_type=bildwahlen.weight_type_pruefen(None),
        vae_format=bildwahlen.vae_format_pruefen(start.vae_format),
        prediction=bildwahlen.prediction_pruefen(own.get("prediction")),
        switches=dict(start.switches),
    )
