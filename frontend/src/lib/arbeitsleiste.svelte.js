/*
  The work rail on the right: which module is showing, how wide it is, and
  whether it may open by itself.

  The rail started as one window for the terminal. It is a rail with seven
  modules now — preview, agents, schedules, terminal, CLI, pictures, doc
  folder — and the rule that made the terminal work is the rule they all
  follow: it opens
  itself when its module has something to show, and whoever closes it
  during that is not asked again for it.

  The buttons stand in the column's own row of signs and are ALWAYS
  visible: at its foot while it is open, as a bar of signs while it is
  folded (Arbeitsleiste.svelte, ToolSigns.svelte) — the same anatomy
  as the sidebar on the left. One tool shows at a time; a click on another
  sign swaps it, and a click on the sign of the tool showing folds the
  column.

  Everything here is per chat: switching chats on the left switches runs,
  preview tabs and terminal history with it. (The note was the one thing
  that belonged to the person rather than the conversation; it is gone as a
  module, and its place holds the doc folder now.)
*/

import { VORGABE_LAYOUT, layoutSpeichern } from './anzeige.js'

/* Seven 40px signs of the row at the column's foot, six 10px gaps and 12px
   either side: no sign of the row ever has to shrink. */
export const BREITE_MIN = 364
const BREITE_MAX = 900

/* The CLI is back as a tool of its own: the terminal client `exe` running
   in the window, beside the terminal that logs the chat's tool calls. The
   agents and the schedules are two tools, each with its own button. The
   notes are gone as a tool: the doc folder took their place and stands as
   one of its own now, right beside the pictures. A layout remembered on a
   tool that is gone opens the tool that holds it today (`leisteAnwenden`). */
export const MODULE = ['terminal', 'cli', 'vorschau', 'bilder', 'docfolder', 'agenten', 'cronjobs']
const FRUEHER = { notiz: 'docfolder' }

export const leiste = $state({
  /* Open, closed and which module: remembered like the sidebar's state on
     the left. Somebody who works with the terminal open should find it open
     after a restart, not have to fetch it back every time. */
  offen: VORGABE_LAYOUT.leiste_offen,
  modul: VORGABE_LAYOUT.leiste_modul,
  /* The width it opens at: remembered, and wider is one drag away. */
  breite: VORGABE_LAYOUT.leiste_breite,
  zieht: false,
  /* Which module the user closed the rail on. It stays closed for that one
     until its next fresh occasion — a rail that pops back up is a rail
     people learn to hate. */
  nichtAufdraengen: '',
  /* Counts the tools the user asked for — a sign in the row, or a click
     elsewhere that wants one tool. The picture studio reads it: while it
     shows its details in this column, a tool asked for takes their place. */
  gewaehlt: 0,
})

export function breiteSetzen(px) {
  leiste.breite = Math.round(Math.min(BREITE_MAX, Math.max(BREITE_MIN, px)))
  layoutSpeichern({ leiste_breite: leiste.breite })
}

/* The rail as the service hands it out — set without writing it straight
   back, or the first start would save the defaults over what was just read.
   `nichtAufdraengen` stays out of it on purpose: which module somebody
   dismissed is about this sitting, not about the next one. */
export function leisteAnwenden(wert) {
  leiste.offen = wert.leiste_offen
  const modul = FRUEHER[wert.leiste_modul] ?? wert.leiste_modul
  leiste.modul = MODULE.includes(modul) ? modul : 'terminal'
  leiste.breite = Math.round(Math.min(BREITE_MAX, Math.max(BREITE_MIN, wert.leiste_breite)))
}

/**
 * A click on a sign in the column's row: that tool shows, and a folded
 * column opens on it. The sign of the tool already showing folds the
 * column, the same way the head's button does — one way in, one way out.
 * `covered` says that something else lies over the tool in the column (the
 * picture studio's details): the tool is then not showing, and the click
 * brings it forward instead.
 */
export async function modulWaehlen(name, covered = false) {
  if (!MODULE.includes(name)) return
  leiste.gewaehlt += 1
  if (leiste.offen && leiste.modul === name && !covered) {
    await schliessen()
    return
  }
  zeigenRoh(name)
  leiste.nichtAufdraengen = ''
}

/** Something the user clicked asks for exactly this tool: it comes to the
 *  front, and one already showing stays. */
export async function moduleShow(name) {
  if (!MODULE.includes(name)) return
  leiste.gewaehlt += 1
  zeigenRoh(name)
  leiste.nichtAufdraengen = ''
}

/* Shows a tool, opening the column on it. */
function zeigenRoh(name) {
  leiste.modul = name
  leiste.offen = true
  merken()
}

function merken() {
  layoutSpeichern({ leiste_offen: leiste.offen, leiste_modul: leiste.modul })
}

/** ⌘J, the mirror of ⌘B on the left: the column folds and unfolds on
 *  the tool it was showing. */
export async function schalten() {
  if (leiste.offen) await schliessen()
  else oeffnen()
}

/** The column folds to its bar of signs — the head's button, ⌘J, the seam
 *  dragged shut. */
export async function schliessen() {
  leiste.offen = false
  leiste.nichtAufdraengen = leiste.modul
  merken()
}

export function oeffnen() {
  leiste.offen = true
  leiste.nichtAufdraengen = ''
  merken()
}

/** A view that needs the column for a while (the picture studio) opens it
 *  without remembering it, and gets back whether it stood open before. */
export function zeitweiseOeffnen() {
  const vorher = leiste.offen
  leiste.offen = true
  return vorher
}

/**
 * A module has something new to show. It comes to the front unless the user
 * shut the rail on exactly this module.
 */
export function anbieten(name) {
  if (!MODULE.includes(name)) return
  /* A tool the user folded the column on does not push itself back in. */
  if (leiste.nichtAufdraengen === name) return
  zeigenRoh(name)
}
