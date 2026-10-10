/*
  The permission mode — auto / manuell / restricted — for chat and for
  agents, each its own setting (app/berechtigungswahl.py). Global, not
  per-chat: it is one shared rule file on disk, not a per-conversation
  preference, so there is exactly one current value for each origin.
*/

import { api } from './api.js'
import { t } from './texte.svelte.js'

const SCHLUESSEL = { chat: 'berechtigungsmodus_chat', agent: 'berechtigungsmodus_agent' }

export const berechtigungsmodus = $state({
  chat: 'manuell',
  agent: 'manuell',
  geladen: false,
})

/* Guards against every early mounter (the header dot, the input bar, the
   job dialog) firing its own load in the same tick — one request pays for
   all of them, the rest just wait on it. */
let ladenLaeuft = null

export function berechtigungsmodusLaden() {
  if (ladenLaeuft) return ladenLaeuft
  ladenLaeuft = Promise.all([
    api.einstellungAufgeloest(SCHLUESSEL.chat).catch(() => null),
    api.einstellungAufgeloest(SCHLUESSEL.agent).catch(() => null),
  ])
    .then(([chat, agent]) => {
      /* `zusammengefuehrt()` on the backend answers an unset key with an
         empty object, not null — and an empty object is truthy in
         JavaScript, so `|| 'manuell'` never caught it. Checked against the
         actual mode words instead of the value's truthiness. */
      const gueltig = new Set(modusOptionen().map(([wert]) => wert))
      berechtigungsmodus.chat = gueltig.has(chat?.wert) ? chat.wert : 'manuell'
      berechtigungsmodus.agent = gueltig.has(agent?.wert) ? agent.wert : 'manuell'
      berechtigungsmodus.geladen = true
    })
    .finally(() => { ladenLaeuft = null })
  return ladenLaeuft
}

/** The three modes, translated — the one place the list is written out, so
 * every pill that offers them stays in step with the others. */
export function modusOptionen(herkunft = 'chat') {
  /* The same three VALUES for both origins, and one of them wears a
     different word on the agent side.
     
     For a chat the three are a question of how often you are asked. For an
     agent nobody is there to answer, so `fragen` becomes `nein`
     (app/berechtigungen.py) and the very same ladder stops being about
     frequency and becomes about REACH: the whole disk, the shared folders,
     or no files at all. "Manuell" then promises something that does not
     exist there — nothing asks — while what it actually does is keep the
     run inside the folders it was given.

     Only the label changes. The stored value stays `manuell`, so nothing
     that reads a setting, judges a path or migrates a file has to know this
     happened. */
  const manuell =
    herkunft === 'agent'
      ? t('berechtigungen.modus_agent_manuell')
      : t('berechtigungen.modus_manuell')
  return [
    ['auto', t('berechtigungen.modus_auto')],
    ['manuell', manuell],
    ['restricted', t('berechtigungen.modus_restricted')],
  ]
}

export async function berechtigungsmodusSetzen(herkunft, wert) {
  const vorher = berechtigungsmodus[herkunft]
  berechtigungsmodus[herkunft] = wert
  try {
    await api.einstellungSetzen('global', SCHLUESSEL[herkunft], wert)
  } catch {
    /* Put it back rather than showing a mode that was never stored. */
    berechtigungsmodus[herkunft] = vorher
  }
}
