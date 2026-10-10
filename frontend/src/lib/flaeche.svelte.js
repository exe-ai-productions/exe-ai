/* The shape of the tool surface beside the chat, as the views read it.

   Two widths decide how a view is laid out: at its narrowest the surface
   asks for tighter rows, and from a certain width a view may stand in two
   columns. Both are read off the surface's own width, which the person drags
   (`leiste.breite`) — a container query would say the same without any
   script, but a containing box turns every fixed window inside it (the
   report window, the confirmation) into one that is placed against the
   surface instead of the screen.

   On a narrow screen the surface is a sheet of the whole width and the width
   it remembers says nothing about it: neither shape applies there. */
import { BREITE_MIN, leiste } from './arbeitsleiste.svelte.js'
import { SEITENLEISTE_SCHMAL_ABFRAGE } from './zustand.svelte.js'

/* The narrowest the surface can be dragged to, and the width from which a
   view stands in two columns. */
export const BREITE_ENG = BREITE_MIN
export const BREITE_ZWEI = 780

/* The narrow window: the same width at which the sidebar becomes a drawer. */
const BLATT = typeof window !== 'undefined' ? window.matchMedia(SEITENLEISTE_SCHMAL_ABFRAGE) : null
let blatt = $state(BLATT?.matches ?? false)
BLATT?.addEventListener('change', (e) => {
  blatt = e.matches
})

export const flaeche = {
  get eng() {
    return !blatt && leiste.breite <= BREITE_ENG
  },
  get zweispaltig() {
    return !blatt && leiste.breite >= BREITE_ZWEI
  },
}
