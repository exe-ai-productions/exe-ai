/*
  Two small readings the cloud page makes of what a provider says and what
  the hand typed, kept apart so they can be tried without a window.

  Imports only the plain counting helper of the catalogue module.
*/
import { shortCount } from './catalog.js'

/** What the context field means once typed: `null` for an empty field (ask
    the server again), a positive whole number, or `undefined` for anything
    else — the caller keeps the old value then, never a guess. */
export function contextValue(text) {
  const value = String(text ?? '').trim()
  if (value === '') return null
  if (!/^\d+$/.test(value)) return undefined
  const number = Number(value)
  if (!Number.isSafeInteger(number) || number > 10000000) return undefined
  return number === 0 ? null : number
}

/** The context the service found, as a short word, or `null` where nothing
    was found — a stand-in value is not a finding. */
export function contextFound(house) {
  if (!house?.kontext || house.kontextQuelle === 'ersatz') return null
  return shortCount(house.kontext)
}

/** Whether a new provider has what it needs: a key of at least eight
    characters, and for the own server a name and an address as well. */
export function providerReady(kind, { key, id, url }) {
  if (String(key ?? '').trim().length < 8) return false
  if (kind !== 'eigen') return true
  return Boolean(String(id ?? '').trim() && String(url ?? '').trim())
}
