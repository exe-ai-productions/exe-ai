/*
  One beat for every page that asks the service again and again.

  A page that asks every two or three seconds with a plain timer asks again
  even when its last question is still on its way. Slow answers then pile up
  and take the connections the browser has per machine (six, one of them held
  by the event stream), and every other request of the window waits behind
  them. This beat starts a round only when the one before it has answered:
  a tick that falls into a running round asks nothing. The rhythm itself is
  the caller's; a round that fails does not stop the beat.

  `round` returns what ends the round: a promise, or nothing for a round that
  has already ended. Hands back the way to stop; stopping also ends the beat
  while a round is running, and that round is let to finish.
*/

/**
 * @param {() => unknown} round   asks once; a returned promise is waited for
 * @param {number} ms             the time between two ticks
 * @returns {() => void}          stops the beat
 */
export function pollWithoutOverlap(round, ms) {
  let running = false
  const timer = setInterval(async () => {
    if (running) return
    running = true
    try {
      await round()
    } catch {
      // The next tick asks again; a failed round is the round's own business.
    } finally {
      running = false
    }
  }, ms)
  return () => clearInterval(timer)
}
