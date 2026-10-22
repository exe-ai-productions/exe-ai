/*
  The place a permission card points at inside the command it asks about.

  A call that reaches outside the shared folders, over the network or into the
  program's own command line is asked about with a reason, and the reason has
  a value: the path, the address or the program word. The card does not put
  that value into a sentence; it lays a soft marker over it where it stands in
  the command — one surface for the whole value, across the colours of the
  highlighted command and across a line break — and the colours under the
  marker stay. Where the command does not carry the value as written (`~/notes`
  for `/Users/x/notes`), the value follows the sentence after a colon instead.

  The card of the window and the card of the phone share it.
*/

import { displayPath } from './paths.js'

/* What may stand directly before or after a whole word of a command: nothing,
   a space, a quote, or a character that ends or joins commands. A hyphen, a
   slash, a dot or a letter does not — `exe` is a word in `cd x && exe run`,
   but not in `/tmp/exe-ai`. */
const EDGE = /[\s"'`;&|()<>=,]/

const MARK_OPEN = '<mark class="outside">'

/* A command that is not coloured, as HTML: only what HTML reads is escaped.
   The highlighting library is not pulled in for this, so the phone's card,
   which never colours, can use it. */
export function plainHtml(text) {
  return String(text ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

/* Highlighted HTML as tokens: a tag of the colouring, one character entity
   (one character of the command), or one plain character. */
const TOKEN = /<\/?span[^>]*>|&#?\w+;|[\s\S]/g

/* The ways a value may be written in a command. The service names the place
   it resolves to, and on a Mac `/etc`, `/tmp` and `/var` lie under
   `/private`: a command that says `cat /etc/hosts` reaches
   `/private/etc/hosts`, the same place under the name the command gave it. */
function forms(value) {
  const plain = value.replace(/^\/private(?=\/(?:etc|tmp|var)(?:\/|$))/, '')
  return plain === value ? [value] : [value, plain]
}

/* Every place `value` stands in `text` as a whole word, as [start, end),
   in the order they stand. */
function places(text, value) {
  const found = []
  if (!value) return found
  for (const form of forms(value)) {
    let from = 0
    for (;;) {
      const at = text.indexOf(form, from)
      if (at < 0) break
      const end = at + form.length
      const before = at === 0 || EDGE.test(text[at - 1])
      const after = end === text.length || EDGE.test(text[end])
      if (before && after) {
        found.push([at, end])
        from = end
      } else {
        from = at + 1
      }
    }
  }
  found.sort((a, b) => a[0] - b[0])
  // The spellings do not overlap; were they to, the first one stands.
  return found.filter((spot, index) => index === 0 || spot[0] >= found[index - 1][1])
}

/**
 * The command's HTML with a marker around every whole-word place of `value`.
 *
 * `html` is the command as the colouring made it (or as it was escaped, when
 * it is not coloured), `raw` the same command as plain text. The marker is
 * one element per place: a colour span it crosses is closed before it and
 * opened again inside it, so no colour changes and no colour part gets a
 * marker of its own.
 *
 * Returns the HTML and how many places were marked.
 */
export function markPath(html, raw, value) {
  const text = String(raw ?? '')
  const spots = places(text, String(value ?? ''))
  if (!spots.length) return { html, count: 0 }

  let out = ''
  let position = 0
  let next = 0
  let inside = false
  const open = []
  for (const token of String(html).match(TOKEN) ?? []) {
    const closing = token.startsWith('</')
    const tag = token.startsWith('<')
    if (!closing) {
      // A marker begins and ends in front of text or in front of a tag that
      // opens, never in front of one that closes: a colour that ends exactly
      // at the edge of a place stays whole.
      if (inside && position === spots[next - 1][1]) {
        out += '</span>'.repeat(open.length) + '</mark>' + open.join('')
        inside = false
      }
      if (!inside && next < spots.length && position === spots[next][0]) {
        out += '</span>'.repeat(open.length) + MARK_OPEN + open.join('')
        inside = true
        next += 1
      }
    }
    if (closing) {
      open.pop()
      out += token
    } else if (tag) {
      open.push(token)
      out += token
    } else {
      out += token
      position += 1
    }
  }
  if (inside) out += '</span>'.repeat(open.length) + '</mark>' + open.join('')
  return { html: out, count: spots.length }
}

/**
 * The warning line under the command: the reason's sentence, and the value
 * after a colon where no marker carries it.
 */
export function reasonLine(sentence, value, marked) {
  const text = String(sentence ?? '')
  if (!value || marked) return text
  return `${text}: ${displayPath(value)}`
}
