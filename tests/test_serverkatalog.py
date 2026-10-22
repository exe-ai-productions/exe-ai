"""The shipped tool servers, their logos, their one line of purpose — and the
card the gallery draws from the three.

Four files have to agree for a card to be whole: the catalogue names the
server and how to sign in, the logo file carries its mark, both text
catalogues carry what it is for, and the gallery puts them together. A server
added to one of them and forgotten in another shows up as a card with a hole
in it — no mark, or a raw text key where the line should be.

The two JavaScript modules are imported, not searched: what is checked is
what the gallery gets. The gallery itself is a component whose logic lives in
its instance script, which cannot be run outside a browser, so it is read as
source text — the same standing in for a behavioural test the other checks of
this window use.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "frontend" / "src"
CATALOGUE = SOURCE / "lib" / "serverkatalog.js"
LOGOS = SOURCE / "lib" / "logos.js"
GALLERY = SOURCE / "teile" / "Verbindungen.svelte"
CARDS = SOURCE / "lib" / "mcpCards.js"
LOCALES = ROOT / "app" / "locales"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")

# name -> (title, address, sign-in). `oauth` where the provider's sign-in
# server registers a client by itself, `oauth_kennung` where a client id made
# by hand is the only way in.
SHIPPED = {
    "websuche": ("Exe Web Search", None, "keine"),
    "searxng": ("SearXNG", None, "keine"),
    "recraft": ("Recraft", "https://mcp.recraft.ai/mcp", "oauth"),
    "notion": ("Notion", "https://mcp.notion.com/mcp", "oauth"),
    "github": ("GitHub", "https://api.githubcopilot.com/mcp/", "schluessel"),
    "figma": ("Figma", "https://mcp.figma.com/mcp", "oauth"),
    "gmail": ("Gmail", "https://gmailmcp.googleapis.com/mcp/v1", "oauth_kennung"),
    "huggingface": ("Hugging Face", "https://huggingface.co/mcp", "schluessel"),
    "calendar": ("Google Calendar", "https://calendarmcp.googleapis.com/mcp/v1", "oauth_kennung"),
    "drive": ("Google Drive", "https://drivemcp.googleapis.com/mcp/v1", "oauth_kennung"),
    "slack": ("Slack", "https://mcp.slack.com/mcp", "oauth_kennung"),
    "canva": ("Canva", "https://mcp.canva.com/mcp", "oauth"),
    "todoist": ("Todoist", "https://ai.todoist.net/mcp", "oauth"),
    "spotify": ("Spotify", "https://mcp-gateway-external-pilot.spotify.net/mcp", "oauth_kennung"),
    "trello": ("Trello", "https://mcp.trello.com/v1", "oauth"),
    "asana": ("Asana", "https://mcp.asana.com/v2/mcp", "oauth_kennung"),
    "linear": ("Linear", "https://mcp.linear.app/mcp", "oauth"),
    "clickup": ("ClickUp", "https://mcp.clickup.com/mcp", "oauth"),
    "airtable": ("Airtable", "https://mcp.airtable.com/mcp", "oauth"),
    "vercel": ("Vercel", "https://mcp.vercel.com/", "oauth"),
    "sentry": ("Sentry", "https://mcp.sentry.dev/mcp", "oauth"),
}
# The marks that come in one colour and take the colour of the text.
MONOCHROME = ("github", "vercel", "sentry")
# The line of the last card, the way to a server of one's own.
OWN_SERVER = "eigener"


@lru_cache(maxsize=None)
def _modules() -> dict:
    """The catalogue and the logos as the gallery imports them."""
    script = (
        "const [k, l] = await Promise.all([import(process.argv[1]), import(process.argv[2])]);"
        "console.log(JSON.stringify({catalogue: k.SERVERKATALOG, logos: l.LOGOS,"
        " titles: Object.fromEntries(['canva', 'calendar', 'searxng', 'nobody', 'constructor']"
        ".map((n) => [n, k.serverTitel(n)]))}))"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, CATALOGUE.as_uri(), LOGOS.as_uri()],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout)


def _purposes(language: str) -> dict[str, str]:
    texts = json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))
    return texts["verbindungen"]["zweck"]


def _texts(language: str) -> dict:
    return json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))["verbindungen"]


def _gallery() -> str:
    return GALLERY.read_text(encoding="utf-8")


def _cards() -> str:
    """The rules of a card (state, name, logo, split into groups), which the page and the overview share."""
    return CARDS.read_text(encoding="utf-8")


def _card() -> str:
    return _gallery().split("{#snippet card(k)}", 1)[1].split("{/snippet}", 1)[0]


def _rule(selector: str) -> str:
    """The declarations of the one rule of the gallery that opens with this selector."""
    found = re.findall(r"\n  " + re.escape(selector) + r" \{(.*?)\}", _gallery(), re.S)
    assert len(found) == 1, selector
    return found[0]


# --- The catalogue ---------------------------------------------------------


@needs_node
def test_the_catalogue_ships_exactly_these_servers():
    catalogue = _modules()["catalogue"]
    assert [entry["name"] for entry in catalogue] == list(SHIPPED)
    for entry in catalogue:
        title, address, sign_in = SHIPPED[entry["name"]]
        assert (entry["titel"], entry["url"], entry["anmeldung"]) == (title, address, sign_in), entry["name"]


@needs_node
def test_the_self_run_search_is_a_card_that_asks_for_its_address():
    """SearXNG has no address of ours to ship. Its card is in the catalogue
    like Exe Web Search — no sign-in, no key — and names the program that
    starts here and the variable that program reads the address from; by
    that variable the sheet knows to ask. Nothing about the instance
    (limits, tool lists) is written for it."""
    entry = next(e for e in _modules()["catalogue"] if e["name"] == "searxng")
    assert entry["url"] is None and entry["anmeldung"] == "keine"
    assert entry["command"] == ".venv/bin/python" and entry["args"] == ["mcp/searxng_server.py"]
    assert entry["address_env"] == "SEARXNG_URL" and entry["vorauswahl"] is None
    # Only this one asks; the other shipped server that runs here does not.
    assert [e["name"] for e in _modules()["catalogue"] if "address_env" in e] == ["searxng"]
    assert "NAMED_ONLY" not in CATALOGUE.read_text(encoding="utf-8")


@needs_node
def test_every_server_names_a_sign_in_the_sheet_knows():
    """The sheet draws one row per kind of sign-in and nothing for a kind it
    has never heard of. A browser sign-in needs an address to go to and no
    key variable; a pasted key needs the variable it is kept in."""
    for entry in _modules()["catalogue"]:
        name, kind = entry["name"], entry["anmeldung"]
        assert kind in {"keine", "schluessel", "oauth", "oauth_kennung"}, name
        if kind in {"oauth", "oauth_kennung"}:
            assert entry["url"].startswith("https://"), name
            assert "api_key_env" not in entry, name
        if kind == "schluessel":
            assert entry.get("api_key_env"), name


@needs_node
def test_the_tools_window_gets_the_proper_name():
    """The second reader of the catalogue: `canva` is what the file calls it,
    `Canva` is what it is called. One nobody knows keeps its id — also when
    that id is a word every object answers to."""
    assert "named" not in _modules()
    assert _modules()["titles"] == {
        "canva": "Canva", "calendar": "Google Calendar", "searxng": "SearXNG", "nobody": "nobody",
        "constructor": "constructor",
    }


# --- The logos -------------------------------------------------------------


@needs_node
def test_every_shipped_server_has_a_logo():
    logos = _modules()["logos"]
    for name in SHIPPED:
        assert name in logos, f"{name} has no logo — its card would wear the plug"
        assert re.fullmatch(r"-?[\d.]+ -?[\d.]+ [\d.]+ [\d.]+", logos[name]["vb"]), name
        assert logos[name]["html"].strip(), name


@needs_node
def test_no_two_logos_share_an_id() -> None:
    """Twenty logos stand on one page as inline drawings: a gradient called
    `a` in two of them would paint both with whichever came first."""
    logos = _modules()["logos"]
    seen: dict[str, str] = {}
    for name, logo in logos.items():
        for ident in re.findall(r'\bid="([^"]+)"', logo["html"]):
            assert ident not in seen, f"id {ident!r} stands in {seen[ident]} and in {name}"
            seen[ident] = name
    # And what a server's logo points at, it carries itself.
    for name in SHIPPED:
        for reference in re.findall(r"url\(#([^)]+)\)", logos[name]["html"]):
            assert seen.get(reference) == name, f"{name} points at {reference!r}, which it does not carry"


@needs_node
def test_the_logos_of_the_servers_carry_drawings_only():
    """A logo is put into the page as markup. What came from outside holds
    shapes and paint, nothing that loads or runs."""
    logos = _modules()["logos"]
    allowed = {"g", "path", "rect", "circle", "ellipse", "polygon", "polyline", "line", "defs",
               "linearGradient", "radialGradient", "stop", "clipPath", "mask", "use"}
    for name in SHIPPED:
        markup = logos[name]["html"]
        assert set(re.findall(r"<([A-Za-z]+)", markup)) <= allowed, name
        assert not re.search(r"https?:|\son[a-z]+=|<script|foreignObject", markup), name
        # A reference stays inside the drawing it stands in.
        assert all(target.startswith("#") for target in re.findall(r'href="([^"]*)"', markup)), name


@needs_node
def test_the_monochrome_marks_follow_the_text_colour():
    """A black or dark-violet mark vanishes on a dark card."""
    logos = _modules()["logos"]
    for name in MONOCHROME:
        assert "currentColor" in logos[name]["html"], name
        assert not re.search(r'fill="#|fill:\s*#', logos[name]["html"]), name


# --- The lines -------------------------------------------------------------


@pytest.mark.parametrize("language", ["de", "en"])
def test_both_catalogues_carry_one_line_per_server(language):
    purposes = _purposes(language)
    assert set(purposes) == set(SHIPPED) | {OWN_SERVER}
    for name, line in purposes.items():
        assert line.strip() and line.endswith("."), f"{language}: {name}"


def test_the_lines_are_written_in_each_language():
    german, english = _purposes("de"), _purposes("en")
    assert all(german[name] != english[name] for name in german)


# --- The card --------------------------------------------------------------


def test_the_gallery_draws_a_card_with_line_and_foot():
    card = _card()
    # Who it is: the logo at forty, the name beside it.
    assert "{@render mark(k, 40)}" in card and "{titelVon(k)}" in card
    assert "const titelVon = (k) => (istKatalogName(k) ? serverTitel(nameVon(k)) : nameVon(k))" in _cards()
    # What it is for.
    assert '<p class="purpose">{purposeOf(name)}</p>' in card
    # What to do with it: for a server whose sign-in is gone, the grey house
    # button into the sheet …
    branch, on_file = card.split("{#if stand === 'getrennt'}", 1)[1].split("{:else}", 1)
    assert 'class="button"' in branch and "maskeOeffnen(k)" in branch
    assert "t('verbindungen.verbinden')" in branch
    # … and the state of every other server on file, which opens its menu.
    assert 'class="state"' in on_file and "oeffnen(k, e)" in on_file
    assert "{stateText(k, stand)}" in on_file
    assert 'aria-haspopup="menu"' in on_file


def test_a_server_without_a_logo_wears_the_plug():
    """Also a server whose id is a word every object answers to: asked for
    the table's own entries only, it has no logo and gets the plug like any
    other server nobody drew a mark for."""
    source = _gallery()
    assert "Object.hasOwn(LOGOS, nameVon(k)) ? LOGOS[nameVon(k)] : null" in _cards()
    # Card and menu both draw from that one answer, never from the table itself.
    assert "LOGOS[name]" not in source
    assert source.count("{#if logo}") == 2 and source.count("{@const logo = logoVon(k)}") == 2


def test_the_status_dot_in_the_corner_is_gone():
    """The state stands in the foot of the card; a second place for it in the
    corner would say the same thing twice."""
    source = _gallery()
    assert "punktecke" not in source
    assert 'class="kachel' not in source and ".kachel" not in source


def test_a_purpose_line_only_where_the_catalogue_has_one():
    """A server nobody shipped has no line. Asking the text catalogue for it
    anyway would print the key itself on the card."""
    source = _gallery()
    known = re.search(r"const withPurpose = new Set\((.*)\)\n", source)
    assert known and "KATALOG.map((k) => k.name)" in known.group(1)
    assert "NAMED_ONLY" not in source
    line = re.search(r"const purposeOf = \(serverName\) =>(.*?)\n\n", source, re.S)
    assert line and "withPurpose.has(serverName)" in line.group(1) and ": ''" in line.group(1)


def test_a_local_program_under_a_shipped_name_is_not_asked_to_sign_in():
    """A server of one's own may be called what a shipped one is called. If
    it starts a program on this machine, the browser sign-in of the shipped
    one is no question for it: read as one, a running server would show the
    button for connecting, and the sheet behind that button would write the
    shipped address over the entry."""
    state = _cards().split("export function zustand(kachel, status)", 1)[1].split("\n}", 1)[0]
    sign_in = state.split("const oauthKachel =", 1)[1].split("\n    if", 1)[0]
    assert "eintrag.type === 'http'" in sign_in


def test_the_last_tile_adds_a_server_of_ones_own():
    source = _gallery()
    own = source.split('<div class="tile own"', 1)[1].split("</div>\n    </div>", 1)[0]
    assert own.count("<button") == 1
    assert 'zeichen="stecker" groesse={36}' in own
    assert "t('verbindungen.custom_server')" in own
    assert "t('verbindungen.zweck.eigener')" in own
    assert 'class="button" onclick={mcpNeuOeffnen}' in own and "t('verbindungen.hinzufuegen')" in own
    # It is the last of the group, after the shipped servers without an entry.
    tiles = source.split('<div class="tiles">', 1)[1]
    assert tiles.index("{@render tile(k)}") < tiles.index('<div class="tile own"')


def test_the_cards_of_a_group_are_one_size():
    """As many columns as fit at 300 wide (three at about a thousand pixels of
    page, four at the full width), and one height for every row; a phone gets
    one column because the minimum gives way."""
    grid = _gallery().split("\n  .galerie {", 1)[1].split("}", 1)[0]
    assert "repeat(auto-fill, minmax(min(300px, 100%), 1fr))" in grid
    assert "grid-auto-rows: 1fr" in grid


def test_the_tiles_are_wide_and_at_least_eighty_eight_high():
    """Two columns at about a thousand pixels, three at the full width, every
    row as tall as its tallest tile."""
    grid = _rule(".tiles")
    assert "repeat(auto-fill, minmax(min(400px, 100%), 1fr))" in grid
    assert "grid-auto-rows: minmax(88px, auto)" in grid
    tile = _rule(".tile")
    assert "grid-template-columns: 36px minmax(0, 1fr) auto" in tile and "border-radius: 9px" in tile
    assert "--glass-card" in tile


def test_button_and_state_are_the_same_size():
    """Side by side in one row of cards, so neither may be taller than the other."""
    source = _gallery()
    state = re.search(r"\n  \.state \{(.*?)\}", source, re.S)
    assert state and "height: 34px" in state.group(1) and "border-radius: 9px" in state.group(1)
    assert "height: 34px" in _rule(".foot .button")


# --- The foot of a card still to be connected ------------------------------


def test_a_server_that_lost_its_sign_in_says_so_beside_the_button():
    """Set up once and no longer signed in is not the same as never set up:
    only the first stands as a card, with the red dot and the words to the
    left of the grey button. With the button alone nothing on the card would
    say that something has failed."""
    branch = _card().split("{#if stand === 'getrennt'}", 1)[1].split("{:else}", 1)[0]
    foot = branch.split('<div class="foot">', 1)[1]
    lost, after = foot.split('<span class="lost">', 1)[1].split("</span>\n        <button", 1)
    # The dot, then the words; no button inside them.
    assert "<button" not in lost
    assert lost.index("<Leuchtpunkt farbe={punktFarbe(stand)}") < lost.index("t('verbindungen.stand_getrennt')")
    # One grey button after the words.
    assert branch.count("<button") == 1 and after.count('class="button"') == 1
    assert "maskeOeffnen(k)" in after and "t('verbindungen.verbinden')" in after
    # The dot of that state is red, and so are the words — plain text on no surface.
    assert "stand === 'getrennt' || stand === 'schluessel_fehlt' ? 'rot'" in _cards()
    words = _rule(".lost")
    assert "color: var(--rot-text)" in words and "background" not in words and "border" not in words
    # One line: the words left, the button right and as tall as the state
    # button of a card beside it.
    line = _rule(".foot")
    assert "display: flex" in line and "align-items: center" in line
    button = _rule(".foot .button")
    assert "margin-left: auto" in button and "height: 34px" in button
    # Never cut short and never broken, in a narrow card too.
    whole = _rule(".lost .statetext")
    assert "white-space: nowrap" in whole and "line-height: 1.2" in whole
    assert "white-space: normal" not in whole and "ellipsis" not in whole


def test_a_server_on_file_that_needs_nothing_keeps_its_state_and_arrow():
    """The other side of the foot is as it was: the dot in the colour of the
    state, its words, the arrow into the menu — and nothing to connect."""
    source = _gallery()
    on_file = _card().split("{#if stand === 'getrennt'}", 1)[1].split("{:else}", 1)[1]
    assert "<Leuchtpunkt farbe={punktFarbe(stand)} groesse={11} />" in on_file
    assert 'class="arrow"' in on_file
    assert 'class="button"' not in on_file and 'class="lost"' not in on_file
    assert "stand === 'verbunden' || stand === 'wartet' ? 'gruen'" in _cards()
    green = re.search(
        r"\.state\[data-stand='verbunden'\],\s*\.state\[data-stand='wartet'\] \{(.*?)\}", source, re.S)
    assert green and "--state-colour: var(--gruen)" in green.group(1)
    # The words of that state wear the form made for type; the dot, the
    # surface and the line stay in the plain colour.
    assert "--state-ink: var(--gruen-text)" in green.group(1)
    assert "color: var(--state-ink)" in _rule(".state .statetext")


# --- The page above the cards ----------------------------------------------

INTRO = {
    "de": ("Eigene Apps, direkt im Chat.", "Exe mit den täglich genutzten Anwendungen verbinden."),
    "en": ("Your apps, directly in the chat.", "Connect Exe to the applications you use every day."),
}


@pytest.mark.parametrize("language", ["de", "en"])
def test_two_lines_stand_above_the_grid(language):
    texts = _texts(language)
    assert (texts["einleitung_kopf"], texts["einleitung"]) == INTRO[language]
    above = _gallery().split('<div class="rollbereich"', 1)[1].split('<div class="galerie">', 1)[0]
    assert above.index("t('verbindungen.einleitung_kopf')") < above.index("t('verbindungen.einleitung')")
    assert 'class="introhead"' in above and 'class="introhint"' in above


def test_the_second_line_is_a_quiet_hint():
    """Bold at the size of a section heading, and under it a quiet hint: the
    size of a hint and the still text colour, no size and no colour of its own."""
    head, hint = _rule(".introhead"), _rule(".introhint")
    assert "font-weight: 600" in head and "font-size: var(--schrift-abschnitt)" in head
    assert "color" not in head
    for declaration in ("font-size: var(--schrift-hinweis)", "color: var(--text-still)"):
        assert declaration in hint


def test_two_groups_by_the_entry_the_connected_cards_first():
    """"Installed" on top: every server with an entry as a card, what is
    connected or starting first. "Not installed" below: the shipped servers
    without an entry as tiles, and last the tile of one's own."""
    source = _gallery()
    page = source.split('<div class="rollbereich"', 1)[1].split("<style>", 1)[0]
    assert page.count('<div class="galerie">') == 1 and page.count('<div class="tiles">') == 1
    assert page.index('<div class="galerie">') < page.index('<div class="tiles">')
    assert "{#each setUp as k (schluesselVon(k))}{@render card(k)}{/each}" in page
    assert "{#each notSetUp as k (schluesselVon(k))}{@render tile(k)}{/each}" in page
    assert "Schriftzug" not in source and ".bereich" not in source and 'class="bereich"' not in source
    shared = _cards()
    assert "const isConnected = (stand) => ['verbunden', 'wartet'].includes(stand)" in shared
    group = shared.split("export function setUpCards(cards, status) {", 1)[1].split("\n}", 1)[0]
    assert "cards.filter((k) => zustand(k, status) !== 'frei')" in group
    assert "onFile.filter((k) => isConnected(zustand(k, status)))" in group
    assert "onFile.filter((k) => !isConnected(zustand(k, status)))" in group
    assert "export const notSetUpCards = (cards, status) => cards.filter((k) => zustand(k, status) === 'frei')" in shared
    assert "const setUp = $derived(setUpCards(alle, status))" in source
    assert "const notSetUp = $derived(notSetUpCards(alle, status))" in source
    # `zustand` stays the one place that decides; the markup never asks twice.
    assert shared.count("export function zustand(") == 1 and "function zustand(" not in source


def test_a_group_without_servers_leaves_no_empty_head():
    """No entry in the file: "Installed" goes with its head, no empty surface
    stands over nothing. The other group always has its own tile."""
    page = _gallery().split('<div class="rollbereich"', 1)[1].split("<style>", 1)[0]
    on_top = page.split("{#if setUp.length}", 1)[1].split("{/if}", 1)[0]
    assert "verbindungen.section_set_up" in on_top and "{setUp.length}" in on_top
    assert "verbindungen.section_not_set_up" not in on_top
    below = page.split("{/if}", 1)[1]
    assert "verbindungen.section_not_set_up" in below and "{notSetUp.length}" in below


def test_the_heads_are_half_bold_with_a_quiet_count():
    name = _rule(".sectionname")
    assert "font-weight: 600" in name and "color: var(--text-leise)" in name
    count = _rule(".sectioncount")
    assert "color: var(--text-still)" in count and "font-weight: 400" in count


@pytest.mark.parametrize("language,words", [("de", ("Eingerichtet", "Nicht eingerichtet")),
                                            ("en", ("Installed", "Not installed"))])
def test_the_two_heads_are_words_of_their_own(language, words):
    texts = _texts(language)
    assert (texts["section_set_up"], texts["section_not_set_up"]) == words
    # The state `frei` has no card any more, so no text of its own either.
    assert "stand_frei" not in texts


def test_a_tile_is_logo_name_line_and_the_grey_button_and_nothing_blue_is_left():
    source = _gallery()
    tile = source.split("{#snippet tile(k)}", 1)[1].split("{/snippet}", 1)[0]
    assert "{@render mark(k, 36)}" in tile and "{titelVon(k)}" in tile
    assert "purposeOf(nameVon(k))" in tile
    assert 'class="button" onclick={() => maskeOeffnen(k)}' in tile
    assert 'role="group" aria-label={titelVon(k)}' in tile
    # The one blue connect button of the program is gone with its rules.
    assert "--blau" not in source and ".connect" not in source and 'class="connect"' not in source


def test_no_rule_of_the_page_sets_a_plain_state_colour_as_type():
    """A plain colour is made for dots and surfaces; written words take the
    `-text` form. The colour of a surface or a line is not type and may mix
    the plain one, so only the `color` property is read here."""
    source = _gallery()
    plain = re.findall(r"(?<![-\w])color:\s*var\(--(gruen|gelb|rot|blau)\)", source)
    assert plain == [], plain


def test_every_state_word_wears_the_text_form_of_its_colour():
    source = _gallery()
    assert "color: var(--rot-text)" in _rule(".lost")
    heads = re.search(r"\.state\[data-stand='schluessel_fehlt'\] \{(.*?)\}", source, re.S)
    assert heads and "--state-ink: var(--rot-text)" in heads.group(1)
    assert "--state-colour: var(--rot)" in heads.group(1)
    stand = source.split(".mstand[data-stand='verbunden']", 1)[1].split(".mzeile", 1)[0]
    assert "var(--gruen-text)" in stand and "var(--rot-text)" in stand
    assert "color: var(--rot-text)" in _rule(".mleise.gefahr:hover")
