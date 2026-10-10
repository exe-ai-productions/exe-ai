/*
  The assignable microphone key: how a combination is written, read,
  recorded, recognised and shown, and how the switched-on keyboard layout
  is read.
  Pure functions and two small state machines besides that one reading, no
  imports, so the tests run this very file in node.

  A combination is stored as text: the modifiers in a fixed order, then at
  most one key, joined by "+" — "Meta+Alt" (the works key, Cmd + Option) or
  "Meta+Shift+KeyD". The key is the event's `code`, which names the place
  on the keyboard and not the letter the layout prints on it: the same
  place is recognised whatever layout is switched on, and the layout only
  decides whether the program already answers to what it writes there.

  Whether a combination is one the program already has, and how its key is
  shown, also goes by the character the switched-on layout prints on the
  key (`navigator.keyboard.getLayoutMap()`, read in `readLayout` and passed
  in as `layout`): on a German layout "+" sits on the code `BracketRight`,
  not on `Equal` as on a US one. The comparison by code stays as well,
  because a stored combination is read back without a layout (splitCombo);
  the recogniser asks for the current reading at every press, since a key
  that writes a shortcut of the program's on the switched-on layout must
  fire nothing.

  A combination of modifiers alone fires when they are let go, and only
  when no other key was pressed while they were held: Cmd + Option + I
  opens the developer tools and must not also start a dictation.
*/

export const DEFAULT_KEY = 'Meta+Alt'

// The order a combination is written and shown in.
const MODIFIERS = ['Meta', 'Control', 'Alt', 'Shift']

const SYMBOLS = { Meta: '⌘', Control: '⌃', Alt: '⌥', Shift: '⇧' }

/** The system a browser says it runs on — 'mac', 'windows' or 'other' —
    from the platform it names (`navigator.userAgentData.platform` or
    `navigator.platform`). What stands beside a shortcut goes by it: off the
    Mac the keys carry other names, and the shell's menu answers to other
    keys. A browser that names nothing is taken for a Mac. */
export function systemOf(platform) {
  if (!platform || /^(mac|iphone|ipad|ipod)/i.test(platform)) return 'mac'
  return /^win/i.test(platform) ? 'windows' : 'other'
}

// The `code` of every modifier key, left and right, and the modifier it is.
const MODIFIER_OF = {
  MetaLeft: 'Meta', MetaRight: 'Meta', OSLeft: 'Meta', OSRight: 'Meta',
  ControlLeft: 'Control', ControlRight: 'Control',
  AltLeft: 'Alt', AltRight: 'Alt',
  ShiftLeft: 'Shift', ShiftRight: 'Shift',
}

/** The modifier a key event's `code` stands for, or null. */
export function modifierOf(code) {
  return MODIFIER_OF[code] ?? null
}

/** A stored combination taken apart: `{ mods, key }`, or null when the text
    is no combination at all. The shape alone — whether the program already
    has it is a question of its own (`inUse`), because such a key is still
    named and marked while it stands, instead of going blank. */
export function splitCombo(text) {
  if (typeof text !== 'string' || !text) return null
  const parts = text.split('+')
  const mods = parts.filter((part) => MODIFIERS.includes(part))
  const rest = parts.filter((part) => !MODIFIERS.includes(part))
  if (rest.length > 1 || new Set(mods).size !== mods.length) return null
  const key = rest[0] ?? null
  return wellFormed(mods, key) ? { mods: ordered(mods), key } : null
}

/** A stored combination this module can recognise: `{ mods, key }`, or null
    when the text is no combination or one the program already has on
    `system` — to those the microphone does not answer. */
export function parseCombo(text, system = 'mac') {
  const combo = splitCombo(text)
  return combo && isUsable(combo.mods, combo.key, null, system) ? combo : null
}

/** A combination as stored text, the modifiers in their fixed order. */
export function writeCombo(mods, key = null) {
  return [...ordered(mods), ...(key ? [key] : [])].join('+')
}

/* The shortcuts the program already has (the page's and the shell menu's,
   the rows the Shortcuts page lists): a microphone key on one of them would
   run both. Written the way a Mac has them, with `Mod` for the modifier
   they hang on: Cmd on a Mac, Control everywhere else — the shell's
   accelerators read CommandOrControl (fenster-electron/main.js). */
const SHORTCUTS = [
  'Mod+KeyN', 'Mod+Comma', 'Mod+KeyB', 'Mod+KeyJ', 'Mod+KeyK', 'Mod+Shift+KeyM',
  'Mod+KeyR', 'Mod+Alt+KeyI', 'Mod+Equal', 'Mod+Shift+Equal', 'Mod+Minus',
  'Mod+Digit0', 'Mod+KeyM',
  'Mod+KeyW', 'Mod+KeyQ', 'Mod+KeyZ', 'Mod+Shift+KeyZ', 'Mod+KeyX', 'Mod+KeyC',
  'Mod+KeyV', 'Mod+KeyA', 'Mod+KeyH', 'Mod+Alt+KeyH', 'Mod+Alt+Shift+KeyV',
]

/* Where the shell's menu answers differently off the Mac, by system: the
   keys it answers to there, or `null` where it has no such entry — the
   roles of the menu carry their keys per system. The developer tools and
   pasting without the style take Shift instead of Option, Redo is
   Control + Y on Windows, and Quit, Hide and Hide Others stand in the
   program's own menu, which only a Mac has. */
const ELSEWHERE = {
  'Mod+Alt+KeyI': { windows: 'Mod+Shift+KeyI', other: 'Mod+Shift+KeyI' },
  'Mod+Alt+Shift+KeyV': { windows: 'Mod+Shift+KeyV', other: 'Mod+Shift+KeyV' },
  'Mod+Shift+KeyZ': { windows: 'Mod+KeyY' },
  'Mod+KeyQ': { windows: null, other: null },
  'Mod+KeyH': { windows: null, other: null },
  'Mod+Alt+KeyH': { windows: null, other: null },
}

/* The taken shortcuts of each system, as stored combinations — made once
   per system, on the first question about it. */
const TAKEN = new Map()

function takenOn(system) {
  if (!TAKEN.has(system)) {
    const mod = system === 'mac' ? 'Meta' : 'Control'
    TAKEN.set(
      system,
      new Set(
        SHORTCUTS.map((shortcut) =>
          Object.hasOwn(ELSEWHERE[shortcut] ?? {}, system) ? ELSEWHERE[shortcut][system] : shortcut,
        )
          .filter(Boolean)
          .map((shortcut) => shortcut.replace('Mod', mod)),
      ),
    )
  }
  return TAKEN.get(system)
}

/* Which of them are the page's own: those answer to Control as well as to
   Cmd on every system (frontend/src/App.svelte), so both combinations of
   theirs are taken. The shell answers to the one modifier of its system
   alone, so the other one with one of its keys — Control + R on a Mac, the
   Windows key + R off it — is not the program's and is not refused here. */
const PAGE_SHORTCUTS = new Set(['Meta+KeyN', 'Meta+Comma', 'Meta+KeyB', 'Meta+KeyJ', 'Meta+KeyK'])

/* The US-layout code of every character a taken shortcut is written with:
   Zoom In answers to "+" as well as to "=", Zoom Out to "-" (the zoom
   roles in fenster-electron/main.js). On a US keyboard "+" is Shift and
   "=" together, so Cmd + Shift + "=" is Zoom In as well — and a key
   writing "+" under another layout lands on that same taken shortcut. */
const CODE_OF_CHARACTER = { ',': 'Comma', '=': 'Equal', '+': 'Equal', '-': 'Minus' }

/** The character a key writes on `layout`, or null without one. */
function characterOf(code, layout) {
  return layout?.get(code) || null
}

/** The US-layout code of the character a key writes on `layout` — the
    name it is compared with the taken shortcuts under — or null when the
    layout has nothing for it or the character is in no taken shortcut. */
function codeOfCharacter(key, layout) {
  const character = characterOf(key, layout)
  if (!character) return null
  if (/^[a-z]$/i.test(character)) return `Key${character.toUpperCase()}`
  if (/^[0-9]$/.test(character)) return `Digit${character}`
  return CODE_OF_CHARACTER[character] ?? null
}

/** Whether a combination has the shape of a microphone key: a key needs Cmd
    or Control with it — with Shift or Option alone it is typing (a capital
    letter, a €) — and modifiers alone need at least two, or every capital
    letter would fire them. */
function wellFormed(mods, key) {
  if (!key) return mods.length >= 2
  return (mods.includes('Meta') || mods.includes('Control')) && !modifierOf(key)
}

/** Whether a combination can serve as the microphone key: the shape above,
    and no shortcut the program has on `system` ('mac', 'windows' or
    'other') on it — by place and by the character the key writes under
    `layout` (`taken`). */
export function isUsable(mods, key, layout = null, system = 'mac') {
  return wellFormed(mods, key) && !taken(mods, key, layout, system)
}

/** Whether the program already answers to this press on `system` — by the
    place of the key (`code`) or by the character it writes under `layout`.

    The Keyboard API names the character a key writes WITHOUT Shift; what a
    shifted press writes it does not say, so with Shift held only the place
    counts — and the shifted US press that is Zoom In stands in the list by
    its place alone ("Meta+Shift+Equal"). */
function taken(mods, key, layout, system) {
  const asCmd = [...new Set(mods.map((mod) => (mod === 'Control' ? 'Meta' : mod)))]
  const written = mods.includes('Shift') ? null : codeOfCharacter(key, layout)
  const ofSystem = takenOn(system)
  return [key, written]
    .filter(Boolean)
    .some(
      (code) =>
        ofSystem.has(writeCombo(mods, code)) || PAGE_SHORTCUTS.has(writeCombo(asCmd, code)),
    )
}

/** Whether a combination is one the program already has on `system` under
    `layout` — the state the key field marks beside itself. A combination
    recorded on one layout can fall on a shortcut of the program's on
    another: "]" recorded under a US layout writes "+" (Zoom In) on a German
    one, and the program's shortcut wins then, so the field stands marked
    until a new key is chosen. Text that is no combination at all (or empty)
    is nothing of the program's. */
export function inUse(text, layout = null, system = 'mac') {
  const combo = splitCombo(text)
  return combo ? !isUsable(combo.mods, combo.key, layout, system) : false
}

/** Keys as they stand beside a shortcut. Without `names` the way a Mac
    menu writes them: the sign of every modifier, in the order given, and
    the key behind them with nothing between — "⌘⌥I", "⇧⌘Z". With `names`
    (the word printed on each modifier key, by modifier) the way they are
    written everywhere else: the words in the fixed order, then the key,
    joined by "+" — "Ctrl+Shift+I". `Mod` stands for the modifier the
    program's own shortcuts hang on: Cmd on a Mac, Control off it. */
export function showKeys(mods, key = '', names = null) {
  const actual = mods.map((mod) => (mod === 'Mod' ? (names ? 'Control' : 'Meta') : mod))
  if (!names) return actual.map((mod) => SYMBOLS[mod]).join('') + key
  return [...ordered(actual).map((mod) => names[mod]), ...(key ? [key] : [])].join('+')
}

/** How a combination is shown: "⌘⌥", "⌘⇧D" — with a `layout`, the key as
    the character it writes there ("⌘+" for `BracketRight` on a German one),
    and with `names` in the words printed on the keys ("Win+Alt", showKeys).
    A combination the program already has is named as well: the field shows
    the key it stands on and marks it (`inUse`), the way a shortcut list
    does. */
export function showCombo(text, layout = null, names = null) {
  const combo = splitCombo(text)
  if (!combo) return ''
  return showKeys(combo.mods, combo.key ? keyName(combo.key, layout) : '', names)
}

function keyName(code, layout) {
  const character = characterOf(code, layout)
  if (character) {
    if (character === '-') return '−'
    // "ß" would turn into "SS": only a capital of one character is taken.
    const capital = character.toUpperCase()
    return capital.length === 1 ? capital : character
  }
  if (/^Key[A-Z]$/.test(code)) return code.slice(3)
  if (/^Digit[0-9]$/.test(code)) return code.slice(5)
  return code
}

function ordered(mods) {
  return MODIFIERS.filter((mod) => mods.includes(mod))
}

/*
  The recogniser. It is fed every keydown and keyup of the window
  (`{ code, repeat }`) and answers true on exactly the event that is the
  microphone key.

  For modifiers alone: it keeps which modifiers are held and whether any
  other key was pressed since the first of them went down. When one is let
  go and, at that moment, exactly the combination's modifiers were held and
  nothing else came between, that release is the key. For a combination
  with a key: the keydown of that key, with exactly its modifiers held, not
  repeated by holding it. `system` says whose shortcuts the combination
  must stay off (isUsable).
*/
export function recogniser(text, currentLayout = () => null, system = 'mac') {
  const combo = parseCombo(text, system)
  const held = new Set()
  let spoiled = false

  function matches() {
    return combo.mods.length === held.size && combo.mods.every((mod) => held.has(mod))
  }

  return {
    down({ code, repeat = false }) {
      if (!combo) return false
      const mod = modifierOf(code)
      if (mod) {
        held.add(mod)
        // A modifier the combination does not have spoils the press, even
        // if it is let go again first.
        if (!combo.mods.includes(mod)) spoiled = true
        return false
      }
      const hit = Boolean(combo.key) && code === combo.key && !repeat && matches()
      // Another key pressed while modifiers are held spoils a press of
      // modifiers alone; one typed with nothing held is plain typing.
      if (held.size > 0) spoiled = true
      // The layout can be switched while the window stands open, and the
      // key this combination names can then write a character the program
      // has a shortcut on: "]" recorded under a US layout writes "+" on a
      // German one, which is Zoom In. The program's shortcut wins then and
      // this press starts no dictation — until a new key is chosen; the
      // key field says so while it stands.
      return hit && isUsable(combo.mods, code, currentLayout(), system)
    },
    up({ code }) {
      if (!combo) return false
      const mod = modifierOf(code)
      if (!mod) return false
      const hit = !combo.key && !spoiled && matches()
      held.delete(mod)
      // Letting go of the first modifier ends the press: the rest being let
      // go after it is no second press.
      if (hit) spoiled = true
      if (held.size === 0) spoiled = false
      return hit
    },
    /** Forgets what is held — after the window lost focus, whose keyups
        never arrive. */
    reset() {
      held.clear()
      spoiled = false
    },
  }
}

/* The switched-on keyboard layout, read where the browser offers it: the
   map from the `code` of a key to the character it writes there
   (`navigator.keyboard.getLayoutMap()`, the Keyboard API). The one reading
   for everything that needs it — the key field, the settings overview and
   the recogniser all ask here, so a key is shown and judged by the same
   character everywhere. Read again at every focus of the window: the
   layout can be switched while the page stands open.

   Answers null where there is no such map to have (no Keyboard API, a page
   not served securely, a refused promise): then every combination goes by
   the code alone, as it did before there were layouts to ask about.
*/
export function readLayout() {
  try {
    return Promise.resolve(navigator.keyboard?.getLayoutMap?.()).then(
      (map) => map ?? null,
      () => null,
    )
  } catch {
    return Promise.resolve(null)
  }
}

/*
  Recording a new combination in the key field: fed the same events, it
  answers the combination once it is complete — a key pressed with
  modifiers held, or modifiers let go without a key between — and null
  until then or when the press is no combination the key may be.
  `currentLayout` answers the layout as for isUsable at each key press: the
  map may arrive only after recording began. `system` is the one whose
  shortcuts a recorded key must stay off.
*/
export function recorder(currentLayout = () => null, system = 'mac') {
  const held = new Set()
  let pressed = new Set()
  let spoiled = false
  return {
    down({ code }) {
      const mod = modifierOf(code)
      if (mod) {
        held.add(mod)
        pressed.add(mod)
        return null
      }
      // A key without a code (some input methods, Fn) names nothing that
      // could be recognised again; with nothing held it is a stray key.
      if (!code || held.size === 0) return null
      spoiled = true
      const mods = [...held]
      return isUsable(mods, code, currentLayout(), system) ? writeCombo(mods, code) : null
    },
    up({ code }) {
      const mod = modifierOf(code)
      if (!mod) return null
      held.delete(mod)
      if (held.size > 0) return null
      const mods = [...pressed]
      const wasSpoiled = spoiled
      pressed = new Set()
      spoiled = false
      return !wasSpoiled && isUsable(mods, null, null, system) ? writeCombo(mods) : null
    },
  }
}
