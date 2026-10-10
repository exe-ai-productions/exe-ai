/*
  Settings on the interface side.

  The server resolves the cascade — global, then per model, then per chat —
  and also reports which scope each value came from. This module holds the
  answer and writes changes back to the scope they belong to.

  Its own module because settings are not a property of the parameter menu:
  the working folders, the tool selection and the appearance will ask the same
  questions, and they should get the same answers from the same place.
*/

import { api } from './api.js'

export const einstellungen = $state({
  /* What applies right now, per key. `parameter` is the only one so far. */
  parameter: {},
  /* Per value: which scope it comes from ('global', 'modell:…', 'chat:…').
     The menu shows it, so a number never stands there without an origin. */
  herkunft: {},
  /* Which model the loaded values belong to — a switch has to reload. */
  fuerModell: null,
})

export function modellBereich(modellId) {
  return `modell:${modellId}`
}

export async function parameterLaden(modellId, chatId = null) {
  if (!modellId) return
  try {
    const antwort = await api.einstellungAufgeloest('parameter', {
      modell: modellId,
      chat: chatId,
    })
    einstellungen.parameter = antwort?.wert ?? {}
    einstellungen.herkunft = antwort?.herkunft ?? {}
    einstellungen.fuerModell = modellId
  } catch {
    /* Without an answer the menu falls back to the defaults it knows — the
       sliders stay usable, only the stored values are missing. */
    einstellungen.parameter = {}
    einstellungen.herkunft = {}
    einstellungen.fuerModell = modellId
  }
}

/**
 * Stores one value for a model. Applies to every new chat with that model,
 * on every device — that is the whole point of the move off the chat row.
 */
export async function parameterSetzen(modellId, name, wert) {
  const bereich = modellBereich(modellId)
  const neu = { ...einstellungen.parameter, [name]: wert }
  const antwort = await api.einstellungSetzen(bereich, 'parameter', neu)
  einstellungen.parameter = antwort?.wert ?? {}
  // Everything just written comes from this model now — everything that
  // really carries a value, that is.
  for (const schluessel of Object.keys(einstellungen.parameter)) {
    einstellungen.herkunft[schluessel] = bereich
  }
  // A field cleared back to "Auto" is not stored at all: the check drops a
  // null before anything is written (app/parameter.py, `pruefen`), so the
  // answer comes back without that key. Its old origin has to go with it —
  // left standing, it claims a scope for a number that is no longer set,
  // and the panel showed the empty field's word beside "Model" until a
  // reload happened to correct it. The same entry is what marks a value as
  // not sent (`zahl-unversendet` in Parametertafel.svelte), so both read
  // the same truth again.
  if (einstellungen.parameter[name] === undefined) delete einstellungen.herkunft[name]
}

/** Removes the model's values so the scope above takes over again. */
export async function parameterZuruecksetzen(modellId) {
  await api.einstellungSetzen(modellBereich(modellId), 'parameter', null)
  await parameterLaden(modellId)
}
