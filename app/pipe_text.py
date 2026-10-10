"""A child process's pipe read as text, piece by piece as it is written.

A text wrapper's ``read(n)`` waits until ``n`` characters have arrived or
the pipe closes. A painter prints one short progress line per step, so a
reader built on it hears only every few steps. The buffered pipe's own
``read1`` hands over what a single read of the pipe returns — whatever has
been written so far — and an incremental decoder keeps a character whole
that two reads split.
"""

from __future__ import annotations

import codecs
import io
import locale
from collections.abc import Iterator
from typing import IO, cast

# The most one read hands over. Less arrives whenever less has been written.
PIECE = 256


def live_text(
    pipe: IO[bytes], encoding: str, *, universal_newlines: bool = False
) -> Iterator[str]:
    """Yield what ``pipe`` carries as text, each piece as soon as the program
    at the other end has written it, until the pipe closes.

    A byte that is no text in ``encoding`` is replaced, never raised.
    ``universal_newlines`` turns every "\\r" and "\\r\\n" into "\\n", as a
    pipe opened in text mode does; without it the text arrives untranslated.
    """
    # "locale" is the name the text layer uses for the platform's own
    # encoding; the codec registry does not know it.
    if encoding == "locale":
        encoding = locale.getencoding()
    decoder: codecs.IncrementalDecoder | io.IncrementalNewlineDecoder
    decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
    if universal_newlines:
        decoder = io.IncrementalNewlineDecoder(decoder, translate=True)
    # The pipes a child process is opened with are buffered readers; the
    # general type they are declared as does not name read1.
    read_piece = cast(io.BufferedIOBase, pipe).read1
    while True:
        raw = read_piece(PIECE)
        text = decoder.decode(raw, final=not raw)
        if text:
            yield text
        if not raw:
            return
