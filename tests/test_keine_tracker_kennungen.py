"""No tracker-ID citation survives anywhere in the repository but Markdown.

The pattern this guards against is never spelled out as one literal string
here either — it is built from its parts at run time, the same way the
order behind this test asked for, so that this file's own source could
never be mistaken for a citation and trip the very rule it exists to check.
The scope is the repo's own git index plus whatever it would add next
(``--others --exclude-standard``): the same reach the write-time hook has,
without naming ``node_modules``, ``.venv`` or every other generated folder
by hand — ``.gitignore`` already keeps those out.
"""

from __future__ import annotations

import contextlib
import re
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
FREIE_ENDUNG = ".md"

_PRAEFIX = "EXE"
_ARTEN = "TQDF"


def _muster_teile() -> tuple[str, str]:
    return _PRAEFIX, _ARTEN


def _funde_in_datei(pfad: Path) -> list[int]:
    """Line numbers in `pfad` that carry the pattern — always empty for a
    Markdown file, and for one that will not decode as text, since a binary
    is not a citation and is read as what it is instead of being guessed
    at."""
    import re

    if pfad.suffix.lower() == FREIE_ENDUNG:
        return []
    try:
        text = pfad.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    praefix, arten = _muster_teile()
    muster = re.compile(rf"\b{praefix}_[{arten}]-\d{{4}}\b")
    return [nr for nr, zeile in enumerate(text.splitlines(), start=1) if muster.search(zeile)]


def _repo_dateien(wurzel: Path) -> list[Path]:
    """Every file the repo's git already tracks, plus every file it would
    accept next — the reach ``git add`` has, not the reach of the disk
    underneath it."""
    lauf = subprocess.run(
        ["git", "-C", str(wurzel), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=True,
    )
    namen = lauf.stdout.decode("utf-8").split("\0")
    return [wurzel / name for name in namen if name]


def test_keine_tracker_kennung_in_einer_repo_datei():
    """The rule the write-time hook already enforces per edit, run once over
    the whole tree it protects: no file but Markdown carries a citation."""
    funde = [
        f"{pfad.relative_to(WURZEL)}:{nr}"
        for pfad in _repo_dateien(WURZEL)
        for nr in _funde_in_datei(pfad)
    ]
    assert funde == [], f"Tracker ids found: {', '.join(funde)}"


def test_gegenprobe_eine_geschriebene_kennung_faellt_auf(tmp_path):
    """Writing the shape into any ordinary file makes the check fail, and
    names the file — proving this is a real guard, not green by
    construction."""
    praefix, arten = _muster_teile()
    beispiel = f"{praefix}_{arten[0]}-{9231}"
    ziel = tmp_path / "irgendwas.py"
    ziel.write_text(f"# {beispiel}\n", encoding="utf-8")
    assert _funde_in_datei(ziel) == [1]


def test_schweigeprobe_markdown_bleibt_stumm(tmp_path):
    """The same shape, the same file content, only the ending changed to
    Markdown — and the same check must now stay silent, because that is
    where a citation is meant to live."""
    praefix, arten = _muster_teile()
    beispiel = f"{praefix}_{arten[0]}-{9231}"
    ziel = tmp_path / "bericht.md"
    ziel.write_text(f"{beispiel}\n", encoding="utf-8")
    assert _funde_in_datei(ziel) == []


def test_schweigeprobe_ausserhalb_des_repos_bleibt_stumm():
    """A file that sits on the disk under the repo folder but that git does
    not track and never would (a cache directory, ``.gitignore``d) is
    outside the repo in the sense this check cares about — the scan reaches
    exactly as far as ``git add`` would, not as far as the filesystem does."""
    praefix, arten = _muster_teile()
    beispiel = f"{praefix}_{arten[0]}-{9231}"
    ausserhalb = WURZEL / ".pytest_cache" / "kennungen-schweigeprobe.py"
    # A fresh checkout has no cache folder yet: pytest makes it only once it
    # has something to keep. Made here, it is taken away again, so pytest
    # still lays it out itself.
    cache = ausserhalb.parent
    made_here = not cache.exists()
    cache.mkdir(exist_ok=True)
    ausserhalb.write_text(f"# {beispiel}\n", encoding="utf-8")
    try:
        gefunden = [pfad for pfad in _repo_dateien(WURZEL) if pfad == ausserhalb]
        assert gefunden == []
    finally:
        ausserhalb.unlink(missing_ok=True)
        if made_here:
            # Not empty any more means someone else keeps something in it.
            with contextlib.suppress(OSError):
                cache.rmdir()


# --- Where a sentence came from, instead of what the code does ---------------
#
# A comment, docstring or string in app/ and tests/ says what the code does
# and why. A pointer to the work item, plan step or review that produced it
# means nothing to a reader of the code, and goes stale the moment that
# plan is filed away. The words are put together from their parts here, for
# the same reason as the tracker pattern above: this file's own source must
# never read as the very thing it looks for.

GEPRUEFTE_ORDNER = ("app", "tests")


def _herkunftsmuster() -> list[re.Pattern[str]]:
    auftrag, order = "Auf" + "trag", "Or" + "der"
    stufen = "|".join(("Stu" + "fe", "Schr" + "itt", "Run" + "de"))
    befund = "|".join(("Fu" + "nd", "Befu" + "nd"))
    woerter = "|".join(("Nachbes" + "serung", "Einsp" + "ruch", "Aufse" + "her"))
    return [
        # A work item by its number, in either language.
        re.compile(rf"\b(?:{order}|{order.lower()}|{auftrag}|{auftrag.lower()})s? \d"),
        # A plan step, also when the number wraps onto the next comment line.
        re.compile(rf"\b(?:{stufen})\s+(?:#\s*)?\d"),
        # A review finding by its number or letter.
        re.compile(rf"\b(?:{befund})\s+(?:#\s*)?(?:\d|[A-Z]\b)"),
        # The names of review rounds and reviewers.
        re.compile(rf"\b(?:{woerter})\b"),
        # A numbered phase or extension of an old work plan.
        re.compile(r"\b[Pp]h" + r"ase \d+\.\d|\b\d\.\d ext" + r"ension\b"),
        # A file of the measurement folder beside the repo, or one of its stubs.
        re.compile(r"\bWerk" + r"zeuge/|\batt" + r"rappe-\d"),
    ]


def _herkunft_in_text(text: str) -> list[int]:
    zeilen = []
    for muster in _herkunftsmuster():
        for treffer in muster.finditer(text):
            zeilen.append(text.count("\n", 0, treffer.start()) + 1)
    return sorted(set(zeilen))


def test_kein_verweis_auf_auftrag_plan_oder_review_im_code():
    """Comments, docstrings and strings in app/ and tests/ name the thing,
    not where it came from."""
    funde = [
        f"{pfad.relative_to(WURZEL)}:{nr}"
        for ordner in GEPRUEFTE_ORDNER
        for pfad in sorted((WURZEL / ordner).rglob("*.py"))
        for nr in _herkunft_in_text(pfad.read_text(encoding="utf-8"))
    ]
    assert funde == [], f"References to work items found: {', '.join(funde)}"


@pytest.mark.parametrize(
    "beispiel",
    [
        "# measured for or" + "der 613",
        '"""Auf' + 'trag 20: the table."""',
        "# retired in Stu" + "fe 8",
        "# the guard (Schr" + "itt 9,\n# Run" + "de 2)",
        "# (Nachbes" + "serung Fu" + "nd C)",
        '"""Befu' + 'nd 2: nothing between."""',
        "# (Einsp" + "ruch, Aufse" + "her)",
        '"""Jobs (ph' + 'ase 6.2)."""',
        "# see Werk" + "zeuge/att" + "rappe-607-cache.py",
    ],
)
def test_gegenprobe_ein_geschriebener_verweis_faellt_auf(beispiel):
    """Every shape the guard knows makes it fail when it is written into a
    file — proving it is a real guard, not green by construction."""
    assert _herkunft_in_text(beispiel)


def test_schweigeprobe_gewoehnliche_woerter_bleiben_stumm():
    """English prose, identifiers and test data that merely look alike stay
    silent: a step of a migration, a table cell, a lower-case file name."""
    text = (
        "# migration 28 adds five columns, in order\n"
        'bericht = "| Schritt | 1 |"\n'
        'denken = f"Schritt {i} "\n'
        "# see tests/test_stufe9_nachbesserung.py\n"
        "# a round of 3 tools, step 2 of the fold\n"
    )
    assert _herkunft_in_text(text) == []
