/* The picture studio and the two columns beside the chat.

   The studio carries its settings in both columns: a folded sidebar
   unfolds for it and the tools column opens, and neither is written to the
   saved layout — it is the studio's, not the person's. Closing the studio
   puts the columns back the way the person had them.

   Where the columns stand beside the chat the window may be too narrow for
   both: they give way for the studio like they do for the chat
   (columnRoom.svelte.js) — the right one first, then the left — and come
   back by themselves with the room. What the person had before the studio
   is kept apart from that, so a column the window folded is never mistaken
   for one the person folded. */

import { zustand, istSeitenleisteSchmal } from './zustand.svelte.js'
import { leiste, zeitweiseOeffnen } from './arbeitsleiste.svelte.js'
import { foldedForRoom, forgetFolded } from './columnRoom.svelte.js'

/* How the person had the columns before the studio pulled them open:
   `leftFolded` — the sidebar was folded by hand — and `rightOpen` — the
   tools were open, which counts a column the window had folded for room as
   open, the person did not ask for that. */
let before = null

/** The studio is about to open: both columns carry its settings. */
export function columnsForStudio() {
  /* On a narrow window the right column is a sheet over the whole window
     and would hide the surface, so it is left as it is there, and so is
     what the window folded for room. */
  const narrow = istSeitenleisteSchmal()
  const folded = foldedForRoom()
  before = {
    leftFolded: zustand.seitenleisteEingeklappt && !folded.left,
    rightOpen: leiste.offen || folded.right,
    modul: leiste.modul,
  }
  if (!narrow) {
    zeitweiseOeffnen()
    /* The studio asks for both columns afresh: what was folded for room
       before is in `before`, and the window folds again as it must. */
    forgetFolded()
  }
  zustand.seitenleisteEingeklappt = false
}

/** The studio has closed: the columns go back to how the person had them. */
export function columnsBack() {
  if (!before) return
  /* Only what the studio itself unfolded folds again: a column the person
     folded in the meantime stays folded, and one whose tool the person
     picked in the meantime stays open on it. A column the window folded for
     room is not the person's fold — it goes back to how the person had it
     and, if that was open, comes back with the room. */
  const folded = foldedForRoom()
  const leftByHand = zustand.seitenleisteEingeklappt && !folded.left
  if (!leftByHand && before.leftFolded) {
    zustand.seitenleisteEingeklappt = true
    forgetFolded('left')
  }
  const rightByHand = !leiste.offen && !folded.right
  if (!rightByHand && !before.rightOpen && leiste.modul === before.modul) {
    leiste.offen = false
    forgetFolded('right')
  }
  before = null
}
