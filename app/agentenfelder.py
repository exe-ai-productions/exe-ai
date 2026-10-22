"""Field-wise editing of an agent file without losing the rest of it.

The agent form knows a fixed set of controls; the file may carry more — a
``permissions`` block, comments, fields from a newer program version. A form
that rebuilt the file from its own controls would silently delete everything
it does not show. This module goes the other way: it takes the RAW text and
surgically replaces only the fields the caller names, line by line. Whatever
it was not asked about — known or unknown, comment or key — stays exactly as
written.

The file stays the source of truth and stays hand-editable; the form is a
second way in, not a replacement.
"""

from __future__ import annotations

import re
from typing import Any

from app import frontmatter, i18n

# The fields the form may set, in the order a fresh file lists them. The
# order only matters when a field is INSERTED — an existing field is replaced
# in place and keeps its position.
FORMULAR_FELDER: tuple[str, ...] = (
    # First, because it says WHICH agent this is rather than what it may do
    # — the same reason a name heads a form.
    "color",
    # Second for the same reason: what the agent is for.
    "description",
    "tools",
    "folders",
    "max_rounds",
    "max_minutes",
    "max_tokens",
    "reasoning_budget",
    "reasoning_effort",
    "max_command_seconds",
)

# Fields that hold prose. Always written quoted: bare, a description that
# reads "yes" or "42" would come back from YAML as a truth value or a number.
_TEXT_FIELDS = frozenset({"description", "reasoning_effort"})

# A top-level YAML key at the start of a line. Everything indented below it
# belongs to it; the next unindented key line ends its block.
_SCHLUESSEL_ZEILE = re.compile(r"^([A-Za-z_][\w-]*)\s*:")

# Scalars that read fine without quotes. Anything else is written as a quoted
# string that survives every character (``frontmatter.yaml_quoted``).
_SCHLICHT = re.compile(r"^[A-Za-z0-9._/-]+$")


class KopfteilKaputt(ValueError):
    """The text has no usable front matter to edit fields in.

    Carries the catalogue key of the reason, not a finished sentence: a
    person reads it in the language of their page (``text``); ``str()``
    stays English for the log."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(self.text(i18n.STANDARDSPRACHE))

    def text(self, language: str) -> str:
        return i18n.t(f"agent_file.{self.key}", language)

    def __reduce__(self):
        # Rebuilt from its key, not from the sentence ValueError keeps.
        return (type(self), (self.key,))


def _skalar(wert: Any) -> str:
    if isinstance(wert, bool):
        return "true" if wert else "false"
    if isinstance(wert, (int, float)):
        if isinstance(wert, float) and wert.is_integer():
            return str(int(wert))
        return str(wert)
    text = str(wert)
    if _SCHLICHT.match(text):
        return text
    return frontmatter.yaml_quoted(text)


def _feld_zeilen(name: str, wert: Any) -> list[str]:
    """The lines this field is written as. An empty list for "remove"."""
    if wert is None:
        return []
    if name in _TEXT_FIELDS:
        return [f"{name}: {frontmatter.yaml_quoted(str(wert))}"]
    if isinstance(wert, (list, tuple)):
        if not wert:
            return [f"{name}: []"]
        return [f"{name}:", *[f"  - {_skalar(eintrag)}" for eintrag in wert]]
    return [f"{name}: {_skalar(wert)}"]


def _zerlegen(text: str) -> tuple[list[str], str]:
    """The front-matter lines and the body, or a plain refusal."""
    try:
        kopf_roh, rumpf = frontmatter.split(text)
    except frontmatter.NoFrontMatter as error:
        raise KopfteilKaputt("front_missing") from error
    except frontmatter.NoClosingLine as error:
        raise KopfteilKaputt("closing_missing") from error
    kopf_zeilen = kopf_roh.split("\n")
    # The split leaves an empty first entry (the newline after the opening
    # marker) and the line break before the closing marker — both are the
    # markers' own, not content.
    if kopf_zeilen and kopf_zeilen[0] == "":
        kopf_zeilen = kopf_zeilen[1:]
    if kopf_zeilen and kopf_zeilen[-1] == "":
        kopf_zeilen = kopf_zeilen[:-1]
    return kopf_zeilen, rumpf


def _bloecke(zeilen: list[str]) -> list[tuple[str | None, list[str]]]:
    """The front matter as (key, lines) blocks, in file order.

    Lines before the first key — comments, blanks — form a keyless block and
    survive untouched at the top.
    """
    ergebnis: list[tuple[str | None, list[str]]] = []
    aktuell: list[str] = []
    schluessel: str | None = None
    for zeile in zeilen:
        treffer = _SCHLUESSEL_ZEILE.match(zeile)
        if treffer:
            if aktuell or schluessel is not None:
                ergebnis.append((schluessel, aktuell))
            schluessel = treffer.group(1)
            aktuell = [zeile]
        else:
            aktuell.append(zeile)
    if aktuell or schluessel is not None:
        ergebnis.append((schluessel, aktuell))
    return ergebnis


def felder_anwenden(
    text: str, felder: dict[str, Any], prompt: str | None = None
) -> str:
    """The file text with exactly these fields changed and nothing else.

    ``felder`` maps field name to new value; ``None`` removes the field.
    A field not named in ``felder`` keeps its lines verbatim — the same for
    every key this module does not know, every comment and the field order.
    ``prompt`` replaces the body when given, otherwise the body stays.
    """
    unbekannt = set(felder) - set(FORMULAR_FELDER)
    if unbekannt:
        raise ValueError(f"Fields that cannot be used in forms: {', '.join(sorted(unbekannt))}")

    kopf_zeilen, rumpf = _zerlegen(text)
    bloecke = _bloecke(kopf_zeilen)

    offen = dict(felder)
    neu: list[str] = []
    for schluessel, zeilen in bloecke:
        if schluessel is not None and schluessel in offen:
            neu.extend(_feld_zeilen(schluessel, offen.pop(schluessel)))
        else:
            neu.extend(zeilen)

    # Fields the file did not have yet are appended in form order — visible
    # at the end of the head, where a hand edit would also land.
    for name in FORMULAR_FELDER:
        if name in offen:
            neu.extend(_feld_zeilen(name, offen.pop(name)))

    if prompt is not None:
        rumpf = f"\n\n{prompt.strip()}\n"

    kopf = "\n".join(neu)
    if kopf:
        kopf += "\n"
    return f"---\n{kopf}---{rumpf}"


def neu_bauen(felder: dict[str, Any], prompt: str) -> str:
    """A fresh agent file from the form: only the fields that say something."""
    zeilen: list[str] = []
    for name in FORMULAR_FELDER:
        if name in felder:
            zeilen.extend(_feld_zeilen(name, felder[name]))
    kopf = "\n".join(zeilen)
    if kopf:
        kopf += "\n"
    return f"---\n{kopf}---\n\n{prompt.strip()}\n"
