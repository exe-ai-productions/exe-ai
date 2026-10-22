/*
  Whether a new chat would change nothing on screen.

  The buttons that start a new chat (the pen in the phone's head, the plus of
  the desktop's sign bar) stand dimmed while this holds, so none of them looks
  usable and does nothing.
*/

import { zustand } from './zustand.svelte.js'

/* No chat is open, no message stands in the list, and the side sheet is
   already the chat list. */
export function newChatIdle() {
  return !zustand.aktiverChat && zustand.nachrichten.length === 0 && zustand.seitenblatt === 'chats'
}
