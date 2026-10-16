/*
  Which call of the answer was clicked, for the terminal on the right to
  show, and where the focus goes back to when the column is closed.

  A line of a call in the answer says what ran and nothing more — its
  arguments and its result stand in the terminal tool. A click on the line
  names the call (`key`, the same key `lib/werkzeughistorie.js` gives
  the call's line there), brings the terminal forward and remembers the line
  that was clicked; the terminal opens that call and marks it. Closing the
  column, with its button or with Esc, gives the focus back to the line, so
  somebody who walks the answer with the keyboard does not lose their place.

  The agents view needs only the second half: a click on the row of an agent
  asks for its card through `openTranscript` (lib/agentchat.svelte.js) and
  leaves its line here to be found again.
*/

import { moduleShow } from './arbeitsleiste.svelte.js'

export const callSelection = $state({
  /* The call asked for, until the terminal has read it. */
  key: null,
  /* How often one was asked for: the same call asked for twice is a new
     gesture and unfolds again. */
  counter: 0,
})

/* The line that was clicked, outside of the reactive state: it is a node. */
let trigger = null

/** Remember the line a click on the column was made from. */
export function rememberTrigger(node) {
  trigger = node ?? null
}

/** The terminal shows `key`: unfolded, marked, in view. */
export async function openCall(key, node) {
  rememberTrigger(node)
  callSelection.key = key
  callSelection.counter += 1
  await moduleShow('terminal')
}

/** Whether the column was opened from a line of the answer, so that Esc
 *  has something to close and give the focus back to. */
export function hasTrigger() {
  return Boolean(trigger && trigger.isConnected)
}

/** The column was closed: the focus goes back to the line it was opened
 *  from, once. */
export function restoreFocus() {
  const node = trigger
  trigger = null
  callSelection.key = null
  if (node && node.isConnected) node.focus({ preventScroll: false })
}
