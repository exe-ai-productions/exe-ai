/* Where the generation area stands on the drawing surface: the studio's
   width × height, fitted into the room the surface leaves it. Plain
   numbers in, plain numbers out, so the room can be measured without a
   window. */

/* Room the area leaves around itself: on the right the row of pictures
   (its bar stands 14 to 90 px from the edge, 12 px of air after it), and
   as much on the left, so it stands in the middle; the bar and the area's
   label above, the prompt bar below. The area never slides under the bar. */
export const SIDE_ROOM = 102
// Room above the area for its two rows (the picture's resolution, the
// area's size) under the zoom, which ends 44 px from the top.
export const TOP_ROOM = 122
export const BOTTOM_ROOM = 274
/* The bar of the brush stands at the top between the tools and the zoom
   while the surface is wide enough for the widest bar (621.5 px, plus the
   64 px of the tools and the 194 px of the zoom). Narrower, it stands in a
   row of its own under the zoom, 40 px lower (its top at 52 instead of 12),
   and the area keeps that row free: with the hand chosen too, so the area
   does not jump when the tool changes. */
export const BRUSH_BAR_MIN_WIDTH = 880
export const BRUSH_ROW_ROOM = 40

export function brushBarAbove(surfaceWidth) {
  return surfaceWidth >= BRUSH_BAR_MIN_WIDTH
}

/* `surfaceWidth`/`surfaceHeight` is the surface's size, `width`/`height`
   the area's in generated pixels. `s` is the scale of the fit, `x`/`y` the
   area's top left corner on the surface. */
export function fitArea(surfaceWidth, surfaceHeight, width, height) {
  const top = TOP_ROOM + (brushBarAbove(surfaceWidth) ? 0 : BRUSH_ROW_ROOM)
  const s = Math.max(
    0.01,
    Math.min((surfaceWidth - 2 * SIDE_ROOM) / width, (surfaceHeight - top - BOTTOM_ROOM) / height),
  )
  const w = width * s
  const h = height * s
  return {
    s, w, h,
    x: (surfaceWidth - w) / 2,
    y: top + Math.max(0, (surfaceHeight - top - BOTTOM_ROOM - h) / 2),
  }
}
