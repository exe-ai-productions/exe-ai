/*
  The deeds of the chat template row, for both chat server pages (the model
  server and the agent server): they differ only in the two routes they ask,
  which come in as `edit` and `reveal`. The choice itself lives in the page's
  levers (`fein.chat_template`, `fein.chat_template_file`), stored with the
  others.
*/
import { melde } from './zustand.svelte.js'

/* The copy of the model's template is made (or found), opened in the text
   editor, and from then on the template of the server. Says whether it
   worked. */
export async function editTemplate(fein, modell, edit) {
  try {
    const antwort = await edit(modell)
    fein.chat_template = 'file'
    fein.chat_template_file = antwort.pfad
    return true
  } catch (fehler) {
    melde(fehler.message ?? String(fehler), 'fehler')
    return false
  }
}

/* The file in the file manager: the copy, or the model file without one. */
export async function revealTemplate(modell, reveal) {
  try {
    await reveal(modell)
  } catch (fehler) {
    melde(fehler.message ?? String(fehler), 'fehler')
  }
}

/* The choice was made. "Own file" without a copy yet makes it (and opens it,
   as the pencil does); where that fails, the model's own template stays. */
export async function templateChosen(neu, fein, modell, edit) {
  if (neu !== 'file' || fein.chat_template_file) return
  if (!(await editTemplate(fein, modell, edit))) fein.chat_template = 'model'
}

/* Another model: the copy was made of the one before. */
export function resetTemplate(fein) {
  fein.chat_template = 'model'
  fein.chat_template_file = ''
}
