/*
  What the fingers on a picture mean: zoom with two fingers, a double tap, a
  long press, a swipe to the side or down, one finger that moves the zoomed
  picture or paints.

  The same picture sits in three places on the phone — the studio's surface,
  the reader and the mask page — and each of them hears the same fingers the
  same way. This module is the decision, with no window around it: pointer
  positions and times go in, a list of things that happened comes out. The
  action in `pictureGesturesAction.js` wires it to a node.

  The view is `{ zoom, x, y }` the way a style writes it: the picture is
  moved by `x` and `y` pixels from the middle of its stage and scaled by
  `zoom` about that middle.
*/
import { wischSchritt } from './bildreihe.js'

export const ZOOM_MIN = 1
export const ZOOM_MAX = 4

/* A touch that moves less than TAP_MOVE and ends within TAP_TIME is a tap;
   two taps within DOUBLE_TIME and DOUBLE_MOVE are a double tap; a finger
   held still for LONG_TIME is a long press. */
const TAP_MOVE = 10
const TAP_TIME = 400
const DOUBLE_TIME = 320
const DOUBLE_MOVE = 32
export const LONG_TIME = 480

export const NEUTRAL = Object.freeze({ zoom: ZOOM_MIN, x: 0, y: 0 })

export const clamp = (value, low, high) => Math.min(high, Math.max(low, value))
export const clampZoom = (zoom) => clamp(zoom, ZOOM_MIN, ZOOM_MAX)

const gap = (a, b) => Math.hypot(a.x - b.x, a.y - b.y)
const middle = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 })

/* A view that cannot leave its stage: the picture fills the stage at zoom 1,
   so at a larger zoom it can be moved by half of what it grew by, and not
   further. At zoom 1 it does not move at all. */
export function limitView(view, { w, h }) {
  if (view.zoom <= ZOOM_MIN + 0.001) return { ...NEUTRAL }
  const rx = Math.max(0, ((view.zoom - 1) * w) / 2)
  const ry = Math.max(0, ((view.zoom - 1) * h) / 2)
  return { zoom: view.zoom, x: clamp(view.x, -rx, rx), y: clamp(view.y, -ry, ry) }
}

/* Two fingers: the zoom follows the distance between them, and the point of
   the picture that lay under their middle stays under it — so the picture
   follows the fingers as well as growing. `start` holds the view and the two
   fingers' distance and middle when the second finger came down, all
   relative to the middle of the stage. */
export function pinchView(start, a, b, stage) {
  const zoom = clampZoom(start.view.zoom * (gap(a, b) / Math.max(1, start.gap)))
  const now = middle(a, b)
  const point = {
    x: (start.middle.x - start.view.x) / start.view.zoom,
    y: (start.middle.y - start.view.y) / start.view.zoom,
  }
  return limitView({ zoom, x: now.x - zoom * point.x, y: now.y - zoom * point.y }, stage)
}

/* The zoom that shows a picture at its own pixels: its natural width over
   the width it is shown at. A picture smaller than its stage has no larger
   "own size" to go to, so it goes twice in. */
export function ownSizeZoom(natural, shown) {
  if (!natural?.w || !shown?.w) return 2
  const zoom = natural.w / shown.w
  return clampZoom(zoom < 1.05 ? 2 : zoom)
}

/* Double tap: a zoomed picture is fitted; a fitted one goes to its own size
   about the tapped point, which stays where it is. `point` is relative to the
   middle of the stage. */
export function doubleTapView(view, point, natural, shown, stage) {
  if (view.zoom > ZOOM_MIN + 0.01) return { ...NEUTRAL }
  const zoom = ownSizeZoom(natural, shown)
  return limitView({ zoom, x: point.x * (1 - zoom), y: point.y * (1 - zoom) }, stage)
}

/* A swipe down: more down than across, far enough, quick enough. */
export function swipedDown({ dx, dy, elapsed }, { reach = 90, limit = 700 } = {}) {
  return dy >= reach && dy >= Math.abs(dx) * 1.5 && elapsed <= limit
}

/* The decision. One tracker per node; it keeps the fingers that are down.

   options:
     paint      one finger paints (the mask page); two fingers never do
     swipe      a swipe to the side or down is reported (the reader); where
                the page scrolls sideways by itself (the studio) it is not
     stageSize  () => ({ w, h }) — the stage's size
     natural    () => ({ w, h }) | null — the picture's own size
     shown      () => ({ w, h }) — the size the picture is shown at, unzoomed

   Every method returns the things that happened, in order:
     { kind: 'view', view }            the view changed
     { kind: 'tap' } { kind: 'double', view }
     { kind: 'long' }                  held still long enough (see `hold`)
     { kind: 'swipe', step }           +1 next, -1 before
     { kind: 'swipe-down' }
     { kind: 'paint-start' | 'paint-move' | 'paint-end', point }
     { kind: 'paint-cancel' }          a second finger came: the stroke is void
*/
export function startGestures(options = {}) {
  /* Read at every touch, not once: the mask page changes `paint` while the
     picture stays zoomed where it is. */
  const live = options
  const stageSize = () => (live.stageSize ?? (() => ({ w: 1, h: 1 })))()
  const natural = () => live.natural?.() ?? null
  const shown = () => live.shown?.() ?? null

  let view = { ...NEUTRAL }
  const fingers = new Map()
  let centre = { x: 0, y: 0 }
  let pair = null
  let lastTap = null
  let touch = null

  const relative = (point) => ({ x: point.x - centre.x, y: point.y - centre.y })
  const viewEffect = () => ({ kind: 'view', view: { ...view } })

  function beginPair() {
    const [a, b] = [...fingers.values()].map(relative)
    pair = { view: { ...view }, gap: gap(a, b), middle: middle(a, b) }
  }

  return {
    get view() {
      return view
    },

    /* Back to the whole picture. */
    reset() {
      view = { ...NEUTRAL }
      pair = null
      return [viewEffect()]
    },

    /* `box` is the stage's rectangle on the screen, taken once per touch:
       the view is told from its middle. */
    down(id, x, y, time, box) {
      const effects = []
      if (!fingers.size) {
        centre = { x: box.left + box.width / 2, y: box.top + box.height / 2 }
        touch = { x0: x, y0: y, t0: time, moved: false, long: false, orphan: false }
      }
      fingers.set(id, { x, y })
      if (fingers.size === 1) {
        if (live.paint) effects.push({ kind: 'paint-start', point: { x, y } })
      } else if (fingers.size === 2) {
        if (live.paint && touch && !touch.orphan) effects.push({ kind: 'paint-cancel' })
        if (touch) {
          touch.moved = true
          touch.orphan = true
        }
        beginPair()
      }
      return effects
    },

    move(id, x, y) {
      const effects = []
      const before = fingers.get(id)
      if (!before) return effects
      fingers.set(id, { x, y })
      if (fingers.size >= 2 && pair) {
        const [a, b] = [...fingers.values()].map(relative)
        view = pinchView(pair, a, b, stageSize())
        effects.push(viewEffect())
        return effects
      }
      if (fingers.size !== 1 || !touch) return effects
      if (Math.hypot(x - touch.x0, y - touch.y0) > TAP_MOVE) touch.moved = true
      if (live.paint) {
        if (!touch.orphan) effects.push({ kind: 'paint-move', point: { x, y } })
        return effects
      }
      if (view.zoom > ZOOM_MIN + 0.001) {
        view = limitView({ ...view, x: view.x + (x - before.x), y: view.y + (y - before.y) }, stageSize())
        effects.push(viewEffect())
      }
      return effects
    },

    /* The one finger that is down has not moved for LONG_TIME. */
    hold() {
      if (!touch || fingers.size !== 1 || touch.moved || touch.long || live.paint) return []
      touch.long = true
      return [{ kind: 'long' }]
    },

    up(id, x, y, time) {
      const effects = []
      if (!fingers.has(id)) return effects
      const before = fingers.size
      fingers.delete(id)
      if (before >= 2) {
        // Two fingers became one: that one carries on as a plain drag from
        // where it stands, and nothing it does now is a tap or a swipe.
        pair = null
        return effects
      }
      const done = touch
      touch = null
      if (!done) return effects
      if (live.paint) {
        if (!done.orphan) effects.push({ kind: 'paint-end', point: { x, y } })
        return effects
      }
      if (done.orphan || done.long) return effects
      const dx = x - done.x0
      const dy = y - done.y0
      const elapsed = time - done.t0
      if (!done.moved && elapsed <= TAP_TIME) {
        if (
          lastTap
          && time - lastTap.time <= DOUBLE_TIME
          && Math.hypot(x - lastTap.x, y - lastTap.y) <= DOUBLE_MOVE
        ) {
          lastTap = null
          view = doubleTapView(view, relative({ x, y }), natural(), shown(), stageSize())
          effects.push({ kind: 'double', view: { ...view } })
        } else {
          lastTap = { x, y, time }
          effects.push({ kind: 'tap' })
        }
        return effects
      }
      lastTap = null
      if (live.swipe && view.zoom <= ZOOM_MIN + 0.001) {
        const step = wischSchritt({ dx, dy, dauer: elapsed })
        if (step) effects.push({ kind: 'swipe', step })
        else if (swipedDown({ dx, dy, elapsed })) effects.push({ kind: 'swipe-down' })
      }
      return effects
    },

    /* The system took the touch away (a call, a gesture of its own). */
    cancel() {
      const effects = []
      if (live.paint && touch && !touch.orphan && fingers.size === 1) effects.push({ kind: 'paint-cancel' })
      fingers.clear()
      touch = null
      pair = null
      return effects
    },

    /* Fingers are down right now. */
    get touching() {
      return fingers.size > 0
    },
  }
}
