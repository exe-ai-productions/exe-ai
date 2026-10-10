"""One read per document per answer.

A row that carries a document only points at it; the document's text is
read when the row is turned into words for the model. One answer turns
the same rows into words several times — compaction weighs them, the
compaction request is built from them, the prompt is built from them —
and every reading fetched every document's full text from the database
again. Measured on a chat of forty short turns each carrying a 24 KB
document: at least a megabyte of document text read twice per turn, every
turn, once the chat sat above the compaction threshold.

The cache lives for one answer and no longer. It is a context variable,
so it follows the task that is setting the answer up and is invisible to
every other request; a document edited between two answers is read fresh
by the second. Where nothing opened the cache, reads go straight through.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

_cache: ContextVar[dict[str, Any] | None] = ContextVar("dokumentcache", default=None)


@contextmanager
def aktiv() -> Iterator[None]:
    """Opens a cache for the duration of the block."""
    marke = _cache.set({})
    try:
        yield
    finally:
        _cache.reset(marke)


def holen(repositories, kennung: str) -> Any:
    """The document behind ``kennung`` — from the cache while one is open,
    from the repository otherwise. A missing document is cached as missing,
    so a deleted row costs one read too, not one per reading."""
    cache = _cache.get()
    if cache is None:
        return repositories.documents.holen(kennung)
    if kennung not in cache:
        cache[kennung] = repositories.documents.holen(kennung)
    return cache[kennung]
