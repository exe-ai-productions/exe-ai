"""Characters per token — the one proxy everything that prices text uses.

There is no tokenizer on this side, so whatever has to know what a request
weighs BEFORE it is sent counts characters and divides. Four per token is
the ordinary rule of thumb for prose and code alike, and it is a PROXY and
nothing more: erring either way costs a little more or a little less room,
never correctness.

The number sits in a module of its own, and this module imports nothing,
because four modules price text with it — the verbatim tail budget
(``app/verdichtung.py``), the pressure on the window ahead of a request
(``app/kontextdruck.py``), the answer's ceiling (``app/antwortgrenze.py``)
and the document budget (``app/dokumentbudget.py``). Kept inside any one of
them it is an import edge from each of the others back into that one, and
that closed a circle: ``verdichtung`` imports ``antwortgrenze`` imports
``kontextdruck``, which read the number back out of a ``verdichtung`` that
was still half built. Importing ``app.verdichtung`` first then failed
outright with an ``ImportError``, which is why a single test file could no
longer be run on its own. A constant that needs no module of the circle to
be reachable cannot close it again.
"""

from __future__ import annotations

import re

# CJK/Hangul/Kana codepoints (~1 token each), counted in one C-level regex
# pass: Hangul Jamo (+Ext-A), CJK radicals/ideographs (+compat), Hangul
# syllables, fullwidth/halfwidth.
_DICHT = re.compile("[\u1100-\u11ff\u2e80-\u9fff\ua960-\ua97f\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]")


def tokens(text: str | None) -> int:
    """What this text weighs, in tokens — measured, not divided.

    CJK, Hangul and Kana count about one token per character; everything
    else is priced by its UTF-8 BYTES, not its characters. The bytes are the
    correction: Cyrillic, Greek and Arabic take two bytes per character and
    therefore cost about two characters per token, where a flat four
    under-counted them by half. Calibrated against cl100k, o200k and
    Qwen2.5; accented Latin barely moves.

    Measured here: a 600-page PDF with 733,678 characters was
    priced at 183,419 tokens by the flat four and refused by the server at
    308,703 — the request went out because the estimate said it fit.

    The ceiling keeps a short text from pricing at zero. ``errors="replace"``
    because a lone surrogate is routine in tool output and must not turn an
    estimate into a raise.
    """
    if not text:
        return 0
    text = str(text)
    if text.isascii():  # a flag check on CPython; ASCII holds no dense CJK
        return (len(text) + 3) // 4
    ohne = _DICHT.sub("", text)
    dicht = len(text) - len(ohne)
    return dicht + ((len(ohne.encode("utf-8", "replace")) + 3) // 4)


# The other direction, and it is a different question: how many CHARACTERS
# of a text still to be written fit into a token budget. There is no text to
# measure yet, so this stays a ratio — the optimistic one on purpose, because
# every user of it CUTS a text to the answer and a cut that is a little too
# generous costs room, while one that is too mean throws content away.
# Whoever has a text in hand asks `tokens()` instead; this is only for a
# budget that has to become a length before the text exists.
ZEICHEN_JE_TOKEN_ROH = 4
