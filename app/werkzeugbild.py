"""An image a tool read, on its way to the model.

``read_file`` on a picture has to hand the model the picture, not a paragraph
about it. A tool result cannot carry one: it is a ``tool`` role, and an image
part is only valid on a ``user`` message — on every backend we speak to. So
the picture travels the way an attachment in the chat travels, as a user
message with image parts, placed directly after the results of the round that
read it.

One module for both runs (``app/api/v1/generierung.py`` and
``app/api/v1/auftraege.py``): a chat and a job read files with the same tool,
and the sentence that introduces the picture must not drift between them.

Nothing here decides whether the model can see at all. That is asked before
the tool runs — a model without vision is given no sink, and the tool then
says plainly that it cannot look at the file (``app/tools/datei_lesen.py``).
"""

from __future__ import annotations

import re

from app.providers.base import ChatNachricht

# Said in the user's voice because that is the role the picture rides on, and
# said at all because a bare image part gives the model nothing to hang it on:
# the file name is what the next sentence of the answer has to quote.
EINLEITUNG = (
    "The requested file is an image and is attached here for inspection: {namen}. Describe or "
    "use only what you can actually see."
)

# The tool's own result for such a read (``app/tools/datei_lesen.py``) — said
# here because the sentence is only true while the picture travels with it,
# and the module that hangs the picture on the request is the one that knows
# when that stops being the case. `ANHANG_SATZ` is what the model reads in
# the round the call ran in; :func:`gelesener_bildpfad` is how a later
# reader recognises such a result.
ANHANG_SATZ = (
    "is attached below for THIS response only. Read it again if needed in a later turn. "
    "Describe what you see now so the response preserves the image's relevant information."
)

# What stands in place of that result when a LATER request rebuilds the
# history from the stored rows (``app/verlaufsbau.py``). The picture is not
# in that request: it rode on a message of its own round, and a rebuilt
# history carries the stored text alone. Saying "attached below" there is a
# sentence that was true once and points the model at nothing — so it is
# replaced by the one note the house gives for a picture that is no longer in
# the request, path and all (``app/dokumentablage.py`` ``nachlesehinweis``,
# the same pairing ``app/werkzeugkuerzung.py`` makes for a retired one).
# Nothing is lost: the model is told where the file is and which
# tool reads it back.
NICHT_MEHR_DABEI = (
    "[This call read an image. It was attached only for that response and is not included in "
    "this request.]"
)


# The key a stored tool entry carries when its call handed the model a
# picture: the whole path of that file, written by the run at the moment the
# picture was attached (``app/api/v1/generierung.py``). A later request that
# rebuilds the history attaches a picture again only where this note stands.
# The result's own words are no proof of it: a text file that quotes
# :func:`bildsatz` is somebody's real output, and following its path would
# send a file the model never opened to the provider.
READ_IMAGE_PATH = "read_image_path"


def bildsatz(pfad: str, groesse: int) -> str:
    """The whole result ``read_file`` returns for a picture it attached."""
    return f"'{pfad}' is an image of {groesse:,} bytes and {ANHANG_SATZ}"


# The shape :func:`bildsatz` produces, whole and from end to end, with the
# file it names kept. Recognised by its form rather than by the sentence
# alone: a result that merely QUOTES that sentence — a shell `grep` over this
# source tree, a read of an exported transcript — is somebody's real output
# and must come back untouched.
_BILDSATZ = re.compile(
    r"^'(?P<pfad>.+)' is an image of [\d,]+ bytes and " + re.escape(ANHANG_SATZ) + r"$",
    re.DOTALL,
)


def gelesener_bildpfad(werkzeug: str, ergebnis: object) -> str | None:
    """The picture this stored result announced — or ``None``.

    Both halves of one question: whether the result announced a picture of
    its own round, and which file it was. Asked of the reading tool's results
    only, and of the whole text: a read that was refused — a model without
    eyes, a picture over the size limit, a file named like an image and made
    of something else — answers with a text that says exactly that, and none
    of those may be replaced by a note about a picture that never travelled.

    The path comes out of the RESULT, not out of the call's arguments: the
    result carries the file as it was resolved, while the argument may be
    relative and resolves against the chat's first shared folder — a folder
    the user can reorder or replace, which would send the model to a
    different file. It is also the path a retired picture is named by
    (``app/werkzeugkuerzung.py``), and one picture must not be described two
    ways in one request.
    """
    # Imported here, not above: the reading tool asks this module for the
    # sentence it returns, so a module-level import would close a circle.
    from app.tools import datei_lesen

    if werkzeug != datei_lesen.WERKZEUG_NAME or not isinstance(ergebnis, str):
        return None
    treffer = _BILDSATZ.match(ergebnis)
    return treffer.group("pfad") if treffer else None


def nachricht(
    namen: list[str], bild_urls: list[str], pfade: list[str] | None = None
) -> ChatNachricht | None:
    """The message that carries the pictures of one round — or None.

    ``namen`` are the files they came out of, in the same order, purely so
    the sentence can name them. ``pfade`` are those same files with their
    whole path: they mark this message as one a TOOL filled, and they are
    what the note says to read again once the picture has been retired from
    a long request (``app/werkzeugkuerzung.py``). No pictures, no message: a
    round that read no image must not gain an empty turn.
    """
    if not bild_urls:
        return None
    return ChatNachricht(
        role="user",
        content=EINLEITUNG.format(namen=", ".join(namen) or "unnamed"),
        bild_urls=list(bild_urls),
        werkzeugbilder=list(pfade or namen),
    )
