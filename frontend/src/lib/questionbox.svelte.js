/*
  The one question standing in a chat, and what the user did with it.

  A tool's permission, the model's own question (ask_user) and the question
  of an agent this chat started wait for the user in the same card over the
  chat column. The bar draws it and the
  window's Escape key pushes it away, so both ask this one place which
  question stands, whether "later" was pressed for it and what was typed
  into its own-answer row.
*/

import { zustand } from './zustand.svelte.js'
import { agentQuestions, questionOpen } from './agentchat.svelte.js'

/* Per chat and per question: whether "later" pushed it away, and the words
   typed for it and not sent yet. Kept by the question's key, so nothing
   carries over to the next question — and several agents asking at once
   each keep their own, rather than one pushing the other's "later" out.
   Nothing is swept when a question goes: a stream that is picked up again
   drops its question and replays the same one, which must come back still
   pushed away and with its words; an entry is a flag and a line of text.
   The key is the kind, the run and the call: a question asked through
   ask_user follows its own permission and the two share one call, and a
   call id alone may repeat in another run. */
const held = $state({})

/* The question of an agent the user picked in the agents column. An agent
   that waits in another chat, in the archive, in a schedule or without a
   chat has no place in this chat's row; picking it puts its question in the
   card all the same, as the one question standing. Kept with the chat it was
   picked in and the call it was picked for, so it does not travel into the
   next conversation and the same agent's next question does not stand up by
   itself. */
const picked = $state({ chatId: null, jobId: null, callId: null })

/* What an agent's question looks like to the row and to the card. */
function agentEntry(chatId, job) {
  return {
    kind: 'agent',
    question: {
      ...job.question,
      chatId,
      generationId: job.id,
      aufrufId: job.question.aufruf_id,
      jobId: job.id,
      agentName: job.agent,
    },
  }
}

/* Everything waiting on the user in this chat, in one row: the permission of
   a tool, the model's own question, then the questions of the agents this
   chat started. Each carries its place in the row and the length of the row,
   whether it stands in the card or was pushed away with "later" — a question
   pushed away stays in the row and so stays reachable. */
export function waitingQuestions(chatId) {
  const tool = zustand.werkzeugfrage[chatId]
  const ask = zustand.benutzerfrage[chatId]
  const agents = agentQuestions(chatId).map((job) => agentEntry(chatId, job))
  const waiting = [
    ...(tool ? [{ kind: 'tool', question: tool }] : []),
    ...(ask ? [{ kind: 'ask', question: ask }] : []),
    ...agents,
  ]
  return waiting.map((standing, index) => ({ ...standing, position: index + 1, total: waiting.length }))
}

/* The one question of a row the card shows: the first that "later" did not
   push away, and when all were pushed away, the first — its chip brings it
   back. A question pushed away never hides the ones behind it. */
export function standingIn(chatId, waiting) {
  return waiting.find((standing) => !isDeferred(chatId, standing)) ?? waiting[0] ?? null
}

/* The question of the agent picked in the agents column, while it is not in
   this chat's row. It stands first and counts the row behind it, so "1 of 3"
   tells that two more wait; with nothing behind it, "1 of 1". */
export function pickedQuestion(chatId, behind = 0) {
  if (!picked.jobId || picked.chatId !== chatId) return null
  const job = zustand.auftraege.find((item) => item.id === picked.jobId)
  if (!questionOpen(job) || job.question.aufruf_id !== picked.callId) return null
  if (chatId && job.chat_id === chatId) return null
  return { ...agentEntry(chatId, job), position: 1, total: behind + 1 }
}

/* What the card shows: the picked agent's question until "later" pushes it
   away, otherwise the row's. */
export function standingWith(chatId, waiting) {
  const asked = pickedQuestion(chatId, waiting.length)
  if (asked && !isDeferred(chatId, asked)) return asked
  return standingIn(chatId, waiting)
}

export function standingQuestion(chatId) {
  return standingWith(chatId, waitingQuestions(chatId))
}

/* Whether the card is up over this chat: a question stands and "later" did
   not push it away. While it is, the chat behind it is out of reach for keys
   as well as for the eye; a question pushed away makes nothing unreachable. */
export function questionCardStands(chatId) {
  const standing = standingQuestion(chatId)
  return Boolean(standing) && !isDeferred(chatId, standing)
}

/** A click on an agent that waits on the user: its question stands in the
 *  card. An agent of this chat's row comes to the front of it, the ones that
 *  stood before it wait behind their chips; any other agent's question
 *  stands alone. Returns whether there was a question to show. */
export function showAgentQuestion(chatId, job) {
  if (!questionOpen(job)) return false
  const waiting = waitingQuestions(chatId)
  const index = waiting.findIndex(
    (standing) => standing.kind === 'agent' && standing.question.jobId === job.id,
  )
  if (index >= 0) {
    for (const before of waiting.slice(0, index)) deferQuestion(chatId, before)
    resumeQuestion(chatId, waiting[index])
    picked.jobId = null
    return true
  }
  picked.chatId = chatId
  picked.jobId = job.id
  picked.callId = job.question.aufruf_id
  resumeQuestion(chatId, pickedQuestion(chatId))
  return true
}

export function questionKey(standing) {
  if (!standing) return null
  const { generationId = '', aufrufId = '' } = standing.question
  return `${standing.kind}:${generationId}:${aufrufId}`
}

function entry(chatId, standing) {
  const key = questionKey(standing)
  return key ? (held[chatId]?.[key] ?? null) : null
}

function hold(chatId, standing) {
  const key = questionKey(standing)
  if (!key) return null
  held[chatId] ??= {}
  held[chatId][key] ??= { deferred: false, draft: '' }
  return held[chatId][key]
}

export function isDeferred(chatId, standing) {
  return Boolean(entry(chatId, standing)?.deferred)
}

export function deferQuestion(chatId, standing) {
  const current = hold(chatId, standing)
  if (current) current.deferred = true
}

export function resumeQuestion(chatId, standing) {
  const current = entry(chatId, standing)
  if (current) current.deferred = false
}

export function ownDraft(chatId, standing) {
  return entry(chatId, standing)?.draft ?? ''
}

export function keepOwnDraft(chatId, standing, text) {
  const current = hold(chatId, standing)
  if (current) current.draft = text
}
