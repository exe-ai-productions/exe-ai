"""Every text in the catalogue is still read by somebody.

Twice a component was deleted and its texts stayed behind: `ModulWaechter`
left seventeen `waechter.*` entries (22ebd36), `Klangwahl` left every
`klaenge.*` entry (9bd4ddf). Together with the local-model rebuilds that is
130 dead texts, cleared out by hand in 614232c — and it would happen again,
because nothing says a word about it.

`test_i18n.py` guards the two catalogues against EACH OTHER: same keys on
both sides, no sentence left untranslated. This file guards them against
the CODE, which is a different question and gets its own file.

**Why a naive search would cry wolf.** Plenty of keys are never written out
in one piece — the code builds them:

    f"jobs.grund.{grund}"          the fixed part is at the FRONT
    t(f"fehler.runner_{grund}")    the same, with a different front
    t(`${bereich}.dauer_ms`)       the fixed part is at the BACK

So a key counts as used when it appears verbatim, OR when a fixed piece the
code really builds keys from matches its front or its back. Those pieces are
READ OUT OF THE CODE (:data:`VORN`, :data:`HINTEN`), never kept as a list by
hand — a hand-kept list goes stale, which is the very disease this guard is
here to cure.

**And the open middle is read out of the code too.** `nachricht.${wort}`
stands for one of the two words the service sends for that slot,
`cronjobs.kind_${each}` for an entry of the list `KINDS`, `bild.sw_${key}`
for a row of the switch table. Which words those are is a question the code
answers: a list, a table, a condition, a return value, the catalogue itself
(:func:`_werte`). A key of such a template counts as read only when it lies
in that set — a word merely occurring somewhere proves nothing (`titel`
occurs, and `nachricht.titel` outlived its component).

Where a set cannot be read, the template keeps the older, softer reading:
the open middle has to occur in the sources. A guard that cries wolf gets
switched off, and there are middles only the running service knows. Which
templates those are is not a rumour — `test_die_weiche_lesung_ist_benannt`
lists every one of them, with the reason.

The guard leans towards silence on purpose: better to miss a dead key than
to go off over a live one.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from app.i18n import LOCALES_VERZEICHNIS, STANDARDSPRACHE

WURZEL = Path(__file__).resolve().parent.parent
# Where a key can be read from. The catalogues themselves are NOT in here:
# a key proves nothing by standing in the file it is defined in.
QUELLEN = (WURZEL / "app", WURZEL / "frontend" / "src")
# `.yaml` is in here because `app/daten/` carries tables that name keys too.
# `.json` is NOT: the catalogues are JSON, and a key would then prove itself.
ENDUNGEN = {".py", ".js", ".mjs", ".cjs", ".ts", ".svelte", ".html", ".yaml", ".yml"}

# The terminal client reads the catalogue as well. It is kept apart from the
# sources above on purpose: its files are searched for keys written out
# whole, between quotes, and for nothing else — so a string it happens to
# build never counts as a piece of a key for the rest of the tree, and a
# key never counts because a longer one begins with it. It is not part of every tree
# either. Where it is left out, the texts kept for it are not judged — there
# is nobody to ask whether they are read. All of them stand under one prefix.
CLIENT = WURZEL / "cli"
CLIENT_PREFIX = "cli."

# What a key is made of, so a piece of one can be recognised in the source.
_STUECK = r"[A-Za-z0-9_.]"

# A fixed piece with a variable AFTER it: an f-string, a template literal, or
# a concatenation. What the expression yields starts with the piece.
#
# The template literal is NOT read as such a piece any more: `nachricht.` in
# front of an interpolated name waved the whole namespace through, and
# `bild.sw_` did the same with its underscore. A template proves a key only
# as a WHOLE, and that is `_durch_vorlage` with `_werte` below. What stands
# here is the concatenation alone.
VORN = (re.compile(rf"""["']({_STUECK}+?)["']\s*\+"""),)

# A whole template literal: what stands before the variable, the expression
# between the braces, and what stands behind it. `nachricht.${art}` and
# `bild.sw_${row.key}` are two; the expression may hold a CALL —
# `t(`werkzeuge.${stand(quelle)}`)` — because it is resolved to what it
# returns. What the expression may NOT hold is a second pair of braces: the
# pattern has to know where the template ends.
VORLAGE = re.compile(
    rf"""["'`]({_STUECK}*?)\$\{{([^`{{}}]{{1,80}})\}}({_STUECK}*)["'`]"""
)
# The same for Python: `f"jobs.grund.{grund}"`, `f"fehler.runner_{grund}"` —
# on ONE line: across two, the quotes of two strings would enclose something
# that is no template at all.
VORLAGE_PY = re.compile(
    r"""["']([A-Za-z0-9_.]{2,40}?)\{([^`{}\n]{1,80})\}([A-Za-z0-9_.]{0,40})["']"""
)

# A fixed piece with a variable BEFORE it. What the expression yields ends
# with the piece — `frontend/src/lib/dauer.js:44` is this shape, and reading
# only fronts would call every `.dauer_ms` key dead.
HINTEN = (
    re.compile(rf"""\}}({_STUECK}*?)["'`]"""),
    re.compile(rf"""\+\s*["']({_STUECK}+?)["']"""),
)

# A piece shorter than this, or one without a separator in it, says nothing
# about which key was meant — "a" or "x." would wave through half the
# catalogue, and a guard that waves everything through is not a guard.
MINDESTLAENGE = 3


@lru_cache(maxsize=1)
def _dateien() -> tuple[tuple[str, str], ...]:
    """Every source file with its text, read once.

    Kept apart where :func:`_quelltext` joins them: a binding is looked up in
    the file that writes it (`const KINDS = [...]` in the file that walks the
    list), and a template's open middle is looked up across all of them.

    A missing source folder is an error, not an empty one: read as empty it
    would make the whole catalogue look dead, and a guard that fails that
    way says the wrong thing about the tree it is guarding.
    """
    dateien = []
    for ordner in QUELLEN:
        assert ordner.is_dir(), f"source folder missing: {ordner}"
        for datei in sorted(ordner.rglob("*")):
            if datei.suffix in ENDUNGEN and datei.is_file():
                # Spelled with forward slashes on every system: a caller
                # names a file the way the tree is written, and the native
                # spelling of Windows would be another string.
                dateien.append(
                    (datei.relative_to(WURZEL).as_posix(), datei.read_text("utf-8", "replace"))
                )
    return tuple(dateien)


@lru_cache(maxsize=1)
def _quelltext() -> str:
    """Every source file that can mention a key, as one string."""
    return "\n".join(text for _, text in _dateien())


# Which file names which word. Without it every lookup walked all 450 files
# with half a dozen patterns, and the guard took minutes per handful of keys
# (measured: 264 s for 189 keys). One pass builds it; every lookup after that
# reads the two or three files that can answer.
_WORT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


@lru_cache(maxsize=1)
def _wortstellen() -> dict[str, tuple[int, ...]]:
    karte: dict[str, list[int]] = {}
    for nummer, (_, text) in enumerate(_dateien()):
        for wort in set(_WORT.findall(text)):
            karte.setdefault(wort, []).append(nummer)
    return {wort: tuple(nummern) for wort, nummern in karte.items()}


def _dateien_mit(name: str) -> tuple[tuple[str, str], ...]:
    """The files that name this word at all."""
    alle = _dateien()
    return tuple(alle[nummer] for nummer in _wortstellen().get(name, ()))


_RUFNAME = r"[A-Za-z_$][A-Za-z0-9_$]*"


@lru_cache(maxsize=1)
def _bindungen() -> dict[str, tuple[tuple[int, str, str], ...]]:
    """What binds a name: `const KINDS = […]`, `{#each … as each}`,
    `for grund in […]`, and the parameter of a callback the code maps over.

    Gathered in ONE pass over the sources. Read one name at a time it was
    0.15 s each — 915 lookups cost 137 s of the guard's 264 s — because every
    lookup walked all 450 files with five patterns.
    """
    karte: dict[str, list[tuple[int, str, str]]] = {}
    for nummer, (_, text) in enumerate(_dateien()):
        for treffer in re.finditer(rf"""\b(?:const|let|var)\s+({_RUFNAME})\s*=""", text):
            karte.setdefault(treffer.group(1), []).append(
                (nummer, "zuweisung", _rechts(text, treffer.end()).strip())
            )
        for treffer in re.finditer(rf"""^\s*({_RUFNAME})\s*=""", text, re.M):
            karte.setdefault(treffer.group(1), []).append(
                (nummer, "zuweisung", _rechts(text, treffer.end()).strip())
            )
        for treffer in re.finditer(
            r"""\{#each\s+([^}]+?)\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*)\b""", text
        ):
            karte.setdefault(treffer.group(2), []).append(
                (nummer, "liste", treffer.group(1).strip())
            )
        for treffer in re.finditer(rf"""\bfor\s+({_RUFNAME})\s+in\s+([^\n:]+):""", text):
            karte.setdefault(treffer.group(1), []).append(
                (nummer, "liste", treffer.group(2).strip())
            )
        for treffer in re.finditer(rf"""\b({_RUFNAME})\s*(?:,[^)]*)?\)\s*=>""", text):
            karte.setdefault(treffer.group(1), []).append(
                (nummer, "callback", str(treffer.start()))
            )
    return {name: tuple(eintraege) for name, eintraege in karte.items()}


@lru_cache(maxsize=1)
def _felder() -> dict[str, tuple[tuple[int, int], ...]]:
    """What one pass finds written for a field name: `key: 'x'`, `"key": 1`,
    `key=x`, `key = …` — with the position of the sign.

    Only the position is kept, not the text on the right: most of the 7473
    field names are never asked for, and reading every right-hand side up
    front cost 2.1 s of the scan (`_rechts` for each of them, measured) —
    the caller reads the few it needs, and is cached per field anyway.
    """
    karte: dict[str, list[tuple[int, int]]] = {}
    for nummer, (_, text) in enumerate(_dateien()):
        for treffer in re.finditer(
            rf"""(?:self\.|this\.)?["']?({_RUFNAME})["']?(?:\s*,[^=\n]*)?\s*\]?\s*[:=](?![=:>])""", text
        ):
            karte.setdefault(treffer.group(1), []).append((nummer, treffer.end()))
    return {name: tuple(eintraege) for name, eintraege in karte.items()}


def _feld_rechts(nummer: int, ende: int) -> str:
    """The right-hand side of one field, read when it is asked for."""
    return _rechts(_dateien()[nummer][1], ende).strip()


@lru_cache(maxsize=1)
def _koepfe() -> dict[str, tuple[tuple[int, int, str], ...]]:
    """Where a name is defined: `class C`, `def f(`, `function f(`, `f = (…) =>`."""
    karte: dict[str, list[tuple[int, int, str]]] = {}
    for nummer, (_, text) in enumerate(_dateien()):
        for art, muster in (
            ("class", r"^class\s+([A-Za-z_][A-Za-z0-9_]*)"),
            ("def", r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)"),
            ("function", r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)\s*[\(<]"),
        ):
            for treffer in re.finditer(muster, text, re.M if muster.startswith("^") else 0):
                karte.setdefault(treffer.group(1), []).append((nummer, treffer.start(), art))
        for treffer in re.finditer(
            rf"""\b({_RUFNAME})\s*=\s*(?:async\s*)?(?:\([^)]*\)|{_RUFNAME})\s*=>""", text
        ):
            karte.setdefault(treffer.group(1), []).append((nummer, treffer.start(), "pfeil"))
    return {name: tuple(eintraege) for name, eintraege in karte.items()}


def _kandidaten(eintraege, datei: str | None, name: str = ""):
    """The entries that count: the file's own, or those it imports.

    `stand(quelle)` calls the one `function stand(` of its own file, not the
    `def stand(` of a Python module somewhere else. `SPRACHEN` and `REPEATS`
    are imported from another file, and only an import lets a name be read
    there: a loop counter or a local that happens to share the name with a
    table somewhere else is NOT what this file means (measured: `i` in
    `ModulTerminal.svelte` collected seven colours from a foreign file).
    """
    if datei is None:
        return list(eintraege)
    alle = _dateien()
    lokal = [eintrag for eintrag in eintraege if alle[eintrag[0]][0] == datei]
    if lokal:
        return lokal
    text = next((text for pfad, text in alle if pfad == datei), "")
    if not _importiert(text, name):
        return []
    return list(eintraege)


def _importiert(text: str, name: str) -> bool:
    """Whether a file imports this name from somewhere else."""
    if not name:
        return False
    for zeile in text.splitlines():
        if "import" not in zeile or name not in zeile:
            continue
        if re.search(rf"""\bimport\b[^\n]*\b{re.escape(name)}\b""", zeile):
            return True
    return False


def _feste_teile(muster: Iterable[re.Pattern[str]]) -> frozenset[str]:
    """The fixed pieces the code really builds keys from.

    A piece comes from a concatenation (`"jobs.grund." + grund`) and stands
    there on its own: the interface writes keys out of it. A piece out of a
    TEMPLATE is no such proof and does not reach here — what a template can
    produce is its whole set, and that is `_durch_vorlage`.
    """
    text = _quelltext()
    gefunden = set()
    for m in muster:
        for treffer in m.finditer(text):
            stueck = treffer.group(1)
            if len(stueck) < MINDESTLAENGE or ("." not in stueck and "_" not in stueck):
                continue
            gefunden.add(stueck)
    return frozenset(gefunden)


# ---------------------------------------------------------------------------
# What the open middle of a template can BE — read out of the code.


# A quoted literal — one line, and the same kind of quote may not stand
# inside it. Across lines the quotes of two strings would enclose a whole
# condition, and a fragment like `').indexOf('` begins and ends with a quote
# too, without being a word anything writes (both measured).
_ZITAT = re.compile(r"""^(["'])((?:(?!\1)[^\n])*)\1$""")
_ZAHL = re.compile(r"^[0-9]+$")
# A piece of a key: what a condition has to name to make a field a table.
_WORTSTUECK = re.compile(r"^[A-Za-z0-9_.-]+$")
# A call: `stand(quelle)`, `String(nummer)`.
_AUFRUF = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(")
# A field of a row: `row.key`, `werkzeug.zustand`, `stats.denken_aufgebraucht`,
# and the same written with the optional dot — `stand?.stand`.
_FELD = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*\??\.([A-Za-z_][A-Za-z0-9_]*)$")
# `Object.keys(texte.katalog.wartewort ?? {})` — the catalogue's own keys.
_KATALOG = re.compile(r"^Object\.keys\s*\(\s*[A-Za-z0-9_$.]*?katalog\.([A-Za-z0-9_.]+)")
_NAME = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
# What says nothing about the value: `String(x)`, `$derived(x)`, `$state(x)`.
_HUELLEN = (
    re.compile(r"""^String\s*\((.*)\)$""", re.S),
    re.compile(r"""^Number\s*\((.*)\)$""", re.S),
    re.compile(r"""^\$derived(?:\.by)?\s*\((.*)\)$""", re.S),
    re.compile(r"""^\$state\s*\((.*)\)$""", re.S),
    re.compile(r"""^\$props\s*\((.*)\)$""", re.S),
)


@lru_cache(maxsize=None)
def _katalog_unter(pfad: str) -> frozenset[str]:
    """The catalogue keys below one path, without the path itself.

    `wartewort.${nummer}` walks `Object.keys(texte.katalog.wartewort)`: the
    numbers it can take are the catalogue's own — read, not guessed.
    """
    knoten = json.loads((LOCALES_VERZEICHNIS / f"{STANDARDSPRACHE}.json").read_text("utf-8"))
    for teil in pfad.split("."):
        if not isinstance(knoten, dict) or teil not in knoten:
            return frozenset()
        knoten = knoten[teil]
    if not isinstance(knoten, dict):
        return frozenset()
    return frozenset(knoten)


def _geklammert(text: str) -> bool:
    """Whether the outermost parentheses of ``text`` enclose all of it."""
    if not (text.startswith("(") and text.endswith(")")):
        return False
    tiefe = 0
    for stelle, zeichen in enumerate(text):
        if zeichen == "(":
            tiefe += 1
        elif zeichen == ")":
            tiefe -= 1
            if tiefe == 0:
                return stelle == len(text) - 1
    return False


def _kern(ausdruck: str) -> str | None:
    """The expression with the wrappers peeled off that say nothing."""
    a = ausdruck.strip().rstrip(",;").strip()
    while a.startswith("..."):
        # A spread says nothing about the value: `...SPRACHEN.map(…)` walks
        # the same list as without it.
        a = a[3:].strip()
    while a:
        neu = a
        if _geklammert(neu):
            neu = neu[1:-1].strip()
        else:
            for huelle in _HUELLEN:
                treffer = huelle.match(neu)
                if treffer:
                    neu = treffer.group(1).strip()
                    break
        if neu == a:
            return a or None
        a = neu
    return None


def _zweige(ausdruck: str) -> tuple[str, str] | None:
    """The two arms of a condition, or None.

    `c ? a : b` (JavaScript) and `a if c else b` (Python). A chain —
    `a ? 'morgen' : b ? 'tag' : 'abend'` — hands its tail back through this
    same function, so every arm of a chain is read.
    """
    tiefe = 0
    for i, zeichen in enumerate(ausdruck):
        if zeichen in "([{":
            tiefe += 1
        elif zeichen in ")]}":
            tiefe -= 1
        elif zeichen == "?" and tiefe == 0:
            # `?.` and `??` are no condition: the SECOND question mark of a
            # `??` is no ternary either, and reading it as one left the
            # fallback rule below unreachable (measured: `x ?? 'y'` gave
            # None, and `bildserver.stand_${stand?.stand ?? 'kein_programm'}`
            # stayed unreadable).
            if ausdruck[i : i + 2] in ("?.", "??") or (i and ausdruck[i - 1] == "?"):
                continue
            rest = ausdruck[i + 1 :]
            innen = 0
            for stelle, zeichen2 in enumerate(rest):
                if zeichen2 in "([{":
                    innen += 1
                elif zeichen2 in ")]}":
                    innen -= 1
                elif zeichen2 == ":" and innen == 0 and rest[stelle : stelle + 2] != "::":
                    return rest[:stelle].strip(), rest[stelle + 1 :].strip()
            return None
    if " if " in ausdruck and " else " in ausdruck:
        # Python writes it the other way round: `A if condition else B` — the
        # two VALUES are A and B, and what stands between them is the test.
        # The brackets of the whole expression sit on the first and the last
        # arm (`(\n "a"\n if c\n else "b"\n)`), so they come off here.
        wert, _, rest = ausdruck.partition(" if ")
        _, _, sonst = rest.partition(" else ")
        wert, sonst = wert.strip().lstrip("(").strip(), sonst.strip().rstrip(")").strip()
        if wert and sonst:
            return wert, sonst
    for trenner in ("||", "??"):
        if trenner in ausdruck:
            links, _, rechts = ausdruck.partition(trenner)
            if links.strip() and rechts.strip():
                return links.strip(), rechts.strip()
    return None


def _koerper(text: str, ab: int) -> str | None:
    """The body of a definition: braces in the interface, indent in Python.

    `ab` points at the definition's head — `def f(`, `class C:`,
    `function f(…`. The first `{` after it opens the body in JavaScript; in
    Python the body is the block indented under the head's own line.
    """
    zeilenende = text.find("\n", ab)
    auf = text.find("{", ab)
    if auf != -1 and (zeilenende == -1 or auf < zeilenende):
        tiefe = 0
        for stelle in range(auf, len(text)):
            if text[stelle] == "{":
                tiefe += 1
            elif text[stelle] == "}":
                tiefe -= 1
                if tiefe == 0:
                    return text[auf + 1 : stelle]
        return None
    if zeilenende == -1:
        return None
    zeile = text[text.rfind("\n", 0, ab) + 1 : zeilenende]
    einzug = len(zeile) - len(zeile.lstrip())
    zeilen = []
    for folgezeile in text[zeilenende + 1 :].splitlines():
        if not folgezeile.strip():
            zeilen.append(folgezeile)
            continue
        if len(folgezeile) - len(folgezeile.lstrip()) <= einzug:
            break
        zeilen.append(folgezeile)
    return "\n".join(zeilen)


def _rechts(text: str, ab: int, grenze: int = 400) -> str:
    """The expression to the right of an `=`: up to the comma or semicolon
    that stands on top. Brackets may span lines, so a newline inside one does
    not end it — but a value longer than `grenze` characters is no value this
    guard reads, and walking it would cost more than the whole guard."""
    tiefe = 0
    for stelle in range(ab, min(len(text), ab + grenze)):
        zeichen = text[stelle]
        if zeichen in "([{":
            tiefe += 1
        elif zeichen in ")]}":
            if tiefe == 0:
                return text[ab:stelle]
            tiefe -= 1
        elif tiefe == 0 and zeichen in ",;\n":
            return text[ab:stelle]
    return text[ab : ab + grenze]


def _zeilenrest(text: str, ab: int) -> str:
    """From a position to the end of its line, brackets kept together."""
    tiefe = 0
    for stelle in range(ab, len(text)):
        if text[stelle] in "([{":
            tiefe += 1
        elif text[stelle] in ")]}":
            tiefe -= 1
        elif text[stelle] == "\n" and tiefe == 0:
            return text[ab:stelle]
    return text[ab:]


@lru_cache(maxsize=None)
def _rueckgaben(name: str, datei: str | None = None) -> frozenset[str] | None:
    """The values a function returns, read from its body, or None.

    `stand(quelle)` returns `'ausgeschaltet'` or `'nicht_verbunden'`, and
    those two are the whole set `werkzeuge.${stand(quelle)}` can name. Every
    `return` counts and a condition inside one counts on both arms. A body
    with a return that cannot be read is left out as a whole — a half-read
    set would report live keys as dead.

    The file the call stands in is searched first: `def stand(` exists a few
    times in Python, and none of those is what `stand(quelle)` calls. Only
    when the call's own file does not define the name is the whole tree
    searched — that is the case for a template a test writes on its own.
    """
    werte: set[str] = set()
    for nummer, stelle, art in _kandidaten(_koepfe().get(name, ()), datei, name):
        text = _dateien()[nummer][1]
        if art == "pfeil":
            pfeil = text.index("=>", stelle)
            rumpf = (
                _koerper(text, pfeil + 2)
                if text[pfeil + 2 :].lstrip().startswith("{")
                else _zeilenrest(text, pfeil + 2)
            )
            zweige = re.findall(r"\breturn\b([^\n;]*)", rumpf or "") or [rumpf or ""]
        else:
            zweige = re.findall(r"\breturn\b([^\n;]*)", _koerper(text, stelle) or "")
        teile = [_werte(zweig.strip().rstrip(";"), datei) for zweig in zweige]
        if not zweige or any(teil is None for teil in teile):
            continue
        for teil in teile:
            assert teil is not None
            werte |= teil
    return frozenset(werte) if werte else None


@lru_cache(maxsize=None)
def _bedingt_geschrieben(feld: str) -> bool:
    """Whether a condition writes a word of this field — the other kind of table.

    `messwerte["denken_aufgebraucht"] = ("…"` — the arms of that condition are
    the words the field can take, and they are the whole set the interface can
    show. A condition whose arms are computed (`x = a if b else c`) names no
    word and makes the field no table.
    """
    for nummer, ende in _felder().get(feld, ()):
        zweige = _zweige(_feld_rechts(nummer, ende))
        if not zweige:
            continue
        # An arm that is not a plain word names no key piece: `"a b"` or a
        # sentence goes into no middle, and a condition full of them makes
        # the field no table.
        if any(
            (kern := _kern(zweig)) is not None
            and (zitat := _ZITAT.match(kern))
            and _WORTSTUECK.match(zitat.group(2))
            for zweig in zweige
        ):
            return True
    return False


@lru_cache(maxsize=1)
def _klassen() -> tuple[tuple[int, int], ...]:
    """Every class of the sources: its file and where it starts."""
    return tuple(
        (nummer, stelle)
        for eintraege in _koepfe().values()
        for nummer, stelle, art in eintraege
        if art == "class"
    )


@lru_cache(maxsize=None)
def _klassen_mit_feld(feld: str) -> tuple[tuple[str, int], ...]:
    """Classes that carry this name, with where it sits in their call.

    Two shapes: a class that declares the field first — `class Switch:
    key: str` — so `Switch("circular", …)` hands it the first argument; and a
    constructor that copies a parameter into the instance (`self.key = key`),
    where the name may sit anywhere — `AgentDateiKaputt(file, "not_yaml")`
    hands it the second. The number counts without `self`, the way the call
    site counts.
    """
    gefunden = []
    alle = _dateien()
    for nummer, stelle in _klassen():
        text = alle[nummer][1]
        rumpf = _koerper(text, stelle)
        if rumpf is None:
            continue
        kopf = re.match(r"class\s+([A-Za-z_][A-Za-z0-9_]*)", text[stelle:])
        if kopf is None:
            continue
        init = re.search(r"\bdef\s+__init__\s*\((.*?)\)", rumpf, re.S)
        parameter: list[str] = []
        if init:
            parameter = [
                teil.split(":")[0].split("=")[0].strip().lstrip("*")
                for teil in _teile_oben(init.group(1))
            ]
            parameter = [p for p in parameter if p != "self"]
        kopie = re.search(rf"""self\.{re.escape(feld)}\b[^=\n]*=\s*([A-Za-z_][A-Za-z0-9_]*)\b""", rumpf)
        if kopie and kopie.group(1) in parameter:
            gefunden.append((kopf.group(1), parameter.index(kopie.group(1))))
            continue
        erster = re.search(r"^\s+([A-Za-z_][A-Za-z0-9_]*)\s*:", rumpf, re.M)
        if erster and erster.group(1) == feld:
            gefunden.append((kopf.group(1), 0))
    return tuple(gefunden)


def _argumente(quelltext: str, stelle: int, ausdruck: str) -> frozenset[str]:
    """The literal arguments that reach one name at every call site.

    `def _sample(key: str, …)` composes `Switch(key=f"sample_{key}")`; what
    `key` holds comes from the calls — `_sample("apg_eta", …)` hands it
    `apg_eta`. `self.kind` inside a constructor takes the argument of the
    class's own call, `SkillKaputt("auto")`. Read by position, and only
    literals count: an argument the code composes itself lands in no set.
    """
    parameter = ausdruck.split(".")[-1]
    kopf = _kopf_davor(quelltext, stelle)
    if kopf is None:
        return frozenset()
    name, kopfstelle, art = kopf
    if ausdruck.startswith("self.") or art == "class" or name == "__init__":
        # The constructor carries the name; what a class hands it is written
        # at the class's own call — `SkillKaputt("auto")`, not `__init__(…)`.
        if name == "__init__":
            klasse = re.finditer(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)", quelltext[:stelle], re.M)
            letzte = None
            for letzte in klasse:
                pass
            if letzte is None:
                return frozenset()
            name = letzte.group(1)
            kopfstelle = letzte.start()
        init = re.search(r"\bdef\s+__init__\s*\(", quelltext[kopfstelle:])
        if not init:
            return frozenset()
        kopfstelle = kopfstelle + init.start()
    klammer = quelltext.find("(", kopfstelle)
    if klammer == -1:
        return frozenset()
    namen = [
        teil.split(":")[0].split("=")[0].strip().lstrip("*")
        for teil in _teile_oben(_klammer_inhalt(quelltext[klammer:]))
    ]
    namen = [n for n in namen if n != "self"]
    if parameter not in namen:
        return frozenset()
    stelle_des_parameters = namen.index(parameter)
    argumente = set()
    for _, text in _dateien():
        for aufruf in re.finditer(rf"""\b{re.escape(name)}\s*\(""", text):
            teile = _teile_oben(_klammer_inhalt(text[aufruf.end() - 1 :]))
            if len(teile) <= stelle_des_parameters:
                continue
            zitat = _ZITAT.match(teile[stelle_des_parameters].strip())
            if zitat:
                argumente.add(zitat.group(2))
    return frozenset(argumente)


def _kopf_davor(quelltext: str, stelle: int) -> tuple[str, int, str] | None:
    """The definition a position stands in: its name, its start, its kind.

    The nearest `class C` or `def f(` above the position. Both are needed
    apart: a class carries the name in its constructor, a function in its own
    parameter list.
    """
    treffer: tuple[str, int, str] | None = None
    for art, muster in (
        ("class", r"^class\s+([A-Za-z_][A-Za-z0-9_]*)"),
        ("def", r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ):
        for m in re.finditer(muster, quelltext[:stelle], re.M):
            if treffer is None or m.start() > treffer[1]:
                treffer = (m.group(1), m.start(), art)
    return treffer


def _klammer_inhalt(text: str) -> str:
    """What stands between the first `(` and its closing parenthesis."""
    auf = text.find("(")
    if auf == -1:
        return ""
    tiefe = 0
    for stelle in range(auf, len(text)):
        if text[stelle] in "([{":
            tiefe += 1
        elif text[stelle] in ")]}":
            tiefe -= 1
            if tiefe == 0:
                return text[auf + 1 : stelle]
    return text[auf + 1 :]


def _teile_oben(text: str) -> list[str]:
    """The parts of an argument list, split at the commas that are on top."""
    teile, tiefe, anfang = [], 0, 0
    for stelle, zeichen in enumerate(text):
        if zeichen in "([{":
            tiefe += 1
        elif zeichen in ")]}":
            tiefe -= 1
        elif zeichen == "," and tiefe == 0:
            teile.append(text[anfang:stelle])
            anfang = stelle + 1
    teile.append(text[anfang:])
    return [teil for teil in teile if teil.strip()]


# The fields a value is being read for right now: `"key": switch.key` names
# the field it reads, and the walk stops instead of circling for ever.
_IM_LAUF_FELD: set[str] = set()


@lru_cache(maxsize=None)
def _feldwerte(feld: str) -> frozenset[str] | None:
    """The values written for one field name, anywhere in the sources.

    Four shapes, all of them tables the interface really walks: a literal
    left in a row (`key: "x"`, `"key": "x"`, `key="x"`), a value a function
    composes from one of its names (`Switch(key=f"sample_{key}")` with the
    call `_sample("apg_eta", …)`, `self.key = f"skills.fehler_{self.kind}"`
    with `SkillKaputt("auto")`), the first positional argument of a row whose
    first field carries that name (`Switch("circular", …)`), and a plain
    expression another table hands it (`"name": tool.WERKZEUG_NAME`).

    Looked up in every file: the row is walked in the interface while its
    table may stand in Python. A field that names itself (`"key": switch.key`)
    ends the walk with ``None`` — not with a half-read set, which would
    depend on the order the keys happen to be asked in (measured: 351 values
    against 51 for the same field in the same tree) and could report a live
    key as dead.
    """
    if feld in _IM_LAUF_FELD:
        return None
    _IM_LAUF_FELD.add(feld)
    try:
        werte: set[str] = set()
        vorlage = re.compile(r"""^f["']([^"'{}]*)\{([A-Za-z0-9_.]+)\}([^"'{}]*)["']""")
        alle = _dateien()
        for nummer, ende in _felder().get(feld, ()):
            text = alle[nummer][1]
            rechts = _feld_rechts(nummer, ende)
            zitat = _ZITAT.match(rechts)
            if zitat:
                werte.add(zitat.group(2))
                continue
            gebaut = vorlage.match(rechts)
            if gebaut:
                vorne, ausdruck, hinten = gebaut.group(1), gebaut.group(2), gebaut.group(3)
                for argument in _argumente(text, ende, ausdruck):
                    werte.add(f"{vorne}{argument}{hinten}")
                continue
            teil = _werte(rechts, None)
            if teil is not None:
                werte |= teil
        # A row written positionally: `Switch("circular", …)` hands its first
        # argument to the class's first field, `AgentDateiKaputt(file, "…")`
        # the second to `key`.
        for klasse, stelle_der_klasse in _klassen_mit_feld(feld):
            for pfad, text in _dateien_mit(klasse):
                for treffer in re.finditer(rf"""\b{re.escape(klasse)}\s*\(""", text):
                    teile = _teile_oben(_klammer_inhalt(text[treffer.end() - 1 :]))
                    if len(teile) <= stelle_der_klasse:
                        continue
                    zitat = _ZITAT.match(teile[stelle_der_klasse].strip())
                    if zitat:
                        werte.add(zitat.group(2))
        return frozenset(werte)
    finally:
        _IM_LAUF_FELD.discard(feld)


def _ausdruck_davor(text: str, ende: int) -> str | None:
    """The expression that ends just before a position.

    `Object.keys(texte.katalog.wartewort ?? {}).map((nummer) => …)` — the
    receiver of that `.map` is what stands before it, brackets balanced out.
    """
    i = ende - 1
    while i >= 0:
        zeichen = text[i]
        if zeichen in ")]}":
            anfang = i
            tiefe = 0
            while anfang >= 0:
                if text[anfang] in ")]}":
                    tiefe += 1
                elif text[anfang] in "([{":
                    tiefe -= 1
                    if tiefe == 0:
                        break
                anfang -= 1
            if anfang < 0:
                return None
            i = anfang - 1
            continue
        if zeichen.isalnum() or zeichen in "_$.'":
            i -= 1
            continue
        break
    ausdruck = text[i + 1 : ende].strip()
    return ausdruck or None


# The names a value is being read for right now. A binding that names itself
# — `let zeile = zeile ?? ''` — would otherwise walk into itself for ever.
_IM_LAUF: set[str] = set()


@lru_cache(maxsize=None)
def _bindung(name: str, datei: str | None = None) -> frozenset[str] | None:
    """What binds a name to its values, read out of the code, or None.

    The shapes the sources really use: `{#each KINDS as each}` and
    `const KINDS = [...]` in the interface, `for grund in […]` and
    `grund = …` in Python, and the parameter of a callback the code maps over
    (`.map((nummer) => …)` after `Object.keys(…)`). A binding that cannot be
    read is left out; what the other bindings give stands.

    Read in the file the name is used in, never in the whole tree: `name`,
    `teil` and `stand` stand in a dozen scopes, and only one of them is this
    one. Without a file (a template a test writes on its own) the whole tree
    is searched.
    """
    if name in _IM_LAUF:
        return None
    _IM_LAUF.add(name)
    try:
        werte: set[str] = set()
        alle = _dateien()
        for nummer, art, inhalt in _kandidaten(_bindungen().get(name, ()), datei, name):
            text = alle[nummer][1]
            if art == "liste":
                teil = _werte(inhalt, datei)
                if teil is None:
                    continue
                werte |= teil
            elif art == "zuweisung":
                teil = _werte(inhalt, datei)
                if teil is None:
                    continue
                werte |= teil
            else:  # "callback" — what it walks stands before the call
                stelle = int(inhalt)
                klammer = text.rfind("(", 0, stelle + len(name))
                if klammer == -1:
                    continue
                if klammer and text[klammer - 1] == "(":
                    klammer -= 1
                quelle = _ausdruck_davor(text, klammer)
                if quelle is None:
                    continue
                teil = _werte(quelle, datei)
                if teil is None:
                    continue
                werte |= teil
        # `{#each [['bild', false], ['video', true]] as [name, video]}` — the
        # name takes the element at its place in every row of the list.
        for pfad, quelltext in alle:
            if datei is not None and pfad != datei:
                continue
            for treffer in re.finditer(r"""\{#each\s+(\[[^\n]*?\])\s+as\s+\[([^\]]+)\]""", quelltext):
                namen = [teil.strip() for teil in treffer.group(2).split(",")]
                if name not in namen:
                    continue
                stelle = namen.index(name)
                for zeile in _teile_oben(treffer.group(1).strip()[1:-1]):
                    teile = _teile_oben(zeile.strip()[1:-1])
                    if len(teile) <= stelle:
                        continue
                    zitat = _ZITAT.match(teile[stelle].strip())
                    if zitat:
                        werte.add(zitat.group(2))
        # No word at all is no readable answer either: `gespraechZustand`
        # bound to `null` everywhere proves nothing about a key.
        return frozenset(werte) if werte else None
    finally:
        _IM_LAUF.discard(name)


@lru_cache(maxsize=None)
def _werte(ausdruck: str, datei: str | None = None) -> frozenset[str] | None:
    """The finite set of values this expression can take, or None.

    None means "not readable" — the caller then keeps the softer reading of
    the open middle. Every readable branch answers with a SET, and an empty
    set is a real answer: `null` is no word at all.

    ``datei`` is the file the expression stands in; what a NAME holds is
    looked up there and not in the whole tree, where a dozen scopes share
    the same name. A field is looked up in every file — the switch table a
    row walks is in Python while the row is walked in the interface.
    """
    return _werte_tief(ausdruck, datei, 0)


def _werte_tief(ausdruck: str, datei: str | None, tiefe: int) -> frozenset[str] | None:
    if tiefe > 8:
        return None
    a = _kern(ausdruck)
    if a is None:
        return None
    # The catalogue FIRST: `Object.keys(texte.katalog.wartewort ?? {})` holds
    # a `??`, and read as a condition its left arm is a call without its
    # closing bracket.
    katalog = _KATALOG.match(a)
    if katalog:
        return _katalog_unter(katalog.group(1))
    # Then the condition, BEFORE the literal: `'x' if c else 'y'` on one line
    # begins and ends with a quote, so `_ZITAT` would swallow it whole and
    # lose both arms (measured: `zustand = "fertig" if … else "gescheitert"`
    # gave one mangled word instead of the two).
    zweige = _zweige(a)
    if zweige is not None:
        aus_den_zweigen: set[str] = set()
        for zweig in zweige:
            teil = _werte_tief(zweig, datei, tiefe + 1)
            if teil is None:
                return None
            aus_den_zweigen |= teil
        return frozenset(aus_den_zweigen)
    zitat = _ZITAT.match(a)
    if zitat:
        return frozenset({zitat.group(2)})
    if _ZAHL.match(a):
        return frozenset({a})
    if a in {"null", "undefined", "None", "false"}:
        return frozenset()
    if a.startswith("[") and a.endswith("]"):
        # A list: `['fertig', 'wartet', 'fehler']` — its values are what it
        # holds. `...rest` spreads another list in.
        aus_der_liste: set[str] = set()
        for eintrag in _teile_oben(a[1:-1]):
            eintrag = eintrag.strip()
            if eintrag.startswith("..."):
                eintrag = eintrag[3:].strip()
            teil = _werte_tief(eintrag, datei, tiefe + 1)
            if teil is None:
                return None
            aus_der_liste |= teil
        return frozenset(aus_der_liste)
    ruf = _AUFRUF.match(a)
    if ruf:
        return _rueckgaben(ruf.group(1), datei)
    feld = _FELD.match(a)
    if feld:
        # A field is only read where the code writes it as a TABLE: a class
        # carries it (`Switch("circular", …)`, `self.kind = kind`), or a
        # condition writes it (`messwerte["denken_aufgebraucht"] = "…" if …`).
        # Everything else — `antwort.ergebnis`, `stand?.stand`,
        # `werkzeug.name` — is named by the running service, and the guard
        # reads no set for it. Not readable means the softer reading, never a
        # key reported dead.
        if _klassen_mit_feld(feld.group(1)) or _bedingt_geschrieben(feld.group(1)):
            werte = _feldwerte(feld.group(1))
            return werte or None
        return None
    if _NAME.match(a):
        return _bindung(a, datei)
    return None


@lru_cache(maxsize=None)
def _vorlagen_in(text: str, datei: str | None) -> tuple[tuple[str, str, str, str | None], ...]:
    """Every template literal of one text: front, expression, back, file.

    Read once per text — `_durch_vorlage` asks this for each key, and a full
    scan over the sources is what costs (measured 0.021 s per scan against
    407 keys). Templates with neither a front nor a back are left out: what
    they interpolate would be the whole key, and a key that stands somewhere
    in the sources never reaches `_durch_vorlage` at all.

    The file travels with the template: what a name in it holds is read in
    the file that writes it, not in the whole tree — `name`, `teil` and
    `stand` stand in a dozen scopes, and only one of them is this one.
    """
    return tuple(
        (t.group(1), t.group(2).strip(), t.group(3), datei)
        for muster in (VORLAGE, VORLAGE_PY)
        for t in muster.finditer(text)
        # One side has to carry a separator: a template whose fixed parts are
        # `a` and `` names no key, whatever the code builds with it.
        if ("." in t.group(1) or "_" in t.group(1))
        or ("." in t.group(3) or "_" in t.group(3))
    )


@lru_cache(maxsize=1)
def _vorlagen() -> tuple[tuple[str, str, str, str | None], ...]:
    """Every template of every source file, each with the file it stands in."""
    return tuple(
        vorlage for datei, text in _dateien() for vorlage in _vorlagen_in(text, datei)
    )


def _durch_vorlage(schluessel: str, text: str | None = None) -> bool:
    """Whether a template literal in the interface can produce this key.

    `nachricht.${wort}` names one of the few words the service sends for that
    slot; the key it stands for can therefore be pinned down — pinned down by
    the SET the expression can take (:func:`_werte`), never by the word merely
    occurring somewhere. A template whose set cannot be read keeps the older
    reading: its open middle has to occur in the sources.

    Without a ``text`` the sources are walked file by file, and every
    expression is read in its own file. A ``text`` that is not a source file
    (a test writing one template) is walked on its own, and what its
    expressions name is looked up across the sources.
    """
    vorlagen = _vorlagen() if text is None else _vorlagen_in(text, None)
    ganz = _quelltext()
    for anfang, ausdruck, ende, datei in vorlagen:
        if not schluessel.startswith(anfang) or not schluessel.endswith(ende):
            continue
        # Where the window between front and back begins and ends. Written
        # out and not as `… or None`: a stop of 0 is an EMPTY window, not
        # "to the end of the key".
        mitte_anfang, mitte_ende = len(anfang), len(schluessel) - len(ende)
        if mitte_ende <= mitte_anfang:
            continue
        mitte = schluessel[mitte_anfang:mitte_ende]
        werte = _werte(ausdruck, datei)
        if werte is None:
            if mitte in ganz:
                return True
            continue
        if mitte in werte:
            return True
    return False


@lru_cache(maxsize=2)
def _teile(hinten: bool) -> frozenset[str]:
    return _feste_teile(HINTEN if hinten else VORN)


@lru_cache(maxsize=1)
def _client_text() -> str | None:
    """The terminal client's sources as one string, or ``None`` in a tree
    that comes without it."""
    if not CLIENT.is_dir():
        return None
    return "\n".join(
        file.read_text("utf-8", "replace") for file in sorted(CLIENT.rglob("*.py"))
    )


def _client_reads(key: str) -> bool:
    """Whether the terminal client accounts for this key: it names it — or,
    in a tree without the client, the key is one of those kept for it."""
    text = _client_text()
    if text is None:
        return key.startswith(CLIENT_PREFIX)
    return f'"{key}"' in text or f"'{key}'" in text


def tote_schluessel(schluessel: Iterable[str]) -> list[str]:
    """Those of ``schluessel`` that no line of source code asks for."""
    text = _quelltext()
    vorn, hinten = _teile(False), _teile(True)
    return [
        s
        for s in schluessel
        if s not in text
        and not _client_reads(s)
        and not _durch_vorlage(s)
        and not any(s.startswith(v) for v in vorn)
        and not any(s.endswith(h) for h in hinten)
    ]


def _schluessel(knoten, praefix=""):
    for name, wert in knoten.items():
        pfad = f"{praefix}{name}"
        if isinstance(wert, dict):
            yield from _schluessel(wert, f"{pfad}.")
        else:
            yield pfad


def katalogschluessel() -> list[str]:
    katalog = json.loads(
        (LOCALES_VERZEICHNIS / f"{STANDARDSPRACHE}.json").read_text("utf-8")
    )
    return sorted(_schluessel(katalog))


def test_kein_katalogtext_ist_tot():
    """A key nobody reads any more is a text that got left behind when its
    component was deleted. Either it is used, or it goes — the two cases
    this guard exists for both ended in a hand-written cleanup."""
    tot = tote_schluessel(katalogschluessel())
    assert not tot, (
        f"{len(tot)} catalogue text(s) are read nowhere any more. Each must "
        "either be used or be deleted from app/locales/de.json AND en.json:"
        "\n  " + "\n  ".join(tot)
    )


def test_the_terminal_client_counts_as_a_reader():
    """A key only the terminal client names is read, and an invented one
    under its prefix is not. In a tree without the client nothing under that
    prefix is judged — and every other key still is."""
    invented = "cli.made_up_for_this_test"
    if _client_text() is None:
        assert tote_schluessel([invented]) == []
    else:
        assert tote_schluessel(["cli.cmd_help"]) == []
        assert tote_schluessel([invented]) == [invented]
        # The beginning of a key the client names is no key it names.
        assert tote_schluessel(["cli.cmd_hel"]) == ["cli.cmd_hel"]
    assert tote_schluessel(["made_up.for_this_test"]) == ["made_up.for_this_test"]


def test_die_wache_faellt_bei_einem_erfundenen_schluessel_um():
    """The guard checked against itself: a key that is in no catalogue and
    in no source file has to come back as dead. Without this, a guard that
    silently found nothing at all would look exactly like a clean tree."""
    erfunden = "diesenschluessel.gibt_es_nirgends_wirklich"
    assert tote_schluessel([erfunden]) == [erfunden]


def test_die_wache_schweigt_bei_zusammengebauten_schluesseln():
    """The silence test, in both directions: a key whose front is built in
    Python (`f"jobs.grund.{grund}"`) and one whose BACK is built in a
    template literal (`` `${bereich}.dauer_ms` ``). Neither is ever written
    out in one piece, and calling either dead would be the false alarm that
    gets a guard switched off.

    `jobs.grund.` reaches this over the CONCATENATION
    (`'jobs.grund.' + grund`, frontend/src/lib/auftragsmelder.js) — that is
    the one shape `VORN` still reads. The Python f-string is no proof any
    more, and neither is a template.
    """
    assert "jobs.grund." in _teile(False)
    assert tote_schluessel(["jobs.grund.ein_grund_den_es_nicht_gibt"]) == []
    assert tote_schluessel(["einbereich.dauer_ms"]) == []


def test_die_wache_meldet_einen_toten_schluessel_aus_einem_namensraum():
    """Keys of an interpolated namespace that nothing can produce.

    Each of the three stands for a set the code writes down: `nachricht.${…}`
    for the two words the service sends for that slot, `gruss.${…}` for
    morning, day and evening, `wartewort.${…}` for the catalogue's own
    numbers. None of the three names lies in its set, and the bare
    `nachricht.` in front of the interpolation must not decide it either:
    that would wave the WHOLE namespace through, and a key whose component
    was deleted would look read.
    """
    assert tote_schluessel(["nachricht.wartezeit_kurz"]) == ["nachricht.wartezeit_kurz"]
    assert tote_schluessel(["nachricht.titel"]) == ["nachricht.titel"]
    assert tote_schluessel(["gruss.nacht"]) == ["gruss.nacht"]
    assert tote_schluessel(["wartewort.99"]) == ["wartewort.99"]


def test_die_wache_meldet_einen_toten_schluessel_aus_einer_unterstrich_vorlage():
    """The same for the two namespaces whose template fixes a piece with an
    underscore in front of the braces — `bild.sw_${row.key}` and
    `cronjobs.kind_${each}`. The fixed piece alone used to count as the
    proof, so the WHOLE namespace passed, deleted components included."""
    assert tote_schluessel(["bild.sw_gibtsnicht"]) == ["bild.sw_gibtsnicht"]
    assert tote_schluessel(["cronjobs.kind_gibtsnicht"]) == ["cronjobs.kind_gibtsnicht"]


def test_dieselben_zehn_zaehlen_auch_anders_geschrieben():
    """The ten `wartewort.` keys hang on the set the number comes from, not
    on how the template spells it. Written as `${String(nummer)}` over the
    catalogue's own keys, all ten stay read — and a number outside the
    catalogue is still reported. Held against the template alone, so the
    proof has to be the resolution and not the real line in App.svelte."""
    vorlage = "const zeile = (nummer) => t(`wartewort.${String(nummer)}`)"
    assert _durch_vorlage("wartewort.7", vorlage)
    assert not _durch_vorlage("wartewort.99", vorlage)
    assert tote_schluessel([f"wartewort.{n}" for n in range(1, 11)]) == []


def test_die_weiche_lesung_ist_benannt():
    """The templates whose value set could not be read, named here.

    Every one of them keeps the older, softer reading: its open middle only
    has to occur somewhere in the sources. That is weaker than the guard
    wants — a component deleted from one of these namespaces stays unnoticed
    as long as its word stands anywhere — and this list is the honest state
    of the file. Pinned as names and not as a number: a count would let one
    name slip out while another slipped in.

    Why their set is out of reach, by group:

    * a value the SERVICE answers with, or one only the running program
      knows: `antwort.ergebnis`, `gespraechZustand`, `index`, `uuid4()`,
      `kennung.toUpperCase()`
    * a parameter the CALLERS fill (`grund`, `fall`, `code`, `sorte`, `wert`,
      `bereich`, `eintrag`, `name`, `key` in the switch helpers — the switch
      keys themselves are read strictly, over `bild.sw_${row.key}`;
      `serverName`, whose lines test_serverkatalog.py holds against the
      shipped servers name by name)
    * strings that are no keys at all: `${name}.txt`, `_${name}`
    """
    weich = sorted(
        f"{anfang}${{{ausdruck}}}{ende}"
        for anfang, ausdruck, ende, datei in _vorlagen()
        if _werte(ausdruck, datei) is None
    )
    assert sorted(set(weich)) == [
        "${bereich}.dauer",
        "${bereich}.dauer_ms",
        "${kennung.toUpperCase().replace(/-/g, '_')}_API_KEY",
        "${name}.txt",
        "_${name}",
        "ad_${key}",
        "agenten.${fall}",
        "aufruf_${index}",
        "call_${uuid4().hex[:24]}",
        "cronjobs.${fall}",
        "dateien.${fall}",
        "editor.${fall}",
        "fehler.runner_${grund}",
        "gedaechtnis.${fall}",
        "high_noise_${key}",
        "jobs.grund.${grund}",
        "katalog.art_${eintrag}",
        "katalog.satz_zub_${sorte}",
        "katalog.sorte_${sorte}",
        "ordnerwissen.${antwort.ergebnis}",
        "regeln.${name}",
        "sample_${key}",
        "sprache.gespraech_${gespraechZustand}",
        "sprache.name_${code}",
        "systemprompt.${fall}",
        "verbindungen.zweck.${serverName}",
        "werkzeuge.${fall}",
    ]


def test_ein_aufruf_in_der_vorlage_zaehlt_ueber_seine_rueckgabe():
    """`t(`werkzeuge.${stand(quelle)}`)` — the expression between the braces
    is a CALL, and what it returns is the set of keys that line can name. The
    two real ones stay read through the call alone; a word the function never
    returns is reported. Held against the template alone: the two bare-path
    lines that used to cover the pair are not in this text."""
    vorlage = "const satz = (quelle) => t(`werkzeuge.${stand(quelle)}`)"
    # The set itself, so that this test falls on the older reading: there the
    # call was read as a word and any key passing by stayed silent.
    assert _werte("stand(quelle)", "frontend/src/teile/Werkzeuge.svelte") == frozenset(
        {"ausgeschaltet", "nicht_verbunden"}
    )
    assert _durch_vorlage("werkzeuge.ausgeschaltet", vorlage)
    assert _durch_vorlage("werkzeuge.nicht_verbunden", vorlage)
    assert not _durch_vorlage("werkzeuge.gibtsnicht", vorlage)


def test_jeder_heute_gelesene_schluessel_bleibt_still():
    """The silence probe the other way round — keys the interface really
    reads stay silent. Without this the guard above could pass for the wrong
    reason: a guard that reports everything is not a guard either.

    Each line names what it holds: the two `nachricht.` keys are the words
    the service sends for that slot and go through the whole-template way;
    `wartewort.<n>` is composed from the catalogue object (frontend/src/
    App.svelte); the two `werkzeuge.` keys are what `stand()` returns
    (teile/Werkzeuge.svelte); `bild.sw_<key>` is a row of the switch table
    (app/image_switches.py, composed by its own helpers); `cronjobs.kind_*`
    walks the list `KINDS` (teile/ScheduleForm.svelte) — each pinned here so
    that the dependency is a promise and not a coincidence.
    """
    assert tote_schluessel(["nachricht.denken_aufgebraucht"]) == []
    assert tote_schluessel(["nachricht.denken_aufgebraucht_eigene_grenze"]) == []
    assert tote_schluessel(["bild.sw_circular"]) == []
    assert tote_schluessel(["cronjobs.kind_agent"]) == []
    assert tote_schluessel([f"wartewort.{nummer}" for nummer in range(1, 11)]) == []
    assert tote_schluessel(["werkzeuge.ausgeschaltet"]) == []
    assert tote_schluessel(["werkzeuge.nicht_verbunden"]) == []


def test_die_wache_liest_die_festen_teile_aus_dem_code():
    """Both shapes really are found — otherwise the silence test above would
    pass for the wrong reason (a guard finding nothing wherever it looks)."""
    assert "jobs.grund." in _teile(False)
    assert ".dauer_ms" in _teile(True)
