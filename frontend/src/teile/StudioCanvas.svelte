<script>
  /* The studio's drawing surface: the whole of the chat tile while the
     studio is open. A grid lies on it; the generation area — the chat's
     width × height — stands fixed in it and never leaves the window. Only
     the picture moves: the wheel zooms it towards the pointer, the hand (or
     a held space bar) drags it. The picture in the area is the start
     picture.

     The mask is painted right on the picture, with the brush and the eraser
     of the mask editor (lib/maske.js), at the picture's own size. It stays
     with the chat for the session (studio.svelte.js `maskeDesChats`) and
     leaves the surface as a file only when a picture is drawn.

     Along the left edge the tools: hand, brush, eraser, invert, clear,
     undo, redo, fit and fill. While brush or eraser is picked, a bar at the
     top carries their size, the tint and the switch that shows the mask. At
     the top right the zoom: a list of percentages, and a step of one
     percentage point to either side of it.

     While no picture stands in the area and none of this chat is drawn or
     waits to be, the house's picture plaque fills it: a click opens the
     file picker, and a picture laid on it — a file, or one off the picture
     wall — is the start picture. */
  import { tick, untrack } from 'svelte'
  import Auswahlfeld from './Auswahlfeld.svelte'
  import Bildablage from './Bildablage.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import MaskenZeichen from './MaskenZeichen.svelte'
  import Schalter from './Schalter.svelte'
  import Schieberegler from './Schieberegler.svelte'
  import StudioPictureMenu from './StudioPictureMenu.svelte'
  import { api } from '../lib/api.js'
  import { draussen } from '../lib/draussen.js'
  import { chatanzeige } from '../lib/chatanzeige.svelte.js'
  import { pictureProgress, watchPicturePreview, watchPictureProgress } from '../lib/pictureProgress.svelte.js'
  import { zeichnung } from '../lib/studiozeichnen.svelte.js'
  import { alsSchwarzWeiss, aufFlaeche, bemalt, leeren, malflaeche, strich, umkehren } from '../lib/maske.js'
  import {
    leinwand, maskeDesChats, newestIntoArea, releaseLayers, startbildWaehlen, studioSichtbar, surface, werte,
  } from '../lib/studio.svelte.js'
  import { t } from '../lib/texte.svelte.js'
  import { melde, zustand } from '../lib/zustand.svelte.js'

  /* Room the area leaves around itself: the tools on the left (and as much
     on the right, so it stands in the middle), the bar and the area's label
     above, the prompt bar below. */
  const RAND_SEITE = 70
  const RAND_OBEN = 110
  const RAND_UNTEN = 274
  // How far the picture zooms, in picture pixels per generated pixel.
  const ZOOM_MIN = 0.05
  const ZOOM_MAX = 8
  const ZOOM_STUFEN = [25, 50, 100, 200, 400]
  // The brush and the tint, as in the mask editor.
  const GROESSEN = Array.from({ length: 119 }, (_, i) => 4 + i * 2)
  const TOENUNGEN = Array.from({ length: 16 }, (_, i) => Math.round((0.15 + i * 0.05) * 100) / 100)
  // What the eye sees of the mask: the painted layer in this colour.
  const TINTE = 'rgba(90, 150, 255, 1)'

  let flaecheKnoten = $state(null)
  let bildKnoten = $state(null)
  let sicht = $state(null)

  // The surface's own size, followed through every resize.
  let fw = $state(0)
  let fh = $state(0)
  $effect(() => {
    if (!flaecheKnoten) return
    const messen = () => {
      fw = flaecheKnoten.clientWidth
      fh = flaecheKnoten.clientHeight
    }
    const beobachter = new ResizeObserver(messen)
    beobachter.observe(flaecheKnoten)
    messen()
    return () => beobachter.disconnect()
  })

  // The generation area: the chat's width × height, fitted into the room.
  const gw = $derived(Math.max(64, Number(werte.breite) || 1024))
  const gh = $derived(Math.max(64, Number(werte.hoehe) || 1024))
  const bereich = $derived.by(() => {
    const s = Math.max(0.01, Math.min((fw - 2 * RAND_SEITE) / gw, (fh - RAND_OBEN - RAND_UNTEN) / gh))
    const w = gw * s
    const h = gh * s
    return { s, w, h, x: (fw - w) / 2, y: RAND_OBEN + Math.max(0, (fh - RAND_OBEN - RAND_UNTEN - h) / 2) }
  })

  /* The picture: where its top left corner lies in the area's own pixels,
     and how large it is shown, in picture pixels per generated pixel. Kept
     in the area's pixels, so a resized window keeps it where it was. */
  const bildUrl = $derived(werte.startbild ? api.bildAdresse(werte.startbild) : '')

  /* "···" at the area's top right: the picture menu for the picture in it,
     there only while one is. A click anywhere else shuts it. */
  let menueOffen = $state(false)
  $effect(() => {
    if (!bildUrl) menueOffen = false
  })
  let natur = $state({ w: 0, h: 0 })
  let lage = $state({ x: 0, y: 0, zoom: 1 })
  const bildStil = $derived(
    `width:${natur.w}px;height:${natur.h}px;transform:translate(${bereich.x + lage.x * bereich.s}px,`
    + `${bereich.y + lage.y * bereich.s}px) scale(${lage.zoom * bereich.s})`,
  )

  /* Fitted, the picture follows the area when its size changes; moved or
     zoomed by hand, it stays where it was put. */
  let eingepasst = true
  const centred = (zoom) => ({ zoom, x: (gw - natur.w * zoom) / 2, y: (gh - natur.h * zoom) / 2 })
  // The whole picture in the middle of the area.
  function einpassen() {
    if (!natur.w) return
    lage = centred(Math.min(gw / natur.w, gh / natur.h))
    eingepasst = true
  }
  // The picture covers the whole area, in its middle: nothing of the area
  // is left without picture.
  function fill() {
    if (!natur.w) return
    lage = centred(Math.max(gw / natur.w, gh / natur.h))
    eingepasst = false
  }
  $effect(() => {
    void gw
    void gh
    untrack(() => {
      if (eingepasst) einpassen()
    })
  })

  /* Zoom about a point of the surface, keeping the picture point under it
     where it is. */
  function zoomen(neu, mx, my) {
    const zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, neu))
    const gx = (mx - bereich.x) / bereich.s
    const gy = (my - bereich.y) / bereich.s
    const px = (gx - lage.x) / lage.zoom
    const py = (gy - lage.y) / lage.zoom
    lage = { zoom, x: gx - px * zoom, y: gy - py * zoom }
    eingepasst = false
  }

  const zoomProzent = $derived(Math.round(lage.zoom * 100))
  /* The zoom list: percentages only — the steps and where the zoom stands
     now. "Fit" and "fill" are things to do, not places to stand at; they
     are buttons of the tool rail. */
  const zoomEintraege = $derived(
    [...new Set([...ZOOM_STUFEN, zoomProzent])].sort((a, b) => a - b)
      .map((p) => ({ wert: p, text: `${p} %` })),
  )
  // A zoom by the list or by its two steps is about the area's middle.
  const zoomAboutCentre = (zoom) => zoomen(zoom, bereich.x + bereich.w / 2, bereich.y + bereich.h / 2)
  // One percentage point in or out.
  const zoomStep = (points) => zoomAboutCentre(lage.zoom + points / 100)

  // --- The mask ---------------------------------------------------------

  let maske = $state.raw(null)
  // Counts each change of the mask, so what reads it follows.
  let stand = $state(0)
  const kannZurueck = $derived(stand >= 0 && Boolean(maske?.verlauf.length))
  const kannVor = $derived(stand >= 0 && Boolean(maske?.zukunft.length))
  let werkzeug = $state('pinsel')
  let groesse = $state(48)
  let toenung = $state(0.5)
  let maskeSichtbar = $state(true)
  const malt = $derived(werkzeug === 'pinsel' || werkzeug === 'radierer')
  // Read back once per change of the mask, not per drawing of the tools.
  const etwasGemalt = $derived(stand >= 0 && maske?.flaeche ? bemalt(maske.flaeche) : false)
  // Told to the studio: a painted mask is one of the things "auto" goes by.
  $effect(() => {
    surface.masked = etwasGemalt
    return () => {
      surface.masked = false
    }
  })

  function zeichnenAufSicht() {
    if (!sicht || !maske?.flaeche) return
    const f = maske.flaeche
    if (sicht.width !== f.width) sicht.width = f.width
    if (sicht.height !== f.height) sicht.height = f.height
    const stift = sicht.getContext('2d')
    stift.clearRect(0, 0, sicht.width, sicht.height)
    stift.drawImage(f, 0, 0)
    stift.save()
    stift.globalCompositeOperation = 'source-in'
    stift.fillStyle = TINTE
    stift.fillRect(0, 0, sicht.width, sicht.height)
    stift.restore()
  }

  function anwenden(schritt) {
    const f = maske.flaeche
    if (schritt.art === 'strich') {
      const p = schritt.punkte
      strich(f, p[0], p[0], schritt.groesse, schritt.radiert)
      for (let i = 1; i < p.length; i += 1) strich(f, p[i - 1], p[i], schritt.groesse, schritt.radiert)
    } else if (schritt.art === 'umkehren') {
      umkehren(f)
    } else if (schritt.art === 'leeren') {
      leeren(f)
    }
  }

  // A changed mask is no longer the one the chat has stored.
  function geaendert() {
    werte.maske = ''
    stand += 1
    zeichnenAufSicht()
  }

  function merken(schritt) {
    maske.verlauf.push(schritt)
    maske.zukunft = []
    geaendert()
  }

  // From the mask the chat had stored (if any), every step again.
  function paintLayer() {
    leeren(maske.flaeche)
    if (maske.grund) maske.flaeche.getContext('2d').drawImage(maske.grund, 0, 0)
    for (const schritt of maske.verlauf) anwenden(schritt)
  }

  function neuZeichnen() {
    if (!maske?.flaeche) return
    paintLayer()
    geaendert()
  }

  function ganzeMaske(art) {
    if (!maske?.flaeche) return
    const schritt = { art }
    anwenden(schritt)
    merken(schritt)
  }

  function zurueck() {
    if (!kannZurueck) return
    maske.zukunft.push(maske.verlauf.pop())
    neuZeichnen()
  }

  function vor() {
    if (!kannVor) return
    maske.verlauf.push(maske.zukunft.pop())
    neuZeichnen()
  }

  /* A mask the chat has stored is black and white; on the surface white is
     painted and black is free, so its brightness becomes the cover of the
     layer under the steps. What was painted while it loaded stays on top. */
  function gespeicherteLaden(f, name) {
    const bild = new Image()
    bild.onload = () => {
      if (maske?.flaeche !== f) return
      const base = malflaeche(f.width, f.height)
      const stift = base.getContext('2d')
      stift.drawImage(bild, 0, 0, f.width, f.height)
      const daten = stift.getImageData(0, 0, f.width, f.height)
      const p = daten.data
      for (let i = 0; i < p.length; i += 4) {
        const hell = Math.round((p[i] + p[i + 1] + p[i + 2]) / 3)
        p[i] = 255
        p[i + 1] = 255
        p[i + 2] = 255
        p[i + 3] = hell
      }
      stift.putImageData(daten, 0, 0)
      maske.grund = base
      paintLayer()
      if (laufenderStrich) anwenden(laufenderStrich)
      stand += 1
      zeichnenAufSicht()
    }
    bild.src = api.bildAdresse(name)
  }

  /* The picture loaded: a picture new to the area is fitted into it, and
     the chat's mask for it comes forward — the one painted this session,
     else the one the chat has stored, else an empty layer at the picture's
     size. A picture that only loads again stands where it was put: the
     area is emptied and refilled when a chat's stored values arrive, as
     they do for the chat a first draw opens. A finished picture that takes
     the place of one of its own size stands where that one stood, at its
     zoom: what was worked on stays in view. */
  let fittedPicture = null
  /* An area that stands empty has no fitted picture any more: whatever
     comes into it next is new to it. While a chat's stored values are on
     their way the area is only between two fillings and nothing is
     forgotten — asked once every effect of that moment has run, so a
     filling in the same breath counts whichever of the two runs first. A
     read that failed brings no filling: the area stands empty like any
     other. */
  $effect(() => {
    if (bildUrl) return
    if (chatanzeige.chatId && !chatanzeige.geladen && !chatanzeige.readError) return
    tick().then(() => {
      if (!bildUrl) fittedPicture = null
    })
  })
  function bildGeladen(ereignis) {
    const knoten = ereignis.currentTarget
    const replaced = natur
    natur = { w: knoten.naturalWidth, h: knoten.naturalHeight }
    // Told by what was loaded, not by what the chat names by now.
    const loaded = knoten.getAttribute('src')
    if (fittedPicture !== loaded) {
      const finished = Boolean(leinwand.keepView) && loaded === api.bildAdresse(leinwand.keepView)
      if (finished) leinwand.keepView = ''
      if (!(finished && replaced.w === natur.w && replaced.h === natur.h)) einpassen()
      fittedPicture = loaded
    }
    maskeHolen()
  }

  /* A layer the mask gave back while its chat was closed is painted again
     from what it is made of — the stored mask it was read from and the
     steps since. Any other layer that is missing or of another size than
     the picture starts from the mask the chat has stored now. */
  function maskeHolen() {
    maske = maskeDesChats(chatanzeige.chatId, werte.startbild)
    const fits = (w, h) => w === natur.w && h === natur.h
    if (!maske.flaeche || !fits(maske.flaeche.width, maske.flaeche.height)) {
      const givenBack = !maske.flaeche && Boolean(maske.size) && fits(...maske.size)
      if (maske.flaeche) releaseLayers(maske)
      if (!givenBack) Object.assign(maske, { stored: werte.maske, verlauf: [], zukunft: [] })
      maske.flaeche = malflaeche(natur.w, natur.h)
      if (givenBack) paintLayer()
      if (maske.stored) gespeicherteLaden(maske.flaeche, maske.stored)
    }
    stand += 1
    zeichnenAufSicht()
  }

  /* Another chat with the very same picture loads nothing new: its own mask
     is fetched all the same. A view to keep was the chat's before. */
  $effect(() => {
    void chatanzeige.chatId
    leinwand.keepView = ''
    untrack(() => {
      if (natur.w && bildUrl) maskeHolen()
    })
  })

  $effect(() => {
    if (!bildUrl) {
      maske = null
      natur = { w: 0, h: 0 }
    }
  })

  // --- Handing over -----------------------------------------------------

  /* What is drawn from is what the area holds. A picture fitted whole into
     an area of its own shape goes as it is; any other is laid onto the
     area's own size first, black where it does not reach, and its mask
     with it. Where a picture is drawn from a part of the picture, the
     part's place in it goes along (`placeInPicture`), and picture and mask
     are cut at exactly that place, whole pixels of the picture: what is
     drawn is then set back where it was cut, with nothing in between.
     Null while the surface has not loaded this picture. */
  function aufDenBereich(quelle, place = null) {
    const ziel = document.createElement('canvas')
    ziel.width = gw
    ziel.height = gh
    const stift = ziel.getContext('2d')
    stift.fillStyle = '#000'
    stift.fillRect(0, 0, gw, gh)
    if (place) stift.drawImage(quelle, ...place, 0, 0, gw, gh)
    else stift.drawImage(quelle, lage.x, lage.y, natur.w * lage.zoom, natur.h * lage.zoom)
    return ziel
  }

  /* Where the area lies in the picture, as x, y, width and height in the
     picture's own pixels — while the area shows only a part of the picture
     and lies wholly inside it; else null. What is drawn from such a part
     can be set back into the whole picture at this place. Inside is told
     on the area's own pixels: the picture reaches every edge of the area
     to within half a pixel of it, so no pixel of what is drawn from is
     without picture. The place is the area's edges in the picture, rounded
     to whole pixels and never beyond the picture. */
  const HALF_PIXEL = 0.5
  function placeInPicture() {
    const inside = lage.x <= HALF_PIXEL && lage.y <= HALF_PIXEL
      && lage.x + natur.w * lage.zoom >= gw - HALF_PIXEL
      && lage.y + natur.h * lage.zoom >= gh - HALF_PIXEL
    if (!inside) return null
    const left = Math.max(0, Math.round(-lage.x / lage.zoom))
    const top = Math.max(0, Math.round(-lage.y / lage.zoom))
    const right = Math.min(natur.w, Math.round((gw - lage.x) / lage.zoom))
    const bottom = Math.min(natur.h, Math.round((gh - lage.y) / lage.zoom))
    const part = right - left < natur.w || bottom - top < natur.h
    return part && right > left && bottom > top ? [left, top, right - left, bottom - top] : null
  }

  /* What the area puts together is a working picture: made for the draw,
     never one of the picture folder. */
  async function hochladen(knoten, name) {
    const blob = await new Promise((fertig) => knoten.toBlob(fertig, 'image/png'))
    if (!blob) throw new Error('picture could not be encoded')
    return (await api.bildHochladen(new File([blob], name, { type: 'image/png' }), true)).bild
  }

  /* The last hand-over, kept while nothing it was made of changed: drawing
     again takes the same files instead of laying them down anew. */
  let zuletzt = null
  async function ausgeben(name, mitMaske) {
    if (!bildKnoten || !natur.w || name !== werte.startbild) return null
    const schluessel = JSON.stringify([name, mitMaske, lage, gw, gh, natur, chatanzeige.chatId, stand])
    if (zuletzt?.schluessel === schluessel) return zuletzt.ergebnis
    const ergebnis = await ausgebenNeu(name, mitMaske)
    zuletzt = { schluessel, ergebnis }
    return ergebnis
  }

  async function ausgebenNeu(name, mitMaske) {
    const wieEs = eingepasst && Math.abs(natur.w * gh - natur.h * gw) < natur.w
    // Only a picture drawn from the picture — the one that takes a mask —
    // is set back into it.
    const place = wieEs || !mitMaske ? null : placeInPicture()
    /* Picture and mask are both cut before either is laid down: the view
       may move while a file is on its way, and the two must show the same
       place. */
    const cut = wieEs ? null : aufDenBereich(bildKnoten, place)
    let cutMask = null
    if (mitMaske && maske?.flaeche && bemalt(maske.flaeche)) {
      const schwarzWeiss = alsSchwarzWeiss(maske.flaeche)
      cutMask = wieEs ? schwarzWeiss : aufDenBereich(schwarzWeiss, place)
    }
    const startbild = cut ? await hochladen(cut, 'startbild.png') : name
    const maskenName = cutMask ? await hochladen(cutMask, 'maske.png') : null
    return { startbild, maske: maskenName, place }
  }

  $effect(() => {
    leinwand.ausgeben = ausgeben
    return () => {
      if (leinwand.ausgeben === ausgeben) leinwand.ausgeben = null
    }
  })

  // --- Pointer ----------------------------------------------------------

  let raumTaste = $state(false)
  let schiebt = $state(false)
  const schiebend = $derived(werkzeug === 'hand' || raumTaste)
  let laufenderStrich = null
  let zeiger = $state(null)

  /* A pointer position on the surface in the layout pixels its children are
     placed in: an ancestor zoom makes measured pixels differ from those. */
  function aufDerFlaeche(ereignis) {
    const kasten = flaecheKnoten.getBoundingClientRect()
    const faktor = flaecheKnoten.offsetWidth ? kasten.width / flaecheKnoten.offsetWidth : 1
    return { x: (ereignis.clientX - kasten.left) / faktor, y: (ereignis.clientY - kasten.top) / faktor }
  }

  /* The wheel over the surface is the picture's alone — a pinch arrives
     as a wheel with Ctrl held. Without a picture nothing moves, and the
     page must not scroll or zoom in its place: the area never changes size
     or place. What floats over the surface is kept from zooming the page
     by the studio itself (ImageStudio.svelte). */
  function radeln(ereignis) {
    ereignis.preventDefault()
    if (!natur.w) return
    const { x, y } = aufDerFlaeche(ereignis)
    zoomen(lage.zoom * Math.exp(-ereignis.deltaY * 0.0016), x, y)
  }

  function fassen(ereignis) {
    if (!natur.w || ereignis.button !== 0) return
    ereignis.currentTarget.setPointerCapture(ereignis.pointerId)
    if (schiebend) {
      schiebt = true
      return
    }
    if (!malt || !maske?.flaeche) return
    const punkt = aufFlaeche(ereignis, bildKnoten, maske.flaeche)
    const radiert = werkzeug === 'radierer'
    laufenderStrich = { art: 'strich', punkte: [punkt], groesse, radiert }
    strich(maske.flaeche, punkt, punkt, groesse, radiert)
    zeichnenAufSicht()
  }

  function ziehen(ereignis) {
    zeiger = aufDerFlaeche(ereignis)
    if (!ereignis.currentTarget.hasPointerCapture?.(ereignis.pointerId)) return
    if (schiebt) {
      const kasten = flaecheKnoten.getBoundingClientRect()
      const faktor = flaecheKnoten.offsetWidth ? kasten.width / flaecheKnoten.offsetWidth : 1
      lage = {
        ...lage,
        x: lage.x + ereignis.movementX / faktor / bereich.s,
        y: lage.y + ereignis.movementY / faktor / bereich.s,
      }
      eingepasst = false
      return
    }
    if (!laufenderStrich || !maske?.flaeche) return
    const jetzt = aufFlaeche(ereignis, bildKnoten, maske.flaeche)
    const punkte = laufenderStrich.punkte
    strich(maske.flaeche, punkte[punkte.length - 1], jetzt, groesse, laufenderStrich.radiert)
    punkte.push(jetzt)
    zeichnenAufSicht()
  }

  // One step is one stroke, pointer down to pointer up.
  function loslassen(ereignis) {
    if (ereignis.currentTarget.hasPointerCapture?.(ereignis.pointerId)) {
      ereignis.currentTarget.releasePointerCapture(ereignis.pointerId)
    }
    schiebt = false
    if (laufenderStrich) {
      merken(laufenderStrich)
      laufenderStrich = null
    }
  }

  /* Space lends the hand while held; Cmd/Ctrl+Z steps back, with Shift
     forward. Never while something is typed, and only while the studio
     shows. */
  function tasteRunter(ereignis) {
    if (!studioSichtbar()) return
    const ziel = ereignis.target
    // Typing, or a focused control that Space would press, keeps its keys.
    const tippt = ziel instanceof HTMLElement
      && (['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(ziel.tagName) || ziel.isContentEditable)
    if (tippt) return
    if (ereignis.code === 'Space') {
      ereignis.preventDefault()
      raumTaste = true
    } else if ((ereignis.metaKey || ereignis.ctrlKey) && ereignis.key.toLowerCase() === 'z') {
      ereignis.preventDefault()
      if (ereignis.shiftKey) vor()
      else zurueck()
    }
  }
  function tasteHoch(ereignis) {
    if (ereignis.code === 'Space') raumTaste = false
  }

  // --- A picture laid on the surface ----------------------------------

  let ablegen = $state(false)
  let ablageWahl = 0
  /* A picture file for the area: uploaded, then the start picture — unless
     another one was laid down or another chat opened meanwhile. */
  async function setFile(datei) {
    if (!datei?.type?.startsWith('image/')) return
    const fuer = chatanzeige.chatId
    const wahl = ++ablageWahl
    try {
      const ergebnis = await api.bildHochladen(datei)
      if (fuer === chatanzeige.chatId && wahl === ablageWahl) startbildWaehlen(ergebnis.bild)
    } catch (fehler) {
      if (fuer === chatanzeige.chatId) melde(String(fehler.message || fehler), 'fehler')
    }
  }
  /* A picture off the picture wall (ModulBilder) travels by its name: it
     lies in the pictures folder already, so it is the start picture as it
     is, without a second upload. The payload is text any drag source could
     write; only a name of the folder's own shape is taken. */
  const WALL_PICTURE = 'application/x-exe-bild'
  const FOLDER_NAME = /^[0-9a-f]{32}\.(?:png|jpg|webp)$/
  function setFromFolder(name) {
    if (!FOLDER_NAME.test(name)) return
    ablageWahl += 1
    startbildWaehlen(name)
  }
  function abgelegt(ereignis) {
    ereignis.preventDefault()
    const name = ereignis.dataTransfer?.getData(WALL_PICTURE)
    if (name) setFromFolder(name)
    else setFile([...(ereignis.dataTransfer?.files ?? [])].find((d) => d.type.startsWith('image/')))
  }

  /* The picture of this chat drawing now: its progress stands in the
     area too, with its stop — and, where it is drawn with a live preview,
     the picture as far as it is, laid over the area. The watch follows the
     picture, not the line: a line rebuilt around the same picture must not
     end it and start it over. */
  const laufend = $derived(zustand.pictureQueue.find((w) => w.running && w.chat_id === chatanzeige.chatId) ?? null)
  const prozent = $derived(Math.round((pictureProgress.share || 0) * 100))
  const runningId = $derived(laufend?.id ?? null)
  /* A picture of this chat drawing or waiting in the line: the empty area
     belongs to the progress, not to the picture plaque. Waiting counts too
     — between two pictures of one run the first is drawn and the next has
     not begun, and the plaque would show up for that moment. */
  const inLine = $derived(zustand.pictureQueue.some((w) => w.chat_id === chatanzeige.chatId))
  $effect(() => {
    if (runningId === null) return
    const stopProgress = watchPictureProgress()
    const stopPreview = watchPicturePreview(runningId)
    return () => {
      stopPreview()
      stopProgress()
    }
  })
  /* The chat's newest picture comes into the area by itself
     (lib/studio.svelte.js): its pictures are read when the chat opens,
     whenever its line of pictures changes — a picture that left the line
     is finished — and when a message arrives, which may bring one. */
  const line = $derived(
    zustand.pictureQueue.filter((w) => w.chat_id === chatanzeige.chatId).map((w) => w.id).join(),
  )
  $effect(() => {
    void chatanzeige.chatId
    void line
    void zustand.nachrichten.length
    untrack(newestIntoArea)
  })

  const WERKZEUGE = [
    { name: 'hand', zeichen: 'hand', text: 'maske.verschieben' },
    { name: 'pinsel', zeichen: 'pinsel', text: 'maske.pinsel' },
    { name: 'radierer', zeichen: 'radierer', text: 'maske.radierer' },
  ]
</script>

<svelte:window onkeydown={tasteRunter} onkeyup={tasteHoch} />

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div class="flaeche" class:ablegen role="region" aria-label={t('studio.zeichenflaeche')}
     bind:this={flaecheKnoten}
     ondragover={(e) => { e.preventDefault(); ablegen = true }}
     ondragleave={() => (ablegen = false)} ondropcapture={() => (ablegen = false)} ondrop={abgelegt}>
  <!-- The picture and its mask, moved and zoomed as one box; clipped to the
       surface, veiled outside the area. -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="buehne" class:hand={schiebend} class:greift={schiebt} class:malt={malt && !schiebend && natur.w}
       onwheel={radeln} onpointerdown={fassen} onpointermove={ziehen} onpointerup={loslassen}
       onpointercancel={loslassen} onpointerleave={() => (zeiger = null)}>
    {#if bildUrl}
      <div class="bild" style={bildStil}>
        <img src={bildUrl} alt={t('bild.startbild')} bind:this={bildKnoten} onload={bildGeladen} draggable="false" />
        <canvas bind:this={sicht} class="maske" style:opacity={maskeSichtbar ? toenung : 0}></canvas>
      </div>
    {/if}
    <div class="bereich" class:leer={!bildUrl} aria-hidden="true"
         style="left:{bereich.x}px;top:{bereich.y}px;width:{bereich.w}px;height:{bereich.h}px"></div>
    {#if !bildUrl && !inLine}
      <!-- No picture in the area and none of this chat in the line: the
           picture plaque fills it. While one is drawn its progress stands
           there instead. -->
      <div class="plaque" style="left:{bereich.x}px;top:{bereich.y}px;width:{bereich.w}px;height:{bereich.h}px">
        <Bildablage waehlen={setFile} named={setFromFolder} fill />
      </div>
    {/if}
    {#if zeiger && malt && !schiebend && natur.w}
      {@const d = groesse * lage.zoom * bereich.s}
      <div class="pinselring" aria-hidden="true"
           style="left:{zeiger.x}px;top:{zeiger.y}px;width:{d}px;height:{d}px"></div>
    {/if}
  </div>

  {#if laufend}
    <div class="fortschritt" style="left:{bereich.x}px;top:{bereich.y}px;width:{bereich.w}px;height:{bereich.h}px">
      <!-- The live preview lies over the start picture, not in its place:
           picture, mask and view stay as they are underneath. -->
      {#if pictureProgress.previewUrl}<img class="preview" src={pictureProgress.previewUrl} alt="" />{/if}
      <span class="pille">
        {prozent} %
        <span aria-hidden="true">·</span>
        <button onclick={() => zeichnung.stopEins?.(laufend.id)}>{t('bild.stopp')}</button>
      </span>
      <span class="balken" style:width="{prozent}%"></span>
    </div>
  {/if}

  <div class="bereichsname" style="left:{bereich.x}px;top:{bereich.y - 36}px">
    <Hauszeichen zeichen="raster" groesse={14} />
    <span>{t('studio.generierungsbereich')} · {gw} × {gh}</span>
  </div>

  {#if bildUrl}
    <div class="bereichsmenue" style="left:{bereich.x + bereich.w}px;top:{bereich.y - 36}px" use:draussen={() => (menueOffen = false)}>
      <button class="mehr" aria-label="···" aria-haspopup="menu" aria-expanded={menueOffen}
              onclick={() => (menueOffen = !menueOffen)}>···</button>
      {#if menueOffen}
        <div class="menueplatz">
          <StudioPictureMenu name={werte.startbild} zu={() => (menueOffen = false)} imBereich />
        </div>
      {/if}
    </div>
  {/if}

  <div class="werkzeuge glas" role="toolbar" aria-orientation="vertical" aria-label={t('studio.zeichenflaeche')}
       style="top:{bereich.y}px">
    {#each WERKZEUGE as w (w.name)}
      <button class:an={werkzeug === w.name} aria-pressed={werkzeug === w.name} onclick={() => (werkzeug = w.name)}
              title={t(w.text)} aria-label={t(w.text)}>
        <MaskenZeichen name={w.zeichen} groesse={18} />
      </button>
    {/each}
    <button onclick={() => ganzeMaske('umkehren')} disabled={!natur.w} title={t('maske.umkehren')}
            aria-label={t('maske.umkehren')}>
      <MaskenZeichen name="umkehren" groesse={18} />
    </button>
    <button onclick={() => ganzeMaske('leeren')} disabled={!natur.w || !etwasGemalt}
            title={t('maske.leeren')} aria-label={t('maske.leeren')}>
      <!-- The catalogue's "mask clear": the frame with the dashed mask
           inside, as the drawing has it. -->
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"
           stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <rect x="3.6" y="3.6" width="16.8" height="16.8" rx="4" />
        <rect x="6.6" y="6.6" width="10.8" height="10.8" rx="2" stroke-dasharray="2.7 2.7" />
      </svg>
    </button>
    <button onclick={zurueck} disabled={!kannZurueck} title={t('maske.zurueck')} aria-label={t('maske.zurueck')}>
      <MaskenZeichen name="zurueck" groesse={18} />
    </button>
    <button onclick={vor} disabled={!kannVor} title={t('maske.vor')} aria-label={t('maske.vor')}>
      <MaskenZeichen name="vor" groesse={18} />
    </button>
    <!-- The view of the picture, last in the rail: the whole picture in
         the area, and under it the picture over the whole area. Both rest
         while there is no picture. -->
    <button onclick={einpassen} disabled={!natur.w} title={t('maske.ansicht')} aria-label={t('maske.ansicht')}>
      <MaskenZeichen name="ganzzeigen" groesse={18} />
    </button>
    <button onclick={fill} disabled={!natur.w} title={t('maske.fuellen')} aria-label={t('maske.fuellen')}>
      <MaskenZeichen name="fuellen" groesse={18} />
    </button>
  </div>

  {#if malt}
    <div class="oben">
    <div class="pinselleiste glas">
      <span class="teil">
        <MaskenZeichen name={werkzeug} groesse={14} />
        <span class="name">{t(werkzeug === 'pinsel' ? 'maske.pinsel' : 'maske.radierer')}</span>
        <span class="regler"><Schieberegler bind:wert={groesse} stufen={GROESSEN} mit_zahl={false} fuellung
                                             beschriftung={t('maske.groesse')} /></span>
        <span class="zahl">{groesse}</span>
      </span>
      <span class="trenner" aria-hidden="true"></span>
      <span class="teil">
        <span class="name">{t('maske.toenung')}</span>
        <span class="regler"><Schieberegler bind:wert={toenung} stufen={TOENUNGEN} mit_zahl={false} fuellung
                                             beschriftung={t('maske.toenung')} /></span>
        <span class="zahl">{toenung.toLocaleString(undefined, { minimumFractionDigits: 1 })}</span>
      </span>
      <span class="trenner" aria-hidden="true"></span>
      <span class="teil">
        <span class="name">{t('studio.maske')}</span>
        <Schalter an={maskeSichtbar} onschalten={(an) => (maskeSichtbar = an)} beschriftung={t('studio.maske')} />
      </span>
    </div>
    </div>
  {/if}

  <div class="zoom">
    <button class="step glas" onclick={() => zoomStep(-1)} disabled={!natur.w}
            title={t('shortcuts.zoom_out')} aria-label={t('shortcuts.zoom_out')}>−</button>
    <div class="level">
      <!-- The field shows the zoom in percent and nothing else: read from
           where the picture stands, a pick sets the zoom. -->
      <Auswahlfeld bind:wert={() => zoomProzent, (percent) => zoomAboutCentre(percent / 100)}
                   eintraege={zoomEintraege} gesperrt={!natur.w} beschriftung={t('maske.ansicht')} />
    </div>
    <button class="step glas" onclick={() => zoomStep(1)} disabled={!natur.w}
            title={t('shortcuts.zoom_in')} aria-label={t('shortcuts.zoom_in')}>+</button>
  </div>
</div>

<style>
  .flaeche {
    flex: 1;
    min-height: 0;
    position: relative;
    overflow: hidden;
    /* The zoom field, wide enough that a percentage of four digits is read
       whole: a small picture that fills a large area stands at one. */
    --zoom-field: 94px;
    /* The grid the area stands on. */
    --raster: color-mix(in srgb, var(--text) 9%, transparent);
    background-image:
      linear-gradient(var(--raster) 1px, transparent 1px),
      linear-gradient(90deg, var(--raster) 1px, transparent 1px);
    background-size: 28px 28px;
    background-position: -1px -1px;
  }
  .flaeche.ablegen {
    box-shadow: inset 0 0 0 2px var(--blau);
  }
  .buehne {
    position: absolute;
    inset: 0;
    overflow: hidden;
    touch-action: none;
  }
  .buehne.malt {
    cursor: none;
  }
  .buehne.hand {
    cursor: grab;
  }
  .buehne.greift {
    cursor: grabbing;
  }
  .bild {
    position: absolute;
    left: 0;
    top: 0;
    transform-origin: 0 0;
  }
  .bild img,
  .bild canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    user-select: none;
    -webkit-user-drag: none;
  }
  .bild canvas {
    pointer-events: none;
  }
  /* The area: its edge always, and outside it the picture veiled. */
  .bereich {
    position: absolute;
    pointer-events: none;
    box-shadow:
      0 0 0 1px var(--glass-card-line),
      0 0 0 100vmax color-mix(in srgb, var(--bg) 55%, transparent);
  }
  .bereich.leer {
    background: var(--glass-card);
    box-shadow: 0 0 0 1px var(--glass-card-line);
  }
  .plaque {
    position: absolute;
  }
  .pinselring {
    position: absolute;
    transform: translate(-50%, -50%);
    border-radius: 50%;
    border: 1px dashed #fff;
    box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.45);
    pointer-events: none;
  }
  .glas {
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    border-radius: 9px;
    backdrop-filter: blur(14px);
  }
  .fortschritt {
    position: absolute;
    display: grid;
    place-items: center;
    pointer-events: none;
    background: color-mix(in srgb, var(--bg) 35%, transparent);
  }
  .fortschritt .preview {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
  .fortschritt .pille {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 26px;
    padding: 0 10px;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: 400 13px/18px var(--schrift);
    pointer-events: auto;
  }
  .fortschritt button {
    padding: 0;
    border: none;
    background: none;
    color: inherit;
    font: inherit;
    cursor: pointer;
  }
  .fortschritt .balken {
    position: absolute;
    left: 0;
    bottom: 0;
    height: 3px;
    background: var(--blau);
  }
  .bereichsname {
    position: absolute;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    height: 26px;
    padding: 0 10px;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: 400 13px/18px var(--schrift);
    pointer-events: none;
    white-space: nowrap;
  }
  .bereichsmenue {
    position: absolute;
    z-index: 5;
    transform: translateX(-100%);
  }
  .mehr {
    height: 26px;
    padding: 0 10px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: 600 13px/26px var(--schrift);
    cursor: pointer;
  }
  .mehr:hover {
    background: var(--glass-hover);
  }
  .menueplatz {
    position: absolute;
    top: calc(100% + 6px);
    right: 0;
  }
  .werkzeuge {
    position: absolute;
    left: 14px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 4px;
  }
  .werkzeuge button {
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    cursor: pointer;
  }
  .werkzeuge button:hover:not(:disabled) {
    background: var(--glass-hover);
    color: var(--text);
  }
  .werkzeuge button.an {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  .werkzeuge button:disabled {
    opacity: 0.35;
    cursor: default;
  }
  /* Between the tools and the zoom, centred where there is room. */
  .oben {
    position: absolute;
    top: 12px;
    left: 64px;
    /* The zoom at the right: its two steps, the gaps, its edge distance and
       a gap to this bar — and the field between the steps. */
    right: calc(100px + var(--zoom-field));
    display: flex;
    justify-content: center;
    pointer-events: none;
  }
  .pinselleiste {
    min-width: 0;
    pointer-events: auto;
    display: flex;
    align-items: center;
    gap: 10px;
    height: 32px;
    padding: 0 12px;
    color: var(--text);
    font: 400 13px/18px var(--schrift);
    white-space: nowrap;
  }
  .teil {
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }
  .regler {
    width: 120px;
    min-width: 48px;
    flex: 0 1 auto;
    display: block;
  }
  .regler > :global(*) {
    width: 100%;
  }
  .zahl {
    min-width: 24px;
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
  .trenner {
    width: 1px;
    height: 16px;
    background: var(--glass-card-line);
  }
  .zoom {
    position: absolute;
    top: 12px;
    right: 14px;
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .zoom .level {
    width: var(--zoom-field);
  }
  /* The two steps beside the zoom: one size, the field's own height. */
  .zoom .step {
    width: 32px;
    height: 32px;
    padding: 0;
    border: none;
    color: var(--text);
    font: 400 16px/32px var(--schrift);
    cursor: pointer;
  }
  .zoom .step:hover:not(:disabled) {
    background: var(--glass-hover);
  }
  .zoom .step:disabled {
    opacity: 0.35;
    cursor: default;
  }
</style>
