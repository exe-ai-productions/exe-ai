/* How much room the chat keeps between the two columns, and which columns
   stand open when the window cannot hold both beside it.

   Pure arithmetic, no state: the window's own width and the two columns'
   widths go in, the answer comes out — so the seam handle (Seitengriff.svelte)
   and the folding glue (columnRoom.svelte.js) read the same three numbers
   and the same rule. */

/* The folded column's bar of signs, on either side. */
export const SIGN_BAR = 52
/* The chat's own air: 8px to either column. */
export const CHAT_AIR = 16
/* What the chat keeps, however narrow the window. */
export const CHAT_MIN = 420

/* The chat's width beside two columns of these widths. */
export function chatWidth(windowWidth, leftWidth, rightWidth) {
  return windowWidth - leftWidth - rightWidth - CHAT_AIR
}

/**
 * Which columns may stand open so that the chat keeps its minimum.
 *
 * `left` and `right` say which columns are wanted open, `leftWidth` and
 * `rightWidth` the width each takes while open. When the chat would fall
 * under its minimum the right column folds first, then the left one — except
 * that the column named in `last` (the one somebody has just opened) is the
 * last to give way. A folded column still takes its bar of signs; two bars
 * always fit a window the columns are laid out beside the chat in.
 */
export function openColumns({ windowWidth, leftWidth, rightWidth, left, right, last = null }) {
  let leftOpen = left
  let rightOpen = right
  const fits = () => chatWidth(
    windowWidth,
    leftOpen ? leftWidth : SIGN_BAR,
    rightOpen ? rightWidth : SIGN_BAR,
  ) >= CHAT_MIN
  for (const side of last === 'right' ? ['left', 'right'] : ['right', 'left']) {
    if (fits()) break
    if (side === 'right') rightOpen = false
    else leftOpen = false
  }
  return { left: leftOpen, right: rightOpen }
}
