"""House rules the code has to keep, enforced instead of remembered.

A rule that lives only in a document gets read once and forgotten; one that
fails the suite stays kept.

  1. Comments, docstrings and commit messages are ENGLISH. German is the
     language between people, not in the source.
  2. No person's name in a comment. The reasoning stays, the origin goes —
     decisions belong in the log, not in a source file.
  3. No interface text hardcoded in a component. Whatever is not in the
     catalogue can never be translated, and nobody notices until they open
     the window in the other language.

Rule 2 is counted: a counter that only ever reads zero keeps it that way.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path
from uuid import uuid4

import pytest

WURZEL = Path(__file__).resolve().parent.parent
# The whole of frontend/, not just frontend/src/: the build configuration in
# the root folder is source too, and a rule that stops at the src boundary
# lets exactly those files through unchecked.
DURCHSUCHT = ("app", "tests", "frontend")
ENDUNGEN = (".py", ".js", ".svelte")

# How many name references a comment may carry: none. The counter stays at
# zero; never raise it.
NAMEN_OBERGRENZE = 0

# Words that occur in German and not in English. Two of them in one comment
# is the signal — a single one can be an English word that happens to look
# German ("the loop must never die").
# Words that exist in German and NOT in English. "die" was in this list and
# is an ordinary English verb — it is what made an entirely English sentence
# read as German. A guard that cries at correct code is a guard nobody
# believes, and once it is permanently red every other red test hides behind
# it.
DEUTSCHE_WOERTER = {
    "der", "das", "und", "nicht", "wird", "werden", "über", "für",
    "kein", "keine", "muss", "soll", "darf", "dann", "noch", "schon", "beim",
    "vom", "zum", "eine", "einen", "einem", "wenn", "aber", "auch", "sich",
    "nur", "sind", "ist", "haben", "hat", "wurde", "diese", "dieser", "damit",
    "weil", "durch", "gegen", "ohne", "steht", "gibt", "macht",
}


def _dateien():
    for teil in DURCHSUCHT:
        for pfad in (WURZEL / teil).rglob("*"):
            if pfad.suffix in ENDUNGEN and "node_modules" not in str(pfad):
                yield pfad


def _kommentare(pfad: Path):
    """Every comment and docstring of a file, as (line number, text)."""
    text = pfad.read_text(errors="replace")
    if pfad.suffix == ".py":
        for nr, zeile in enumerate(text.splitlines(), 1):
            if "#" in zeile:
                yield nr, zeile[zeile.index("#"):]
        for treffer in re.finditer(r'"""(.*?)"""', text, re.S):
            yield text[: treffer.start()].count("\n") + 1, treffer.group(1)
        return
    for muster in (r"//(.*)$", r"/\*(.*?)\*/", r"<!--(.*?)-->"):
        flags = re.M if muster.endswith("$") else re.S
        for treffer in re.finditer(muster, text, flags):
            yield text[: treffer.start()].count("\n") + 1, treffer.group(1)


# What a comment quotes is not what a comment SAYS. An English sentence
# naming ``test_grenze_haelt_an_und_meldet_einmal`` carries German words only
# because it names a German identifier, and renaming the identifier to please
# a test would be the tail wagging the dog. Quoted IDENTIFIERS come out
# before the words are counted — a backtick span without a space. A span with
# spaces in it is a sentence in backticks, and a German sentence does not
# stop being German for being quoted.
ZITAT = re.compile(r"``[^`\s]+``|`[^`\s]+`|\b[A-Za-zÄÖÜäöüß]+_[A-Za-zÄÖÜäöüß_]+\b")


def _ist_deutsch(kommentar: str) -> bool:
    ohne_zitate = ZITAT.sub(" ", kommentar)
    woerter = {w.lower() for w in re.findall(r"[A-Za-zÄÖÜäöüß]+", ohne_zitate)}
    return len(woerter & DEUTSCHE_WOERTER) >= 2


def test_kein_deutscher_kommentar_im_quelltext():
    """A comment carrying two German-only words is German, not English."""
    gefunden = []
    for pfad in _dateien():
        for nr, kommentar in _kommentare(pfad):
            if _ist_deutsch(kommentar):
                knapp = " ".join(kommentar.split())[:70]
                gefunden.append(f"{pfad.relative_to(WURZEL)}:{nr}  {knapp}")
    assert not gefunden, "German comments in the source:\n" + "\n".join(gefunden)


def test_ein_deutscher_satz_in_backticks_wird_gemeldet():
    """Only an identifier in backticks is a quote; a sentence is still a
    sentence."""
    assert _ist_deutsch("See `das wird nicht gebaut, weil es fehlt` here.")
    assert _ist_deutsch("``der Knopf ist nur da, wenn es geht``")


def test_ein_bezeichner_in_backticks_wird_nicht_gemeldet():
    """The silent case: a German identifier named in an English sentence."""
    assert not _ist_deutsch("Reads `nicht` and `wird` from ``keine_ist``.")


# --- The message list the chat draws ---------------------------------------


def test_die_anzeigeschleife_reicht_keine_ungepruefte_liste_weiter():
    """The loop runs over ``nachrichtenAnzeige()``, the list checked against
    the chat it belongs to. A helper inside that loop handed the raw
    ``zustand.nachrichten`` instead would read another chat's messages in the
    moment between a chat switch and its load."""
    text = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")
    start = text.index("{#each nachrichtenAnzeige() as nachricht")
    # The loop's own nested blocks close with {/each} too; take the whole
    # stretch up to the matching close by counting.
    tiefe, pos = 0, start
    for treffer in re.finditer(r"\{#each\b|\{/each\}", text[start:]):
        tiefe += 1 if treffer.group().startswith("{#") else -1
        if tiefe == 0:
            pos = start + treffer.end()
            break
    assert pos != start, "the loop's {#each} never closes"
    schleife = text[start:pos]
    # The list itself, not zustand.nachrichtenChatId beside it.
    assert not re.search(r"\bzustand\.nachrichten\b", schleife)


def test_keine_zufallskennung_die_ueber_http_fehlt():
    """``crypto.randomUUID`` exists only in a secure context. Over plain HTTP
    (a Tailscale address) it is missing, and the code calling it dies."""
    stellen = [
        f"{pfad.relative_to(WURZEL)}:{nr}"
        for pfad in (WURZEL / "frontend/src").rglob("*")
        if pfad.suffix in ENDUNGEN
        for nr, zeile in _zeilen(pfad)
        # Any reach for it — a call, `?.`, a lookup, a destructuring — once
        # the identifiers a comment quotes in backticks are taken out.
        if "randomUUID" in re.sub(r"`[^`\n]*`", " ", zeile)
    ]
    assert not stellen, stellen


def test_die_kennung_des_hauptmodells_steht_einmal():
    """The main model's endpoint id is named in one module; a copy elsewhere
    would be left behind by a rename."""
    stellen = [
        pfad.relative_to(WURZEL).as_posix()
        for pfad in (WURZEL / "frontend/src").rglob("*")
        if pfad.suffix in ENDUNGEN
        # A string literal; a comment naming `runner` in backticks is prose.
        and re.search(r"['\"]runner['\"]|kennung:runner", pfad.read_text(encoding="utf-8"))
    ]
    assert stellen == ["frontend/src/lib/agentenserver.svelte.js"], stellen


def _zeilen(pfad: Path):
    """Every line of a file, as (line number, text) -- not just its
    comment portion. A name in a string literal (a test's own file name,
    an example value, a fixture) is exactly as much a name as one in
    prose; scanning only comments left that whole other half of the
    source unchecked."""
    for nr, zeile in enumerate(pfad.read_text(errors="replace").splitlines(), 1):
        yield nr, zeile


def test_namensnennungen_werden_nicht_mehr():
    """No comment, docstring, or string literal carries a person's name --
    no exceptions. A name that only stands in as plausible test data
    (an address setting's own tests, an escaping test's example folder)
    is carried just as well by any other name, so it has no reason to
    be the real one -- least of all the setting whose whole purpose is
    to carry a real name, which is closer to the risk this rule guards
    against, not further from it.

    Case-insensitive: a filename or identifier lowercases a name as a
    matter of convention, not intent -- it is exactly as much a name as
    the capitalised word.
    """
    stellen = [
        f"{pfad.relative_to(WURZEL)}:{nr}"
        for pfad in _dateien()
        for nr, zeile in _zeilen(pfad)
        if re.search(r"\bChris\b", zeile, re.IGNORECASE)
    ]
    assert len(stellen) <= NAMEN_OBERGRENZE, (
        f"{len(stellen)} name references, {NAMEN_OBERGRENZE} allowed. New ones:\n"
        + "\n".join(stellen[NAMEN_OBERGRENZE:])
    )


# Where a literal really is allowed to stand in the markup: the product name
# is a proper noun and reads the same in every language.
TEXT_ERLAUBT = {"frontend/src/teile/Wortmarke.svelte"}


def _ohne_ausdruecke(stueck: str) -> str:
    """Strips {...} including nested braces.

    A counter and not a pattern, because `{t('x', { a: b })}` has braces
    inside it — a non-greedy pattern stops at the inner one and leaves the
    rest looking like prose.
    """
    raus, tiefe = [], 0
    for zeichen in stueck:
        if zeichen == "{":
            tiefe += 1
        elif zeichen == "}":
            tiefe = max(0, tiefe - 1)
        elif tiefe == 0:
            raus.append(zeichen)
    return "".join(raus)


def test_kein_oberflaechentext_steht_fest_im_bauteil():
    """Visible words that never pass through t() cannot be translated.

    Checked are text between tags and the three attributes a person reads:
    title, placeholder, aria-label. Everything inside {...} is an expression
    and none of this business.
    """
    gefunden = []
    for pfad in (WURZEL / "frontend/src").rglob("*.svelte"):
        if pfad.relative_to(WURZEL).as_posix() in TEXT_ERLAUBT:
            continue
        markup = re.sub(
            r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", pfad.read_text(encoding="utf-8")
        )
        markup = re.sub(r"<!--[\s\S]*?-->", "", markup)
        for nr, zeile in enumerate(markup.splitlines(), 1):
            stuecke = re.findall(r">([^<>]*)<", zeile)
            stuecke += [
                wert
                for _, wert in re.findall(
                    r'\b(title|placeholder|aria-label)="([^"]*)"', zeile
                )
            ]
            for stueck in stuecke:
                woerter = re.findall(
                    r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß'’-]{2,}", _ohne_ausdruecke(stueck)
                )
                if woerter:
                    gefunden.append(
                        f"{pfad.relative_to(WURZEL)}:{nr}  {' '.join(stueck.split())[:60]}"
                    )
    assert not gefunden, (
        "Interface text fixed in the component instead of the catalogue:\n" + "\n".join(gefunden)
    )


TAFELKOPF_FORM = re.compile(
    r"font:\s*600\s*var\(--schrift-abschnitt\)\s*var\(--schrift\);\s*"
    r"letter-spacing:\s*normal;\s*"
    r"text-transform:\s*none;\s*"
    r"color:\s*var\(--text\);",
)


def test_die_servertafel_ueberschrift_steht_nur_noch_einmal():
    """The house form for a server-panel section heading — the section size token, the
    system face, sentence case, --text, 600 — used to stand written out in
    five different files; one of them drifting from the rest went unnoticed
    for a while, because nothing tied them together."""
    treffer = [
        pfad.relative_to(WURZEL)
        for pfad in (WURZEL / "frontend/src").rglob("*")
        if pfad.suffix in (".svelte", ".css") and TAFELKOPF_FORM.search(pfad.read_text(encoding="utf-8"))
    ]
    assert treffer == [Path("frontend/src/stil/global.css")], (
        f"the server-panel heading form stands somewhere besides its one "
        f"shared place: {treffer}"
    )


def test_die_fuenf_servertafeln_tragen_dieselbe_ueberschrift_klasse():
    """Schweigeprobe: the panels the order names still wear the heading.
    Every section head of a server window is drawn by one part
    (Serverabschnitt.svelte), and that part wears the shared class; the
    panels draw their sections through it and carry no copy of the form."""
    abschnitt = (WURZEL / "frontend/src/teile/Serverabschnitt.svelte").read_text(encoding="utf-8")
    assert "tafelkopf" in abschnitt, "the section part no longer wears the shared heading class"
    for datei in (
        "Servertafel.svelte", "Serverregler.svelte", "Sprachserver.svelte",
        "Bildserver.svelte", "Parametertafel.svelte",
    ):
        quelle = (WURZEL / "frontend/src/teile" / datei).read_text(encoding="utf-8")
        assert "<Serverabschnitt" in quelle, f"{datei} no longer draws its sections through the shared part"
        assert not TAFELKOPF_FORM.search(quelle), f"{datei} carries its own copy of the heading form"


def test_einbettungsserver_hat_keine_eigene_ueberschrift_regel_mehr():
    """`PORT` on the embedding panel used to carry its own, differently
    sized and coloured heading form — now it wears the same one as every
    other panel."""
    quelle = (WURZEL / "frontend/src/teile/Einbettungsserver.svelte").read_text(encoding="utf-8")
    assert not TAFELKOPF_FORM.search(quelle)
    assert "font-size: 12px" not in quelle
    assert "letter-spacing: 0.03em" not in quelle
    # Its port section is drawn by the shared settings part, whose head is
    # the shared one.
    assert "<Serverregler" in quelle


def test_ruf_ergaenzt_eigene_kopfzeilen_statt_sie_zu_ersetzen():
    """A caller's own `headers` (raw-byte uploads set their own Content-Type)
    must ADD to the ones `ruf()` builds, never replace them outright.

    The incident this guards against: spreading the caller's whole options
    object after a `headers` object in the same fetch call overwrites that
    key wholesale, not field by field. That silently dropped the session
    key from every call with its own headers — three of them, image
    upload among them, so picture-to-picture came back 401 on a valid
    picture.

    Source-text only, not a behavioral test: it catches exactly this
    bauform coming back, not every way a header could get lost. The
    running behavior (a real upload answering 201) was checked by hand
    against the service, not here.
    """
    quelle = (WURZEL / "frontend/src/lib/api.js").read_text(encoding="utf-8")
    # Found by what it DOES, not by what it is called. `ruf` was later split
    # into a thin wrapper over `rufRoh`, the fetch moved with the body, and
    # a guard anchored on the name went on passing over an empty wrapper —
    # a source-text rule that can be disarmed by a rename guards nothing.
    rumpf = None
    for treffer in re.finditer(
        r"async function \w+\([^)]*\)\s*\{.*?\n\}", quelle, re.S
    ):
        if "fetch(BASIS + pfad" in treffer.group(0):
            rumpf = treffer.group(0)
            break
    assert rumpf, "the function with the fetch on BASIS was not found"

    # The caller's headers must be pulled out of `optionen` before any of
    # it reaches the fetch call.
    ausgepackt = re.search(
        r"const\s*\{\s*headers:\s*(\w+)\s*,\s*\.\.\.(\w+)\s*\}\s*=\s*optionen", rumpf
    )
    assert ausgepackt, "the caller no longer splits `optionen` into headers and the rest"
    eigene, rest = ausgepackt.groups()

    # Only that leftover — never the raw `optionen` — may be spread at the
    # top level of the fetch call; a bare `...optionen` there is exactly
    # the old bauform, since it would carry a `headers` key of its own.
    assert re.search(rf"\.\.\.{rest}\b", rumpf), f'...{rest} is no longer spread into fetch()'
    assert not re.search(r"\.\.\.optionen\b", rumpf), "...optionen appears raw in fetch() again"

    # And the caller's headers must land INSIDE the shared `headers`
    # object, so they add Content-Type without erasing the session key.
    header_objekt = re.search(r"headers:\s*\{(.*?)\n\s*\},", rumpf, re.S)
    assert header_objekt and re.search(rf"\.\.\.{eigene}\b", header_objekt.group(1)), (
        f'...{eigene} no longer lands in the shared headers object'
    )


def test_kein_fetch_haengt_den_schluessel_an_die_adresse():
    """A `fetch` carries the session key in its header, never in the URL.

    `mitSchluessel` exists for the two places a browser cannot attach a
    header at all — EventSource and a plain <img src>/href. A `fetch` is
    not one of them: it can send `X-Sitzungsschluessel` like every other
    call, and a key in the query string travels on into the service log,
    the referrer and the browser history for no gain.

    Three drop paths did it anyway — the note dock, the agents' shelf and
    the picture wall. Source-text only: it catches the address builder
    being handed to a fetch, which is exactly the bauform that came back
    three times.
    """
    wurzel = WURZEL / "frontend/src"
    an_der_adresse = re.compile(r"fetch\(\s*(?:api\.)?(?:\w*(?:Adresse|Address)|mitSchluessel)\(")
    funde = []
    for pfad in wurzel.rglob("*"):
        if pfad.suffix not in (".js", ".svelte"):
            continue
        for nummer, zeile in enumerate(pfad.read_text(encoding="utf-8").splitlines(), 1):
            if an_der_adresse.search(zeile):
                funde.append(f"{pfad.relative_to(WURZEL)}:{nummer}")
    assert not funde, "fetch() builds the address with the key again: " + ", ".join(funde)

    # The silent half: the builders themselves stay. They are what an
    # <img src> and an EventSource need, and a guard that drove them out
    # would break the very places the query parameter exists for.
    api = (WURZEL / "frontend/src/lib/api.js").read_text(encoding="utf-8")
    for name in ("docFolderAddress", "bildAdresse"):
        assert f"{name}: (" in api, f"{name} is gone — <img src> has no other way"
    # And each one has a header-carrying twin for the fetch callers, going
    # through the shared caller rather than building a fetch of its own.
    for name in ("docFolderBlob", "bildBlob"):
        zwilling = re.search(rf"{name}: \([^)]*\) => (\w+)\(", api)
        assert zwilling, f"{name} is missing"
        assert zwilling.group(1) == "rufRoh", (
            f"{name} no longer goes through rufRoh, so it carries no session key header"
        )


def _zweig(quelle: str, ereignis: str) -> str:
    """The body of one `else if (ereignis.typ === '<name>')` branch."""
    anfang = quelle.find(f"ereignis.typ === '{ereignis}'")
    assert anfang > 0, f"the branch for {ereignis} is gone"
    rest = quelle[anfang:]
    ende = rest.find("} else if (ereignis.typ ===")
    return rest[:ende] if ende > 0 else rest


def test_das_wachsende_werkzeug_argument_wird_gesagt_und_gezaehlt():
    """While the model writes a long tool argument, the window says how far
    it has got — and the speed display counts it.

    The service has been sending `zeichen` with every `tool_call_laeuft`
    packet since the reporters were built; nobody read it. The window
    showed the bare name, so a growing argument looked exactly like a
    stuck one.

    Source-text, and one half only since the estimate was removed: the notice
    is given the figure. The other half used to feed a speed bar out of these
    characters — that bar is gone, and with it the estimate behind it: the
    displayed speed now comes from the tokens the server counted, so a
    growing argument no longer has a reading to feed (Nachricht.svelte,
    the foot under the answer).
    """
    app = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")
    zweig = _zweig(app, "tool_call_laeuft")

    # Half one: the notice carries the count, not only the name.
    assert "werkzeug.schreibt" in zweig, "the branch no longer names the notice"
    assert re.search(r"zeichen:\s*ereignis\.zeichen", zweig), (
        "the notice is given only the name again — the figure the service sends is dropped"
    )
    # And a text that cannot show it would make the figure pointless.
    for sprache in ("de", "en"):
        katalog = json.loads((WURZEL / f"app/locales/{sprache}.json").read_text(encoding="utf-8"))
        satz = katalog["werkzeug"]["schreibt"]
        assert "{zeichen}" in satz, f"{sprache}.json: werkzeug.schreibt has no place for the figure"


def test_zahlenfeld_rundet_nur_die_bildzahl():
    """H3: Zahlenfeld.svelte only ever clamped a typed value
    into [min, max] — a typed "2.5" survived untouched, and the picture
    count field is the one caller whose value cannot carry a fraction:
    it becomes `von` in a request the server rejects with 422 unless it
    is a whole number.

    Fixed as an opt-in `ganzzahlig` prop, off by default, so the shared
    component's ten OTHER callers (cfg among them, where a fraction like
    7.5 is an ordinary value) keep clamping exactly as before.

    Source-text only, not a behavioral test: it catches the wiring
    coming apart, not every way a fraction could reach a request. The
    running behavior (a real "2.5" producing exactly two requests with
    an integer `von`) was checked by hand against the service, not here.
    """
    zahlenfeld = (WURZEL / "frontend/src/teile/Zahlenfeld.svelte").read_text(encoding="utf-8")

    setzen = re.search(r"function setzen\([^)]*\)\s*\{.*?\n  \}", zahlenfeld, re.S)
    assert setzen, "setzen() not found"
    assert re.search(r"ganzzahlig\s*\?\s*Math\.trunc", setzen.group(0)), (
        "setzen() no longer rounds once ganzzahlig is set"
    )

    studio = (WURZEL / "frontend/src/teile/StudioBasics.svelte").read_text(encoding="utf-8")
    zeilen = [z for z in studio.splitlines() if "<Zahlenfeld" in z]
    tragen_ganzzahlig = [z for z in zeilen if "bind:wert={werte.bilder_je_lauf}" in z]
    cfg = [z for z in zeilen if "bind:wert={werte.cfg}" in z]

    assert tragen_ganzzahlig and all("ganzzahlig" in z for z in tragen_ganzzahlig), (
        "the picture-count field does not carry the ganzzahlig property (any more)"
    )
    # H3 is the picture-count bug, not a rebuild of the whole component: a
    # field whose fraction is an ordinary value (cfg) must keep clamping
    # only, unchanged.
    assert cfg and not any("ganzzahlig" in z for z in cfg), (
        "the cfg field in StudioBasics.svelte now carries ganzzahlig too -- a "
        "fraction like 7.5 is an ordinary value there"
    )


def test_bildlauf_kachel_bricht_ueber_die_textspalte_aus():
    """K3: the picture row was capped at exactly two
    tiles' worth of the OLD, fixed 260/318px tile size, and the row's
    own max-width lived inside the text column (`--chat-breite`,
    720/810/890) with no way to be wider — raising the tile size (K1,
    then K1b) never actually widened the row, since the tile itself grew
    with the interface's own zoom level while the row's cap stayed a
    flat number, breaking two-per-row at "gross"/"groesser".

    Fixed by breaking the row out of the text column (a picture has
    none of the readability reason that column is capped for) up to
    `.verlauf`'s own width — container query units, not viewport ones,
    so the row stops at the sidebar rather than sliding under it — and
    by giving each tile's own wrapper a percentage width instead of a
    fixed pixel one, so the row and every tile in it shrink together on
    a narrow window instead of overflowing or falling back to one tile
    per line.

    Source-text only, not a behavioral test: it catches the wiring
    coming apart, not every window size that could break. The running
    behavior (two tiles side by side at all three interface levels, and
    a simulated narrow container shrinking both the row and its tiles
    together with no overflow) was checked by hand against the service,
    not here.
    """
    quelle = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")

    # The NUMBER is what was signed off, not the spelling around it. The
    # tile size is the user's now (the layout mode); 700 is its factory
    # value, and App.svelte reads it from the state.
    layout = (WURZEL / "frontend/src/lib/chatlayout.js").read_text(encoding="utf-8")
    assert re.search(r"id:\s*'bildkachel'[^}]*standard:\s*700\b", layout), (
        "the picture tile's factory value is no longer 700 -- the accepted number is missing"
    )
    assert re.search(r"BILDLAUF_KACHEL\s*=\s*\$derived\(zustand\.chatlayout\.bildkachel\)", quelle), (
        "BILDLAUF_KACHEL no longer follows the chat layout"
    )
    assert re.search(r"\.verlauf\s*\{[^}]*container-type:\s*inline-size", quelle, re.S), (
        "verlauf no longer carries a container-type -- the tile row would have no "
        "frame of reference left to shrink or break out against without sliding "
        "under the sidebar"
    )
    raster_regel = re.search(r"\.spur > \.bildlauf-raster\s*\{.*?\n  \}", quelle, re.S)
    assert raster_regel, ".spur > .bildlauf-raster rule not found"
    assert re.search(r"cqw", raster_regel.group(0)), (
        "the tile row no longer measures itself against the container (cqw) -- a "
        "narrow window would overflow again or the row would stay bound to the text "
        "column"
    )
    platz_regel = re.search(r"\.bildlauf-platz\s*\{.*?\n  \}", quelle, re.S)
    assert platz_regel, ".bildlauf-platz rule not found"
    # Both declarations checked on their OWN line, not just "somewhere in
    # the block": `flex` alone still carries its own `calc(50% - 6px)`
    # even with `max-width` weakened to `auto` next to it, so a check
    # against the whole block's text would stay green while the actual
    # clamp is gone (measured: window 1400, "2 + 2" becomes "3 + 1",
    # tiles stuck at 219px regardless of window width).
    # The basis is `auto` on purpose since the "verschraenkt" report: a
    # forced half-row made a picture narrower than its box leave the
    # remainder standing inside it, and with two tiles that remainder
    # collected in the middle. What actually guards the measured
    # regression below is the max-width clamp, not the basis — so the
    # basis is only checked for not being a fixed pixel size, which
    # would take the row's shrinking with it.
    assert re.search(r"flex:\s*0 1 auto", platz_regel.group(0)), (
        "the tile shell no longer sets flex-basis to its content (auto) -- a picture "
        "narrower than its box would leave the rest of the box standing again"
    )
    assert re.search(r"max-width:\s*calc\(50% -", platz_regel.group(0)), (
        "the tile shell no longer clamps max-width to half its row -- on a narrow "
        "window the row would shrink while the tiles stayed fixed and fell back to "
        "one per row"
    )


def test_a_generated_picture_frame_is_as_wide_as_its_picture():
    """The frame of a generated picture hugs the picture: its cap is the
    picture's cap plus the frame's own edge, and the row of a run counts
    exactly that edge per tile. A picture whose size the chat only learns
    while loading carries its cap as a percentage, which does not count
    while the frame works out its own width — without a cap of its own the
    frame took all the room and stood wider than a landscape picture.

    What a tile being drawn says stands inside that frame, so its frame
    starts level with a finished tile beside it.

    Source-text only: it catches the three places drifting apart, not the
    geometry. The measured sizes (frame = picture + 2 at three window
    widths, two tiles side by side) were taken against the running service.
    """
    app = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")
    card = (WURZEL / "frontend/src/teile/Nachricht.svelte").read_text(encoding="utf-8")

    frame = re.search(r"\n  \.erzeugt \{.*?\n  \}", card, re.S)
    assert frame, ".erzeugt rule not found"
    edge = re.search(r"padding:\s*(\d+)px;", frame.group(0))
    assert edge, "the frame no longer carries its edge as a padding in pixels"
    both_edges = 2 * int(edge.group(1))
    assert re.search(
        rf"max-width:\s*min\(100%, calc\(var\(--bild-deckel, 540px\) \+ {both_edges}px\)\)",
        frame.group(0),
    ), "the frame's cap is no longer the picture's cap plus the frame's own edge"
    assert re.search(rf"const BILDLAUF_KACHEL_RAHMEN = {both_edges}\n", app), (
        "the row of a run no longer counts the frame's edge per tile"
    )
    assert "(BILDLAUF_KACHEL + BILDLAUF_KACHEL_RAHMEN) * 2 + 12" in app, (
        "the row's cap is no longer two tiles with their edges and the gap"
    )

    # The line of a tile being drawn stands in the frame, after the fill, and
    # nowhere above the frame.
    before, _, inside = card.partition('<div class="erzeugt">')
    assert 'class="bild-kopf"' not in before, "the line stands above the frame again"
    # The stage ends where the picture without a known size begins.
    stage = inside.partition('<button class="erzeugt-bild" ')[0]
    assert -1 < stage.find("<Bildfuellung fuellen />") < stage.find('<span class="bild-kopf">'), (
        "the line of a tile being drawn no longer stands inside its frame"
    )
    line = re.search(r"\n  \.bild-kopf \{.*?\n  \}", card, re.S)
    assert line and "position: absolute;" in line.group(0), (
        "the line takes room in the frame again and would push the fill aside"
    )
    # Silence probe: only a tile being drawn carries the line.
    assert re.search(
        r"\{#if nachricht\.bildLaeuft\}\s*<span class=\"bild-kopf\">", stage
    ), "a finished picture would carry the line too"
    assert card.count('class="bild-kopf"') == 1


def test_frage_neu_senden_ruehrt_kein_bild_an():
    """"Send again" under a question looked
    only at the CHAT's own last message and its role — in a run of
    several pictures, the chat's last message is one of that run's own
    tiles, so a single click under the question deleted it and left the
    run's own shortfall caption reporting a failure that was only ever
    this button's doing. The same door H1b and K2 already had to close
    for the run's own pictures, one click away.

    The guard now goes through `traegtBild`
    instead of reading `!letzte.bild` directly, so it also recognises a
    run's own `bilder` list — see the behavioral test right below
    this one for what that function actually has to get right.

    Source-text only, not a behavioral test: it catches the wiring
    coming apart, not every way this button could misfire. The running
    behavior (a real run of four, one click under its question, all
    four tiles still there afterward — and a plain text question still
    replacing its own answer as before) was checked by hand against the
    service, not here.
    """
    quelle = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")
    funktion = re.search(r"async function frageNeuSenden\(\) \{.*?\n  \}", quelle, re.S)
    assert funktion, "frageNeuSenden not found"
    assert re.search(r"!traegtBild\(letzte\)", funktion.group(0)), (
        "frageNeuSenden no longer asks traegtBild whether the last message is a "
        "picture -- under a run a click deletes that run's own last tile or its "
        "run answer row again"
    )
    # The role half of the guard moved: the button no longer reaches for the
    # chat's last row at all, it takes `letzteAntwort`, and THAT is where a
    # row's role and kind are checked. Two reasons it moved rather than
    # being duplicated -- the same decision written twice drifts apart, and
    # `art` catches two shapes a role test never could: a finished
    # background report and a run's picture row are both assistant rows.
    assert re.search(r"const letzte = letzteAntwort\b", funktion.group(0)), (
        "frageNeuSenden no longer takes letzteAntwort -- a click can then delete a "
        "tool report or a picture row again"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_frage_neu_senden_verschont_alle_fuenf_nachbarn():
    """The source-text guard above catches the
    wiring coming apart; it does not say whether the wiring still
    decides the RIGHT way for each shape the last message can actually
    take. Five, named directly in the work order:

    - the run's own QUESTION being the chat's last message (its answer
      row does not exist yet, or was never written) — caught by the
      `role === 'assistant'` half, not by `traegtBild` at all
    - a row from before this migration, `bild` only
    - a run split across two rows by a mid-run restart, the later of
      the two carrying a mix of gaps and one real picture
    - a tool call's own image, hanging off `bild` exactly like the
      legacy row above from this guard's point of view
    - ⓘ the positive control: an ordinary text answer, carrying
      neither — without this one holding true, none of the other four
      would mean anything, since a button that never deletes passes
      every one of them by accident

    The literal condition is extracted from the source, not
    reimplemented — a rewrite that keeps the same shapes working by a
    different route would still pass a hand-written copy of today's
    expression."""
    quelle = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")
    bild_dateien = re.search(r"function bildDateien\(nachricht\) \{.*?\n  \}", quelle, re.S)
    assert bild_dateien, "bildDateien not found"
    traegt_bild = re.search(r"function traegtBild\(nachricht\) \{.*?\n  \}", quelle, re.S)
    assert traegt_bild, "traegtBild not found"
    funktion = re.search(r"async function frageNeuSenden\(\) \{.*?\n  \}", quelle, re.S)
    assert funktion, "frageNeuSenden not found"
    # The decision is in two places now, so both are extracted and joined
    # here exactly as the running code joins them: `letzteAntwort` picks
    # WHICH row, the condition then says whether it may be replaced.
    # Reimplementing either half by hand would let a rewrite that keeps the
    # same shapes working by a different route pass a copy of today's text.
    auswahl = re.search(
        r"const letzteAntwort = \$derived\(\s*\[\.\.\.nachrichtenAnzeige\(\)\]\s*"
        r"\.reverse\(\)\s*\.find\((\(n\) => [^\n]+?)\),",
        quelle,
    )
    assert auswahl, "letzteAntwort not found"
    bedingung = re.search(
        r"letzte && letzte\.id && !traegtBild\(letzte\)",
        funktion.group(0),
    )
    assert bedingung, "the expected condition is missing from the current source of frageNeuSenden"

    faelle = [
        ("frage_eines_laufs", {"role": "user", "id": "q1", "lauf_id": "l"}, False),
        ("alte_weg_b_zeile", {"role": "assistant", "id": "a1", "bild": "alt.png"}, False),
        ("geteilter_lauf", {"role": "assistant", "id": "a2", "bilder": [None, "b.png"]}, False),
        ("werkzeugbild_antwort", {"role": "assistant", "id": "a3", "bild": "werkzeug.png"}, False),
        # Two shapes a role test could never have told apart from an
        # answer, and both of which a click used to destroy: a finished
        # background command, and a run's own picture row.
        ("werkzeugmeldung", {"role": "assistant", "id": "a5", "art": "werkzeugmeldung"}, False),
        ("bildlaufzeile", {"role": "assistant", "id": "a6", "art": "bildlauf"}, False),
        ("gewoehnliche_textantwort", {"role": "assistant", "id": "a4"}, True),
    ]
    # Each case is run through BOTH halves, joined the way the running code
    # joins them: the row has to survive `letzteAntwort`'s filter to become
    # `letzte` at all, and only then does the condition decide. A case the
    # filter drops can never be deleted, which is the whole point of it.
    skript = bild_dateien.group(0) + "\n" + traegt_bild.group(0) + "\n" + "\n".join(
        f"if (((nachrichten) => {{"
        f"  const letzte = nachrichten.reverse().find({auswahl.group(1)});"
        f"  return Boolean({bedingung.group(0)});"
        f"}})([{json.dumps(letzte)}]) !== {str(loescht).lower()}) "
        f"{{ console.error({json.dumps(name)}); process.exit(1) }}"
        for name, letzte, loescht in faelle
    ) + "\nconsole.log('OK')"

    lauf = subprocess.run(
        ["node", "-e", skript], capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    assert lauf.returncode == 0, f"Case {lauf.stderr.strip()!r} fails -- {lauf.stdout}{lauf.stderr}"
    assert "OK" in lauf.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_traegt_bild_erkennt_beide_bildformen():
    """A message carries a picture in one of two
    shapes — the old single upload (`bild`, a bare file name) or a
    run's own list (`bilder`, one array entry per requested
    position, `null` where a picture has not finished or did not
    survive). A run that has not drawn a single picture yet still has a
    non-empty ARRAY of nulls, and in JavaScript that array is truthy the
    same as a full one — a guard checking only `!nachricht.bilder` would
    call an all-null run "no picture" and let a click through to delete
    it; one checking mere presence of any array would call it "has a
    picture" even when every entry is still `null`.

    Executed for real via Node, not matched as a source string: a
    reimplementation that keeps the name `traegtBild` but only checks
    truthiness would pass a source-text test and still fail every one of
    the cases below.
    """
    quelle = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")
    bild_dateien = re.search(r"function bildDateien\(nachricht\) \{.*?\n  \}", quelle, re.S)
    assert bild_dateien, "bildDateien not found"
    funktion = re.search(r"function traegtBild\(nachricht\) \{.*?\n  \}", quelle, re.S)
    assert funktion, "traegtBild not found"

    faelle = [
        ("kein_bild", {}, False),
        ("altes_einzelbild", {"bild": "a.png"}, True),
        ("weg_a_alles_offen", {"bilder": [None, None, None, None]}, False),
        ("weg_a_eines_fertig", {"bilder": [None, "b.png", None]}, True),
        ("weg_a_alle_fertig", {"bilder": ["a.png", "b.png"]}, True),
        ("leere_liste", {"bilder": []}, False),
    ]
    skript = bild_dateien.group(0) + "\n" + funktion.group(0) + "\n" + "\n".join(
        f"if (traegtBild({json.dumps(nachricht)}) !== {str(erwartet).lower()}) "
        f"{{ console.error({json.dumps(name)}); process.exit(1) }}"
        for name, nachricht, erwartet in faelle
    ) + "\nconsole.log('OK')"

    lauf = subprocess.run(
        ["node", "-e", skript], capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    assert lauf.returncode == 0, f"Case {lauf.stderr.strip()!r} fails -- {lauf.stdout}{lauf.stderr}"
    assert "OK" in lauf.stdout


def test_weg_b_gruppierung_ist_ersatzlos_weg():
    """`nachrichtenBloecke` and the machinery it needed
    — `gesamtProLauf`, `meldetTeilausfall`, `eigeneFrage`, the
    `BILDLAUF_IM_CHAT` ceiling — grouped several MESSAGES that shared a
    `stats.lauf` into one growing row. A run is one message now; there is
    nothing left to group. Their absence is the point of this step, not
    an oversight — kept as a named regression guard so a later change
    does not quietly bring the old grouping back beside the new one."""
    quelle = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")
    # Measured baseline, not assumed: none of the four appear even in a
    # comment today (unlike `eigeneFrage`, named in prose above) — an
    # exact zero, not "at most one somewhere explaining it is gone".
    for name in ("nachrichtenBloecke", "gesamtProLauf", "meldetTeilausfall", "BILDLAUF_IM_CHAT"):
        treffer = re.findall(rf"\b{name}\b", quelle)
        assert len(treffer) == 0, f"'{name}' occurs {len(treffer)} times, should be gone without replacement"


def test_bildlauf_kachel_traegt_nie_den_neu_erzeugen_pfeil():
    """K2 — a regression seen and reported directly against the running
    program, not a theoretical one: the regenerate arrow reappeared on
    a run's own last picture. The old test for this guard was removed
    alongside the two one-message-per-picture tests it sat next to when
    `nachrichtenBloecke` came out — wrongly: K2 itself did not go away,
    it just moved to a hand-written `istLetzte={false}` on the synthetic
    tile view (`bildKacheln`'s own shim never carries the field, so
    `istLetzte` is set directly on the `<Nachricht>` call in the tile
    branch). A written `false` nobody re-checks is a side effect of how
    the branch happens to read today, not a guarantee — the same
    distinction B7f drew for the write-side protection. Whoever later
    passes the real per-message `istLetzte` through here "for
    consistency" brings the arrow back, and nothing before this test
    would have said so.

    Source-text only, not a behavioral test: it catches the wiring
    coming apart, not every way the arrow could reappear. The running
    behavior (a real run of four where no tile carries the arrow, and an
    ordinary single picture plus the last text answer still do) was
    checked by hand against the service, not here."""
    quelle = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")
    kachelzweig = re.search(r"\{#if kacheln\}.*?\{:else\}", quelle, re.S)
    assert kachelzweig, "the tile branch ({#if kacheln}) was not found"
    rumpf = kachelzweig.group(0)

    nachricht_aufruf = re.search(r"<Nachricht\b.*?/>", rumpf, re.S)
    assert nachricht_aufruf, "the Nachricht call in the tile branch was not found"
    assert re.search(r"istLetzte=\{\s*false\s*\}", nachricht_aufruf.group(0)), (
        "a tile no longer gets istLetzte fixed to false -- a run's last tile would "
        "carry the regenerate arrow again, which at a picture asks nothing but the "
        "language model"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_bild_kacheln_baut_eine_kachel_je_echtem_bild():
    """B8/K8: the tile row now comes from ONE message's own
    `bilder` — a synthetic per-tile view built here, not a rebuild of
    `Nachricht.svelte`'s 16 single-picture read sites, all of which keep
    working unchanged because every tile still looks like an ordinary
    one-picture message to them (save, enlarge and seed-copy are none of
    them destructive per tile, so sharing the parent's real `id` across
    tiles is safe — K2 already removed the one action that was).

    B14: an empty string is exactly as much "no picture" as `null` is —
    checked with a REAL neighbour present (`["", "b.png"]`), the
    acceptance case named for this, not the lone `[""]` a weaker guard
    could still pass by accident."""
    quelle = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")
    funktion = re.search(r"function bildKacheln\(nachricht\) \{.*?\n  \}", quelle, re.S)
    assert funktion, "bildKacheln not found"

    skript = funktion.group(0) + '''
    const faelle = []

    const keinLauf = bildKacheln({ id: 'm1', bilder: null })
    faelle.push(['kein_lauf', keinLauf === null])

    const nochNichts = bildKacheln({ id: 'm2', bilder: [null, null, null, null] })
    faelle.push(['noch_nichts_fertig_laenge', nochNichts.length === 0])

    const teilweise = bildKacheln({
      id: 'm3', bilder: [null, 'b.png', null],
      stats: { lauf: 'l', von: 3, seeds: [10, 11, 12] },
    })
    faelle.push(['teilweise_laenge', teilweise.length === 1])
    faelle.push(['teilweise_bild', teilweise[0]?.bild === 'b.png'])
    faelle.push(['teilweise_seed', teilweise[0]?.stats?.seed === 11])
    faelle.push(['teilweise_teilt_id', teilweise[0]?.id === 'm3'])

    // B14: a real neighbour sits right beside the empty string.
    const mitLeerem = bildKacheln({
      id: 'm4', bilder: ['', 'b.png'], stats: { seeds: [1, 2] },
    })
    faelle.push(['leerer_name_laenge', mitLeerem.length === 1])
    faelle.push(['leerer_name_bild', mitLeerem[0]?.bild === 'b.png'])
    faelle.push(['leerer_name_seed', mitLeerem[0]?.stats?.seed === 2])

    const voll = bildKacheln({
      id: 'm5', bilder: ['a.png', 'b.png'], stats: { seeds: [1, 2] },
    })
    faelle.push(['voll_laenge', voll.length === 2])
    faelle.push(['voll_beide_ids_teilen', voll[0].id === 'm5' && voll[1].id === 'm5'])

    let fehler = []
    for (const [name, bestanden] of faelle) if (!bestanden) fehler.push(name)
    if (fehler.length) { console.error(fehler.join(', ')); process.exit(1) }
    console.log('OK')
    '''
    lauf = subprocess.run(
        ["node", "-e", skript], capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    assert lauf.returncode == 0, f"Cases {lauf.stderr.strip()!r} fail -- {lauf.stdout}{lauf.stderr}"
    assert "OK" in lauf.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_teilausfall_hat_keinen_deckel_mehr():
    """A pair in two directions, each with its own
    case (a defect that disappears without its own measurement may only
    have moved somewhere else): the old one-message-per-picture shape capped this comparison at
    four (the chat's own old display limit). B9 was that cap reporting a
    shortfall a fully successful run of more than four never had. B15 was
    the SAME cap swallowing a real shortfall above four just as quietly
    (a run of six with five drawn compared "5 < min(6, 4)" and stayed
    silent). Both die from removing the ceiling entirely, not from two
    separate fixes — `von` is the run's own true total now, nothing here
    ever compares against anything smaller.

    A lauf is one row by construction, but a mid-run
    restart can still leave it split across two — the row written
    before the restart and the one the next picture created after, both
    carrying the same `stats.lauf`. Counting only one row's own
    `bilder` reads a picture sitting in the OTHER row as a failure —
    B9's own defect in a new shape. Summed across every row sharing the
    lauf now, reported once, on the last of them.

    And summing only `bilder` still read a row
    from BEFORE this migration — one that only ever got `bild`, no
    `bilder` at all — as contributing zero pictures, even though it has
    one. A split lauf whose earlier half is such a row reported a false
    shortfall for a picture that is genuinely there. Fixed by asking
    `bildDateien`, the same place `traegtBild` now asks too, instead of
    reading `n.bilder` directly."""
    quelle = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")
    bild_dateien = re.search(r"function bildDateien\(nachricht\) \{.*?\n  \}", quelle, re.S)
    assert bild_dateien, "bildDateien not found"
    lauf_kennung = re.search(r"function laufKennung\(nachricht\) \{.*?\n  \}", quelle, re.S)
    assert lauf_kennung, "laufKennung not found"
    funktion = re.search(
        r"function teilausfall\(nachricht, laufAktuell, alleNachrichten\) \{.*?\n  \}",
        quelle, re.S,
    )
    assert funktion, "teilausfall not found"

    skript = (
        bild_dateien.group(0) + "\n" + lauf_kennung.group(0) + "\n" + funktion.group(0) + '''
    const faelle = []

    // B9: a full run of 6 (more than the old ceiling of 4) reports nothing.
    const voll6 = { stats: { von: 6 }, bilder: Array(6).fill('x.png') }
    faelle.push(['b9_voller_lauf_ueber_vier', teilausfall(voll6, null, [voll6]) === null])

    // B15: a real shortfall above four is not swallowed by the old ceiling.
    const teil6 = { stats: { von: 6 }, bilder: ['x.png', 'x.png', 'x.png', 'x.png', 'x.png', null] }
    const ergebnisTeil6 = teilausfall(teil6, null, [teil6])
    faelle.push(['b15_teilausfall_ueber_vier_gefunden', ergebnisTeil6 !== null])
    faelle.push(['b15_teilausfall_ueber_vier_zahl', ergebnisTeil6?.gescheitert === 1 && ergebnisTeil6?.von === 6])

    // Still drawing: suppressed regardless of the true count so far. The
    // run id sits in `lauf_id`, the way the server sends it — the whole
    // point of this case is that the suppression reads the field the rows
    // actually carry, so writing it as `stats.lauf` here would only prove
    // the window agrees with a shape nothing produces any more.
    const nochAktiv = { lauf_id: 'l', stats: { von: 4 }, bilder: [null, null, null, null] }
    faelle.push(['waehrend_des_laufs_still', teilausfall(nochAktiv, 'l', [nochAktiv]) === null])

    // An ordinary message (no `von` at all) never reports anything.
    const keinLauf = { stats: {} }
    faelle.push(['kein_lauf_keine_meldung', teilausfall(keinLauf, null, [keinLauf]) === null])

    // C6: a lauf split across two rows by a mid-run restart — the picture
    // in the OTHER row is not a failure, and the shortfall is judged over
    // BOTH rows together, reported once, on the later one.
    const ersteZeile = { lauf_id: 'x', stats: { von: 4 }, bilder: ['a.png', null, null, null] }
    const zweiteZeile = { lauf_id: 'x', stats: { von: 4 }, bilder: [null, 'b.png', null, null] }
    const alle = [ersteZeile, zweiteZeile]
    faelle.push(['c6_erste_zeile_meldet_nicht', teilausfall(ersteZeile, null, alle) === null])
    const c6Ergebnis = teilausfall(zweiteZeile, null, alle)
    faelle.push(['c6_zweite_zeile_zahl', c6Ergebnis?.gescheitert === 2 && c6Ergebnis?.von === 4])

    // C6 continued: a split lauf where the EARLIER row predates the change
    // to `bilder` and only ever got `bild`, never `bilder` at all. Such a
    // row also predates the `lauf_id` column — it carries one anyway,
    // because the migration that added the column backfilled it out of
    // `stats.lauf` for every row that had one.
    const alteZeile = { lauf_id: 'y', stats: { lauf: 'y', von: 2 }, bild: 'alt.png' }
    const neueZeile = { lauf_id: 'y', stats: { von: 2 }, bilder: [null, 'b.png'] }
    const gemischt = [alteZeile, neueZeile]
    faelle.push(['c6_form_gemischt_keine_meldung', teilausfall(neueZeile, null, gemischt) === null])
    const neueZeileEchterAusfall = { lauf_id: 'z', stats: { von: 2 }, bilder: [null, null] }
    const alteZeileEchterAusfall = { lauf_id: 'z', stats: { lauf: 'z', von: 2 }, bild: 'alt.png' }
    const gemischtAusfall = [alteZeileEchterAusfall, neueZeileEchterAusfall]
    const c6GemischtErgebnis = teilausfall(neueZeileEchterAusfall, null, gemischtAusfall)
    faelle.push(['c6_form_gemischt_echter_ausfall', c6GemischtErgebnis?.gescheitert === 1 && c6GemischtErgebnis?.von === 2])

    let fehler = []
    for (const [name, bestanden] of faelle) if (!bestanden) fehler.push(name)
    if (fehler.length) { console.error(fehler.join(', ')); process.exit(1) }
    console.log('OK')
    '''
    )
    lauf = subprocess.run(
        ["node", "-e", skript], capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    assert lauf.returncode == 0, f"Cases {lauf.stderr.strip()!r} fail -- {lauf.stdout}{lauf.stderr}"
    assert "OK" in lauf.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_kachelwand_liest_die_laufkennung_aus_der_spalte():
    """The run id a row belongs to lives in the `lauf_id` COLUMN, and the
    tile row has to read it there.

    It did not. When the id moved out of the stats blob the window kept
    asking the blob, and every row written after the move answered
    `undefined` — which reads exactly like "belongs to some other run", so
    nothing failed anywhere: the tiles simply stopped recognising each
    other. Three things broke at once and all three are pinned here,
    because each one goes quiet in a different direction and a fix aimed at
    one could leave the others exactly as they were:

      - the cell for the picture still being drawn left the wall and stood
        beside it as its own full-width frame (`laufendeKachel` found no
        run to put it in, `inKachelAufgegangen` then had no reason to
        suppress the second drawing of it)
      - the shortfall caption stopped appearing at all: with no id to
        compare, `teilausfall`'s own "which rows share this run" filter
        collapsed to "every row of the chat that has no id either", and any
        ordinary message below the run took the last-row spot the caption
        is reported on
      - and the same filter, before that, read a run STILL BEING DRAWN as
        one that had finished short

    The rows below are shaped the way `NachrichtAntwort` sends them — the
    run's question carries the id too, the answer row carries `von` and
    `seeds` in stats and nothing else. A row stored BEFORE the move is
    included as its own case: the migration that added the column
    backfilled it and left the old key in place, so such a row carries
    both, and old and new runs standing in one chat must read alike. That
    they did not is what made the defect look like a display glitch rather
    than a field that had moved."""
    quelle = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")
    teile = []
    for name, muster in (
        ("laufKennung", r"function laufKennung\(nachricht\) \{.*?\n  \}"),
        ("bildDateien", r"function bildDateien\(nachricht\) \{.*?\n  \}"),
        ("bildKacheln", r"function bildKacheln\(nachricht\) \{.*?\n  \}"),
        ("laufendeKachel",
         r"function laufendeKachel\(nachricht, laufAktuell, alleNachrichten\) \{.*?\n  \}"),
        ("inKachelAufgegangen",
         r"function inKachelAufgegangen\(nachricht, laufAktuell, alleNachrichten\) \{.*?\n  \}"),
        ("teilausfall",
         r"function teilausfall\(nachricht, laufAktuell, alleNachrichten\) \{.*?\n  \}"),
    ):
        treffer = re.search(muster, quelle, re.S)
        assert treffer, f"{name} not found"
        teile.append(treffer.group(0))

    skript = "\n".join(teile) + '''
    const faelle = []

    // A run of three, two pictures in, the third still being drawn.
    const frage = { id: 'q1', role: 'user', content: 'zwei Katzen', lauf_id: 'lauf-7' }
    const laufZeile = {
      id: 'a1', role: 'assistant', content: '', art: 'bildlauf', lauf_id: 'lauf-7',
      stats: { von: 3, seeds: [10, 11, null] }, bilder: ['a.png', 'b.png', null],
    }
    // The cell being painted: pushed by the window itself, never on the
    // server, and carrying no run id of its own — it is found by
    // `bildLaeuft`, and it is the WALL that has to claim it.
    const malende = {
      id: 'bildlauf-c1', role: 'assistant', content: '', bildLaeuft: true, stats: {},
    }
    const waehrendDesLaufs = [frage, laufZeile, malende]

    faelle.push(['kacheln_stehen', bildKacheln(laufZeile)?.length === 2])

    // The painting cell belongs INSIDE this run's wall...
    faelle.push([
      'malende_zelle_gehoert_in_die_wand',
      laufendeKachel(laufZeile, 'lauf-7', waehrendDesLaufs) === malende,
    ])
    // ...and must therefore not be drawn a second time below it.
    faelle.push([
      'malende_zelle_nicht_doppelt',
      inKachelAufgegangen(malende, 'lauf-7', waehrendDesLaufs) === true,
    ])
    // A cell of a DIFFERENT run is not adopted by this wall — the half of
    // the comparison that keeps two runs in one chat apart, and the one a
    // reader that answers `undefined` for every row would lose first.
    faelle.push([
      'fremder_lauf_bleibt_draussen',
      laufendeKachel(laufZeile, 'lauf-9', waehrendDesLaufs) === null,
    ])
    // Still filling in: no shortfall is claimed while this run is the one
    // being drawn, however few of its pictures have landed so far.
    faelle.push([
      'waehrend_des_laufs_keine_meldung',
      teilausfall(laufZeile, 'lauf-7', waehrendDesLaufs) === null,
    ])

    // The run is over, the third picture never arrived, and an ordinary
    // answer has since been written below it. That last row is what used
    // to take the caption's place: without an id to filter on, "the rows
    // sharing this run" became "every row without one", and the caption is
    // only ever reported on the LAST of them.
    const spaetereAntwort = { id: 'a2', role: 'assistant', content: 'gern geschehen' }
    const danach = [frage, laufZeile, spaetereAntwort]
    const fehlbetrag = teilausfall(laufZeile, null, danach)
    faelle.push(['meldung_erscheint', fehlbetrag !== null])
    faelle.push([
      'meldung_zaehlt_richtig',
      fehlbetrag?.gescheitert === 1 && fehlbetrag?.von === 3,
    ])

    // A second run in the same chat is counted on its own, not folded into
    // the first — two runs whose ids both read as "absent" would sum into
    // one and report a shortfall neither of them has.
    const zweiterLauf = {
      id: 'a3', role: 'assistant', content: '', art: 'bildlauf', lauf_id: 'lauf-8',
      stats: { von: 2, seeds: [20, 21] }, bilder: ['c.png', 'd.png'],
    }
    const zweiLaeufe = [frage, laufZeile, zweiterLauf]
    const ersterVonZweien = teilausfall(laufZeile, null, zweiLaeufe)
    faelle.push([
      'erster_lauf_zaehlt_allein',
      ersterVonZweien?.gescheitert === 1 && ersterVonZweien?.von === 3,
    ])
    faelle.push([
      'zweiter_lauf_ist_vollstaendig',
      teilausfall(zweiterLauf, null, zweiLaeufe) === null,
    ])

    // A row stored before the id moved: the column is filled (the
    // migration backfilled it) and the retired key is still in the blob
    // beside it. It has to read exactly like the new row above — old and
    // new runs stand in the same chat.
    const alteZeile = {
      id: 'a4', role: 'assistant', content: '', art: 'bildlauf', lauf_id: 'lauf-alt',
      stats: { lauf: 'lauf-alt', von: 3, seeds: [30, 31, null] },
      bilder: ['e.png', 'f.png', null],
    }
    const alteFrage = { id: 'q2', role: 'user', content: 'damals', lauf_id: 'lauf-alt' }
    const gemischterChat = [alteFrage, alteZeile, frage, laufZeile, spaetereAntwort]
    const altErgebnis = teilausfall(alteZeile, null, gemischterChat)
    const neuErgebnis = teilausfall(laufZeile, null, gemischterChat)
    faelle.push([
      'alte_zeile_meldet',
      altErgebnis?.gescheitert === 1 && altErgebnis?.von === 3,
    ])
    faelle.push([
      'neue_zeile_meldet_genauso',
      neuErgebnis?.gescheitert === 1 && neuErgebnis?.von === 3,
    ])

    // And the accessor itself, on the three shapes above: absence is
    // `null`, not `undefined` — `teilausfall` compares it against
    // `laufAktuell`, which is `null` between runs.
    faelle.push(['kennung_neu', laufKennung(laufZeile) === 'lauf-7'])
    faelle.push(['kennung_alt', laufKennung(alteZeile) === 'lauf-alt'])
    faelle.push(['kennung_ohne_lauf', laufKennung(spaetereAntwort) === null])

    let fehler = []
    for (const [name, bestanden] of faelle) if (!bestanden) fehler.push(name)
    if (fehler.length) { console.error(fehler.join(', ')); process.exit(1) }
    console.log('OK')
    '''
    lauf = subprocess.run(
        ["node", "-e", skript], capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    assert lauf.returncode == 0, f"Cases {lauf.stderr.strip()!r} fail -- {lauf.stdout}{lauf.stderr}"
    assert "OK" in lauf.stdout


def test_der_lokale_platzhalter_traegt_dieselbe_laufkennung_wie_die_serverzeile():
    """The window's own optimistic row must be shaped like the row that
    replaces it.

    Pictures are drawn strictly one after another, and each one's reconcile
    swaps the whole list for the server's before the next begins — so from
    the second picture on, the row `bildEinesZeichnen` looks for is the
    SERVER's. While the placeholder carried its run id under the retired
    `stats.lauf` and the server's row carried `lauf_id`, that lookup missed:
    the second picture opened a wall of its own beside the first instead of
    taking the next cell in it.

    Source-text only: a shape mismatch between two writers is what this
    guards, and the write is a plain assignment nothing else makes."""
    quelle = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")
    funktion = re.search(
        r"async function bildEinesZeichnen\(wunsch\) \{.*?\n  \}", quelle, re.S,
    )
    assert funktion, "bildEinesZeichnen not found"
    rumpf = funktion.group(0)
    zuweisungen = re.findall(r"\b(?:ziel|geteilt)\.lauf_id = wunsch\.lauf_kennung", rumpf)
    assert len(zuweisungen) == 2, (
        f"expected two assignments of lauf_id to the local row (folded and "
        f"standalone), found: {len(zuweisungen)}"
    )
    assert not re.search(r"stats = \{[^}]*\blauf:", rumpf), (
        "the local row writes the run id into the stats blob again -- the server row "
        "carries it in lauf_id, and the run's next picture then no longer finds its "
        "own tile wall"
    )


def test_bild_stoppen_raeumt_die_lauf_kennung_mit_auf():
    """`laufAktuell` and `laufFehlerZahl` were only ever
    cleared by a run's OWN last request finishing (`nr === von`, in
    `bildEinesZeichnen`'s own `finally`) — stopping a run before that
    request ever happens (picture 5 of 8, say) left `laufAktuell` stuck
    naming it. `teilausfall` reads a message whose own `stats.lauf`
    still equals `laufAktuell` as "still being drawn" and stays silent
    about it — exactly the shortfall B15 exists to report, silenced
    again by a stop instead of a completion, until either a new run
    overwrites the same one value or a reload starts fresh.

    Source-text only, not a behavioral test: it catches the wiring
    coming apart, not every way the state could go stale."""
    quelle = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")
    funktion = re.search(r"function bildStoppen\(\) \{.*?\n  \}", quelle, re.S)
    assert funktion, "bildStoppen not found"
    rumpf = funktion.group(0)
    assert re.search(r"laufAktuell\s*=\s*null", rumpf), (
        "bildStoppen no longer resets laufAktuell -- an abort mid-run would suppress "
        "the partial-failure notice for this run for good, until a new run "
        "overwrites the same value"
    )
    assert re.search(r"laufFehlerZahl\.clear\(\)", rumpf), (
        "bildStoppen no longer clears laufFehlerZahl -- the same cause as with "
        "laufAktuell"
    )


def test_lauf_zeile_suche_prueft_immer_die_rolle():
    """A run's own question row carries the same run id
    as its answer row (`bild.py` writes it on the user-role row too, to
    let the shortfall toast find the request even before any picture
    lands) — a `find` matching on the run id alone can return that
    question row just as easily as the answer it was meant to find. The
    sibling single-picture branch three lines below already guards
    against exactly this (`n.role === 'assistant' && n.bild ===
    antwort.bild`); both per-run lookups in `bildEinesZeichnen` need the
    same guard, or a fresh run's own placeholder folds into the question
    bubble instead of its answer.

    The id itself moved from the stats blob into the `lauf_id` column,
    so both lookups go through `laufKennung` now. The guard this test
    exists for is unaffected by that move — and matching on the new
    accessor is the point: a lookup left on the retired key would find
    nothing at all, which is not the failure mode this test describes
    but would sail through a pattern still written for the old one.

    Source-text only: it catches the guard coming off either lookup,
    not every way the merge could go wrong."""
    quelle = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")
    funktion = re.search(
        r"async function bildEinesZeichnen\(wunsch\) \{.*?\n  \}", quelle, re.S,
    )
    assert funktion, "bildEinesZeichnen not found"
    rumpf = funktion.group(0)
    lauf_suchen = re.findall(
        r"\.find\(\s*\(n\)\s*=>[^\n]*laufKennung\(n\) === wunsch\.lauf_kennung", rumpf,
    )
    assert len(lauf_suchen) == 2, (
        f"expected exactly two lookups of the run id in bildEinesZeichnen, found: "
        f"{len(lauf_suchen)}"
    )
    for suche in lauf_suchen:
        assert "n.role === 'assistant'" in suche, (
            f"a run-id lookup does not check the role -- it also hits the same run's "
            f"question row: {suche!r}"
        )


def test_der_laufzustand_wird_wieder_abgeraeumt():
    """A row fetched mid-run carries `zustand: 'laeuft'` from the server, and
    nothing else in the window ever writes that field.

    Left standing it never becomes false again: the bubble keeps drawing
    itself as a running answer after the run is long over — waiting mark and
    clock going — and the truncation notice stays suppressed, because that
    one is gated on `!laeuft`. Exactly the stuck row this whole change set
    was built to remove, reintroduced from the other side.

    Two places have to clear it, and both are asserted: the resume, which
    adopts such a row and empties it, and the end of the run, which catches
    every row that reached the window some other way.

    Source-text only. What it guards is a field nothing else assigns, so a
    grep for the assignment IS the guarantee — and its absence is invisible
    in any test that does not run a real reload against a real service.
    """
    quelle = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")

    uebernahme = re.search(r"if \(uebernehmen\) \{.*?\n    \}", quelle, re.S)
    assert uebernahme, "the adoption block was not found"
    assert "uebernehmen.zustand = null" in uebernahme.group(0), (
        "the adopted row keeps zustand='laeuft' -- it is then drawn as a running "
        "answer for good"
    )

    # The word written at the end is the server's closing state off the
    # `done` event, never a guess and never 'laeuft': a run whose stream
    # broke before `done` leaves the row with no word at all.
    assert re.search(r"platzhalter\.zustand = schlussZustand", quelle), (
        "the run state is not cleared at the run's end -- a row fetched during the "
        "run stays on 'laeuft' afterwards"
    )
    assert re.search(r"schlussZustand = ereignis\.zustand \?\? null", quelle), (
        "the done event is no longer asked for the closing state"
    )

    # And the reading itself still has to ask the row, not its position --
    # that half is what the whole change set replaced.
    assert re.search(r"laeuft=\{zeileLaeuft\(nachricht\)", quelle), (
        "the running mark no longer asks the row itself"
    )
    assert re.search(r"function zeileLaeuft\(zeile\) \{\s*return \(\s*zeile\.zustand === 'laeuft'", quelle), (
        "the one reading of a running row no longer starts from the row's own word"
    )
    assert not re.search(r"laeuft=\{[^}]*i === zustand\.nachrichten\.length - 1", quelle), (
        "the running mark goes by position again -- every foreign row behind the "
        "answer pulls it onto itself"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_die_kennung_der_laufenden_zeile_kommt_beim_wiederanhang_an():
    """The resume adopts the running row BY ITS ID. That id travels four
    hops, and it went missing at the second.

    `chatOeffnen` stored {chatId, generationId, messageId}; the effect that
    picks it up called `antwortWiederAnhaengen(wiederanhang.chatId,
    wiederanhang.generationId)`; that function rebuilt `{chatId,
    generationId}` and handed THAT on. So `wiederanhang?.messageId` in
    `antwortHolen` was always undefined, nothing was ever adopted, and every
    cold reattach pushed a second placeholder beside the stored answer —
    the doubling the id was introduced to stop. Silently: the code read
    correctly at each end, and only the middle dropped it.

    Nothing about this is visible in a test that never reloads mid-run, so
    it is nailed here: the record goes through whole, and the reader at the
    far end still asks for the field.
    """
    quelle = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")

    aufruf = re.search(r"antwortWiederAnhaengen\((.*?)\)\n", quelle)
    assert aufruf, "the call of antwortWiederAnhaengen was not found"
    assert "," not in aufruf.group(1), (
        f"antwortWiederAnhaengen is called with single fields again -- that is how "
        f"the messageId went missing once before (found: {aufruf.group(1)!r})"
    )

    funktion = re.search(
        r"async function antwortWiederAnhaengen\(.*?\n  \}", quelle, re.S
    )
    assert funktion, "antwortWiederAnhaengen not found"
    # Comments stripped first: the one inside this function NAMES the old
    # broken shape in order to explain it, and a check that cannot tell the
    # description from the thing described would fail on the fix.
    nur_code = "\n".join(
        zeile for zeile in funktion.group(0).splitlines()
        if not zeile.lstrip().startswith("//")
    )
    assert not re.search(r"\{ chatId, generationId \}", nur_code), (
        "the reattach record is assembled from single fields again -- exactly where "
        "the messageId drops out"
    )

    # And the far end still reads it.
    assert re.search(r"wiederanhang\?\.messageId", quelle), (
        "antwortHolen no longer asks for the messageId -- then it is guessed again"
    )


# --- The end of a run, run for real ---------------------------------------
#
# What follows is not a house rule but a race, and a race cannot be read out
# of a source file: it is about WHEN two things happen, not whether they are
# written down. So the three pieces of App.svelte that take part in it are
# lifted out and executed under Svelte's own runtime in node, the way
# ``test_chatscrollen.py`` runs the scroll logic and ``test_warteschlange.py``
# runs the queue module. The effect scheduling is then the real one — which
# is the entire point, because the defect is that the effect fires inside an
# ``await`` nobody expected it to reach.
#
# The race: ``delete zustand.laeuft[zielChat]`` is not bookkeeping, it is the
# signal the queue effect listens for. Everything the queue must be gated on
# has to stand above that line, and everything the run still means to write
# into the message list has to be written above it too. Twice it was not, and
# both times the damage was invisible in every test that never let a second
# message wait during a run.

P662_FRONTEND = WURZEL / "frontend"
P662_WARTESCHLANGE = P662_FRONTEND / "src/lib/warteschlange.svelte.js"


def _p662_quelle() -> str:
    """The component as it stands. Its own function, so a check of this test
    can hand it a different revision without touching the working tree."""
    return (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")


def _p662_stueck(quelle: str, muster: str, name: str) -> str:
    treffer = re.search(muster, quelle, re.S)
    assert treffer, f'{name} not found -- the excerpt no longer matches'
    return treffer.group(0)


# The driver. Everything the lifted stretch reaches out to is stood in for,
# and only two of those stand-ins carry any judgement:
#
#   `senden`  — the queue calls it. What decides this race is only how far
#               that call gets BEFORE it yields, and the real one gets all
#               the way: with nothing to upload and a chat that already has
#               a history, `senden` reaches its own `zustand.nachrichten.push`
#               without a single await, and `antwortHolen`, called on the
#               same tick, reaches its placeholder push and its write to
#               `laufenderPlatzhalter` the same way. That stretch is what is
#               modelled here.
#   `dienst`  — the service's own rows. `generierung.py` writes the answer's
#               row carrying `zustand: 'laeuft'` at the first moment of a
#               run, before the stream even opens, so a run that has started
#               is a run the next fetch can bring back. Whether it does is
#               exactly what the ordering decides.
P662_FAHRER = """
import { anhalten, ausreihen, einreihen, haelt, fuerChat, zurueckEinreihen } from './p662.warteschlange.mjs'
import { untrack, flushSync } from 'svelte'

const zustand = $state({
  aktiverChat: null, nachrichten: [], nachrichtenChatId: null,
  laeuft: {}, laufenderPlatzhalter: {}, sendet: {},
  bildLaeuftChat: {}, bildMasse: {},
})
const laufVon = (chatId) => (chatId != null ? (zustand.laeuft[chatId] ?? null) : null)
// The quick picker's switch for the chat's model (lib/modelle.svelte.js).
const chosenModelOff = () => Boolean(globalThis.__modelOff)
// The real one also tags the list with the chat it now belongs to; the
// lifted "ende" stretch below calls it, so it has to exist here too.
function nachrichtenSetzen(chatId, liste) {
  zustand.nachrichten = liste
  zustand.nachrichtenChatId = chatId
}
// `__unfocused` puts the window in the background, where the finished
// and failed dots are drawn; both are recorded.
const document = { hasFocus: () => !globalThis.__unfocused }
const chatFehlerMerken = () => protokoll.push('chatFehlerMerken')
const chatFertigMerken = () => protokoll.push('chatFertigMerken')
const chatFehlerGesehen = () => protokoll.push('chatFehlerGesehen')
// A drawing call's working tile going with the run (App.svelte).
const drawingDone = () => protokoll.push('drawingDone')
const ownRunsReattached = new Set()
const protokoll = []
const dienst = []
// The input bar, as far as the queue touches it: a message the queue
// dispatches is not the bar's own, so the bar is told to forget what it
// still remembers of an earlier send (App.svelte, `warteschlangeWeiter`).
const eingabe = {
  vergessen: () => protokoll.push('eingabe.vergessen'),
  zurueckgeben: (...args) => protokoll.push(['zurueckgegeben', ...args]),
}
const chatOeffnen = async (chatId) => { protokoll.push(['chatOeffnen', chatId]) }
// The claims the stop button can cut short, by chat (App.svelte).
const anspruchWarten = new Map()
// The chats the window folds by hand right now (`/compact`).
const compactSince = {}

// Both of these are a request to the service, so both are at least one turn
// of the event loop -- and one turn is all the effect needs.
const chatsLaden = async () => {
  protokoll.push('chatsLaden')
  await new Promise((frei) => setTimeout(frei, 0))
}
// `__claims` lets a scenario hand out the service's run flags one question
// at a time ({ laufend, gehalten }); without it every answer carries
// `__laufend` and no claim.
const api = {
  abbrechen: async (generationId, chatId) => {
    protokoll.push(['stop', generationId, chatId])
    return { abgebrochen: 1 }
  },
  nachrichten: async () => {
    protokoll.push('api.nachrichten')
    await new Promise((frei) => setTimeout(frei, 0))
    const claim = globalThis.__claims?.length ? globalThis.__claims.shift() : null
    if (claim === 'offline') throw new Error('offline')
    if (claim?.add) dienst.push(claim.add)
    // The service's rows as they stand after this answer: a stop that lands.
    if (claim?.ersetze) dienst.splice(0, dienst.length, ...claim.ersetze)
    return {
      nachrichten: dienst.map((zeile) => ({ ...zeile })),
      laufend: claim ? claim.laufend ?? null : globalThis.__laufend ?? null,
      gehalten: claim ? Boolean(claim.gehalten) : false,
    }
  },
}

// The real one registers the run before its first await; that is what
// this stand-in mirrors, and all it mirrors. Called with `nachholen:
// false` here, exactly like the shipped call from this stretch -- so,
// like the shipped function, it never touches `wiederanhaengen` either
// (that clear lives in `chatOeffnen`, not here).
async function antwortWiederAnhaengen(wiederanhang) {
  protokoll.push(['wiederanhaengen', wiederanhang.generationId, wiederanhang.messageId])
  zustand.laeuft[wiederanhang.chatId] = { chatId: wiederanhang.chatId, generationId: wiederanhang.generationId }
}

function senden(inhalt) {
  protokoll.push('senden')
  const chatId = zustand.aktiverChat
  zustand.nachrichten.push({ id: 'eigen-zwei', role: 'user', content: inhalt })
  zustand.nachrichten.push({ id: `platzhalter-${chatId}`, role: 'assistant', content: '' })
  const meiner = zustand.nachrichten[zustand.nachrichten.length - 1]
  zustand.laufenderPlatzhalter[chatId] = meiner
  zustand.laeuft[chatId] = { chatId }
  if (globalThis.__dienstSchreibtSofort) {
    dienst.push({ id: 'u2', role: 'user', content: inhalt })
    dienst.push({ id: 'a2', role: 'assistant', content: '', zustand: 'laeuft' })
  }
}
%s

async function laufEnde({ zielChat, abgebrochen, gescheitert, belegt = false, platzhalter, drawing = false, verdichtetZu, zeileNachladen = false, schlussZustand = 'fertig', lauf = { generationId: 'eigen' }, fremderLauf = null, heldWithoutRun = false, wiederanhang = null, redo = null, retried = null, retriedState = null, begun = true, replacedId = null, discarded = false, doneSeen = false, zurueckInReihe = false, inhalt = 'zwei', nachrichtId = null, ausReihe = null }) {
%s
%s
}

async function szenario() {
%s
}

export async function fahren() {
  const stop = $effect.root(() => {
%s
  })
  flushSync()
  const bericht = await szenario()
  stop()
  return bericht
}
"""

P662_TREIBER = """
import { compileModule } from 'svelte/compiler'
import { readFileSync, writeFileSync } from 'fs'
const bauen = (quelle, ziel, name) => writeFileSync(
  ziel,
  compileModule(readFileSync(quelle, 'utf-8'), { filename: name, generate: 'client' }).js.code
    // The generated module, not the source: the compiler forbids
    // `svelte/internal/*` in a .svelte.js file, while node resolves a
    // plain `svelte` to the SERVER build — where `untrack` passes straight
    // through and `flushSync` does nothing. On that build the effect
    // tracked everything the queue read, and a test of what wakes it was
    // green whatever the effect declared.
    .replace("from 'svelte';", "from './p662.echt.mjs';"),
)
bauen(%r, %r, 'warteschlange.svelte.js')
bauen(%r, %r, 'p662.fahrer.svelte.js')
console.log('---BERICHT---' + JSON.stringify(await (await import(%r)).fahren()))
"""

# The client runtime's own `untrack` and flush, for the driver above.
P662_ECHT = """
import { untrack, flush } from 'svelte/internal/client'
export { untrack }
export const flushSync = flush
"""

# Chat A is being answered; a second message was typed while it ran. The
# service knows the first exchange and has just folded the history away.
P662_AUFBAU = """
    const b1 = { id: 'u1', role: 'user', content: 'eins' }
    const p1 = { id: 'platzhalter-A', role: 'assistant', content: 'antwort eins' }
    zustand.aktiverChat = 'A'
    zustand.nachrichten = [b1, p1]
    zustand.laeuft.A = { chatId: 'A' }
    zustand.laufenderPlatzhalter.A = p1
    flushSync()
    einreihen('A', { inhalt: 'zwei' })
    dienst.push({ id: 'naht', role: 'system', content: 'zusammenfassung' })
    dienst.push({ id: 'u1', role: 'user', content: 'eins' })
    dienst.push({ id: 'a1', role: 'assistant', content: 'antwort eins', zustand: 'fertig' })
"""


def _p662_lauf(quelle: str, szenario: str) -> dict:
    """Compile the real queue module and a driver built from the real
    App.svelte stretches, then run the scenario in node."""
    weiter = _p662_stueck(
        quelle, r"\n  function warteschlangeWeiter\(\) \{.*?\n  \}\n", "warteschlangeWeiter"
    )
    effekt = _p662_stueck(
        quelle,
        r"\n  \$effect\(\(\) => \{\n    void zustand\.aktiverChat\n.*?"
        r"Object\.keys\(zustand\.laeuft\)\.length\n.*?\n  \}\)\n",
        "der Warteschlangen-Effekt",
    )
    ende = _p662_stueck(
        quelle,
        r"\n      const fertigerChat = zielChat\n.*?\n      warteschlangeWeiter\(\)\n",
        "das Laufende in antwortHolen",
    )
    # The five files of this run carry a token of their own: two workers of
    # one test session run this driver side by side, and under shared names
    # each wrote over the other's files and read the other's scenario.
    run_token = uuid4().hex[:10]
    fahrer = P662_FRONTEND / f"p662.{run_token}.fahrer.svelte.js"
    treiber = P662_FRONTEND / f"p662.{run_token}.pruefung.mjs"
    ws_gebaut = P662_FRONTEND / f"p662.{run_token}.warteschlange.mjs"
    fahrer_gebaut = P662_FRONTEND / f"p662.{run_token}.fahrer.mjs"
    # The bound the reconcile puts on its fetch, lifted with the stretch
    # that uses it: the real number, so a driver never runs on a made-up one.
    frist = _p662_stueck(
        quelle, r"\n  const NACHLADE_FRIST_MS = [0-9_]+\n", "die Nachladefrist"
    ) + _p662_stueck(
        quelle, r"\n  const HALTEPRUEFUNG_MS = [0-9_]+\n", "the claim check interval"
    )
    # The claim question the end of the run asks, with its two helpers.
    fragen = _p662_stueck(quelle, _WITH_DEADLINE, "claimOutcome")
    # The stop button's own two functions: the wait for a claim is cut by it.
    stopp = _p662_stueck(
        quelle,
        r"\n  async function stoppWiederholen\(lauf\) \{.*?\n  \}\n"
        r".*?\n  async function abbrechen\(\) \{.*?\n  \}\n",
        "abbrechen",
    )
    # What the end does when the service turned the send away (409).
    belegt_ende = _p662_stueck(
        quelle,
        r"\n      if \(belegt\) \{\n        /\* The bubble and its placeholder.*?\n      \}\n"
        r"(?=      // If the answer aborts while the confirmation stands)",
        "the 409 end",
    )
    echt = P662_FRONTEND / f"p662.{run_token}.echt.mjs"
    fahrer.write_text(
        (P662_FAHRER % (frist + weiter + fragen + stopp, belegt_ende, ende, szenario, effekt)).replace(
            "./p662.warteschlange.mjs", "./" + ws_gebaut.name
        ),
        encoding="utf-8",
    )
    echt.write_text(P662_ECHT, encoding="utf-8")
    treiber.write_text(
        (
            P662_TREIBER
            % (
                str(P662_WARTESCHLANGE), str(ws_gebaut),
                str(fahrer), str(fahrer_gebaut),
                "./" + fahrer_gebaut.name,
            )
        ).replace("./p662.echt.mjs", "./" + echt.name),
        encoding="utf-8",
    )
    try:
        lauf = subprocess.run(
            ["node", treiber.name],
            cwd=P662_FRONTEND, capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
    finally:
        for pfad in (fahrer, treiber, ws_gebaut, fahrer_gebaut, echt):
            pfad.unlink(missing_ok=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-2000:]
    marke = "---BERICHT---"
    assert marke in lauf.stdout, lauf.stdout[-2000:]
    return json.loads(lauf.stdout.split(marke, 1)[1].strip())


p662_braucht_node = pytest.mark.skipif(
    shutil.which("node") is None or not (P662_FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)


@p662_braucht_node
def test_ein_fremder_lauf_im_nachladen_wird_angehaengt_statt_ueberrannt():
    """The service releases a run before it sends `done`, and a wake can
    start in that gap and write its own live row. The reconcile fetched
    that row: drawn as running with no stream behind it, never cleared,
    and the queue sent into a chat the service had already claimed.

    The page's `laufend` names that run. It is reattached the moment this
    run lets go — synchronously, so the queue effect the release wakes
    finds the chat taken and holds."""
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    globalThis.__laufend = { generation_id: 'g-wecken', message_id: 'a-wecken' }
    dienst.push({ id: 'a-wecken', role: 'assistant', content: '', zustand: 'laeuft' })
    await laufEnde({
      zielChat: 'A', abgebrochen: false, gescheitert: false,
      platzhalter: p1, verdichtetZu: 'naht',
    })
    await new Promise((frei) => setTimeout(frei, 5))
    return {
      protokoll,
      laeuft: Boolean(zustand.laeuft.A),
      wartet: fuerChat('A').length,
    }
        """,
    )
    assert ["wiederanhaengen", "g-wecken", "a-wecken"] in bericht["protokoll"], bericht["protokoll"]
    assert "senden" not in bericht["protokoll"], (
        f"the queue sent into a chat another run already holds: {bericht['protokoll']}"
    )
    assert bericht["laeuft"], "the foreign run was not registered in the window"
    assert bericht["wartet"] == 1, "the queued message was lost"


@p662_braucht_node
def test_a_queued_message_the_service_turned_away_goes_back_in_line_and_leaves_once_free():
    """Another window holds the chat (it folds), the queue's send meets the
    409: the message goes back to the front of its own line and not into the
    field, waits for the claim the way the end of a held chat does, and is
    sent — once — when the chat is free."""
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    globalThis.__claims = [
      { laufend: null, gehalten: true },    // the claim stands
      { laufend: null, gehalten: false },   // gone: the wait is over
      { laufend: null, gehalten: false },
    ]
    // The queue took the entry out for sending (the chat was free for it).
    const eintrag = ausreihen('A')
    zustand.nachrichten.push({ id: 'eigen-x', role: 'user', content: 'zwei' })
    const nachDemAbweis = []
    const ende = laufEnde({
      zielChat: 'A', abgebrochen: false, gescheitert: false, belegt: true,
      platzhalter: { id: 'platzhalter-A', role: 'assistant', content: '' },
      inhalt: 'zwei', nachrichtId: 'x', ausReihe: eintrag, begun: false,
      lauf: { generationId: null },
    })
    await new Promise((frei) => setTimeout(frei, 0))
    nachDemAbweis.push({ inReihe: fuerChat('A').map((e) => e.inhalt), gehalten: Boolean(zustand.sendet.A) })
    await ende
    await new Promise((frei) => setTimeout(frei, 20))
    return {
      protokoll, nachDemAbweis, gesendet: protokoll.filter((p) => p === 'senden').length,
      wartet: fuerChat('A').map((e) => e.inhalt),
    }
        """,
    )
    assert bericht["nachDemAbweis"][0]["inReihe"] == ["zwei"], bericht
    assert not any(isinstance(p, list) and p[0] == "zurueckgegeben" for p in bericht["protokoll"]), (
        f"the message was handed back to the field: {bericht['protokoll']}"
    )
    assert bericht["gesendet"] == 1, f"sent {bericht['gesendet']} times: {bericht['protokoll']}"
    assert bericht["wartet"] == []


@p662_braucht_node
def test_a_typed_message_the_service_turned_away_still_goes_back_to_the_field():
    """Silence probe: no entry of the queue, the words go back to the field
    as they always did and nothing waits."""
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    ausreihen('A')
    await laufEnde({
      zielChat: 'A', abgebrochen: false, gescheitert: false, belegt: true,
      platzhalter: { id: 'platzhalter-A', role: 'assistant', content: '' },
      inhalt: 'getippt', nachrichtId: 'y', ausReihe: null, begun: false,
      lauf: { generationId: null },
    })
    return { protokoll, wartet: fuerChat('A').length }
        """,
    )
    assert ["zurueckgegeben", "getippt", "A", "y"] in bericht["protokoll"], bericht["protokoll"]
    assert bericht["wartet"] == 0


@p662_braucht_node
def test_two_queued_messages_keep_their_order_when_the_first_is_turned_away():
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    einreihen('A', { inhalt: 'drei' })
    globalThis.__claims = [{ laufend: null, gehalten: true }, { laufend: null, gehalten: false }]
    const eintrag = ausreihen('A')               // 'zwei'
    const ende = laufEnde({
      zielChat: 'A', abgebrochen: false, gescheitert: false, belegt: true,
      platzhalter: { id: 'platzhalter-A', role: 'assistant', content: '' },
      inhalt: 'zwei', nachrichtId: 'x', ausReihe: eintrag, begun: false,
      lauf: { generationId: null },
    })
    await new Promise((frei) => setTimeout(frei, 0))
    const reihe = fuerChat('A').map((e) => e.inhalt)
    await ende
    return { reihe }
        """,
    )
    assert bericht["reihe"] == ["zwei", "drei"], bericht


@p662_braucht_node
def test_a_message_turned_away_twice_in_a_row_goes_back_to_the_field():
    """Silence probe for the loop guard: refused again before one check of
    the claim's clock has passed, it is no claim that ends — the words go
    back to the field and nothing is sent in a circle."""
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    const eintrag = ausreihen('A')
    eintrag.abgewiesenUm = Date.now()            // refused a moment ago already
    await laufEnde({
      zielChat: 'A', abgebrochen: false, gescheitert: false, belegt: true,
      platzhalter: { id: 'platzhalter-A', role: 'assistant', content: '' },
      inhalt: 'zwei', nachrichtId: 'x', ausReihe: eintrag, begun: false,
      lauf: { generationId: null },
    })
    return { protokoll, wartet: fuerChat('A').length }
        """,
    )
    assert ["zurueckgegeben", "zwei", "A", "x"] in bericht["protokoll"], bericht["protokoll"]
    assert bericht["wartet"] == 0
    assert "senden" not in bericht["protokoll"]


@p662_braucht_node
def test_stop_cuts_the_wait_for_a_foreign_claim_short_and_the_line_holds():
    """The end of an answer waits for another window's claim on the chat.
    The stop button reaches the claim through the chat's id, the wait ends at
    once — long before the check interval — and the queue does not send."""
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    globalThis.__claims = Array.from({ length: 50 }, () => ({ laufend: null, gehalten: true }))
    const begonnen = Date.now()
    const ende = laufEnde({
      zielChat: 'A', abgebrochen: false, gescheitert: false,
      platzhalter: p1, verdichtetZu: 'naht', heldWithoutRun: true,
    })
    await new Promise((frei) => setTimeout(frei, 50))
    const wartetVorStopp = anspruchWarten.has('A')
    await abbrechen()
    await ende
    return {
      protokoll, wartetVorStopp, dauer: Date.now() - begonnen,
      wartetNachStopp: anspruchWarten.has('A'),
      haelt: fuerChat('A').map((e) => e.haelt),
      gesendet: protokoll.filter((p) => p === 'senden').length,
      gehalten: Boolean(zustand.sendet.A),
    }
        """,
    )
    assert bericht["wartetVorStopp"] is True
    assert ["stop", None, "A"] in bericht["protokoll"], bericht["protokoll"]
    assert bericht["dauer"] < 400, f"the wait outlived the stop: {bericht['dauer']} ms"
    assert bericht["wartetNachStopp"] is False
    assert bericht["haelt"] == [True], "the queue does not hold after the stop"
    assert bericht["gesendet"] == 0
    assert bericht["gehalten"] is False


@p662_braucht_node
def test_stop_without_a_run_and_without_a_waiting_claim_does_nothing():
    """Silence probe: no claim is waited for, no run — no request goes out."""
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    ausreihen('A')                                // nothing in line to send
    delete zustand.laeuft.A
    delete zustand.laufenderPlatzhalter.A
    flushSync()
    await abbrechen()
    return { protokoll: protokoll.filter((p) => Array.isArray(p) && p[0] === 'stop') }
        """,
    )
    assert bericht["protokoll"] == []


@p662_braucht_node
@pytest.mark.parametrize("model_off", [True, False])
def test_a_switched_off_model_holds_the_queue(model_off):
    """The chat's model is switched off in the quick picker: the run ends and
    the queued message stays in line instead of going to it. Silence probe:
    with the model on, the same message goes."""
    report = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + f"""
    globalThis.__modelOff = {str(model_off).lower()}
    await laufEnde({{
      zielChat: 'A', abgebrochen: false, gescheitert: false,
      platzhalter: p1, verdichtetZu: 'naht',
    }})
    await new Promise((done) => setTimeout(done, 5))
    return {{ protokoll, wartet: fuerChat('A').length }}
        """,
    )
    sent = any(e == "senden" or (isinstance(e, list) and e and e[0] == "senden")
                   for e in report["protokoll"])
    if model_off:
        assert not sent, f"the queue sent to a switched-off model: {report['protokoll']}"
        assert report["wartet"] == 1, "the queued message was lost"
    else:
        assert sent, f"the queue did not move with the model on: {report['protokoll']}"


@p662_braucht_node
def test_a_held_chat_keeps_the_queue_waiting_until_the_claim_goes():
    """The reconcile finds the chat held with no run named yet: a send that
    claimed it is still folding its history. The queue waits while the claim
    stands and moves once it is gone — sending into it at once only ran into
    a 409."""
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    globalThis.__claims = [
      { laufend: null, gehalten: true },
      { laufend: null, gehalten: true },
      { laufend: null, gehalten: false, add: { id: 'other', role: 'user', content: 'other' } },
    ]
    await laufEnde({
      zielChat: 'A', abgebrochen: false, gescheitert: false,
      platzhalter: p1, verdichtetZu: 'naht',
    })
    const otherShown = zustand.nachrichten.some((n) => n.id === 'other')
    await new Promise((frei) => setTimeout(frei, 5))
    return { protokoll, sendet: Boolean(zustand.sendet.A), otherShown }
        """,
    )
    protokoll = bericht["protokoll"]
    fragen = [i for i, z in enumerate(protokoll) if z == "api.nachrichten"]
    # The reconcile, two questions about the claim, and the list fetched
    # again once it is gone.
    assert len(fragen) == 4, protokoll
    assert "senden" in protokoll, f"the queue never moved once the claim was gone: {protokoll}"
    assert protokoll.index("senden") > fragen[-1], (
        f"the queue sent into a chat the service still held: {protokoll}"
    )
    assert not bericht["sendet"], "the hold mark outlived the claim"
    assert bericht["otherShown"], "the other send's rows were not fetched after the claim"


@p662_braucht_node
def test_a_held_chat_after_a_fresh_send_leaves_the_gate_to_that_send():
    """The common case: a fresh send holds its own send-in-flight mark until
    `antwortHolen` returns. The end of the run leaves that mark alone and
    waits for the claim behind it; the queue moves only once the send lifts
    its mark."""
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    zustand.sendet.A = true
    globalThis.__claims = [
      { laufend: null, gehalten: true },
      { laufend: null, gehalten: false },
    ]
    await laufEnde({
      zielChat: 'A', abgebrochen: false, gescheitert: false,
      platzhalter: p1, verdichtetZu: 'naht',
    })
    await new Promise((frei) => setTimeout(frei, 5))
    const before = [...protokoll]
    const markKept = Boolean(zustand.sendet.A)
    delete zustand.sendet.A
    await new Promise((frei) => setTimeout(frei, 5))
    return { before, protokoll, markKept }
        """,
    )
    assert bericht["markKept"], "the end of the run took the send's own mark away"
    assert "senden" not in bericht["before"], bericht["before"]
    assert bericht["before"].count("api.nachrichten") == 3, bericht["before"]
    assert "senden" in bericht["protokoll"], bericht["protokoll"]


@p662_braucht_node
def test_a_held_chat_whose_service_stops_answering_lets_the_queue_go():
    """Partial failure: the service stops answering while the chat is held.
    A line that is gone cannot be waited for — the mark goes and the queue
    moves."""
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    globalThis.__claims = [{ laufend: null, gehalten: true }, 'offline']
    await laufEnde({
      zielChat: 'A', abgebrochen: false, gescheitert: false,
      platzhalter: p1, verdichtetZu: 'naht',
    })
    await new Promise((frei) => setTimeout(frei, 5))
    return { protokoll }
        """,
    )
    assert "senden" in bericht["protokoll"], bericht["protokoll"]


@p662_braucht_node
def test_a_named_run_that_is_over_by_the_refetch_is_not_replayed():
    """The claim became a run, and the run is over by the time the list is
    fetched again: the fresher word wins, nothing finished is replayed."""
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    globalThis.__claims = [
      { laufend: null, gehalten: true },
      { laufend: { generation_id: 'g-neu', message_id: 'a-neu' }, gehalten: false },
      { laufend: null, gehalten: false, add: { id: 'a-neu', role: 'assistant', content: 'done' } },
    ]
    await laufEnde({
      zielChat: 'A', abgebrochen: false, gescheitert: false,
      platzhalter: p1, verdichtetZu: 'naht',
    })
    const finishedShown = zustand.nachrichten.some((n) => n.id === 'a-neu')
    await new Promise((frei) => setTimeout(frei, 5))
    return { protokoll, finishedShown }
        """,
    )
    assert not [z for z in bericht["protokoll"] if z[0] == "wiederanhaengen"], bericht["protokoll"]
    assert bericht["finishedShown"], "the finished answer did not come in with the list"
    assert "senden" in bericht["protokoll"], bericht["protokoll"]


@p662_braucht_node
def test_a_claimed_run_is_attached_when_the_refetch_fails():
    """Partial failure: the claim became a run and the list cannot be
    fetched again — the run is attached as it stands, not dropped."""
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    globalThis.__claims = [
      { laufend: null, gehalten: true },
      { laufend: { generation_id: 'g-neu', message_id: 'a-neu' }, gehalten: false },
      'offline',
    ]
    await laufEnde({
      zielChat: 'A', abgebrochen: false, gescheitert: false,
      platzhalter: p1, verdichtetZu: 'naht',
    })
    await new Promise((frei) => setTimeout(frei, 5))
    return { protokoll }
        """,
    )
    assert ["wiederanhaengen", "g-neu", "a-neu"] in bericht["protokoll"], bericht["protokoll"]
    assert "senden" not in bericht["protokoll"], bericht["protokoll"]


@p662_braucht_node
def test_a_held_chat_whose_claim_becomes_a_run_is_attached():
    """Held, then the claim turns into a run: the window attaches to it, and
    the queued message keeps waiting behind that run."""
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    globalThis.__claims = [
      { laufend: null, gehalten: true },
      { laufend: { generation_id: 'g-neu', message_id: 'a-neu' }, gehalten: false },
      { laufend: { generation_id: 'g-neu', message_id: 'a-neu' }, gehalten: false },
    ]
    await laufEnde({
      zielChat: 'A', abgebrochen: false, gescheitert: false,
      platzhalter: p1, verdichtetZu: 'naht',
    })
    await new Promise((frei) => setTimeout(frei, 5))
    return { protokoll, laeuft: Boolean(zustand.laeuft.A), wartet: fuerChat('A').length }
        """,
    )
    assert ["wiederanhaengen", "g-neu", "a-neu"] in bericht["protokoll"], bericht["protokoll"]
    assert "senden" not in bericht["protokoll"], bericht["protokoll"]
    assert bericht["laeuft"]
    assert bericht["wartet"] == 1


@p662_braucht_node
def test_a_run_the_service_still_runs_is_attached_again():
    """The line to this very run was refused while the run went on: the
    reconcile brings its row back carrying `zustand: 'laeuft'`. Skipped as
    "our own", that row stood as running with no stream behind it for good;
    it is attached again instead."""
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    globalThis.__laufend = { generation_id: 'eigen', message_id: 'a1' }
    dienst[2].zustand = 'laeuft'
    await laufEnde({
      zielChat: 'A', abgebrochen: false, gescheitert: true,
      platzhalter: p1, verdichtetZu: null, zeileNachladen: true,
      lauf: { generationId: 'eigen' },
    })
    await new Promise((frei) => setTimeout(frei, 5))
    return { protokoll, laeuft: Boolean(zustand.laeuft.A), haelt: haelt('A') }
        """,
    )
    assert ["wiederanhaengen", "eigen", "a1"] in bericht["protokoll"], bericht["protokoll"]
    assert bericht["laeuft"], "the live row was left with no stream behind it"
    assert "senden" not in bericht["protokoll"], bericht["protokoll"]
    # A refused line, not a failed run: the queue does not hold for it, and
    # the failure mark goes.
    assert not bericht["haelt"], "the queue holds behind a run that goes on"
    assert "chatFehlerGesehen" in bericht["protokoll"], bericht["protokoll"]


@p662_braucht_node
def test_a_refused_reattach_of_the_own_run_is_not_attached_a_third_time():
    """The own run was attached again once already, and that line is
    refused too: no further reattach, or a line that keeps refusing would
    loop with a notice every round. Its row keeps no running mark."""
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    globalThis.__laufend = { generation_id: 'eigen', message_id: 'a1' }
    dienst[2].zustand = 'laeuft'
    ownRunsReattached.add('eigen')
    await laufEnde({
      zielChat: 'A', abgebrochen: false, gescheitert: true,
      platzhalter: p1, verdichtetZu: null, zeileNachladen: true,
      lauf: { generationId: 'eigen' },
      wiederanhang: { chatId: 'A', generationId: 'eigen', messageId: 'a1' },
    })
    await new Promise((frei) => setTimeout(frei, 5))
    return {
      protokoll, haelt: haelt('A'),
      zeile: zustand.nachrichten.find((n) => n.id === 'a1')?.zustand ?? null,
    }
        """,
    )
    assert not [z for z in bericht["protokoll"] if z[0] == "wiederanhaengen"], bericht["protokoll"]
    assert bericht["haelt"]
    assert bericht["zeile"] is None, "the row stands as running with no stream behind it"


@p662_braucht_node
def test_a_run_stopped_here_that_the_service_still_names_is_not_attached():
    """Stopped from here, and the service has not taken the stop in yet:
    the run is not attached again (the stop would look as if it did
    nothing). Its row says stopped instead of standing as running."""
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    globalThis.__laufend = { generation_id: 'eigen', message_id: 'a1' }
    dienst[2].zustand = 'laeuft'
    await laufEnde({
      zielChat: 'A', abgebrochen: true, gescheitert: false,
      platzhalter: p1, verdichtetZu: null, zeileNachladen: true,
      lauf: { generationId: 'eigen' },
    })
    await new Promise((frei) => setTimeout(frei, 5))
    return {
      protokoll,
      zeile: zustand.nachrichten.find((n) => n.id === 'a1')?.zustand ?? null,
      haelt: haelt('A'),
    }
        """,
    )
    assert not [z for z in bericht["protokoll"] if z[0] == "wiederanhaengen"], bericht["protokoll"]
    assert bericht["zeile"] == "abgebrochen"
    assert bericht["haelt"]


def _stopped_by_service(abgebrochen: bool) -> dict:
    """A `done` event read by the shipped branch, then the run's end, with
    the window in the background where the dots are drawn."""
    quelle = _p662_quelle()
    zweig = _p662_stueck(
        quelle,
        r"verdichtetZu = ereignis\.verdichtet \?\? null\n.*?"
        r"if \(ereignis\.abgebrochen\) abgebrochen = true\n",
        "the done branch",
    )
    return _p662_lauf(
        quelle,
        P662_AUFBAU
        + f"""
    globalThis.__unfocused = true
    let abgebrochen = false
    let verdichtetZu = null
    let schlussZustand = null
    const ereignis = {json.dumps({
        "typ": "done", "abgebrochen": abgebrochen,
        "zustand": "abgebrochen" if abgebrochen else "fertig",
    })}
    {zweig}
    await laufEnde({{
      zielChat: 'A', abgebrochen, gescheitert: false,
      platzhalter: p1, verdichtetZu, schlussZustand,
    }})
    await new Promise((frei) => setTimeout(frei, 5))
    return {{ protokoll, zustand: p1.zustand, haelt: haelt('A') }}
        """,
    )


@p662_braucht_node
def test_a_run_stopped_on_the_service_is_no_finished_answer():
    """A `done` that says the run was stopped (another window, or before it
    began) and no stop of this window's own: no green dot, no red one, the
    bubble says stopped, and the queue holds as after any stop."""
    bericht = _stopped_by_service(abgebrochen=True)
    assert "chatFertigMerken" not in bericht["protokoll"], bericht["protokoll"]
    assert "chatFehlerMerken" not in bericht["protokoll"], bericht["protokoll"]
    assert bericht["zustand"] == "abgebrochen"
    assert bericht["haelt"]
    assert "senden" not in bericht["protokoll"]


@p662_braucht_node
def test_a_finished_run_in_the_background_still_gets_its_dot():
    """Silence probe: an ordinary `done` keeps the green dot and lets the
    queue move."""
    bericht = _stopped_by_service(abgebrochen=False)
    assert "chatFertigMerken" in bericht["protokoll"], bericht["protokoll"]
    assert bericht["zustand"] == "fertig"
    assert not bericht["haelt"]


@p662_braucht_node
def test_a_run_stopped_here_before_anything_came_says_stopped():
    """Stopped by this window before the service sent anything: no `done`,
    and the bubble said "the model wrote nothing". It says stopped."""
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    p1.content = ''
    await laufEnde({
      zielChat: 'A', abgebrochen: true, gescheitert: false,
      platzhalter: p1, verdichtetZu: null, schlussZustand: null,
    })
    return { zustand: p1.zustand }
        """,
    )
    assert bericht["zustand"] == "abgebrochen"


@p662_braucht_node
def test_a_broken_line_without_done_keeps_no_word():
    """Silence probe: a line that broke without `done` and without a stop is
    left with no word rather than a guessed one."""
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    await laufEnde({
      zielChat: 'A', abgebrochen: false, gescheitert: true,
      platzhalter: p1, verdichtetZu: null, schlussZustand: null,
    })
    return { zustand: p1.zustand ?? null }
        """,
    )
    assert bericht["zustand"] is None


@p662_braucht_node
def test_das_nachladen_wirft_die_wartende_nachricht_nicht_weg():
    """⛔ The regression. A compaction made the reconcile at the end of a run
    fire in ordinary chats, and it replaces `zustand.nachrichten` outright.

    With the release at the top of the block, `delete zustand.laeuft` armed
    the queue effect and the first await let it through: the next message was
    sent, pushed its own bubble and its placeholder, and the replacement two
    lines later threw both away. On screen the second question was simply
    gone, the answer streamed into an object nothing draws, and the bar went
    on offering a stop button for it. It does not heal on its own — after a
    fold the history is short again, so the second run reports no compaction
    of its own and never reconciles.

    Three things are asserted, and the third is the one that matters most:
    the pointer this window writes through has to name a row that is really
    in the list. A pointer into nowhere is what makes the answer invisible.
    """
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    await laufEnde({
      zielChat: 'A', abgebrochen: false, gescheitert: false,
      platzhalter: p1, verdichtetZu: 'naht',
    })
    const zeiger = zustand.laufenderPlatzhalter.A
    return {
      protokoll,
      ids: zustand.nachrichten.map((n) => n.id),
      zweite_frage_da: zustand.nachrichten.some((n) => n.content === 'zwei'),
      zeiger_in_liste: zustand.nachrichten.includes(zeiger),
      naht_da: zustand.nachrichten.some((n) => n.id === 'naht'),
      antwort_eins_da: zustand.nachrichten.some((n) => n.content === 'antwort eins'),
    }
        """,
    )
    assert bericht["protokoll"].index("api.nachrichten") < bericht["protokoll"].index(
        "senden"
    ), (
        f"the queue fires before the reconcile -- what it puts in is replaced right "
        f"after (order: {bericht['protokoll']})"
    )
    assert bericht["zweite_frage_da"], (
        f"the second question has vanished from the screen (list: {bericht['ids']})"
    )
    assert bericht["zeiger_in_liste"], (
        "laufenderPlatzhalter points at a row that is no longer in the list -- the "
        "second run writes into an orphan object"
    )
    # And the reconcile still does what it was added for.
    assert bericht["naht_da"], "the seam is missing -- the reconcile was undone"
    assert bericht["antwort_eins_da"], "the window's own finished answer is gone"


@p662_braucht_node
def test_die_nachgeladene_zeile_traegt_keine_fremde_wartemarke():
    """The worse half of the same race, and the half that outlives the
    session. `generierung.py` writes the answer's row with `zustand: 'laeuft'`
    the moment a run starts, so once the queue has fired, the reconcile can
    bring that row back — and `zustand === 'laeuft'` is drawn as a waiting
    mark by App.svelte.

    Nothing in this window ever clears that field on a row it did not adopt.
    The second run only ever writes through `laufenderPlatzhalter`, which the
    replacement has just orphaned, so its own cleanup lands on the invisible
    object and the visible bubble keeps the mark and its frozen token count
    for the rest of the session.

    The fix removes the case rather than repairing it: the reconcile happens
    while the chat is still claimed, so there is no second run for the
    service to have a row for.
    """
    bericht = _p662_lauf(
        _p662_quelle(),
        """
    globalThis.__dienstSchreibtSofort = true
        """
        + P662_AUFBAU
        + """
    await laufEnde({
      zielChat: 'A', abgebrochen: false, gescheitert: false,
      platzhalter: p1, verdichtetZu: 'naht',
    })
    const zeiger = zustand.laufenderPlatzhalter.A
    return {
      ids: zustand.nachrichten.map((n) => n.id),
      fremde_wartemarke: zustand.nachrichten.some(
        (n) => n.zustand === 'laeuft' && n !== zeiger,
      ),
    }
        """,
    )
    assert not bericht["fremde_wartemarke"], (
        f"a row carries zustand='laeuft' without this window ever being able to touch "
        f"it again -- the waiting mark stays (list: {bericht['ids']})"
    )


@p662_braucht_node
def test_ein_gestoppter_lauf_haelt_die_schlange_bevor_er_sie_freigibt():
    """The second defect at the same place, and an older one. `anhalten`
    stood BELOW the release, past two awaits — so a run that failed or was
    stopped by hand let the line go on its way out and only afterwards said
    it should have held. The waiting message was already gone by then, fired
    into exactly the state that had just gone wrong.

    `warteschlange.svelte.js` opens with that promise in as many words, and
    it was the one thing the queue could not keep.
    """
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    await laufEnde({
      zielChat: 'A', abgebrochen: true, gescheitert: false,
      platzhalter: p1, verdichtetZu: null,
    })
    return {
      losgeschickt: protokoll.includes('senden'),
      rest: fuerChat('A').map((e) => e.inhalt),
      haelt: haelt('A'),
    }
        """,
    )
    assert not bericht["losgeschickt"], (
        "the stopped run sent the waiting message anyway"
    )
    assert bericht["rest"] == ["zwei"], f"the message is no longer queued: {bericht['rest']}"
    assert bericht["haelt"], "the bubble does not carry the hold mark"


# --- An owed reattachment must not outlive the run it names ---------------
#
# `chatOeffnen` writes `zustand.wiederanhaengen[chatId]` in one
# branch — `else if (laufend && !zustand.laeuft[id])` — and nothing ever took
# it back. The map is deliberately keyed by chat so an entry may WAIT: it is
# written for whichever chat the fetch was about, and App.svelte's effect
# spends it only once that chat is the one on screen. Waiting is the feature;
# waiting past the end of the run it names is the defect. A run that finished
# while another chat was in front left its entry lying, and the next visit to
# that chat replayed a generation the service had dropped long ago
# (app/generationen.py keeps the last fifty, and a restart keeps none): two
# 404s and an empty bubble beside the finished answer.
#
# Not readable out of the file, for the same reason the block above is not:
# what decides it is WHEN the effect runs against WHEN the fetch answers.
# Svelte flushes effects on the microtask after `zustand.aktiverChat = id`,
# which is a whole round trip before `api.nachrichten` replies — so a
# withdrawal written at the fetch, which is where it looks like it belongs,
# arrives too late to stop the very open that triggers it. Only running it
# shows that. So the real state module is compiled with Svelte's own
# compiler and driven in node, the way ``tests/test_agentenampel.py`` drives
# the rail dot, with the two stretches of App.svelte that take part in the
# handover lifted out of the shipped component rather than described.

P666_FRONTEND = WURZEL / "frontend"

# On the two tests below rather than on the module: a `pytestmark` here would
# take every house rule in this file with it the moment node is missing.
P666_BRAUCHT_NODE = pytest.mark.skipif(
    shutil.which("node") is None or not (P666_FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

# The modules zustand.svelte.js imports, all but the two copied as shipped
# (the activity helper and the chat layout table). Only these are stubbed — the
# decision under test is the shipped one. `api.nachrichten` is handed out
# through a global so the scenario can hold the answer back and let the
# effect run first, which is the whole race.
P666_STUMPFE = {
    # The frame's hue turn: hand the colour through untouched — these runs
    # decide chat entries, never a painted frame.
    "agentenfarbe.mjs": "export function farbtonDrehen(farbe) { return farbe }\n",
    "api.mjs": "export const api = { nachrichten: (id) => globalThis.__nachrichten(id) }\n",
    "anzeige.mjs": (
        "export const VORGABE_DARSTELLUNG = {}\n"
        "export const VORGABE_LAYOUT = {}\n"
        "export function darstellungSpeichern() {}\n"
        "export function layoutSpeichern() {}\n"
        "export function modellSpeichern() {}\n"
        "export function keptModelName() { return '' }\n"
        "export async function storedModelId() { return '' }\n"
    ),
    "chatanzeige.mjs": (
        "export const chatanzeige = { chatId: null, geladen: false }\n"
        "export const chatless = { pictureValues: null }\n"
        "export function chatZustandLaden() {}\n"
    ),
    "fensterweg.mjs": (
        "export function ausFenster() { return null }\n"
        "export function ohneWeg(x) { return x }\n"
    ),
    "meldewesen.mjs": (
        "export const meldungen = []\n"
        "export function melde(text, art) { globalThis.__protokoll.push(['melde', art]) }\n"
        "export function melden() {}\n"
        "export function aktualisiereMeldung() {}\n"
        "export function meldungenZuAuftragSchliessen() {}\n"
        "export function schliesseMeldung() {}\n"
    ),
    "texte.mjs": "export function t(schluessel) { return schluessel }\n",
    "warteschlange.mjs": "export function leeren() {}\n",
}

# The module writes the five display values onto the root element as it
# loads. Without a DOM a stub that does nothing is enough — nothing under
# test reads them back.
P666_DOM = """
globalThis.document = { documentElement: {
  setAttribute() {}, removeAttribute() {},
  style: { setProperty() {}, removeProperty() {} },
} }
"""

# %s is the wipe block lifted from App.svelte, %s the effect that spends the
# entry, %s the scenario.
P666_FAHRER = """
import { zustand, chatOeffnen, laufVon } from './zustand.mjs'
import { taetigkeitSetzen } from './taetigkeit.mjs'
import { flushSync } from 'svelte'

globalThis.__protokoll = []
const protokoll = globalThis.__protokoll

/* The service. Its answer is held until `aufloesen` lets it go — that is
   what makes "the effect runs before the fetch replies" reproducible
   instead of asserted. A held promise plus a macrotask is exactly the
   distance a real request has: Svelte's effects are microtasks and get
   there first, every time. */
let dienst = {}
let offen = []
// A scenario sets this right before triggering a call that must fail —
// the flag is read at QUEUE time (this call, not a later one) and reset
// at once, so only that one open answers with a rejection.
globalThis.__naechsterFehlschlag = false
globalThis.__nachrichten = (id) => new Promise((loesen, ablehnen) => {
  protokoll.push(['api.nachrichten', id])
  const fehlschlagen = globalThis.__naechsterFehlschlag
  globalThis.__naechsterFehlschlag = false
  offen.push(() => (fehlschlagen ? ablehnen(new Error('offline')) : loesen({
    nachrichten: (dienst[id]?.zeilen ?? []).map((z) => ({ ...z })),
    laufend: dienst[id]?.laufend ?? null,
  })))
})
const aufloesen = async () => {
  const jetzt = offen
  offen = []
  jetzt.forEach((f) => f())
  for (let i = 0; i < 8; i++) await new Promise((f) => setTimeout(f, 0))
  flushSync()
  for (let i = 0; i < 8; i++) await new Promise((f) => setTimeout(f, 0))
  flushSync()
}

/* The replay. `erreichbar: false` is a run the service has forgotten — the
   fiftieth run after it, or a restart — and that answers 404, which is what
   api.js turns into a throw. */
class ApiFehler extends Error {
  constructor(text, status) {
    super(text)
    this.name = 'ApiFehler'
    this.status = status
  }
}
let erreichbar = true
async function* zusehenStrom(generationId, ab) {
  protokoll.push(['zusehenStrom', generationId, ab])
  if (!erreichbar) throw new ApiFehler('Fehler 404', 404)
  yield { typ: 'content', text: 'the answer once more' }
}

/* antwortHolen, cut down to the handover. The block that adopts the row and
   empties it is the shipped one, lifted from App.svelte; the placeholder
   push after it and the two entries in `laufenderPlatzhalter` / `laeuft` are
   modelled from the same function (App.svelte, 'Stable key, same reason as
   the picture placeholder') because chatOeffnen's own rescue reads them —
   that rescue is how the stray placeholder reaches the freshly loaded list.
   Everything down to the first await is synchronous there and here. */
async function antwortHolen(inhalt, bilder, dokumente, denken, skill, wiederanhang) {
  const zielChat = wiederanhang ? wiederanhang.chatId : zustand.aktiverChat
  protokoll.push(['antwortHolen', zielChat, wiederanhang?.generationId ?? null])
%s
  if (!uebernehmen) {
    zustand.nachrichten.push({
      id: `platzhalter-${zielChat}`, role: 'assistant', content: '',
      reasoning: '', stats: {}, werkzeuge: [], abschnitte: [],
    })
  }
  const platzhalter = uebernehmen ?? zustand.nachrichten[zustand.nachrichten.length - 1]
  zustand.laufenderPlatzhalter[zielChat] = platzhalter
  const lauf = { generationId: wiederanhang?.generationId ?? null, chatId: zielChat }
  zustand.laeuft[zielChat] = lauf
  let ereignisZahl = 0
  try {
    try {
      for await (const e of zusehenStrom(wiederanhang.generationId, 0)) {
        platzhalter.content += e.text
        ereignisZahl++
      }
    } catch (fehler) {
      if (fehler.name === 'AbortError' || !lauf.generationId) throw fehler
      for await (const e of zusehenStrom(lauf.generationId, ereignisZahl)) {
        platzhalter.content += e.text
        ereignisZahl++
      }
    }
  } catch (fehler) {
    protokoll.push(['gescheitert', String(fehler.message)])
  } finally {
    delete zustand.laeuft[zielChat]
    if (zustand.laufenderPlatzhalter[zielChat] === platzhalter) {
      delete zustand.laufenderPlatzhalter[zielChat]
    }
  }
}

async function antwortWiederAnhaengen(wiederanhang) {
  const { chatId } = wiederanhang
  if (zustand.aktiverChat !== chatId || laufVon(chatId)) return
  await antwortHolen(null, null, null, null, null, wiederanhang)
}

/* The row the service keeps for the answer: half written while the run goes
   (carrying `zustand: 'laeuft'`, which only the service ever sets), whole
   once it has ended. */
const HALB = {
  id: 'm2', role: 'assistant', content: 'half ', zustand: 'laeuft',
  stats: {}, werkzeuge: [], abschnitte: [], gesamt_tokens: 4000,
}
const GANZ = {
  id: 'm2', role: 'assistant', content: 'the finished answer',
  reasoning: 'this is how it thought', zustand: null, stats: { dauer: 12.5 },
  werkzeuge: [{ name: 'lesen' }], abschnitte: [{ art: 'text' }],
  gesamt_tokens: 8123,
}
const FRAGE = { id: 'm1', role: 'user', content: 'question' }

export async function fahren() {
  const stop = $effect.root(() => {
%s
  })
  flushSync()
  const bericht = await (async () => {
%s
  })()
  stop()
  return { ...bericht, protokoll }
}
"""

# Chat B is answered while B is opened; before the answer to that open
# arrives the reader is already in chat A. The entry for B is written after
# that, and waits — which is what it is for.
P666_AUFBAU = """
    dienst = {
      A: { zeilen: [{ id: 'a1', role: 'user', content: 'chat a' }], laufend: null },
      B: { zeilen: [FRAGE, { ...HALB }], laufend: { generation_id: 'G1', message_id: 'm2' } },
    }
    const bOffen = chatOeffnen('B')
    const aOffen = chatOeffnen('A')
    await aufloesen()
    await bOffen
    await aOffen
"""


def _p666_zustand() -> str:
    """The state module as it stands. Its own function, so a check of this
    test can hand it another revision without touching the working tree."""
    return (WURZEL / "frontend/src/lib/zustand.svelte.js").read_text(encoding="utf-8")


def _p666_lauf(zustand_quelle: str, szenario: str) -> dict:
    """Compile the real state module against stubs of its eight imports,
    build a driver out of the two shipped App.svelte stretches, run the
    scenario in node and hand back what it reports."""
    app_quelle = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")
    effekt = _p662_stueck(
        app_quelle,
        r"  \$effect\(\(\) => \{\n    const chatId = zustand\.aktiverChat\n.*?\n  \}\)",
        "der Wiederanhang-Effekt",
    )
    wischen = _p662_stueck(
        app_quelle,
        r"    const uebernehmen = wiederanhang\?\.messageId\n.*?"
        r"\n      uebernehmen\.gesamt_tokens = null\n    \}",
        "der Block, der die uebernommene Zeile leert",
    )
    # The helper that block asks for the question's own picture — the eye
    # mark of a reattach. Lifted too, so the real one decides here.
    fragebild = _p662_stueck(
        app_quelle,
        r"  function frageTrugBild\(zeile\) \{.*?\n  \}",
        "frageTrugBild",
    )

    # Under frontend/node_modules for the same two reasons as
    # tests/test_agentenampel.py: node resolves `svelte/compiler` by walking
    # up from the importing file, and an aborted run can leave nothing behind
    # in the working tree. The name is this call's own, so two runs at once
    # cannot write over each other.
    ordner = P666_FRONTEND / "node_modules" / f".pruefstand-p666-{uuid4().hex}"
    ordner.mkdir(parents=True)
    try:
        for name, inhalt in P666_STUMPFE.items():
            (ordner / name).write_text(inhalt, encoding="utf-8")
        # The reset block writes the activity through the shipped helper —
        # the real one, not a stub.
        (ordner / "taetigkeit.mjs").write_text(
            (WURZEL / "frontend/src/lib/taetigkeit.js").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        # The chat layout table has no imports of its own and touches the
        # page only where one exists — the real one runs here as shipped.
        (ordner / "chatlayout.js").write_text(
            (WURZEL / "frontend/src/lib/chatlayout.js").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (ordner / "zustand.svelte.js").write_text(
            zustand_quelle
            .replace("./agentenfarbe.svelte.js", "./agentenfarbe.mjs")
            .replace("./api.js", "./api.mjs")
            .replace("./anzeige.js", "./anzeige.mjs")
            .replace("./chatanzeige.svelte.js", "./chatanzeige.mjs")
            .replace("./fensterweg.svelte.js", "./fensterweg.mjs")
            .replace("./meldewesen.svelte.js", "./meldewesen.mjs")
            .replace("./texte.svelte.js", "./texte.mjs")
            .replace("./warteschlange.svelte.js", "./warteschlange.mjs"),
            encoding="utf-8",
        )
        (ordner / "fahrer.svelte.js").write_text(
            P666_FAHRER % (textwrap.indent(fragebild + "\n" + wischen, "  "), textwrap.indent(effekt, "  "), szenario),
            encoding="utf-8",
        )
        treiber = ordner / "pruefung.mjs"
        treiber.write_text(
            P666_DOM
            + textwrap.dedent(
                """
                import { compileModule } from 'svelte/compiler'
                import { readFileSync, writeFileSync } from 'fs'
                const bauen = (q, z, n) => writeFileSync(
                  z,
                  compileModule(readFileSync(q, 'utf-8'), {
                    filename: n, generate: 'client',
                  }).js.code,
                )
                bauen(%r, %r, 'zustand.svelte.js')
                bauen(%r, %r, 'fahrer.svelte.js')
                const { fahren } = await import(%r)
                console.log('---BERICHT---' + JSON.stringify(await fahren()))
                """
            )
            % (
                str(ordner / "zustand.svelte.js"), str(ordner / "zustand.mjs"),
                str(ordner / "fahrer.svelte.js"), str(ordner / "fahrer.mjs"),
                # An import wants a URL, not a path: a Windows path is read
                # as a protocol ('c:') and refused.
                (ordner / "fahrer.mjs").as_uri(),
            ),
            encoding="utf-8",
        )
        lauf = subprocess.run(
            ["node", str(treiber)],
            cwd=P666_FRONTEND, capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
    finally:
        shutil.rmtree(ordner, ignore_errors=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-2000:]
    assert "---BERICHT---" in lauf.stdout, lauf.stdout[-2000:]
    return json.loads(lauf.stdout.split("---BERICHT---")[1])


@P666_BRAUCHT_NODE
def test_ein_beendeter_lauf_laesst_keinen_wiederanhang_zurueck():
    """The run ends while another chat is in front, and by the time the
    reader comes back the service has forgotten it. Nothing may then be
    replayed: the answer stands finished in the list, and there is no stream
    left that could deliver it again.

    Left standing, the entry is spent on the next visit and takes the chat
    with it — `antwortHolen` runs against a message list that still belongs
    to the chat being left (the effect fires a whole round trip before
    `api.nachrichten` answers), finds no row of that id to adopt, pushes a
    placeholder, and `chatOeffnen`'s own rescue then carries that placeholder
    into the freshly loaded list. An empty bubble under the finished answer,
    two 404s, and an error notice for an answer that was never in trouble.
    """
    bericht = _p666_lauf(
        _p666_zustand(),
        P666_AUFBAU
        + """
    // The run finishes, and the service forgets it — fifty runs on, or a
    // restart. Both leave the same 404 behind.
    dienst.B = { zeilen: [FRAGE, { ...GANZ }], laufend: null }
    erreichbar = false

    const wieder = chatOeffnen('B')
    await aufloesen()
    await wieder
    return {
      liste: zustand.nachrichten.map((n) => ({ id: n.id, content: n.content })),
      offen: Object.keys(zustand.wiederanhaengen),
    }
        """,
    )
    geister = [z for z in bericht["liste"] if str(z["id"]).startswith("platzhalter-")]
    assert not geister, (
        f"an empty bubble stands beside the finished answer: {bericht['liste']}"
    )
    versuche = [z for z in bericht["protokoll"] if z[0] == "zusehenStrom"]
    assert not versuche, (
        f'a run long over is replayed once more: {versuche}'
    )
    assert not [z for z in bericht["protokoll"] if z[0] == "gescheitert"], (
        "the finished answer gets an error notice although nothing is missing"
    )
    fertig = [z for z in bericht["liste"] if z["id"] == "m2"]
    assert fertig and fertig[0]["content"] == "the finished answer", (
        f"the finished answer no longer stands intact: {bericht['liste']}"
    )


@P666_BRAUCHT_NODE
def test_ein_neustart_mitten_im_lauf_haengt_weiterhin_wieder_an():
    """The case the whole mechanism exists for, and it has to keep working:
    a window that opens a chat cold while the service is still writing the
    answer reattaches and takes the replay from its very first event.

    Guarding against the stale entry must not cost this one. It does not:
    what is cleared is cleared BEFORE the fetch, and the fetch writes the
    entry again from what the service says right now. A reload has no entry
    to clear in the first place.
    """
    bericht = _p666_lauf(
        _p666_zustand(),
        """
    // A window that has just started: it knows nothing, and the service is
    // in the middle of an answer.
    dienst = {
      B: { zeilen: [FRAGE, { ...HALB }], laufend: { generation_id: 'G1', message_id: 'm2' } },
    }
    const offen = chatOeffnen('B')
    await aufloesen()
    await offen
    return {
      liste: zustand.nachrichten.map((n) => ({ id: n.id, content: n.content })),
    }
        """,
    )
    versuche = [z for z in bericht["protokoll"] if z[0] == "zusehenStrom"]
    assert versuche, "a running run is no longer reattached"
    assert versuche[0][2] == 0, (
        f'the reattach no longer starts at the first event: {versuche[0]}'
    )
    # Adopted, not doubled: the row the service named carries the replay, and
    # no second placeholder stands beside it.
    assert not [z for z in bericht["liste"] if str(z["id"]).startswith("platzhalter-")], (
        f"the reattach puts a second bubble beside it: {bericht['liste']}"
    )
    zeile = [z for z in bericht["liste"] if z["id"] == "m2"]
    assert zeile and zeile[0]["content"] == "the answer once more", (
        f"the adopted row does not carry the replayed stream: {bericht['liste']}"
    )


# --- The shown list carries its own chat id -------------------------------
#
# Three overtaking opens, A -> B -> A, and the third fails. Its own
# guard already discards a fetch nobody is waiting for any more -- but a
# FAILED third open never fetches anything, so nothing there notices that
# the list still standing belongs to neither the chat it is about to name
# active again (B) nor, once it does, to anything actually on screen. The
# tag introduced for this is what the display compares
# against `aktiverChat`; this proves the tag itself never lies about it.


@P666_BRAUCHT_NODE
def test_a_failed_third_open_ends_on_the_start_page():
    """A -> B -> A, the third fetch failing while B's fetch is still held:
    no chat is selected and no row stands — neither A's from the first,
    successful open nor B's, whose fetch arrives afterwards and is dropped.
    The start page, as after "New chat"; the notice stays."""
    bericht = _p666_lauf(
        _p666_zustand(),
        """
    dienst = {
      A: { zeilen: [{ id: 'a-echt', role: 'user', content: 'a' }], laufend: null },
      B: { zeilen: [{ id: 'b-echt', role: 'user', content: 'b' }], laufend: null },
    }
    // A clean first open of A: it settles, and tags the list as its own.
    const firstA = chatOeffnen('A')
    await aufloesen()
    await firstA

    // B starts opening -- its fetch is queued but not yet answered --
    // and before it is, A is opened a third time. This one fails.
    const bOpen = chatOeffnen('B')
    globalThis.__naechsterFehlschlag = true
    const thirdA = chatOeffnen('A')
    await aufloesen()
    await bOpen
    await thirdA
    return {
      aktiverChat: zustand.aktiverChat,
      nachrichtenChatId: zustand.nachrichtenChatId,
      rows: zustand.nachrichten.map((n) => n.id),
    }
        """,
    )
    assert bericht["aktiverChat"] is None, f"a chat is still selected: {bericht}"
    assert bericht["rows"] == [], f"rows of another chat still stand: {bericht['rows']}"
    assert bericht["nachrichtenChatId"] is None, f"the list's own tag lies: {bericht}"
    assert ["melde", "fehler"] in bericht["protokoll"], "the notice is gone"


@P666_BRAUCHT_NODE
def test_a_failed_switch_from_an_open_chat_ends_on_the_start_page_with_the_model_from_before():
    """A is open, B is asked for and the service does not answer: the start
    page, no row of A under B's name, the model the reader had before the
    click (it is set for B when the click is made)."""
    bericht = _p666_lauf(
        _p666_zustand(),
        """
    zustand.modelle = [{ id: 'm-a' }, { id: 'm-b' }]
    zustand.chats = [{ id: 'A', endpoint_id: 'm-a' }, { id: 'B', endpoint_id: 'm-b' }]
    zustand.modellId = 'm-a'
    dienst = {
      A: { zeilen: [{ id: 'a-echt', role: 'user', content: 'a' }], laufend: null },
    }
    const firstA = chatOeffnen('A')
    await aufloesen()
    await firstA
    const rowsBefore = zustand.nachrichten.map((n) => n.id)

    globalThis.__naechsterFehlschlag = true
    const bOpen = chatOeffnen('B')
    await aufloesen()
    await bOpen
    return {
      rowsBefore,
      aktiverChat: zustand.aktiverChat,
      rows: zustand.nachrichten.map((n) => n.id),
      modellId: zustand.modellId,
    }
        """,
    )
    assert bericht["rowsBefore"] == ["a-echt"]
    assert bericht["aktiverChat"] is None
    assert bericht["rows"] == [], f"a row stands under no chat: {bericht['rows']}"
    assert bericht["modellId"] == "m-a", f"the model is not the one from before: {bericht}"
    assert ["melde", "fehler"] in bericht["protokoll"]


@P666_BRAUCHT_NODE
def test_a_failed_second_look_at_the_open_chat_leaves_chat_and_list_standing():
    """Silence probe: no switch, so nothing changes — the chat stays
    selected, its list keeps standing, the notice comes. And a successful
    open shows its list as before."""
    bericht = _p666_lauf(
        _p666_zustand(),
        """
    dienst = {
      A: { zeilen: [{ id: 'a-echt', role: 'user', content: 'a' }], laufend: null },
    }
    const firstA = chatOeffnen('A')
    await aufloesen()
    await firstA
    const opened = {
      aktiverChat: zustand.aktiverChat,
      rows: zustand.nachrichten.map((n) => n.id),
    }

    globalThis.__naechsterFehlschlag = true
    const again = chatOeffnen('A')
    await aufloesen()
    await again
    return {
      opened,
      aktiverChat: zustand.aktiverChat,
      rows: zustand.nachrichten.map((n) => n.id),
    }
        """,
    )
    assert bericht["opened"] == {"aktiverChat": "A", "rows": ["a-echt"]}
    assert bericht["aktiverChat"] == "A", f"the open chat was left: {bericht}"
    assert bericht["rows"] == ["a-echt"], f"the standing list changed: {bericht['rows']}"
    assert ["melde", "fehler"] in bericht["protokoll"]


# --- A second, still-unsaved question is not the first one again ---------
#
# `chatOeffnen`'s rescue for a send in flight used to fall back
# to matching by WORDING once the id came up empty -- so a second "hi" sent
# right after the first, whose own row the service had already saved under
# a different id, looked like a duplicate of that first one and never
# appeared until its own run had saved it too.


@P666_BRAUCHT_NODE
def test_eine_zweite_gleichlautende_frage_verschwindet_nicht():
    bericht = _p666_lauf(
        _p666_zustand(),
        """
    dienst = {
      A: { zeilen: [{ id: 'srv-1', role: 'user', content: 'hi' }], laufend: null },
    }
    zustand.aktiverChat = 'A'
    zustand.nachrichtenChatId = 'A'
    zustand.nachrichten = [
      { id: 'eigen-1', role: 'user', content: 'hi' },
      { id: 'eigen-2', role: 'user', content: 'hi' },
      { id: 'platzhalter-A', role: 'assistant', content: '' },
    ]
    zustand.sendet.A = true
    const wieder = chatOeffnen('A')
    await aufloesen()
    await wieder
    return { ids: zustand.nachrichten.map((n) => n.id) }
        """,
    )
    assert "eigen-1" in bericht["ids"] and "eigen-2" in bericht["ids"], (
        f"a second, still-unsaved question with the same wording as one "
        f"the service already saved vanished: {bericht['ids']}"
    )


# --- A reload mid-send does not double the very question just sent -------
#
# senden() (App.svelte) hands the service the same id its own bubble already
# carries. A reload landing in the gap between the push and the service
# answering used to compare the two rows by their raw id, which never
# matched -- the local `eigen-...` row and the service's own copy of it,
# freshly fetched under the bare id, stood side by side.


@P666_BRAUCHT_NODE
def test_die_eigene_frage_steht_nach_einem_neuladen_mitten_im_senden_nur_einmal():
    bericht = _p666_lauf(
        _p666_zustand(),
        """
    dienst = {
      A: { zeilen: [{ id: 'k1', role: 'user', content: 'hallo' }], laufend: null },
    }
    zustand.aktiverChat = 'A'
    zustand.nachrichtenChatId = 'A'
    zustand.nachrichten = [
      { id: 'eigen-k1', role: 'user', content: 'hallo' },
      { id: 'platzhalter-A', role: 'assistant', content: '' },
    ]
    zustand.sendet.A = true
    const wieder = chatOeffnen('A')
    await aufloesen()
    await wieder
    return { ids: zustand.nachrichten.map((n) => n.id) }
        """,
    )
    frage_zeilen = [i for i in bericht["ids"] if i == "k1" or i == "eigen-k1"]
    assert frage_zeilen == ["k1"], (
        f"the question the interface already sent under its own id stands "
        f"twice once the service's copy of the same row arrives: {bericht['ids']}"
    )


# --- A stale owed reattachment does not survive the next open ------------
#
# `chatOeffnen` clears `zustand.wiederanhaengen[id]` before it
# decides anything new about this open, then writes a fresh entry only if
# the fetch actually names a run still going. Nothing before this measured
# whether that clear ever has anything TO do -- the earlier stand-in for
# `antwortWiederAnhaengen` is not this branch at all (the shipped function
# never touches `wiederanhaengen` when called with `nachholen: false`, the
# only way that stretch calls it), so only `chatOeffnen` itself, run for
# real, can show it.


@P666_BRAUCHT_NODE
def test_ein_veralteter_wiederanhang_wird_beim_naechsten_oeffnen_geraeumt():
    """An entry from some earlier look, naming a run long since decided one
    way or the other. `aktiverChat = id` two lines below wakes the effect
    that spends it — synchronously, before the fetch has said whether
    anything is still going — so the clear has to land before that
    assignment, not merely by the time this open is done: cleared any
    later and the stale entry gets attached and replayed once regardless,
    same as leaving it standing to begin with."""
    bericht = _p666_lauf(
        _p666_zustand(),
        P666_AUFBAU
        + """
    zustand.wiederanhaengen.A = { chatId: 'A', generationId: 'alt', messageId: 'alt' }
    dienst.A = { zeilen: [{ id: 'a-neu', role: 'user', content: 'neu' }], laufend: null }
    const wieder = chatOeffnen('A')
    await aufloesen()
    await wieder
    return { offen: Object.keys(zustand.wiederanhaengen), protokoll }
        """,
    )
    assert "A" not in bericht["offen"], (
        f"a stale reattachment survived chatOeffnen's own clear: {bericht['offen']}"
    )
    wiederholt = [z for z in bericht["protokoll"] if z[0] == "zusehenStrom" and z[1] == "alt"]
    assert not wiederholt, (
        f"a generation the service no longer lists was replayed once more: "
        f"{bericht['protokoll']}"
    )


def test_das_fenster_hat_nur_die_leiste_links_und_keine_kopfleiste():
    """One way to find a place in the program, not three.

    The window used to carry a header band, a chat list on the left and a
    strip of signs on the right. The header is gone: the sidebar says the
    program's name and folds itself away, the windows sit in the sidebar's
    foot row, and the tools have the same anatomy on the right — their
    signs in the column's foot row, or its bar of signs when folded. The
    chat's head carries only the chat's name.

    Source-text guard: it catches the pieces, not what lands on screen.
    """
    app = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")
    seitenleiste = (WURZEL / "frontend/src/teile/Seitenleiste.svelte").read_text(encoding="utf-8")
    spalte = (WURZEL / "frontend/src/teile/Arbeitsleiste.svelte").read_text(encoding="utf-8")
    rand = (WURZEL / "frontend/src/teile/ToolSigns.svelte").read_text(encoding="utf-8")

    assert "kopfleiste" not in app, "the header band is back"
    marke = '<div class="chatkopf"'
    assert marke in app, "the chat has no head of its own"
    kopf = app.split(marke, 1)[1].split("</div>\n      <!--", 1)[0]
    assert "ToolSigns" not in kopf, "tool buttons stand in the chat's head again"
    assert "<button" not in kopf, "the chat's head carries a button again"
    assert "cliknopf" not in app, "the head's button for the CLI, or its style, is back"
    assert "ToolSigns" not in app, "the tool signs belong to the column"
    assert '<div class="fusszeile">\n      <ToolSigns />' in spalte, "the column lost its row"
    assert '<nav class="zeichenleiste">' in spalte, "the folded column lost its bar"
    assert "leiste.reiter" not in spalte, "the tabs are back"

    assert "<Wortmarke" in seitenleiste, "the sidebar lost the program's name"
    assert "t('seitenleiste.ausblenden')" in seitenleiste, "the folding button is gone"
    assert 'class="zeichenleiste"' in seitenleiste, "the folded icon bar is gone"
    assert 'class="fensterzeile"' in seitenleiste, "the window row is gone"
    # The windows open from the sidebar only; the tool row opens tools only.
    assert "menueFensterOeffnen" not in rand
    # The CLI is a tool of the column again — the terminal client in the
    # window, beside the terminal that logs the chat's tool calls.
    assert "'cli'" in rand and "'terminal'" in rand, "the CLI or the terminal left the tools"


def test_the_folders_live_only_in_the_bar_chip():
    """The folder chip in the input bar's row is the one place the folders
    are shown and changed: no pills in the chat's head, no entry in the plus
    menu, and the chip itself opens the mask that adds one."""
    eingabe = (WURZEL / "frontend/src/teile/Eingabeleiste.svelte").read_text(encoding="utf-8")
    chip = (WURZEL / "frontend/src/teile/FolderChip.svelte").read_text(encoding="utf-8")
    app = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")

    assert "<FolderChip" in eingabe, "the chip is gone from the bar"
    assert "Ordnerpillen" not in app, "the pills are back in the head"
    assert "maskeOeffnen" not in eingabe, "the plus menu adds folders again"
    assert "act(maskeOeffnen)" in chip, "the chip lost its way to add a folder"


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_frage_neu_senden_loescht_nur_die_antwort_auf_die_letzte_frage():
    """`letzteAntwort` skips reports and pictures, which is right for the
    arrow and wrong on its own for a button that DELETES: after a picture
    prompt and its picture, the last ordinary answer belongs to the
    question before them, and "send again" under the picture prompt would
    have deleted that older answer. The guard is the answer's position
    against the last question's, and it is executed here, not matched."""
    quelle = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")
    funktion = re.search(r"async function frageNeuSenden\(\) \{.*?\n  \}", quelle, re.S)
    assert funktion, "frageNeuSenden not found"
    assert "antwortAufLetzteFrage(zustand.nachrichten, letzte, letzteFrage)" in funktion.group(0), (
        "frageNeuSenden no longer asks whether the answer stands behind the last "
        "question"
    )
    helfer = re.search(
        r"function antwortAufLetzteFrage\(nachrichten, antwort, frage\) \{.*?\n  \}", quelle, re.S
    )
    assert helfer, "antwortAufLetzteFrage not found"

    frage1 = {"role": "user", "id": "q1"}
    antwort1 = {"role": "assistant", "id": "a1"}
    bildfrage = {"role": "user", "id": "p"}
    bild = {"role": "assistant", "id": "b", "art": "bild"}
    meldung = {"role": "assistant", "id": "w", "art": "werkzeugmeldung"}
    faelle = [
        # The picture window wrote a prompt and a picture after the answer:
        # the answer belongs to q1, the last question is p -- nothing is deleted.
        ("bild_nach_der_antwort", [frage1, antwort1, bildfrage, bild], "a1", "p", False),
        # A finished command reported after the answer: the answer still
        # belongs to the last question and may be replaced.
        ("meldung_nach_der_antwort", [frage1, antwort1, meldung], "a1", "q1", True),
        ("gewoehnlich", [frage1, antwort1], "a1", "q1", True),
        ("keine_antwort", [frage1], None, "q1", False),
        ("keine_frage", [antwort1], "a1", None, False),
    ]
    skript = helfer.group(0) + "\n" + "\n".join(
        f"{{ const zeilen = {json.dumps(zeilen)};"
        f"  const antwort = zeilen.find((n) => n.id === {json.dumps(antwort)}) ?? null;"
        f"  const frage = zeilen.find((n) => n.id === {json.dumps(frage)}) ?? null;"
        f"  if (antwortAufLetzteFrage(zeilen, antwort, frage) !== {str(erwartet).lower()})"
        f"  {{ console.error({json.dumps(name)}); process.exit(1) }} }}"
        for name, zeilen, antwort, frage, erwartet in faelle
    ) + "\nconsole.log('OK')"
    lauf = subprocess.run(
        ["node", "-e", skript], capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    assert lauf.returncode == 0, f"Case {lauf.stderr.strip()!r} fails -- {lauf.stdout}{lauf.stderr}"
    assert "OK" in lauf.stdout


def test_das_nachladen_am_laufende_ist_zeitlich_begrenzt():
    """The release of a run (`delete zustand.laeuft[...]`) stands BELOW the
    end-of-run reconcile, on purpose: the queue fires on the release and
    must not push a bubble the reconcile then overwrites. That makes the
    release wait on a fetch — and a fetch with no bound can wait forever: a
    dropped connection left the chat marked running for the whole session,
    input greyed, Stop offered for a run that was over, the queue never
    fired. So the reconcile carries a timeout, and `api.nachrichten` has to
    hand that signal on to the fetch.

    Source-text only: it catches the bound being dropped again, not every
    way the release could stall.
    """
    fenster = (WURZEL / "frontend/src/App.svelte").read_text(encoding="utf-8")
    nachladen = re.search(
        r"const frisch = await api\.nachrichten\(zielChat, \{[^}]*\}\)", fenster, re.S
    )
    assert nachladen, "the end-of-run reconcile no longer calls api.nachrichten with options"
    assert "AbortSignal.timeout(" in nachladen.group(0), (
        "the end-of-run reconcile has no bound any more -- a hanging fetch keeps the "
        "chat locked for the rest of the session"
    )
    schnittstelle = (WURZEL / "frontend/src/lib/api.js").read_text(encoding="utf-8")
    lesen = re.search(r"nachrichten: async \(id, \{[^}]*\} = \{\}\) => \{.*?\n  \},", schnittstelle, re.S)
    assert lesen, "api.nachrichten not found"
    assert "signal" in lesen.group(0) and "{ signal }" in lesen.group(0), (
        "api.nachrichten no longer hands the signal on to the fetch"
    )


def test_die_geometriewache_startet_nur_mit_diagnose_flagge():
    """The watch paints a report panel over the app and writes marker
    lines into the access log — a diagnosis tool for a test service. A
    shipped install must not run it: the start is gated on the flag the
    service injects beside the session key, and the config default is
    off."""
    haupt = (WURZEL / "frontend/src/main.js").read_text(encoding="utf-8")
    assert "if (window.__DIAGNOSE__) geometriewacheStarten()" in haupt, (
        "the guard starts unconditionally again"
    )
    einbettung = (WURZEL / "app/main.py").read_text(encoding="utf-8")
    assert "window.__DIAGNOSE__" in einbettung, "the flag no longer travels into the page"
    # The default itself, measured rather than read: a renamed field with a
    # flipped default would pass a string test and ship the watch.
    from app.config import Config

    assert Config.model_validate({"app": {"data_dir": "/tmp/x"}}).app.diagnose is False


def test_die_seite_traegt_die_diagnoseflagge_des_dienstes(client):
    """What the service injects beside the session key is the config's
    value — off unless somebody switched it on for a test service."""
    seite = client.get("/app/").text
    assert "window.__DIAGNOSE__=false" in seite
    client.app.state.config.app.diagnose = True
    assert "window.__DIAGNOSE__=true" in client.get("/app/").text


@p662_braucht_node
def test_die_warteschlange_geht_weiter_wenn_die_sendemarke_faellt():
    """`senden` holds its chat's send mark until `antwortHolen` has returned
    — which is AFTER that run's own end has released `laeuft` and woken the
    queue effect once, into a chat still marked as sending. The mark's
    release has to wake it again, or a message queued during an ordinary
    answer stays in the queue until the next chat switch."""
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    zustand.sendet.A = true
    await laufEnde({
      zielChat: 'A', abgebrochen: false, gescheitert: false,
      platzhalter: p1, verdichtetZu: null,
    })
    await new Promise((frei) => setTimeout(frei, 5))
    const waehrend = protokoll.filter((e) => e === 'senden').length
    delete zustand.sendet.A
    flushSync()
    await new Promise((frei) => setTimeout(frei, 5))
    return { waehrend, danach: protokoll.filter((e) => e === 'senden').length, wartet: fuerChat('A').length }
        """,
    )
    assert bericht["waehrend"] == 0, "the queue sent while the send mark still stood"
    assert bericht["danach"] == 1, f"the queue did not move when the send mark fell: {bericht}"
    assert bericht["wartet"] == 0


def test_jedes_modul_unter_api_v1_haengt_an_einem_router():
    """A module under app/api/v1/ that nothing registers is a door with no
    corridor behind it.

    One of them sat there for a fortnight: `waechter.py` kept two routes for
    a panel that had been deleted, and the only way to notice was to read the
    import list and the folder side by side. A reader looking for the route
    that serves a screen finds it and believes it; a tool counting the API's
    surface counts it. Both are wrong, and neither says so.

    Registered means BOTH halves of app/api/v1/__init__.py: the module is
    imported AND its router is included. Importing alone is not enough — an
    imported module whose router nobody includes is exactly the same door
    with nothing behind it, and it would read as wired up to anyone skimming
    the import list.

    ``schemas`` is the one module here that is not a router and never will
    be. Another helper put in this folder fails this test, and that is the
    answer rather than the problem: a module beside the routers either is
    one or belongs somewhere else.
    """
    ordner = WURZEL / "app" / "api" / "v1"
    module = {
        pfad.stem
        for pfad in ordner.glob("*.py")
        if pfad.stem not in {"__init__", "schemas"}
    }
    # Commented-out lines dropped first. A wiring somebody switched off with
    # a '#' and meant to come back to is the very state this test is for —
    # left standing, it would read as registered and keep the orphan green.
    register = "\n".join(
        zeile
        for zeile in (ordner / "__init__.py").read_text(encoding="utf-8").splitlines()
        if not zeile.lstrip().startswith("#")
    )
    # Both halves, matched on the spelling this file actually uses: one name
    # per line in the import block, one plain include per router. A different
    # spelling turns the test red rather than silent, which is the safe way
    # round for a guard.
    importiert = set(re.findall(r"^\s{4}(\w+),$", register, re.MULTILINE))
    eingehaengt = set(re.findall(r"include_router\((\w+)\.router\)", register))

    verwaist = sorted(module - (importiert & eingehaengt))
    assert not verwaist, (
        "modules under app/api/v1/ that no router registers: "
        f"{verwaist} — wire them up or delete them"
    )


# --- A refused send, and the stop before the start -------------------------
#
# Three stretches of the window, each lifted out of its component and run in
# node with everything around it stubbed: what a refused send gives back
# (frontend/src/teile/Eingabeleiste.svelte), which handles the stop button
# sends (App.svelte), and where a send whose line broke before the stream's
# `start` goes looking for its answer (App.svelte, `nachholen`).

EINGABELEISTE = WURZEL / "frontend/src/teile/Eingabeleiste.svelte"
APP = WURZEL / "frontend/src/App.svelte"


def _stueck(datei: Path, muster: str, name: str) -> str:
    treffer = re.search(muster, datei.read_text(encoding="utf-8"), re.S)
    assert treffer, f"{name} not found"
    return treffer.group(0).replace("export ", "")


def _node(skript: str) -> dict:
    lauf = subprocess.run(
        ["node", "--input-type=module", "-e", skript],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert lauf.returncode == 0, f"{lauf.stderr}\n{lauf.stdout}"
    return json.loads(lauf.stdout.strip().splitlines()[-1])


def _thinking_stage_shown(denken: dict, entry: dict | None, model_id: str = "m1"):
    """The stage the switch shows, evaluated as the bar really writes it."""
    stueck = _stueck(
        EINGABELEISTE, r"\n  const denkStufe = \$derived\(.*?\n  \)\n", "denkStufe"
    ).strip()
    expression = stueck.replace("const denkStufe = $derived(", "", 1).removesuffix(")").strip()
    stueck = f"const denkStufe = {expression.removesuffix(',')}"
    return _node(f"""
const zustand = {{ modellId: {json.dumps(model_id)} }}
const denken = {json.dumps(denken)}
const modellEintrag = {json.dumps(entry)}
const denkprofil = modellEintrag?.denkprofil ?? null
{stueck}
console.log(JSON.stringify(denkStufe))
""")


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_the_switch_shows_the_stage_the_service_sends_for_a_dropped_one():
    """Stored `xhigh`, offered low/medium/high with `medium` as the default:
    the service sends `high`, so the switch shows `high` — the list carries
    it and the window works nothing out."""
    entry = {
        "denkprofil": {"stufen": ["low", "medium", "high"], "standard": "medium"},
        "thinking_sent": "high",
    }
    assert _thinking_stage_shown({"modell": "m1", "stufe": "xhigh", "picked": False}, entry) == "high"
    # Before the stored stage has been read, the list's word stands already.
    assert _thinking_stage_shown({"modell": None, "stufe": None, "picked": False}, entry) == "high"


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_the_switch_keeps_a_stage_the_model_still_offers_and_a_hand_pick():
    """Silence probe: a stored or picked stage that is offered is shown as it
    was, and a list without the word falls back to the default."""
    entry = {
        "denkprofil": {"stufen": ["low", "medium", "high"], "standard": "medium"},
        "thinking_sent": "high",
    }
    assert _thinking_stage_shown({"modell": "m1", "stufe": "low", "picked": False}, entry) == "low"
    assert _thinking_stage_shown({"modell": "m1", "stufe": "low", "picked": True}, entry) == "low"
    # Another model's stored stage never applies here.
    assert _thinking_stage_shown({"modell": "m2", "stufe": "low", "picked": False}, entry) == "high"
    # An older service that does not carry the word: the default, as before.
    older = {"denkprofil": entry["denkprofil"]}
    assert _thinking_stage_shown({"modell": "m1", "stufe": "xhigh", "picked": False}, older) == "medium"
    assert _thinking_stage_shown({"modell": None, "stufe": None, "picked": False}, None) is None


def _leiste(fall: str) -> dict:
    """The bar with `zurueckgeben` and `anhangSetzen` as they really stand."""
    zurueckgeben = _stueck(
        EINGABELEISTE,
        r"\n  export function zurueckgeben\(inhalt, chat = entwurfChat, messageId = null\) \{.*?\n  \}\n",
        "zurueckgeben",
    )
    anhang_setzen = _stueck(
        EINGABELEISTE, r"\n  function anhangSetzen\(datei\) \{.*?\n  \}\n", "anhangSetzen",
    )
    # The bar's own caps, lifted with the stretch that reads them: a driver
    # must never run on a made-up number.
    grenzen = "\n".join(
        re.findall(r"  const (?:MAX_BILDER|MAX_DOKUMENTE) = \d+", EINGABELEISTE.read_text(encoding="utf-8"))
    )
    assert "MAX_BILDER" in grenzen and "MAX_DOKUMENTE" in grenzen, "the limits were not found"
    skript = f"""
const gemeldet = []
const meldeText = (schluessel, werte, art) => gemeldet.push([schluessel, werte, art])
const melde = (text, art) => gemeldet.push([text, art])
const t = (schluessel) => schluessel
const BILD_TYPEN = ['image/png', 'image/jpeg', 'image/webp']
{grenzen}
const visionFaehig = true
const URL = {{ createObjectURL: (datei) => 'blob:' + datei.name, revokeObjectURL: () => {{}} }}
const LEERER_ENTWURF = {{ text: '', anhaenge: [], dokumentAnhaenge: [] }}
const datei = (name, typ = 'image/png') => ({{ name, type: typ }})
let text = ''
let anhaenge = []
let dokumentAnhaenge = []
const zurueckbehalten = new Map()
const entwuerfe = new Map()
let entwurfChat = 'A'
{zurueckgeben}
{anhang_setzen}
const stand = () => ({{
  text,
  bilder: anhaenge.map((a) => a.datei.name),
  dokumente: dokumentAnhaenge.map((d) => d.id),
  entwuerfe: [...entwuerfe].map(([k, v]) => [k, v.text, v.anhaenge.map((a) => a.datei.name), v.dokumentAnhaenge.map((d) => d.id)]),
  zurueckbehalten: [...zurueckbehalten.keys()],
  gemeldet,
}})
{fall}
console.log(JSON.stringify(stand()))
"""
    return _node(skript)


BEHALTEN = (
    "{ bilder: [{ datei: datei('rot.png') }, { datei: datei('blau.png') }], "
    "dokumente: [{ id: 'dok-1', datei: datei('plan.pdf'), dokument: { id: 'gespeichert-1' } }] }"
)


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_eine_abgelehnte_abgabe_ohne_text_gibt_die_anhaenge_zurueck():
    """The service refused the send because its chat was taken: two pictures
    and a document go back into the bar — with no word sent, which used to
    get nothing back at all."""
    stand = _leiste(f"zurueckbehalten.set('k1', {BEHALTEN})\nzurueckgeben('', 'A', 'k1')")
    assert stand["text"] == ""
    assert stand["bilder"] == ["rot.png", "blau.png"]
    assert stand["dokumente"] == ["dok-1"]
    assert stand["zurueckbehalten"] == [], "they came back and still sit in the keeper"


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_die_zurueckgegebenen_anhaenge_stehen_zusaetzlich_da():
    """Beside what is already picked, not instead of it — and the words only
    into an empty field."""
    stand = _leiste(
        "anhaenge = [datei('schon.png')].map((d) => ({ datei: d, url: 'blob:schon' }))\n"
        "text = 'schon getippt'\n"
        f"zurueckbehalten.set('k1', {BEHALTEN})\n"
        "zurueckgeben('verlorene worte', 'A', 'k1')"
    )
    assert stand["bilder"] == ["schon.png", "rot.png", "blau.png"]
    assert stand["text"] == "schon getippt", "the words overwrote what was typed"
    # Only words, empty field: they come back as they always did.
    leer = _leiste("zurueckgeben('nur worte', 'A', 'k1')")
    assert leer["text"] == "nur worte"
    assert leer["bilder"] == [] and leer["dokumente"] == []


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_nach_einem_chatwechsel_kommen_sie_in_den_entwurf():
    """After a switch they belong to the chat they were sent in and wait in
    its draft, beside whatever that draft already holds."""
    stand = _leiste(
        "entwuerfe.set('B', { text: '', anhaenge: [], dokumentAnhaenge: [] })\n"
        f"zurueckbehalten.set('k1', {BEHALTEN})\n"
        "zurueckgeben('hallo', 'B', 'k1')"
    )
    assert stand["text"] == "", "the switch wrote the words into the bar"
    assert stand["entwuerfe"] == [["B", "hallo", ["rot.png", "blau.png"], ["dok-1"]]]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_a_second_send_in_another_chat_does_not_replace_the_first_ones_attachments():
    """Two sends one after the other, in chat A and then in chat B; the first
    is refused. What comes back is the first send's own attachments — the
    second one, still under way, keeps its entry."""
    stand = _leiste(
        f"zurueckbehalten.set('k1', {BEHALTEN})\n"
        "zurueckbehalten.set('k2', { bilder: [{ datei: datei('green.png') }], dokumente: [] })\n"
        "zurueckgeben('', 'A', 'k1')"
    )
    assert stand["bilder"] == ["rot.png", "blau.png"]
    assert stand["dokumente"] == ["dok-1"]
    assert stand["zurueckbehalten"] == ["k2"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_a_send_the_bar_did_not_make_gets_its_words_back_only():
    """Silence probe: a queued message has no entry in the bar — its words
    come back, and another send's attachments stay where they are."""
    stand = _leiste(
        f"zurueckbehalten.set('k1', {BEHALTEN})\n"
        "zurueckgeben('from the queue', 'A', 'q9')"
    )
    assert stand["text"] == "from the queue"
    assert stand["bilder"] == [] and stand["dokumente"] == []
    assert stand["zurueckbehalten"] == ["k1"]


def test_the_bar_hands_its_message_id_to_the_send_and_drops_it_after():
    """The id the bar keeps the attachments under is the one the message
    goes out with — the refusal names that id — and the entry goes once the
    send is over."""
    leiste = EINGABELEISTE.read_text(encoding="utf-8")
    assert "const release = keep(messageId, kept)" in leiste
    assert "senden(auftrag.inhalt, bilder, dokumente, auftrag.denken, skill, false, messageId)" in leiste
    assert ".finally(release)" in leiste
    app = APP.read_text(encoding="utf-8")
    assert "gespraech = false,\n    messageId = null, kept = null, ausReihe = null,\n  ) {" in app
    assert "const sendId = messageId ?? Math.random().toString(36).slice(2, 9)" in app
    assert "const frageKennung = sendId" in app


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_die_grenze_bleibt_fuer_das_was_der_nutzer_anhaengt():
    """Silence probe: six pictures are the bar's limit for a hand picking
    one, and the seventh is still turned away — the way back past that limit
    is for what a refused send carried, not for the hand."""
    stand = _leiste(
        "anhaenge = ['a', 'b', 'c', 'd', 'e', 'f'].map((n) => ({ datei: datei(n + '.png'), url: 'blob:' + n }))\n"
        "anhangSetzen(datei('siebtes.png'))"
    )
    assert stand["bilder"] == ["a.png", "b.png", "c.png", "d.png", "e.png", "f.png"]
    assert stand["gemeldet"] == [["eingabe.bilder_voll", {"anzahl": 6}, "hinweis"]]


def _abbrechen(lauf_js: str) -> list:
    """The stop button's own function, with the service call recorded."""
    return [e[1:] for e in _stop_events(lauf_js, [0], ends_after=1) if e[0] == "stop"]


def _stop_events(
    lauf_js: str, counts: list, ends_after: int | None = None, presses: int = 1
) -> list:
    """The stop button's own two functions, with every service call and the
    local cut of the send recorded in the order they happen.

    ``counts`` is what the service answers to the stops, one after the
    other (the last one repeats); ``ends_after`` ends the send — the chat has
    no run any more — once that many stops have gone out."""
    funktionen = _stueck(
        APP,
        r"\n  async function stoppWiederholen\(lauf\) \{.*?\n  \}\n"
        r".*?\n  async function abbrechen\(\) \{.*?\n  \}\n",
        "abbrechen",
    )
    skript = f"""
const ereignisse = []
const antworten = {json.dumps(counts)}
const endetNach = {json.dumps(ends_after)}
let gestoppt = 0
let laeuft = true
const lauf = ({lauf_js})
lauf.abbruch = {{
  signal: {{ aborted: false }},
  abort() {{ this.signal.aborted = true; ereignisse.push(['abort']) }},
}}
const api = {{
  abbrechen: async (generationId, chatId) => {{
    ereignisse.push(['stop', generationId, chatId])
    const antwort = antworten[Math.min(gestoppt, antworten.length - 1)]
    gestoppt += 1
    if (endetNach !== null && gestoppt >= endetNach) laeuft = false
    return {{ abgebrochen: antwort }}
  }},
}}
const HALTEPRUEFUNG_MS = 1
const laufVon = () => (laeuft ? lauf : null)
const anspruchWarten = new Map()
const compactSince = {{}}
const anhalten = () => {{ throw new Error('the queue is not held by a stop of a run') }}
const zustand = {{ aktiverChat: 'A' }}
{funktionen}
for (let i = 0; i < {presses}; i += 1) await abbrechen()
// Until the send is cut (a loaded machine is slow, not wrong), then a moment
// longer so a stop that should not exist has time to show up.
for (let i = 0; i < 400 && !ereignisse.some((e) => e[0] === 'abort'); i += 1) {{
  await new Promise((frei) => setTimeout(frei, 5))
}}
await new Promise((frei) => setTimeout(frei, 30))
console.log(JSON.stringify(ereignisse))
"""
    lauf = subprocess.run(
        ["node", "--input-type=module", "-e", skript],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert lauf.returncode == 0, f"{lauf.stderr}\n{lauf.stdout}"
    return json.loads(lauf.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_der_stopp_geht_mit_beiden_kennungen_hinaus():
    """Before the stream's `start` the window has no run id — the chat id is
    all it has, and the service needs it to reach the claim it took. Sent
    with the run's id alone, the press reached nothing."""
    assert _abbrechen("{ generationId: 'g1', chatId: 'A' }") == [["g1", "A"]]
    assert _abbrechen("{ generationId: null, chatId: 'A' }") == [[None, "A"]]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ohne_lauf_wird_gar_nicht_gestoppt():
    """Silence probe: nothing running in this chat, nothing to stop."""
    skript = """
const api = { abbrechen: async () => { throw new Error('no stop expected') } }
const laufVon = () => null
const anspruchWarten = new Map()
const compactSince = {}
const anhalten = () => { throw new Error('nothing to hold') }
const zustand = { aktiverChat: 'A' }
const HALTEPRUEFUNG_MS = 1
FUNKTIONEN
await abbrechen()
console.log(JSON.stringify([]))
""".replace(
        "FUNKTIONEN",
        _stueck(
            APP,
            r"\n  async function stoppWiederholen\(lauf\) \{.*?\n  \}\n"
            r".*?\n  async function abbrechen\(\) \{.*?\n  \}\n",
            "abbrechen",
        ),
    )
    assert _node(skript) == []


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_stop_that_arrives_before_the_claim_is_repeated_until_it_lands():
    """The service counts 0, 0, 1: three stops go out, and the send is cut
    only after the third (without the repetition: one stop, the cut at once,
    and the answer begins a moment later)."""
    events = _stop_events("{ generationId: null, chatId: 'A' }", [0, 0, 1])
    assert events == [["stop", None, "A"]] * 3 + [["abort"]]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_stop_that_counts_zero_ends_with_the_send_without_another_stop():
    events = _stop_events("{ generationId: null, chatId: 'A' }", [0], ends_after=1)
    assert [e[0] for e in events] == ["stop", "abort"]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_stop_that_lands_at_once_is_sent_once_and_cuts_the_send():
    """Silence probe: no second stop where the first one hit."""
    events = _stop_events("{ generationId: null, chatId: 'A' }", [1])
    assert events == [["stop", None, "A"], ["abort"]]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_named_run_is_cut_and_stopped_once_as_before():
    """Silence probe: with the run's id one stop goes out and the cut comes
    at once, whatever the count."""
    events = _stop_events("{ generationId: 'g1', chatId: 'A' }", [0])
    assert events[0] == ["abort"]
    assert [e for e in events if e[0] == "stop"] == [["stop", "g1", "A"]]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_second_press_starts_no_second_repetition():
    events = _stop_events("{ generationId: null, chatId: 'A' }", [0, 0, 1], presses=2)
    assert events == [["stop", None, "A"]] * 3 + [["abort"]]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_the_repetition_names_the_run_once_the_stream_has():
    """The run is named while the stops count 0: the next one carries its id."""
    events = _stop_events(
        "(() => { const l = { generationId: null, chatId: 'A' }; "
        "setTimeout(() => { l.generationId = 'g7' }, 0); return l })()",
        [0, 0, 1],
    )
    ids = [e[1] for e in events if e[0] == "stop"]
    assert ids[0] is None and ids[-1] == "g7"
    assert events[-1] == ["abort"]


_WITH_DEADLINE = (
    r"\n    /\* A question about the run, bounded.*?\n    function withDeadline\(signal\) \{.*?\n    \}\n"
    r".*?\n    function pauseOrStop\(ms, signal\) \{.*?\n    \}\n"
    r".*?\n    async function claimOutcome\(chatId, signal\) \{.*?\n    \}\n"
)


def _nachholen(
    antworten: list, own_question: str | None = None, redo: dict | None = None
) -> dict:
    """Where a send whose line broke before `start` looks for its answer.

    `antworten` are the service's answers, one per question (`null` = no
    answer at all); `own_question` is the id this send gave its question;
    `redo` is the regeneration this send is for (`{"replaces": id}`)."""
    stueck = _stueck(
        APP,
        r"\n    async function nachholen\(laufJetzt, chatId, signal\) \{.*?\n    \}\n",
        "nachholen",
    )
    eigene = _stueck(
        APP,
        r"\n    async function antwortetAufEigene\(chatId, antwortId, signal\) \{.*?\n    \}\n",
        "antwortetAufEigene",
    )
    deadline = _stueck(APP, _WITH_DEADLINE, "withDeadline")
    skript = f"""
const HALTEPRUEFUNG_MS = 1
const NACHLADE_FRIST_MS = 60_000
const nachrichtId = {json.dumps(own_question)}
const redo = {json.dumps(redo)}
let zeileNachladen = false
const gefragt = []
const folge = {json.dumps(antworten)}
const api = {{
  nachrichten: async (chatId, optionen) => {{
    gefragt.push(optionen.limit ?? 'alle')
    const naechste = folge.shift()
    if (naechste === null) throw new Error('keine Verbindung')
    return naechste
  }},
}}
{deadline}
{eigene}
{stueck}
const lauf = {{ generationId: null }}
const gefunden = await nachholen(lauf, 'A', undefined)
console.log(JSON.stringify({{ gefunden, generationId: lauf.generationId, gefragt, zeileNachladen }}))
"""
    return _node(skript)


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ein_abgerissener_versand_haengt_sich_an_den_lauf_den_der_dienst_nennt():
    """The line broke before `start`; the service names the run, and the
    caller watches it from the first event. Before, this was declared a
    failed send while the answer ran."""
    stand = _nachholen([
        {"laufend": None, "gehalten": True},
        {"laufend": {"generation_id": "g9", "message_id": "m9"}, "gehalten": False},
    ])
    assert stand["gefunden"] == "run"
    assert stand["generationId"] == "g9"
    assert stand["gefragt"] == [1, 1], "the held chat was not asked again"


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ein_freigegebener_chat_beendet_das_warten():
    """Partial failure: the service lets go of the chat without a run, and
    the stored history does not hold this send's question — then the send
    really is over, and the wait has to end by itself."""
    stand = _nachholen(
        [{"laufend": None, "gehalten": True}, {"laufend": None, "gehalten": False},
         {"nachrichten": [{"id": "fremd", "role": "user"}]}],
        own_question="q1",
    )
    assert stand["gefunden"] is False
    assert stand["zeileNachladen"] is False
    assert stand["gefragt"] == [1, 1, 50]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_eine_verlorene_verbindung_beendet_das_warten():
    """A service that stops answering cannot be waited for either."""
    stand = _nachholen([{"laufend": None, "gehalten": True}, None], own_question="q1")
    assert stand["gefunden"] is False
    assert stand["gefragt"] == [1, 1]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_das_warten_haengt_sofort_an_wenn_der_lauf_schon_da_ist():
    """Silence probe: the ordinary case — the service names the run on the
    first question, nothing is waited for."""
    stand = _nachholen([{"laufend": {"generation_id": "g1", "message_id": None}, "gehalten": False}])
    assert stand["gefunden"] == "run"
    assert stand["gefragt"] == [1]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_run_that_began_and_ended_between_two_questions_is_no_failure():
    """Held, then neither run nor claim: the run began and ended inside one
    tick. The stored history holds this send's question — the answer is
    there, the stored row is fetched, and the send is not drawn as failed."""
    stand = _nachholen(
        [{"laufend": None, "gehalten": True}, {"laufend": None, "gehalten": False},
         {"nachrichten": [{"id": "q0", "role": "user"}, {"id": "q1", "role": "user"},
                          {"id": "a1", "role": "assistant", "art": "nachricht",
                           "zustand": "fertig"}]}],
        own_question="q1",
    )
    assert stand["gefunden"] == "stored"
    assert stand["zeileNachladen"] is True
    assert stand["gefragt"] == [1, 1, 50]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_send_whose_question_never_arrived_is_a_failed_send():
    """Partial failure: neither run nor claim, and the stored history does
    not hold this send's question — it never arrived, and it is drawn as
    failed."""
    stand = _nachholen(
        [{"laufend": None, "gehalten": False},
         {"nachrichten": [{"id": "a0", "role": "assistant", "art": "nachricht",
                           "zustand": "fertig"}]}],
        own_question="q1",
    )
    assert stand["gefunden"] is False
    assert stand["zeileNachladen"] is False


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_without_its_own_question_id_a_send_is_not_looked_up():
    """Silence probe: a send that named no question (a regeneration) has
    nothing to look for in the history — it ends as before."""
    stand = _nachholen([{"laufend": None, "gehalten": False}])
    assert stand["gefunden"] is False
    assert stand["gefragt"] == [1]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_regeneration_whose_run_ended_between_two_questions_is_stored_not_failed():
    """Held, then neither run nor claim, and the replaced answer is gone from
    the newest rows with a new answer standing last: the service stored the
    new one in the step that took the old one away. No red notice, the
    queue goes on, the stored list is fetched."""
    stand = _nachholen(
        [{"laufend": None, "gehalten": True}, {"laufend": None, "gehalten": False},
         {"nachrichten": [{"id": "q0", "role": "user"},
                          {"id": "a2", "role": "assistant", "art": "nachricht",
                           "zustand": "fertig"}]}],
        redo={"replaces": "a1"},
    )
    assert stand["gefunden"] == "stored"
    assert stand["zeileNachladen"] is True
    assert stand["gefragt"] == [1, 1, 50]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_regeneration_whose_replaced_answer_still_stands_is_a_failed_send():
    """Silence probe: nothing was written, the old answer is still there."""
    stand = _nachholen(
        [{"laufend": None, "gehalten": False},
         {"nachrichten": [{"id": "q0", "role": "user"},
                          {"id": "a1", "role": "assistant", "art": "nachricht",
                           "zustand": "fertig"}]}],
        redo={"replaces": "a1"},
    )
    assert stand["gefunden"] is False
    assert stand["zeileNachladen"] is False


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_regeneration_concludes_nothing_where_the_service_does_not_answer():
    """Silence probe: no answer at all, or no row at all — nothing is
    concluded."""
    stand = _nachholen(
        [{"laufend": None, "gehalten": False}, None], redo={"replaces": "a1"}
    )
    assert stand["gefunden"] is False
    assert stand["zeileNachladen"] is False
    stand = _nachholen(
        [{"laufend": None, "gehalten": False}, {"nachrichten": []}], redo={"replaces": "a1"}
    )
    assert stand["gefunden"] is False


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_run_that_answers_another_question_is_not_attached_to():
    """The service names a run for the chat, but its row stands behind a
    question of another window: its answer would stream into this bubble.
    The send ends as a failed one, the queue holds, and nothing is attached."""
    stand = _nachholen(
        [{"laufend": {"generation_id": "g2", "message_id": "a2"}, "gehalten": False},
         {"nachrichten": [{"id": "q1", "role": "user"}, {"id": "q2", "role": "user"},
                          {"id": "a2", "role": "assistant", "art": "nachricht",
                           "zustand": "laeuft"}]}],
        own_question="q1",
    )
    assert stand["gefunden"] is False
    assert stand["generationId"] is None
    assert stand["gefragt"] == [1, 50]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_run_that_answers_the_own_question_is_attached_to():
    """Silence probe: the row stands directly behind the own question, or
    behind it with a tool report between (no other question)."""
    for between in ([], [{"id": "t1", "role": "assistant", "art": "werkzeugmeldung"}]):
        stand = _nachholen(
            [{"laufend": {"generation_id": "g1", "message_id": "a1"}, "gehalten": False},
             {"nachrichten": [{"id": "q0", "role": "user"}, {"id": "q1", "role": "user"}, *between,
                              {"id": "a1", "role": "assistant", "art": "nachricht",
                               "zustand": "laeuft"}]}],
            own_question="q1",
        )
        assert stand["gefunden"] == "run"
        assert stand["generationId"] == "g1"


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_run_is_attached_to_where_it_cannot_be_compared():
    """Silence probe: no row named, a row not among the newest, a list that
    cannot be read — nothing says it is a foreign one, and it stays attached
    as it did."""
    named = {"laufend": {"generation_id": "g1", "message_id": "a1"}, "gehalten": False}
    assert _nachholen([{**named, "laufend": {"generation_id": "g1", "message_id": None}}],
                      own_question="q1")["gefunden"] == "run"
    assert _nachholen([named, {"nachrichten": [{"id": "q1", "role": "user"}]}],
                      own_question="q1")["gefunden"] == "run"
    assert _nachholen([named, None], own_question="q1")["gefunden"] == "run"


def _catch_up_and_watch(antworten: list, breaks: int, own_question: str | None = None) -> dict:
    """The catch's whole way for a line broken before `start`: `nachholen`
    finds the run, and the caller watches it through `weiterZusehen` — the
    same retry as any other line that breaks mid-answer. The stream gives
    one event and then breaks `breaks` times before it carries on."""
    nachholen = _stueck(
        APP,
        r"\n    async function nachholen\(laufJetzt, chatId, signal\) \{.*?\n    \}\n",
        "nachholen",
    )
    eigene = _stueck(
        APP,
        r"\n    async function antwortetAufEigene\(chatId, antwortId, signal\) \{.*?\n    \}\n",
        "antwortetAufEigene",
    )
    deadline = _stueck(APP, _WITH_DEADLINE, "withDeadline")
    weiter = _stueck(
        APP,
        r"\n      async function weiterZusehen\(laufJetzt, chatId, signal\) \{.*?\n      \}\n",
        "weiterZusehen",
    )
    limits = "\n".join(
        re.findall(r"  const WIEDERANHANG_PAUSE(?:_MAX)?_MS = [0-9_]+", APP.read_text(encoding="utf-8"))
    )
    call = re.search(
        r"const found = await nachholen\(lauf, zielChat, abbruch\.signal\)\n.*?\n          return\n",
        APP.read_text(encoding="utf-8"), re.S,
    )
    assert call, "the call of nachholen in the catch"
    skript = f"""
const HALTEPRUEFUNG_MS = 1
const NACHLADE_FRIST_MS = 60_000
{limits}
const nachrichtId = {json.dumps(own_question)}
const redo = null
let zeileNachladen = false
const protokoll = []
let offen = {breaks}
const folge = {json.dumps(antworten)}
async function* zusehenStrom(id, ab) {{
  protokoll.push(['strom', id, ab])
  if (ab === 0) yield {{ typ: 'content', text: 'eins' }}
  if (offen > 0) {{ offen -= 1; throw new Error('gerissen') }}
  yield {{ typ: 'content', text: 'zwei' }}
}}
const api = {{
  nachrichten: async () => {{
    const naechste = folge.shift()
    if (naechste === null || naechste === undefined) throw new Error('keine Verbindung')
    return naechste
  }},
}}
let ereignisZahl = 7
const ereignisVerarbeiten = async (strom) => {{
  for await (const e of strom) {{ ereignisZahl++; protokoll.push(['ereignis', e.text]) }}
}}
globalThis.setTimeout = ((echt) => (f, ms) => echt(f, 0))(globalThis.setTimeout)
{deadline}
{eigene}
{nachholen}
{weiter}
const lauf = {{ generationId: null }}
const zielChat = 'A'
const abbruch = {{ signal: undefined }}
const fehler = new Error('broken before start')
async function handleBreak() {{
  {call.group(0)}
}}
await handleBreak().catch((f) => protokoll.push(['fehler', String(f)]))
console.log(JSON.stringify({{ protokoll, zeileNachladen }}))
"""
    return _node(skript)


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_late_found_run_whose_line_breaks_is_watched_again():
    """Found by asking after a break before `start`, the run's own stream
    breaks once more: a second stream with the counter, not a red failure."""
    stand = _catch_up_and_watch(
        [{"laufend": {"generation_id": "g9"}, "gehalten": False},
         {"laufend": {"generation_id": "g9"}, "gehalten": False}],
        breaks=1,
    )
    streams = [z for z in stand["protokoll"] if z[0] == "strom"]
    assert streams == [["strom", "g9", 0], ["strom", "g9", 1]], stand["protokoll"]
    assert ["ereignis", "zwei"] in stand["protokoll"]
    assert not [z for z in stand["protokoll"] if z[0] == "fehler"], stand["protokoll"]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_late_found_run_that_holds_watches_once():
    """Silence probe: the found run's stream does not break — one stream,
    from the first event, and nothing else."""
    stand = _catch_up_and_watch(
        [{"laufend": {"generation_id": "g9"}, "gehalten": False}], breaks=0
    )
    assert [z for z in stand["protokoll"] if z[0] == "strom"] == [["strom", "g9", 0]]
    assert ["ereignis", "zwei"] in stand["protokoll"]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_stored_answer_ends_the_catch_without_a_failure_or_a_stream():
    """Through the catch: the run began and ended between two questions,
    the history holds the question and its answer — no stream is opened,
    nothing is thrown, and the stored row is fetched."""
    stand = _catch_up_and_watch(
        [{"laufend": None, "gehalten": False},
         {"nachrichten": [{"id": "q1", "role": "user"},
                          {"id": "a1", "role": "assistant", "art": "nachricht",
                           "zustand": "fertig"}]}],
        breaks=0, own_question="q1",
    )
    assert not [z for z in stand["protokoll"] if z[0] in ("strom", "fehler")], stand["protokoll"]
    assert stand["zeileNachladen"] is True


# --- The reattach, and the end of the stream -------------------------------
#
# `weiterZusehen` out of App.svelte, driven with a stubbed service and a
# stubbed stream: what the window does after a line broke a second time —
# come back, and how long it waits in between.

def _weiter_zusehen(
    fehlschlaege: int, antworten: list, refused_status: int | None = None,
    hangs: bool = False, stop_after_ms: int | None = None,
    carries: int = 0, real_pauses: bool = False,
) -> dict:
    """Runs the real `weiterZusehen` with a service that answers `antworten`
    (one entry per question, `null` = no answer at all) and a stream that
    breaks `fehlschlaege` times before it opens — or, with `refused_status`,
    is refused with that status after them. With `hangs` every question hangs
    until its deadline, which is cut short here; `stop_after_ms` presses stop
    that long after the start. Each broken line carries `carries` events
    before it breaks; `real_pauses` lets the waits run on the clock instead
    of being cut short."""
    stueck = _stueck(
        APP,
        r"\n      async function weiterZusehen\(laufJetzt, chatId, signal\) \{.*?\n      \}\n",
        "weiterZusehen",
    )
    grenzen = "\n".join(
        re.findall(r"  const WIEDERANHANG_PAUSE(?:_MAX)?_MS = [0-9_]+", APP.read_text(encoding="utf-8"))
    )
    assert "WIEDERANHANG_PAUSE_MS" in grenzen and "MAX" in grenzen, grenzen
    deadline = _stueck(APP, _WITH_DEADLINE, "withDeadline")
    skript = f"""
const HALTEPRUEFUNG_MS = 1
const NACHLADE_FRIST_MS = 50
{grenzen}
{deadline}
const refusedStatus = {json.dumps(refused_status)}
const hangs = {json.dumps(hangs)}
const stopAfterMs = {json.dumps(stop_after_ms)}
const carries = {carries}
const realPauses = {json.dumps(real_pauses)}
const protokoll = []
let zeileNachladen = false
let offen = {fehlschlaege}
let fragen = {len(antworten)}
const folge = {json.dumps(antworten)}
async function* zusehenStrom(id, ab, signal) {{
  protokoll.push(['strom', ab])
  // What fetch does with a signal that is already stopped.
  if (signal?.aborted) throw new DOMException('stopped', 'AbortError')
  if (offen > 0) {{
    offen -= 1
    for (let i = 0; i < carries; i++) yield {{ typ: 'content', text: 'piece' }}
    throw new Error('gerissen')
  }}
  if (refusedStatus) {{ const f = new Error('refused'); f.status = refusedStatus; throw f }}
  yield {{ typ: 'content', text: 'weiter' }}
}}
const api = {{
  nachrichten: async (chatId, optionen) => {{
    if (hangs) {{
      protokoll.push(['hangs'])
      return new Promise((_, nein) => optionen.signal.addEventListener(
        'abort', () => nein(optionen.signal.reason), {{ once: true }}))
    }}
    fragen += 1
    protokoll.push(['frage', fragen])
    const naechste = folge.shift()
    if (naechste === null || naechste === undefined) throw new Error('keine Verbindung')
    return naechste
  }},
}}
let ereignisZahl = 7
const ereignisVerarbeiten = async (strom) => {{
  for await (const e of strom) {{ ereignisZahl++; protokoll.push(['ereignis', e.text]) }}
}}
/* The pauses, counted instead of waited out: the real setTimeout would make
   this take minutes. */
const pausen = []
const echterTimer = globalThis.setTimeout
globalThis.setTimeout = (f, ms) => {{ pausen.push(ms); return echterTimer(f, realPauses ? ms : 0) }}
{stueck}
const lauf = {{ generationId: 'g1' }}
/* The deadline's own timer does not keep Node alive; this one does, until
   the run is over. */
const keepAlive = setInterval(() => {{}}, 10)
const stop = new AbortController()
if (stopAfterMs !== null) echterTimer(() => stop.abort(), stopAfterMs)
const begonnen = Date.now()
await weiterZusehen(lauf, 'c1', stop.signal).catch(
  (f) => protokoll.push(['fehler', f.name, f.status ?? null]))
const dauer = Date.now() - begonnen
clearInterval(keepAlive)
globalThis.setTimeout = echterTimer
console.log(JSON.stringify({{ protokoll, pausen, zeileNachladen, dauer }}))
"""
    return _node(skript)


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ein_zweiter_abriss_haengt_wieder_an_solange_der_dienst_den_lauf_kennt():
    """The line broke; the retry broke too; the service still knows the run.
    The window comes back to it — without a message, and the chat stays
    held, so the queue does not send into it."""
    stand = _weiter_zusehen(
        fehlschlaege=2,
        antworten=[{"laufend": {"generation_id": "g1"}, "gehalten": False}] * 2,
    )
    # Two lines broke and the third one carried the answer through.
    assert stand["protokoll"].count(["strom", 7]) == 3, stand["protokoll"]
    assert ["ereignis", "weiter"] in stand["protokoll"], stand["protokoll"]
    assert not [z for z in stand["protokoll"] if z[0] == "fehler"]
    # Two broken lines, two waits — the second already twice the first.
    assert stand["pausen"] == [1000, 2000], stand["pausen"]
    assert stand["zeileNachladen"] is False


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ohne_lauf_beim_dienst_steht_die_gespeicherte_zeile():
    """The service names no run and holds nothing: then there is nothing
    left to watch, and the stored row is what stands — with the state it
    ended in and no waiting mark."""
    stand = _weiter_zusehen(
        fehlschlaege=2,
        antworten=[{"laufend": None, "gehalten": False}],
    )
    assert stand["zeileNachladen"] is True
    assert ["ereignis", "weiter"] not in stand["protokoll"]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_die_pause_verdoppelt_sich_bis_halbminute():
    """A service that never answers must not be hammered: every further
    attempt waits twice as long as the one before, and the wait ends at
    half a minute (the yardstick's own numbers)."""
    stand = _weiter_zusehen(
        fehlschlaege=8,
        antworten=[{"laufend": {"generation_id": "g1"}, "gehalten": False}] * 7 + [
            {"laufend": None, "gehalten": False}
        ],
    )
    assert stand["pausen"][:4] == [1000, 2000, 4000, 8000], stand["pausen"]
    assert max(stand["pausen"]) == 30000, stand["pausen"]
    assert len(stand["pausen"]) <= 8


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_refused_second_attempt_fetches_the_stored_row():
    """The line broke, and the second attempt is refused (404: the run is
    gone, a restarted service). For a fresh send as for a resume, the stored
    row is fetched; the refusal itself still ends the run."""
    stand = _weiter_zusehen(
        fehlschlaege=1,
        antworten=[{"laufend": {"generation_id": "g1"}, "gehalten": False}],
        refused_status=404,
    )
    assert stand["zeileNachladen"] is True
    assert ["fehler", "Error", 404] in stand["protokoll"], stand["protokoll"]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_question_that_never_answers_ends_at_its_deadline():
    """A proxy that holds the question open: the deadline ends it, the loop
    is over, and the stored row stands — no hang, and no stop either."""
    stand = _weiter_zusehen(fehlschlaege=1, antworten=[], hangs=True)
    assert ["hangs"] in stand["protokoll"]
    assert stand["zeileNachladen"] is True
    assert not [z for z in stand["protokoll"] if z[0] == "fehler"], stand["protokoll"]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_stop_during_a_bounded_question_is_still_a_stop():
    """Silence probe for the deadline: the person's stop still arrives as
    an AbortError through the joined signal — a stop, not a stored row."""
    stand = _weiter_zusehen(fehlschlaege=1, antworten=[], hangs=True, stop_after_ms=10)
    assert ["fehler", "AbortError", None] in stand["protokoll"], stand["protokoll"]
    assert stand["zeileNachladen"] is False


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")


@needs_node
def test_a_line_that_carried_something_waits_a_second_again():
    """The counter: every event handled moves the position the next attempt
    resumes from, and a line that did carry something before it broke puts
    the wait back to one second instead of letting it climb."""
    stand = _weiter_zusehen(
        fehlschlaege=2,
        antworten=[{"laufend": {"generation_id": "g1"}, "gehalten": False}] * 2,
        carries=2,
    )
    streams = [z for z in stand["protokoll"] if z[0] == "strom"]
    assert streams == [["strom", 7], ["strom", 9], ["strom", 11]], stand["protokoll"]
    assert stand["pausen"] == [1000, 1000], stand["pausen"]


@needs_node
def test_a_stop_during_the_wait_ends_it_at_once():
    """Stop pressed while the window waits between two attempts: the wait
    ends there and then, not a second later, and it ends as a stop."""
    stand = _weiter_zusehen(
        fehlschlaege=1,
        antworten=[{"laufend": {"generation_id": "g1"}, "gehalten": False}],
        stop_after_ms=20, real_pauses=True,
    )
    assert ["fehler", "AbortError", None] in stand["protokoll"], stand["protokoll"]
    assert stand["pausen"][:1] == [1000], stand["pausen"]
    assert stand["dauer"] < 800, f"the wait outlived the stop: {stand['dauer']} ms"
    assert stand["zeileNachladen"] is False


def _send_failed(wiederanhang: str, fehler: str, stopped_before: bool = False) -> dict:
    """The outer catch of `antwortHolen`, run with a resume (or none) and an
    error: what it decides about the run and the stored row."""
    stueck = _stueck(
        APP,
        r"\n      abgebrochen = abgebrochen \|\| fehler\.name === 'AbortError'"
        r" \|\| abbruch\.signal\.aborted\n"
        r".*?\n      if \(gescheitert\) melde\(String\(fehler\.message \|\| fehler\), 'fehler'\)\n",
        "the outer catch",
    )
    skript = f"""
const gemeldet = []
const melde = (text, art) => gemeldet.push(art)
const abbruch = {{ signal: {{ aborted: false }} }}
const wiederanhang = {wiederanhang}
let abgebrochen = {json.dumps(stopped_before)}, belegt = false, gescheitert = false, zeileNachladen = false
const fehler = {fehler}
{stueck}
console.log(JSON.stringify({{ abgebrochen, belegt, gescheitert, zeileNachladen, gemeldet }}))
"""
    return _node(skript)


@needs_node
def test_eine_abgelehnte_wiederanbindung_holt_den_gespeicherten_stand():
    """A reattach the service REFUSED (404 for a run it no longer has): the
    row this window meant to fill from the stream stays empty unless the
    stored one is fetched. The refusal is still reported."""
    stand = _send_failed(
        "{ chatId: 'A', generationId: 'g1', messageId: 'm1' }",
        "Object.assign(new Error('Fehler 404'), { status: 404 })",
    )
    assert stand["zeileNachladen"] is True
    assert stand["gescheitert"] is True
    assert stand["gemeldet"] == ["fehler"]


@needs_node
def test_a_refused_fresh_send_fetches_nothing():
    """Silence probe: a fresh send refused with a status (no resume) and a
    resume that broke without one fetch no stored row here."""
    assert _send_failed("null", "Object.assign(new Error('x'), { status: 500 })")[
        "zeileNachladen"
    ] is False
    assert _send_failed(
        "{ chatId: 'A', generationId: 'g1', messageId: null }", "new Error('broken')"
    )["zeileNachladen"] is False


@needs_node
def test_a_stop_the_service_reported_stays_a_stop_when_the_line_breaks():
    """`done` said the run was stopped, then the line broke: still a stop,
    not a failure with a red dot and an error notice."""
    stand = _send_failed("null", "new Error('broken')", stopped_before=True)
    assert stand["abgebrochen"] is True
    assert stand["gescheitert"] is False
    assert stand["gemeldet"] == []
    # Silence probe: without that `done`, a broken line is a failure.
    assert _send_failed("null", "new Error('broken')")["gescheitert"] is True


@p662_braucht_node
def test_a_stored_row_to_fetch_makes_the_end_reconcile():
    """And the fetch it asks for is the reconcile at the end of the run —
    the only place allowed to replace the list, before the release."""
    bericht = _p662_lauf(
        _p662_quelle(),
        P662_AUFBAU
        + """
    await laufEnde({
      zielChat: 'A', abgebrochen: false, gescheitert: true,
      platzhalter: p1, verdichtetZu: null, zeileNachladen: true,
    })
    return { protokoll, naht: zustand.nachrichten.some((n) => n.id === 'naht') }
        """,
    )
    assert "api.nachrichten" in bericht["protokoll"], bericht["protokoll"]
    assert bericht["naht"], "the stored rows did not replace the list"


def test_the_product_is_named_exe_ai_where_the_user_reads_it():
    """The product is called "Exe AI". The page title, the title of a
    notification, the name the service states about itself,
    the sign-in page of the tools, the name an MCP server shows at sign-in
    and the head of the example configuration say so, and so do the page
    under "/", the web manifest, the shell's loading page and the name the
    service's bundle shows. No page and no catalogue text carries the former
    name."""
    former = "Exe AI Terminal"
    named = {
        "frontend/index.html": "<title>Exe AI</title>",
        "app/cronmeldung.py": 'TITEL = "Exe AI"\n',
        "app/api/v1/meta.py": 'name="Exe AI",\n',
        "app/api/v1/werkzeuge.py": "<title>{titel} — Exe AI</title>",
        "app/tools/mcp_auth.py": 'CLIENT_NAME = "Exe AI"\n',
        "config.example.yaml": "# Exe AI — configuration\n",
        "static/index.html": "<title>Exe AI</title>",
        "static/manifest.webmanifest": '"name": "Exe AI",\n',
        "fenster-electron/anzeige/index.html": "<title>Exe AI</title>",
        "deploy/exe-ai-terminal.spec": '"CFBundleName": "Exe AI",\n            "CFBundleDisplayName": "Exe AI",\n',
    }
    for path, line in named.items():
        assert line in (WURZEL / path).read_text(encoding="utf-8"), path
    # Nothing a page or a catalogue shows carries the former name.
    for path in (
        "frontend/index.html", "app/locales/de.json", "app/locales/en.json",
        "static/index.html", "static/manifest.webmanifest", "fenster-electron/anzeige/index.html",
    ):
        assert former not in (WURZEL / path).read_text(encoding="utf-8"), path
    # The silence check: the data folder keeps its name, the page under "/"
    # its sentence, and the folder of the service's bundle its name — the
    # packaging addresses it by that.
    start_page = (WURZEL / "static" / "index.html").read_text(encoding="utf-8")
    assert '<p lang="en">Phase 1 — Foundation. The interface will be built in Phase 2.</p>' in start_page
    assert "<p>Phase 1 — Grundlage. Die Oberfläche entsteht in Phase 2.</p>" in start_page
    assert 'name="Exe AI Terminal.app",' in (WURZEL / "deploy" / "exe-ai-terminal.spec").read_text(encoding="utf-8")
    packaging = (WURZEL / "app" / "paketierung.py").read_text(encoding="utf-8")
    assert '"Library" / "Application Support" / "Exe AI Terminal"' in packaging
    assert '"AppData" / "Roaming" / "Exe AI Terminal"' in packaging
    # The welcome sentence calls the program by its name too, not by the word
    # left over from the former one.
    texts = {
        language: json.loads((WURZEL / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))
        for language in ("de", "en")
    }
    assert {language: catalogue["erststart"]["satz"] for language, catalogue in texts.items()} == {
        "de": "Drei Einstellungen, mit denen du Exe AI auf dich abstimmst.",
        "en": "Three choices to make Exe AI your own.",
    }


def test_the_drawing_area_is_named_images_and_the_module_of_all_pictures_gallery():
    """The area the user draws in reads "Bilder" / "Images", and the module
    that holds every picture reads "Galerie" / "Gallery": two names for two
    things."""
    catalogues = {
        language: json.loads((WURZEL / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))
        for language in ("de", "en")
    }
    assert {language: texts["studio"]["titel"] for language, texts in catalogues.items()} == {
        "de": "Bilder", "en": "Images"}
    assert {language: texts["bilder"]["titel"] for language, texts in catalogues.items()} == {
        "de": "Galerie", "en": "Gallery"}
    # The silence check: the neighbouring words keep their own wording.
    de, en = catalogues["de"], catalogues["en"]
    assert (de["studio"]["bilder"], en["studio"]["bilder"]) == ("Bilder", "Images")
    assert (de["werkzeug"]["art_bilder"], en["werkzeug"]["art_bilder"]) == ("Bilder", "Images")
    assert (de["bild"]["bilder_zahl"], en["bild"]["bilder_zahl"]) == ("Bilder", "Images")
    assert (de["bilder"]["bildordner"], en["bilder"]["bildordner"]) == ("Bildordner", "Image folder")


# --- What goes out with the repository -------------------------------------
#
# The repository is public, and so is the page the service draws of its own
# routes. Both carry only what a reader of the program is meant to find.

# The German words a route description is made of, beside the ones a comment
# is judged by: such a line is two or three words long, mostly a noun and a
# verb, and seldom carries an article.
ROUTE_WORDS = {
    "entfernen", "zeigen", "holen", "starten", "anhalten", "speichern", "sichern",
    "auflisten", "lesen", "setzen", "anlegen", "abbrechen", "einschalten",
    "ausschalten", "ablegen", "suchen", "erzeugen", "verbessern", "beantworten",
    "zusehen", "hochladen", "liegt", "eines", "einer", "dem", "je", "alle",
    "welche", "welches", "auskunft", "zustand", "datei", "dateien", "bild",
    "bilder", "auftrag", "termin", "antwort", "werkzeuge", "modelle", "bereich",
    "aufnahme", "bildmodelle", "bildfortschritt", "liste", "verwaltung",
    "bearbeiten", "zuruecksetzen",
}


def _route_summaries(client) -> list[tuple[str, str]]:
    """The line the page of routes shows for every route of the service, as
    (method and address, text) — the `summary` a route is given, or the one
    made from the name of its function where it is given none."""
    return [
        (f"{method.upper()} {address}", str(route.get("summary", "")))
        for address, methods in client.app.openapi()["paths"].items()
        for method, route in methods.items()
        if isinstance(route, dict)
    ]


def _reads_german(text: str) -> bool:
    """One German word is enough in a line this short — so "hat", which a
    comment may carry once without being German, is left out here."""
    words = {word.lower() for word in re.findall(r"[A-Za-zÄÖÜäöüß]+", text)}
    return bool(re.search(r"[äöüÄÖÜß]", text) or words & ((DEUTSCHE_WOERTER | ROUTE_WORDS) - {"hat"}))


def test_every_route_description_is_english(client):
    summaries = _route_summaries(client)
    german = [f"{place}  {text}" for place, text in summaries if _reads_german(text)]
    assert not german, "German route descriptions:\n" + "\n".join(german)
    assert len(summaries) > 150, "the measurement lost its routes"


def test_a_german_route_description_is_told_from_an_english_one():
    """The probe itself, on both sides: short German lines without an umlaut
    are caught, and English lines pass — also the ones that share a word
    with German."""
    for text in ("Chat anlegen", "Bildmodelle", "Was der Server sagt", "Chat holen", "Image-Turbo — Zustand",
                 "Auto Setzen", "Zuruecksetzen"):
        assert _reads_german(text), text
    for text in ("Create a chat", "Server messages", "Stop a running command", "Image-Turbo — status",
                 "Get a chat", "List projects", "Model files", "Whoever wears the hat"):
        assert not _reads_german(text), text


# A container, a service file for a system the program is not offered on, an
# empty marker and a page nothing in the program links to.
LEFT_OUT = (
    "Dockerfile", "docker-compose.yml", ".dockerignore", "deploy/exe-ai-terminal.service",
    "prompts/.gitkeep", "static/zeichen/index.html",
)


def _tracked(path: str) -> bool:
    """Whether git tracks the path — False as well where this folder is no
    checkout."""
    asked = subprocess.run(
        ["git", "-C", str(WURZEL), "ls-files", "--error-unmatch", "--", path], capture_output=True,
    )
    return asked.returncode == 0


@pytest.mark.parametrize("path", LEFT_OUT)
def test_what_no_offered_way_uses_is_not_in_the_repository(path):
    assert not (WURZEL / path).exists(), path
    assert not _tracked(path), path


def test_what_the_service_delivers_from_static_is_still_there(client):
    """The silence probe: the page under "/", the help and the icons stay
    where the service takes them from, and the service still hands the two
    pages out — only the page that left is not answered any more."""
    for path in ("static/index.html", "static/hilfe", "static/icons", "static/klaenge", "deploy/exe-ai-terminal.spec"):
        assert (WURZEL / path).exists(), path
    assert client.get("/").status_code == 200
    assert client.get("/hilfe/").status_code == 200
    assert client.get("/zeichen/").status_code == 404


@pytest.mark.parametrize("page", ("static/hilfe/index.html", "static/hilfe/de/index.html"))
def test_no_section_the_manual_moves_the_focus_onto_draws_a_focus_ring(page):
    """The manual puts the focus on the section it shows, the overview or a
    chapter, so that a screen reader starts there. Such a section is no
    control: the browser's own focus ring around it would frame the whole
    page, as it did around the overview after a change of language."""
    text = (WURZEL / page).read_text(encoding="utf-8")
    focused = set(re.findall(r'<section class="([^"]+)"[^>]*\btabindex="-1"', text))
    assert {"home", "chapter"} <= {name for names in focused for name in names.split()}, (page, focused)
    # The selectors in front of the rule, from the brace before them on. The
    # look behind makes the search start a selector list only there: without
    # it every character of the page is tried as a start and read up to the
    # next brace, and the page's text is one long stretch without one.
    silenced = {
        selector.strip()
        for selectors in re.findall(r"(?:^|(?<=[{}]))([^{}]+)\{outline:none\}", text)
        for selector in selectors.split(",")
    }
    for names in sorted(focused):
        assert any(f".{name}:focus" in silenced for name in names.split()), (page, names)


def test_a_start_makes_the_folder_of_the_prompt_files(config, client):
    """A fresh copy of the program carries no prompts folder. The service
    makes it at its start and puts nothing into it: the prompt files are the
    user's, and a missing one still reads as the empty text."""
    folder = config.pfad(config.app.system_prompt_file).parent
    assert folder.is_dir()
    assert config.pfad(config.app.memory_file).parent.is_dir()
    assert not config.pfad(config.app.system_prompt_file).exists()
    assert not config.pfad(config.app.memory_file).exists()
    assert client.get("/api/v1/system-prompt").json()["text"] == ""
    assert client.get("/api/v1/memory").json()["text"] == ""


def test_the_readme_and_the_patch_notes_name_windows_and_the_updater():
    readme = (WURZEL / "README.md").read_text(encoding="utf-8")
    notes = (WURZEL / "PATCHNOTES.md").read_text(encoding="utf-8")
    assert "Windows (x64)" in readme
    assert "coming soon" not in readme
    assert "Automatic updates" in notes
    assert "no automatic updates" not in notes


def test_every_address_the_readme_lists_is_a_route_of_the_service(client):
    """The silence probe for the README: its table of routes names only
    addresses the service answers on."""
    readme = (WURZEL / "README.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"<code>(/[^<]*)</code>", readme))
    assert len(listed) > 30, "the measurement lost its table"
    routes = {route.path for route in client.app.routes}
    assert not listed - routes, sorted(listed - routes)
