/*
  How the drawing of the CLI follows the size of its box.

  The client keeps a block of its own on the last rows of the window and
  takes it off, asks the terminal where its cursor stands and draws it anew
  whenever it learns that the window changed its size. The drawing breaks
  every row anew that no longer fits when it is made narrower: told first,
  it would break the old block with the rest — the block would stand higher
  in the drawing than the client knows, and what the client then takes off
  and draws leaves empty rows behind, more with every step.

  So where the box gets narrower while the client's screen is up, the client
  is told first, and the drawing follows once it has read the client's
  question for the cursor: by then the client has taken its block off, and
  what is broken anew is the history alone. That is read off what the client
  writes, never off a clock. Wider, or only another height, before the
  client's screen is up, after its end and on the systems whose console
  breaks nothing of the block: the drawing follows at once, as it always did.
*/

/**
 * @param {object} parts
 * @param {object} parts.xterm        the drawing: `cols`, `rows`, `resize`, `buffer`, `scrollToBottom`
 * @param {object} parts.fit          its fit: `proposeDimensions`, `fit`
 * @param {(cols: number, rows: number) => void} parts.tell  hands a size to the client
 * @param {() => boolean} parts.screenIsUp   whether the client's screen is up
 * @param {boolean} parts.atOnce      follow at once, whatever the box does
 */
export function followTheBox({ xterm, fit, tell, screenIsUp, atOnce }) {
  // The size the client was last given.
  let given = null
  // The size the client was given while the drawing still has the old one,
  // and whether the client asked for the cursor since.
  let waiting = null
  let asked = false

  /* Whether the view stands on the last row, where the client's block is. */
  function atBottom() {
    const buffer = xterm.buffer && xterm.buffer.active
    return !buffer || buffer.viewportY >= buffer.baseY
  }

  /* Puts the view back on the last row, and once more after the box has laid
     itself out: its scroll position is clamped to the new height only then,
     and that moves the view away from the last row. */
  function pin() {
    if (!xterm.scrollToBottom) return
    xterm.scrollToBottom()
    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(() => requestAnimationFrame(() => xterm.scrollToBottom()))
    }
  }

  /* A change of size shifts rows under the view; one that stood on the last
     row is put back there. */
  function keepBottom(change) {
    const bottom = atBottom()
    change()
    if (bottom) pin()
  }

  function give(cols, rows) {
    if (given && given.cols === cols && given.rows === rows) return
    given = { cols, rows }
    tell(cols, rows)
  }

  /* The box changed: set the drawing to it, or — where it got narrower and
     the client has to take its block off first — tell the client and wait. */
  function follow() {
    // Once the drawing has caught up, the box as it stands then is looked at.
    if (waiting) return
    const size = fit.proposeDimensions()
    if (!size || Number.isNaN(size.cols) || Number.isNaN(size.rows)) return
    if (size.cols === xterm.cols && size.rows === xterm.rows) return
    if (!atOnce && size.cols < xterm.cols && screenIsUp()) {
      waiting = size
      asked = false
      give(size.cols, size.rows)
      return
    }
    keepBottom(() => fit.fit())
  }

  /* The drawing took a size of its own: the client has it, or is told. */
  function resized(cols, rows) {
    give(cols, rows)
  }

  /* The client asked where its cursor stands. It does so after taking its
     block off, once it has learned of a new size. */
  function cursorAsked() {
    if (waiting) asked = true
  }

  /* Called after a piece of the client's output was read by the drawing,
     the question in it answered. */
  function read() {
    if (waiting && asked) release()
  }

  /* The drawing takes the size the client was given. */
  function release() {
    const size = waiting
    if (!size) return
    waiting = null
    asked = false
    const box = fit.proposeDimensions()
    keepBottom(() => {
      if (box && box.cols === size.cols && box.rows === size.rows) fit.fit()
      else xterm.resize(size.cols, size.rows)
    })
    // The box may have changed meanwhile; this looks at it as it stands.
    follow()
  }

  /* A client was started with the drawing's size. */
  function started(cols, rows) {
    waiting = null
    asked = false
    given = { cols, rows }
  }

  return { follow, resized, cursorAsked, read, release, started, atBottom, pin }
}
