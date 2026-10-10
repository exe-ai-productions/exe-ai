/* The system the page runs on, and the names its modifier keys are shown
   under.

   On a Mac a shortcut is written with the signs printed on the keys, set
   side by side ("⌘⌥"); everywhere else with the words printed on them,
   joined by "+" ("Ctrl+Alt"). The Shortcuts page and the settings overview
   both ask here, so the same key reads the same in both. */
import { t } from './texte.svelte.js'
import { systemOf } from './microphoneKey.js'

/** 'mac', 'windows' or 'other' — read once: a page does not change the
    system under it. */
export const system = systemOf(navigator.userAgentData?.platform || navigator.platform)

/** The word on every modifier key in the language of the interface, or
    null on a Mac, where the signs are shown instead. */
export function keyNames() {
  if (system === 'mac') return null
  return {
    Meta: t('shortcuts.key_win'),
    Control: t('shortcuts.key_ctrl'),
    Alt: t('shortcuts.key_alt'),
    Shift: t('shortcuts.key_shift'),
  }
}
