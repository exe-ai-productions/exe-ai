/*
  What a row of the settings list does, from wherever the list stands.

  The list stands in the sidebar of the settings, of the local models and of
  the six server pages. A row of the settings' own pages opens that page — in
  the settings window itself the caller switches there (it asks first if an
  edit stands unsaved); anywhere else the settings open on it. The other rows
  open the menu they name with the part they name, which the page there reads
  once; the manual and the row of the updates do what their names say: a click
  looks for a newer version, or takes the next step of the one found.
*/
import { zustand, seiteZeigen } from './zustand.svelte.js'
import { handbuchOeffnen } from './handbuch.js'
import { updates, downloadUpdate, installUpdate } from './updates.svelte.js'

/* The settings, opened on one of their pages. */
export function openSettingsPage(art) {
  zustand.promptStart = art
  seiteZeigen('prompt')
}

/* `page(art)`: how a row of the settings' own pages is taken; `look()`: how
   the look for a newer version is asked. */
export function chooseRow(row, { page = openSettingsPage, look = () => {} } = {}) {
  const target = row.ziel
  if (target.art) return page(target.art)
  if (target.hilfe) return handbuchOeffnen()
  if (target.update) {
    // A copy kept current by a store has nothing to look for, and a look or
    // a fetch already on its way is not asked for twice.
    if (['store', 'checking', 'downloading'].includes(updates.state)) return
    if (updates.state === 'available') return downloadUpdate()
    if (updates.state === 'downloaded') return installUpdate()
    return look()
  }
  if (target.menu === 'lokal') zustand.lokalWunsch = target.server ?? 'lokal'
  if (target.menu === 'katalog') zustand.katalogArtWunsch = target.seite ?? 'chat'
  return seiteZeigen(target.menu)
}
