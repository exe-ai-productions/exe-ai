/*
  Draws streamed HTML in place, instead of rebuilding it.

  `{@html}` tears every node out and puts the new ones in, on every text
  chunk. For one frame the scroll area is as high as the chat WITHOUT the
  answer; the browser clamps the position to that height, fires a scroll
  event for the clamp, and the follow-along reads that event as the
  reader leaving (App.svelte, scrollGeprueft). Chromium's scroll anchoring
  hides most of it; WebKit has none — there the reader was thrown to the
  top of the answer on every chunk, and following switched itself off.

  So nothing is torn out that did not change. Old and new tree are walked
  together from the front: a text node takes its new text in place, an
  element with the same tag and attributes is entered rather than
  replaced, and only from the first real difference on is the rest
  swapped. A streamed answer only ever changes at its tail, so per chunk
  that is one text node — the scroll height never dips, nothing clamps,
  no spurious scroll event, and every node above the tail (a finished
  code block, a picture) stays exactly the node it was.

  Worn as an action: `<div use:lebendHtml={html}>`. The first draw is a
  plain fill; every update is the walk above.
*/

const ELEMENT = 1
const TEXT = 3

export function lebendHtml(knoten, html) {
  htmlAngleichen(knoten, html)
  return {
    update(neu) {
      htmlAngleichen(knoten, neu)
    },
  }
}

/* Make `ziel`'s children match `html`, touching as little as possible. */
export function htmlAngleichen(ziel, html) {
  const vorlage = ziel.ownerDocument.createElement('template')
  vorlage.innerHTML = html ?? ''
  angleichen(ziel, vorlage.content)
}

function angleichen(alt, neu) {
  const alte = alt.childNodes
  const neue = neu.childNodes
  let i = 0
  while (i < alte.length && i < neue.length) {
    const a = alte[i]
    const n = neue[i]
    if (a.nodeType === TEXT && n.nodeType === TEXT) {
      if (a.nodeValue !== n.nodeValue) a.nodeValue = n.nodeValue
      i += 1
      continue
    }
    if (a.nodeType === ELEMENT && n.nodeType === ELEMENT && gleicheHuelle(a, n)) {
      angleichen(a, n)
      i += 1
      continue
    }
    if (a.isEqualNode(n)) {
      i += 1
      continue
    }
    break
  }
  /* From the first difference on: the old tail goes, the new tail comes.
     Removed from the back so the live list never shifts under the index. */
  while (alte.length > i) alte[alte.length - 1].remove()
  while (neue.length > i) alt.appendChild(neue[i])
}

/* Same tag, same attributes — the element can be kept and only its
   children looked at. A changed attribute (a class the highlighter
   added, a src) is a different element and gets replaced whole. */
function gleicheHuelle(a, n) {
  if (a.tagName !== n.tagName) return false
  if (a.attributes.length !== n.attributes.length) return false
  for (const attribut of n.attributes) {
    if (a.getAttribute(attribut.name) !== attribut.value) return false
  }
  return true
}
