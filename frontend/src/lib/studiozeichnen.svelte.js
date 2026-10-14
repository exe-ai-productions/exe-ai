/*
  Drawing from the picture studio: the chat's values become one request
  per picture, handed to the queue the chat keeps (App.svelte
  `bildLokalZeichnen`). The request carries every field the draw route
  reads from a chat's picture values.

  Without an open chat, drawing opens one first, and the new chat starts
  with what the studio holds — its values, its kind, its control video. So
  does a chat that is created any other way while the studio shows values
  without one. A chat opened that way stays, whatever becomes of its
  pictures: the studio never deletes a chat.
*/
import { tick } from 'svelte'
import { api } from './api.js'
import { chatNameFrom } from './chatName.js'
import { chatStateRead, chatanzeige, chatless } from './chatanzeige.svelte.js'
import { imageSwitches } from './imageSwitches.svelte.js'
import { seedlage } from './bildseed.svelte.js'
import { familyOf } from './imageFamilies.svelte.js'
import {
  art, auswahl, drawAsked, leinwand, maskIntoChat, pictureMissing, refVideo, setValues,
  startValuesThere, steuervideo, stilVon, studioSichtbar, takesRefVideo, werte,
} from './studio.svelte.js'
import { t } from './texte.svelte.js'
import { videoFrames as takeVideoFrames } from './videoFrames.js'
import { melde, openNewChat, zustand } from './zustand.svelte.js'

// sd-cli's own frame rate, what control frames are taken at without one —
// and the rate it reads a reference video at.
const SD_CLI_FPS = 24

/* The chat's picture line, handed in by the studio while it is mounted:
   its way in, the stop of the picture drawing now, a waiting one taken out. */
export const zeichnung = $state({
  losZeichnen: null, stopEins: null, entfernen: null, bereitet: false,
})

// An empty or cleared number field is no number; NaN is none either.
function zahl(wert, vorgabe) {
  const z = Number(wert)
  return wert === '' || wert === undefined || wert === null || Number.isNaN(z) ? vorgabe : z
}

/* What the next draw sends as its seed: fresh, held, or one step on from
   the last picture drawn (the server reports it). */
function seedFuerLauf(w) {
  const text = String(w.seed ?? '').trim()
  const feld = /^\d+$/.test(text) ? Number(text) : null
  if (w.seed_modus === 'zufall') return -1
  if (w.seed_modus === 'fest') return feld ?? seedlage.letzter ?? -1
  const basis = seedlage.letzter ?? feld
  if (basis === null) return -1
  return Math.max(0, basis + (w.seed_modus === 'plus' ? 1 : -1))
}

// The set switches only; the machine's own stay the picture server's.
function gesetzteSchalter(werte) {
  const maschine = (key) => imageSwitches.list.find((row) => row.key === key)?.machine
  return Object.fromEntries(Object.entries(werte ?? {}).filter(([key, wert]) =>
    wert !== '' && wert !== false && wert !== null && !maschine(key)))
}

/* The frames of a video, taken by the window and laid among the service's
   working pictures: their names. The last taking for each `place` a video
   is laid down in is kept while file, rate and count stay the same —
   drawing again takes the same pictures instead of taking and sending
   them anew. The service empties its working pictures only when it
   starts, and a page that outlives a start reloads itself (lib/api.js), so
   a kept name is one that is there. */
const taken = {}
async function framesOf(place, file, rate, count) {
  const last = taken[place]
  if (last && last.file === file && last.rate === rate && last.count === count) return last.names
  const frames = await takeVideoFrames(file, rate, count)
  const names = []
  for (const frame of frames) names.push((await api.bildHochladen(frame, true)).bild)
  taken[place] = { file, rate, count, names }
  return names
}

/* The control video's frames, taken now at the rate and count the fields
   say; their names, or null. */
async function steuerbilder(w) {
  const datei = steuervideo.datei
  if (!datei) {
    melde(t('bild.steuervideo_fehlt'), 'hinweis')
    return null
  }
  const rateFeld = zahl(w.fps, null) === null ? null : Math.trunc(zahl(w.fps, 0))
  const anzahlFeld = zahl(w.video_frames, null) === null ? null : Math.trunc(zahl(w.video_frames, 0))
  try {
    const names = await framesOf('control', datei, rateFeld ?? SD_CLI_FPS, anzahlFeld ?? 1)
    return { names, rate: rateFeld, count: anzahlFeld }
  } catch (fehler) {
    melde(String(fehler.message || fehler), 'fehler')
    return null
  }
}

/* The reference video's frames, taken now: sd-cli reads them at its own
   rate and uses no more of them than the video it draws has frames — one
   without a count, as for the control video. Their names, or null. */
async function referenceFrames(w) {
  const count = zahl(w.video_frames, null) === null ? 1 : Math.trunc(zahl(w.video_frames, 0))
  try {
    return await framesOf('reference', refVideo.datei, SD_CLI_FPS, count)
  } catch (fehler) {
    melde(String(fehler.message || fehler), 'fehler')
    return null
  }
}

/* What was set in the studio while no chat is open goes with the chat that
   is created from the window next, whichever way creates it: the values set
   there start that chat's store — those only, so every other value stays
   the model's start value, as it was shown — and the control video and the
   painted mask move with it. That holds before the model's start values
   have arrived too: what is set is told from what was filled in, not from
   what the model starts at.

   Only while the studio is what the window shows — its values are filled
   for the window then, not left over from a chat opened behind it — or
   while a draw that was pressed there is still being prepared: a menu page
   opened over the studio since then changes nothing about whose values
   these are. */
chatless.pictureValues = (chatId) => {
  if (chatanzeige.chatId || !(studioSichtbar() || zeichnung.bereitet)) return null
  if (steuervideo.datei) steuervideo.chat = chatId
  if (refVideo.datei) refVideo.chat = chatId
  maskIntoChat(chatId)
  const set = setValues()
  // Nothing set is nothing to store: the service keeps no empty store.
  return Object.keys(set).length ? set : null
}

/* The references of an edit: the picture in the generation area first, as
   the area holds it, then the ones laid down in the right column. A family
   that takes one reference has the area as its one place for it. */
function references(w, fam, inArea) {
  const first = inArea ? [inArea] : []
  if (!fam?.many_references) return first
  return [...first, ...w.ref_bilder.filter((name) => name !== w.startbild)]
}

/* One draw: as many requests as pictures per run, or one for a mode on a
   finished picture (`modeWish`: upscale, the detector alone). */
export async function studioZeichnen(modeWish = null) {
  /* One press at a time while it is prepared — frames, the area's files, a
     new chat: a second press then would open a second chat. The pictures
     themselves queue up in the chat's line, not here. */
  if (zeichnung.bereitet) return
  zeichnung.bereitet = true
  try {
    await vorbereitenUndZeichnen(modeWish)
  } finally {
    zeichnung.bereitet = false
  }
}

async function vorbereitenUndZeichnen(modeWish) {
  const losZeichnen = zeichnung.losZeichnen
  if (!losZeichnen) return
  /* In a chat, that chat's own values first: a press while its store is
     still being read draws once it is read and filled in, never with the
     default model the studio shows meanwhile. A read that failed draws
     nothing and says what it failed with. The press counts for the chat it
     was made in. */
  const chat = chatanzeige.chatId
  if (chat) {
    let read
    do {
      read = chatStateRead()
      await read
    } while (read !== chatStateRead())
    if (chatanzeige.chatId !== chat) return
    if (!chatanzeige.geladen) {
      if (chatanzeige.readError) melde(chatanzeige.readError, 'fehler')
      return
    }
    // The column fills the read store in within this breath.
    await tick()
  }
  /* The shown model's start values next: a press while they are on their
     way draws with them once they are laid in, never with the values the
     fields start at. */
  const startValues = await startValuesThere()
  if (chatanzeige.chatId !== chat) return
  /* The values as they stand now, before anything below is prepared:
     opening a chat refills the studio from that chat's store meanwhile. */
  const w = $state.snapshot(werte)
  // Without a prompt nothing is drawn, and the press says so.
  if (!modeWish && !w.prompt.trim()) {
    melde(t('studio.no_prompt'), 'hinweis')
    return
  }
  if (!w.modell) {
    melde(t('bildserver.kein_standardmodell'), 'hinweis')
    return
  }
  // They did not arrive: nothing is drawn, the failed request has said so.
  if (!startValues) return
  const kind = art()
  /* A kind that draws from a picture draws nothing while none is there —
     it is never drawn from the text instead. */
  if (!modeWish && pictureMissing()) return
  /* The family as it stands at the press, too: the column that refills for
     a new chat asks for the default model's family on the way. */
  const fam = familyOf(w.familie || auswahl.klasse)
  // A ControlNet goes along only for a family sd.cpp computes it for; a
  // model whose family is unknown is left as it was.
  const controlNet = !fam || fam.control_net !== false
  let control = null
  if (!modeWish && kind.value === 'v2v') {
    control = await steuerbilder(w)
    if (!control) return
  }
  /* A reference video counts for the chat it was laid down in: the column
     that lets it go for another chat may be hidden behind a tool. */
  let reference = null
  if (!modeWish && refVideo.datei && refVideo.chat === chat && takesRefVideo(kind, fam)) {
    reference = await referenceFrames(w)
    if (!reference) return
  }
  // The picture and mask as the generation area holds them, taken before
  // a new chat refills the surface: the picture to start from, or the first
  // reference of an edit.
  const nutztStart = ['img2img', 'i2v', 'flf2v'].includes(kind.value)
  const edits = kind.value === 'edit'
  const fromArea = nutztStart || edits
  let flaeche = null
  if (!modeWish && fromArea && w.startbild && leinwand.ausgeben) {
    try {
      flaeche = await leinwand.ausgeben(w.startbild, kind.value === 'img2img' || edits, edits)
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
      return
    }
  }
  /* Drawn from a part of the picture in the area, the result is that
     picture with the drawn piece set back in its place: the picture's name
     and where the part lies in it go along. Only for a picture drawn from
     a picture — a reference and a video have no place to go back to. */
  const place = kind.value === 'img2img' ? flaeche?.place ?? null : null
  let ziel = chatanzeige.chatId
  if (!ziel) {
    // No chat yet: one is opened, named after the prompt by the rule every
    // new chat is named by.
    const title = chatNameFrom(w.prompt) || t('eingabe.bild_titel')
    try {
      ziel = (await openNewChat({ title, endpoint_id: zustand.modellId || null })).id
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
      return
    }
  }
  const paintedEdit = edits && Boolean(flaeche?.maske)
  const stil = stilVon(w.stil)
  const ganz = (wert) => Math.trunc(zahl(wert, 0))
  const drawsVideo = kind.video
  const adAn = Boolean(w.ad_modell)
  const hires = Boolean(w.hires_wahl)
  const grund = {
    modell: w.modell,
    chat_id: ziel,
    prompt: w.prompt.trim(),
    negativ: w.negativ.trim(),
    stil_text: stil?.text ?? '',
    stil_negativ: stil?.negativ ?? '',
    breite: w.breite,
    hoehe: w.hoehe,
    schritte: w.schritte,
    cfg: w.cfg,
    seed: seedFuerLauf(w),
    sampler: w.sampler,
    scheduler: w.scheduler,
    loras: w.stapel.filter((e) => e.name).map((e) => ({ name: e.name, staerke: e.staerke })),
    lora_apply_mode: w.lora_modus,
    // An edit draws from its reference alone; with a mask painted over it
    // the picture goes as the starting picture as well, so the mask has a
    // picture to act on and the strength a start to measure from.
    startbild: nutztStart ? flaeche?.startbild ?? (w.startbild || null)
      : paintedEdit ? flaeche.startbild : null,
    // The strength control is not shown for an edit, and a picture laid
    // into the area leaves it below 1: that hidden value would let the
    // reference stand almost unchanged, so the mask alone decides.
    staerke: paintedEdit ? 1 : w.staerke,
    maske: kind.value === 'img2img' ? flaeche?.maske ?? (w.maske || null)
      : paintedEdit ? flaeche.maske : null,
    crop_of: place ? w.startbild : null,
    crop_box: place,
    video: drawsVideo,
    video_frames: control ? control.count
      : drawsVideo && zahl(w.video_frames, null) !== null ? ganz(w.video_frames) : null,
    fps: control ? control.rate
      : drawsVideo && zahl(w.fps, null) !== null ? ganz(w.fps) : null,
    end_bild: kind.value === 'flf2v' ? w.end_bild || null : null,
    steuerbilder: control ? control.names : [],
    ref_video_frames: reference ?? [],
    ref_bilder: kind.value === 'edit' ? references(w, fam, flaeche?.startbild ?? w.startbild) : [],
    img_cfg: kind.value === 'edit' ? zahl(w.img_cfg, null) : null,
    ref_image_args: kind.value === 'edit' ? w.ref_image_args.trim() : '',
    increase_ref_index: kind.value === 'edit' && Boolean(w.increase_ref_index),
    clip_skip: w.clip_skip == null || w.clip_skip === ''
      ? -1 : Math.max(1, Math.round(Number(w.clip_skip))),
    vae_format: w.vae_format === 'auto' ? '' : w.vae_format,
    rng: w.rng,
    weight_type: w.weight_type === 'auto' ? '' : w.weight_type,
    ad_modell: w.ad_modell || null,
    ad_prompt: w.ad_prompt.trim(),
    ad_loras: adAn
      ? w.ad_stapel.filter((e) => e.name).map((e) => ({ name: e.name, staerke: e.staerke })) : [],
    ad_negativ: adAn ? w.ad_negativ.trim() : '',
    ad_confidence: adAn ? zahl(w.ad_confidence, null) : null,
    pm_klasse: w.pm_klasse,
    pulid_weights: w.pulid_weights || null,
    pulid_id_embedding: w.pulid_id_embedding || null,
    pulid_id_weight: w.pulid_id_weight,
    // Only where the family's model computes a ControlNet (the family
    // table's `control_net`); a model without a known family sends it.
    control_net: controlNet ? w.control_net || null : null,
    control_image: controlNet ? w.control_image || null : null,
    control_strength: w.control_strength,
    canny: controlNet && Boolean(w.canny),
    hires,
    // Left out while the pass is off: the service keeps its own.
    hires_scale: hires ? Number(w.hires_wahl) : undefined,
    hires_steps: ganz(w.hires_steps),
    hires_denoise: zahl(w.hires_denoise, 0),
    hires_upscaler: w.hires_upscaler,
    hires_width: ganz(w.hires_breite),
    hires_height: ganz(w.hires_hoehe),
    eta: zahl(w.eta, null),
    flow_shift: zahl(w.flow_shift, null),
    sigmas: w.sigmas.trim(),
    extra_sample_args: w.extra_sample_args.trim(),
    switches: gesetzteSchalter(w.switches),
    prediction: w.prediction === 'auto' ? '' : w.prediction,
    guidance: zahl(w.guidance, null),
    familie: w.familie || fam?.name || null,
    model_args: w.model_args.trim(),
    slg_scale: zahl(w.slg_scale, 0),
    skip_layer_start: w.skip_layer_start,
    skip_layer_end: w.skip_layer_end,
    skip_layers: w.skip_layers.trim(),
    live_preview: w.live_preview,
    preview_interval: w.live_preview && zahl(w.preview_interval, null) !== null
      ? ganz(w.preview_interval) : null,
    preview_noisy: Boolean(w.live_preview) && Boolean(w.preview_noisy),
    taesd: w.live_preview === 'tae' ? w.taesd || null : null,
  }
  /* The picture this draw finishes comes into the generation area by
     itself; a finished video stays in the row of pictures. Every picture
     of the run is drawn from what stood in the area at this press. */
  if (modeWish || !drawsVideo) drawAsked(ziel)
  if (modeWish) {
    const base = modeWish.mode === 'upscale'
      ? { modell: w.modell, chat_id: ziel, prompt: modeWish.prompt }
      : grund
    // An enlarging that has no prompt writes no question into the chat.
    losZeichnen({ ...base, ...modeWish, von: 1, nr: 1, lauf_kennung: null,
                  frage_erstellen: Boolean(modeWish.prompt) })
    return
  }
  const anzahl = Math.max(1, ganz(w.bilder_je_lauf) || 1)
  // Not `crypto.randomUUID()`: over plain HTTP the page is no secure context.
  const laufKennung = anzahl > 1
    ? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}` : null
  for (let nr = 1; nr <= anzahl; nr += 1) {
    losZeichnen({ ...grund, von: anzahl, nr, lauf_kennung: laufKennung, frage_erstellen: nr === 1 })
  }
}

/* The values the next draw would send that decide which painter draws it,
   as they stand now — what the service is asked about while the picture
   server runs, so the footer can say which control sends the picture to
   sd-cli. Null while no model is chosen. */
export function painterQuery() {
  const w = $state.snapshot(werte)
  if (!w.modell) return null
  const kind = art()
  const fam = familyOf(w.familie || auswahl.klasse)
  const adAn = Boolean(w.ad_modell)
  const named = (stapel) => (stapel ?? []).some((entry) => entry.name)
  return {
    modell: w.modell,
    live_preview: w.live_preview,
    pulid_weights: w.pulid_weights || null,
    pulid_id_embedding: w.pulid_id_embedding || null,
    sigmas: w.sigmas.trim(),
    slg_scale: zahl(w.slg_scale, 0),
    skip_layers: w.skip_layers.trim(),
    switches: gesetzteSchalter(w.switches),
    // As the draw sends it: the service reads the model's kit with it.
    familie: w.familie || fam?.name || null,
    ref_video: Boolean(
      refVideo.datei && refVideo.chat === chatanzeige.chatId && takesRefVideo(kind, fam),
    ),
    lora: named(w.stapel) || (adAn && named(w.ad_stapel)),
    ad_modell: adAn,
    hires: Boolean(w.hires_wahl),
    video: Boolean(kind.video),
    lora_apply_mode: w.lora_modus,
    pm_klasse: w.pm_klasse,
  }
}
