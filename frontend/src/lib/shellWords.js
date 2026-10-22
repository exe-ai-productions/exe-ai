/*
  The words the window's shell shows by itself, in the interface's language.

  The shell names a few entries of the right-click menu on its own: the ones
  that act on a link or a picture; the sign in the menu bar has three of its
  own. It has no catalogue, so the page reads the words from its own and
  hands them over (preload.js). Until then, and for a word left out, the
  shell shows its English ones.

  The same way back: what the shell has to tell the user (ending the service
  from the sign's menu failed) arrives here and is shown in the page's words.

  In a browser there is no shell, and nothing is told.
*/
import { t } from './texte.svelte.js'
import { melde } from './meldewesen.svelte.js'

/* The shell's name of each word, and where the catalogue keeps it. */
const WORDS = {
  copyLink: 'menue.copy_link',
  copyLinkUnavailable: 'menue.copy_link_unavailable',
  saveImage: 'menue.save_image',
  copyImage: 'menue.copy_image',
  openWindow: 'menue.sign_open_window',
  endService: 'menue.sign_end_service',
  endProgram: 'menue.sign_end_program',
}

let listening = false
// The notice came before the catalogue did: shown when the words are there.
let noticeWaiting = false

function showStopFailed() {
  const key = 'menue.sign_stop_failed'
  const word = t(key)
  // A key the catalogue does not carry yet comes back as the key itself.
  if (word === key) {
    noticeWaiting = true
    return
  }
  noticeWaiting = false
  melde(word, 'fehler')
}

/** Tells the shell its words. Reads the catalogue, so an effect that calls
 *  it runs again whenever the language changes. */
export function tellShellWords() {
  /* Listening comes before telling: the shell hands a waiting notice over
     when the words arrive, and the page must hear it by then. */
  if (!listening && window.exeHuelle?.onShellNotice) {
    listening = true
    window.exeHuelle.onShellNotice((kind) => {
      if (kind === 'service-stop-failed') showStopFailed()
    })
  }
  const words = {}
  for (const [name, key] of Object.entries(WORDS)) {
    const word = t(key)
    // A key the catalogue does not carry comes back as the key itself: left
    // out, so the shell keeps its own word instead of showing a key.
    if (word !== key) words[name] = word
  }
  if (noticeWaiting) showStopFailed()
  window.exeHuelle?.menuWords?.(words)
}
