/*
  The one spring everything that follows the text of a running answer moves
  on.

  The distance to the goal halves every `GLEIT_HALB_MS`, and each frame covers
  the share its time earns, never less than a pixel, so the goal is reached.
  The chat's view follows the floor with it when a new line of the chat
  comes (App.svelte), and the line and the mark at the end of a running
  answer follow the growing text with it (`glideHeight`): the same law, not
  two. A reader who stands at the floor while the text grows is held there
  in the very frame (the `glidegrow` event), not carried by a second spring.
*/

import { reducedMotion } from './softSwitch.js'

export const GLEIT_HALB_MS = 80

/** How far a spring covers in one frame of `dt` milliseconds when `distance`
    (positive) is left to go. */
export function glideStep(distance, dt) {
  return distance <= 1 ? distance : Math.max(1, distance * (1 - 0.5 ** (dt / GLEIT_HALB_MS)))
}

/*
  An action for the entry that holds the running text of an answer: its
  height follows the height of its text on the spring, instead of jumping by
  a line each time the text wraps. Everything under the entry — the line that
  runs through it, the mark at the end of the line — moves with it, so the
  line grows softly and the mark glides down, and the line ends on the mark in
  every frame.

  The text itself is not held back: it stands where it belongs at once and
  fades in; only the room it takes is let out softly. `on` is whether the
  text is flowing; when it turns off, the entry finishes its way and then
  stands free again. A reader who asked for less motion, and a window nobody
  looks at (it runs no frames), get the new height at once.
*/
export function glideHeight(node, on) {
  const content = node.querySelector(':scope > .antwort')
  if (!content || typeof ResizeObserver === 'undefined') return {}
  let running = Boolean(on)
  let shown = null
  let frame = 0
  let last = 0

  const natural = () => content.getBoundingClientRect().height
  const write = () => {
    node.style.height = shown === null ? '' : `${shown}px`
  }
  /* Every frame that lets room out says so, up the tree, in that same frame:
     whoever keeps a reader at the floor can take it there before the frame
     is drawn. Letting go of the height, and pinning it when the text starts
     to flow, change nothing on screen and say nothing. */
  const grown = new Event('glidegrow', { bubbles: true })
  const announce = () => node.dispatchEvent(grown)
  const release = () => {
    shown = null
    write()
  }
  const settle = () => {
    shown = natural()
    write()
  }

  function tick(now) {
    frame = 0
    if (shown === null) return
    const target = natural()
    const distance = target - shown
    const dt = Math.min(100, now - last)
    last = now
    if (Math.abs(distance) < 0.25) {
      shown = target
      write()
      if (distance !== 0) announce()
      if (!running) release()
      return
    }
    shown += Math.sign(distance) * glideStep(Math.abs(distance), dt)
    write()
    announce()
    frame = requestAnimationFrame(tick)
  }

  function follow() {
    if (shown === null) return
    if (reducedMotion() || (typeof document !== 'undefined' && document.hidden)) {
      const before = shown
      settle()
      if (shown !== before) announce()
      if (!running) release()
      return
    }
    if (frame) return
    // The first step is taken as one frame's worth (16 ms).
    last = performance.now() - 16
    frame = requestAnimationFrame(tick)
  }

  /* The box is measured before the frame is drawn, so the entry is held at
     its old height in the very frame the text grows in. */
  const observer = new ResizeObserver(follow)
  observer.observe(content)
  if (running) settle()

  return {
    update(next) {
      running = Boolean(next)
      if (running && shown === null) settle()
      else if (!running && shown !== null) follow()
    },
    destroy() {
      observer.disconnect()
      cancelAnimationFrame(frame)
      release()
    },
  }
}
