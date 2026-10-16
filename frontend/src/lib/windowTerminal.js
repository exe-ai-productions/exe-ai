/*
  The CLI in the window: xterm.js on this side, the client `exe` in a
  pseudoterminal of the shell on the other (fenster-electron/terminal.js,
  reached over the bridge `window.exeHuelle.terminal`).

  What stands here lives as long as the page: the drawing, its scrollback
  and the listeners on the bridge. The component (teile/Terminal.svelte)
  only shows it. Folded away with the column it is gone from view, and the
  client keeps running in the shell; unfolded, the same drawing comes back
  with everything that arrived meanwhile. One terminal per window.

  The drawing has no ground of its own — `allowTransparency` and a ground
  with full alpha — so the column's surface shows through; the client is
  told it runs here and leaves the ground alone. The text takes the look's
  ink, read off the sheet, and follows a change of look; a selection lies
  on a tone between the look's ground and that ink, and its text keeps its
  colour. Look, language and the open chat go to the client once, at its
  start. What is typed before the client's screen is up waits here and
  reaches the client with its first drawing.
*/

import { Terminal as Xterm } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import { WebglAddon } from '@xterm/addon-webgl'
import { api } from './api.js'
import { droppedText } from './droppedPaths.js'
import { system } from './keyNames.js'
import { followTheBox } from './terminalResize.js'
import { t, texte } from './texte.svelte.js'
import { zustand } from './zustand.svelte.js'

/** The shell's side of the terminal, or undefined in a plain browser. */
export function bridge() {
  return typeof window !== 'undefined' ? window.exeHuelle?.terminal : undefined
}

/* The window's looks under the client's names: the fixed ones by name,
   the own gradient by whether it stands dark or light, and a look that
   follows the device by what the device prefers. */
const LOOKS = { dunkel: 'exe', hell: 'pearl', darkmatter: 'darkmatter', heaven: 'heaven', moune: 'moune' }

export function currentLook() {
  const root = document.documentElement
  const modus = root.getAttribute('data-modus')
  if (modus === 'eigen') return root.getAttribute('data-eigen') === 'hell' ? 'pearl' : 'exe'
  if (modus === null) return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'exe' : 'pearl'
  return LOOKS[modus] ?? 'exe'
}

/* No ground, the look's ink for text and cursor. Under a selection lies a
   solid tone mixed from the look's two colours; what is selected keeps its
   own colour, so letters and the block and line signs of the wordmark stay
   visible. A see-through wash is no way to do it: the drawing mixes a
   selection's colour with its own ground, and that ground, having none,
   counts as black. With or without the focus the selection looks the
   same. Read off the sheet as it applies right now. */
const NO_GROUND = '#00000000'
const FALLBACK_INK = '#ecebe6'
const FALLBACK_GROUND = '#1c1c1a'

function sheetColour(name, fallback) {
  const read = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return /^#[0-9a-f]{6}$/i.test(read) ? read : fallback
}

/* The tone under a selection: the look's ground with a quarter of its ink
   mixed in, channel by channel — a faint wash of the ink, handed to the
   drawing as one solid colour, so it paints exactly that. In a dark look
   the tone is lighter than the ground, in a light look darker.

   Heaven and Moune need more: Heaven's column lies on a gradient whose
   darkest colour stands as close to a quarter-ink tone in lightness as
   1.0 : 1 (measured: the two differ in hue only), Moune's at 1.3 : 1. There
   the share is the smallest one that
   lifts the tone to 1.5 : 1 against every colour of the gradient — the
   stops and what lies between two of them: a blend of two stops can be
   darker than either (measured at the top of the tab, a hair under the
   middle stop). */
const INK_IN_A_SELECTION = 0.25
const MIN_SELECTION_CONTRAST = 1.5
// The looks whose tone sits too close to their column to stand off it with a
// quarter of ink (measured: Heaven 1.0 : 1, Moune 1.3 : 1).
const MEASURED_SHARE_LOOKS = new Set(['heaven', 'moune'])

function channelsOf(colour) {
  return [1, 3, 5].map((at) => parseInt(colour.slice(at, at + 2), 16))
}

function selectionTone(ground, ink, share = INK_IN_A_SELECTION) {
  const [from, to] = [channelsOf(ground), channelsOf(ink)]
  const mixed = from.map((value, at) => Math.round(value + (to[at] - value) * share))
  return `#${mixed.map((value) => value.toString(16).padStart(2, '0')).join('')}`
}

// The relative luminance of three channels and the contrast of two of them,
// as WCAG 2.1 states them.
function luminance(channels) {
  const [red, green, blue] = channels.map((value) => {
    const share = value / 255
    return share <= 0.03928 ? share / 12.92 : ((share + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue
}

function contrastOf(one, other) {
  const [lighter, darker] = [luminance(one), luminance(other)].sort((a, b) => b - a)
  return (lighter + 0.05) / (darker + 0.05)
}

/* Every colour a gradient shows between its stops, sampled: each stop and
   sixteen steps between two neighbours, blended channel by channel as the
   browser blends them. The screen shows whole steps of a channel and a
   blend that lands between two of them may show the lower: a colour of the
   gradient that stands a step darker than the blend itself (measured: the
   top of Heaven's tab, 1.497 : 1 where the blend said 1.5002 : 1). So the
   blends are taken down to whole steps, the darker reading of each. */
const BLEND_STEPS = 16

function coloursBetween(stops) {
  const found = [...stops]
  for (let at = 1; at < stops.length; at += 1) {
    for (let step = 1; step < BLEND_STEPS; step += 1) {
      const share = step / BLEND_STEPS
      found.push(
        stops[at - 1].map((value, channel) =>
          Math.floor(value + (stops[at][channel] - value) * share)
        )
      )
    }
  }
  return found
}

/* The share of ink in the tone under a selection in this look: a quarter
   everywhere but in Heaven and Moune, where it is the smallest (in
   hundredths) that stands at least MIN_SELECTION_CONTRAST off every colour of
   the gradient behind the drawing. */
function selectionShare(look, ground, ink, stops) {
  if (!MEASURED_SHARE_LOOKS.has(look) || !stops.length) return INK_IN_A_SELECTION
  const shown = coloursBetween(stops)
  for (let hundredths = Math.round(INK_IN_A_SELECTION * 100); hundredths <= 100; hundredths += 1) {
    const share = hundredths / 100
    const tone = channelsOf(selectionTone(ground, ink, share))
    if (shown.every((colour) => contrastOf(tone, colour) >= MIN_SELECTION_CONTRAST)) return share
  }
  return 1
}

/* What lies under the drawing, as a colour with no opacity. The drawing
   paints a cell that carries a link or an underline on a solid ground made
   of its ground colour's red, green and blue and ignores the opacity, so
   with the ground black those cells stand on a black box. Given the colour
   of what lies under the drawing, the box has the colour of the column and
   cannot be seen; the drawing still lets the column show through
   everywhere else. Where the column lies on a gradient, the mean of the
   gradient's colours is the nearest solid one. */
function surfaceStops() {
  const frame = getComputedStyle(document.documentElement).getPropertyValue('--frame')
  return (frame.match(/#[0-9a-f]{6}\b|rgba?\([^)]*\)/gi) ?? []).map((stop) =>
    stop.startsWith('#')
      ? channelsOf(stop)
      : stop.match(/[\d.]+/g).slice(0, 3).map(Number)
  )
}

function groundBehind() {
  const stops = surfaceStops()
  if (!stops.length) return NO_GROUND
  const mean = [0, 1, 2].map((at) =>
    Math.round(stops.reduce((sum, stop) => sum + stop[at], 0) / stops.length)
  )
  return `#${mean.map((value) => value.toString(16).padStart(2, '0')).join('')}00`
}

export function theme() {
  const ink = sheetColour('--text', FALLBACK_INK)
  const ground = sheetColour('--bg', FALLBACK_GROUND)
  const share = selectionShare(currentLook(), ground, ink, surfaceStops())
  return {
    background: groundBehind(),
    foreground: ink,
    // Until the client says otherwise: it asks for the cursor in the look's
    // mark colour (OSC 12) and gives it back at its end.
    cursor: ink,
    cursorAccent: NO_GROUND,
    selectionBackground: selectionTone(ground, ink, share),
  }
}

/* The keys the page keeps for itself while the terminal has the focus:
   its own shortcuts (App.svelte). Handed back to the page, not to the
   client. */
export function pageKeepsKey(event) {
  if (event.type !== 'keydown') return false
  if (event.ctrlKey && !event.metaKey && !event.altKey && event.key === '`') return true
  return event.metaKey && !event.altKey && ['b', 'j', 'k', 'n', ','].includes(event.key)
}

/* What is typed before the client's screen is up. Until then the terminal
   the client runs in still shows every key by itself, and a key sent there
   would stand as a stray sign above the client's head. So it waits here and
   goes to the client in one piece, in the order it was typed, once the
   screen is up; from then on every key goes straight through. An Enter
   among what waited arrives as a line break, the way that terminal handed
   it on while it still took whole lines: the text stands in the input
   field and is not sent before anybody saw it there. A new client starts
   behind a gate that is shut again, with nothing left waiting.

   The interrupt key never waits: a client that hangs on its way up must
   stay as easy to stop as it was. */
const INTERRUPT = '\x03'

function typedGate(send) {
  let waiting = []
  return {
    typed(data) {
      if (waiting && data !== INTERRUPT) waiting.push(data)
      else send(data)
    },
    open() {
      if (!waiting) return
      const held = waiting.join('').replaceAll('\r', '\n')
      waiting = null
      if (held) send(held)
    },
    shut() {
      waiting = []
    },
    // Whether the client's screen is up.
    isOpen() {
      return waiting === null
    },
  }
}

/* The mode a client switches on with its first drawing: pasted text then
   arrives between two marks. */
const BRACKETED_PASTE = 2004

/* The one terminal of this page. `holder` is the element the drawing lives
   in, moved into whichever component shows it and kept when none does. */
const session = {
  xterm: null,
  fit: null,
  holder: null,
  gate: null,
  order: null,
  running: false,
  ended: false,
  // The look and the language the client was last given, at its start or
  // by a change.
  look: '',
  lang: '',
  // The theme the drawing holds, as text — to tell whether a change of the
  // page changes it.
  theme: '',
}

/* The width of the drawing's own scrollbar, which its fit takes off the box
   before it counts the columns. The fit takes it off whether the bar is
   drawn or not, and a width set to 0 counts as unset and gives these 14 px
   again; the tab draws no bar, so the holder is made this much wider than
   the room it has, and the columns that fit the room are counted. What
   reaches into the air at the column's right edge holds no column. */
const SCROLLBAR_WIDTH = 14

function endedLine() {
  return t('cli.window.ended')
}

/** Opens an address of the history in the system's browser: the window
    switch of the shell hands every address that is not the program's own on
    to it. Only http and https. */
function openAddress(address) {
  if (/^https?:\/\//i.test(address)) window.open(address, '_blank')
}

/** The drawing, built on first use and kept from then on. */
export function ensureTerminal() {
  if (session.xterm) return session
  const shell = bridge()
  const holder = document.createElement('div')
  holder.className = 'xterm-halter'
  holder.style.marginRight = `-${SCROLLBAR_WIDTH}px`
  const xterm = new Xterm({
    allowTransparency: true,
    theme: theme(),
    fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
    fontSize: 13,
    lineHeight: 1.25,
    cursorBlink: true,
    scrollback: 5000,
    // A link the client writes itself (OSC 8) opens at a click; without
    // this the drawing asks with a browser dialog.
    linkHandler: { activate: (_event, address) => openAddress(address) },
  })
  const fit = new FitAddon()
  xterm.loadAddon(fit)
  // An address in the text that carries no link opens at a click as well,
  // as in a terminal that knows links.
  xterm.loadAddon(new WebLinksAddon((_event, address) => openAddress(address)))
  xterm.open(holder)
  // A key the page keeps goes up to the page and not to the client; every
  // other key goes to the client and stops there — the page's own key
  // handler must not act on what was typed into the terminal.
  xterm.attachCustomKeyEventHandler((event) => {
    const keep = pageKeepsKey(event)
    if (!keep) event.stopPropagation()
    return !keep
  })
  try {
    const webgl = new WebglAddon()
    webgl.onContextLoss(() => webgl.dispose())
    xterm.loadAddon(webgl)
  } catch {
    /* No WebGL here: the DOM renderer draws instead. */
  }
  const gate = typedGate((data) => shell.write(data))
  const order = followTheBox({
    xterm,
    fit,
    tell: (cols, rows) => shell.resize(cols, rows),
    screenIsUp: () => session.running && !session.ended && gate.isOpen(),
    // Windows breaks nothing of the block in its console the way a terminal
    // does; there the drawing follows at once, as before.
    atOnce: system === 'windows',
  })
  xterm.onData((data) => {
    /* After the client has ended, Enter starts it again; nothing else
       typed goes anywhere. */
    if (session.ended) {
      if (data.includes('\r')) start()
      return
    }
    gate.typed(data)
  })
  /* The client's screen is up once it asks the terminal where the cursor
     stands — the first thing it does when it begins to read keys one by
     one — or, where it does not ask, once it switches bracketed paste on
     with its first drawing. Either opens the gate and is then left to the
     terminal to act on. The answer to the question is the terminal's own
     word and leaves through a gate that is open by then: it is never kept
     waiting. */
  xterm.parser.registerCsiHandler({ final: 'n' }, () => {
    gate.open()
    order.cursorAsked()
    return false
  })
  xterm.parser.registerCsiHandler({ prefix: '?', final: 'h' }, (modes) => {
    if (modes.includes(BRACKETED_PASTE)) gate.open()
    return false
  })
  xterm.onResize(({ cols, rows }) => order.resized(cols, rows))
  shell.onData((data) => xterm.write(data, order.read))
  shell.onExit(() => {
    session.running = false
    session.ended = true
    // Nobody will ask any more: the drawing takes the size it waits for.
    order.release()
    xterm.write(`\r\n${endedLine()}\r\n`)
  })
  /* A change of look or of language: the drawing's colours follow at once,
     and the client inside is told what the window shows now, so what it
     writes itself is written for the new ground and in the new language.
     Told only while it runs, and only what is another than the one it was
     given last. */
  const windowChanged = () => {
    /* Assigned only where it differs: an assignment resets what the client
       asked of the drawing — its cursor colour — and a change of language
       alone would take the cursor's accent away. */
    const next = JSON.stringify(theme())
    if (next !== session.theme) {
      session.theme = next
      xterm.options.theme = JSON.parse(next)
    }
    if (!session.running) return
    const told = {}
    const look = currentLook()
    if (look !== session.look) {
      session.look = look
      told.theme = look
    }
    if (texte.sprache !== session.lang) {
      session.lang = texte.sprache
      told.language = texte.sprache
    }
    if (told.theme || told.language) api.fensterMelden(told).catch(() => {})
  }
  new MutationObserver(windowChanged).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-modus', 'data-eigen', 'lang'],
  })
  // A look that follows the device changes no attribute: the device's own
  // preference is what tells.
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', windowChanged)
  session.xterm = xterm
  session.theme = JSON.stringify(theme())
  session.fit = fit
  session.holder = holder
  session.gate = gate
  session.order = order
  return session
}

/** Asks the shell for the client: this drawing's size, the look and the
 *  language the page shows, the chat it has open. A refusal is written
 *  where the client's own words would have stood. */
export async function start() {
  const shell = bridge()
  if (!shell || !session.xterm || session.running) return
  session.ended = false
  session.running = true
  /* The new client's keys wait for its screen — where early keys show at
     all. The terminal a client gets on Windows shows nothing before the
     client reads, and not every version of that system lets the client's
     first drawing announce itself to the page: there nothing waits. */
  session.gate.shut()
  if (system === 'windows') session.gate.open()
  session.fit.fit()
  // The client begins with the size the drawing has now.
  session.order.started(session.xterm.cols, session.xterm.rows)
  // The look and the language it is given, kept to tell them from a later
  // change.
  session.look = currentLook()
  session.lang = texte.sprache
  let answer
  try {
    answer = await shell.start({
      cols: session.xterm.cols,
      rows: session.xterm.rows,
      look: session.look,
      lang: session.lang,
      chat: zustand.aktiverChat || '',
    })
  } catch (failure) {
    answer = { error: String((failure && failure.message) || failure) }
  }
  if (answer && answer.error) {
    session.running = false
    session.ended = true
    // A missing node-pty and a missing program are the failures the shell
    // names by itself, in English; the catalogue has those sentences in the
    // interface's language.
    let said = answer.error
    if (answer.reason === 'no-pty') said = t('cli.window.pty_unavailable')
    else if (answer.reason === 'no-file') said = t('cli.window.not_found', { path: answer.path })
    session.xterm.write(`\r\n${said}\r\n${endedLine()}\r\n`)
  }
}

/** Types the paths of files dropped on the tab, the way a terminal of the
 *  computer types a dropped file. The text goes in as a paste, so the client
 *  reads it as what a dropped file is — and through the same gate as every
 *  key, so before its first screen it waits like the keys do. Only files
 *  that lie on the disk count (the bridge names none for another); answers
 *  whether anything was typed. */
export function typeDropped(files) {
  const shell = bridge()
  const { xterm } = session
  if (!shell?.pathOf || !xterm || session.ended) return false
  const text = droppedText([...files].map((file) => shell.pathOf(file)), system)
  if (!text) return false
  xterm.paste(text)
  return true
}

/** Shows the drawing in `root`: fits it, follows the size of `root`, starts
 *  the client where none is running or has ended, and hands back the way
 *  to take the drawing out again. */
export function show(root) {
  const { xterm, order, holder } = ensureTerminal()
  // The view that stands on the last row when the drawing is taken in again
  // stands there when it is shown.
  const atBottom = order.atBottom()
  root.appendChild(holder)
  const watcher = new ResizeObserver(() => {
    if (holder.isConnected) order.follow()
  })
  watcher.observe(root)
  order.follow()
  if (atBottom) order.pin()
  if (!session.running && !session.ended) start()
  xterm.focus()
  return () => {
    watcher.disconnect()
    if (holder.parentNode === root) root.removeChild(holder)
  }
}
