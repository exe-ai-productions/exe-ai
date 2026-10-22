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

  A running answer may be told to fade its new characters in:
  `use:lebendHtml={{ html, fadeIn: true }}`. After each walk the
  characters that came up in the last 280 ms are wrapped in a span that
  carries a negative animation delay of its age, so a span that is made
  afresh with the next frame goes on from where the last one was; whatever is
  older is left plain. Nothing of it stays in the text: the next walk finds
  plain text again and the spans are gone once their time is out.
*/

const ELEMENT = 1
const TEXT = 3

/* How long a new character takes to come up, in milliseconds — the time
   of `.flow-char`'s animation in the component that wears the action. */
const FADE_IN_MS = 280

/* The class of a character that is fading in (`.flow-char`, drawn by
   the component that wears the action). */
const CHAR_CLASS = 'flow-char'

function parameter(arg) {
  return typeof arg === 'string' || arg == null ? { html: arg, fadeIn: false } : arg
}

export function lebendHtml(knoten, arg) {
  const seen = { before: 0, arrivals: [] }
  const draw = (neu) => {
    const { html, fadeIn } = parameter(neu)
    htmlAngleichen(knoten, html)
    if (fadeIn) fadeInChars(knoten, seen, performance.now())
    else {
      seen.before = textLength(knoten)
      seen.arrivals.length = 0
    }
  }
  draw(arg)
  return {
    update(neu) {
      draw(neu)
    },
  }
}

function textNodes(root) {
  const walker = root.ownerDocument.createTreeWalker(root, 4 /* NodeFilter.SHOW_TEXT */)
  const list = []
  while (walker.nextNode()) list.push(walker.currentNode)
  return list
}

function textLength(root) {
  let sum = 0
  for (const node of textNodes(root)) sum += node.nodeValue.length
  return sum
}

/* Wraps the characters that arrived within the last `FADE_IN_MS` in spans
   that go on fading from their age. `seen.before` is how long the text was
   when it was looked at last; what lies beyond is new and gets its moment. */
function fadeInChars(root, seen, now) {
  const total = textLength(root)
  if (total < seen.before) {
    // The text got shorter (a block was parsed differently): what stood
    // beyond the new end is gone with it.
    seen.arrivals = seen.arrivals.filter((e) => e.from < total)
    for (const e of seen.arrivals) e.to = Math.min(e.to, total)
  } else if (total > seen.before) {
    seen.arrivals.push({ from: seen.before, to: total, at: now })
  }
  seen.before = total
  seen.arrivals = seen.arrivals.filter((e) => now - e.at < FADE_IN_MS)
  if (!seen.arrivals.length) return
  // From the back, so the places of the earlier ones do not move.
  for (const e of [...seen.arrivals].reverse()) {
    wrapChars(root, e.from, e.to, Math.round(now - e.at))
  }
}

function wrapChars(root, from, to, age) {
  let place = 0
  for (const node of textNodes(root)) {
    const length = node.nodeValue.length
    const begin = place
    place += length
    if (place <= from) continue
    if (begin >= to) break
    const a = Math.max(from, begin) - begin
    const b = Math.min(to, place) - begin
    let target = node
    if (a > 0) target = target.splitText(a)
    if (b - a < target.nodeValue.length) target.splitText(b - a)
    const wrapper = root.ownerDocument.createElement('span')
    wrapper.className = CHAR_CLASS
    wrapper.style.animationDelay = `-${age}ms`
    target.parentNode.replaceChild(wrapper, target)
    wrapper.appendChild(target)
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

/* The one class the page itself puts on a live element, never the markup:
   the copy button wears it for the second its tick shows. It is no
   difference, or the next piece of a growing answer would replace the button
   and the tick would end before its time. */
const LIVE_STATE_CLASS = 'copied'

function withoutLiveState(value) {
  const names = value.split(' ')
  return names.includes(LIVE_STATE_CLASS) ? names.filter((name) => name !== LIVE_STATE_CLASS).join(' ') : value
}

/* Same tag, same attributes — the element can be kept and only its
   children looked at. A changed attribute (a class the highlighter
   added, a src) is a different element and gets replaced whole. */
function gleicheHuelle(a, n) {
  if (a.tagName !== n.tagName) return false
  if (a.attributes.length !== n.attributes.length) return false
  for (const attribut of n.attributes) {
    const value = a.getAttribute(attribut.name)
    if ((attribut.name === 'class' && value !== null ? withoutLiveState(value) : value) !== attribut.value) return false
  }
  return true
}
