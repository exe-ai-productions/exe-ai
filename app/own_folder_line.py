"""The paragraph that names a chat's own folder, kept apart so it can go last.

The path of the chat's own folder carries the chat's id, so it differs in
every new chat. A model server reuses only the beginning two requests have
in common: from the first differing character on, everything is read again.
With the path in the middle of the system message, everything behind it —
notes, skills, limits, the user's own prompt, the memory — was read anew in
each new chat. The paragraph therefore stands at the very end of the message,
and everything before it is the same for every new chat of one user.

The words are the ones the paragraph always had; only its place changed.
"""

from __future__ import annotations

from collections.abc import Sequence

# The chat's own folder is the program's, not a share: it holds the chat's
# uploads, and while nothing is shared it is where the file tools work.
# Named apart, so the model is not told the user shared something they did
# not.
#
# Where nothing is shared it is also the folder a relative path starts from,
# and the sentence that says so stands here, beside the path — with the folder
# last in the message, the first one in the list above is another one (the
# dock), and "the first one" would name the wrong folder.
OWN_FOLDER = """\
This conversation has a folder of its own, where its uploads are kept and \
where you work while nothing is shared:

- {ordner}

Relative paths resolve against this folder."""

OWN_FOLDER_ALSO = """\
This conversation also has a folder of its own, where its uploads are kept:

- {ordner}"""


def shared_folders(
    ordner: Sequence[str],
    own_folder: str | None,
    dock: str | None,
    images: str | None,
) -> list[str]:
    """The folders the user shared: ``ordner`` without the program's own.

    Once each — a folder the user shared that is also the chat's own stands
    in the list twice.
    """
    return list(
        dict.fromkeys(p for p in ordner if p not in (own_folder, dock, images))
    )


def starts_in_own_folder(
    ordner: Sequence[str],
    own_folder: str | None,
    dock: str | None,
    images: str | None,
) -> bool:
    """Whether the chat's own folder is the one a relative path starts from:
    the file tools take the first folder of the run's list, so it has to stand
    there — and the user shared none, whose folders would stand before it.
    """
    return (
        bool(own_folder)
        and list(ordner)[:1] == [own_folder]
        and not shared_folders(ordner, own_folder, dock, images)
    )


def own_folder_line(
    ordner: Sequence[str],
    own_folder: str | None,
    dock: str | None,
    images: str | None,
) -> str:
    """The paragraph naming the chat's own folder, or "" without one.

    Empty when the folder is not among the ``ordner`` the run may reach —
    the prompt names the folders the gate lets through, and no other.
    """
    if not own_folder or own_folder not in ordner:
        return ""
    leads = starts_in_own_folder(ordner, own_folder, dock, images)
    text = OWN_FOLDER if leads else OWN_FOLDER_ALSO
    return text.format(ordner=own_folder)


def with_own_folder_last(
    text: str,
    ordner: Sequence[str],
    own_folder: str | None,
    dock: str | None,
    images: str | None,
) -> str:
    """``text`` with the own folder's paragraph behind it, if there is one."""
    line = own_folder_line(ordner, own_folder, dock, images)
    return f"{text}\n\n{line}" if line else text
