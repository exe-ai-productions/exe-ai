/*
  The words the window's shell shows by itself, in the interface's language.

  The shell names a few entries of the right-click menu on its own: the ones
  that act on a link or a picture. It has no catalogue, so the page reads the
  words from its own and hands them over (preload.js). Until then, and for a
  word left out, the shell shows its English ones.

  In a browser there is no shell, and nothing is told.
*/
import { t } from './texte.svelte.js'

/* The shell's name of each word, and where the catalogue keeps it. */
const WORDS = {
  copyLink: 'menue.copy_link',
  copyLinkUnavailable: 'menue.copy_link_unavailable',
  saveImage: 'menue.save_image',
  copyImage: 'menue.copy_image',
}

/** Tells the shell its words. Reads the catalogue, so an effect that calls
 *  it runs again whenever the language changes. */
export function tellShellWords() {
  const words = {}
  for (const [name, key] of Object.entries(WORDS)) {
    const word = t(key)
    // A key the catalogue does not carry comes back as the key itself: left
    // out, so the shell keeps its own word instead of showing a key.
    if (word !== key) words[name] = word
  }
  window.exeHuelle?.menuWords?.(words)
}
