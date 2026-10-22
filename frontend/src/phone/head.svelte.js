/*
  The one head of a page that stands over the chat.

  A page may open a page inside itself — settings open a group, the catalogue
  a model, the servers one server. The head of the whole page then says that
  inner page: the way back on the left with the name of the page it leads
  back to, the inner page's name in the middle. The inner page does not draw a
  head of its own; it puts its name and its way back here (`SubHead`), and the
  frame of the page (`PageFrame`) reads the top of the stack.

  A stack, because an inner page can open one more: the way back then carries
  the name of the inner page before it.
*/
import { untrack } from 'svelte'
import { nameBefore, topOf } from './headname.js'

export const head = $state({ stack: [], right: null })

/** Puts an inner page on the stack and gives the way to take it off again.
    `entry` is `{ title, onback }` and may change while it stands there; it
    may also carry `backText` (a word in place of the arrow, "Cancel") and
    `right` (`{ text, label, onclick, disabled }`, one button at the right
    end, "Done"). */
export function headPush(entry) {
  untrack(() => head.stack.push(entry))
  return () =>
    untrack(() => {
      const at = head.stack.indexOf(entry)
      if (at >= 0) head.stack.splice(at, 1)
    })
}

/** What stands at the right end of the head of the whole page while no inner
    page owns it: one sign (`{ sign, label, onclick }`). Gives the way to take
    it off again. */
let rightEntry = null
export function headRightSet(entry) {
  // The store hands back a proxy of what was put in, so the entry is kept
  // here to tell whether it is still the one that stands.
  rightEntry = entry
  untrack(() => (head.right = entry))
  return () =>
    untrack(() => {
      if (rightEntry === entry) {
        rightEntry = null
        head.right = null
      }
    })
}

/** The inner page that owns the head right now, or `null` while the page
    shows its own list. */
export const headTop = () => topOf(head.stack)

/** The name the way back carries (see `headname.js`). */
export const headBefore = (pageTitle) => nameBefore(head.stack, pageTitle)
