/*
  What a chat row has to say about itself, in one dot.

  A list of chats used to report exactly one thing: an answer had finished
  somewhere. Everything else — that a run is going on over there, that
  something is standing still waiting for a decision, that a run fell over —
  was only visible by opening the chat. With more than one conversation in
  flight at a time that is the wrong way round: the list is where one looks
  to decide WHICH chat to open.

  So every row carries the house's status dot, and the five states it can
  wear are the five things worth walking over for:

    gelb   somebody is waiting for you — a question, a confirmation
    blau   an answer is running here
    rot    a run failed and nobody has looked at it
    gruen  an answer finished and nobody has looked at it
    leer   nothing to report; a small quiet disc keeps the rows in line

  Only one dot per row — two would make the row a dashboard, and a list of
  thirty chats cannot afford that. Which of them wins when several are true
  is decided in `ringfarbe.js`; this file only gathers the four facts the
  decision needs.
*/

import { ringAus } from './ringfarbe.js'
import { agentAsks } from './agentchat.svelte.js'
import { zustand } from './zustand.svelte.js'

/* Chats whose last run failed, until somebody opens them. The sibling of
   `fertigeChats`, and deliberately memory only: after a restart there is
   no run to point at anymore, so the mark would be a claim without a
   subject. */
export const fehlerChats = $state({ liste: [] })

export function chatFehlerMerken(id) {
  if (id && !fehlerChats.liste.includes(id)) fehlerChats.liste.push(id)
}

export function chatFehlerGesehen(id) {
  if (id && fehlerChats.liste.includes(id))
    fehlerChats.liste = fehlerChats.liste.filter((c) => c !== id)
}

/* Is this chat the one holding a question? All three pending boxes are maps
   keyed by chat id, so a question in one conversation cannot light up the
   row of another.

   THREE, not two. The job confirmation was left out, and it is the one that
   waits longest: a start_job question standing in another chat left that
   row dark, so a run that had already asked sat there unanswered with
   nothing on screen pointing at it. Every box that stops a run until
   somebody answers belongs in here — that is what the ring is for. The
   chat's waiting mark asks the same (App.svelte, laufMarke). */
export function fragtNach(chatId) {
  return (
    Boolean(zustand.werkzeugfrage[chatId]) ||
    Boolean(zustand.benutzerfrage[chatId]) ||
    Boolean(zustand.jobfrage[chatId])
  )
}

/* The three lists a row looks itself up in, each turned into a set ONCE per
   change. A row used to search the chat list and two id lists on its own;
   with a couple of thousand rows that is millions of reads of reactive
   arrays every time the list changes, and the page stood still for
   seconds. */
const laeuftInDerListe = $derived.by(
  () => new Set(zustand.chats.filter((c) => c.laeuft).map((c) => c.id)),
)
const fehlerMenge = $derived(new Set(fehlerChats.liste))
const fertigMenge = $derived(new Set(zustand.fertigeChats))

export function ringFarbe(chatId) {
  if (!chatId) return 'leer'
  /* `zustand.laeuft` only ever hears about a run THIS window started or
     watched stream in — a second window, or this same window before its
     next chat list reload, never sets it. The chat list itself now carries
     the service's own answer, so a run neither started nor
     watched here still lights the row up the moment the list is current. */
  return ringAus({
    /* An agent this chat started, standing on a question of its own, lights
       the row too: its box stands only in this chat, so from any other one
       the row is where it shows. Not part of `fragtNach` — that one names
       what stops the chat's own run, and the agent's question does not. */
    fragt: fragtNach(chatId) || agentAsks(chatId),
    laeuft: Boolean(zustand.laeuft[chatId]) || laeuftInDerListe.has(chatId),
    fehler: fehlerMenge.has(chatId),
    fertig: fertigMenge.has(chatId),
  })
}
