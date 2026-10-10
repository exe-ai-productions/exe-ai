"""THIRD_PARTY_NOTICES.md has to name every library the package ships.

What is packaged is the transitive closure of requirements.txt — with the
two test-only packages, and whatever depends on nothing else, left out
(deploy/exe-ai-terminal.spec:127 never bundles pytest either way). The
closure is walked live against the installed environment rather than a
written-down list, so a new pin in requirements.txt cannot silently ship
without its own section here.

The frontend's libraries are measured the same way, from what the built
bundle really contains: the `sources` of its source map (the package names under
`node_modules/`), plus vite, whose module-preload polyfill is written into the
bundle and appears in no source map.

The shell's libraries are walked like requirements.txt: the `dependencies` of
`fenster-electron/package.json` and whatever they ask for in turn, each read
from its own `package.json` in `node_modules`.
"""

from __future__ import annotations

import json
import re
from importlib import metadata
from pathlib import Path

import pytest

from packaging.markers import default_environment
from packaging.requirements import Requirement

WURZEL = Path(__file__).resolve().parent.parent
NOTICES = (WURZEL / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
REQUIREMENTS = WURZEL / "requirements.txt"

# Excluded from the shipped package (deploy/exe-ai-terminal.spec:124) and so
# from this measurement too — nothing they alone depend on ships either.
TESTWERKZEUGE = frozenset({"pytest", "pytest-asyncio"})

# Two target platforms, not the one this test happens to run on: a marker
# such as `sys_platform == 'win32'` must not drop colorama just because the
# build machine is a Mac, and the same the other way round for uvloop.
_UMGEBUNGEN = [
    {**default_environment(), "sys_platform": "darwin"},
    {**default_environment(), "sys_platform": "win32"},
]


def _kurzname(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirements_wurzeln() -> list[Requirement]:
    wurzeln = []
    for zeile in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        zeile = zeile.split("#", 1)[0].strip()
        if not zeile:
            continue
        anforderung = Requirement(zeile)
        if _kurzname(anforderung.name) not in {_kurzname(t) for t in TESTWERKZEUGE}:
            wurzeln.append(anforderung)
    return wurzeln


def _mitgelieferte_bibliotheken() -> set[str]:
    """The transitive closure requirements.txt ships, on either target
    platform, minus the two test packages — by their own short name.

    A package can be reached twice with a different set of extras — plain
    `httpx` as a root of requirements.txt, and `httpx[brotli,http2,socks]`
    through ddgs's own Requires-Dist. Marking a name visited on the first
    encounter and skipping every later one would make the result depend on
    which of the two the stack happens to pop first: whichever loses the
    race never has its extras-gated dependents (h2, brotli, socksio, …)
    evaluated at all. Each name instead keeps the union of every extras set
    it has been seen with, and is re-walked whenever a visit adds extras
    beyond that union.
    """
    besucht: set[str] = set()
    bekannte_extras: dict[str, frozenset[str]] = {}
    ausgeschlossen = {_kurzname(t) for t in TESTWERKZEUGE}
    warteschlange = [(a.name, frozenset(e.lower() for e in a.extras)) for a in _requirements_wurzeln()]

    while warteschlange:
        name, extras = warteschlange.pop()
        schluessel = _kurzname(name)
        if schluessel in ausgeschlossen:
            continue
        bereits_bekannt = bekannte_extras.get(schluessel, frozenset())
        if schluessel in besucht and extras <= bereits_bekannt:
            continue
        besucht.add(schluessel)
        bekannte_extras[schluessel] = bereits_bekannt | extras
        try:
            eintraege = metadata.metadata(name).get_all("Requires-Dist") or []
        except metadata.PackageNotFoundError:
            continue
        for eintrag in eintraege:
            kind = Requirement(eintrag)
            if _kurzname(kind.name) in ausgeschlossen:
                continue
            if kind.marker is not None:
                passt = any(
                    kind.marker.evaluate({**umgebung, "extra": extra})
                    for umgebung in _UMGEBUNGEN
                    for extra in (bekannte_extras[schluessel] or {""})
                )
                if not passt:
                    continue
            warteschlange.append((kind.name, frozenset(e.lower() for e in kind.extras)))
    return besucht


def _section_first_words() -> set[str]:
    """The first word of every `## name — licence` heading. A licence text
    may carry `## ` lines of its own; without the dash they head no section."""
    return {_kurzname(word) for word in re.findall(r"(?m)^## (\S+).* — ", NOTICES)}


def test_jede_mitgelieferte_bibliothek_hat_einen_abschnitt():
    sections = _section_first_words()
    fehlend = sorted(name for name in _mitgelieferte_bibliotheken() if _kurzname(name) not in sections)
    assert not fehlend, f"missing sections for: {', '.join(fehlend)}"


def test_die_testwerkzeuge_brauchen_keinen_abschnitt():
    """The silence probe: pytest and pytest-asyncio stay out of the
    package, so they never have to appear here, and neither does anything
    that exists only for their sake (already excluded from the walk)."""
    gefunden = _mitgelieferte_bibliotheken()
    assert not gefunden & {_kurzname(t) for t in TESTWERKZEUGE}


# --- The frontend's libraries, read from the built bundle ------------------

KARTEN = sorted((WURZEL / "static/app/assets").glob("*.js.map"))

# Written into the bundle by the build, so no source map names it.
IMMER_IM_BUNDLE = frozenset({"vite"})

# Build and check tools: they never end up in the bundle, so a section for
# them would only say something untrue.
NUR_ENTWICKLUNG = frozenset({"svelte-check", "@sveltejs/vite-plugin-svelte"})


def _bundle_pakete() -> set[str]:
    pakete: set[str] = set(IMMER_IM_BUNDLE)
    for karte in KARTEN:
        for quelle in json.loads(karte.read_text(encoding="utf-8"))["sources"]:
            treffer = re.search(r"node_modules/((?:@[^/]+/)?[^/]+)/", quelle)
            if treffer:
                pakete.add(treffer.group(1))
    return pakete


def _abschnittsnamen() -> set[str]:
    """The library name in front of the dash of every `## name — licence`."""
    return {name.strip().lower() for name in re.findall(r"(?m)^## (.+?) — ", NOTICES)}


@pytest.mark.skipif(not KARTEN, reason="the frontend is not built (static/app is not in git)")
def test_jede_bundle_bibliothek_hat_einen_eigenen_abschnitt():
    fehlend = sorted(p for p in _bundle_pakete() if p.lower() not in _abschnittsnamen())
    assert not fehlend, f"missing sections for: {', '.join(fehlend)}"
    assert {"svelte", "highlight.js", "vite"} <= _bundle_pakete(), "the measurement lost its anchors"


@pytest.mark.skipif(not KARTEN, reason="the frontend is not built (static/app is not in git)")
def test_entwicklungswerkzeuge_haben_keinen_abschnitt():
    """The silence probe: what only builds or checks the frontend is not in
    the bundle and gets no section."""
    assert not _bundle_pakete() & NUR_ENTWICKLUNG
    assert not _abschnittsnamen() & NUR_ENTWICKLUNG


# --- The shell's libraries, walked from its package.json -------------------

SHELL = WURZEL / "fenster-electron"

# What a package asks for and the packed shell carries. `devDependencies`
# build and pack the shell and stay outside it, and a peer is not packed for
# the package that names it.
SHIPPED_FIELDS = ("dependencies", "optionalDependencies")


def _asked_for(folder: Path) -> list[str]:
    package = json.loads((folder / "package.json").read_text(encoding="utf-8"))
    return [name for field in SHIPPED_FIELDS for name in package.get(field, {})]


def _installed_at(name: str, asked_from: Path) -> Path | None:
    """The folder a package in `asked_from` is handed when it asks for
    `name`: the nearest `node_modules` on the way up to the shell's own."""
    folder = asked_from
    while True:
        candidate = folder / "node_modules" / name
        if (candidate / "package.json").is_file():
            return candidate
        if folder == SHELL:
            return None
        folder = folder.parent


def _shell_packages() -> set[str]:
    """The transitive closure of the shell's `dependencies`, by name.

    Each package is read where it would be found from the one that asks for
    it, so a nested copy answers with its own list. A name counts the moment
    it is asked for: an optional package this machine did not install may
    still be installed where the other platform is packed.
    """
    names: set[str] = set()
    walked: set[Path] = set()
    queue = [(name, SHELL) for name in _asked_for(SHELL)]
    while queue:
        name, asked_from = queue.pop()
        names.add(name)
        folder = _installed_at(name, asked_from)
        if folder is None or folder in walked:
            continue
        walked.add(folder)
        queue.extend((child, folder) for child in _asked_for(folder))
    return names


SHELL_INSTALLED = all(_installed_at(name, SHELL) for name in _asked_for(SHELL))
NOT_INSTALLED = "the shell's packages are not installed (fenster-electron/node_modules is not in git)"


@pytest.mark.skipif(not SHELL_INSTALLED, reason=NOT_INSTALLED)
def test_every_shell_package_has_its_own_section():
    packages, sections = _shell_packages(), _abschnittsnamen()
    missing = sorted(name for name in packages if name.lower() not in sections)
    assert not missing, f"missing sections for: {', '.join(missing)}"
    assert {"electron-updater", "builder-util-runtime"} <= packages, "the measurement lost its anchors"


@pytest.mark.skipif(not SHELL_INSTALLED, reason=NOT_INSTALLED)
def test_what_only_builds_the_shell_needs_no_section():
    """The silence probe: what runs or packs the shell from outside is not
    part of the walk and gets no section."""
    build_only = set(json.loads((SHELL / "package.json").read_text(encoding="utf-8"))["devDependencies"])
    assert {"electron", "electron-builder"} <= build_only
    assert not _shell_packages() & build_only
    assert not _abschnittsnamen() & build_only


def test_a_heading_inside_a_license_text_heads_no_section():
    """The silence probe for a licence written in Markdown: its own `## `
    lines stand inside the fence and name no library."""
    assert "\n## Purpose\n" in NOTICES, "the measurement lost its anchor"
    assert "purpose" not in _section_first_words()
    assert "purpose" not in _abschnittsnamen()


def test_die_hinweise_liegen_im_electron_paket():
    paket = json.loads((WURZEL / "fenster-electron/package.json").read_text(encoding="utf-8"))
    eintraege = paket["build"]["extraResources"]
    assert {"from": "../THIRD_PARTY_NOTICES.md", "to": "THIRD_PARTY_NOTICES.md"} in eintraege
    assert not (WURZEL / "static/DRITTANBIETER.md").exists(), "the notices live in one file"
