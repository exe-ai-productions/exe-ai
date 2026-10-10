/*
  The look and the layout of the interface, kept by the program.

  All of this used to live in `localStorage`: the code colours, the bubble
  colour, where the two panels stand, light or dark, and which model was
  last in use. That meant a different truth in every browser profile and
  none at all for the program itself — a second window on the same service
  started over at the defaults, and nothing outside the browser could ever
  see or ship these choices.

  They live in the settings cascade now (`app/db/repositories/einstellungen.py`),
  under the checkers in `app/darstellungwahl.py`, `app/layoutwahl.py`,
  `app/moduswahl.py` and `app/modellwahl.py`.

  Two things this module exists for:

  WHOLE OBJECTS. A scope holds one row per setting, and writing that row
  replaces it. Merging happens BETWEEN scopes, not inside one — so sending
  only the key that changed would drop every sibling key from `global`.
  This module therefore keeps the last known full object per setting and
  writes all of it, whichever half of the app touched one field.

  ONE WRITE, NOT ONE PER PIXEL. Both panel widths come from a drag, and the
  bubble colour from a colour input: those fire on every mouse move. Against
  `localStorage` that was free; against the service it would be a request per
  pixel. Writes are collected and go out once the hand stops.

  And the thing that follows from both: NOTHING IS WRITTEN BEFORE THE FIRST
  READ CAME BACK. Reading is a request now, and the app does not stand still
  while it is in flight — the work rail offers a module to itself within the
  first frames. Such an early change used to go out on top of the DEFAULTS,
  which then replaced the whole row and took the sibling keys with it: the
  sidebar came back at its default width because the rail had changed module. Early
  changes are therefore held, layered onto what the read brings, and sent
  once. A read that fails holds them forever rather than writing defaults
  over settings this window never got to see.
*/

import { api } from './api.js'

export const VORGABE_DARSTELLUNG = {
  codefarben: 'exe',
  blasenfarbe: '',
  /* Per look (hell, dunkel, darkmatter, heaven): the colours, hue and angle
     the user set for the frame's gradient. Empty means every look draws its
     own. */
  verlauf: {},
  /* The chat layout from the layout mode, only what differs from the
     factory values (lib/chatlayout.js). Empty: the factory layout. */
  chat: {},
}

/* Where nothing is stored, both panels stand folded to their bars of signs:
   a fresh installation opens in its basic state. The service answers with
   what is stored and nothing else, so these are the values in effect then;
   its own copy (app/layoutwahl.py) is kept equal to them. */
export const VORGABE_LAYOUT = {
  leiste_offen: false,
  leiste_modul: 'terminal',
  leiste_breite: 314,
  seitenleiste_zu: true,
  seitenleiste_breite: 314,
}

/* A fresh installation opens in Exe, the grey dark look — the same default
   app/moduswahl.py hands out. */
export const VORGABE_MODUS = 'dunkel'

const SCHLUESSEL = ['darstellung', 'layout', 'modus', 'modell_zuletzt']

/* The last full object per setting — the base every partial change is
   written on top of. Seeded from the service by `anzeigeLaden()`. */
const stand = {
  darstellung: { ...VORGABE_DARSTELLUNG },
  layout: { ...VORGABE_LAYOUT },
}

/* Has the first read come back? Until it has, nothing goes out. */
let geladen = false

/* What changed while the first read was still in flight. Layered on top of
   what that read brings, so a change nobody could see yet is not lost — and
   not written on top of defaults either. */
const frueh = { darstellung: {}, layout: {}, modus: null, modell_zuletzt: null }

/* Long enough that a drag becomes one write, short enough that nobody
   closes the window in between. */
const VERZOEGERUNG = 300

const offen = new Map()
let uhr = null

function schreiben() {
  uhr = null
  for (const [schluessel, wert] of offen) {
    api.einstellungSetzen('global', schluessel, wert).catch(() => {})
  }
  offen.clear()
}

function merken(schluessel, wert) {
  offen.set(schluessel, wert)
  if (uhr) clearTimeout(uhr)
  uhr = setTimeout(schreiben, VERZOEGERUNG)
}

/* Whatever is still waiting when the page goes away goes out now — the last
   drag of a session must not be the one that is lost. `pagehide` is the
   event that also fires when a tab is put aside rather than closed, which
   `beforeunload` does not reliably do. */
if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', () => {
    if (uhr) clearTimeout(uhr)
    if (offen.size) schreiben()
  })
}

export function darstellungSpeichern(teil) {
  Object.assign(stand.darstellung, teil)
  if (!geladen) {
    Object.assign(frueh.darstellung, teil)
    return
  }
  merken('darstellung', { ...stand.darstellung })
}

export function layoutSpeichern(teil) {
  Object.assign(stand.layout, teil)
  if (!geladen) {
    Object.assign(frueh.layout, teil)
    return
  }
  merken('layout', { ...stand.layout })
}

/* The one value that is also kept in the browser: the chosen look, under
   this key, so the page can paint in it before the service has answered
   (index.html reads it in a script that runs before the first paint).
   Everything else stays with the service alone. A browser that refuses
   storage just paints the root look first, as before. */
export const MODUS_SCHLUESSEL = 'exe-modus'

function modusVormerken(modus) {
  try {
    localStorage.setItem(MODUS_SCHLUESSEL, modus)
  } catch {
    /* No storage, no mirror. */
  }
}

export function modusSpeichern(modus) {
  modusVormerken(modus)
  if (!geladen) {
    frueh.modus = { modus }
    return
  }
  merken('modus', { modus })
}

export function modellSpeichern(id) {
  if (!geladen) {
    frueh.modell_zuletzt = { id }
    return
  }
  merken('modell_zuletzt', { id })
}

/**
 * Everything the interface needs to draw itself, in one read.
 *
 * Returns null if the service cannot be reached — the caller then keeps the
 * defaults it started with rather than showing half a look.
 */
export async function anzeigeLaden() {
  let daten
  try {
    daten = await api.einstellungAufgeloestViele(SCHLUESSEL)
  } catch {
    return null
  }
  /* What the service says, with anything that changed while the read was in
     flight on top of it — the app does not stand still for a request. */
  const darstellung = {
    ...VORGABE_DARSTELLUNG, ...(daten.darstellung?.wert || {}), ...frueh.darstellung,
    /* The frame choices are one map per look (zustand's `verlauf`): a look
       changed while the read was in flight must not erase the other looks
       the service just handed out — the shallow spread above would. */
    verlauf: {
      ...(daten.darstellung?.wert?.verlauf || {}),
      ...(frueh.darstellung.verlauf || {}),
    },
  }
  const layout = { ...VORGABE_LAYOUT, ...(daten.layout?.wert || {}), ...frueh.layout }
  const modus = frueh.modus?.modus || daten.modus?.wert?.modus || VORGABE_MODUS
  modusVormerken(modus)
  const modell = frueh.modell_zuletzt?.id || daten.modell_zuletzt?.wert?.id || ''

  /* Seed the base for later partial writes, or the first change would write
     the defaults over everything the service just handed out. */
  stand.darstellung = { ...darstellung }
  stand.layout = { ...layout }
  geladen = true

  /* Now, and only now, what was held may go out. */
  if (Object.keys(frueh.darstellung).length) merken('darstellung', { ...darstellung })
  if (Object.keys(frueh.layout).length) merken('layout', { ...layout })
  if (frueh.modus) merken('modus', frueh.modus)
  if (frueh.modell_zuletzt) merken('modell_zuletzt', frueh.modell_zuletzt)

  return { darstellung, layout, modus, modell }
}
