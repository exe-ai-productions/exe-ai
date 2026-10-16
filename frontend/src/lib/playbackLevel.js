/*
  The loudness of the answer voice, for the line in the input bar.

  A clip played through a bare `Audio` element cannot be measured. So the
  element is routed through the page's audio graph instead:

      element → analyser → output

  The analyser passes everything through untouched; it only lets the line read
  how loud the clip is right now. The route is set up before `play()` and
  taken down when the clip ends.

  Nothing here may cost the answer its sound. A route is only built when the
  context is running — an element handed to a suspended context would play
  silence — and when building it fails, the element is left alone: the answer
  is still heard, and the line stays calm (`playbackLevel` reads 0).
*/

const FFT = 1024
/* How long a suspended context gets to wake up before the clip plays
   without a route. */
const WAKE_MS = 400

let context = null
let analyser = null
let source = null
/* Whether a suspended context was already given its moment to wake up. */
let woken = false
const samples = new Float32Array(FFT)

function ensureContext() {
  if (context) return context
  const Context = globalThis.AudioContext ?? globalThis.webkitAudioContext
  if (!Context) return null
  context = new Context()
  analyser = context.createAnalyser()
  analyser.fftSize = FFT
  analyser.connect(context.destination)
  return context
}

/** Routes `audio` through the analyser. Resolves to a function that takes the
    route down again, or `null` when no route was built — then the element
    plays on its own, as it would have without this call. Call it before
    `audio.play()`. */
export async function attachPlayback(audio) {
  try {
    const ctx = ensureContext()
    if (!ctx) return null
    if (ctx.state !== 'running') {
      if (woken) {
        /* It did not wake the last time: no waiting for it again — every
           clip would start late — only another try for the next one. */
        ctx.resume().catch(() => {})
        return null
      }
      woken = true
      await Promise.race([ctx.resume(), new Promise((done) => setTimeout(done, WAKE_MS))])
    }
    if (ctx.state !== 'running') return null
    const node = ctx.createMediaElementSource(audio)
    node.connect(analyser)
    source = node
    return () => {
      try {
        node.disconnect()
      } catch {
        /* A node already taken down needs no taking down. */
      }
      if (source === node) source = null
    }
  } catch {
    return null
  }
}

/** How loud the answer voice is right now: the RMS of the last samples, 0 to
    1. 0 while no clip is routed. */
export function playbackLevel() {
  if (!analyser || !source) return 0
  analyser.getFloatTimeDomainData(samples)
  let sum = 0
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i]
  return Math.min(1, Math.sqrt(sum / samples.length))
}
