/*
  The row of pictures of the studio's surface on the phone, as lists: which
  pictures the swipe pages through, which tiles the strip under it shows,
  which one stands on show and where the dots under the surface stand.

  The studio's pictures are the ones it drew, newest first, with the picture
  last laid in from outside (the original) on top and the picture drawing now
  in front of all. Waiting pictures have a tile in the strip and no page of
  their own: there is nothing to see of them yet.

  No imports, so the decisions can be tried without a window around them.
*/

/** The pages: the picture drawing now, the picture in the area when none of
    the others is it (one chosen from the chat or a folder), the original,
    then the drawn ones. */
export function pagesOf({ running, held = '', original, names }) {
  const pages = []
  if (running) pages.push({ key: `run:${running.id}`, kind: 'running', id: running.id })
  if (held && held !== original && !names.includes(held)) pages.push({ key: `pic:${held}`, kind: 'picture', name: held })
  if (original) pages.push({ key: `pic:${original}`, kind: 'picture', name: original, original: true })
  for (const name of names) {
    if (name !== original) pages.push({ key: `pic:${name}`, kind: 'picture', name })
  }
  return pages
}

/** The tiles of the strip: the pages, with the waiting pictures behind the
    one drawing (before the pictures that are done). */
export function tilesOf({ running, waiting, held = '', original, names }) {
  const tiles = []
  if (running) tiles.push({ key: `run:${running.id}`, kind: 'running', id: running.id })
  for (const entry of waiting) tiles.push({ key: `wait:${entry.id}`, kind: 'waiting', id: entry.id })
  if (held && held !== original && !names.includes(held)) tiles.push({ key: `pic:${held}`, kind: 'picture', name: held })
  if (original) tiles.push({ key: `pic:${original}`, kind: 'picture', name: original, original: true })
  for (const name of names) {
    if (name !== original) tiles.push({ key: `pic:${name}`, kind: 'picture', name })
  }
  return tiles
}

/** The page on show: the one that holds the picture in the area; none in the
    area — the picture drawing now (it is first), else none: the surface is
    empty, as it is where the picture was taken out of the area. */
export function shownIndex(pages, area) {
  if (!pages.length) return -1
  const at = area ? pages.findIndex((page) => page.name === area) : -1
  if (at >= 0) return at
  return pages[0].kind === 'running' ? 0 : -1
}

/** Which page a scroll position rests on. */
export function pageAt(scrollLeft, width, count) {
  if (!count || !width) return 0
  return Math.min(count - 1, Math.max(0, Math.round(scrollLeft / width)))
}

/** The dots under the surface: at most `max`, the one on show among them,
    and where it stands in them. */
export function dotsOf(count, index, max = 7) {
  if (count < 2) return { dots: 0, at: -1 }
  if (count <= max) return { dots: count, at: index }
  const half = Math.floor(max / 2)
  const start = Math.min(count - max, Math.max(0, index - half))
  return { dots: max, at: index - start }
}
