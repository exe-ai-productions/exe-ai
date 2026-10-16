"""Guards that the UI stays bilingual.

The catalog was once fully in place and yet the frontend never used it —
around ninety German texts were hard-coded. To keep that from coming back,
these tests check on every run:

  * does every ``t('…')`` call point to a key that actually exists?
  * has a German text been hard-coded into a display attribute again?

Both are cheap to check and would otherwise only show up once the spot
appears on screen — a mistyped key even only at the user's end.
"""

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
QUELLEN = WURZEL / "frontend" / "src"

# The brand name is the same in every language and must not be translated.
# The long form stays listed: it is still the name of the program folder and
# of the user's data directory, even though the surface now reads the short one.
ERLAUBT = {"Exe AI", "Exe AI Terminal"}


def _dateien():
    return sorted(QUELLEN.rglob("*.svelte")) + sorted(QUELLEN.rglob("*.js"))


def _flach(objekt, praefix=""):
    for schluessel, wert in objekt.items():
        if isinstance(wert, dict):
            yield from _flach(wert, f"{praefix}{schluessel}.")
        else:
            yield praefix + schluessel


def _katalog(sprache):
    return set(_flach(json.loads((WURZEL / "app" / "locales" / f"{sprache}.json").read_text(encoding="utf-8"))))


@pytest.fixture(scope="module")
def bekannte_schluessel():
    return _katalog("de")


def _benutzte_schluessel(datei):
    return re.findall(r"\bt\(\s*'([a-z_]+(?:\.[a-z_]+)+)'", datei.read_text(encoding="utf-8"))


@pytest.mark.skipif(not QUELLEN.is_dir(), reason="frontend sources not present")
def test_jeder_benutzte_schluessel_steht_im_katalog(bekannte_schluessel):
    """A typo in the key would otherwise show the key itself on screen."""
    fehlend = {}
    for datei in _dateien():
        for schluessel in re.findall(r"\bt\(\s*'([a-z_]+(?:\.[a-z_]+)+)'", datei.read_text(encoding="utf-8")):
            if schluessel not in bekannte_schluessel:
                fehlend.setdefault(schluessel, []).append(datei.name)
    assert not fehlend, f"Keys without an entry in the catalogue: {fehlend}"


@pytest.mark.skipif(not QUELLEN.is_dir(), reason="frontend sources not present")
def test_die_texte_des_cli_reiters_stehen_in_beiden_katalogen():
    """The CLI tab in the column and its state module read `cli.window.*`;
    the column and the sign row name the tab by `cli.titel`. Each of those
    keys stands in the English catalogue, the first version of every text,
    and in the German one."""
    gelesen = {
        schluessel
        for datei in (QUELLEN / "teile" / "Terminal.svelte", QUELLEN / "lib" / "windowTerminal.js")
        for schluessel in _benutzte_schluessel(datei)
        if schluessel.startswith("cli.window.")
    }
    assert {"cli.window.browser", "cli.window.ended", "cli.window.not_found"} <= gelesen
    # The tab's name is no call of its own: the column and the sign row each
    # look it up in their table of names.
    for source in (QUELLEN / "teile" / "Arbeitsleiste.svelte", QUELLEN / "teile" / "ToolSigns.svelte"):
        assert "'cli.titel'" in source.read_text(encoding="utf-8"), f"{source.name} no longer names the CLI tab"
    gelesen.add("cli.titel")
    for sprache in ("en", "de"):
        fehlend = gelesen - _katalog(sprache)
        assert not fehlend, f"cli keys missing in {sprache}.json: {sorted(fehlend)}"
    assert "shortcuts.cli" in _katalog("en") & _katalog("de")


@pytest.mark.skipif(not QUELLEN.is_dir(), reason="frontend sources not present")
def test_keine_festen_deutschen_texte_in_anzeige_attributen():
    """title, aria-label, placeholder and alt belong to the user, not the code."""
    umlaut = re.compile(r"[äöüÄÖÜß]")
    attribut = re.compile(r'\b(title|aria-label|placeholder|alt)="([^"{][^"]*)"')

    gefunden = []
    for datei in _dateien():
        inhalt = datei.read_text(encoding="utf-8")
        ohne_stil = re.sub(r"<style>.*?</style>", "", inhalt, flags=re.S)
        ohne_kommentar = re.sub(r"/\*.*?\*/|<!--.*?-->", "", ohne_stil, flags=re.S)
        for art, wert in attribut.findall(ohne_kommentar):
            if wert.strip() in ERLAUBT:
                continue
            if umlaut.search(wert) or " " in wert.strip():
                gefunden.append(f"{datei.name}: {art}={wert!r}")

    assert not gefunden, "Fixed text instead of t(…): " + "; ".join(gefunden)


# --- The CLI tab's terminal: what a selection looks like ------------------------

SHEET = QUELLEN / "stil" / "global.css"
WINDOW_TERMINAL = QUELLEN / "lib" / "windowTerminal.js"
TERMINAL_RESIZE = QUELLEN / "lib" / "terminalResize.js"

# Where the stylesheet opens the block of each of the five looks.
LOOK_BLOCKS = {
    "pearl": ":root {",
    "exe": ":root[data-modus='dunkel'] {",
    "darkmatter": ":root[data-modus='darkmatter'] {",
    "heaven": ":root[data-modus='heaven'] {",
    "moune": ":root[data-modus='moune'] {",
}

# How faint a selection was in the two dark looks while it was a see-through
# wash, which the drawing mixed with black: the ground under selected text
# against the ground beside it, measured in the picture.
FAINT_BEFORE = {"exe": 1.08, "darkmatter": 1.61}

# The share of the look's ink in the tone under a selection, and the least
# contrast a selection keeps against every colour its column lies on.
INK_IN_A_SELECTION = 0.25
MIN_SELECTION_CONTRAST = 1.5
# The looks whose share is measured against their gradient, not a quarter.
MEASURED_SHARE_LOOKS = ("heaven", "moune")

# What `data-modus` says in each look (the look of the first block, the
# light one, is set by the absence of the dark ones: it is `hell`).
MODUS_OF = {"pearl": "hell", "exe": "dunkel", "darkmatter": "darkmatter", "heaven": "heaven", "moune": "moune"}

# Runs the module's `theme()` once per look, with the sheet's two colours of
# that look in place of the page. The imports go: they pull in the drawing
# and the page's state, and the theme needs neither.
THEME_DRIVER = """
import { readFileSync, writeFileSync } from 'fs'
import { pathToFileURL } from 'url'
const [source, built, looks] = process.argv.slice(2)
writeFileSync(built, readFileSync(source, 'utf-8').replace(/^import .*$/gm, ''))
let sheet = {}
let modus = ''
globalThis.document = { documentElement: { getAttribute: (name) => (name === 'data-modus' ? modus : null) } }
globalThis.window = { matchMedia: () => ({ matches: true }) }
globalThis.getComputedStyle = () => ({ getPropertyValue: (name) => sheet[name] ?? '' })
const { theme } = await import(pathToFileURL(built).href)
const themes = {}
for (const [name, colours] of Object.entries(JSON.parse(looks))) {
  const { '--modus': own, ...values } = colours
  sheet = values
  modus = own
  themes[name] = theme()
}
console.log(JSON.stringify(themes))
"""


def _look_colours() -> dict[str, dict[str, str]]:
    """Ground and text colour of every look, as the stylesheet names them."""
    sheet = SHEET.read_text(encoding="utf-8")
    looks = {}
    for look, opening in LOOK_BLOCKS.items():
        start = sheet.index("\n" + opening) + 1
        block = sheet[start : sheet.index("\n}", start)]
        looks[look] = {
            name: re.search(rf"^\s*{name}:\s*(#[0-9a-fA-F]{{6}});", block, re.M).group(1)
            for name in ("--bg", "--text")
        }
        looks[look]["--modus"] = MODUS_OF[look]
        # The column's gradient as the page computes it: the look's own three
        # default stops where it names them (`--rahmen-vorgabe-N`).
        stops = re.findall(r"^\s*--rahmen-vorgabe-[123]:\s*(#[0-9a-fA-F]{6});", block, re.M)
        if len(stops) == 3:
            looks[look]["--frame"] = f"linear-gradient(160deg, {stops[0]} 0%, {stops[1]} 50%, {stops[2]} 100%)"
    return looks


@pytest.fixture(scope="module")
def terminal_themes(tmp_path_factory):
    """What `theme()` hands the drawing in each look, beside that look's
    two colours."""
    folder = tmp_path_factory.mktemp("window-terminal")
    driver = folder / "driver.mjs"
    driver.write_text(THEME_DRIVER, encoding="utf-8")
    looks = _look_colours()
    ran = subprocess.run(
        ["node", str(driver), str(WINDOW_TERMINAL), str(folder / "built.mjs"), json.dumps(looks)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert ran.returncode == 0, ran.stderr
    return {look: (looks[look], theme) for look, theme in json.loads(ran.stdout).items()}


def _channels(colour: str) -> tuple[int, ...]:
    return tuple(int(colour[at : at + 2], 16) for at in range(1, len(colour), 2))


def _luminance(colour: tuple[float, ...]) -> float:
    def linear(value: int) -> float:
        share = value / 255
        return share / 12.92 if share <= 0.03928 else ((share + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(value) for value in colour)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(one: tuple[float, ...], other: tuple[float, ...]) -> float:
    lighter, darker = sorted((_luminance(one), _luminance(other)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _tone(ground: tuple[int, ...], ink: tuple[int, ...], share: float) -> tuple[int, ...]:
    """The ground with that share of the ink mixed in, channel by channel."""
    return tuple(
        math.floor(below + (above - below) * share + 0.5) for below, above in zip(ground, ink, strict=True)
    )


def _stops(colours: dict[str, str]) -> list[tuple[float, ...]]:
    """The colours the column's gradient shows, from its computed value: its
    stops, and sixteen steps between each two neighbours, each taken down to
    whole steps of a channel (a blend of two stops can be darker than
    either, and the screen may show the lower step)."""
    stops = [_channels(stop) for stop in re.findall(r"#[0-9a-fA-F]{6}", colours.get("--frame", ""))]
    shown: list[tuple[float, ...]] = [*stops]
    for before, after in zip(stops, stops[1:], strict=False):
        for step in range(1, 16):
            shown.append(
                tuple(math.floor(b + (a - b) * step / 16) for b, a in zip(before, after, strict=True))
            )
    return shown


def _share_of(look: str, colours: dict[str, str]) -> float:
    """The share of ink the tone under a selection is made with: a quarter,
    and in Heaven and Moune the smallest (in hundredths) that keeps 1.5 : 1
    off every colour of the gradient."""
    if look not in MEASURED_SHARE_LOOKS:
        return INK_IN_A_SELECTION
    ground, ink = _channels(colours["--bg"]), _channels(colours["--text"])
    for hundredths in range(25, 101):
        tone = _tone(ground, ink, hundredths / 100)
        if all(_contrast(tone, stop) >= MIN_SELECTION_CONTRAST for stop in _stops(colours)):
            return hundredths / 100
    raise AssertionError("no share of ink reaches the contrast")


needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not QUELLEN.is_dir(), reason="no Node or no frontend sources"
)


@needs_node
@pytest.mark.parametrize("look", LOOK_BLOCKS)
def test_a_selection_in_the_cli_tab_lies_on_a_solid_tone_and_its_text_keeps_its_colour(terminal_themes, look):
    """Under selected text lies the look's ground with a quarter of its ink
    mixed in, as one solid colour — a see-through one the drawing would mix
    with black. It stands out from the ground beside it, lighter in a dark
    look and darker in a light one, and the text stands out from it; in the
    two looks where a selection was faint, both by more than it did then.

    Selected text has no colour of its own: it keeps the one it has, so
    block signs and coloured text stay what they were. Nor has a selection
    that lost the focus one: it is drawn like one that has it. The fixture
    asks the same module for every look in turn, so the tone follows the
    sheet as it stands when it is asked."""
    colours, theme = terminal_themes[look]
    ground, ink = _channels(colours["--bg"]), _channels(colours["--text"])
    assert "selectionForeground" not in theme
    assert "selectionInactiveBackground" not in theme
    assert re.fullmatch(r"#[0-9a-f]{6}", theme["selectionBackground"]), theme["selectionBackground"]
    under = _channels(theme["selectionBackground"])
    assert under == _tone(ground, ink, _share_of(look, colours))
    assert (_luminance(under) > _luminance(ground)) == (_luminance(ink) > _luminance(ground))
    stands_out, reads = _contrast(under, ground), _contrast(ink, under)
    assert reads > stands_out > FAINT_BEFORE.get(look, 1.0), (look, stands_out, reads)


@needs_node
@pytest.mark.parametrize("look", MEASURED_SHARE_LOOKS)
def test_in_heaven_and_moune_a_selection_stands_at_least_one_and_a_half_to_one_off_every_colour_it_lies_on(
    terminal_themes, look
):
    """The column of Heaven lies on a gradient whose darkest colour is as
    light as a quarter-ink tone — the two differ in hue only (1.0 : 1
    measured) — and the one of Moune is close behind (1.3 : 1). The tone is
    mixed with the smallest share of ink that lifts it to 1.5 : 1 against
    every colour of the gradient, so it stands that far off at the top, in
    the middle and at the bottom of the tab. With a quarter it falls short."""
    colours, theme = terminal_themes[look]
    stops = _stops(colours)
    assert len(stops) == 3 + 2 * 15
    under = _channels(theme["selectionBackground"])
    assert min(_contrast(under, stop) for stop in stops) >= MIN_SELECTION_CONTRAST
    # A quarter — what every other look keeps — would not do there.
    ground, ink = _channels(colours["--bg"]), _channels(colours["--text"])
    quarter = _tone(ground, ink, INK_IN_A_SELECTION)
    assert min(_contrast(quarter, stop) for stop in stops) < MIN_SELECTION_CONTRAST
    # And the share is the smallest one: one hundredth less does not reach it.
    share = _share_of(look, colours)
    less = _tone(ground, ink, round(share - 0.01, 2))
    assert min(_contrast(less, stop) for stop in stops) < MIN_SELECTION_CONTRAST


@needs_node
@pytest.mark.parametrize("look", [name for name in LOOK_BLOCKS if name not in MEASURED_SHARE_LOOKS])
def test_in_every_other_look_the_selection_keeps_its_quarter_of_ink(terminal_themes, look):
    """The silence side: nothing but Heaven and Moune changes."""
    colours, theme = terminal_themes[look]
    ground, ink = _channels(colours["--bg"]), _channels(colours["--text"])
    assert _channels(theme["selectionBackground"]) == _tone(ground, ink, INK_IN_A_SELECTION)


@needs_node
@pytest.mark.parametrize("look", LOOK_BLOCKS)
def test_the_cli_tabs_terminal_keeps_the_looks_ink_and_no_ground(terminal_themes, look):
    colours, theme = terminal_themes[look]
    # See-through: the column's surface is the ground. Where the look has a
    # gradient the drawing's ground carries its mean colour, at no opacity.
    assert re.fullmatch(r"#[0-9a-f]{6}00", theme["background"]), theme["background"]
    assert theme["cursorAccent"] == "#00000000"
    assert theme["foreground"] == theme["cursor"] == colours["--text"]
    assert "allowTransparency: true" in WINDOW_TERMINAL.read_text(encoding="utf-8")


# --- The CLI tab's terminal: no scrollbar -----------------------------------------

TERMINAL_TAB = QUELLEN / "teile" / "Terminal.svelte"
# The stylesheet the drawing brings along, where its packages are installed.
DRAWINGS_SHEET = WURZEL / "frontend" / "node_modules" / "@xterm" / "xterm" / "css" / "xterm.css"
# How the drawing names the bar of its own at its right edge, and the version
# of the drawing that name was read off.
DRAWINGS_OWN_BAR = ".xterm .xterm-scrollable-element > .scrollbar"
DRAWINGS_VERSION = "6.0.0"
PACKAGES = WURZEL / "frontend" / "package.json"


def _rules(sheet: str) -> dict[str, str]:
    """Each selector of a stylesheet with what its block declares, comments
    left out and blanks run together."""
    without_comments = re.sub(r"/\*.*?\*/", "", sheet, flags=re.S)
    return {
        " ".join(selector.split()): " ".join(block.split())
        for selector, block in re.findall(r"([^{}]+)\{([^{}]*)\}", without_comments)
    }


@pytest.mark.skipif(not QUELLEN.is_dir(), reason="frontend sources not present")
def test_the_cli_tab_draws_no_scrollbar_of_the_drawings_own():
    """The drawing brings a bar of its own that fades in at the right edge
    while it scrolls. The tab takes it out of the picture, for every state
    the bar can be in, and still leaves the viewport's own one hidden."""
    styles = TERMINAL_TAB.read_text(encoding="utf-8").split("<style>", 1)[1].split("</style>", 1)[0]
    rules = _rules(styles)
    assert rules[f".terminal :global({DRAWINGS_OWN_BAR})"] == "display: none;"
    assert rules[".terminal :global(.xterm .xterm-viewport)"] == "scrollbar-width: none;"
    assert rules[".terminal :global(.xterm .xterm-viewport::-webkit-scrollbar)"] == "display: none;"


@pytest.mark.skipif(not DRAWINGS_SHEET.is_file(), reason="the drawing's packages are not installed")
def test_the_bar_the_cli_tab_takes_out_is_the_one_the_drawing_brings():
    """A rule for a name the drawing does not use hides nothing: the name is
    the one the installed drawing's own stylesheet gives its bar."""
    assert DRAWINGS_OWN_BAR in _rules(DRAWINGS_SHEET.read_text(encoding="utf-8"))


@pytest.mark.skipif(not PACKAGES.is_file(), reason="frontend sources not present")
def test_the_bars_name_belongs_to_the_version_of_the_drawing_in_use():
    """The name is the drawing's own and may change with its version. Where
    the packages are not installed, nothing checks it against the drawing's
    stylesheet — so a change of version stops here first: read the bar's
    name off the new stylesheet, then name the new version."""
    wanted = json.loads(PACKAGES.read_text(encoding="utf-8"))["dependencies"]["@xterm/xterm"]
    assert wanted == DRAWINGS_VERSION


@pytest.mark.skipif(not QUELLEN.is_dir(), reason="frontend sources not present")
def test_the_cli_tabs_terminal_keeps_its_scrollback():
    """Without a bar the terminal still keeps what scrolled out of sight,
    and the wheel and the keys bring it back."""
    assert re.search(r"^\s*scrollback: 5000,$", WINDOW_TERMINAL.read_text(encoding="utf-8"), flags=re.M)


# The fit that counts the columns of the box, where its package is installed.
DRAWINGS_FIT = WURZEL / "frontend" / "node_modules" / "@xterm" / "addon-fit" / "lib" / "addon-fit.mjs"
# How the tab names the width the fit takes off the box, and how it gives it back.
BARS_WIDTH = re.compile(r"^const SCROLLBAR_WIDTH = (\d+)$", flags=re.M)
BARS_WIDTH_GIVEN_BACK = "holder.style.marginRight = `-${SCROLLBAR_WIDTH}px`"


@pytest.mark.skipif(not QUELLEN.is_dir(), reason="frontend sources not present")
def test_the_cli_tabs_terminal_counts_the_columns_that_fit_its_room():
    """The tab draws no bar, but the drawing's fit takes the width of one
    off the box before it counts the columns — a width set to 0 counts as
    unset and gives the same 14 px again. Without the width given back the
    terminal stands two columns narrower than the room it has. The holder is
    made that much wider than the room, so the fit counts what fits."""
    source = WINDOW_TERMINAL.read_text(encoding="utf-8")
    assert BARS_WIDTH.search(source)
    assert BARS_WIDTH_GIVEN_BACK in source


@pytest.mark.skipif(not DRAWINGS_FIT.is_file(), reason="the drawing's packages are not installed")
def test_the_width_the_cli_tab_gives_back_is_the_one_the_drawings_fit_takes_off():
    """A width that is not the fit's own leaves a column too many or too
    few: the number is the one the installed fit takes off, as it spells
    it out when no width is set."""
    given_back = BARS_WIDTH.search(WINDOW_TERMINAL.read_text(encoding="utf-8"))
    taken_off = re.search(r"overviewRuler\?\.width\|\|(\d+)", DRAWINGS_FIT.read_text(encoding="utf-8"))
    assert taken_off, "the fit no longer names the width it takes off: read it off the new version"
    assert given_back is not None
    assert given_back.group(1) == taken_off.group(1)


# --- The CLI tab's terminal: what is typed before the client's screen is up -----

# Runs the module against stand-ins: a drawing that records what is registered
# on it, a shell that records what it is sent, a page with nothing on it. Each
# scene gets the module afresh, shows the terminal, and then plays its steps:
# what is typed, what the client writes, and the client's end.
#
# The drawing's stand-in does what the real one does with a client's output:
# each control sequence goes to the handlers registered for it, the one
# registered last first, and a question for the cursor's position that none
# of them took for itself is answered — as typed data, which is the way the
# real drawing says anything to the client. A scene that begins with a step
# `system` runs on that system; every other on a Mac.
GATE_DRIVER = r"""
import { readFileSync, writeFileSync } from 'fs'
import { pathToFileURL } from 'url'
const [source, resizeSource, built, scenes] = process.argv.slice(2)
const standIns = `
const world = globalThis.world
class Xterm {
  constructor(options) {
    this.cols = 80
    this.rows = 24
    this.options = {}
    this.buffer = { active: { viewportY: 0, baseY: 0 } }
    this.parser = { registerCsiHandler: (id, handler) => { world.handlers.unshift({ id, handler }) } }
    this.constructed = options
    world.xterm = this
  }
  loadAddon(addon) { world.addons.push(addon) }
  open() {}
  focus() {}
  attachCustomKeyEventHandler() {}
  onResize(listener) { world.resized = listener }
  onData(listener) { world.typed = listener }
  write(data, done) { world.draw(data); if (done) done() }
  scrollToBottom() { this.buffer.active.viewportY = this.buffer.active.baseY }
  resize(cols, rows) {
    if (cols === this.cols && rows === this.rows) return
    // Fewer rows push rows into the history and leave the view where it
    // was, as the real drawing does when its scroll position is clamped.
    const active = this.buffer.active
    if (rows < this.rows) active.baseY += this.rows - rows
    else active.baseY = Math.max(0, active.baseY - (rows - this.rows))
    active.viewportY = Math.min(active.viewportY, active.baseY)
    this.cols = cols
    this.rows = rows
    world.resized({ cols, rows })
  }
}
class FitAddon {
  proposeDimensions() { return { ...world.box } }
  fit() { world.xterm.resize(world.box.cols, world.box.rows) }
}
class WebglAddon { onContextLoss() {} }
class WebLinksAddon { constructor(handler) { this.handler = handler } }
const t = (key) => key
const texte = { sprache: 'en' }
const zustand = { aktiverChat: '' }
const system = world.system
`
const strip = (file) => readFileSync(file, 'utf-8').replace(/^import .*$/gm, '')
writeFileSync(built, standIns + strip(resizeSource) + strip(source))

const ANSWER = '\x1b[1;1R'
const results = {}
let run = 0
for (const [name, allSteps] of Object.entries(JSON.parse(scenes))) {
  const world = { addons: [], opened: [], handlers: [], typed: null, sent: [], told: [], starts: 0, output: null, exit: null, box: { cols: 80, rows: 24 }, system: 'mac', frame: '' }
  // Leading steps that set the world the scene runs in: the system, and the
  // colour of what lies under the drawing.
  let steps = allSteps
  while (steps.length && ['system', 'frame'].includes(steps[0][0])) {
    world[steps[0][0]] = steps[0][1]
    steps = steps.slice(1)
  }
  world.draw = (data) => {
    for (const [, prefix, numbers, final] of String(data).matchAll(/\x1b\[(\??)([0-9;]*)([A-Za-z])/g)) {
      const params = numbers.split(';').filter(Boolean).map(Number)
      const taken = world.handlers
        .filter(({ id }) => (id.prefix ?? '') === prefix && id.final === final)
        .some(({ handler }) => handler(params))
      if (!taken && prefix === '' && final === 'n' && params[0] === 6) world.typed(ANSWER)
    }
  }
  globalThis.world = world
  globalThis.window = {
    exeHuelle: { terminal: {
      start: async () => { world.starts += 1; return { pid: 1 } },
      write: (data) => world.sent.push(data),
      resize: (cols, rows) => world.told.push([cols, rows]),
      onData: (listener) => { world.output = listener },
      onExit: (listener) => { world.exit = listener },
    } },
    matchMedia: () => ({ matches: true, addEventListener() {} }),
    open: (...given) => world.opened.push(given),
  }
  globalThis.document = {
    documentElement: { getAttribute: () => 'dunkel' },
    createElement: () => ({ isConnected: true, style: {} }),
  }
  globalThis.getComputedStyle = () => ({ getPropertyValue: (name) => (name === '--frame' ? world.frame : '') })
  globalThis.MutationObserver = class { observe() {} }
  globalThis.ResizeObserver = class { constructor(listener) { world.observer = listener } observe() {} disconnect() {} }
  run += 1
  const terminal = await import(`${pathToFileURL(built).href}?scene=${run}`)
  const root = { appendChild() {}, removeChild() {} }
  let hide = terminal.show(root)
  await Promise.resolve()
  const seen = []
  const sizes = []
  const told = []
  const view = []
  for (const [kind, data, rows] of steps) {
    if (kind === 'typed') world.typed(data)
    else if (kind === 'client') world.output(data)
    else if (kind === 'end') world.exit(0)
    else if (kind === 'box') { world.box = { cols: data, rows }; world.observer() }
    // The box changes while the drawing is taken out of view.
    else if (kind === 'quiet') world.box = { cols: data, rows }
    // The client wrote this many rows of history, and the view is on the last.
    else if (kind === 'history') {
      world.xterm.buffer.active.baseY = data
      world.xterm.buffer.active.viewportY = data
    }
    // The person scrolled this many rows up.
    else if (kind === 'scrolled') world.xterm.buffer.active.viewportY -= data
    else if (kind === 'hide') hide()
    // A click on a link the client wrote (OSC 8) and on an address the
    // drawing found in the text.
    else if (kind === 'link') world.xterm.constructed.linkHandler.activate({}, data, {})
    else if (kind === 'address') world.addons.find((addon) => addon.handler).handler({}, data)
    else if (kind === 'show') hide = terminal.show(root)
    await Promise.resolve()
    seen.push([...world.sent])
    sizes.push([world.xterm.cols, world.xterm.rows])
    told.push(world.told.map((size) => [...size]))
    view.push([world.xterm.buffer.active.viewportY, world.xterm.buffer.active.baseY])
  }
  results[name] = { sent: world.sent, seen, sizes, told, view, starts: world.starts, opened: world.opened, ground: world.xterm.constructed.theme.background }
}
console.log(JSON.stringify(results))
"""

# What the terminal answers when the client asks where the cursor stands.
CURSOR_ANSWER = "\x1b[1;1R"
# How the client's output begins, before its screen is up: the cursor's
# shape, the cursor shown, and the head with the wordmark.
HEAD = "\x1b[?12l\x1b[?25h\r\n  ██╗  the head\r\n"
# The first thing the client's screen does, and its first drawing.
ASKS_FOR_THE_CURSOR = "\x1b[6n"
FIRST_DRAWING = "\x1b[?2004h\x1b[?25l"

GATE_SCENES = {
    "typed_early": [
        ["typed", "a"],
        ["typed", "b"],
        ["client", HEAD],
        ["client", ASKS_FOR_THE_CURSOR + FIRST_DRAWING],
        ["typed", "c"],
    ],
    "typed_early_with_enter": [
        ["typed", "hello"],
        ["typed", "\r"],
        ["client", HEAD + ASKS_FOR_THE_CURSOR + FIRST_DRAWING],
        ["typed", "\r"],
    ],
    "interrupted_early": [
        ["typed", "a"],
        ["typed", "\x03"],
        ["end", ""],
    ],
    "typed_early_on_windows": [
        ["system", "windows"],
        ["typed", "a"],
        ["client", HEAD],
        ["typed", "b"],
    ],
    "typed_late": [
        ["client", HEAD + ASKS_FOR_THE_CURSOR + FIRST_DRAWING],
        ["typed", "x"],
    ],
    # The colour of the column under the drawing, a plain one and a gradient.
    "ground_plain": [["frame", "#353634"], ["client", HEAD]],
    "ground_gradient": [
        ["frame", "linear-gradient(135deg, #102030 0%, rgb(30, 50, 70) 50%, #405060 100%)"],
        ["client", HEAD],
    ],
    "ground_unknown": [["client", HEAD]],
    # A click on a link the client wrote, on an address the drawing found
    # itself, and on two that must not open.
    "clicked_addresses": [
        ["client", HEAD + ASKS_FOR_THE_CURSOR + FIRST_DRAWING],
        ["link", "https://docs.example.com/guides/getting-started/installation?lang=en"],
        ["address", "https://docs.example.com/a/very/long/path?x=1"],
        ["link", "file:///etc/passwd"],
        ["address", "javascript:alert(1)"],
    ],
    "never_asks": [
        ["typed", "a"],
        ["client", HEAD],
        ["client", FIRST_DRAWING],
        ["typed", "b"],
    ],
    "started_again": [
        ["client", HEAD + ASKS_FOR_THE_CURSOR + FIRST_DRAWING],
        ["end", ""],
        ["typed", "\r"],
        ["typed", "b"],
        ["client", HEAD],
        ["client", ASKS_FOR_THE_CURSOR + FIRST_DRAWING],
    ],
    "ends_without_a_drawing": [
        ["typed", "a"],
        ["client", HEAD],
        ["end", ""],
        ["typed", "z"],
        ["typed", "\r"],
        ["typed", "b"],
        ["client", HEAD + ASKS_FOR_THE_CURSOR + FIRST_DRAWING],
        ["typed", "c"],
    ],
    # The client's screen is up; the box gets narrower, then the question for
    # the cursor arrives, in a piece of output of its own.
    "narrower_with_the_screen_up": [
        ["client", HEAD + ASKS_FOR_THE_CURSOR + FIRST_DRAWING],
        ["box", 60, 24],
        ["client", "\x1b[2K"],
        ["client", ASKS_FOR_THE_CURSOR],
        ["client", "drawn anew"],
    ],
    "narrower_twice_while_waiting": [
        ["client", HEAD + ASKS_FOR_THE_CURSOR + FIRST_DRAWING],
        ["box", 60, 24],
        ["box", 40, 24],
        ["client", ASKS_FOR_THE_CURSOR],
        ["client", ASKS_FOR_THE_CURSOR],
    ],
    "wider_with_the_screen_up": [
        ["client", HEAD + ASKS_FOR_THE_CURSOR + FIRST_DRAWING],
        ["box", 100, 24],
    ],
    "narrower_before_the_screen_is_up": [
        ["client", HEAD],
        ["box", 60, 24],
    ],
    "narrower_and_the_client_ends": [
        ["client", HEAD + ASKS_FOR_THE_CURSOR + FIRST_DRAWING],
        ["box", 60, 24],
        ["end", ""],
    ],
    "narrower_on_windows": [
        ["system", "windows"],
        ["client", HEAD],
        ["box", 60, 24],
    ],
    "only_lower_with_the_screen_up": [
        ["client", HEAD + ASKS_FOR_THE_CURSOR + FIRST_DRAWING],
        ["box", 80, 20],
    ],
    # The view stands on the last row, where the client's block is; the box
    # gets lower, or is shown again with another height.
    "lower_with_the_view_on_the_last_row": [
        ["client", HEAD + ASKS_FOR_THE_CURSOR + FIRST_DRAWING],
        ["history", 30],
        ["box", 80, 20],
    ],
    "lower_with_the_view_scrolled_up": [
        ["client", HEAD + ASKS_FOR_THE_CURSOR + FIRST_DRAWING],
        ["history", 30],
        ["scrolled", 10],
        ["box", 80, 20],
    ],
    "shown_again_lower_with_the_view_on_the_last_row": [
        ["client", HEAD + ASKS_FOR_THE_CURSOR + FIRST_DRAWING],
        ["history", 30],
        ["hide", ""],
        ["quiet", 80, 20],
        ["show", ""],
    ],
    "shown_again_lower_with_the_view_scrolled_up": [
        ["client", HEAD + ASKS_FOR_THE_CURSOR + FIRST_DRAWING],
        ["history", 30],
        ["scrolled", 10],
        ["hide", ""],
        ["quiet", 80, 20],
        ["show", ""],
    ],
}


@pytest.fixture(scope="module")
def gate_scenes(tmp_path_factory):
    """What reached the client in each scene: everything in order (`sent`),
    what had reached it after each step (`seen`), how often the client was
    started (`starts`), the size the drawing had after each step (`sizes`)
    and the sizes the client had been told by then (`told`)."""
    folder = tmp_path_factory.mktemp("window-terminal-gate")
    driver = folder / "driver.mjs"
    driver.write_text(GATE_DRIVER, encoding="utf-8")
    ran = subprocess.run(
        [
            "node",
            str(driver),
            str(WINDOW_TERMINAL),
            str(TERMINAL_RESIZE),
            str(folder / "built.mjs"),
            json.dumps(GATE_SCENES),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert ran.returncode == 0, ran.stderr
    return json.loads(ran.stdout)


@needs_node
def test_a_key_typed_before_the_clients_screen_is_up_waits_and_then_arrives_once_in_order(gate_scenes):
    """Until the client reads keys one by one, the terminal it runs in shows
    every key by itself: a key sent then stands above the client's head."""
    scene = gate_scenes["typed_early"]
    after_a, after_b, after_the_head, after_the_screen, after_c = scene["seen"]
    assert after_a == after_b == after_the_head == []
    # Both keys in one piece, as typed, and before the terminal's answer.
    assert after_the_screen == ["ab", CURSOR_ANSWER]
    assert after_c == ["ab", CURSOR_ANSWER, "c"]


@needs_node
def test_an_enter_typed_before_the_screen_is_up_arrives_as_a_line_break(gate_scenes):
    """What was typed early stands in the input field and is not sent: the
    Enter that waited with it breaks the line, as it did when the terminal
    handed it on itself. An Enter typed once the screen is up is an Enter."""
    scene = gate_scenes["typed_early_with_enter"]
    assert scene["sent"] == ["hello\n", CURSOR_ANSWER, "\r"]


@needs_node
def test_the_interrupt_key_reaches_a_client_that_is_still_on_its_way_up_at_once(gate_scenes):
    """A client that hangs before its screen is up can be stopped as
    before; what was typed ahead of the interrupt stays where it waited."""
    scene = gate_scenes["interrupted_early"]
    after_a, after_the_interrupt, after_the_end = scene["seen"]
    assert after_a == []
    assert after_the_interrupt == after_the_end == ["\x03"]


@needs_node
def test_on_windows_nothing_waits(gate_scenes):
    """There the client's terminal shows no key before the client reads,
    and a client's first drawing is not sure to reach the page as one: a
    gate that waited for it could stay shut for good."""
    scene = gate_scenes["typed_early_on_windows"]
    assert scene["seen"] == [["a"], ["a"], ["a", "b"]]


@needs_node
def test_a_key_typed_once_the_screen_is_up_goes_straight_to_the_client(gate_scenes):
    scene = gate_scenes["typed_late"]
    assert scene["seen"] == [[CURSOR_ANSWER], [CURSOR_ANSWER, "x"]]


@needs_node
def test_what_the_terminal_answers_is_never_kept_waiting(gate_scenes):
    """The answer to the client's question leaves in the very step the
    question arrives in, with keys waiting and with none."""
    assert gate_scenes["typed_early"]["seen"][3][-1] == CURSOR_ANSWER
    assert gate_scenes["typed_late"]["seen"][0] == [CURSOR_ANSWER]


@needs_node
def test_a_client_that_never_asks_for_the_cursor_gets_the_keys_with_its_first_drawing(gate_scenes):
    scene = gate_scenes["never_asks"]
    after_a, after_the_head, after_the_drawing, after_b = scene["seen"]
    # The mode switches the head begins with are not a screen yet.
    assert after_a == after_the_head == []
    assert after_the_drawing == ["a"]
    assert after_b == ["a", "b"]


@needs_node
def test_a_client_started_again_is_waited_for_like_the_first(gate_scenes):
    """After the client's end Enter starts it again, as before — and until
    the new client's screen is up, what is typed waits again."""
    scene = gate_scenes["started_again"]
    assert scene["starts"] == 2
    first_screen, after_the_end, after_enter, after_b, after_the_head, second_screen = scene["seen"]
    assert first_screen == after_the_end == after_enter == after_b == after_the_head == [CURSOR_ANSWER]
    assert second_screen == [CURSOR_ANSWER, "b", CURSOR_ANSWER]


@needs_node
def test_after_a_client_that_ended_without_a_screen_nothing_typed_later_is_lost(gate_scenes):
    """The client ends before its screen was ever up. What waited for it
    goes nowhere, as nothing typed after its end does; Enter starts the
    client again as before, and what is typed for the new one reaches it."""
    scene = gate_scenes["ends_without_a_drawing"]
    assert scene["starts"] == 2
    after_a, after_the_head, after_the_end, after_z, after_enter, after_b, after_the_screen, after_c = scene["seen"]
    assert after_a == after_the_head == after_the_end == after_z == after_enter == after_b == []
    assert after_the_screen == ["b", CURSOR_ANSWER]
    assert after_c == ["b", CURSOR_ANSWER, "c"]


# --- The CLI tab's terminal: the order in which a narrower box is followed ------


@needs_node
def test_a_narrower_box_is_told_to_the_client_first_and_the_drawing_follows_after_its_question(gate_scenes):
    """The terminal breaks every row anew that no longer fits, the rows of
    the client's block among them. So the client hears of the new width
    while the drawing still has the old one, takes its block off, asks
    where its cursor stands — and only when that question has been read
    does the drawing take the width."""
    scene = gate_scenes["narrower_with_the_screen_up"]
    after_the_screen, after_the_box, after_the_erase, after_the_question, after_the_drawing = scene["sizes"]
    assert after_the_screen == after_the_box == after_the_erase == [80, 24]
    assert after_the_question == after_the_drawing == [60, 24]
    assert scene["told"][1] == scene["told"][-1] == [[60, 24]]


@needs_node
def test_a_box_that_changes_again_while_the_drawing_waits_is_taken_after_the_question(gate_scenes):
    """The second change is looked at once the first one is done: the
    client is told 60 first, then 40, and the drawing ends at 40 after the
    next question."""
    scene = gate_scenes["narrower_twice_while_waiting"]
    after_the_screen, after_the_first, after_the_second, after_the_question, after_the_next = scene["sizes"]
    assert after_the_first == after_the_second == [80, 24]
    # The first question lets the drawing take 60; the box is 40 by then, and
    # the client is told that at once. The next question lets it take 40.
    assert after_the_question == [60, 24]
    assert after_the_next == [40, 24]
    assert scene["told"][-1] == [[60, 24], [40, 24]]


@needs_node
def test_a_wider_box_is_followed_at_once(gate_scenes):
    """Nothing is broken when the drawing gets wider: the client hears of it
    with the drawing, as always."""
    scene = gate_scenes["wider_with_the_screen_up"]
    assert scene["sizes"][-1] == [100, 24]
    assert scene["told"][-1] == [[100, 24]]


@needs_node
def test_a_box_that_is_only_lower_is_followed_at_once(gate_scenes):
    scene = gate_scenes["only_lower_with_the_screen_up"]
    assert scene["sizes"][-1] == [80, 20]
    assert scene["told"][-1] == [[80, 20]]


@needs_node
def test_before_the_clients_screen_is_up_a_narrower_box_is_followed_at_once(gate_scenes):
    """No block stands there yet that the terminal could break."""
    scene = gate_scenes["narrower_before_the_screen_is_up"]
    assert scene["sizes"][-1] == [60, 24]
    assert scene["told"][-1] == [[60, 24]]


@needs_node
def test_a_client_that_ends_while_the_drawing_waits_lets_it_take_the_width(gate_scenes):
    """Nobody asks any more, so nothing would ever let the drawing go on."""
    scene = gate_scenes["narrower_and_the_client_ends"]
    after_the_screen, after_the_box, after_the_end = scene["sizes"]
    assert after_the_box == [80, 24]
    assert after_the_end == [60, 24]


@needs_node
def test_on_windows_a_narrower_box_is_followed_at_once(gate_scenes):
    """The console between the client and the window's terminal breaks
    nothing of the block the way the terminal does."""
    scene = gate_scenes["narrower_on_windows"]
    assert scene["sizes"][-1] == [60, 24]


# --- The CLI tab's terminal: the view stays on the last row of the client -------


@needs_node
def test_a_lower_box_leaves_the_view_on_the_last_row_where_it_stood(gate_scenes):
    """The block of the client stands on the last rows. When the drawing
    gets fewer rows its scroll position is clamped and the view can be left
    above the last row: the block is then out of view until it is scrolled
    to. A view that stood on the last row stands there after the change."""
    scene = gate_scenes["lower_with_the_view_on_the_last_row"]
    viewport, base = scene["view"][-1]
    assert scene["sizes"][-1] == [80, 20]
    assert viewport == base == 34


@needs_node
def test_a_view_the_person_scrolled_up_is_left_where_it_is(gate_scenes):
    scene = gate_scenes["lower_with_the_view_scrolled_up"]
    assert scene["view"][-1] == [20, 34]


@needs_node
def test_a_drawing_shown_again_with_another_height_stands_on_the_last_row(gate_scenes):
    """The column shows another tool and then the CLI again, and its height
    is another one meanwhile: the drawing is taken in with fewer rows."""
    scene = gate_scenes["shown_again_lower_with_the_view_on_the_last_row"]
    viewport, base = scene["view"][-1]
    assert scene["sizes"][-1] == [80, 20]
    assert viewport == base == 34


@needs_node
def test_a_drawing_shown_again_keeps_the_view_the_person_scrolled_up(gate_scenes):
    scene = gate_scenes["shown_again_lower_with_the_view_scrolled_up"]
    assert scene["view"][-1] == [20, 34]


@needs_node
def test_a_click_on_an_address_of_the_history_opens_it_once_in_the_browser(gate_scenes):
    """An address the client wrote as a link and one the drawing found in the
    text each go to the window's switch as the whole address, once, in a tab
    of its own; nothing but http and https goes."""
    scene = gate_scenes["clicked_addresses"]
    assert scene["opened"] == [
        ["https://docs.example.com/guides/getting-started/installation?lang=en", "_blank"],
        ["https://docs.example.com/a/very/long/path?x=1", "_blank"],
    ]


@needs_node
def test_the_drawing_is_given_both_ways_to_open_an_address():
    """The drawing asks no browser dialog and opens no empty window: it is
    given its own handler for a link the client wrote, and the add-on that
    finds addresses is given one as well."""
    source = WINDOW_TERMINAL.read_text(encoding="utf-8")
    assert "linkHandler: { activate:" in source
    assert "new WebLinksAddon((_event, address) => openAddress(address))" in source
    assert "confirm(" not in source
    assert "window.open()" not in source


@needs_node
def test_the_drawing_is_given_the_colour_of_the_column_under_it_without_opacity(gate_scenes):
    """A cell with a link or an underline is painted on a solid ground made
    of the drawing's ground colour: black where that is none. Given the
    column's colour with no opacity, the box under an address cannot be
    seen — and a ground that is none stays none where the column's colour
    is unknown."""
    assert gate_scenes["ground_plain"]["ground"] == "#35363400"
    assert gate_scenes["ground_gradient"]["ground"] == "#25364700"
    assert gate_scenes["ground_unknown"]["ground"] == "#00000000"
