/*
  How the phone page talks to each of the five servers that run a model with
  llama.cpp: the report it asks for, the protocol, the start, the stop, the
  folder, and the numbers each of them takes.

  The routes are the desktop page's own. The two servers whose start choice
  is kept as a setting — the model server and the agent server — go through
  the stores that keep it, so a start from the phone and a start from the
  desktop leave the same choice behind; the others take what a start needs
  in the request.
*/
import { api } from '../../lib/api.js'
import { nurGeaendert } from '../../lib/nurgeaendert.js'
import {
  runnermodell,
  standLaden as modelLoad,
  werteSetzen as modelStore,
} from '../../lib/runnermodell.svelte.js'
import {
  agentenmodell,
  slotStoppen,
  standLaden as agentLoad,
  waehlen as agentChoose,
  werteSetzen as agentStore,
} from '../../lib/agentenserver.svelte.js'
import { seedValue, wholeNumber } from '../servers.js'

/* The numbers each server takes, by field name; `fields` is the order the
   page lists them in and `title` the catalogue key of each label. */
const NUMBER_TITLES = {
  kontext: 'modell.feld_kontext',
  schichten: 'modell.feld_schichten',
  threads: 'modell.feld_faeden',
  port: 'modell.feld_port',
}

export const DRIVERS = {
  model: {
    report: () => api.runnerAuskunft(),
    log: () => api.runnerProtokoll(),
    folder: () => api.modellordnerOeffnen(),
    stop: () => api.runnerStoppen(),
    fields: ['kontext', 'schichten', 'port'],
    stored: () => runnermodell,
    /* Reads the stored choice, which nothing on the phone has read yet. */
    load: () => modelLoad(),
    remembered: () => runnermodell.modell,
    /* The numbers go into the stored choice first, only what the hand
       changed — a pre-filled default is no choice — and the start reads the
       choice from there. */
    async start(model, numbers, report) {
      const typed = {
        kontext: wholeNumber(numbers.kontext),
        schichten: wholeNumber(numbers.schichten),
        port: wholeNumber(numbers.port),
      }
      const later = nurGeaendert(typed, runnermodell, { ...(report?.vorgaben ?? {}), port: report?.port })
      await modelStore({ modell: model, ...later })
      return api.runnerStarten({ modell: model })
    },
  },
  agent: {
    report: () => api.agentenmodellAuskunft(),
    log: () => api.agentenmodellProtokoll(),
    folder: () => api.modellordnerOeffnen(),
    stop: () => slotStoppen(),
    fields: ['kontext', 'schichten', 'port'],
    stored: () => agentenmodell,
    load: () => agentLoad(),
    remembered: () => (agentenmodell.sorte === 'slot' ? agentenmodell.wert : null),
    async start(model, numbers, report) {
      const typed = {
        kontext: wholeNumber(numbers.kontext),
        schichten: wholeNumber(numbers.schichten),
        port: wholeNumber(numbers.port),
      }
      const later = nurGeaendert(typed, agentenmodell, { ...(report?.vorgaben ?? {}), port: report?.port })
      if (Object.keys(later).length) await agentStore(later)
      await agentChoose(`slot:${model}`)
      return null
    },
  },
  embedding: {
    report: () => api.einbettungAuskunft(),
    log: () => api.einbettungProtokoll(),
    folder: () => api.einbettungOrdnerOeffnen(),
    stop: () => api.einbettungStoppen(),
    fields: ['port'],
    start: (model, numbers) => api.einbettungStarten(model, wholeNumber(numbers.port)),
  },
  speech: {
    report: () => api.spracheAuskunft(),
    log: () => api.spracheProtokoll(),
    folder: () => api.spracheOrdnerOeffnen(),
    stop: () => api.spracheStoppen(),
    fields: ['kontext', 'schichten', 'threads', 'port'],
    start: (model, numbers) =>
      api.spracheStarten(model, {
        port: wholeNumber(numbers.port),
        kontext: wholeNumber(numbers.kontext),
        schichten: wholeNumber(numbers.schichten),
        threads: wholeNumber(numbers.threads),
      }),
  },
  cleanup: {
    report: () => api.bereinigungAuskunft(),
    log: () => api.bereinigungProtokoll(),
    folder: null,
    stop: () => api.bereinigungStoppen(),
    fields: ['port'],
    start: (model, numbers) => api.bereinigungStarten(model, wholeNumber(numbers.port)),
  },
}

/** The label key of a numeric field. */
export const numberTitle = (name) => NUMBER_TITLES[name]

/** What the fields of a server hold, as text, from its report. */
export function seedNumbers(kind, report) {
  const numbers = {}
  const stored = DRIVERS[kind].stored?.()
  for (const name of DRIVERS[kind].fields) numbers[name] = seedValue(report, name, stored)
  return numbers
}
