/*
  What the row "Updates" of the settings list shows at its right end.

  At rest it is the running version. A look for a newer version, the row's own
  click, answers in the same place: up to date, a newer version with the word
  of its next step (fetch, then install), the progress of a fetch, or why a
  step failed. The sentences are the ones the update card and the phone's row
  already use (`updates.*`); the row only decides which one stands and what
  colour it wears.
*/
import { t } from './texte.svelte.js'
import { updates, failedKey } from './updates.svelte.js'

/* `text`: the sentence (the version at rest); `art`: the colour of a state
   (`running`, `failed`, `done` or none); `tat`: the word of the step a click
   on the row takes next, or ''. */
export function updatesRowShow() {
  switch (updates.state) {
    case 'store':
      return { text: t('updates.store'), art: 'done', tat: '' }
    case 'available':
      return { text: t('updates.found', { version: updates.found }), art: '', tat: t('updates.download') }
    case 'downloading':
      return { text: t('updates.downloading', { percent: updates.percent }), art: 'running', tat: '' }
    case 'downloaded':
      return { text: t('updates.found', { version: updates.found }), art: '', tat: t('updates.install') }
    case 'error':
      return { text: t(failedKey(), { reason: updates.reason }), art: 'failed', tat: '' }
    case 'none':
      if (updates.looked) return { text: t('updates.current'), art: 'done', tat: '' }
  }
  return { text: updates.version ?? '', art: '', tat: '' }
}
