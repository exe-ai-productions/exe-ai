/*
  What the phone's surface hands the draw: the picture in the area and the
  mask painted over it, as the generator takes them.

  The desktop's drawing surface does this itself (`StudioCanvas.svelte` sets
  `leinwand.ausgeben`); on the phone the surface only shows the picture, so the
  same hand-over is made here from the picture and the mask layer the mask
  page painted. A picture that has the area's shape goes as it is; any other
  is laid whole into the middle of an area-sized canvas, black where it does
  not reach, and its mask with it. A picture with nothing painted over it
  needs nothing: the draw takes the picture's own name.
*/
import { api } from '../../lib/api.js'
import { alsSchwarzWeiss, bemalt } from '../../lib/maske.js'
import { studioMask, surface, werte } from '../../lib/studio.svelte.js'
import { t } from '../../lib/texte.svelte.js'
import { fitInto, sameShape } from './format.js'

/* The picture's own pixels: loaded from the pictures folder, once per name
   while the studio stands. */
const loaded = new Map()
const KEPT = 2
export function loadPicture(name) {
  if (!loaded.has(name)) {
    // Only the last few stay: a picture's own pixels are large.
    while (loaded.size >= KEPT) loaded.delete(loaded.keys().next().value)
    loaded.set(
      name,
      new Promise((done, failed) => {
        const image = new Image()
        image.onload = () => done(image)
        image.onerror = () => {
          loaded.delete(name)
          failed(new Error(t('studio.encode_failed')))
        }
        image.src = api.bildAdresse(name)
      }),
    )
  }
  return loaded.get(name)
}

/* What the area puts together is a working picture: made for the draw,
   never one of the picture folder. */
async function upload(canvas, name) {
  const blob = await new Promise((done) => canvas.toBlob(done, 'image/png'))
  if (!blob) throw new Error(t('studio.encode_failed'))
  return (await api.bildHochladen(new File([blob], name, { type: 'image/png' }), true)).bild
}

function layOnArea(source, geometry, width, height) {
  const target = document.createElement('canvas')
  target.width = width
  target.height = height
  const pen = target.getContext('2d')
  pen.fillStyle = '#000'
  pen.fillRect(0, 0, width, height)
  pen.drawImage(
    source,
    geometry.x,
    geometry.y,
    source.naturalWidth ? source.naturalWidth * geometry.zoom : source.width * geometry.zoom,
    source.naturalHeight ? source.naturalHeight * geometry.zoom : source.height * geometry.zoom,
  )
  return target
}

/* `withMask`: the kind draws over a mask. Null while there is nothing to
   change about the picture's own name. */
export async function handOver(name, withMask) {
  if (!name || name !== werte.startbild) return null
  const areaWidth = Math.max(64, Number(werte.breite) || 1024)
  const areaHeight = Math.max(64, Number(werte.hoehe) || 1024)
  const picture = await loadPicture(name)
  const layer = withMask && surface.maskOn ? studioMask(name)?.flaeche : null
  const painted = Boolean(layer && bemalt(layer))
  const whole = sameShape(picture.naturalWidth, picture.naturalHeight, areaWidth, areaHeight)
  if (whole && !painted) return null
  const geometry = fitInto(picture.naturalWidth, picture.naturalHeight, areaWidth, areaHeight)
  const blackWhite = painted ? alsSchwarzWeiss(layer) : null
  const startbild = whole ? name : await upload(layOnArea(picture, geometry, areaWidth, areaHeight), 'startbild.png')
  const maske = blackWhite
    ? await upload(whole ? blackWhite : layOnArea(blackWhite, geometry, areaWidth, areaHeight), 'maske.png')
    : null
  return { startbild, maske, place: null }
}
