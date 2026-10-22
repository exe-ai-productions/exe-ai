/*
  The window buttons that stand in the page.

  On the Mac the shell leaves the system's top bar out of the window and puts
  the three window buttons over the page (fenster-electron/topbar.js). The
  page makes room for them: the first row of the sidebar carries them in
  front of the mark, and the narrow bar of signs, 20 px wider than elsewhere,
  carries them over its signs. Where the shell says nothing (a browser, the
  phone, Windows, Linux) there is no room to make and every number here is
  the one it always was.

  One home for the facts, so the sidebar, the window body and the right
  column cannot disagree about them.
*/
import { SEITENLEISTE_SCHMAL_ABFRAGE } from './zustand.svelte.js'

/* Whether the window buttons stand in the page. */
export const windowButtonsInPage = typeof window !== 'undefined' && Boolean(window.exeHuelle?.topBar)

/* The width of the narrow bar of signs: 52 px, and 72 where the three window
   buttons stand over it. */
export const RAIL_WIDTH = windowButtonsInPage ? 72 : 52

/* How far the first row of the open sidebar keeps free in front of its mark
   for the buttons, in px: the left padding of the row. Elsewhere the 18 px
   the row always had. */
export const MARK_LEFT = windowButtonsInPage ? 86 : 18

/* How far down the first sign of the narrow bar stands so that it clears the
   row of buttons: the bar's top padding. Elsewhere the 12 px it always had. */
export const RAIL_TOP = windowButtonsInPage ? 58 : 12

/* The height of the strip at the top of the narrow bar that grabs the window,
   up to the first sign. */
export const GRAB_HEIGHT = 58

const NARROW = typeof window !== 'undefined' ? window.matchMedia?.(SEITENLEISTE_SCHMAL_ABFRAGE) : null

export const narrow = $state({ now: Boolean(NARROW?.matches) })
NARROW?.addEventListener?.('change', (event) => {
  narrow.now = event.matches
})

/* Tells the shell whether the narrow bar of signs stands instead of the open
   sidebar — folded by hand, or the window too narrow for anything else — so
   that it puts the buttons where they fit. */
export function reportRail(folded) {
  if (!windowButtonsInPage) return
  window.exeHuelle?.sidebarFolded?.(Boolean(folded))
}
