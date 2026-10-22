/*
  The round picture of a repository's owner on Hugging Face, for an owner the
  house has no logo of (see ownerLogo in logos.js).

  The service fetches and checks it (GET /models/avatar/{owner}); the page
  only asks, once per owner and for as long as it lives. Nothing is stored:
  the answer is kept in memory, and an owner without a picture, or a request
  that fails, simply stays a letter — no message, nothing to retry.
*/
import { api } from './api.js'
import { ownerLogo } from './logos.js'

const pictures = $state({})
const asked = new Set()

/* The picture of an owner as a data URL, or null (not asked yet, none, or
   failed). An owner with a house logo is never asked for. */
export function ownerPicture(owner) {
  const key = String(owner ?? '').toLowerCase()
  if (!key || ownerLogo(key)) return null
  if (!asked.has(key)) {
    asked.add(key)
    api
      .ownerAvatar(owner)
      .then((answer) => {
        if (typeof answer?.image === 'string' && answer.image.startsWith('data:image/')) pictures[key] = answer.image
      })
      .catch(() => {})
  }
  return pictures[key] ?? null
}
