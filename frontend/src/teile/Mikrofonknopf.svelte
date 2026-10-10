<script>
  /* The dictation button, on its own so it can stand in two places.

     It used to live only in the bar's footer, and the footer is folded away
     while a chat is still empty — so the one thing dictation is FOR, opening
     your mouth before anything has been written, was the one moment the
     button was not there.

     THE MARK is a microphone: capsule, arc, foot. It was five bars before —
     a level meter, and a level meter is also a diagram. Nothing about it
     said that this is where you speak; this one needs no explaining, which
     is the whole of the argument for it.

     THE MOVEMENT is around the mark, never in it. While it records, two
     rings open out of the button and fade, one behind the other, and the
     mark itself only brightens. Three other movements were drawn and put
     aside: the mark drawing itself on, a level rising inside the capsule,
     and the arc sweeping like a needle. All three move the glyph, and a
     glyph this small that moves is a glyph that flickers. This one is the
     quiet one — it says "listening" without asking the eye to follow
     anything.

     Its drawing lives here and nowhere else. The comment it was born with
     says the mark is meant to be swapped, and a second copy beside the
     first would make that a lie the day somebody swapped one of them.

     A HOLD, next to the click: a short click still means what it always
     did, but holding for one second toggles a free conversation — a blue
     arc fills while the second runs, so letting go early costs nothing.
     `onhalten` fires once the second is up; a release before that instead
     fires `onschalten`, exactly as a plain click always has. The one
     timer decides which of the two happened, so the two can never both
     fire for the same press.

     THE CONVERSATION RING is a third movement, on top of the two above,
     never at once with them: a blue arc turns slowly the whole time a
     conversation runs, and three of its own states ride on it — a slow
     wobble while it listens, a faster spin while it thinks, a flicker
     while it speaks. `prefers-reduced-motion` leaves the ring standing
     lit rather than turning it off outright: the state stays readable,
     only the motion goes. */
  import { t } from '../lib/texte.svelte.js'

  let {
    nimmt = false,
    holt = false,
    gespraech = false,
    gespraechZustand = null,
    onschalten,
    onhalten,
  } = $props()

  let haelt = $state(false)
  let haltTimer = null
  /* Set the instant a hold or a pointer-driven tap already answered the
     press — the `click` a mouse or a touch fires right after `pointerup`
     would otherwise call `onschalten` a second time. A key press never
     sets it: it never sends the pointer events this guards against. */
  let pointerBehandelt = false
  /* Set while the running hold is the keyboard's. The keys only ever end a
     hold they began themselves: a key let go during a mouse hold, or the
     focus moving away from under the mouse, leaves that hold to the
     pointer — which answers for its own click; and the pointer, in turn,
     leaves a keyboard hold alone. */
  let tasteHaelt = false

  function nieder(e) {
    // Only the primary button: a right click opens the context menu and
    // must not start a dictation on its way up, nor a conversation held.
    if (e.button !== 0) return
    // A hold already running (the keyboard's) is not taken over.
    if (haltTimer) return
    haelt = true
    haltTimer = setTimeout(() => {
      haltTimer = null
      haelt = false
      pointerBehandelt = true
      onhalten?.()
    }, 1000)
  }
  function hoch() {
    if (tasteHaelt) return
    if (!haltTimer) {
      haelt = false
      return
    }
    clearTimeout(haltTimer)
    haltTimer = null
    haelt = false
    pointerBehandelt = true
    onschalten?.()
  }
  function abgebrochen() {
    // A mouse merely passing off the button does not end a keyboard hold.
    if (tasteHaelt) return
    if (haltTimer) clearTimeout(haltTimer)
    haltTimer = null
    haelt = false
    // A hold that already fired and was then dragged off the button ends
    // without a click, so nothing would consume the mark and the next key
    // press on the button would be swallowed in its place.
    pointerBehandelt = false
  }
  function klick() {
    if (pointerBehandelt) {
      pointerBehandelt = false
      return
    }
    onschalten?.()
  }

  /* The same hold from the keyboard. Space and Enter are the two keys a
     focused button answers to, and each would fire its own `click` — Enter
     on the way down (and again on every repeat), Space on the way up. Both
     defaults are cancelled here, so the press is decided by the one timer
     above and never also by a click: short = `onschalten`, one second =
     `onhalten`, exactly as with the pointer. */
  function istAusloeser(e) {
    return e.key === ' ' || e.key === 'Enter'
  }
  function tasteNieder(e) {
    if (!istAusloeser(e)) return
    e.preventDefault()
    // A held key repeats its keydown; only the first one starts the hold.
    if (e.repeat || haelt || haltTimer) return
    tasteHaelt = true
    haelt = true
    haltTimer = setTimeout(() => {
      haltTimer = null
      haelt = false
      tasteHaelt = false
      onhalten?.()
    }, 1000)
  }
  function tasteHoch(e) {
    if (!istAusloeser(e)) return
    e.preventDefault()
    if (!tasteHaelt || !haltTimer) return
    clearTimeout(haltTimer)
    haltTimer = null
    haelt = false
    tasteHaelt = false
    onschalten?.()
  }
  /* Focus leaving the button mid-hold ends a keyboard hold without a
     click, like a pointer dragged off it. */
  function verlassen() {
    if (!tasteHaelt) return
    if (haltTimer) clearTimeout(haltTimer)
    haltTimer = null
    haelt = false
    tasteHaelt = false
  }

  /* A finger resting on the button is also a long press, and a long press
     is what raises the browser's context menu — measured with a touch
     gesture: the menu event arrived after 0.68 s, in the middle of the
     one-second hold. Cancelled only while a hold runs, so a right click
     with the mouse (which never starts one) keeps its menu. */
  function menue(e) {
    if (haelt) e.preventDefault()
  }

  const gespraechTitel = $derived(
    !gespraech
      ? t('sprache.gespraech_beginnen')
      : t(`sprache.gespraech_${gespraechZustand}`),
  )
</script>

<button
  class="mikro"
  class:nimmt
  class:holt
  class:haelt
  class:gespraech
  class:hoert={gespraech && gespraechZustand === 'hoert'}
  class:denkt={gespraech && gespraechZustand === 'denkt'}
  class:spricht={gespraech && gespraechZustand === 'spricht'}
  disabled={holt}
  onpointerdown={nieder}
  onpointerup={hoch}
  onpointerleave={abgebrochen}
  onpointercancel={abgebrochen}
  onclick={klick}
  onkeydown={tasteNieder}
  onkeyup={tasteHoch}
  onblur={verlassen}
  oncontextmenu={menue}
  title={gespraech || haelt ? gespraechTitel : (nimmt ? t('sprache.aufnahme_stoppen') : t('sprache.aufnehmen'))}
  aria-label={gespraech ? gespraechTitel : t('sprache.diktat')}
  aria-pressed={nimmt || gespraech}
>
  <svg class="zeichen" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-linecap="round"
       stroke-linejoin="round" aria-hidden="true">
    <!-- Capsule, arc, foot. One layer: nothing in here moves, so there is
         nothing for a second one to draw. -->
    <path d="M32 9 a8 8 0 0 1 8 8 V29 a8 8 0 0 1 -16 0 V17 a8 8 0 0 1 8 -8 Z" stroke-width="5" />
    <path d="M15 29 a17 17 0 0 0 34 0" stroke-width="5" />
    <path d="M32 46 V56" stroke-width="5" />
  </svg>
  <!-- The two breathing rings, and the spinner for the third state. Both
       sit outside the sign so neither can push it around. -->
  <span class="atem" aria-hidden="true"></span>
  <span class="atem zwei" aria-hidden="true"></span>
  <span class="ring"></span>
  <!-- The hold arc: empty until a press begins, drawn to full over the one
       second that decides click from hold. -->
  <svg class="halten" viewBox="0 0 32 32" aria-hidden="true">
    <circle cx="16" cy="16" r="15.2" pathLength="100" />
  </svg>
  <!-- The conversation ring, always present in the markup so its opacity
       transition has something to animate between; invisible until
       `gespraech` is on. -->
  <span class="blau" aria-hidden="true"></span>
</button>

<style>
  /* The action button's own box, at its own size and radius, in the quiet
     construction that button already wears while it is stopping something —
     no fill, a sign in the resting brightness. */
  .mikro {
    width: 32px;
    height: 32px;
    flex: none;
    border-radius: 50%;
    border: none;
    padding: 0;
    cursor: pointer;
    display: grid;
    place-items: center;
    position: relative;
    background: none;
    color: var(--text-leise);
    /* Slower than a hover, because this one is the state changing and not a
       pointer passing over. */
    transition: color 0.24s ease, transform 0.1s ease;
    /* A finger held on the button is a hold, not a scroll, a text selection
       or the system's callout: without these the browser may take the touch
       for itself and cancel the pointer halfway through the second. */
    touch-action: none;
    user-select: none;
    -webkit-user-select: none;
    -webkit-touch-callout: none;
  }
  .mikro:not(:disabled):hover { color: var(--text); }
  .mikro:not(:disabled):active { transform: scale(0.94); }
  .mikro:disabled { cursor: default; }
  /* 20, not the 16 the other signs in the bar wear. The microphone is a
     NARROW drawing — its widest part, the arc, fills barely half the box,
     where a plus or an arrow fills all of it. At the same number it reads
     as the smaller sign; at 20 it reads as an equal, and there is still
     6 px of air on either side of it inside the button. Only the sign: a
     rule on every svg in here would also shrink the hold arc below to 20 px
     and pin it to the button's top-left corner. */
  .mikro .zeichen { width: 20px; height: 20px; overflow: visible; }
  /* Recording is the sign at full brightness. Brightness, not colour: the
     four colours of the palette mean a state of the program, and this is a
     state of one button. */
  .mikro.nimmt { color: var(--text); }

  /* The breath. Two rings on the same 2.4s, the second half a cycle behind,
     so there is always one on its way out and the ring never appears to
     stop. They open just outside the sign and end exactly on the button's
     own edge, faded to nothing before they get there.

     ENDING ON THE EDGE is not a taste, it is the measurement: the input bar
     clips its content (`overflow: hidden`), so a ring that grew past the
     button would be cut off flat at the bar's rim — half a circle, top and
     bottom shaved. Contained, it looks the same wherever the button stands.

     `currentColor`, so it is the sign's own brightness that breathes, and
     `pointer-events: none`, so a ring on its way out cannot swallow the
     click that stops the recording. */
  .atem {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    border: 1.5px solid currentColor;
    opacity: 0;
    pointer-events: none;
  }
  /* Not while a conversation runs: `nimmt` is also true for the recording
     a conversation's own "hoert" phase keeps open, and the conversation
     ring below already says so on its own — two rings breathing under a
     third one turning would be three movements standing for one state. */
  .mikro.nimmt:not(.gespraech) .atem {
    animation: atmen 2.4s cubic-bezier(0.25, 0.6, 0.3, 1) infinite;
  }
  .mikro.nimmt .atem.zwei { animation-delay: 1.2s; }
  @keyframes atmen {
    0% { transform: scale(0.55); opacity: 0; }
    20% { opacity: 0.55; }
    100% { transform: scale(1); opacity: 0; }
  }

  .ring {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    border: 1.5px solid var(--linie-stark);
    border-top-color: var(--blau);
    opacity: 0;
    transition: opacity 0.16s;
  }
  /* The spinner the action button already has, in the third state. */
  .mikro.holt .ring {
    opacity: 1;
    animation: dreht 1.4s linear infinite;
  }
  @keyframes dreht {
    to { transform: rotate(360deg); }
  }

  /* The hold arc: empty until a press begins, drawn to full stroke over the
     one second a hold takes — `pathLength="100"` on the circle itself is
     what lets the dash numbers below read as a plain percentage regardless
     of the radius. */
  .halten {
    position: absolute;
    inset: 0;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.12s;
  }
  .halten circle {
    fill: none;
    stroke: var(--blau);
    stroke-width: 1.5;
    stroke-dasharray: 100;
    stroke-dashoffset: 100;
    transform: rotate(-90deg);
    transform-origin: 50% 50%;
  }
  .mikro.haelt .halten { opacity: 1; }
  .mikro.haelt .halten circle {
    transition: stroke-dashoffset 1s linear;
    stroke-dashoffset: 0;
  }

  /* The conversation ring: a turning arc the whole time a conversation
     runs, with a state of its own riding on top for listening, thinking
     and speaking. The mask cuts a hole the size of the sign out of the
     middle, so the ring reads as a ring around it and not a disc behind
     it. */
  .blau {
    position: absolute;
    inset: 1px;
    border-radius: 50%;
    opacity: 0;
    pointer-events: none;
    background: conic-gradient(
      from 0deg, transparent 0deg, var(--blau) 120deg, transparent 240deg,
      var(--blau) 330deg, transparent 360deg
    );
    -webkit-mask: radial-gradient(circle, transparent 12.5px, #000 13px);
    mask: radial-gradient(circle, transparent 12.5px, #000 13px);
    transition: opacity 0.2s;
  }
  .mikro.gespraech .blau { opacity: 0.9; animation: dreht 4s linear infinite; }
  .mikro.gespraech.hoert .blau {
    animation: dreht 4s linear infinite, schwingt 1.6s ease-in-out infinite;
  }
  .mikro.gespraech.denkt .blau { opacity: 0.55; animation: dreht 1.2s linear infinite; }
  .mikro.gespraech.spricht .blau {
    animation: dreht 4s linear infinite, spricht 0.45s ease-in-out infinite alternate;
  }
  @keyframes schwingt {
    50% { transform: scale(0.9) rotate(180deg); }
  }
  @keyframes spricht {
    from { opacity: 0.5; }
    to { opacity: 1; }
  }

  /* Whoever asked for less movement gets none: the sign still brightens and
     the conversation ring still shows, so both states stay readable — it is
     only the motion that goes. */
  @media (prefers-reduced-motion: reduce) {
    .mikro.nimmt .atem,
    .mikro.gespraech .blau {
      animation: none;
    }
  }
</style>
