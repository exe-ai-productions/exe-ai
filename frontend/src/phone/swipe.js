/*
  The two swipes of the phone page: from the left edge inward opens the
  chat list, a swipe back to the left closes it.

  `swipeDirection` is the whole decision — a pure function of where a finger
  went down and where it came up — so a test can run it without a screen.
  `listenForSwipes` is the thin ear around it: it listens on the window and
  calls back, and does nothing else.
*/

/* How far from the left edge a finger may go down and still be an edge
   swipe, and how far it has to travel. */
export const EDGE = 24
export const TRAVEL = 56

/* How much sideways drift a swipe may carry as a share of its travel: a
   scroll that wanders must not open the list. */
const DRIFT = 0.6

/** 'open' for an edge swipe inward, 'close' for a swipe to the left, else null. */
export function swipeDirection(from, to, isOpen) {
  const dx = to.x - from.x
  const dy = to.y - from.y
  if (Math.abs(dx) < TRAVEL || Math.abs(dy) > Math.abs(dx) * DRIFT) return null
  if (!isOpen && from.x <= EDGE && dx > 0) return 'open'
  if (isOpen && dx < 0) return 'close'
  return null
}

/* Listens for touches on the window for as long as it stands. `isOpen()`
   says whether the list is open right now; `onSwipe(direction)` is told what
   the finger did. Returns the function that stops it. */
export function listenForSwipes(isOpen, onSwipe, win = globalThis.window) {
  let from = null
  const down = (event) => {
    /* Two fingers are a pinch or a scroll, not a swipe. */
    const finger = event.touches?.length === 1 ? event.touches[0] : null
    from = finger ? { x: finger.clientX, y: finger.clientY } : null
  }
  const up = (event) => {
    const finger = event.changedTouches?.[0]
    if (!from || !finger) return
    const direction = swipeDirection(from, { x: finger.clientX, y: finger.clientY }, isOpen())
    from = null
    if (direction) onSwipe(direction)
  }
  win.addEventListener('touchstart', down, { passive: true })
  const cancel = () => {
    from = null
  }
  win.addEventListener('touchend', up, { passive: true })
  win.addEventListener('touchcancel', cancel, { passive: true })
  return () => {
    win.removeEventListener('touchstart', down)
    win.removeEventListener('touchend', up)
    win.removeEventListener('touchcancel', cancel)
  }
}
