/*
  What one conversation left standing in the interface.

  Switching chats used to hand back an empty picture window and a view
  scrolled to the end: the prompt, the negative and the seed plan of the
  chat being left were simply gone, and coming back looked like starting
  over. They live in the settings cascade under `chat:<id>` now
  (`app/bildfensterwahl.py`, `app/scrollwahl.py`), so the program holds them
  and a second window on the same service sees the same thing.

  Three rules this module exists for — the same three the app-wide look
  needed (`lib/anzeige.js`), plus one that is only true here:

  WHOLE OBJECTS. A scope holds one row per setting and writing it replaces
  the row. Merging happens BETWEEN scopes, not inside one, so sending only
  the field that changed would drop its siblings. The last known full object
  is kept here for that.

  NOTHING BEFORE THE FIRST READ. Reading is a request, and the window does
  not stand still while it is in flight. A write that starts first lands on
  the DEFAULTS and takes the sibling fields with it.

  AND: EVERY WRITE CARRIES ITS OWN CHAT. Writes are collected so that typing
  is not one request per keystroke — but a chat can be switched while one is
  still waiting, and that pending value belongs to the chat it was typed in,
  not to the one now on screen. So the chat id travels with the write, and
  switching flushes what is waiting before it loads the next one.
*/

import { api } from './api.js'

export const VORGABE_SCROLL = { am_boden: true, versatz: 0 }

const SCHLUESSEL = ['bildfenster', 'scrollstelle']

export const chatanzeige = $state({
  /* Which chat the values below belong to. Never read them without it: a
     component that renders while the next chat is still loading would
     otherwise show the previous conversation's prompt as if it were this
     one's. */
  chatId: null,
  geladen: false,
  /* What the read of this chat's store failed with, in the words of the
     failed request; empty while it has not failed. A failed read is no
     read — nothing is shown as the chat's and nothing is written — but
     nothing waits for it any longer either. */
  readError: '',
  /* The picture values this chat holds of its own, and nothing else: a
     value nobody set for the chat is not in here, so it is never written
     as the chat's own and the studio shows the model's start value for it
     (lib/studio.svelte.js `werteFuellen`). */
  bildfenster: {},
  scrollstelle: { ...VORGABE_SCROLL },
})

/* Picture values can stand in the window while no chat is open; they belong
   to no store yet. Whoever shows them hands in a reader: asked with the id
   of a chat just created from this window, it gives back what that chat's
   store starts with, or null (lib/studiozeichnen.svelte.js). */
export const chatless = { pictureValues: null }

/* Long enough that a typed sentence is one request, short enough that a
   chat switch a moment later still finds it — and the switch flushes what
   is left anyway. */
const VERZOEGERUNG = 250

/* Pending writes, keyed `chat:<id>|<schluessel>` so two chats can each have
   one waiting without overwriting each other. */
const offen = new Map()
let uhr = null

function schreiben() {
  uhr = null
  for (const [, eintrag] of offen) {
    api
      .einstellungSetzen(`chat:${eintrag.chatId}`, eintrag.schluessel, eintrag.wert)
      .catch(() => {})
  }
  offen.clear()
}

function merken(chatId, schluessel, wert) {
  offen.set(`chat:${chatId}|${schluessel}`, { chatId, schluessel, wert })
  if (uhr) clearTimeout(uhr)
  uhr = setTimeout(schreiben, VERZOEGERUNG)
}

function ausschreiben() {
  if (uhr) clearTimeout(uhr)
  uhr = null
  if (offen.size) schreiben()
}

/* Whatever is still waiting when the page goes away goes out now — the last
   sentence of a session must not be the one that is lost. */
if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', ausschreiben)
}

function speichern(schluessel, teil) {
  const stand = chatanzeige[schluessel]
  Object.assign(stand, teil)
  // Before the read came back there is nothing to write on top of, and no
  // chat this reliably belongs to.
  if (!chatanzeige.geladen || !chatanzeige.chatId) return
  merken(chatanzeige.chatId, schluessel, { ...stand })
}

/* The picture studio's write of a chat's picture values
   (lib/studio.svelte.js). */
export function bildfensterAusDemStudio(teil) {
  speichern('bildfenster', teil)
}

export function scrollstelleSpeichern(teil) {
  speichern('scrollstelle', teil)
}

/* The read of the open chat's store, for whoever must not act before it has
   an outcome (a draw from the studio): settled once the store is read, the
   read has failed (`readError`), or another chat was opened meanwhile. */
let reading = Promise.resolve()
export const chatStateRead = () => reading

/**
 * Everything this chat left standing, in one read.
 *
 * Call it on opening a chat. What was still waiting for the PREVIOUS chat
 * goes out first — it belongs to that conversation, and a moment later this
 * module is pointing at another one.
 */
export function chatZustandLaden(chatId) {
  reading = readChatState(chatId)
  return reading
}

async function readChatState(chatId) {
  ausschreiben()
  chatanzeige.geladen = false
  chatanzeige.readError = ''
  chatanzeige.chatId = chatId
  if (!chatId) {
    chatanzeige.bildfenster = {}
    chatanzeige.scrollstelle = { ...VORGABE_SCROLL }
    return
  }
  let daten
  try {
    daten = await api.einstellungAufgeloestViele(SCHLUESSEL, { chat: chatId })
  } catch (error) {
    // The service could not say. Nothing counts as read, so nothing is shown
    // as this chat's and nothing is written back — a window that never saw
    // the truth must not overwrite it.
    if (chatanzeige.chatId === chatId) chatanzeige.readError = String(error.message || error)
    return
  }
  /* Another chat may have been opened while this was in flight; its own
     read is the one that counts. */
  if (chatanzeige.chatId !== chatId) return
  chatanzeige.bildfenster = { ...(daten.bildfenster?.wert || {}) }
  chatanzeige.scrollstelle = { ...VORGABE_SCROLL, ...(daten.scrollstelle?.wert || {}) }
  chatanzeige.geladen = true
}
