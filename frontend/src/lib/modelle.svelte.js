/*
  The models: which ones exist, which of a catalogue the user has picked, and
  which of those appear in the quick picker.

  Its own module because this is neither the picker's business nor the
  parameter panel's. Everyone asks the same questions and should get the same
  answers from one place.

  Two separate things live here, and mixing them was the old confusion:

    gewaehlt  Which models of a PROVIDER'S CATALOGUE are in the list at all.
              A provider with a catalogue starts EMPTY — OpenAI reports 124
              models, most of them for speech, images or embeddings, and
              nobody asked for a list they did not order.

    an / aus  Which of the models in the list appear in the quick picker.
              Here the reverse is stored — what is OFF — so a model that
              newly appears is visible instead of staying hidden until
              somebody remembers to allow it.

  Both are settings and therefore live in the cascade on the server: the same
  on every device.
*/

import { api } from './api.js'
import { aktuellesModell, zustand } from './zustand.svelte.js'

/* What is switched OFF in the quick picker. */
const SCHLUESSEL_AUS = 'modelle_aus'
/* Which models of each catalogue provider were picked: { anbieter: [modell] }. */
const SCHLUESSEL_WAHL = 'katalog_wahl'

export const modellwahl = $state({
  aus: [],
  gewaehlt: {},
  geladen: false,
})

export async function auswahlLaden() {
  const [aus, wahl] = await Promise.all([
    api.einstellungAufgeloest(SCHLUESSEL_AUS).catch(() => null),
    api.einstellungAufgeloest(SCHLUESSEL_WAHL).catch(() => null),
  ])
  modellwahl.aus = Array.isArray(aus?.wert) ? aus.wert : []
  modellwahl.gewaehlt =
    wahl?.wert && typeof wahl.wert === 'object' && !Array.isArray(wahl.wert)
      ? wahl.wert
      : {}
  modellwahl.geladen = true
}

/* ——— The catalogue: what is in the list at all ——— */

/** Does this entry come from a catalogue the user has to pick from? */
function ausKatalog(modell) {
  return Boolean(modell.modell)
}

export function istGewaehlt(modell) {
  if (!ausKatalog(modell)) return true
  /* What the configuration names is picked without anyone ticking it —
     otherwise a provider that demonstrably works would look unused. */
  if (modell.angeheftet) return true
  return (modellwahl.gewaehlt[modell.anbieter] ?? []).includes(modell.modell)
}

/** Everything the server offers, whether picked or not — for the tick list. */
export function katalogVon(anbieter) {
  return zustand.modelle.filter((m) => m.anbieter === anbieter && ausKatalog(m))
}

export async function katalogSchalten(modell, gewaehlt) {
  const vorher = modellwahl.gewaehlt
  const bisher = vorher[modell.anbieter] ?? []
  const neu = gewaehlt
    ? [...new Set([...bisher, modell.modell])]
    : bisher.filter((name) => name !== modell.modell)
  await katalogSichern({ ...vorher, [modell.anbieter]: neu }, vorher)
}

/** The "select all" of a catalogue — and its counterpart, with an empty list. */
export async function katalogAlle(anbieter, alle) {
  const vorher = modellwahl.gewaehlt
  const neu = alle ? katalogVon(anbieter).map((m) => m.modell) : []
  await katalogSichern({ ...vorher, [anbieter]: neu }, vorher)
}

async function katalogSichern(neu, vorher) {
  modellwahl.gewaehlt = neu
  /* Providers without a single pick are dropped instead of stored as an
     empty list — an empty entry says nothing the absence does not. */
  const knapp = Object.fromEntries(
    Object.entries(neu).filter(([, namen]) => namen.length),
  )
  try {
    await api.einstellungSetzen(
      'global', SCHLUESSEL_WAHL, Object.keys(knapp).length ? knapp : null,
    )
  } catch {
    /* Put it back rather than showing a state that was never stored. */
    modellwahl.gewaehlt = vorher
  }
}

/* ——— The quick picker: which of them are on ——— */

export function istAn(modellId) {
  return !modellwahl.aus.includes(modellId)
}

/* The chat's model is switched off in the quick picker. Then nothing is
   sent: the bar keeps its words, the send button is shut, and a queued
   message waits — "off" means off, not "off but answering".
   One reading for the bar, its button, the
   queue and the "Model disabled" label, so the four cannot disagree. */
export function chosenModelOff() {
  return Boolean(aktuellesModell()) && !istAn(zustand.modellId)
}

export async function schalten(modellId, an) {
  const vorher = modellwahl.aus
  const neu = an
    ? vorher.filter((id) => id !== modellId)
    : [...new Set([...vorher, modellId])]
  modellwahl.aus = neu
  try {
    await api.einstellungSetzen('global', SCHLUESSEL_AUS, neu.length ? neu : null)
  } catch {
    modellwahl.aus = vorher
  }
}

/* ——— Who belongs where ——— */

/** Everything running on this machine. */
export function lokale() {
  return zustand.modelle.filter((m) => m.group === 'local')
}

/** The cloud providers, each with the models picked from its catalogue.

    Grouped by the provider the server names — before, the group was guessed
    from the host name in the address, which was only ever right by accident. */
export function anbieter() {
  const haeuser = []
  for (const modell of zustand.modelle) {
    if (modell.group === 'local') continue
    let haus = haeuser.find((h) => h.id === modell.anbieter)
    if (!haus) {
      haus = {
        id: modell.anbieter,
        name: modell.anbieter_name || modell.anbieter,
        erreichbar: modell.erreichbar,
        schluessel_env: modell.schluessel_env,
        schluessel_gesetzt: modell.schluessel_gesetzt,
        /* Endpoint-wide: every model of a provider carries the same
           capability answer, so the first one speaks for the house. */
        vision: Boolean(modell.capabilities?.vision),
        /* A LIST of stages, not a yes — and an empty array is truthy in
           this language, so the length is what answers the question. The
           hand switch below writes a plain boolean back; the service reads
           that as the older form of the same word. */
        denken: (modell.capabilities?.thinking?.length ?? 0) > 0,
        werkzeuge: Boolean(modell.capabilities?.tool_calls),
        /* Endpoint-wide, same as the three above: the "Zeitgrenze" switch.
           On by default — a bare endpoint with no answer yet has always
           meant the 600 s it always had. */
        zeitgrenze: modell.timeout_enabled ?? true,
        /* What the service resolved, whether it asked the server, read the
           model list or took it out of the configuration — taken back
           below where the provider's models disagree (a catalogue with a
           window per model; the chat bar reads the picked model's entry).
           A value entered by hand stands on every entry alike. Null means
           nobody knows, and that is exactly when the field below has
           something to do. */
        kontext: modell.context_tokens ?? null,
        // The two kept apart: what the configuration says, and what
        // the service found. A field filled from the first alone can
        // be emptied back to 'ask the server'; filled from both it
        // could not, and it showed a found number as somebody's choice.
        kontextEigen: modell.kontext_eigen ?? null,
        // Which of the five sources (app/fenstergroesse.py) resolved
        // 'kontext' — 'ersatz' is the one the field must not call
        // 'found', since nothing actually was.
        kontextQuelle: modell.kontext_quelle ?? null,
        modelle: [],
        katalog: 0,
      }
      haeuser.push(haus)
    }
    /* A catalogue gives each model its own window: the provider names one
       only while its models agree, otherwise the field has no found
       number to show. */
    if (haus.kontext !== (modell.context_tokens ?? null)) {
      haus.kontext = null
      haus.kontextQuelle = null
    }
    haus.katalog += 1
    if (istGewaehlt(modell)) haus.modelle.push(modell)
  }
  return haeuser
}

/** What the quick picker may show: picked from the catalogue, and switched on. */
export function sichtbare() {
  return zustand.modelle.filter((m) => istGewaehlt(m) && istAn(m.id))
}
