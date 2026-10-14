/*
  `slide` for rows that may sit in a sheet nobody sees.

  `slide` reads the height of the node it moves. A row inside a sheet that
  stands aside (`display: none`) has no height, the animation then asks the
  browser for keyframes of NaN pixels, and the console says so once per row.
  A row nobody can see has nothing to move: it comes and goes at once, and a
  row that is drawn slides as it always did.
*/
import { slide } from 'svelte/transition'

export function slideIfDrawn(node, params) {
  if (node.getClientRects().length === 0) return { duration: 0 }
  return slide(node, params)
}
