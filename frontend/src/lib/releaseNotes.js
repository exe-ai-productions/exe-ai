/*
  The notes of a release, made safe to set as formatted text.

  The shell hands them over the way the release feed carries them: as HTML
  somebody else wrote. Only what a note is written with is let through —
  headings, paragraphs, lists, emphasis, code, quotes — and only as bare
  tags: no attribute survives, so no address, no style and no handler does.
  Every other tag is dropped and its text kept: a picture is gone, and a
  link reads as its words, because a click on one would take the window away
  from the program. What a tag carries for a machine alone is dropped with
  its content. A "<" that opens no tag is text.

  Nothing of the source reaches the result except through these two doors:
  a tag written here, or text with its angle brackets taken out. A pure
  function with no imports, so the tests run this very file in node.
*/

const KEPT = new Set([
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'ul', 'ol', 'li',
  'strong', 'b', 'em', 'i', 'code', 'pre', 'blockquote', 'br', 'hr',
])

// These stand alone: a closing tag of theirs is nothing to write.
const ALONE = new Set(['br', 'hr'])

// Their content is no text of the note: scripts, styles, drawings, frames,
// form fields.
const GONE_WITH_CONTENT = new Set([
  'script', 'style', 'template', 'iframe', 'object', 'svg', 'math',
  'noscript', 'head', 'title', 'textarea', 'select',
])

// A comment, or one tag with whatever stands in it — a ">" inside a quoted
// value does not end the tag.
const TAG = /<!--[\s\S]*?-->|<(\/?)([a-zA-Z][a-zA-Z0-9]*)\b(?:[^>"']|"[^"]*"|'[^']*')*>/g

function asText(piece) {
  return piece.replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** The notes as HTML that carries nothing but formatted text. */
export function releaseNotesHtml(notes) {
  const source = typeof notes === 'string' ? notes : ''
  let result = ''
  let read = 0
  // The tag whose content is being left out, until it closes.
  let leavingOut = null
  for (const found of source.matchAll(TAG)) {
    if (!leavingOut) result += asText(source.slice(read, found.index))
    read = found.index + found[0].length
    const closing = found[1] === '/'
    const name = found[2]?.toLowerCase()
    // A comment carries no name and leaves nothing.
    if (!name) continue
    if (leavingOut) {
      if (closing && name === leavingOut) leavingOut = null
    } else if (GONE_WITH_CONTENT.has(name)) {
      if (!closing) leavingOut = name
    } else if (KEPT.has(name) && !(closing && ALONE.has(name))) {
      result += closing ? `</${name}>` : `<${name}>`
    }
  }
  if (!leavingOut) result += asText(source.slice(read))
  return result.trim()
}
