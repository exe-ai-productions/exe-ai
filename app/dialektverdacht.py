"""When an endpoint's configured dialect does not match the server behind it.

The dialect decides which words a request is written in, and the thinking
switch is the place where getting it wrong costs the most: a local MLX server
reads thinking — on, off and a depth alike — only through
``chat_template_kwargs``, and ignores a top-level ``reasoning_effort`` such
as an ``openai`` dialect sends. Measured against a running
server, the same prompt produced a 210-character chain of thought with the
OpenAI wording and none at all with the MLX one. The switch is flipped, the
model goes on thinking, and nothing says so — which is exactly what "a
control that does nothing lies" is written against.

This module answers one question and nothing else: does this endpoint LOOK
like a local MLX or vLLM server that is entered as ``openai``? It changes
nothing. The configuration is the user's file, and a program that corrects
it behind their back is worse than one that shows the mistake.

The rule is deliberately narrow, because a detector that always reports is
worth nothing. Both halves have to hold:

  * the endpoint is on this machine — a cloud provider is never one of these
    servers, whatever else it answers;
  * and it answers something no cloud provider does: a ``/v1/models/status``
    route, or a ``max_model_len`` on its model list entries. Both are
    conventions of the local serving stacks, and OpenAI, Anthropic and the
    rest carry neither.
"""

from __future__ import annotations

from typing import Any

from app.denkstufen import wirt_von

# The dialect that gets mistaken for the others. Anything already entered as
# `mlx` or `llama_cpp` has been thought about, and this module stays quiet.
VERDAECHTIGER_DIALEKT = "openai"

# Names that mean "this machine". A server reached over the network may well
# be an MLX server too, but then it is somebody else's and the address alone
# no longer says so.
# An IPv6 address comes without its brackets: the host is read by
# `wirt_von`, and the parser drops them.
EIGENE_NAMEN = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0"})


def ist_eigene_maschine(base_url: str) -> bool:
    """Whether this address points at the machine the program runs on.

    The host is read the one way the program reads hosts, so an address
    typed without a scheme (`localhost:8080/v1`) names the same machine here
    as it does when the provider is looked up.
    """
    return wirt_von(base_url) in EIGENE_NAMEN


def spuren_lesen(modelliste: Any, statusblatt: Any) -> bool:
    """Whether these two answers carry a local serving stack's fingerprints.

    ``statusblatt`` is whatever ``/v1/models/status`` gave back, ``None``
    where the route did not answer. A shape that route only ever has is
    enough; the number in it does not matter here.
    """
    if isinstance(statusblatt, (dict, list)) and statusblatt:
        return True
    eintraege = (modelliste or {}).get("data") if isinstance(modelliste, dict) else None
    if not isinstance(eintraege, list):
        return False
    return any(
        isinstance(e, dict) and e.get("max_model_len") is not None for e in eintraege
    )


def verdacht(dialekt: str, base_url: str, *, spuren: bool) -> bool:
    """The whole rule, in the order that makes it cheapest to refuse.

    ``spuren`` is the answer of ``spuren_lesen`` — passed in rather than
    fetched, because the discovery already holds both answers and asking a
    second time for them would be a knock nobody needs.
    """
    if (dialekt or "").strip().lower() != VERDAECHTIGER_DIALEKT:
        return False
    if not ist_eigene_maschine(base_url):
        return False
    return spuren
