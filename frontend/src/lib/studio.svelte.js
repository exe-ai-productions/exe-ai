/*
  The picture studio: a view of its own, not a menu page. While it is open
  the three areas of the window swap their content — the sidebar shows the
  basics instead of the chat list, the chat tile is the drawing surface,
  the column on the right shows the details — and the chat itself stays
  loaded underneath, so closing the studio shows it exactly as it was.

  The studio belongs to no chat: its picture, mask, model and every value
  are kept once, for the studio (lib/studioStore.svelte.js), and opening,
  switching, creating or deleting a chat changes none of them.

  One shared state that every part reads (Seitenleiste.svelte, App.svelte,
  Arbeitsleiste.svelte). A menu page opened from the sidebar lies over the
  studio the way it lies over the chat; closing the page shows the studio
  again.
*/

import { zustand, eineSeiteOffen, seitenSchliessen, melde } from './zustand.svelte.js'
import { api } from './api.js'
import { familyOf, imageFamilies, loadImageFamilies } from './imageFamilies.svelte.js'
import { loadImageSwitches } from './imageSwitches.svelte.js'
import { columnsForStudio, columnsBack } from './studioColumns.svelte.js'
import { studioStore, writeStudioStore } from './studioStore.svelte.js'

/* `rechts`: what the right column shows while the studio is open — its
   details, or the tool picked from the row of signs at its foot. */
export const studio = $state({ offen: false, rechts: 'feinheiten' })

/* A video the user laid down for a draw: the file and the address it is
   shown from. Not kept in the store — a file from the user's disk is no
   name on the service — so it stays for the session only. */
function laidVideo() {
  const video = $state({ datei: null, url: '' })
  function release() {
    if (video.url) URL.revokeObjectURL(video.url)
    video.datei = null
    video.url = ''
  }
  function set(datei) {
    release()
    video.datei = datei
    video.url = URL.createObjectURL(datei)
    return true
  }
  return { video, set, release }
}

// The control video of a video drawn from a video.
const control = laidVideo()
export const steuervideo = control.video
export const steuervideoSetzen = control.set
export const steuervideoLoesen = control.release

// The reference video a family that takes one draws after.
const reference = laidVideo()
export const refVideo = reference.video
export const refVideoSet = reference.set
export const refVideoRelease = reference.release

/* Whether the studio is what the window shows right now: open, and no menu
   page lying over it. */
export function studioSichtbar() {
  return studio.offen && !eineSeiteOffen()
}

export function studioOeffnen() {
  // The studio takes the main area: a menu page lying there gives way.
  seitenSchliessen()
  if (studio.offen) return
  columnsForStudio()
  studio.rechts = 'feinheiten'
  studio.offen = true
}

export function studioSchliessen() {
  if (!studio.offen) return
  studio.offen = false
  columnsBack()
}

/* The studio opened on a picture of a chat: it stands in the generation
   area, the picture to start from. The left column fills the values from
   the studio's store when it comes up, so a picture handed over before that
   is noted like one chosen before the store arrived, and the filling keeps
   it. */
export function studioWithPicture(name) {
  const columnUp = studioSichtbar()
  studioOeffnen()
  startbildWaehlen(name)
  if (!columnUp) vorgemerkt = { startbild: name }
}

/* The studio's search: one field, at the top of the left column, over the
   rows of both columns. */
export const search = $state({ text: '' })
export const searching = () => Boolean(search.text.trim())

/* What the search does to one column, as an action on the column's root. A
   row stays while its name holds what was typed; a section stays while its
   head does or one of its rows stays. The rule reads the rows off the page
   itself — a row names itself with `data-suche`, a switch row with its
   label — so a row added later is found without a list kept here. */
export function searchRows(column) {
  const name = (row) => {
    if (row.dataset.suche) return row.dataset.suche
    // A switch row: the text of its name, without the ⓘ sentence.
    const label = row.querySelector(':scope > span')
    return [...(label?.childNodes ?? [])]
      .filter((part) => !part.classList?.contains('info'))
      .map((part) => part.textContent)
      .join('')
  }
  $effect(() => {
    const query = search.text.trim().toLowerCase()
    const apply = () => {
      for (const section of column.querySelectorAll('.abschnitt')) {
        const head = (section.dataset.suche ?? '').toLowerCase()
        const headMatches = Boolean(query) && head.includes(query)
        let shown = 0
        for (const row of section.querySelectorAll('[data-suche]:not(.abschnitt), .switchrow')) {
          const stays = !query || headMatches || name(row).toLowerCase().includes(query)
          row.hidden = !stays
          if (stays) shown += 1
        }
        // The fold's rows leave no empty band behind when none of them stays.
        for (const band of section.querySelectorAll('.schalterflaeche')) {
          band.hidden = [...band.children].every((row) => row.hidden)
        }
        section.hidden = Boolean(query) && !headMatches && shown === 0
      }
    }
    apply()
    if (!query) return
    // Rows that come and go while a search stands are sorted in too.
    const watch = new MutationObserver(apply)
    watch.observe(column, { childList: true, subtree: true })
    return () => watch.disconnect()
  })
}

/* The studio's sign at the foot of the sidebar: a second click closes the
   studio; with a menu page lying over it, the click brings it back. */
export function studioSchalten() {
  if (studioSichtbar()) studioSchliessen()
  else studioOeffnen()
}

/* The picture values as the studio shows them: the fields the service
   keeps for the studio (app/bildfensterwahl.py, key "bildfenster" in the
   global scope), read from and written to that one store. What the studio
   has no value of its own for starts at these. */
export const ANFANG = {
  /* The prompt bar: the prompt, its negative and the style it is drawn
     through (by the style's id, app/bildstile.py). */
  prompt: '',
  negativ: '',
  stil: '',
  modell: '',
  breite: 512,
  hoehe: 512,
  schritte: 20,
  cfg: 7,
  guidance: '',
  // Empty is "Auto": sd.cpp picks the model's own, until the model's start
  // values arrive.
  sampler: '',
  scheduler: '',
  seed: '',
  seed_modus: 'zufall',
  bilder_je_lauf: 1,
  video_frames: '',
  fps: '',
  stapel: [],
  lora_modus: 'at_runtime',
  switches: {},
  /* Not shown in the basics, but set with the model: the family said by
     hand, and what a model change starts the studio at beside the measures,
     so a new model is never drawn with the old one's flow shift or CLIP
     skip. */
  familie: '',
  flow_shift: '',
  model_args: '',
  clip_skip: null,
  prediction: 'auto',
  /* The details on the right: the inputs of the kind (pictures travel by
     the name the service gave them), the face, the face transfer, pose and
     structure, upscaling, the fine tuning and the advanced dials. Unset is
     '' or false, as sd-cli's own value; a number with a start of its own
     carries it. */
  startbild: '',
  /* The picture that last came from outside (a file, the picture folder):
     its tile stands on top of the row of pictures and stays there. */
  original: '',
  maske: '',
  end_bild: '',
  ref_bilder: [],
  staerke: 1,
  img_cfg: '',
  ref_image_args: '',
  increase_ref_index: false,
  pm_klasse: '',
  ad_modell: '',
  ad_stapel: [],
  ad_prompt: '',
  ad_negativ: '',
  ad_confidence: '',
  pulid_weights: '',
  pulid_id_embedding: '',
  pulid_id_weight: 1,
  control_net: '',
  control_image: '',
  control_strength: 0.9,
  canny: false,
  hires_wahl: '',
  hires_steps: '',
  hires_denoise: '',
  hires_upscaler: '',
  // The model "Upscale" enlarges a finished picture with: a file of the upscaler folder.
  upscale_model: '',
  hires_breite: '',
  hires_hoehe: '',
  slg_scale: '',
  skip_layers: '',
  skip_layer_start: 0.01,
  skip_layer_end: 0.2,
  live_preview: '',
  preview_interval: '',
  preview_noisy: false,
  taesd: '',
  eta: '',
  sigmas: '',
  extra_sample_args: '',
  vae_format: 'auto',
  rng: 'cuda',
  weight_type: 'auto',
}

/* What kind of picture is asked for: each kind names the task of the
   family table (app/image_families.py `tasks`) it needs, whether it draws
   a video and whether it starts from pictures of its own (the inputs on
   the right). */
export const KINDS = [
  { value: 'txt2img', task: 'txt2img', text: 'bild.art_txt2img', video: false, input: false },
  { value: 'img2img', task: 'img2img', text: 'bild.art_img2img', video: false, input: true },
  { value: 'edit', task: 'edit', text: 'bild.art_edit', video: false, input: true },
  { value: 't2v', task: 't2v', text: 'bild.art_t2v', video: true, input: false },
  { value: 'i2v', task: 'i2v', text: 'bild.art_i2v', video: true, input: true },
  { value: 'flf2v', task: 'flf2v', text: 'bild.art_flf2v', video: true, input: true },
  { value: 'v2v', task: 'v2v', text: 'bild.art_v2v', video: true, input: true },
]

/* The kinds that draw from the picture in the generation area: as the
   picture to start from, or as the first reference of an edit. */
const FROM_AREA = ['img2img', 'edit', 'i2v', 'flf2v']

/* The kind the next press draws: the one chosen, or the one "auto" picks
   as things stand now (`autoKind`). */
export function art() {
  if (auswahl.art === 'auto') return autoKind()
  return KINDS.find((k) => k.value === auswahl.art) ?? KINDS[0]
}

export const werte = $state(structuredClone(ANFANG))

/* What kind of picture is drawn and which half of the kinds is offered.
   Not stored: the studio opens on the mode that was standing, or, with a
   picture in its area, on one that draws from it (`pictureInArea`).
   `art` is 'auto' or a value of KINDS above, `medium` 'bild' or 'video'.
   `klasse` is the family the service read off the chosen model's header,
   `startKante` the long edge the model starts with (what a format tile
   sets). */
export const auswahl = $state({ art: 'auto', medium: 'bild', klasse: '', startKante: 0 })

/* What the drawing surface tells the studio (StudioCanvas keeps it; false
   while no surface is mounted): `masked` — whether a mask is painted on the
   picture in the generation area — and `maskOn` — the switch "Mask". The
   switch starts off and the person turns it on: off, the mask is not shown
   and goes nowhere, not into a request and not into what "auto" goes by;
   on, it is shown and acts. */
export const surface = $state({ masked: false, maskOn: false })

/* The family the studio draws with: one said by hand, else the header's. */
export function familie() {
  return familyOf(werte.familie || auswahl.klasse)
}

/* Whether a draw of this kind with this family takes a reference video: a
   video of the one family whose models read one (sd-cli `--ref-video`). */
export function takesRefVideo(kind, family) {
  return Boolean(kind.video) && family?.name === 'minimax_h3'
}

/* The kinds of one half the studio's family can draw; every kind of it
   while the family is unknown. A family that says it edits only with a LoRA
   (`edit_needs_lora` of the family table) has its edit among them only
   while a LoRA is chosen in the studio — once the values shown are the
   studio's own (`filledFor`): until then the LoRAs are not read yet, and
   none chosen says nothing. */
export function kindsOf(video) {
  const family = familie()
  const lorasKnown = filledFor.read
  const noEdit = Boolean(family?.edit_needs_lora) && lorasKnown
    && !werte.stapel.some((entry) => entry.name)
  return KINDS.filter((k) => k.video === video && (!family || family.tasks.includes(k.task))
    && !(noEdit && k.value === 'edit'))
}

/* What "auto" draws at the next press, in the chosen half. From the picture
   in the generation area — picture to picture, in the video half picture
   to video — while one lies there, a mask is painted on it or the strength
   stands below 1, and the family can; else from the text. A family that
   cannot draw from the text draws with its first kind from the picture.
   An edit, a first and last frame and a video to video are only ever
   chosen by hand. */
export function autoKind() {
  const video = auswahl.medium === 'video'
  const kinds = kindsOf(video)
  const [fromText, fromPicture] = autoPair(kinds, video)
  const masked = surface.maskOn && (surface.masked || Boolean(werte.maske))
  if (fromPicture && werte.startbild && (masked || Number(werte.staerke) < 1)) return fromPicture
  return fromText ?? kinds.find((k) => FROM_AREA.includes(k.value)) ?? kinds[0]
    ?? KINDS.find((k) => k.video === video)
}

// The two kinds "auto" chooses between, each where the family draws it.
function autoPair(kinds, video) {
  return (video ? ['t2v', 'i2v'] : ['txt2img', 'img2img']).map((value) => kinds.find((k) => k.value === value))
}

/* Whether the strength is what "auto" goes by: a picture lies in the area
   and the family can draw from it as well as from the text. The dial is
   shown then even while "auto" draws from the text — it is the way back. */
export function strengthDecides() {
  if (auswahl.art !== 'auto' || !werte.startbild) return false
  const video = auswahl.medium === 'video'
  return autoPair(kindsOf(video), video).every(Boolean)
}

/* Whether the next press needs a picture that is not there: nothing is
   drawn then. A kind that draws from the picture in the generation area
   needs it there; an edit whose family takes several references draws
   from those of the right column alone as well. */
export function pictureMissing() {
  const kind = art()
  if (!FROM_AREA.includes(kind.value) || werte.startbild) return false
  return !(kind.value === 'edit' && familie()?.many_references && werte.ref_bilder.length)
}

/* The lists the studio's fields offer, read from the service each time the
   studio opens: the model files with their sizes and families, sd-cli's
   samplers and schedulers, and the files of every companion folder — all of
   it in the one answer both columns read. */
export const listen = $state({
  geladen: false, programmDa: true, modelle: [], standardmodell: '', groessen: {}, families: {},
  sampler: [], scheduler: [], loras: [], yolos: [], pulids: [], pulidEmbeddings: [], controlnets: [],
  upscalers: [], upscalerFeste: [], taesd: [], loraOrdner: '', embeddingOrdner: '',
})

let listenAnfrage = null
export function listenLaden() {
  loadImageFamilies()
  loadImageSwitches()
  listenAnfrage ??= api.bildmodelle()
    .then((stand) => {
      Object.assign(listen, {
        programmDa: stand.programm_da, modelle: stand.modelle ?? [],
        standardmodell: stand.standardmodell ?? '', families: stand.families ?? {},
        sampler: stand.sampler ?? [], scheduler: stand.scheduler ?? [], loras: stand.loras ?? [],
        yolos: stand.yolos ?? [], pulids: stand.pulids ?? [], pulidEmbeddings: stand.pulid_embeddings ?? [],
        controlnets: stand.controlnets ?? [], upscalers: stand.upscalers ?? [],
        upscalerFeste: stand.hires_upscaler_feste ?? [], taesd: stand.taesd_files ?? [],
        loraOrdner: stand.lora_ordner ?? '', embeddingOrdner: stand.embedding_ordner ?? '',
        groessen: stand.sizes ?? {},
        geladen: true,
      })
    })
    .catch(() => {
      listen.programmDa = false
    })
    .finally(() => {
      listenAnfrage = null
    })
  return listenAnfrage
}

/* The start values of the chosen model: what the picture server holds for
   it over its family's (GET /bild/vorgaben). Only the newest request
   counts. */
let vorgabenLauf = 0
// The model whose header `auswahl.klasse` was read off.
let headerModel = ''
export async function vorgabenHolen() {
  const lauf = ++vorgabenLauf
  const model = werte.modell
  try {
    const [v] = await Promise.all([api.bildVorgaben(model), loadImageFamilies()])
    if (lauf !== vorgabenLauf || !v || typeof v !== 'object') return null
    auswahl.klasse = v.family || ''
    headerModel = model
    /* A picture that came into the area before this model's family was
       known: its mode is settled with the kinds the family really draws. */
    const due = kindDue
    kindDue = null
    const dueModel = due && (due.model || listen.standardmodell)
    if (due && dueModel === model && werte.startbild) kindOntoPicture()
    return v
  } catch (fehler) {
    if (lauf === vorgabenLauf) melde(String(fehler.message || fehler), 'fehler')
    return null
  }
}

/* A picture's edge as the service keeps it: rounded up onto sd.cpp's grid,
   inside sd.cpp's range (app/bildwahlen.py `kante_pruefen`). The studio
   shows an edge the way it is kept. */
export const EDGE_GRID = 64
export const EDGE_MIN = 64
export const EDGE_MAX = 4096
export const ontoGrid = (edge) =>
  Math.min(EDGE_MAX, Math.max(EDGE_MIN, Math.ceil(edge / EDGE_GRID) * EDGE_GRID))

/* The VAE formats the field offers (StudioDetails.svelte). A start value
   it does not offer is not laid in: the field would stand empty over a
   value that acts. */
const VAE_FORMATS_OFFERED = ['auto', 'flux', 'sd3', 'flux2']

/* What the studio starts at for its model: the family table's start values
   when a family was said by hand, else the answer above — the measures,
   the CFG and what goes with them, the VAE format, the RNG and the switch
   rows a family starts with, and what the model itself sets. */
export const MASSE = ['breite', 'hoehe', 'schritte', 'sampler', 'scheduler']
export function startwerte(v) {
  const start = werte.familie ? familyOf(werte.familie)?.start : null
  const werteDerKlasse = start
    ? { breite: start.width, hoehe: start.height, schritte: start.steps, sampler: start.sampler,
        scheduler: start.scheduler, cfg: start.cfg, guidance: start.guidance,
        flow_shift: start.flow_shift, video_frames: start.frames, fps: start.fps,
        model_args: familyOf(werte.familie)?.model_args,
        vae_format: start.vae_format, rng: start.rng, switches: start.switches }
    : v
  const teil = {}
  // The empty scheduler is a real start value: sd-cli picks its own.
  for (const name of MASSE) if (werteDerKlasse[name] != null) teil[name] = werteDerKlasse[name]
  // A start size off the grid (Wan's 832 × 480) is shown as it is kept.
  for (const name of ['breite', 'hoehe']) {
    if (typeof teil[name] === 'number' && Number.isFinite(teil[name])) teil[name] = ontoGrid(teil[name])
  }
  teil.cfg = werteDerKlasse.cfg
  for (const name of ['guidance', 'flow_shift', 'video_frames', 'fps', 'model_args']) {
    teil[name] = werteDerKlasse[name] ?? ''
  }
  // Without a start of the family's the field's own: never the old model's.
  teil.vae_format = VAE_FORMATS_OFFERED.includes(werteDerKlasse.vae_format)
    ? werteDerKlasse.vae_format : ANFANG.vae_format
  teil.rng = werteDerKlasse.rng || ANFANG.rng
  /* A switch row some family starts with is a start value like the rest: it
     gives way, and the shown family's own are laid in. Every other row
     stays as it was set. */
  const started = new Set(imageFamilies.list.flatMap((family) => Object.keys(family.start?.switches ?? {})))
  teil.switches = {
    ...Object.fromEntries(Object.entries(werte.switches ?? {}).filter(([key]) => !started.has(key))),
    ...werteDerKlasse.switches,
  }
  if (!start) {
    const eigene = v.eigene ?? []
    if (eigene.includes('clip_skip')) teil.clip_skip = v.clip_skip ?? null
    if (eigene.includes('prediction')) teil.prediction = v.prediction || 'auto'
  }
  const lang = Math.max(Number(teil.breite) || 0, Number(teil.hoehe) || 0)
  if (lang) auswahl.startKante = lang
  return teil
}

/* The shown model's start values on their way into the studio's values.
   Whatever fetches them and lays them in — the filling of the studio, a model
   or a family picked, "Standard" — does it inside `layingStartValues` and
   answers whether it laid them in. A draw waits until none of these is
   left (`startValuesThere`): the values the fields start at are not a
   model's, and a picture pressed for meanwhile must not be drawn with
   them.

   Each one that begins puts the values in question; the one that lays
   them in settles it. Which of two that overlap does so is decided by
   whose request is the newer (`vorgabenHolen`), not by which began last —
   the other answers false and changes nothing. Laid until the first one
   begins, so a studio no column has filled yet draws as it stands. */
let startValuesLaid = true
let startValuesDue = Promise.resolve()
export function layingStartValues(work) {
  startValuesLaid = false
  const laying = work()
  const settled = laying.then((laid) => { if (laid) startValuesLaid = true }, () => {})
  startValuesDue = Promise.all([startValuesDue, settled])
  return laying
}

/* Waits until the start values are laid in, also those asked for again
   while it waited; false when they did not arrive. */
export async function startValuesThere() {
  let due
  do {
    due = startValuesDue
    await due
  } while (due !== startValuesDue)
  return startValuesLaid
}

/* A family said by hand (or "automatic") starts the studio at its values,
   the same rule a model change follows. */
export async function familieWaehlen(name) {
  werte.familie = name
  return layingStartValues(async () => {
    const v = await vorgabenHolen()
    if (!v || werte.familie !== name) return false
    Object.assign(werte, startwerte(v))
    return true
  })
}

/* The values the studio last read or wrote, so only a change is written. */
let geschrieben = structuredClone(ANFANG)

/* Whether the values the studio shows were filled from its store: until
   then they are the fields' own starts, not what the studio was left at. */
const filledFor = $state({ read: false, done: false })

/* Whether the values still have to be filled: never yet, or the store was
   read since. */
export const fillDue = () => !filledFor.done || filledFor.read !== studioStore.loaded
// Whether what the values stand at was filled from the read store.
export const filledFromStore = () => filledFor.read

/* Fills the values from the studio's store; returns the measures the store
   has none of its own for — those start at the model's own values.

   A store that arrives after the studio was opened fills only what is
   untouched since: what was typed or set meanwhile stays, is no measure to
   start at the model's value, and is the studio's own from here on —
   written like any value set by hand. */
export function werteFuellen() {
  const stand = studioStore.loaded ? studioStore.value : {}
  const late = studioStore.loaded && !filledFor.read
  const touched = late ? setValues() : {}
  const fehlen = []
  const read = {}
  for (const [name, start] of Object.entries(ANFANG)) {
    const eigen = stand[name] !== undefined
    read[name] = structuredClone($state.snapshot(eigen ? stand[name] : start))
    if (name in touched) continue
    if (!eigen) fehlen.push(name)
    werte[name] = structuredClone(read[name])
  }
  geschrieben = read
  Object.assign(filledFor, { read: studioStore.loaded, done: true })
  /* The family read off a header is that model's: with another model to
     show it is unknown until its own arrives, not the one before. A studio
     without a model of its own shows the picture server's default model. */
  if ((werte.modell || listen.standardmodell) !== headerModel) auswahl.klasse = ''
  /* A start picture chosen before the store arrived outlives it: it stands
     over the stored one and, unlike what was read, is written. */
  if (vorgemerkt) {
    werte.startbild = vorgemerkt.startbild
    werte.maske = ''
    pictureInArea()
    if (studioStore.loaded) vorgemerkt = null
  } else if (werte.startbild) {
    /* The studio opens with a picture in its area: shown, not written —
       opening writes nothing. */
    pictureInArea()
    geschrieben.staerke = werte.staerke
  }
  newestWhereNone()
  /* Written once the store is read: before that nothing can be written, and
     what is set stays set until the store arrives and finds it. */
  if (Object.keys(touched).length && studioStore.loaded) werteSchreiben()
  return fehlen
}

/* A picture stands in the generation area, whichever way it came there: it
   is what the model draws from. One that would be drawn over completely
   starts at the strength where it still shows — a video at sd-cli's own.
   If the kind of the next press does not use the picture after that, the
   mode gives way to the first kind of the same half that does and that
   the model's family can draw; "auto" draws from the picture by now
   wherever the family can and so stays. While the model's family is still
   unknown every kind counts as drawable; the mode is settled again once
   the family arrives (`vorgabenHolen`). */
let kindDue = null
export function pictureInArea() {
  if (Number(werte.staerke) >= 1) werte.staerke = art().video ? 0.75 : 0.6
  kindOntoPicture()
  kindDue = familie() ? null : { model: werte.modell }
}

function kindOntoPicture() {
  const now = art()
  if (!FROM_AREA.includes(now.value)) {
    const next = kindsOf(now.video).find((k) => FROM_AREA.includes(k.value))
    if (next) auswahl.art = next.value
  }
}

/* The start picture is the picture in the generation area. One chosen
   while the studio's store is still on its way is noted, so the store's
   late answer cannot take it back (werteFuellen above). A new picture
   leaves the old picture's mask behind, and sets the kind and the strength
   it is drawn from with (`pictureInArea`) — here, for every way into the
   area. */
let vorgemerkt = null
export function startbildWaehlen(name) {
  // A picture the area showed by itself is the studio's own once it is chosen.
  if (geschrieben.startbild === name) geschrieben.startbild = ''
  emptied = false
  werte.startbild = name
  werte.maske = ''
  pictureInArea()
  vorgemerkt = studioStore.loaded ? null : { startbild: name }
}

/* A picture from outside — a file chosen or dropped, one off the picture
   folder — is the studio's original: it stands in the area like any start
   picture and its tile stays on top of the row, whatever is drawn or
   clicked afterwards, until the next picture from outside takes its place. */
export function pictureFromOutside(name) {
  werte.original = name
  startbildWaehlen(name)
}

/* What the drawing surface hands over when a picture is drawn: the start
   picture and its mask as the generation area holds them (StudioCanvas
   sets `ausgeben`; null while no surface is mounted). `keepView` names a
   picture that came into the area because it was finished: the surface
   leaves zoom and place as they are where it is as large as the picture it
   replaces. */
export const leinwand = { ausgeben: null, keepView: '' }

/* The studio's newest picture stands in its generation area by itself:
   every picture it draws once it is finished — the newest wins, also over a
   picture laid in by hand — and, for a studio that opens with no picture of
   its own there, the newest it has. It is the picture of the area like any
   other, the one the next press draws from if its mode does; but it is
   shown, not written — the store keeps only a picture that was laid in —
   and it changes neither the mode nor the strength.

   Kept for the session: the newest picture last seen, whether a draw was
   asked for since, and whether the area was emptied by hand — it then
   stays empty until the next picture is finished or one is laid in. */
let newestSeen
let drawAskedSince = false
let emptied = false
let areaLook = 0

/* The studio's pictures, newest first, as last read — the one reading of
   that list: the area takes its newest from it, the row of pictures shows
   it. */
export const studioPictures = $state({ names: [] })

// A picture is about to be drawn (studiozeichnen).
export function drawAsked() {
  drawAskedSince = true
}

/* The generation area emptied by hand: no picture and no mask on it, the
   strength back at 1 — and empty it stays until the next picture is
   finished or one is laid in. */
export function emptyArea() {
  werte.startbild = ''
  werte.maske = ''
  werte.staerke = 1
  emptied = true
}

function showInArea(name) {
  werteVorschlagen({ startbild: name, maske: '' })
}

/* For a studio with no picture of its own in the area: the newest it has —
   once the store is read, so a picture of its own comes first. */
function newestWhereNone() {
  if (!studioStore.loaded || werte.startbild || emptied) return
  if (newestSeen) showInArea(newestSeen)
}

/* Reads the studio's pictures, newest first, whenever the studio opens or
   its line of pictures to draw changes. A newer picture than the last one
   seen, after a draw was asked for, is a finished one. Only the newest
   answer counts; a failed read leaves what was read before. */
export async function newestIntoArea() {
  const look = ++areaLook
  let names
  try {
    names = (await api.bilderListe({ studio: true })).bilder ?? []
  } catch {
    return
  }
  if (look !== areaLook) return
  studioPictures.names = names
  const newest = names[0] ?? ''
  const before = newestSeen
  newestSeen = newest
  if (newest && before !== undefined && newest !== before && drawAskedSince) {
    emptied = false
    leinwand.keepView = newest
    showInArea(newest)
  } else {
    newestWhereNone()
  }
  // Nothing left to draw: what comes next is not a finished draw.
  if (!zustand.pictureQueue.length) drawAskedSince = false
}

/* The picture styles (app/bildstile.py): read once, written whole whenever
   one changes. Every style has an id that never changes, and the studio
   keeps its style by it — a new name reaches the style it draws through.
   Styles stored before they had ids get theirs from the service when the
   list is written; that is done here once, so the studio is never handed a
   style without one. */
export const stile = $state({ liste: [], geladen: false })
let stileAnfrage = null
export function stileLaden() {
  stileAnfrage ??= api.einstellungAufgeloest('bildstile')
    .then(async (antwort) => {
      let read = Array.isArray(antwort?.wert) ? antwort.wert : []
      if (read.some((style) => !style.id)) {
        const written = await api.einstellungSetzen('global', 'bildstile', read)
        if (Array.isArray(written?.wert)) read = written.wert
      }
      stile.liste = read
      stile.geladen = true
    })
    .catch(() => {})
    .finally(() => {
      stileAnfrage = null
    })
  return stileAnfrage
}
export function stileSpeichern() {
  // A list that was never read is not written: it would replace the stored one.
  if (!stile.geladen) return Promise.resolve()
  return api.einstellungSetzen('global', 'bildstile', $state.snapshot(stile.liste))
    .catch((fehler) => melde(String(fehler.message || fehler), 'fehler'))
}
/* A new style's id, 32 hex digits. Not `crypto.randomUUID()`: over plain
   HTTP the page is no secure context. */
export const newStyleId = () =>
  [...crypto.getRandomValues(new Uint8Array(16))].map((byte) => byte.toString(16).padStart(2, '0')).join('')
/* The style the studio's choice stands for: the one with that id, else — for a
   choice made before styles had ids — the one called that. A style whose
   name is emptied is on its way out (StudioStyles.svelte) and is none. */
export function stilVon(chosen) {
  if (!chosen) return null
  const named = stile.liste.filter((s) => s.name)
  return named.find((s) => s.id === chosen) ?? named.find((s) => s.name === chosen) ?? null
}

/* The mask painted on the drawing surface: the layer at the start
   picture's own size, the mask the studio had stored for it (`grund`, read
   from the file called `stored`) and the steps painted since, so the studio
   opened again in this session finds its mask as it was left. It leaves
   the surface as a file only when a picture is drawn.

   Only the mask of the picture in the area holds its layers — each as many
   bytes as four times the picture's pixels. A mask for another picture
   gives them back and keeps what they are made of, the stored mask's name
   and the steps; from these the surface paints the layer again (`size`
   tells it the layer that was given back). */
let maske = null
export function studioMask(bild) {
  if (maske && maske.bild === bild) return maske
  if (maske) releaseLayers(maske)
  maske = { bild, flaeche: null, grund: null, stored: '', size: null, verlauf: [], zukunft: [] }
  return maske
}

/* A canvas holds its pixels for as long as it has a size: one of no size
   has given them back at once, not only when the collector finds it. */
export function releaseLayers(mask) {
  if (mask.flaeche) mask.size = [mask.flaeche.width, mask.flaeche.height]
  for (const layer of [mask.flaeche, mask.grund]) {
    if (!layer) continue
    layer.width = 0
    layer.height = 0
  }
  mask.flaeche = null
  mask.grund = null
}

/* Sets values without writing them: what the model starts with, shown for
   a value the studio has none of its own for. */
export function werteVorschlagen(teil) {
  Object.assign(werte, teil)
  Object.assign(geschrieben, structuredClone(teil))
}

/* What was set here: the values that are neither what was read from the
   studio's store nor a start value shown for it, nor written since. */
export function setValues() {
  const set = {}
  for (const [name, value] of Object.entries($state.snapshot(werte))) {
    if (JSON.stringify(value) !== JSON.stringify(geschrieben[name])) set[name] = value
  }
  return set
}

/* Writes what changed since the last read or write into the studio's store. */
export function werteSchreiben() {
  const teil = setValues()
  if (!Object.keys(teil).length) return
  Object.assign(geschrieben, structuredClone(teil))
  writeStudioStore(teil)
}
