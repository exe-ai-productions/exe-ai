/*
  What the six servers report, kept for the list of the settings.

  The list shows a dot at each server that runs (or, for the picture server,
  its own four states). The report of each server is the one its own page
  reads; this module asks for them while a list stands in the sidebar, at the
  rhythm the local page asks at, and stops when the last list is gone.
*/
import { api } from './api.js'
import { pollWithoutOverlap } from './pollWithoutOverlap.js'
import { isRunning } from './serverOverviewRows.js'

/* The picture server's dot says whether sd-server runs — the same four states
   its own tile colours itself by; stopped draws none. */
export const BILDFARBE = { bereit: 'gruen', zeichnet: 'blau', fehler: 'rot' }

export const serverstand = $state({
  server: null,
  agent: null,
  einbettung: null,
  sprache: null,
  bereinigung: null,
  bild: null,
})

const TAKT_MS = 15_000
let halter = 0
let stoppen = null
let runde = 0
/* The reads of the newest round: a refresh waits for these, not for its own
   alone, since a round that starts after it makes the answers of the earlier
   one count for nothing. */
let neueste = Promise.resolve()

/* A report that cannot be read leaves no entry: a server that stopped or
   became unreachable must not keep the dot of its last good answer. */
function holen() {
  // An answer belongs to the round it was asked in: one that comes in after a
  // newer round began, or after the list was gone, is dropped.
  const mein = ++runde
  const setzen = (name, wert) => {
    if (mein === runde) serverstand[name] = wert
  }
  const lesen = (name, anfrage) =>
    anfrage.then((a) => setzen(name, a)).catch(() => setzen(name, null))
  const lauf = Promise.all([
    lesen('server', api.runnerAuskunft()),
    lesen('agent', api.agentenmodellAuskunft()),
    lesen('einbettung', api.einbettungAuskunft()),
    lesen('sprache', api.spracheAuskunft()),
    lesen('bereinigung', api.bereinigungAuskunft()),
    lesen('bild', api.turboStand()),
  ])
  neueste = lauf
  return lauf
}

function leeren() {
  runde += 1
  for (const name of Object.keys(serverstand)) serverstand[name] = null
}

/** Reads all six reports at once, outside the rhythm: before a start or a stop
 *  is decided and after it, so a row never acts on or shows what a server was
 *  up to fifteen seconds ago. Resolves when every report is in. */
export async function refreshServerState() {
  let lauf = holen()
  await lauf
  // A round that began meanwhile (the list's own beat) replaced these answers.
  while (lauf !== neueste) {
    lauf = neueste
    await lauf
  }
}

/** Asks for the reports as long as the caller stands; hands back the way to
 *  stop. Several callers share one rhythm. */
export function serverstandHalten() {
  halter += 1
  if (halter === 1) {
    holen()
    stoppen = pollWithoutOverlap(holen, TAKT_MS)
  }
  let frei = false
  return () => {
    if (frei) return
    frei = true
    halter -= 1
    if (halter === 0) {
      stoppen?.()
      stoppen = null
      leeren()
    }
  }
}

/** A report a page asked for on a faster beat than the one above, handed in so
 *  the dot of that server follows it: the local models page asks the model
 *  server every three seconds. */
export function reportServerState(name, bericht) {
  serverstand[name] = bericht
}

/** The dot of one server: a colour, or null while it does not run. Only a
 *  server that runs (or failed) has one — six grey dots for six stopped
 *  servers said nothing the missing green does not. */
export function serverPunkt(name) {
  if (name === 'bild') return BILDFARBE[serverstand.bild?.zustand] ?? null
  return serverstand[name]?.laeuft ? 'gruen' : null
}

/** Whether one server counts as active: it runs; the picture server also
 *  while it draws. A failed picture server is not active. */
export function serverActive(name) {
  return isRunning(name, serverstand[name])
}
