/* The columns give way when the window shrinks: the chat keeps its minimum
   width, the right column folds first, then the left one, and each comes
   back by itself once the room is there again.

   Folding here is not the person's choice and is never written to the
   saved layout: it changes the live state only, and remembers which column
   it folded (`held`) so that only those come back. A column the person
   opens meanwhile is theirs again — it is let go of, and the other one
   gives way instead. Below the drawer's width neither column sits beside
   the chat (the sidebar is a drawer, the tools a sheet), so nothing folds
   there and nothing comes back. The picture studio asks for both columns
   open and they give way for it like for the chat; what it folded for
   room is handed back and forth through `foldedForRoom` and
   `forgetFolded`. */
import { leiste } from './arbeitsleiste.svelte.js'
import { zustand, istSeitenleisteSchmal } from './zustand.svelte.js'
import { openColumns } from './columnRoom.js'

/* Read by `fitColumns`, which therefore runs again on every resize. */
let windowWidth = $state(typeof window === 'undefined' ? 0 : window.innerWidth)

/* The columns this module folded, and has not yet given back. */
const held = { left: false, right: false }

/* The column the person opened while room was short: it gives way last,
   for as long as it stays open and something is still folded for it. */
let last = null

/** Keeps `windowWidth` current; returns the way to stop. */
export function watchWindowWidth() {
  const take = () => { windowWidth = window.innerWidth }
  take()
  window.addEventListener('resize', take)
  return () => window.removeEventListener('resize', take)
}

/** The columns folded here for room and not yet given back. */
export function foldedForRoom() {
  return { left: held.left, right: held.right }
}

/** Lets go of what was folded for room: the column stays as it stands and
 *  does not come back by itself. `side` names one column, none names both. */
export function forgetFolded(side) {
  if (side !== 'right') held.left = false
  if (side !== 'left') held.right = false
  if (!held.left && !held.right) last = null
}

/** Folds and unfolds the columns to fit the window. Reads the live state,
 *  so inside an effect it runs again whenever a width or a column changes. */
export function fitColumns() {
  const width = windowWidth
  if (istSeitenleisteSchmal()) return

  const leftNow = !zustand.seitenleisteEingeklappt
  const rightNow = leiste.offen
  // Open although folded here: the person opened it, it is theirs again.
  if (held.left && leftNow) { held.left = false; last = 'left' }
  if (held.right && rightNow) { held.right = false; last = 'right' }
  if ((last === 'left' && !leftNow) || (last === 'right' && !rightNow)) last = null

  const want = { left: leftNow || held.left, right: rightNow || held.right }
  const leftWidth = zustand.seitenBreite
  const rightWidth = leiste.breite
  const open = openColumns({
    windowWidth: width, leftWidth, rightWidth, left: want.left, right: want.right, last,
  })

  if (want.left && !open.left) { zustand.seitenleisteEingeklappt = true; held.left = true }
  else if (open.left && held.left) { zustand.seitenleisteEingeklappt = false; held.left = false }
  if (want.right && !open.right) { leiste.offen = false; held.right = true }
  else if (open.right && held.right) { leiste.offen = true; held.right = false }
  if (!held.left && !held.right) last = null
}
