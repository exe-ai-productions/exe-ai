/*
  How the text of a running answer comes up.

  The service sends the text in pieces of whatever size the model produces;
  drawn as they come, each piece stands there at once and the answer grows in
  jerks. Here the pieces go into a queue and the text is let out evenly, at
  one speed: a character every `CHAR_MS` at the slowest, and fast enough that
  what waits is empty `BEHIND_MS` after it came — whichever of the two is
  quicker. A piece that arrives sets the speed for what it brings with it and
  the speed holds until the queue is empty, so it neither ramps up over
  seconds nor jumps from frame to frame. A slow model is told character by
  character, a fast one is never more than a quarter of a second behind, and
  when the answer has ended what still waits runs out within that time
  instead of jumping onto the screen.

  Pure on purpose: time and frames are handed in, so the same code runs in the
  component (Nachricht.svelte) and in a test without a window.
*/

/* The most time one character takes, in milliseconds. */
const CHAR_MS = 5
/* How far the text may lag behind what has arrived, in milliseconds. */
const BEHIND_MS = 250

/* One flow: how many characters to let out in this frame, given the length of
   the queue. */
export function makeFlow() {
  const slowest = 1 / CHAR_MS
  let rate = slowest
  let collected = 0
  let lastAt = 0
  return {
    step(now, waiting) {
      const dt = lastAt ? now - lastAt : 16
      lastAt = now
      if (waiting <= 0) {
        collected = 0
        rate = slowest
        return 0
      }
      rate = Math.max(rate, waiting / BEHIND_MS)
      collected += dt * rate
      const count = Math.min(Math.floor(collected), waiting)
      collected -= count
      return count
    },
    reset() {
      rate = slowest
      collected = 0
      lastAt = 0
    },
  }
}

/*
  The length of the answer's last piece of text that stands on the screen.

  `hooks` is what the caller hands in:
    set(length, flowing)  the length that may be drawn now, and whether the
                            text is flowing (characters fade in) or stands
                            whole as the answer has it
    raf(fn), caf(id)        the frame clock
    reducedMotion()         whether the reader asked for less motion

  `follow(index, target, running)` is told after every change of the answer
  which of its parts is the last piece of text, how long that is and whether
  the answer still runs. An answer that is stored, and every piece of text
  that was there when the window first saw a running answer, stands whole at
  once; only what arrives while the answer runs flows, and what is still
  waiting when it ends runs out.
*/
export function makeTextFlow(hooks) {
  const flow = makeFlow()
  let index = -1
  let shown = 0
  let target = 0
  let visited = false
  let ran = false
  let runningNow = false
  let frame = 0

  const report = () => hooks.set(shown, ran && (shown < target || runningNow))

  const step = (now) => {
    frame = 0
    const count = flow.step(now, target - shown)
    if (count > 0) shown = Math.min(target, shown + count)
    report()
    if (shown < target) frame = hooks.raf(step)
  }

  const whole = (newIndex, newTarget) => {
    index = newIndex
    target = newTarget
    shown = newTarget
    flow.reset()
    hooks.set(shown, false)
  }

  return {
    follow(newIndex, newTarget, running) {
      const first = !visited
      visited = true
      runningNow = running
      if (running) ran = true
      // Less motion, a stored answer, and what was already there when the
      // window first saw the answer run: whole at once.
      if (hooks.reducedMotion() || !ran || (first && running)) {
        whole(newIndex, newTarget)
        // An answer seen running goes on flowing from here.
        if (running && ran && !hooks.reducedMotion()) report()
        return
      }
      if (newIndex !== index) {
        // A piece of text that begins while the answer runs flows from its
        // first character.
        index = newIndex
        target = newTarget
        shown = 0
        flow.reset()
      } else {
        target = newTarget
        if (shown > target) shown = target
      }
      report()
      if (shown < target && !frame) frame = hooks.raf(step)
    },
    /* The window leaves: no frame is asked for any more. */
    cancel() {
      if (frame) hooks.caf(frame)
      frame = 0
    },
  }
}
