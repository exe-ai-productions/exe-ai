"""Whether a chat's shared folders are still where they were shared from.

A folder is checked when it is SET (app/arbeitsordnerpruefung.py) and never
again. Move it afterwards — off the desktop onto a disk — and nothing says
so: the file tools reach into nothing, the folder's ``exe.md`` stops being
read, and every ``read_file`` on a document below it fails, each one on its
own, without ever naming the reason they share.

This module is the question and nothing else: given a list of folders, which
of them are gone? It does not search the disk for where a folder went — it
could find the wrong one, and it would be reading in places nobody shared —
and it removes nothing. What happens next is the user's decision, which is
why this answer only travels to the window.
"""

from __future__ import annotations

from pathlib import Path


def fehlende(ordner: list[str]) -> list[str]:
    """Those of ``ordner`` that are no longer a folder on this machine.

    In the order they were shared in, so the window can name them the way the
    user sees them. A path that is now a FILE counts as missing as much as one
    that is nothing at all: a share is a folder or it is not a share.
    """
    return [pfad for pfad in ordner if not Path(pfad).is_dir()]
