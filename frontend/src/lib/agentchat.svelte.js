/*
  An agent a chat started, as the chat sees it.

  The job list (`zustand.auftraege`) is the one truth: the live line reloads
  it whenever a run starts, asks, writes a reading or ends
  (lib/ereignisstrom.svelte.js). Everything here reads from it — the row at
  the answer's line, the questions in the chat's box, the yellow dot on the
  chat's row in the list — so the three can never disagree.
*/

import { api } from './api.js'
import { anbieten, leiste, moduleShow } from './arbeitsleiste.svelte.js'
import { t } from './texte.svelte.js'
import { auftraegeStillLaden, melde, zustand } from './zustand.svelte.js'

/** The job behind an agent row — the newest run of its work, so a run
 *  that handed its work on is followed to the continuation doing it now —
 *  or undefined once the list no longer carries it. */
export function chatJob(jobId) {
  if (!jobId) return undefined
  const runs = zustand.auftraege.filter((job) => job.id === jobId || job.work_id === jobId)
  return runs.sort((a, b) => (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0)).at(-1)
}

/* Answers sent and not yet taken up. A live run writes its state back a
   moment after the answer reached it, and until the list shows that, the
   question would stand in the box a second time for a second answer the
   server refuses. Kept by job and call, so the same agent's next question
   is not hidden by its last one. */
const answered = $state({})

function answerKey(jobId, callId) {
  return `${jobId}:${callId ?? ''}`
}

/** Does this job wait on the user with a question that no answer of this
 *  window is on its way to? */
export function questionOpen(job) {
  return Boolean(
    job?.state === 'wartet' &&
      job.question?.frage &&
      !answered[answerKey(job.id, job.question.aufruf_id)],
  )
}

/** The questions the agents of this chat stand on, oldest first — one per
 *  agent, the way the box shows them one after the other. */
export function agentQuestions(chatId) {
  if (!chatId) return []
  return zustand.auftraege
    .filter((job) => job.chat_id === chatId && questionOpen(job))
    .sort((a, b) => (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0))
}

/** Does an agent of this chat wait on the user? */
export function agentAsks(chatId) {
  return agentQuestions(chatId).length > 0
}

/**
 * The agent's transcript in the agents view: the view comes forward and the
 * job unfolds there (ModulAgenten.svelte reads `auftragAusgewaehlt`). A
 * click asks for it; a question arriving only offers it, and a view the user
 * closed on purpose stays closed.
 */
export async function openTranscript(jobId, { asked = true } = {}) {
  if (!jobId) return
  if (asked) await moduleShow('agenten')
  else anbieten('agenten')
  /* Picked only where the view now stands: a pick left lying would unfold
     the card hours later, the next time somebody opens the view. */
  if (leiste.offen && leiste.modul === 'agenten') zustand.auftragAusgewaehlt = jobId
}

/** The user's answer to an agent's question, from the chat's box. The
 *  question leaves the box at once; a refused answer brings it back. */
export async function answerAgentQuestion(jobId, callId, text) {
  const key = answerKey(jobId, callId)
  answered[key] = true
  try {
    await api.auftragBeantworten(jobId, text)
  } catch (error) {
    delete answered[key]
    melde(error.message || t('fehler.allgemein'), 'fehler')
  }
  await auftraegeStillLaden()
}
