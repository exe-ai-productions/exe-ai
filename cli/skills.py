"""The skills the service offers, as the list behind a slash shows them,
and ``/skills``: the skills with how they stand, one written, one edited in
the editor of the computer, the switch for offering it automatically, and
a copy of your own reset or deleted.

The list is read once per run, the way the window reads it, and kept: a
service that does not answer leaves it empty and says nothing — the list
behind the slash then holds the commands alone. A skill that has the name
of a command is not in it: the command is the one that runs. After a change
the list is read again, as the window does.
"""

from __future__ import annotations

import threading
from typing import Any

from cli import editor, servers
from cli.client import ServiceError, ServiceUnreachable
from cli.interfaces import Context, Entry


class Skills:
    """The service's skills, read at most once."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx
        self._listed: list[dict[str, Any]] | None = None
        self._lock = threading.Lock()
        self._reading = False

    def listed(self) -> list[dict[str, Any]]:
        """The skills, read from the service on the first call and kept —
        the call waits for the answer."""
        with self._lock:
            if self._listed is not None:
                return self._listed
        found = self._read()
        with self._lock:
            if self._listed is None:
                self._listed = found
            return self._listed

    def known(self) -> list[dict[str, Any]]:
        """The skills as far as they are known, without waiting: before the
        first reading none, and that reading is started on a thread of its
        own, so a screen that asks while the user types is never held up."""
        with self._lock:
            if self._listed is not None:
                return self._listed
            if self._reading:
                return []
            self._reading = True
        threading.Thread(target=self._read_in_background, daemon=True).start()
        return []

    def reload(self) -> None:
        """Reads the list again, after a change of a skill."""
        found = self._read()
        with self._lock:
            self._listed = found

    def _read_in_background(self) -> None:
        self.listed()
        self._ctx.screen.invalidate()

    def _read(self) -> list[dict[str, Any]]:
        try:
            answer = self._ctx.client.get("/skills")
        except (ServiceError, ServiceUnreachable):
            return []
        if not isinstance(answer, list):
            return []
        return [
            entry
            for entry in answer
            if isinstance(entry, dict) and isinstance(entry.get("name"), str) and entry["name"]
        ]

    def find(self, name: str) -> dict[str, Any] | None:
        """The skill of that name, waiting for the list where it is not
        read yet."""
        wanted = name.casefold()
        return next((skill for skill in self.listed() if skill["name"].casefold() == wanted), None)


def matching(
    skills: list[dict[str, Any]], beginning: str, commands: set[str]
) -> list[dict[str, Any]]:
    """The skills whose name holds ``beginning``, those that start with it
    first, the rest in the order the service lists them. A skill that is
    named like a command stands out."""
    wanted = beginning.casefold()
    own = [skill for skill in skills if skill["name"].casefold() not in commands]
    found = [skill for skill in own if wanted in skill["name"].casefold()]
    return sorted(found, key=lambda skill: not skill["name"].casefold().startswith(wanted))


# --- /skills ---------------------------------------------------------------------------------


def run_command(ctx: Context, argument: str, listing: Skills) -> None:
    word = argument.strip()
    if not word:
        _choose(ctx, listing)
    elif word.isdecimal():
        _numbered(ctx, listing, int(word), word)
    else:
        found = _named(_managed(ctx), word.lstrip("/"))
        if found is None:
            ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=word))
        else:
            _menu(ctx, listing, found)


def _managed(ctx: Context) -> list[dict[str, Any]]:
    found = ctx.client.get("/skills/verwaltung")
    listed = [entry for entry in found if isinstance(entry, dict)] if isinstance(found, list) else []
    # The numbers a word behind the command counts into from here on.
    ctx.session.shown_skills = listed
    return listed


def _named(skills: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    wanted = name.casefold()
    return next((skill for skill in skills if str(skill.get("name")).casefold() == wanted), None)


def _state(ctx: Context, skill: dict[str, Any]) -> tuple[str, str]:
    on = bool(skill.get("auto"))
    return ("blue" if on else "muted", ctx.texts.t("status.aktiv" if on else "status.inaktiv"))


def _cells(ctx: Context, skill: dict[str, Any]) -> list[tuple[str, str]]:
    changed = bool(skill.get("mitgeliefert") and skill.get("eigen"))
    return [
        ("text", f"/{skill.get('name')}"),
        ("muted", ctx.texts.t("skills.geaendert") if changed else ""),
        _state(ctx, skill),
    ]


def _description(skill: dict[str, Any]) -> str:
    return " ".join(str(skill.get("beschreibung") or "").split())


def _line(ctx: Context, skill: dict[str, Any]) -> str:
    """The skill as one line: the name, the mark that it is changed, the
    state and the description."""
    parts = [text for _, text in _cells(ctx, skill) if text]
    return "  ".join([*parts, _description(skill)]).rstrip()


def _choose(ctx: Context, listing: Skills) -> None:
    skills = _managed(ctx)
    rows = [Entry(cells=[("text", ctx.texts.t("skills.schreiben"))])]
    # The description is a remark behind the columns: it wraps, where a
    # column of that width would push the names out.
    rows += [Entry(cells=_cells(ctx, skill), note=_description(skill)) for skill in skills]
    picked = ctx.asker.choose(rows)
    if picked is None:
        return
    if picked == 0:
        _write(ctx, listing)
    else:
        _menu(ctx, listing, skills[picked - 1])


def _numbered(ctx: Context, listing: Skills, number: int, word: str) -> None:
    """A number counts into the selection as it was last shown; the skill
    to write is 1."""
    skills = ctx.session.shown_skills
    if skills is None:
        skills = _managed(ctx)
    if number == 1:
        _write(ctx, listing)
    elif 2 <= number <= len(skills) + 1:
        _menu(ctx, listing, skills[number - 2])
    else:
        ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=word))


def _template(ctx: Context) -> str:
    """The file a new skill starts from, the one the window offers."""
    texts = ctx.texts
    return (
        f"---\n{texts.t('skills.template_description')}\nauto: false\n---\n\n"
        f"{texts.t('skills.template_instructions')}\n"
    )


def _write(ctx: Context, listing: Skills) -> None:
    typed = ctx.asker.ask_text(ctx.texts.t("skills.neu_name"))
    name = (typed or "").strip().lstrip("/")
    if not name:
        return
    text = editor.edit(ctx, _template(ctx))
    if text is None:
        return
    try:
        ctx.client.post("/skills", json={"name": name, "inhalt": text})
    except ServiceError as error:
        ctx.renderer.error(error.detail)
        return
    listing.reload()
    ctx.renderer.notice(ctx.texts.t("skills.geschrieben", name=name))


def _menu(ctx: Context, listing: Skills, skill: dict[str, Any]) -> None:
    texts = ctx.texts
    name = str(skill.get("name"))
    actions = [("edit", [("text", texts.t("skills.bearbeiten"))])]
    actions.append(("auto", [("text", texts.t("skills.selbst")), _state(ctx, skill)]))
    # Only a copy of your own can go: a bundled skill comes back in its own
    # version, one you wrote is gone.
    if skill.get("eigen"):
        reset = bool(skill.get("mitgeliefert"))
        actions.append(
            ("remove", [("text", texts.t("skills.zuruecksetzen" if reset else "skills.loeschen"))])
        )
    picked = ctx.asker.choose(
        [Entry(cells=cells) for _, cells in actions], head=_line(ctx, skill)
    )
    if picked is None:
        return
    what = actions[picked][0]
    try:
        if what == "edit":
            _edit(ctx, listing, name)
        elif what == "auto":
            _switch(ctx, listing, skill)
        else:
            _remove(ctx, listing, skill)
    except ServiceError as error:
        ctx.renderer.error(error.detail)


def _edit(ctx: Context, listing: Skills, name: str) -> None:
    file = ctx.client.get(f"/skills/{name}")
    current = file.get("inhalt") if isinstance(file, dict) else None
    text = editor.edit(ctx, current if isinstance(current, str) else "")
    if text is None:
        return
    ctx.client.put(f"/skills/{name}", json={"inhalt": text})
    listing.reload()
    ctx.renderer.notice(ctx.texts.t("skills.geschrieben", name=name))


def _switch(ctx: Context, listing: Skills, skill: dict[str, Any]) -> None:
    changed = ctx.client.patch(
        f"/skills/{skill.get('name')}", json={"auto": not bool(skill.get("auto"))}
    )
    listing.reload()
    if isinstance(changed, dict):
        ctx.renderer.notice(_line(ctx, changed))


def _remove(ctx: Context, listing: Skills, skill: dict[str, Any]) -> None:
    name = str(skill.get("name"))
    reset = bool(skill.get("mitgeliefert"))
    if not reset and not servers.ask(ctx, ctx.texts.t("skills.loeschen_frage", name=name)):
        return
    ctx.client.delete(f"/skills/{name}")
    listing.reload()
    ctx.renderer.notice(ctx.texts.t("skills.zurueckgesetzt" if reset else "skills.geloescht", name=name))
