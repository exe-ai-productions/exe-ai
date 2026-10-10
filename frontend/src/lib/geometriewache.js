/* DIAGNOSIS — the geometry watch.

   Watches the chat's scroll box for three things nobody can see happen
   and everybody notices afterwards, and keeps the moment on three ways so
   none of them gets lost:

     1. localStorage — survives a reload; `geometrieBericht()` prints it
     2. a small window in the app — visible without a console, which the
        program window has none of
     3. a request to the service — lands in the access log with the facts
        in its path, readable from another machine

   What it watches:

   THROW-BACK. The view jumps UP without the reader turning the wheel up.
   Nothing in this program scrolls up on purpose — `runter()` and
   `runterGleiten()` only ever set scrollTop to scrollHeight — so a jump up
   has one of two causes, and the watch tells them apart by holding
   scrollTop AND scrollHeight in the same moment: the total height shrank
   under the reader (content torn out or collapsed while text arrives), or
   the height stayed and the browser moved the position itself (scroll
   anchoring, or somebody set it).

   HOP. The same thing under the threshold of a throw-back: a few pixels,
   the kind the composer shrinking after a send produces. Recorded, not
   shown, so a report can say what happened right before following broke.

   FOLLOWING LOST. An answer is being written (a waiting mark stands) and
   the view sits more than a band above the floor for half a second
   without the reader having scrolled up. That is the "the chat does not
   follow any more" the reader sees; here it gets a time and the last
   dozen movements before it.

   OVERLAP. The history and the input zone overlapping — the layout tipped
   at runtime, the answer's end unreachable behind the composer.

   And every JavaScript error, because an error that aborts drawing tips
   the layout with it, and the two together are what one guesses at later.

   Measured every 100 ms rather than only on `scroll`: when content falls
   away the browser clamps scrollTop SILENTLY, without a scroll event. A
   watch that only listened to `scroll` slept through exactly the case it
   was built to catch. That happened, and it is the reason for the loop.

   Cost: a few getBoundingClientRect every 100 ms. Nothing. */

const TAKT_MS = 100
const LAYOUT_TAKT_MS = 500
const SCHLUESSEL = 'geometriewache'
const HOECHSTENS = 80
// px: from here on a jump up is a throw-back, below it a hop.
const SPRUNG = 120
const HOPSER = 4
// ms: for so long a wheel or touch event counts as "that was the reader".
// Generous on purpose: a reader who parked the view three seconds ago and
// watches the text grow is still the reason the view stands off the floor,
// and two field reports with the reader's own up-ticks in their trace were
// cried as FOLLOWING LOST because this window had already closed.
const LESER_FENSTER = 5_000
// px above the floor at which following counts as lost, and for how long.
const FOLGE_BAND = 80
const FOLGE_FRIST_MS = 500

// `.zone` exists three times (side grip, work bar, input bar). The input
// zone is meant, and it stands in `.anlauf`.
const ZONE = '.anlauf > .zone'

// Two elements carry `.verlauf`; the chat is the one with the track in it.
function verlaufFinden() {
  return document.querySelector('.spur')?.closest('.verlauf') ?? null
}

function messen(verlauf, zone) {
  const V = verlauf.getBoundingClientRect()
  const Z = zone.getBoundingClientRect()
  return {
    zeit: new Date().toISOString().slice(11, 23),
    ueberlappung: Math.round(V.bottom - Z.top),
    verlauf: [Math.round(V.top), Math.round(V.bottom), Math.round(V.height)],
    zone: [Math.round(Z.top), Math.round(Z.bottom), Math.round(Z.height)],
    fenster: [window.innerWidth, window.innerHeight],
    scroll: [Math.round(verlauf.scrollTop), verlauf.clientHeight, verlauf.scrollHeight],
  }
}

function ablegen(eintrag) {
  try {
    const alt = JSON.parse(localStorage.getItem(SCHLUESSEL) || '[]')
    alt.push(eintrag)
    while (alt.length > HOECHSTENS) alt.shift()
    localStorage.setItem(SCHLUESSEL, JSON.stringify(alt))
  } catch {
    /* storage refused — the window and the log still carry it */
  }
}

/* Into the service's access log, as a path nobody serves: the 404 is the
   point, the path carries the facts. With the session key, so the line is
   a plain 404 and not a rejected call. */
function melden(art, eintrag) {
  const kurz = [
    art,
    eintrag.zeit ?? '',
    'sprung=' + (eintrag.sprung_nach_oben ?? eintrag.ueberlappung ?? ''),
    'hoehe=' + (eintrag.hoehe_verloren ?? ''),
    'scroll=' + (eintrag.scroll ?? []).join('x'),
    'leser=' + (eintrag.leser ?? ''),
    // The last movements before it, so the log line alone tells the story
    // without anyone having to press "copy report".
    'spur=' + (eintrag.spur ?? []).map((s) => s.top + '/' + s.hoehe + '/' + (s.abstand ?? '')).join(','),
  ].join(';')
  const schluessel = window.__SITZUNGSSCHLUESSEL__
  fetch('/api/v1/__geometriewache__/' + encodeURIComponent(kurz), {
    headers: schluessel ? { 'X-Sitzungsschluessel': schluessel } : {},
  }).catch(() => {})
}

function fensterchen() {
  let f = document.getElementById('geometriewache-fenster')
  if (f) return f
  f = document.createElement('div')
  f.id = 'geometriewache-fenster'
  f.style.cssText = [
    'position:fixed', 'right:12px', 'top:52px', 'z-index:99999', 'width:360px',
    'max-height:60vh', 'overflow:auto', 'padding:10px 12px', 'border-radius:9px',
    'background:rgba(20,20,20,.94)', 'color:#ddd', 'font:12px/1.4 ui-monospace,monospace',
    'border:1px solid #666', 'white-space:pre-wrap',
  ].join(';')
  document.body.appendChild(f)
  return f
}

function fensterZeigen() {
  const alles = JSON.parse(localStorage.getItem(SCHLUESSEL) || '[]')
  const wichtig = alles.filter((e) => e.art !== 'HOPSER')
  if (!wichtig.length) return
  const f = fensterchen()
  const zeilen = wichtig.slice(-6).map((e) => {
    if (e.art === 'RUECKWURF') {
      return `${e.zeit} THROW-BACK ${e.sprung_nach_oben}px up, height lost ${e.hoehe_verloren}px\n  ${e.ursache}`
    }
    if (e.art === 'FOLGE-VERLOREN') {
      return `${e.zeit} FOLLOWING LOST ${e.abstand}px above the floor while writing\n  before: ${e.spur.map((s) => s.top + '/' + s.hoehe).join(' ')}`
    }
    if (e.art === 'JS-FEHLER') return `${e.zeit} JS ERROR ${e.text}`
    return `${e.zeit} ${e.art} overlap ${e.ueberlappung}px scroll ${e.scroll?.join('/')}`
  })
  f.textContent = `Geometry watch — ${wichtig.length} event(s)\n\n` + zeilen.join('\n\n')
  const knopf = document.createElement('button')
  knopf.textContent = 'copy report · clear'
  knopf.style.cssText = 'margin-top:8px;font:12px ui-monospace,monospace'
  knopf.onclick = () => {
    const text = JSON.stringify(alles, null, 1)
    navigator.clipboard?.writeText(text).catch(() => {})
    console.log(text)
    localStorage.removeItem(SCHLUESSEL)
    f.remove()
  }
  f.appendChild(document.createElement('br'))
  f.appendChild(knopf)
}

function rueckwurfWache(ablegenFn, zeigenFn, meldenFn) {
  const verlauf = verlaufFinden()
  if (!verlauf) return false

  let letzterLeser = 0
  let leserRichtung = 0
  let vorher = { top: verlauf.scrollTop, hoehe: verlauf.scrollHeight, zeit: performance.now() }
  // Short memory, so a report shows what came BEFORE.
  const verlaufsspur = []
  /* The reader's own hand, kept beside the movements: every wheel tick
     and touch drag, with direction and size. A report can then say "the
     last wheel was 8 seconds before this" instead of guessing whether
     the reader scrolled. */
  const leserspur = []
  const leserMerken = (art, richtung, wert) => {
    leserspur.push({ ms: Math.round(performance.now()), art, richtung, wert: Math.round(wert) })
    if (leserspur.length > 20) leserspur.shift()
  }
  const leserText = () => {
    const jetzt = performance.now()
    const letzte = leserspur[leserspur.length - 1]
    if (!letzte) return 'nie'
    const her = Math.round((jetzt - letzte.ms) / 100) / 10
    return leserspur.slice(-5).map((l) => l.art + (l.richtung < 0 ? 'HOCH' : 'RUNTER') + l.wert).join(',') + '@vor' + her + 's'
  }
  let folgeVerlorenSeit = 0
  let folgeGemeldet = false

  verlauf.addEventListener('wheel', (e) => {
    letzterLeser = performance.now()
    leserRichtung = Math.sign(e.deltaY)
    leserMerken('rad', Math.sign(e.deltaY), e.deltaY)
  }, { passive: true })
  let beruehrungY = 0
  verlauf.addEventListener('touchstart', (e) => { beruehrungY = e.touches[0].clientY }, { passive: true })
  verlauf.addEventListener('touchmove', (e) => {
    letzterLeser = performance.now()
    // Finger moving down = looking up.
    leserRichtung = e.touches[0].clientY > beruehrungY ? -1 : 1
    leserMerken('finger', leserRichtung, e.touches[0].clientY - beruehrungY)
  }, { passive: true })

  const pruefen = () => {
    const jetzt = performance.now()
    const top = verlauf.scrollTop
    const hoehe = verlauf.scrollHeight
    const abstand = hoehe - top - verlauf.clientHeight
    const schreibt = !!document.querySelector('.wartet')
    const leserGerade = jetzt - letzterLeser < LESER_FENSTER && leserRichtung < 0

    // Following lost: an answer is written, the view stands above the
    // floor, and the reader did not scroll up. Once per stretch.
    if (schreibt && abstand > FOLGE_BAND && !leserGerade) {
      if (!folgeVerlorenSeit) folgeVerlorenSeit = jetzt
      else if (!folgeGemeldet && jetzt - folgeVerlorenSeit > FOLGE_FRIST_MS) {
        folgeGemeldet = true
        const eintrag = {
          art: 'FOLGE-VERLOREN',
          zeit: new Date().toISOString().slice(11, 23),
          abstand: Math.round(abstand),
          scroll: [Math.round(top), verlauf.clientHeight, hoehe],
          leser: leserText(),
          spur: verlaufsspur.slice(-12),
        }
        ablegenFn(eintrag)
        zeigenFn()
        console.warn('[Geometriewache] FOLLOWING LOST', eintrag)
        meldenFn('FOLGEVERLOREN', eintrag)
      }
    } else {
      folgeVerlorenSeit = 0
      if (abstand <= 2) folgeGemeldet = false
    }

    if (top === vorher.top && hoehe === vorher.hoehe) return
    verlaufsspur.push({ ms: Math.round(jetzt), top: Math.round(top), hoehe, sicht: verlauf.clientHeight, abstand: Math.round(abstand) })
    if (verlaufsspur.length > 40) verlaufsspur.shift()

    const nachOben = vorher.top - top
    const hoeheWeg = vorher.hoehe - hoehe

    if (nachOben > HOPSER && !leserGerade) {
      const eintrag = {
        // Ending AT the floor means the floor itself moved (the box grew
        // taller, the floor value fell): the reader saw nothing. Kept as a
        // HOP for the record, never shown as a throw-back.
        art: nachOben > SPRUNG && abstand > 2 ? 'RUECKWURF' : 'HOPSER',
        zeit: new Date().toISOString().slice(11, 23),
        sprung_nach_oben: Math.round(nachOben),
        hoehe_verloren: hoeheWeg,
        schreibt,
        ursache: hoeheWeg > HOPSER
          ? 'total height shrank — content fell away under the view'
          : 'height stayed — somebody set the position, or the browser moved it (anchoring, or the box grew)',
        von: { top: Math.round(vorher.top), hoehe: vorher.hoehe },
        zu: { top: Math.round(top), hoehe },
        abstand_danach: Math.round(abstand),
        sichtbar: verlauf.clientHeight,
        leser_vor_ms: letzterLeser ? Math.round(jetzt - letzterLeser) : null,
        leser: leserText(),
        spur: verlaufsspur.slice(-12),
      }
      ablegenFn(eintrag)
      if (eintrag.art === 'RUECKWURF') {
        zeigenFn()
        console.warn('[Geometriewache] THROW-BACK', eintrag)
        meldenFn('RUECKWURF', eintrag)
      }
    }
    vorher = { top, hoehe, zeit: jetzt }
  }

  setInterval(pruefen, TAKT_MS)
  // The scroll event as well, so a fast move between two ticks does not
  // slip through.
  verlauf.addEventListener('scroll', pruefen, { passive: true })
  return true
}

/* Who moved, by name. The browser books every layout shift itself
   (PerformanceObserver, layout-shift) with the element and its old and
   new place. The growing answer text is excluded — that one SHOULD move —
   so what remains is structural: a head, a mark, a foot changing place.
   Throttled to one report per second; the entry names each mover with
   its class and how many pixels it went down (+) or up (-). */
function schubwache(ablegenFn, meldenFn) {
  if (typeof PerformanceObserver === 'undefined') return
  let zuletzt = 0
  const beschreiben = (quelle) => {
    const knoten = quelle.node
    if (!knoten || knoten.nodeType !== 1) return null
    if (knoten.closest?.('.antwort')) return null
    const dy = quelle.currentRect && quelle.previousRect
      ? Math.round(quelle.currentRect.y - quelle.previousRect.y)
      : 0
    if (Math.abs(dy) < 6) return null
    const name = knoten.className
      ? knoten.tagName + '.' + String(knoten.className).split(' ')[0]
      : knoten.tagName
    return name + (dy > 0 ? '+' : '') + dy
  }
  try {
    const beobachter = new PerformanceObserver((liste) => {
      const jetzt = performance.now()
      if (jetzt - zuletzt < 1000) return
      const quellen = []
      for (const e of liste.getEntries()) {
        if (e.hadRecentInput) continue
        for (const q of e.sources || []) {
          const text = beschreiben(q)
          if (text && !quellen.includes(text)) quellen.push(text)
        }
      }
      if (!quellen.length) return
      zuletzt = jetzt
      const eintrag = {
        art: 'SCHUB',
        zeit: new Date().toISOString().slice(11, 23),
        quellen: quellen.slice(0, 6).join(','),
        schreibt: !!document.querySelector('.wartet'),
      }
      ablegenFn(eintrag)
      meldenFn('SCHUB', { ...eintrag, leser: eintrag.quellen })
    })
    beobachter.observe({ type: 'layout-shift', buffered: false })
  } catch {
    /* no layout-shift support — the other watches still stand */
  }
}

export function geometriewacheStarten() {
  let warKaputt = false
  let letzterFehler = 0
  // Whatever an earlier session left behind is shown again at once.
  setTimeout(fensterZeigen, 1500)

  // The history only exists once a chat is open — wait for it, attach once.
  const anhaengen = setInterval(() => {
    if (rueckwurfWache(ablegen, fensterZeigen, melden)) clearInterval(anhaengen)
  }, 1000)
  schubwache(ablegen, melden)

  const fehlerMerken = (text) => {
    const jetzt = Date.now()
    if (jetzt - letzterFehler < 1000) return
    letzterFehler = jetzt
    const verlauf = verlaufFinden()
    const zone = document.querySelector(ZONE)
    const eintrag = verlauf && zone
      ? { art: 'JS-FEHLER', text: String(text).slice(0, 200), ...messen(verlauf, zone) }
      : { art: 'JS-FEHLER', text: String(text).slice(0, 200), zeit: new Date().toISOString().slice(11, 23) }
    ablegen(eintrag)
    fensterZeigen()
    console.warn('[Geometriewache] JS error', eintrag)
    melden('JSFEHLER', eintrag)
  }
  window.addEventListener('error', (e) => fehlerMerken(e.message || e.error))
  window.addEventListener('unhandledrejection', (e) => fehlerMerken(e.reason))

  setInterval(() => {
    const verlauf = verlaufFinden()
    const zone = document.querySelector(ZONE)
    if (!verlauf || !zone) return
    const eintrag = messen(verlauf, zone)
    const kaputt = eintrag.ueberlappung > 1
    if (kaputt === warKaputt) return
    warKaputt = kaputt
    const art = kaputt ? 'KAPUTT' : 'WIEDER-GUT'
    ablegen({ art, ...eintrag })
    fensterZeigen()
    console.warn('[Geometriewache] ' + art, eintrag)
    melden(art, eintrag)
  }, LAYOUT_TAKT_MS)

  // By hand, should a console be at hand after all.
  window.geometrieBericht = () => {
    const alles = JSON.parse(localStorage.getItem(SCHLUESSEL) || '[]')
    console.log(JSON.stringify(alles, null, 1))
    return alles
  }
  window.geometrieLeeren = () => {
    localStorage.removeItem(SCHLUESSEL)
    document.getElementById('geometriewache-fenster')?.remove()
    return 'geleert'
  }
}
