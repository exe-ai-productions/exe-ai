/*
  What the head of a page says while pages stand inside it: which inner page
  owns it, and the name the way back carries. The stack is a list of
  `{ title, onback }`, the last one on top.

  No imports on purpose: a list in, a name out, so a test can run it without
  a window around it.
*/

/** The inner page that owns the head, or `null` while the page shows its own
    list. */
export const topOf = (stack) => stack.at(-1) ?? null

/** The name the way back carries: the inner page before the top one, else the
    name of the page itself. */
export const nameBefore = (stack, pageTitle) => (stack.length > 1 ? stack.at(-2).title : pageTitle)
