<script>
  /* The line that takes the left of the input bar's row while the voice is in
     use: it shows what is heard.

     It is the microphone's loudness while somebody dictates or is listened
     to, and the answer voice's loudness while it speaks; the first in the
     text colour, the second in blue. While text is still being fetched after
     a dictation and while the model thinks, no loudness is shown — a small
     wave runs through the line instead (blue for the model, the text colour
     for the fetching).

     It is one canvas with a smooth curve and no state of its own beyond the
     smoothed level, the phase of the wave and the colour it is blending
     towards. The loop runs only while the line is shown, plus the moment it
     needs to fade out.

     `zustand` is 'diktat' | 'holt' | 'hoert' | 'denkt' | 'spricht', or null
     while the voice is not in use. */
  import { currentLevel } from '../lib/aufnahme.svelte.js'
  import { playbackLevel } from '../lib/playbackLevel.js'

  let { zustand = null } = $props()

  /* How a level (an RMS between 0 and 1) becomes a height: speech is quiet
     in RMS terms, the factor makes a normal voice fill most of the line. The
     answer voice is quieter than the microphone's signal (measured: a spoken
     sentence sits at an RMS of about 0.05 with peaks near 0.12), so it gets
     the larger factor. */
  const MIC_GAIN = 6
  const VOICE_GAIN = 9
  /* The fade-out lasts under half a second; the loop stays alive that long
     after the line is switched off. */
  const OUT_MS = 520

  let canvas = $state(null)
  let current = null
  let quiet = false

  $effect(() => {
    current = zustand
  })

  $effect(() => {
    if (typeof matchMedia !== 'function') return
    const media = matchMedia('(prefers-reduced-motion: reduce)')
    quiet = media.matches
    const follow = () => { quiet = media.matches }
    media.addEventListener('change', follow)
    return () => media.removeEventListener('change', follow)
  })

  /* Reads a colour token off the canvas as three numbers. The tokens are
     plain hex; anything else keeps the last colour. */
  function colour(style, name, fallback) {
    const value = style.getPropertyValue(name).trim()
    if (/^#[0-9a-f]{6}$/i.test(value)) {
      return [1, 3, 5].map((i) => parseInt(value.slice(i, i + 2), 16))
    }
    return fallback
  }

  /* The loop belongs to the canvas, not to a state: it starts when the line
     is switched on, keeps going through the fade-out, and ends itself. A
     change from one state to the next must not restart it — the smoothed
     level and the colour carry over. */
  let loop = null
  const on = $derived(Boolean(zustand))

  function build(view) {
    const g = view.getContext('2d')
    const style = getComputedStyle(view)
    let level = 0
    let phase = Math.random() * 6
    let thinking = 0
    let rgb = null
    let before = performance.now()
    let t = 0
    let frame = 0
    let offAt = 0

    function draw(rate, mode, source, target) {
      const dpr = window.devicePixelRatio || 1
      const w = Math.round(view.clientWidth * dpr)
      const h = Math.round(view.clientHeight * dpr)
      if (!w || !h) return
      if (view.width !== w || view.height !== h) {
        view.width = w
        view.height = h
      }
      if (!rgb) rgb = target.slice()
      const k = source > level ? 0.35 : 0.08
      level += (source - level) * (1 - Math.pow(1 - k, rate))
      if (!quiet) phase += (mode === 'denkt' ? 0.05 : 0.12) * rate
      const blend = 1 - Math.pow(0.82, rate)
      for (let i = 0; i < 3; i++) rgb[i] += (target[i] - rgb[i]) * blend
      thinking += ((mode === 'denkt' ? 1 : 0) - thinking) * (1 - Math.pow(0.85, rate))

      g.clearRect(0, 0, w, h)
      const middle = h / 2
      const room = middle - 2 * dpr
      const [r, gr, b] = rgb.map(Math.round)
      const gradient = g.createLinearGradient(0, 0, w, 0)
      for (const [at, alpha] of [[0, 0], [0.2, 0.2], [0.5, 0.9], [0.8, 0.2], [1, 0]]) {
        gradient.addColorStop(at, `rgba(${r},${gr},${b},${alpha})`)
      }
      g.strokeStyle = gradient
      g.lineWidth = 1.6 * dpr
      g.lineCap = 'round'
      g.lineJoin = 'round'
      const points = 120
      const f1 = 6
      const f2 = 10
      /* The little wave of the thinking and fetching states: a bump that
         travels along the line — or stands still in the middle when motion
         is asked to be small. */
      const bump = quiet ? 0.5 : ((t * 0.42) % 1.3) - 0.15
      g.beginPath()
      for (let i = 0; i <= points; i++) {
        const x = i / points
        const weight = Math.sin(Math.PI * x) ** 2
        const swing = 0.65 * Math.sin(x * Math.PI * f1 + phase) + 0.35 * Math.sin(x * Math.PI * f2 - phase * 1.3)
        const wave = weight * room * level * swing
        const near = Math.exp(-((x - bump) ** 2) / (2 * 0.07 * 0.07))
        const small = near * room * 0.42 * Math.sin(x * Math.PI * f2 * 1.6 + phase * 2)
        const y = middle - ((1 - thinking) * wave + thinking * small)
        const px = dpr + x * (w - 2 * dpr)
        if (i) g.lineTo(px, y)
        else g.moveTo(px, y)
      }
      g.stroke()
    }

    function tick(now) {
      const dt = Math.min(0.1, (now - before) / 1000)
      before = now
      t += dt
      const state = current
      if (state) {
        offAt = 0
      } else {
        if (!offAt) offAt = now
        if (now - offAt > OUT_MS) {
          g.clearRect(0, 0, view.width, view.height)
          level = 0
          rgb = null
          frame = 0
          return
        }
      }
      const text = colour(style, '--text', [220, 220, 220])
      const blue = colour(style, '--blau', [106, 151, 196])
      let mode = 'voice'
      let source = 0
      let target = text
      if (state === 'diktat' || state === 'hoert') {
        source = Math.min(1, currentLevel() * MIC_GAIN)
      } else if (state === 'holt') {
        mode = 'denkt'
      } else if (state === 'denkt') {
        mode = 'denkt'
        target = blue
      } else if (state === 'spricht') {
        source = Math.min(1, playbackLevel() * VOICE_GAIN)
        target = blue
      }
      draw(dt * 60, mode, source, target)
      frame = requestAnimationFrame(tick)
    }

    return {
      start() {
        if (frame) return
        before = performance.now()
        frame = requestAnimationFrame(tick)
      },
      stop() {
        cancelAnimationFrame(frame)
        frame = 0
      },
    }
  }

  $effect(() => {
    if (!canvas || !on) return
    loop ??= build(canvas)
    loop.start()
  })

  $effect(() => () => loop?.stop())
</script>

<canvas class="zeilenlinie" class:an={Boolean(zustand)} bind:this={canvas} aria-hidden="true"></canvas>

<style>
  /* Fills the room beside the left group, short of the right edge by a
     little air before the model picker. It never takes part in layout: the
     wrapper around it decides the width. */
  .zeilenlinie {
    position: absolute;
    left: 0;
    top: 50%;
    width: calc(100% - 10px);
    height: 30px;
    margin-top: -15px;
    display: block;
    opacity: 0;
    transform: scaleX(0.6);
    transform-origin: left center;
    pointer-events: none;
    /* Out: the line leaves first, quickly. */
    transition: opacity 0.16s ease-in, transform 0.2s ease-in;
  }
  /* In: after the left group has faded (160 ms), the line fades in and grows
     from its left end. */
  .zeilenlinie.an {
    opacity: 1;
    transform: none;
    transition: opacity 0.22s ease-out 0.16s, transform 0.32s cubic-bezier(0.2, 0.9, 0.3, 1) 0.16s;
  }
  /* Less motion: nothing grows, the fades stay — a hard switch would be worse
     than a soft one. The page-wide rule for less motion cuts every transition
     to a hundredth of a millisecond with `!important`; these two fades are
     the exception, so they say their length with it as well. */
  @media (prefers-reduced-motion: reduce) {
    .zeilenlinie,
    .zeilenlinie.an {
      transform: none;
    }
    .zeilenlinie { transition-duration: 0.16s !important; }
    .zeilenlinie.an { transition-duration: 0.22s !important; }
  }
</style>
