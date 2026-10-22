/* The shape of the tool surface beside the chat, as the views read it.

   One width decides how a view is laid out: at its narrowest the surface
   asks for tighter rows. It is read off the surface's own width, which the
   person drags (`leiste.breite`) — a container query would say the same
   without any script, but a containing box turns every fixed window inside
   it (the
   report window, the confirmation) into one that is placed against the
   surface instead of the screen.

   On a narrow screen the surface is a sheet of the whole width and the width
   it remembers says nothing about it: the tighter rows do not apply there. */
import { BREITE_MIN, leiste } from './arbeitsleiste.svelte.js'
import { SEITENLEISTE_SCHMAL_ABFRAGE } from './zustand.svelte.js'

/* The narrowest the surface can be dragged to. */
export const BREITE_ENG = BREITE_MIN

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
}
