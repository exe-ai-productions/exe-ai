/*
  What the agents sign on the rail has to say, in one dot.

  A job list can hold several truths at once — one run going, another
  standing on a question, a third that fell over an hour ago. The sign has
  exactly one dot, so the order of precedence IS the feature: get it wrong
  and the rail reports the least urgent of the three.

    blau   a job is running
    gelb   a job is waiting for your approval
    rot    the newest ended job failed, and nobody has looked
    gruen  the newest ended job finished, and nobody has looked
    still  nothing worth a colour

  Running beats waiting because something in motion is the more urgent
  fact; a failure beats a success because a success needs nothing from you.

  "Nobody has looked" used to be a watermark: the moment the agents panel
  was open, everything in the list counted as seen, and one timestamp said
  that about all of them at once. Opening the panel once therefore cleared
  nine reports nobody had read. So a run answers for itself now — it is
  seen when IT was opened, and opening the panel is not reading anything.

  The timestamp stays, in the one job it was always right about: it is the
  floor. Whatever ended before this page existed is not news, because
  nobody was sitting in front of it. Everything after it is asked run by
  run.

  Both live in memory only, like `fehlerChats` in chatringe.svelte.js —
  after a restart there is no run to walk over to anymore, so the mark
  would be a claim without a subject. They sit here rather than in the big
  shared state for the same reason that file's do: the fact belongs to the
  dot that draws it.
*/

import { meldungenZuAuftragSchliessen, zustand } from './zustand.svelte.js'
/* The one distinction both displays of a run share — handed on to a
   continuation, or a real ending. It stands in a file of its own because
   this dot and the reports list disagreed about the same run while each of
   them kept a copy of it. */
import { weitergereicht } from './laufstand.js'

/* The states a job is over in, and what each is worth to the dot. Mirrors
   ENDZUSTAENDE in app/db/repositories/auftraege.py — `unterbrochen` counts
   as a failure here because a run that stopped without a result is
   something you have to go and look at. That sentence was true of every
   `unterbrochen` run when it was written; since e959e99 it is true of one
   of its two kinds, and `weitergereicht` is the other.

   A colour here is what an ending is worth IF it reaches the dot. Whether
   it does is `worthReading` below: an abort is red only where it left a
   row to open — a schedule's run, or a run that had written something. */
const AUSGANG = {
  fertig: 'gruen',
  abgebrochen: 'rot',
  gescheitert: 'rot',
  unterbrochen: 'rot',
}

/* Set to "now" at load: whatever ended while the program was not running
   is seen, not news.

   That mark is also why the one red `unterbrochen` left — a run a service
   restart cut off — never reaches this dot in the shipped program. The
   sweep writing those rows runs while the service starts (app/main.py),
   and the window loads this page only once the service answers
   (fenster-electron/main.js), so the mark is always the younger of the
   two and the dot stays quiet. That is the rule working, not a hole in
   it: nobody was sitting in front of a run that ended before the window
   existed, and the row is in the reports list with its reason, where it
   depends on no watermark at all.

   Where it does reach the dot is the case it was written for: a page that
   stayed open across a service restart. Somebody was watching, the run
   died under them, and red is the answer. */
export const agentenampel = $state({
  /* The floor: nothing that ended before this moment is news. */
  seit: Date.now(),
  /* The runs somebody has actually opened since then. */
  gesehene: [],
})

/** One run was looked at. Not the panel — the run.
 *
 *  The notice standing for it goes with it: a notice told to wait for its
 *  run instead of for a clock has exactly this as its clock. */
export function auftragGesehen(id) {
  if (!id) return
  if (!agentenampel.gesehene.includes(id)) agentenampel.gesehene.push(id)
  meldungenZuAuftragSchliessen(id)
}

/** Is this run over? The four states of `AUSGANG`, asked where somebody
 *  needs to know whether there is anything to have read yet. */
export function istBeendet(auftrag) {
  return Boolean(auftrag) && Object.hasOwn(AUSGANG, auftrag.state)
}

/** Does this ended run have something to open in the reports list?
 *
 *  A report — or an ending worth reading without one: a failure, a run a
 *  service restart cut off, and a schedule's run that was stopped, because
 *  the list is the one place that last one can still be seen. A finished
 *  run with nothing to say and a run stopped by hand are neither.
 *
 *  It stands here, and the reports list takes it from here, because the dot
 *  loses a colour in exactly one way: the run is opened, and only a row of
 *  that list can be opened. While the list kept this to itself, a run
 *  stopped by hand painted the dot red and had no row to open — red until
 *  the page was loaded again. One function answers for both, so neither
 *  can change its mind alone. */
export function worthReading(job) {
  return Boolean(
    job.result ||
      job.state === 'gescheitert' ||
      job.state === 'unterbrochen' ||
      (job.state === 'abgebrochen' && job.cronjob_id),
  )
}

/** Is this run still waiting to be looked at? */
export function auftragUngesehen(job) {
  if (!job) return false
  if (abschluss(job) <= agentenampel.seit) return false
  return !agentenampel.gesehene.includes(job.id)
}

/* When a job last moved. `updated_at` is the state change — the moment it
   ended — where `created_at` is only when it was started. */
function abschluss(job) {
  const zeit = Date.parse(job.updated_at || job.created_at || '')
  return Number.isNaN(zeit) ? 0 : zeit
}

export function punktfarbe() {
  const jobs = zustand.auftraege || []
  if (jobs.some((j) => j.state === 'laeuft')) return 'blau'
  if (jobs.some((j) => j.state === 'wartet')) return 'gelb'
  /* The newest ended one decides, and it is looked up rather than taken
     from the list's head: the server hands the list out newest-first, but
     a dot that would report the wrong run if that ever changed is a dot
     built on somebody else's ORDER BY. */
  let neuester = null
  for (const job of jobs) {
    if (!Object.hasOwn(AUSGANG, job.state)) continue
    /* A run that handed its work on is no ending here at all, so it
       decides the dot not at all — skipped rather than merely painted
       'still', because a chain that is still going must not push an older
       unseen report or failure off the dot either.

       The failure counter and CRONJOB_AUSGAENGE
       (app/db/repositories/auftraege.py) leave such a run out too, but they
       are not this rule and must not be read as one: those two leave out
       EVERY `unterbrochen` row, `dienst_neustart` included. This leaves out
       the handed-on ones only. */
    if (weitergereicht(job)) continue
    /* Nothing to open, nothing to colour. Skipped like a handed-on run
       rather than painted 'still', and for the same reason: a run stopped
       by hand a minute ago must not push an older failure nobody has
       opened off the dot. */
    if (!worthReading(job)) continue
    /* Asked per run, not against one watermark: a newer report somebody
       has read must not push an older one nobody has read off the dot. */
    if (!auftragUngesehen(job)) continue
    if (!neuester || abschluss(job) > abschluss(neuester)) neuester = job
  }
  if (!neuester) return 'still'
  return AUSGANG[neuester.state]
}
