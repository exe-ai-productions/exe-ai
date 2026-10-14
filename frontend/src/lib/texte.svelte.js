/*
  Translations for the interface.

  The catalog lives on the server (`app/locales/*.json`) and is fetched once
  at startup — exactly one place for all texts, instead of a copy in the
  bundle that gets forgotten when editing. It is loaded **before** the first
  render (see `main.js`), otherwise the keys flash up for a moment.

  `katalog` is $state: when the language changes, every component that uses
  `t()` re-renders. No component has to know about it.

  The choice comes from the settings cascade (`app/sprachwahl.py`), otherwise
  from the device setting. If the server doesn't know it, it returns its
  default language and says in `sprache` which one that was.

  It used to sit in browser storage, which is the one place the program
  itself cannot look — so a service writing a text for its user had no way
  of knowing which language that user reads.

  `auto` is a stored value here, not an empty entry: somebody going back to
  automatic after having picked a language is making a decision, and a
  cleared entry could not be told apart from never having chosen.
*/

import { api, rememberStatusText, spracheMerken } from './api.js'

/* The texts of the shown language — and, beside `sprache`, the choice the
   service last reported: `auto` until it has been asked. The settings
   window reads that choice while drawing, which cannot wait for a request,
   so the answer is kept here rather than fetched again. It stands IN this
   state and not in a plain `let`: a choice made elsewhere (the first-start
   window, the load at program start) has to reach the settings tile
   without a click, and only a reactive value does. */
export const texte = $state({ sprache: 'de', katalog: {}, wahl: 'auto' })

const SPEICHER = 'sprache'

/* The desired language: the stored choice first, then the device, German
   otherwise. `navigator.language` is "de-DE" or "en-GB" — we only care
   about the first part, because that's what the catalogs are named. Used
   inside the module only: it writes the choice before any catalogue is
   loaded, so a caller outside would rewrite a running switch. */
async function gewuenschteSprache() {
  try {
    const stand = await api.einstellungAufgeloest(SPEICHER)
    texte.wahl = stand?.wert?.sprache || 'auto'
  } catch {
    // The service could not say — then the device decides, as it would
    // without a choice.
    texte.wahl = 'auto'
  }
  if (texte.wahl !== 'auto') return texte.wahl
  return (navigator.language || 'de').slice(0, 2).toLowerCase()
}

/* The newest catalogue request. A switch made while an earlier one is still
   on its way takes over: when the older catalogue arrives afterwards it must
   neither replace the texts nor claim the language. */
let neuesteAnfrage = 0

/* Loads the catalogue and puts it on screen. Answers the language that now
   stands, or `null` when a newer request overtook this one — then nothing of
   it was applied. */
export async function texteLaden(sprache) {
  if (sprache === undefined) sprache = await gewuenschteSprache()
  const meine = ++neuesteAnfrage
  /* The catalogue is the only request that already carries the language
     being switched TO — it asks for exactly those texts, and the window
     still shows the old ones while it runs (api.js, `uebersetzungen`). Every
     other request keeps the language on screen until the texts below have
     arrived: a switch that hangs or fails must not leave the service
     answering in a language nobody is looking at. */
  const daten = await api.uebersetzungen(sprache)
  if (meine !== neuesteAnfrage) return null
  texte.katalog = daten.texte
  texte.sprache = daten.sprache
  document.documentElement.lang = daten.sprache
  // From here on every later request says which language it speaks — the
  // browser's own header only knows the system language, not this choice.
  // The service may have resolved "auto" to another one: its answer stands.
  spracheMerken(daten.sprache)
  // A refusal without a reason of its own is named in this language too
  // (api.js, errorFrom) — from here on, not from its own German default.
  rememberStatusText((status) => t('fehler.status', { status }))
  return daten.sprache
}

/* A switch counts only once its texts are here: the choice is set and stored
   after the catalogue, never before. A catalogue that hangs or fails leaves
   the choice, the window and the stored value as they were — the stored
   choice is how the service knows which language to write its own texts in
   (app/sprachwahl.py, interface_language) and which one the next start
   loads. A switch overtaken by a newer one changes nothing at all. */
export async function spracheWaehlen(sprache) {
  const geladen = await texteLaden(sprache)
  if (geladen === null) return texte.sprache
  texte.wahl = sprache
  await api.einstellungSetzen('global', SPEICHER, { sprache }).catch(() => {})
  return geladen
}

/* Back to "auto": the device decides again, stored as such once its texts
   are here. */
export async function spracheZuruecksetzen() {
  const geladen = await texteLaden((navigator.language || 'de').slice(0, 2).toLowerCase())
  if (geladen === null) return texte.sprache
  texte.wahl = 'auto'
  await api.einstellungSetzen('global', SPEICHER, { sprache: 'auto' }).catch(() => {})
  return geladen
}

/* A text for a dot path, e.g. t('chat.neu').

   If the key is missing, the key itself comes back instead of a blank spot:
   a visible `chat.neu` in the interface shows the error immediately, an
   empty button hides it.

   Placeholders go in curly braces, same notation as in the backend:
   t('werkzeug.fertig', { name: 'websuche' }). */
export function t(pfad, werte) {
  let wert = pfad.split('.').reduce((teil, schluessel) => teil?.[schluessel], texte.katalog)
  if (typeof wert !== 'string') return pfad
  if (werte) {
    for (const [schluessel, ersatz] of Object.entries(werte)) {
      wert = wert.split(`{${schluessel}}`).join(ersatz)
    }
  }
  return wert
}

/** The same sentence, but in PIECES: which part was written here and which
 *  part was put in at the last moment.
 *
 *  `t()` hands back one finished string, and the moment it does, the answer
 *  to "which of these words is a file name and which is the sentence around
 *  it" is gone. A display that wants to set the inserted part apart — the
 *  notices do, in the fixed-width face — cannot work that out afterwards
 *  without guessing: a value can be a common word, a single digit, or a
 *  path that happens to contain the sentence's own wording.
 *
 *  The template still knows. Split ON the braces rather than searching for
 *  the values, and the answer is exact.
 *
 *      teile('werkzeug.schreibt', { name: 'write_file' })
 *      → [{ wert: 'write_file' }, { fest: ' wird geschrieben' }]
 *
 *  A piece carries EITHER `fest` (written in the catalogue) or `wert` (put
 *  in). A placeholder with no value stays as it stands, braces and all —
 *  the same visible failure `t()` gives for a missing key, rather than a
 *  hole nobody notices.
 */
export function teile(pfad, werte) {
  const vorlage = pfad.split('.').reduce((teil, schluessel) => teil?.[schluessel], texte.katalog)
  if (typeof vorlage !== 'string') return [{ fest: pfad }]
  const stuecke = []
  let rest = vorlage
  /* Walks the template from the front rather than replacing in place: a
     value that itself contains braces must not be walked into a second
     time. What is put in is never looked at again. */
  const muster = /\{(\w+)\}/
  let treffer = muster.exec(rest)
  while (treffer) {
    if (treffer.index > 0) stuecke.push({ fest: rest.slice(0, treffer.index) })
    const name = treffer[1]
    const wert = werte?.[name]
    if (wert === undefined || wert === null) stuecke.push({ fest: treffer[0] })
    else stuecke.push({ wert: String(wert) })
    rest = rest.slice(treffer.index + treffer[0].length)
    treffer = muster.exec(rest)
  }
  if (rest) stuecke.push({ fest: rest })
  return stuecke
}
