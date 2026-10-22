/*
  The mask session of one picture, in the steps it was painted with.

  The layer is as large as the picture and is never edited in place alone:
  every change is a step (a stroke, invert, clear) on a list, and the layer
  can always be painted again from what the studio had stored plus those
  steps — which is what undo and redo are, and what brings a layer back after
  another picture had the room. The same shape the desktop's surface keeps
  (`studioMask` in `lib/studio.svelte.js`: `flaeche`, `grund`, `verlauf`,
  `zukunft`), painted with the same brush (`lib/maske.js`).
*/
import { api } from '../../lib/api.js'
import { leeren, malflaeche, strich, umkehren } from '../../lib/maske.js'

/** One step painted onto a layer. */
export function applyStep(layer, step) {
  if (step.art === 'strich') {
    const points = step.punkte
    strich(layer, points[0], points[0], step.groesse, step.radiert)
    for (let i = 1; i < points.length; i += 1) strich(layer, points[i - 1], points[i], step.groesse, step.radiert)
  } else if (step.art === 'umkehren') {
    umkehren(layer)
  } else if (step.art === 'leeren') {
    leeren(layer)
  }
}

/** The layer from its ground (the stored mask, if any) and every step. */
export function replay(mask) {
  leeren(mask.flaeche)
  if (mask.grund) mask.flaeche.getContext('2d').drawImage(mask.grund, 0, 0)
  for (const step of mask.verlauf) applyStep(mask.flaeche, step)
}

/** A mask the studio has stored is black and white; here white is painted and
    black is free, so its brightness becomes the cover of the layer under the
    steps. What was painted while it loaded stays on top: `after` paints it
    again. */
export function loadStored(mask, layer, name, after) {
  const image = new Image()
  image.onload = () => {
    if (mask.flaeche !== layer) return
    const base = malflaeche(layer.width, layer.height)
    const pen = base.getContext('2d')
    pen.drawImage(image, 0, 0, layer.width, layer.height)
    const data = pen.getImageData(0, 0, layer.width, layer.height)
    const pixels = data.data
    for (let i = 0; i < pixels.length; i += 4) {
      const bright = Math.round((pixels[i] + pixels[i + 1] + pixels[i + 2]) / 3)
      pixels[i] = 255
      pixels[i + 1] = 255
      pixels[i + 2] = 255
      pixels[i + 3] = bright
    }
    pen.putImageData(data, 0, 0)
    mask.grund = base
    replay(mask)
    after?.()
  }
  image.src = api.bildAdresse(name)
}
