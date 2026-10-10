/*
  The app shell's previews of doc folder files (fenster-electron/thumbnail.js).

  Each one costs the shell a download, a file in the temporary folder and a
  call into the system, so they are asked for a few at a time and kept for
  the whole session: the tool that shows them is mounted and torn down with
  every switch, and a preview it already had must not be made again.

  Without the shell (a browser) there is no preview, and the answer is ''.
*/

const AT_ONCE = 3

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

/**
 * A data URL of the file's preview, or '' where there is none. `key` names
 * the file and the size — the same key is answered from the cache.
 */
export function shellPreview(key, address, name, size) {
  const shell = typeof window !== 'undefined' ? window.exeHuelle : undefined
  if (!shell?.thumbnail) return Promise.resolve('')
  if (!cache.has(key)) {
    cache.set(
      key,
      new Promise((resolve) => {
        waiting.push(() =>
          shell.thumbnail(address, name, size).then(
            (image) => resolve(image || ''),
            () => resolve(''),
          ),
        )
        next()
      }),
    )
  }
  return cache.get(key)
}

/** Whether previews can be had at all here. */
export function shellPreviews() {
  return typeof window !== 'undefined' && Boolean(window.exeHuelle?.thumbnail)
}
