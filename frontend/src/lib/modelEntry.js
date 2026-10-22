/* What a model entry of a choice field carries besides its name.

   `entryMark` is the logo `fileMark` finds for the file, else the file's
   first letter — the one or the other, the way the overview rows stand. An
   entry that names no file (the empty choice, the main-model entry) is not
   given one. `idMark` is the same for a model id of the discovery
   (`provider:model`, or a bare provider): the mark follows the model after
   the first colon, so every entry of one provider does not wear the
   provider's letter. `entrySize` is a size in GB as the catalogue writes
   it, with the decimal sign of the language. */
import { fileMark } from './fileMark.js'
import { formatGb } from './numberDisplay.js'
import { t, texte } from './texte.svelte.js'

export function entryMark(fileName) {
  const name = String(fileName ?? '')
  if (!name) return {}
  const logo = fileMark(name)
  return logo ? { logo } : { letter: Array.from(name)[0].toUpperCase() }
}

export function idMark(id) {
  const text = String(id ?? '')
  const colon = text.indexOf(':')
  return entryMark(colon >= 0 && colon < text.length - 1 ? text.slice(colon + 1) : text)
}

export function entrySize(gb) {
  return t('modell.gb', { zahl: formatGb(gb, texte.sprache) })
}
