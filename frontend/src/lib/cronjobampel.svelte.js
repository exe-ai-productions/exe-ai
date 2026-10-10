/*
  What the cronjobs sign on the rail has to say, in one dot.

    rot    the cron service does not answer, or the last run of an entry
           came back failed and nobody has looked
    blau   an entry is firing a run right now
    gruen  an entry's last run came back good and nobody has looked
    still  nothing worth a colour — no entry, or entries standing quiet

  No yellow. A cron has no state that waits for you: it fires or it does
  not, and what it produced is read afterwards.

  Red comes before blue here, unlike on the agents sign. A cron dot is
  fed by an answer from the service, and when that answer is missing there
  is no honest way to claim anything is running — the missing answer IS the
  more urgent fact, and a blue dot over a service that is gone would be the
  dot lying about the one thing it can still know.

  Nothing else in the program keeps the cron list in state — the settings
  window and the entry mask each fetch it once when they open. So the list
  lives here, refreshed by the rail's own slow tick, and the panel keeps
  fetching its own the way it always did.

  The watermark is memory only, like the one on the agents sign.
*/

import { api } from './api.js'
import { zustand } from './zustand.svelte.js'

export const cronampel = $state({
  liste: [],
  /* Kept apart from an empty list: "no entries" and "could not ask" are
     different facts and the dot owes the user the difference. */
  fehler: false,
  gesehen: Date.now(),
})

export function cronjobsGesehen() {
  cronampel.gesehen = Date.now()
}

/* The quiet load, for the rail's background tick: a failed fetch turns the
   dot red and says nothing else — a restarting service must not answer a
   mere overview with a toast salvo. */
export async function standLaden() {
  try {
    cronampel.liste = await api.cronjobs()
    cronampel.fehler = false
  } catch {
    cronampel.fehler = true
  }
}

/* `zuletzt_ausgeloest` is the due time the entry last acted on. It is the
   only moment the list carries — the outcome beside it has no stamp of its
   own — so it is what "since you last looked" is measured against. */
function ungesehen(termin) {
  const zeit = Date.parse(termin.zuletzt_ausgeloest || '')
  return !Number.isNaN(zeit) && zeit > cronampel.gesehen
}

/* Is an entry firing right now?

   The job list is the only place a running run appears, and every run it
   hands out names the cron entry that fired it (`cronjob_id`,
   AuftragAntwort, app/api/v1/schemas.py) — or nothing, for a run somebody
   started by hand. Matching the two lists on it says exactly what it looks
   like it says: this entry fired this run.

   Which is what the text comparison this replaces could not say. A firing
   does not hand the run the entry's task verbatim — the entry's note and
   its goal are glued on at firing time (`auftragstext`, app/cronablauf.py)
   — so every entry that keeps a note or watches a goal ran under a text
   that no longer matched its own, and the dot stayed dark right through the
   runs it exists to show. In the other direction the same comparison went
   blue for a run started by hand on the same agent and the same words,
   which is nobody's schedule firing anything.

   Not `work_id`. That is the piece of work a run belongs to, and for a
   restart chain it is the ORIGIN (`werk_von`, app/api/v1/schemas.py) — the
   run a person started by hand included, which is no entry at all. A
   continuation of such a run is fired by a chain row of its own, and that
   row stands in the cron list while it runs; matched on the work, the dot
   would stay dark next to it. The entry that fired the run is the row the
   list shows, whatever the chain's origin is.

   A run whose entry has been deleted finds nothing here, which is the
   honest answer: the list the dot speaks for no longer holds that entry. */
function laeuftGerade() {
  const laufend = (zustand.auftraege || []).filter((j) => j.state === 'laeuft')
  if (!laufend.length) return false
  /* A run without a `cronjob_id` — started by hand, or handed out by an
     older service that does not send the field — names no entry, so it
     reads as "nothing firing" instead of as a wrong match. */
  const termine = new Set(laufend.map((j) => j.cronjob_id).filter(Boolean))
  return cronampel.liste.some((t) => termine.has(t.id))
}

export function punktfarbe() {
  if (cronampel.fehler) return 'rot'
  const liste = cronampel.liste || []
  if (liste.some((t) => t.letzter_ausgang === 'gescheitert' && ungesehen(t))) return 'rot'
  if (laeuftGerade()) return 'blau'
  if (liste.some((t) => t.letzter_ausgang === 'gut' && ungesehen(t))) return 'gruen'
  return 'still'
}
