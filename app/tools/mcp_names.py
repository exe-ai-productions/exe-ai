"""The name a model calls an MCP server's tool by.

Two servers may offer a tool of the same name, and a server may offer one
that a built-in tool already carries (``read_file``). Under its own name
the second would stand beside the first in the offer or be left out, and
which call ran would be a matter of the order the servers started in. The
model is therefore handed ``mcp__<server>__<tool>``, and the server is
called with the name it gave the tool itself.

A character outside letters, digits and the underscore becomes ``_``: the
name has to be one a model API takes as a function name.
"""

from __future__ import annotations

import re

PREFIX = "mcp__"

_INVALID = re.compile(r"[^A-Za-z0-9_]")


def _clean(part: str) -> str:
    return _INVALID.sub("_", part)


def model_name(server: str, tool: str) -> str:
    """What the model calls ``tool`` of ``server`` by."""
    return f"{PREFIX}{_clean(server)}__{_clean(tool)}"
