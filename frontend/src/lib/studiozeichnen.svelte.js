/*
  Drawing from the picture studio: the studio's values become one request
  per picture, handed to the queue of the pictures (App.svelte
  `bildLokalZeichnen`). The request carries every field the draw route
  reads and says it is the studio's (`studio`): it names no chat, makes
  none and writes into none, whichever chat is open — the finished picture
  lies in the pictures folder and on the studio's own list.
*/
import { tick } from 'svelte'
import { api } from './api.js'
import { imageSwitches } from './imageSwitches.svelte.js'
import { seedlage } from './bildseed.svelte.js'
import { familyOf } from './imageFamilies.svelte.js'
import {
  art, auswahl, drawAsked, leinwand, listen, pictureMissing, refVideo,
  startValuesThere, steuervideo, stilVon, surface, takesRefVideo, werte,
} from './studio.svelte.js'
import { readStudioStore, studioStore } from './studioStore.svelte.js'
import { t } from './texte.svelte.js'
import { videoFrames as takeVideoFrames } from './videoFrames.js'
import { melde } from './zustand.svelte.js'
import { meldeText } from './meldewesen.svelte.js'

// sd-cli's own frame rate, what control frames are taken at without one —
// and the rate it reads a reference video at.
const SD_CLI_FPS = 24

/* The picture line, handed in by the studio while it is mounted:
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
  /* One press at a time while it is prepared — frames, the area's files: a
     second press then would draw from what the first is still taking. The
     pictures themselves queue up in the line of the pictures, not here. */
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
  /* The studio's own values first: a press while its store is still being
     read draws once it is read and filled in, never with the default model
     the studio shows meanwhile. A read that failed draws nothing and says
     what it failed with. */
  await readStudioStore()
  if (!studioStore.loaded) {
    if (studioStore.error) melde(studioStore.error, 'fehler')
    return
  }
  // The column fills the read store in within this breath.
  await tick()
  /* The shown model's start values next: a press while they are on their
     way draws with them once they are laid in, never with the values the
     fields start at. */
  const startValues = await startValuesThere()
  // The values as they stand now, before anything below is prepared.
  const w = $state.snapshot(werte)
  // Without a prompt nothing is drawn, and the press says so.
  if (!modeWish && !w.prompt.trim()) {
    melde(t('studio.no_prompt'), 'hinweis')
    return
  }
  if (!w.modell) {
    // A default model that misses a part says which one, not that none is chosen.
    const missing = listen.missingParts[listen.standardmodell]
    if (missing) meldeText('bild.teil_fehlt', { teil: missing }, 'hinweis')
    else melde(t('bildserver.kein_standardmodell'), 'hinweis')
    return
  }
  // They did not arrive: nothing is drawn, the failed request has said so.
  if (!startValues) return
  const kind = art()
  /* A kind that draws from a picture draws nothing while none is there —
     it is never drawn from the text instead. */
  if (!modeWish && pictureMissing()) return
  /* The family as it stands at the press, too: the column that refills asks
     for the default model's family on the way. */
  const fam = familyOf(w.familie || auswahl.klasse)
  // A ControlNet goes along only for a family sd.cpp computes it for; a
  // model whose family is unknown is left as it was.
  const controlNet = !fam || fam.control_net !== false
  let control = null
  if (!modeWish && kind.value === 'v2v') {
    control = await steuerbilder(w)
    if (!control) return
  }
  let reference = null
  if (!modeWish && refVideo.datei && takesRefVideo(kind, fam)) {
    reference = await referenceFrames(w)
    if (!reference) return
  }
  // The picture and mask as the generation area holds them: the picture to
  // start from, or the first reference of an edit.
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
  // A mask that is switched off goes nowhere: not the one painted, not the
  // one the studio has stored.
  const maskOn = surface.maskOn
  const paintedEdit = edits && maskOn && Boolean(flaeche?.maske)
  const stil = stilVon(w.stil)
  const ganz = (wert) => Math.trunc(zahl(wert, 0))
  const drawsVideo = kind.video
  const adAn = Boolean(w.ad_modell)
  const hires = Boolean(w.hires_wahl)
  const grund = {
    modell: w.modell,
    studio: true,
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
    maske: !maskOn ? null
      : kind.value === 'img2img' ? flaeche?.maske ?? (w.maske || null)
        : paintedEdit ? flaeche.maske : null,
    crop_of: place ? w.startbild : null,
    crop_box: place,
    video: drawsVideo,
    video_frames: control ? control.count
      : drawsVideo && zahl(w.video_frames, null) !== null ? ganz(w.video_frames) : null,
    // A family with a fixed rate draws at it whatever is sent.
    fps: fam?.fixed_fps ? null
      : control ? control.rate
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
  if (modeWish || !drawsVideo) drawAsked()
  if (modeWish) {
    const base = modeWish.mode === 'upscale'
      ? { modell: w.modell, studio: true, prompt: modeWish.prompt }
      : grund
    losZeichnen({ ...base, ...modeWish, von: 1, nr: 1, lauf_kennung: null })
    return
  }
  const anzahl = Math.max(1, ganz(w.bilder_je_lauf) || 1)
  // Not `crypto.randomUUID()`: over plain HTTP the page is no secure context.
  const laufKennung = anzahl > 1
    ? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}` : null
  for (let nr = 1; nr <= anzahl; nr += 1) {
    losZeichnen({ ...grund, von: anzahl, nr, lauf_kennung: laufKennung })
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
    preview_interval: w.live_preview && zahl(w.preview_interval, null) !== null
      ? Math.trunc(zahl(w.preview_interval, 0)) : null,
    preview_noisy: Boolean(w.live_preview) && Boolean(w.preview_noisy),
    preview_taesd: w.live_preview === 'tae' && Boolean(w.taesd),
    pulid_weights: w.pulid_weights || null,
    pulid_id_embedding: w.pulid_id_embedding || null,
    sigmas: w.sigmas.trim(),
    slg_scale: zahl(w.slg_scale, 0),
    skip_layers: w.skip_layers.trim(),
    switches: gesetzteSchalter(w.switches),
    // As the draw sends it: the service reads the model's kit with it.
    familie: w.familie || fam?.name || null,
    ref_video: Boolean(
      refVideo.datei && takesRefVideo(kind, fam),
    ),
    lora: named(w.stapel) || (adAn && named(w.ad_stapel)),
    ad_modell: adAn,
    hires: Boolean(w.hires_wahl),
    video: Boolean(kind.video),
    lora_apply_mode: w.lora_modus,
    pm_klasse: w.pm_klasse,
  }
}
