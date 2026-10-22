/*
  Moves an element to the page's root for as long as it lives.

  A layer that belongs to a page but must not be part of it — a menu that
  opens over the cards of a scrolling page — stands at the root instead of
  inside the page's scroller. The scroller wears the soft mask of
  `rollfade.js`, and in the program's own window the menu of a server card,
  drawn inside that mask, painted the whole area under the first row of
  cards black while it was open. At the root the layer is outside the
  scroller and its mask, and takes its place in the page's stacking order by
  its own z-index.

  Use it on ONE element that holds everything the layer is made of: the
  block that owns the element removes it again by its own first and last
  node, so two siblings moved apart would leave the block's walk with no
  end to find.
*/
export function toRoot(node) {
  const root = document.getElementById('wurzel')
  if (!root) throw new Error('toRoot: #wurzel not found - every layer depends on it')
  root.appendChild(node)
  return {
    destroy() {
      if (node.parentNode === root) node.remove()
    },
  }
}
