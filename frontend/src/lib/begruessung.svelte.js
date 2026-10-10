/*
  The greeting and the name behind it.

  One setting drives two things: the corner greeting on the empty chat and
  the one line in the system prompt that names the user. The switch and the
  name live in the settings store; this module keeps the loaded copy and
  the little clock that decides between morning, day and evening.
*/

import { api } from './api.js'

export const begruessung = $state({
  name: '',
  an: true,
  geladen: false,
  // The first name the operating system suggests for the first start.
  vorschlag: '',
  /* Has the first-start window been answered? It rides in the same setting
     because it is the same act — that window is what asks for the name. It
     used to be a mark in browser storage, so it came back in every new
     browser profile, on an installation long since set up. */
  erststart: false,
})

export async function begruessungLaden() {
  try {
    const [stand, meta] = await Promise.all([
      api.einstellungAufgeloest('anrede'),
      api.meta(),
    ])
    const wert = stand?.wert || {}
    begruessung.name = String(wert.name || '')
    begruessung.an = wert.an !== false
    begruessung.erststart = wert.erststart === true
    begruessung.vorschlag = String(meta?.system_name || '')
  } catch {
    // The service could not say — the greeting simply stays quiet.
  }
  begruessung.geladen = true
}

/* Writing a scope replaces its whole row — merging happens BETWEEN scopes,
   not inside one. All three keys therefore go out together, or saving the
   name would take the answered first-start window with it. */
function anredeSchreiben() {
  return api.einstellungSetzen('global', 'anrede', {
    name: begruessung.name,
    an: begruessung.an,
    erststart: begruessung.erststart,
  })
}

export async function anredeSpeichern(name, an) {
  begruessung.name = String(name || '').trim()
  begruessung.an = Boolean(an)
  await anredeSchreiben()
}

/** The greeting key for this hour — morning, day or evening. */
export function grussSchluessel(frage = false) {
  const stunde = new Date().getHours()
  const teil = stunde >= 5 && stunde < 11 ? 'morgen' : stunde >= 11 && stunde < 18 ? 'tag' : 'abend'
  return frage ? `gruss.frage_${teil}` : `gruss.${teil}`
}

/* The first start is a one-time act per installation: once the window was
   answered — or a name exists — it never comes back. */
export function erststartNoetig() {
  return begruessung.geladen && !begruessung.name && !begruessung.erststart
}

export function erststartErledigt() {
  begruessung.erststart = true
  return anredeSchreiben().catch(() => {})
}
