/*
  A tool's result and arguments as the terminal tool shows them.

  The chat's own line of a call says only what ran; the arguments and the
  result stand in the terminal tool, in the colours every code block in the
  program wears (lib/einfaerben.js).
*/

import { hervorheben, maskieren } from './einfaerben.js'

/* An argument value in the same colours as a real code block — a string
   stays plain (no language is known, and guessing one has burned this house
   before), an object or number goes through as the JSON it actually is,
   since stringifying it here is what makes it one. */
export function wertHtml(wert) {
  return typeof wert === 'string' ? hervorheben(wert) : hervorheben(JSON.stringify(wert), 'json')
}

/* A tool's result carries its change block, if any, straight after the
   one-sentence summary — app/tools/aenderungsblock.py joins them with a blank
   line, then the first hunk. That blank line followed by a hunk header is the
   mark: ordinary tool output never happens to start a line with it. */
export function aenderungAufteilen(text) {
  const stelle = String(text || '').indexOf('\n\n@@ ')
  if (stelle === -1) return null
  return { kurz: text.slice(0, stelle), diff: text.slice(stelle + 2) }
}

/* Coloured line by line instead of through hervorheben(): a diff is not a
   programming language, it is `+`/`-`/context rows, and highlight.js has no
   grammar registered for it (einfaerben.js). */
export function aenderungHtml(diff) {
  return diff
    .split('\n')
    .map((zeile) => {
      let art = 'kontext'
      if (zeile.startsWith('@@')) art = 'kopf'
      else if (zeile.startsWith('+')) art = 'hinzu'
      else if (zeile.startsWith('-')) art = 'entfernt'
      else if (zeile.startsWith('… ')) art = 'hinweis'
      return `<span class="diff-zeile diff-${art}">${maskieren(zeile)}</span>`
    })
    .join('\n')
}

/* One tool result, either as plain highlighted text or, when it carries a
   change block, as the short sentence plus the coloured diff below it — the
   same <pre> either way. */
export function werkzeugErgebnisHtml(text) {
  const aenderung = aenderungAufteilen(text)
  if (!aenderung) return hervorheben(text)
  return maskieren(aenderung.kurz) + '\n\n' + aenderungHtml(aenderung.diff)
}
