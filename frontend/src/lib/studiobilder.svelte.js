/* What "···" does with one picture of the studio — on a tile of the row of
   pictures and on the generation area alike: as the input, to a video, its
   infos, the faces redone, upscaled. The infos are a card on the surface
   (StudioPictureInfo.svelte); "Use" writes their values into the fields. */
import { api } from './api.js'
import { chatanzeige } from './chatanzeige.svelte.js'
import { auswahl, emptyArea, familie, listen, pictureMissing, startbildWaehlen, werte } from './studio.svelte.js'
import { studioZeichnen } from './studiozeichnen.svelte.js'
import { t } from './texte.svelte.js'
import { melde } from './zustand.svelte.js'

export const bildInfo = $state({ werte: null })

export function alsEingabe(name) {
  startbildWaehlen(name)
}

/* A finished picture as the first frame of a video: the video half, the
   first kind of it that starts from a picture. A model whose family draws
   none says so; one whose family is unknown is left to try. */
const FROM_PICTURE = ['i2v', 'flf2v']
export function zuVideo(name) {
  const family = familie()
  const kind = family ? FROM_PICTURE.find((task) => family.tasks.includes(task)) : FROM_PICTURE[0]
  if (!kind) {
    melde(t('bild.kein_video_aus_bild'), 'hinweis')
    return
  }
  // The half first: the picture then starts at a video's strength.
  auswahl.medium = 'video'
  auswahl.art = kind
  startbildWaehlen(name)
}

/* The words the faces are redone with: the prompt bar's, otherwise what the
   program kept for this picture. Where it kept none — a picture that was
   uploaded — nothing is drawn: the detector asks for a prompt, and a word of
   the surface is no prompt. A look-up that fails counts as nothing kept. */
export async function nachbessern(name) {
  if (!werte.ad_modell) {
    melde(t('bild.modus_unvollstaendig'), 'fehler')
    return
  }
  const fuer = chatanzeige.chatId
  let prompt = werte.prompt.trim()
  if (!prompt) {
    const gefunden = await api.drawnWith(name).catch(() => null)
    prompt = typeof gefunden?.prompt === 'string' ? gefunden.prompt.trim() : ''
    // Another chat was opened while the question was on its way.
    if (fuer !== chatanzeige.chatId) return
  }
  if (!prompt) {
    melde(t('studio.no_prompt'), 'hinweis')
    return
  }
  studioZeichnen({ mode: 'adetailer', startbild: name, maske: null, prompt })
}

/* Enlarging reads no prompt: the new picture keeps the one the program kept
   for this picture, otherwise the bar's, otherwise none — and a picture
   without one is enlarged all the same, without a word of the surface in
   its place. The model is the one chosen in the row "Upscaler", otherwise
   the first of the folder. A look-up that fails counts as nothing kept. */
export async function hochskalieren(name) {
  const upscaler = listen.upscalers.includes(werte.upscale_model) ? werte.upscale_model : listen.upscalers[0]
  if (!upscaler) {
    melde(t('bild.modus_unvollstaendig'), 'fehler')
    return
  }
  const fuer = chatanzeige.chatId
  const gefunden = await api.drawnWith(name).catch(() => null)
  // Another chat was opened while the question was on its way.
  if (fuer !== chatanzeige.chatId) return
  const gemerkt = typeof gefunden?.prompt === 'string' ? gefunden.prompt.trim() : ''
  studioZeichnen({ mode: 'upscale', startbild: name, maske: null, upscale_model: upscaler,
                   prompt: gemerkt || werte.prompt.trim() })
}

/* "Remove" on the picture in the generation area: the area is emptied, and
   a mode that cannot draw without the picture goes back to "auto", as the
   strength goes back to 1; one that can stays chosen. */
export function bildEntfernen() {
  emptyArea()
  if (pictureMissing()) auswahl.art = 'auto'
}

/* What a picture was drawn with: what the program kept for it, asked for
   by its name; where it kept nothing — a picture drawn elsewhere, or one
   from before the program kept any — what the file itself says. A question
   for the kept values that fails counts as nothing kept: the file is read
   all the same. Only the newest question counts, and only for the chat
   that asked it. */
let infoAnfrage = 0
export async function infosZeigen(name) {
  const nr = ++infoAnfrage
  const fuer = chatanzeige.chatId
  try {
    let gefunden = await api.drawnWith(name).catch(() => null)
    if (!gefunden || !Object.keys(gefunden).length) {
      gefunden = await api.pictureInfo(await api.bildBlob(name))
    }
    if (nr === infoAnfrage && fuer === chatanzeige.chatId) bildInfo.werte = gefunden ?? {}
  } catch (fehler) {
    if (nr === infoAnfrage) melde(String(fehler.message || fehler), 'fehler')
  }
}

/* Into the fields. A model that is not in the folder leaves the model as it
   is; the values are meant as given. */
export function infoUebernehmen() {
  const i = bildInfo.werte ?? {}
  if (i.modell && listen.modelle.includes(i.modell)) werte.modell = i.modell
  for (const name of ['prompt', 'negativ', 'breite', 'hoehe', 'schritte', 'cfg', 'guidance', 'sampler', 'scheduler']) {
    if (i[name] !== undefined) werte[name] = i[name]
  }
  if (i.seed !== undefined) {
    werte.seed = String(i.seed)
    werte.seed_modus = 'fest'
  }
  bildInfo.werte = null
}
