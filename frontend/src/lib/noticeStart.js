/*
  Where the notices begin, once the page that stands open has a head of its
  own: under that head, never over it.

  The stack of notices (teile/Meldungen.svelte) hangs at the top of the chat
  tile and begins 46 px under its edge, which is right over the chat and
  wrong over a page: the head of a page is taller, and the stack began in the
  middle of its title. A page, or the studio, hands over the lowest edge of
  what it keeps free at the top — in the pixels the browser measures — and the
  stack starts under it. One value for every page, never a number of its own
  per page; it goes away with the page that put it up.
*/
import { zustand } from './zustand.svelte.js'

/* Whoever wrote the value last: two pages swapping places write and take
   down in one turn, and the one going must not take down the one coming. */
let holder = null

/* `nodes` is read again at every measure, so a node that comes and goes is
   followed. Returns the function that takes the value down — and only if it
   is still this page's own. It does so a turn later, outside the flush that
   is taking the page down: a write made while the page is torn down does not
   reach the stack that reads it (measured: the stack kept its old start).
   Opening a page closes the studio, so the two never stand open together and
   one value with one owner is enough. */
export function reportHeadBottom(nodes) {
  const me = {}
  const measure = () => {
    const found = nodes().filter(Boolean)
    if (!found.length) return
    holder = me
    zustand.menuHeadBottom = Math.max(...found.map((node) => node.getBoundingClientRect().bottom))
  }
  measure()
  const watcher = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
  nodes().filter(Boolean).forEach((node) => watcher?.observe(node))
  window.addEventListener('resize', measure)
  return () => {
    watcher?.disconnect()
    window.removeEventListener('resize', measure)
    queueMicrotask(() => {
      if (holder !== me) return
      holder = null
      zustand.menuHeadBottom = null
    })
  }
}
