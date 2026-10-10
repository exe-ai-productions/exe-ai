"""Skills — an instruction handed to the model in the middle of a conversation.

A skill is a folder. ``<name>/SKILL.md`` holds a front matter section between
two ``---`` lines and the instruction after it; anything else in the folder
belongs to the skill and can be pointed at from the instruction:

    ---
    description: Sums this conversation up as a handover
    auto: false            # may the model reach for it on its own?
    ---

    Go through the whole conversation and collect ...

The folder name is the skill's name, and it is what the user types after a
slash — so it is restricted to what can be typed and read back without
guessing: lower case, digits, hyphens.

**A skill is not an agent.** It carries no ``model:`` and no ``tools:``. An
agent is a separate run with its own head; it starts empty and cannot
summarise a conversation it was never part of. A skill is an instruction for
the head that is already here and already knows the conversation. Whatever a
skill is allowed to do is exactly what the chat is allowed to do.

Two places hold skills, and the user's wins:

* the shipped folder next to the program — replaced by every update
* the user's folder next to their prompts — never touched

Editing a shipped skill quietly copies it to the user's folder, so an update
walks past it. That is the same layering the settings use (default → global →
model → chat) and the same the prompt uses (shipped → the user's own): what
the house delivers is the floor, what the user writes lies on top.

A broken skill takes itself out of play and nothing else — like an agent
file, and unlike ``config.yaml``, which stops the service. The service is the
foundation, a skill is a guest.

Read fresh on every use: an edited file takes effect at once, no restart.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

from app import i18n

log = logging.getLogger(__name__)

SKILL_DATEI = "SKILL.md"

BEKANNTE_FELDER = {"description", "auto"}

# What an agent has and a skill deliberately does not. Named separately so the
# warning can say where that belongs instead of just calling it unknown.
AGENTENFELDER = {
    "model", "tools", "folders", "max_rounds", "max_minutes", "max_tokens",
    "reasoning_budget", "schedule",
}

# The name is typed after a slash and read back from a list. Spaces, capitals
# and umlauts all survive on disk and then cannot be typed reliably.
NAME_MUSTER = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# What a fault's kind may look like: it becomes part of a catalogue key
# (``skills.fehler_<kind>``), so anything else is not one.
KIND_MUSTER = re.compile(r"^[a-z_]+$")

# The description of an automatic skill rides in the system prompt of every
# chat that lets the model pick skills. A sentence with a condition in it does not fit into one
# short line — the budget is a thousand characters, the same limit the public
# skill format sets for a description.
# Whitespace is still folded into single spaces (`parse` below), so a
# description written over several lines costs no more than it says.
MAX_BESCHREIBUNG = 1024


def _kopf_zeilenweise(roh: str) -> dict[str, str]:
    """Reads a header that is not valid YAML, one line at a time.

    `Name: Wert` opens a field; a line WITHOUT a colon continues the field
    above it, joined with a single space — that is the shape a description
    takes when it is written over two lines, and the reason this reader
    exists at all. A line without a colon and without a field above it is
    skipped: it carries nothing a field could be given.

    Deliberately not YAML: no quotes are stripped, no comment is cut off, no
    word is turned into a boolean. What stands there is what the field
    carries, and the checks above decide whether that is usable.
    """
    felder: dict[str, str] = {}
    letzter: str | None = None
    for zeile in roh.splitlines():
        if not zeile.strip():
            continue
        name, trenner, wert = zeile.partition(":")
        if trenner:
            letzter = name.strip()
            felder[letzter] = wert.strip()
        elif letzter is not None:
            felder[letzter] = f"{felder[letzter]} {zeile.strip()}".strip()
    return felder


class SkillKaputt(ValueError):
    """This one skill is unusable. The service keeps running.

    It carries the KEY of its sentence and the values to fill in, not a
    finished sentence: two readers ask for two languages. The tool result is
    the model's copy and is English; the editing mask asks for the language
    its window shows (``app/api/v1/skills.py``). ``str()`` answers English,
    so a caller that does not care gets the model's copy — the one nobody
    has to translate.
    """

    def __init__(self, kind: str, **values: object) -> None:
        # A kind that is not an identifier can only come from a REBUILD out
        # of the finished sentence (``type(fehler)(*fehler.args)``, what a
        # copy helper does). It must not become a catalogue key and be
        # printed as one — and it must not throw something no caller catches
        # either: every handler around this class catches ``SkillKaputt``.
        # So it falls back to a sentence of its own that names the original.
        if KIND_MUSTER.fullmatch(kind):
            self.kind, self.values = kind, values
        else:
            self.kind, self.values = "unbekannt", {"grund": str(kind)}
        self.key = f"skills.fehler_{self.kind}"
        super().__init__(self.text(i18n.STANDARDSPRACHE))

    def text(self, language: str) -> str:
        return i18n.t(self.key, language, **self.values)

    def __reduce__(self):
        # Copied or pickled, it is rebuilt from what it carries, not from
        # the finished sentence ValueError keeps as its argument.
        return (_skill_broken, (self.kind, self.values))


def _skill_broken(kind: str, values: dict) -> "SkillKaputt":
    return SkillKaputt(kind, **values)


@dataclass
class Skill:
    name: str
    beschreibung: str
    anleitung: str
    ordner: Path
    # May the model load it without being asked? Costs a line of the system
    # prompt on every request, which is why it is off unless somebody decides
    # otherwise — in the mask, or through the tool, which asks either way.
    auto: bool = False
    # From the user's folder rather than the shipped one. Decides whether
    # editing writes straight through or makes a copy first.
    eigen: bool = False


def skill_aus_text(name: str, text: str, *, ordner: Path, eigen: bool = False) -> Skill:
    """Reads a skill from raw text. Raises ``SkillKaputt`` with a reason.

    Separate from file access so the editing mask can check the same way
    before anything reaches the disk.
    """
    anzeige = f"{name}/{SKILL_DATEI}"

    if not NAME_MUSTER.match(name):
        raise SkillKaputt("name", name=name)

    if not text.startswith("---"):
        raise SkillKaputt("kopfteil", anzeige=anzeige)
    teile = text.split("---", 2)
    if len(teile) < 3:
        raise SkillKaputt("abschluss", anzeige=anzeige)
    _, kopf_roh, anleitung = teile

    try:
        kopf = yaml.safe_load(kopf_roh) or {}
        aus_fallback = False
    except Exception:  # noqa: BLE001 - every way a header fails to build is one broken header
        # A header that is not valid YAML is read line by line instead of
        # being thrown away: a description written over two lines is the
        # ordinary case (a `:` inside the sentence, an unquoted `and`), and
        # a skill nobody can store is worse than one whose header is read a
        # little more simply. From here on the values are TEXT, not YAML —
        # `true` is the word, quotes and a trailing comment stay where they
        # are written. A header
        # nested deeper than the parser's stack goes the same way, and so does
        # a value YAML refuses to build: a date like `2026-13-45` or an
        # `!!int abc` raise ValueError, `!!bool maybe` KeyError,
        # `!!timestamp x` AttributeError — none of them a YAMLError.
        kopf = _kopf_zeilenweise(kopf_roh)
        aus_fallback = True
    if not isinstance(kopf, dict):
        raise SkillKaputt("feldliste", anzeige=anzeige)

    # YAML turns keys like `on`, `yes` or `1` into booleans and numbers, and
    # a set of mixed types cannot be sorted for the warnings below. The
    # names are only ever printed, so they are printed as text.
    verirrt = {str(field) for field in kopf} & AGENTENFELDER
    if verirrt:
        log.warning(
            "Skill '%s': %s belongs to an agent, not to a skill, "
            "and is passed over",
            name,
            ", ".join(sorted(verirrt)),
        )
    unbekannt = {str(field) for field in kopf} - BEKANNTE_FELDER - AGENTENFELDER
    if unbekannt:
        # Not a reason to fail: a typo should stand out, but a file from a
        # newer program version should still be readable here.
        log.warning(
            "Skill '%s': unknown header fields are ignored: %s",
            name,
            ", ".join(sorted(unbekannt)),
        )

    beschreibung = kopf.get("description")
    if not isinstance(beschreibung, str) or not beschreibung.strip():
        raise SkillKaputt("beschreibung", anzeige=anzeige)
    beschreibung = " ".join(beschreibung.split())
    if len(beschreibung) > MAX_BESCHREIBUNG:
        raise SkillKaputt(
            "beschreibung_lang", anzeige=anzeige, grenze=MAX_BESCHREIBUNG
        )

    auto = kopf.get("auto", False)
    if aus_fallback and isinstance(auto, str):
        # The line-wise reader hands back the word it found, not a boolean.
        # `auto: true` has to count here exactly as it does in a valid
        # header — and so does every other spelling YAML reads as one
        # (`yes`, `on`, `off`, and each of them in capitals: the format has
        # eighteen of them, and picking two would make an unrelated line
        # decide whether the skill loads at all). A quoted word, a word with
        # a comment behind it, a number or anything else unknown stays what
        # it is and is refused below.
        auto = {"true": True, "yes": True, "on": True,
                "false": False, "no": False, "off": False}.get(
            auto.strip().lower(), auto
        )
    if not isinstance(auto, bool):
        raise SkillKaputt("auto", anzeige=anzeige)

    anleitung = anleitung.strip()
    if not anleitung:
        raise SkillKaputt("anleitung", anzeige=anzeige)

    return Skill(
        name=name,
        beschreibung=beschreibung,
        anleitung=anleitung,
        ordner=ordner,
        auto=auto,
        eigen=eigen,
    )


# What a double-quoted YAML scalar has to carry as an escape although JSON
# writes it raw: the characters YAML does not accept in a file at all (DEL,
# the C1 controls except NEL, the two non-characters), and a run of three
# hyphens, which the readers here take for the end of the header wherever it
# stands (`text.split("---", 2)`). A lone surrogate is deliberately NOT
# escaped: read back, it would be a description no response can encode as
# UTF-8, and writing it raw fails the way it always has.
_YAML_ESCAPE = re.compile(r"[\x7f-\x84\x86-\x9f\ufffe\uffff]|-{3,}")


def _yaml_escape(match: re.Match[str]) -> str:
    return "".join(f"\\u{ord(char):04x}" for char in match.group())


def skill_file_text(description: str, auto: bool, instruction: str) -> str:
    """``SKILL.md`` as the house writes it, for every writer.

    The description goes in as a JSON string, the way agent files carry
    their text fields (``app/agentenfelder.py``): a JSON string is a valid
    double-quoted YAML scalar, so a colon, a ``#`` or a word like ``yes``
    reads back exactly as it was written instead of breaking the header or
    turning into another type. What JSON leaves raw and YAML or the header
    split cannot take goes in as an escape (``_YAML_ESCAPE``). ``auto`` is
    written as ``true``/``false``.
    """
    quoted = _YAML_ESCAPE.sub(_yaml_escape, json.dumps(description, ensure_ascii=False))
    return (
        f"---\ndescription: {quoted}\n"
        f"auto: {'true' if auto else 'false'}\n---\n\n{instruction}\n"
    )


def skill_lesen(ordner: Path, *, eigen: bool = False) -> Skill:
    """Reads exactly one skill folder. Raises ``SkillKaputt`` with a reason."""
    datei = ordner / SKILL_DATEI
    return skill_aus_text(
        ordner.name, datei.read_text(encoding="utf-8"), ordner=ordner, eigen=eigen
    )


def aus_verzeichnis(verzeichnis: Path, *, eigen: bool) -> dict[str, Skill]:
    """Everything usable in ONE of the two places.

    Public because the settings mask has to tell the two apart: what came with
    the program can be reset, what the user wrote themselves cannot.
    """
    gefunden: dict[str, Skill] = {}
    if not verzeichnis.is_dir():
        # Not an error: the place exists, the content belongs to the user.
        return gefunden
    for ordner in sorted(p for p in verzeichnis.iterdir() if p.is_dir()):
        if not (ordner / SKILL_DATEI).is_file():
            continue
        try:
            gefunden[ordner.name] = skill_lesen(ordner, eigen=eigen)
        except SkillKaputt as fehler:
            log.error("Skill skipped: %s", fehler)
        except (OSError, UnicodeDecodeError) as fehler:
            # A file that is not UTF-8 is as broken as a missing header: it
            # takes this one skill out, never the list, the system prompt
            # and every run that reads it. Its error does not name the
            # skill, so the line does.
            log.error("Skill skipped: %s: %s", ordner.name, fehler)
    return gefunden


def skills_laden(mitgeliefert: Path, eigen: Path) -> dict[str, Skill]:
    """Every usable skill, the user's copy winning over the shipped one.

    Sorted by name so the list reads the same way every time — the order in
    which folders come off the disk is not something anyone should have to
    think about.
    """
    zusammen = aus_verzeichnis(mitgeliefert, eigen=False)
    zusammen.update(aus_verzeichnis(eigen, eigen=True))
    return dict(sorted(zusammen.items()))


# The note in front of a picked skill and the line that hands over to the
# user's own words. A picked skill travels in front of the user's message
# and not in the system message: picking one leaves the front of the
# request alone, so the server does not read the whole chat again for it.
INVOCATION_NOTE = (
    '[IMPORTANT: The user has invoked the "{name}" skill, indicating they want '
    "you to follow its instructions. The full skill content is loaded below.]"
)
INVOCATION_HANDOVER = (
    "The user has provided the following instruction alongside the skill invocation:"
)


_INVOKED = re.compile(r'^\[IMPORTANT: The user has invoked the "([^"]+)" skill')


def invoked_name(text: str) -> str | None:
    """The skill a stored invocation is for — read off its own note."""
    treffer = _INVOKED.match(text or "")
    return treffer.group(1) if treffer else None


def words_after_command(text: str, name: str) -> str:
    """The user's words with the "/name" of the picked skill taken off the
    front — the window keeps it in the stored text, which is what was typed,
    and only what follows the command is handed on. Only that one name:
    a path the user starts with ("/etc/hosts …") is their words."""
    return re.sub(rf"^\s*/{re.escape(name)}(?=\s|$)\s*", "", text or "", count=1)


def invocation(skill: Skill, with_words: bool = True) -> str:
    """What goes in front of the user's message when they picked ``skill``:
    the note, the instruction in full, and — where they wrote words beside
    it (``with_words``) — the line that hands over to
    them. Written onto their row once and sent with it ever after, the way
    it first went out (app/verlaufsbau.py), until a fold takes the row — the
    stored text itself stays exactly what they typed."""
    text = f"{INVOCATION_NOTE.format(name=skill.name)}\n\n{skill.anleitung.strip()}"
    return f"{text}\n\n{INVOCATION_HANDOVER}" if with_words else text


# How often the user changed a skill through the window since this process
# started. A skill the USER writes, changes or deletes takes effect at their
# next message: the chat's system message names the skills the model may
# pick by itself, and this number is part of what tells the request route to
# build it anew (app/api/v1/generierung.py, `_system_messages`). One the
# MODEL saves with skill_save does not count it — that one waits for the next
# fold or the next chat, like everything else the model writes.
_user_edits = 0


def note_user_edit() -> None:
    """Called by the skill routes after every change the user made."""
    global _user_edits
    _user_edits += 1


def user_edit_count() -> int:
    return _user_edits


def needed_tools() -> dict[str, str]:
    """The shipped skills that cannot do their work without one tool, by
    skill name — and that tool.

    Kept here and not in their front matter: the instruction of each one
    names the tool and is built on it, and a catalogue line offering it to a
    run without that tool names a door that cannot be opened. By name, so a
    shipped skill the user edited — a copy in their own folder under the
    same name — still needs the same tool.

    Imported when asked: the tool modules import this module themselves.
    """
    from app.tools import bild_werkzeug, cronjob, frage_werkzeug

    return {
        "image-generator": bild_werkzeug.WERKZEUG_NAME,
        "cronjob": cronjob.WERKZEUG_NAME,
        "grill-me": frage_werkzeug.WERKZEUG_NAME,
    }


def automatische(skills: dict[str, Skill], offered: Iterable[str]) -> list[Skill]:
    """Only those the model may reach for on its own, in this run.

    Everything here costs a line in the system prompt on every request; the
    rest costs nothing at all and is still available by typing its name.
    ``offered`` is this run's tool list: a skill that needs a tool
    (``needed_tools``) is only listed where that tool is offered.
    """
    offered_names = set(offered)
    needed = needed_tools()
    return [
        s for s in skills.values()
        if s.auto and (s.name not in needed or needed[s.name] in offered_names)
    ]
