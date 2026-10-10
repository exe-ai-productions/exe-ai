/*
  The beginning of a text file, for a tile that shows it as text.

  A tile shows a few lines, so only those bytes are read: the request asks
  for exactly that range, and where the server sends the whole file anyway,
  the reading stops as soon as enough has come. Asked a few at a time and
  kept for the session, like the shell's previews (lib/thumbnails.js): the
  doc folder is mounted and torn down with every switch of the rail, and a
  beginning it already had must not be fetched again.
*/

const AT_ONCE = 4

const cache = new Map()
const waiting = []
let running = 0

function next() {
  while (running < AT_ONCE && waiting.length) {
    const job = waiting.shift()
    running += 1
    job().finally(() => {
      running -= 1
      next()
    })
  }
}

/* At most `bytes` bytes of the answer, then the stream is let go. */
async function readStart(address, bytes) {
  const answer = await fetch(address, { headers: { Range: `bytes=0-${bytes - 1}` } })
  // A range from 0 cannot be served from an empty file; that file is
  // simply empty, not unreadable.
  if (answer.status === 416) return ''
  if (!answer.ok) return null
  const reader = answer.body.getReader()
  const parts = []
  let have = 0
  while (have < bytes) {
    const { done, value } = await reader.read()
    if (done) break
    parts.push(value)
    have += value.length
  }
  reader.cancel().catch(() => {})
  const all = new Uint8Array(have)
  let at = 0
  for (const part of parts) {
    all.set(part, at)
    at += part.length
  }
  // `stream` keeps a character the cut went through out of the text,
  // instead of showing it as a replacement sign at the end.
  return new TextDecoder().decode(all.subarray(0, Math.min(have, bytes)), { stream: true })
}

/**
 * The first `bytes` bytes of the file at `address` as text; '' for an empty
 * file, null where it could not be read. `key` names the file — the same
 * key is answered from the cache.
 */
export function fileStart(key, address, bytes) {
  if (!cache.has(key)) {
    cache.set(
      key,
      new Promise((resolve) => {
        waiting.push(() => readStart(address, bytes).then(resolve, () => resolve(null)))
        next()
      }),
    )
  }
  return cache.get(key)
}
