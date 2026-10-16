/*
  Writes that wait a beat after the hand stops — and are never lost.

  A number typed into a server window, or a slider dragged across its track,
  must not write every step it passes: each write waits a beat for the next
  one of the same key. What the windows did with that beat was wrong in one
  way: the timer was cleared when the window went away or was cleared before
  "Start" was read, so a value typed a moment before closing or starting was
  simply dropped.

  Here the waiting write is kept by key, replaced by a newer one of the same
  key, dropped by `cancel` where the value was taken back, and written at
  once by `flush` — which the window calls when it goes away and before it
  starts its server.

    const writer = createDelayedWriter()
    writer.plan('putzkontext', () => werteSetzen({ putzkontext: 4096 }), 400)
    await writer.flush()      // every waiting write is made now
*/

export function createDelayedWriter(defaultDelayMs = 400) {
  const waiting = new Map()

  function fire(key) {
    const entry = waiting.get(key)
    if (!entry) return undefined
    clearTimeout(entry.timer)
    waiting.delete(key)
    return entry.write()
  }

  return {
    /* The write for `key`, after `delayMs`; a write already waiting under
       the same key is replaced. */
    plan(key, write, delayMs = defaultDelayMs) {
      const before = waiting.get(key)
      if (before) clearTimeout(before.timer)
      waiting.set(key, { write, timer: setTimeout(() => fire(key), delayMs) })
    },
    /* The waiting write of `key` is dropped: its value was taken back. */
    cancel(key) {
      const before = waiting.get(key)
      if (!before) return
      clearTimeout(before.timer)
      waiting.delete(key)
    },
    /* Every waiting write is made now; resolves when they are through. A
       write that fails does not stop the others. */
    async flush() {
      await Promise.allSettled([...waiting.keys()].map((key) => fire(key)))
    },
    pending() {
      return waiting.size
    },
  }
}
