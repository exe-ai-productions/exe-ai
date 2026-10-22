/* A box that reaches down to the window's lower edge, less a margin, and
   never gets shorter than a floor: a Svelte action.

   The page scrolls inside its frame, so the box cannot take "what is left"
   from the layout; it is measured instead. Its top is taken at the scroll
   position zero of the nearest scrolling ancestor, so scrolling the page does
   not change the height. It is measured again when the window is resized and
   when the content above it changes size (the scrolling ancestor and its
   first child are watched). */

function scrollingAncestor(node) {
  for (let up = node.parentElement; up; up = up.parentElement) {
    const { overflowY } = getComputedStyle(up)
    if (overflowY === 'auto' || overflowY === 'scroll') return up
  }
  return null
}

export function fillToBottom(node, { reserve = 40, min = 320 } = {}) {
  const scroller = scrollingAncestor(node)

  function size() {
    const top = node.getBoundingClientRect().top + (scroller ? scroller.scrollTop : 0)
    const height = Math.max(min, Math.round(window.innerHeight - top - reserve))
    node.style.height = `${height}px`
  }

  size()
  window.addEventListener('resize', size)
  const watcher = new ResizeObserver(size)
  if (scroller) {
    watcher.observe(scroller)
    if (scroller.firstElementChild) watcher.observe(scroller.firstElementChild)
  }

  return {
    destroy() {
      window.removeEventListener('resize', size)
      watcher.disconnect()
    },
  }
}
