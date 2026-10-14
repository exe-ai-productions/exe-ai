/*
  The recording — raw samples straight from the microphone, with a WAV header
  in front of them.

  `MediaRecorder` is deliberately not used. It hands out WebM/Opus, which is
  the one thing the speech engine cannot read (it takes WAV, MP3 and FLAC),
  and turning one into the other means a codec: a library in the page, or
  ffmpeg beside the service. Neither travels in an installer we want to hand
  anybody.

  So nothing is converted here. An `AudioWorklet` receives the samples the
  microphone is already producing, they are written out as 16-bit integers,
  and a 44-byte header says what they are. That is not an encoding step —
  it is the recording itself, written down in the shape the engine reads.

  The context is asked for 16 kHz, which is what a speech model wants and
  which makes the file as small as it can be (32 KB per second, mono). A
  browser is allowed to refuse and resample at its own rate; the header
  carries whatever rate the context actually came up at, never the rate that
  was asked for.
*/

/* The ceiling on one recording. Four minutes is a long dictation and about
   eight megabytes AT THE RATE WE ASK FOR — but the rate is the browser's to
   refuse, and at 48 kHz the same four minutes is 22 MB, nearly three times
   what the service accepts. Sending it anyway means the speaker talks for
   four minutes and gets a refusal at the end, with the recording gone.
   So four minutes is the ceiling we want, and `dauergrenze` below is the one
   that actually applies: whichever of the two comes first at the rate the
   context really came up at. */
export const HOECHSTDAUER = 240

const ZIELRATE = 16000

/* The service's own ceiling (app/api/v1/sprachserver.py). Kept here as a
   number rather than fetched: it decides when to stop RECORDING, which has
   to be known before anything is sent. */
const GRENZE_BYTES = 8 * 1024 * 1024
const KOPF_BYTES = 44

/** Seconds that still fit under the service's limit at this sample rate —
    mono 16-bit, so two bytes a sample. */
function dauerGrenze(abtastrate) {
  const passt = Math.floor((GRENZE_BYTES - KOPF_BYTES) / (abtastrate * 2))
  return Math.max(1, Math.min(HOECHSTDAUER, passt))
}

/* What the button reads: whether something is being recorded, and for how
   long. Nothing else belongs in here — the samples are not state anybody
   renders. */
export const aufnahme = $state({ laeuft: false, sekunden: 0 })

/* The worklet, as source text. It lives in this file rather than beside it
   so the build has one module to place and there is no second file that can
   go missing from a package. */
const PROZESSOR = `
class ExeAufnahme extends AudioWorkletProcessor {
  process(eingaenge) {
    const kanal = eingaenge[0] && eingaenge[0][0]
    if (kanal && kanal.length) this.port.postMessage(new Float32Array(kanal))
    return true
  }
}
registerProcessor('exe-aufnahme', ExeAufnahme)
`

let strom = null
let kontext = null
let knoten = null
let quelle = null
let stumm = null
let bloecke = []
let rate = ZIELRATE
let uhr = null
let beginn = 0
let aufZeitende = null
/* Held from the first line of `starten` until the recording is either
   running or torn down again — the window in which `laeuft` is still false
   but a microphone may already be open. */
let startet = false
/* Fired once per incoming block with its RMS level, scaled to the 16-bit
   range a WAV sample would carry — a live conversation's own silence
   detection (Eingabeleiste.svelte) reads it straight from the worklet's
   callback rather than through a reactive effect, so its timing survives
   whatever else the page's render loop is doing. */
let aufPegel = null

/* Which sentence a failed start deserves, as the catalogue key for it. The
   mapping lives here because the two cases the browser actually reports are
   the two this module provokes; the wording stays in the catalogue. */
export function fehlerschluessel(fehler) {
  const name = fehler?.name
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'sprache.mikro_verweigert'
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'sprache.kein_mikro'
  return 'sprache.aufnahme_fehler'
}

function abbauen() {
  if (uhr) clearInterval(uhr)
  uhr = null
  try {
    knoten?.port?.close?.()
    quelle?.disconnect()
    knoten?.disconnect()
    stumm?.disconnect()
  } catch {
    /* A node already torn down needs no tearing down. */
  }
  for (const spur of strom?.getTracks?.() ?? []) spur.stop()
  kontext?.close?.()
  strom = null
  kontext = null
  knoten = null
  quelle = null
  stumm = null
  startet = false
  aufPegel = null
  aufnahme.laeuft = false
  aufnahme.sekunden = 0
}

/** Starts recording. Throws what `getUserMedia` throws — the caller turns it
    into a sentence through `fehlerschluessel`.

    `beiZeitende` fires when the recording stops itself at the ceiling, so
    the button can fetch the text exactly as it would on a second press.

    `aufPegel(pegel)`, when given, is called for every block with its RMS
    level on the 16-bit scale — a live conversation watches it for silence,
    everything else leaves it out. */
export async function starten(beiZeitende = null, aufPegelCb = null) {
  /* `laeuft` only turns true at the very end of this function, and getting
     there means waiting for the permission dialogue — which stands open for
     as long as somebody hesitates. A second press in that window would run
     this again and overwrite `strom` and `kontext` with a second set, and
     the first microphone would then never be handed to `abbauen()`: it stays
     open, with the recording light on, for the life of the page. So the door
     is shut on the way in, not at the end. */
  if (aufnahme.laeuft || startet) return
  startet = true
  aufZeitende = beiZeitende
  aufPegel = aufPegelCb
  bloecke = []
  try {
    strom = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    })
  } catch (fehler) {
    startet = false
    throw fehler
  }
  try {
    try {
      kontext = new AudioContext({ sampleRate: ZIELRATE })
    } catch (error) {
      /* A browser may refuse the rate it was asked for (the constructor
         throws NotSupportedError). The recording then starts at the rate
         the device runs at: the header carries it and `dauerGrenze` follows
         it. Any other failure is not about the rate and ends the start. */
      if (error?.name !== 'NotSupportedError') throw error
      kontext = new AudioContext()
    }
    const adresse = URL.createObjectURL(new Blob([PROZESSOR], { type: 'text/javascript' }))
    try {
      await kontext.audioWorklet.addModule(adresse)
    } finally {
      URL.revokeObjectURL(adresse)
    }
    /* A context may come up suspended — the browser's own rule about audio
       that starts without a hand on it, and the permission dialogue in front
       of the microphone is long enough for the gesture to have run out. A
       suspended context runs no worklet, so the recording would be silence
       with nothing to say so. Harmless when it is already running. */
    await kontext.resume()
    rate = kontext.sampleRate
    quelle = kontext.createMediaStreamSource(strom)
    knoten = new AudioWorkletNode(kontext, 'exe-aufnahme')
    knoten.port.onmessage = (nachricht) => {
      const block = nachricht.data
      bloecke.push(block)
      if (!aufPegel) return
      let summe = 0
      for (let i = 0; i < block.length; i++) {
        const wert = block[i]
        summe += wert * wert
      }
      const effektivwert = Math.sqrt(summe / block.length)
      aufPegel(Math.min(1, effektivwert) * 0x8000)
    }
    quelle.connect(knoten)
    /* A worklet is only pulled while it leads somewhere. It leads to the
       output through a gain of zero — connected straight to the speakers it
       would play the microphone back into the room. */
    stumm = kontext.createGain()
    stumm.gain.value = 0
    knoten.connect(stumm)
    stumm.connect(kontext.destination)
  } catch (fehler) {
    abbauen()
    throw fehler
  }
  beginn = performance.now()
  aufnahme.sekunden = 0
  aufnahme.laeuft = true
  startet = false
  const grenze = dauerGrenze(rate)
  uhr = setInterval(() => {
    aufnahme.sekunden = Math.floor((performance.now() - beginn) / 1000)
    if (aufnahme.sekunden < grenze) return
    const fertig = aufZeitende
    /* Stopped from in here, so the caller gets the same blob it would get
       from a second press — and gets it exactly once. */
    const blob = stoppen()
    fertig?.(blob)
  }, 250)
}

/** Ends the recording and hands back what was recorded, as a WAV blob.
    `null` when nothing was running. */
export function stoppen() {
  if (!aufnahme.laeuft) return null
  const gesammelt = bloecke
  const genommen = rate
  bloecke = []
  aufZeitende = null
  aufPegel = null
  abbauen()
  return wav(gesammelt, genommen)
}

/** What was recorded so far from sample `ab` on, as a WAV blob — without
    stopping anything. `bis` is where this copy ends, the `ab` of a later
    call that should start behind it. `null` when nothing is running.

    For the readings taken while somebody still dictates: the samples are
    copied, the recording goes on untouched. */
export function zwischenstand(ab = 0) {
  if (!aufnahme.laeuft) return null
  const teile = []
  let stelle = 0
  for (const block of bloecke) {
    const ende = stelle + block.length
    if (ende > ab) teile.push(stelle >= ab ? block : block.subarray(ab - stelle))
    stelle = ende
  }
  return { blob: wav(teile, rate), bis: stelle }
}

/** Ends the recording and throws it away. What Escape does. */
export function abbrechen() {
  if (!aufnahme.laeuft) return
  bloecke = []
  aufZeitende = null
  aufPegel = null
  abbauen()
}

function wav(gesammelt, abtastrate) {
  let laenge = 0
  for (const block of gesammelt) laenge += block.length
  const proben = new Int16Array(laenge)
  let i = 0
  for (const block of gesammelt) {
    for (let k = 0; k < block.length; k++) {
      /* Clamped before scaling: a sample above 1 would wrap around the
         integer and turn a loud moment into a crack. */
      const wert = Math.max(-1, Math.min(1, block[k]))
      proben[i++] = wert < 0 ? wert * 0x8000 : wert * 0x7fff
    }
  }
  const daten = proben.length * 2
  const kopf = new ArrayBuffer(44)
  const sicht = new DataView(kopf)
  const wort = (stelle, text) => {
    for (let k = 0; k < text.length; k++) sicht.setUint8(stelle + k, text.charCodeAt(k))
  }
  wort(0, 'RIFF')
  sicht.setUint32(4, 36 + daten, true)
  wort(8, 'WAVE')
  wort(12, 'fmt ')
  sicht.setUint32(16, 16, true)
  /* 1 is uncompressed integer samples — the only thing written here. */
  sicht.setUint16(20, 1, true)
  sicht.setUint16(22, 1, true)
  sicht.setUint32(24, abtastrate, true)
  sicht.setUint32(28, abtastrate * 2, true)
  sicht.setUint16(32, 2, true)
  sicht.setUint16(34, 16, true)
  wort(36, 'data')
  sicht.setUint32(40, daten, true)
  return new Blob([kopf, proben.buffer], { type: 'audio/wav' })
}
