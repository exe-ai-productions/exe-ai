/*
  The sizes the studio's surface offers on the phone: the format tiles, what
  the size chip says and which tile a size stands on.

  The same rule the desktop's format tiles follow (`StudioBasics.svelte`): a
  tile sets the long edge to the one the size has and works the short one
  out from the ratio, rounded up onto sd.cpp's grid of 64. A size that is no
  tile's is "custom" and sets nothing.

  No imports, so the arithmetic can be tried without a window around it.
*/

/* sd.cpp's grid: an edge is a multiple of it. */
export const GRID = 64

export const FORMATS = [
  [1, 1],
  [3, 4],
  [4, 3],
  [2, 3],
  [3, 2],
  [9, 16],
  [16, 9],
]

/** `[width, height]` of a format at a long edge. */
export function formatPair([a, b], long) {
  const short = Math.ceil(((long / GRID) * Math.min(a, b)) / Math.max(a, b)) * GRID
  return a >= b ? [long, short] : [short, long]
}

/** The format a size stands on exactly, or null for a custom size. */
export function chosenFormat(width, height) {
  const w = Number(width)
  const h = Number(height)
  const long = Math.max(w, h)
  if (!long || long % GRID) return null
  return (
    FORMATS.find((format) => {
      const [fw, fh] = formatPair(format, long)
      return fw === w && fh === h
    }) ?? null
  )
}

/** The long edge a tile starts from: the edge the studio started with when it
    knows one, else the longer of the two now, rounded up onto the grid. */
export function longEdge(startEdge, width, height) {
  const long = startEdge || Math.max(Number(width) || 0, Number(height) || 0)
  return long ? Math.ceil(long / GRID) * GRID : 0
}

/** What the size chip says. */
export const sizeLabel = (width, height) => `${Number(width) || 0} × ${Number(height) || 0}`

/** The shape a tile draws, inside a square of `box` pixels. */
export function tileShape(width, height, box = 16) {
  const w = Number(width) || 1
  const h = Number(height) || 1
  return w >= h ? [box, Math.max(4, (box * h) / w)] : [Math.max(4, (box * w) / h), box]
}

/** Whether a picture has the shape of the area it is drawn from, to within a
    pixel: it then goes as it is and needs no black edge. */
export const sameShape = (naturalWidth, naturalHeight, areaWidth, areaHeight) =>
  Math.abs(naturalWidth * areaHeight - naturalHeight * areaWidth) < naturalWidth

/** Where a picture lies when it is laid whole into the area, in the middle:
    the zoom, and its top left corner in the area's pixels. */
export function fitInto(naturalWidth, naturalHeight, areaWidth, areaHeight) {
  const zoom = Math.min(areaWidth / naturalWidth, areaHeight / naturalHeight)
  return {
    zoom,
    x: (areaWidth - naturalWidth * zoom) / 2,
    y: (areaHeight - naturalHeight * zoom) / 2,
  }
}
