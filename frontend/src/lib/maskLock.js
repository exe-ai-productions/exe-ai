/*
  When the mask layer may be changed.

  The switch "Mask" decides whether the mask counts. A mask that is off is
  not hidden and kept painting under the surface — it is locked: the brush
  and the eraser leave no mark, their ring is gone, and the whole-layer
  actions rest. What was painted before stays and shows when the switch is
  turned on again.

  Kept apart from the drawing surface so the rule is read in one place and
  run on its own.
*/

/* The brush or the eraser, with the switch on. */
export function paintAllowed(tool, maskOn) {
  return Boolean(maskOn) && (tool === 'pinsel' || tool === 'radierer')
}

/* Invert and clear: a picture to act on, and the switch on. */
export function layerChangeable(maskOn, hasPicture) {
  return Boolean(maskOn) && Boolean(hasPicture)
}
