/*
  What sets the message queue in motion, for the page that shows the open chat.

  The queue itself (lib/warteschlange.svelte.js) and the run that sends from
  it (lib/chatlauf.svelte.js) are shared, but nothing in them wakes on its
  own: a page has to watch the moments that matter. The desktop page and the
  phone page both call this while they are made, so a message that waits goes
  out the same way on both — and a page that forgot to would leave it
  standing until the next end of a run in the open chat.

  Called while a page is made: it creates effects, which end with the page.
*/

import { untrack } from 'svelte'
import { zustand, laufVon } from './zustand.svelte.js'
import { chatRun } from './chatlauf.svelte.js'
import { chosenModelOff } from './modelle.svelte.js'
import { standingQuestion } from './questionbox.svelte.js'
import { awaitingInterrupt } from './warteschlange.svelte.js'

export function useQueueDrive() {
  const { warteschlangeWeiter, interruptForQueued, toolIsRunning } = chatRun

  /* Two moments put the line in motion: switching into a chat that has
     somebody waiting, and a run coming to an end. Both are watched here,
     so neither has to remember to call the other.

     Everything else is read untracked on purpose. Firing takes the entry
     OUT of the queue, so an effect that also watched the queue would be
     woken by its own write — the classic self-feeding loop. */
  $effect(() => {
    void zustand.aktiverChat
    // The set of running chats, not the container: a run starting or ending
    // adds or removes a key, and that is what has to wake this.
    void Object.keys(zustand.laeuft).length
    /* And the send-in-flight marks. `senden` holds its chat's mark until
       `antwortHolen` has returned — which is AFTER that run's own end has
       released `laeuft` and woken this effect once, into a chat still
       marked as sending. Without this line nothing woke it again when the
       mark went, and a message queued during an ordinary answer stayed in
       the queue until the next chat switch. */
    void Object.keys(zustand.sendet).length
    /* And the quick picker's switch: a model switched on again, or one that
       is on chosen, frees the queue a switched-off model was holding. */
    void chosenModelOff()
    untrack(warteschlangeWeiter)
  })

  /* A message waits while the open chat's answer runs: the answer is stopped
     and the message follows. Only the open chat — the queue only moves there —
     and not while a question stands or the model is off:
     there the message could not go out, and the answer would be cut for
     nothing. A running tool wakes this again at its result. */
  $effect(() => {
    const chatId = zustand.aktiverChat
    if (!chatId || !laufVon(chatId) || chosenModelOff()) return
    if (!awaitingInterrupt(chatId).length || toolIsRunning(chatId) || standingQuestion(chatId)) return
    untrack(() => interruptForQueued(chatId))
  })
}
