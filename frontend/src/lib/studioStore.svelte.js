/*
  The picture studio's own store: every value it shows, the picture in its
  area, the mask's picture and the model — kept once, in the settings
  cascade's global scope under `bildfenster` (`app/bildfensterwahl.py`
  checks it), so the program holds it and it stands after a restart. It
  belongs to no chat: switching, creating or deleting a chat never reaches
  it.

  Two rules this module exists for, the same ones a chat's store needed:

  WHOLE OBJECTS. A scope holds one row per setting and writing it replaces
  the row. The last known full object is kept here, and a write sends it
  whole.

  NOTHING BEFORE THE FIRST READ. Reading is a request, and the studio does
  not stand still while it is in flight. A write that starts first lands on
  the defaults and takes the sibling fields with it.
*/

import { api } from './api.js'

const KEY = 'bildfenster'

export const studioStore = $state({
  /* The values the studio holds of its own, and nothing else: a value
     nobody set is not in here, so it is never written and the studio shows
     the model's start value for it. */
  value: {},
  loaded: false,
  /* What the read failed with, in the words of the failed request; empty
     while it has not failed. A failed read is no read: nothing is shown as
     the studio's and nothing is written. */
  error: '',
})

let request = null
/* Reads the store once; whoever needs the outcome awaits the same promise.
   Settled when the store is read or the read has failed. */
export function readStudioStore() {
  request ??= api.einstellungAufgeloest(KEY)
    .then((answer) => {
      studioStore.value = { ...answer?.wert }
      studioStore.loaded = true
    })
    .catch((failure) => {
      studioStore.error = String(failure?.message || failure)
      // A failed read may be tried again when the studio opens next.
      request = null
    })
  return request
}

/* Long enough that a typed sentence is one request, short enough that a
   quick close still finds it — and the page going away flushes what is
   left. */
const DELAY = 250
let timer = null
let pending = false

function flush() {
  timer = null
  if (!pending) return
  pending = false
  api.einstellungSetzen('global', KEY, { ...studioStore.value }).catch(() => {})
}

/* Puts the changed values on top of the known ones and sends the whole
   object. Before the read there is nothing to write on top of. */
export function writeStudioStore(part) {
  if (!studioStore.loaded) return
  Object.assign(studioStore.value, part)
  pending = true
  if (timer) clearTimeout(timer)
  timer = setTimeout(flush, DELAY)
}

if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', () => {
    if (timer) clearTimeout(timer)
    flush()
  })
}
