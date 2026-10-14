"""A server that refuses the answer limit under its old name.

OpenAI's newer chat models take the answer limit only as
``max_completion_tokens`` and answer a request carrying ``max_tokens`` with a
400. Which model that is cannot always be read from its name: a deployment or
an intermediate server may serve one under a name of its own. The request
therefore goes out as it always did, and only a refusal that names the old
field is answered by sending the same request once more under the new name.
"""

from __future__ import annotations

from typing import Any


def refused_max_tokens(status: int, raw_text: str, body: dict[str, Any]) -> bool:
    """Did the server refuse this request because of ``max_tokens``?

    A 400 whose error text names the field, for a body that carries it. The
    new name does not contain the old one as a substring, so a refusal of
    ``max_completion_tokens`` is no reason to send again. A 400 about any
    other field ends the request as before.
    """
    return status == 400 and "max_tokens" in body and "max_tokens" in raw_text


def with_completion_tokens(body: dict[str, Any]) -> dict[str, Any]:
    """The same body with the answer limit under its new name, value kept."""
    renamed = dict(body)
    renamed["max_completion_tokens"] = renamed.pop("max_tokens")
    return renamed
