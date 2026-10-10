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
import { agentQuestions } from './agentchat.svelte.js'

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

export function standingQuestion(chatId) {
  const tool = zustand.werkzeugfrage[chatId]
  const ask = zustand.benutzerfrage[chatId]
  /* The chat's own model first, then the agents this chat started, each
     standing on a question of its own. With several, one after the other:
     the first one "later" did not push away, and when all were pushed away,
     the first — its chip brings it back. A question pushed away never hides
     the ones behind it. */
  const agents = agentQuestions(chatId).map((job, index, all) => ({
    kind: 'agent',
    question: {
      ...job.question,
      chatId,
      generationId: job.id,
      aufrufId: job.question.aufruf_id,
      jobId: job.id,
      agentName: job.agent,
      position: index + 1,
      total: all.length,
    },
  }))
  const waiting = [
    ...(tool ? [{ kind: 'tool', question: tool }] : []),
    ...(ask ? [{ kind: 'ask', question: ask }] : []),
    ...agents,
  ]
  return waiting.find((standing) => !isDeferred(chatId, standing)) ?? waiting[0] ?? null
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
