/*
  A run that ended says what it did — once, and in its own words.

  Two things were missing between a finished run and the person who started
  it. Nothing turned the ending into a report at all, and there was nothing
  to put in one: a toast reading "done" is not a message, it is a bell.
  With three agents going, whoever hears it knows exactly as much
  afterwards as before.

  The run already carries the answer. It ends with a `result` — its own
  closing text — and when it has none it ends with a reason, whose
  translations have stood in `jobs.grund.*` all along. Both travel on the
  job row; neither was ever read for this.

  THE ORDER, so that "done" never stands alone:

    1. the first sentence of the result, cut to one line
    2. no result but a reason → the reason in words
    3. neither → the agent and how it ended. The last resort, not the
       normal case.

  And the agent's name is in front of all three, because three runs at once
  produce three notices and each has to say which one it is about.

  HOW THE ENDING IS NOTICED. From the job list the rail already fetches on
  its own slow tick — no second timer, no second source of truth. The list
  is complete, so an ending cannot slip between two ticks; what it does not
  carry is the MOMENT, which is why the service now records that for itself
  (app/auftragsende.py).

  Two rules, the same two the service applies, because both sides answer
  for their own half:

    * Every ending is reported once. The ids already reported are kept
      here, and anything that ended before this window loaded is not news
      at all — the same floor, and the same comparison, the dot on the rail
      keeps.
    * A run that handed its work on has not ended (`weitergereicht`), so a
      chain of ten links reports once, not ten times.

  An abort is the third case and is left out on purpose: the user stopped
  that run a second ago. The service leaves it out of its own announcements
  for the same reason.

  AND ONE THING THAT IS NOT AN ENDING. A run that called `ask_user` stops and
  waits, and that is worth exactly as much as a finished one: nobody is going
  to walk past the agents panel on the off-chance. It is reported here rather
  than from a second watcher, because it is the same list, the same "once"
  rule and the same switch — the notification settings offer three reporters
  (done, waiting, failed), and until now the middle one could not report
  anything at all.

  Once per QUESTION, not per run: a run that asks three times has three
  things to say. The call's id is what tells them apart.
*/

import { weitergereicht } from './laufstand.js'
import { melden } from './meldewesen.svelte.js'
import { agentName } from './agentmarke.js'
import { t } from './texte.svelte.js'

/* The states a run is over in. Mirrors ENDZUSTAENDE in
   app/db/repositories/auftraege.py. */
const ENDEN = ['fertig', 'gescheitert', 'abgebrochen', 'unterbrochen']

/* What an ending is worth as an occurrence. An abort is missing on
   purpose — it is not a fourth kind, it is the one that says nothing. */
const VORFALL = { fertig: 'fertig', gescheitert: 'fehler', unterbrochen: 'fehler' }

/* Long enough for a sentence, short enough that three of them stacked stay
   readable. The toast wraps, so this is about attention, not pixels. */
const SATZ_GRENZE = 140

/* Runs already reported. Memory only, like every other "nobody has looked"
   mark in the house: after a restart there is nothing to walk over to. */
const gemeldet = new Set()

/* Questions already reported, by the id of the call that asked. A run can
   ask several times, and each one is its own piece of news. */
const gefragt = new Set()

/* Whatever ended before this moment is history, not news — nobody was
   sitting in front of it.

   A floor rather than "skip the first list": the first list this module is
   handed is the EMPTY one the state starts out with, because the effect
   that feeds it runs on mount and the rail's fetch answers a moment later.
   Skipping that one skips nothing, and the whole job history then arrives
   as news — a salvo of notices about runs that ended days ago, each one
   standing until that old run is opened.

   Same rule and same comparison as the dot on the rail
   (`agentenampel.seit`), which is the point: the notice and the dot speak
   about exactly the same set of runs. */
const SEIT = Date.now()

function nachDemStart(auftrag) {
  const zeit = Date.parse(auftrag.updated_at || auftrag.created_at || '')
  return !Number.isNaN(zeit) && zeit > SEIT
}

/** Why a run ended, in words — for every ending that is not a plain
 *  'fertig'.
 *
 *  Here rather than in the reports list because both read it now, and one
 *  expression written down twice is how two displays of the same run come
 *  apart. An unknown reason shows ITSELF rather than its key: a run that
 *  died on an error carries the message inline ('fehler: …',
 *  app/api/v1/auftraege.py) and can have no catalogue entry, and t()
 *  answers a missing key with the key, which on screen would read
 *  `jobs.grund.fehler: connection reset`. */
export function grundtext(auftrag) {
  const grund = auftrag.end_reason
  if (!grund || grund === 'fertig') return ''
  const schluessel = 'jobs.grund.' + grund
  const text = t(schluessel)
  return text === schluessel ? grund : text
}

/* The first sentence of a report, on one line. A report is markdown and
   can be pages long; what belongs in a notice is its opening. */
function ersterSatz(text) {
  const sauber = (text || '').replace(/\s+/g, ' ').trim()
  if (!sauber) return ''
  const ende = sauber.search(/[.!?](\s|$)/)
  const satz = ende > 0 ? sauber.slice(0, ende + 1) : sauber
  return satz.length > SATZ_GRENZE ? `${satz.slice(0, SATZ_GRENZE - 1).trimEnd()}…` : satz
}

/** What one ended run has to say, name first. Exported for the test — the
 *  ranking is the point of this file. */
export function meldetext(auftrag) {
  const satz =
    ersterSatz(auftrag.result) ||
    grundtext(auftrag) ||
    t('jobs.zustand.' + auftrag.state)
  return `${agentName(auftrag.agent)} · ${satz}`
}

/**
 * Hand this the job list on every refresh. Anything that ended since the
 * last one is reported, once.
 */
export function auftraegeBeobachten(jobs) {
  const liste = jobs || []
  for (const auftrag of liste) {
    /* Standing on a question is not an ending, and it comes first: the run
       is still alive, so none of the rules below apply to it. */
    if (auftrag.state === 'wartet' && auftrag.question?.aufruf_id) {
      const schluessel = auftrag.question.aufruf_id
      if (!gefragt.has(schluessel)) {
        gefragt.add(schluessel)
        if (nachDemStart(auftrag)) {
          melden({
            was: 'wartet',
            von: 'agent',
            text: `${agentName(auftrag.agent)} · ${auftrag.question.frage}`,
            auftragId: auftrag.id,
            agent: auftrag.agent,
          })
        }
      }
      continue
    }
    if (!ENDEN.includes(auftrag.state)) continue
    /* Handed on is not an ending: the work is still going, on a
       continuation that will report for the whole chain when it stops. */
    if (weitergereicht(auftrag)) continue
    if (gemeldet.has(auftrag.id)) continue
    gemeldet.add(auftrag.id)
    if (!nachDemStart(auftrag)) continue
    const was = VORFALL[auftrag.state]
    if (!was) continue
    /* The name stays IN the text — it is the first thing a notice about a
       run has to say. `agent` names it a second time so the notice can
       write that part in the agent's own colour. */
    melden({
      was,
      von: 'agent',
      text: meldetext(auftrag),
      auftragId: auftrag.id,
      agent: auftrag.agent,
    })
  }
}
