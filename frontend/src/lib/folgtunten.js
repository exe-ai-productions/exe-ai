/*
  Keeps a box pinned to its own bottom while its content grows.

  A capped box that never scrolls is worse than no cap at all: the output
  keeps arriving, the reader keeps seeing the first screen, and there is no
  bar to say so — this house hides them everywhere (stil/global.css). So the
  box follows its own tail, the same way the terminal's outer track follows
  the run.

  Following stops the moment somebody scrolls up inside it, and starts again
  when they come back to the bottom: a reader looking at line 40 of a build
  must not be yanked back down by line 41. `NAH` is the slack that makes
  "at the bottom" survive a fractional scroll height.

  Growth is watched rather than announced, because the text arrives as plain
  DOM updates from several places and none of them knows about this box.
*/

import { inhaltBeobachten } from './inhaltswache.js'

// How far from the bottom still counts as being at the bottom. Exported:
// the terminal's outer track (ModulTerminal.svelte) answers the same
// question, and two unlabeled 24s in two files were already one edit away
// from disagreeing.
export const NAH = 24

export function folgtUnten(knoten) {
  let klebt = true

  const gescrollt = () => {
    const abstand = knoten.scrollHeight - knoten.scrollTop - knoten.clientHeight
    klebt = abstand <= NAH
  }

  const nachziehen = () => {
    if (klebt) knoten.scrollTop = knoten.scrollHeight
  }

  knoten.addEventListener('scroll', gescrollt, { passive: true })
  // Through the shared watcher: this box also wears `rollfade`, and one
  // observer answers both (lib/inhaltswache.js).
  const inhaltAb = inhaltBeobachten(knoten, nachziehen)
  nachziehen()

  return {
    destroy() {
      knoten.removeEventListener('scroll', gescrollt)
      inhaltAb()
    },
  }
}
