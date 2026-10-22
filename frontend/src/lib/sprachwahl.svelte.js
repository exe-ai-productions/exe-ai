/*
  Switching the language of the program: "auto" gives the choice back to the
  device, any other value loads its catalogue. Used by the settings window of
  the desktop and the settings page of the phone.
*/

import { t, spracheWaehlen, spracheZuruecksetzen } from './texte.svelte.js'
import { melde, modelleLaden } from './zustand.svelte.js'

/* Which attempt is the current one: a click made while an earlier one is
   still on its way takes over, and the earlier one must not report a
   failure for a switch nobody is waiting for anymore. */
let attempt = 0

export async function spracheStellen(wert) {
  const mine = ++attempt
  try {
    if (wert === 'auto') await spracheZuruecksetzen()
    else await spracheWaehlen(wert)
    await modelleLaden()
  } catch {
    if (mine === attempt) melde(t('fehler.allgemein'), 'fehler')
  }
}
