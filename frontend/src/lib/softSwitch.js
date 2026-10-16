/*
  The soft change of a step in the block.

  A call that comes into an open block fades in over the time a character
  takes to come up (280 ms); `Nachricht.svelte` reads that time and the
  reader's wish for less motion from here.
*/

export const SWITCH_MS = 280

/* Whether the reader asked the system for less motion. */
export const reducedMotion = () =>
  typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
