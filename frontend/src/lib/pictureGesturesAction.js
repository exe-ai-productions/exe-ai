/*
  The fingers of a picture, as a Svelte action: `use:gestures={options}` on
  the stage a picture sits in. It listens to the pointers of the stage and
  hands them to the decision in `pictureGestures.js`; what the decision says
  happened comes back as the callbacks named below. The picture itself is
  moved by the caller, from `onview` — the stage must not be the node that is
  transformed, or its middle would move with it.

  options (all optional):
    paint, swipe, natural, shown        as in `startGestures`, read at every touch
    resetKey                            a value that, when it changes, brings
                                        the view back to the whole picture
    sideways                            the page scrolls sideways by itself
                                        while the picture is whole (the
                                        studio's row of pictures): the stage
                                        leaves that to the browser and takes
                                        every touch only once zoomed
    onview(view), ontap(), ondouble(), onlong(), onswipe(step),
    onswipedown(), onpaintstart(point), onpaintmove(point), onpaintend(point),
    onpaintcancel()
*/
import { LONG_TIME, NEUTRAL, ZOOM_MIN, startGestures } from './pictureGestures.js'

export function gestures(node, options = {}) {
  let opts = options
  let tracker = null
  let timer = null
  let zoomed = false
  let key = opts.resetKey

  const stageSize = () => ({ w: node.clientWidth || 1, h: node.clientHeight || 1 })

  /* What the decision reads at every touch: always the options as they are
     now, so a changed `paint` does not throw the zoom away. */
  const live = {
    get paint() {
      return Boolean(opts.paint)
    },
    get swipe() {
      return Boolean(opts.swipe)
    },
    stageSize,
    natural: () => opts.natural?.() ?? null,
    shown: () => opts.shown?.() ?? null,
  }

  /* What the browser keeps for itself: nothing where this action takes every
     touch; the sideways scroll while a row of pictures shows them whole. */
  function claim() {
    node.style.touchAction = opts.sideways && !zoomed ? 'pan-x' : 'none'
  }

  function apply(effects) {
    for (const effect of effects) {
      switch (effect.kind) {
        case 'view':
        case 'double':
          zoomed = effect.view.zoom > ZOOM_MIN + 0.001
          claim()
          opts.onview?.(effect.view)
          if (effect.kind === 'double') opts.ondouble?.()
          break
        case 'tap':
          opts.ontap?.()
          break
        case 'long':
          opts.onlong?.()
          break
        case 'swipe':
          opts.onswipe?.(effect.step)
          break
        case 'swipe-down':
          opts.onswipedown?.()
          break
        case 'paint-start':
          opts.onpaintstart?.(effect.point)
          break
        case 'paint-move':
          opts.onpaintmove?.(effect.point)
          break
        case 'paint-end':
          opts.onpaintend?.(effect.point)
          break
        case 'paint-cancel':
          opts.onpaintcancel?.()
          break
        default:
      }
    }
  }

  const stopTimer = () => {
    if (timer !== null) clearTimeout(timer)
    timer = null
  }

  /* Fingers only. A mouse keeps the browser's own clicks and drags, and a
     pointer that is not captured keeps the click on the element that was
     pressed — the reader closes on a click beside the picture, not on it. A
     touch holds on to the node it began on by itself. */
  const fingerOnly = (event) => event.pointerType !== 'mouse'
  // A video keeps its own controls: a touch that begins on it is its own.
  const onVideo = (event) => Boolean(event.target?.closest?.('video'))

  function down(event) {
    if (!fingerOnly(event) || onVideo(event)) return
    const first = !tracker.touching
    apply(tracker.down(event.pointerId, event.clientX, event.clientY, event.timeStamp, node.getBoundingClientRect()))
    stopTimer()
    if (first && opts.onlong) timer = setTimeout(() => apply(tracker.hold()), LONG_TIME)
  }

  function move(event) {
    if (!fingerOnly(event)) return
    apply(tracker.move(event.pointerId, event.clientX, event.clientY))
  }

  function up(event) {
    if (!fingerOnly(event)) return
    stopTimer()
    apply(tracker.up(event.pointerId, event.clientX, event.clientY, event.timeStamp))
  }

  function cancel(event) {
    if (!fingerOnly(event)) return
    stopTimer()
    apply(tracker.cancel())
  }

  tracker = startGestures(live)
  claim()
  node.addEventListener('pointerdown', down)
  node.addEventListener('pointermove', move)
  node.addEventListener('pointerup', up)
  node.addEventListener('pointercancel', cancel)

  return {
    update(next) {
      opts = next
      claim()
      if (next.resetKey !== key) {
        key = next.resetKey
        tracker.reset()
        zoomed = false
        claim()
        opts.onview?.({ ...NEUTRAL })
      }
    },
    destroy() {
      stopTimer()
      node.removeEventListener('pointerdown', down)
      node.removeEventListener('pointermove', move)
      node.removeEventListener('pointerup', up)
      node.removeEventListener('pointercancel', cancel)
    },
  }
}
