/*
  The question card of a chat: what waits on the person — a permission the
  model asks for, a question it puts, a question of a helper agent — which of
  them stands in the card, which "later" pushed aside, and the ways to answer.

  Called while a page is made, by the desktop bar and by the phone page.
  `fokus` gives the field the focus again once the card has gone (a page
  without a keyboard to bring up leaves it out); `showTranscript` is whether
  a helper agent's question brings its transcript into the agents view, which
  only a page that has that view wants.
*/

import { tick, untrack } from 'svelte'
import {
  deferQuestion, isDeferred, questionCardStands, questionKey, resumeQuestion, standingWith, waitingQuestions,
} from './questionbox.svelte.js'
import { answerAgentQuestion, openTranscript } from './agentchat.svelte.js'
import { zustand, werkzeugfrageBeantworten, benutzerfrageBeantworten, aktuellesModell } from './zustand.svelte.js'

export function useFragekarte({ fokus = () => {}, showTranscript = true } = {}) {


  /* The question standing in this chat, and whether "later" pushed it
     away. The card and the chip that brings it back both read this. */
  /* The model's own question of this chat is there but was pushed away with
     "later": typing in the field is then not its answer. */
  function questionHidden(chatId) {
    const ask = zustand.benutzerfrage[chatId]
    return Boolean(ask) && isDeferred(chatId, { kind: 'ask', question: ask })
  }

  const waiting = $derived(waitingQuestions(zustand.aktiverChat))

  const standing = $derived(standingWith(zustand.aktiverChat, waiting))

  const questionDeferred = $derived(isDeferred(zustand.aktiverChat, standing))

  const cardStands = $derived(questionCardStands(zustand.aktiverChat))

  /* Every question of the chat that "later" pushed away, one chip each —
     also while another question stands in the card. */
  const pushedAway = $derived(waiting.filter((item) => isDeferred(zustand.aktiverChat, item)))

  const modelName = $derived(aktuellesModell()?.name ?? '')

  /* The card takes the focus along when it goes: after an answer or
     "later" it comes back to the field, so the next keys are typing
     rather than falling to the window. The bar is out of reach while the
     card stands, so the focus waits for the render that gives it back. */
  function focusFieldAfterRender() {
    tick().then(() => fokus())
  }

  function answerTool(allowed, always = false, words = null) {
    werkzeugfrageBeantworten(allowed, always, zustand.aktiverChat, words)
    focusFieldAfterRender()
  }

  function answerAsk(text) {
    if (standing?.kind === 'agent') {
      answerAgentQuestion(standing.question.jobId, standing.question.aufrufId, text)
    }
    else benutzerfrageBeantworten(text)
    focusFieldAfterRender()
  }

  /* An agent's question brings its transcript along in the agents view,
     and the transcript follows when the card moves on to the next agent's.
     Offered, not forced: a view the user closed stays closed. */
  const askingJob = $derived(standing?.kind === 'agent' ? standing.question.jobId : null)

  $effect(() => {
    if (showTranscript && askingJob) untrack(() => openTranscript(askingJob, { asked: false }))
  })

  function later() {
    deferQuestion(zustand.aktiverChat, standing)
    focusFieldAfterRender()
  }

  /* The chip goes when it brings its card back; the focus it held goes to
     the field, and from there the card takes it as it appears. The card
     that stood until now takes the chip's place, so the question brought
     back is the one that shows. */
  function resume(item) {
    if (standing && !questionDeferred && questionKey(standing) !== questionKey(item)) {
      deferQuestion(zustand.aktiverChat, standing)
    }
    resumeQuestion(zustand.aktiverChat, item)
    focusFieldAfterRender()
  }

  return {
    questionHidden,
    answerTool,
    answerAsk,
    later,
    resume,
    get standing() {
      return standing
    },
    get cardStands() {
      return cardStands
    },
    get pushedAway() {
      return pushedAway
    },
    get modelName() {
      return modelName
    },
  }
}
