<script>
  /* The voice button, on its own so it can stand in two places.

     It used to live only in the bar's footer, and the footer is folded away
     while a chat is still empty — so the one thing dictation is FOR, opening
     your mouth before anything has been written, was the one moment the
     button was not there.

     THE MARK is a microphone: capsule, arc, foot. In rest the button has no
     fill and the mark wears the quiet text colour, so it stands apart from
     the send button beside it, which carries the fill.

     DICTATION turns the mark into a stop square, in the text colour, still
     with no fill. While the text of a dictation is being fetched the mark
     is dimmed and the button waits. What is heard is shown by the line that
     takes the left of the row (VoiceLine.svelte), not by anything on the
     button: no rings, no spinner, no counter.

     THE CONVERSATION is the one state with a colour: a quiet blue fill and a
     blue ring. The ring breathes while the model thinks — its depth is a
     registered number that glides to its new value, so the breathing dies
     away instead of snapping back.

     A HOLD, next to the click: a short click still means what it always
     did, but holding for one second toggles a free conversation — a blue
     arc runs around the button while the second runs, so letting go early
     costs nothing: the arc runs back. `onhalten` fires once the second is
     up; a release before that instead fires `onschalten`, exactly as a
     plain click always has. The one timer decides which of the two
     happened, so the two can never both fire for the same press.

     Its drawing lives here and nowhere else. */
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
  class:diktat={nimmt && !gespraech}
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
  <!-- The stop square of a dictation: in the same place as the mark, which
       leaves as the square arrives. -->
  <span class="stopp" aria-hidden="true"></span>
  <!-- The conversation's ring, its own layer: it fades in and out, and its
       ::after breathes. -->
  <span class="ring" aria-hidden="true"></span>
  <!-- The hold arc: empty until a press begins, drawn to full over the one
       second that decides click from hold, around the button's own outline. -->
  <svg class="halten" viewBox="0 0 30 30" aria-hidden="true">
    <rect x="0.75" y="0.75" width="28.5" height="28.5" rx="14.25" pathLength="100" />
  </svg>
</button>

<style>
  /* The button's own box: no fill, a sign in the quiet text colour. The
     send button beside it is the one that wears the fill. */
  .mikro {
    width: 30px;
    height: 30px;
    flex: none;
    border-radius: 15px;
    border: none;
    padding: 0;
    cursor: pointer;
    display: grid;
    place-items: center;
    position: relative;
    background: none;
    color: var(--text-leise);
    /* Slower than a hover, because this one is the state changing and not a
       pointer passing over. The depth of the ring's breathing glides too. */
    transition: color 0.24s ease, background-color 0.24s ease, transform 0.1s ease, --tiefe 0.3s ease;
    /* A finger held on the button is a hold, not a scroll, a text selection
       or the system's callout: without these the browser may take the touch
       for itself and cancel the pointer halfway through the second. */
    touch-action: none;
    user-select: none;
    -webkit-user-select: none;
    -webkit-touch-callout: none;
  }
  .mikro:not(.gespraech):not(:disabled):hover { color: var(--text); }
  .mikro:not(:disabled):active { transform: scale(0.94); }
  .mikro:disabled { cursor: default; }
  /* 20, not the 16 the other signs in the bar wear. The microphone is a
     NARROW drawing — its widest part, the arc, fills barely half the box,
     where a plus or an arrow fills all of it. At the same number it reads
     as the smaller sign; at 20 it reads as an equal. Only the sign: a rule
     on every svg in here would also shrink the hold arc below. */
  .mikro .zeichen {
    width: 20px;
    height: 20px;
    overflow: visible;
    transition: opacity 0.18s, transform 0.18s cubic-bezier(0.2, 0.9, 0.3, 1);
  }

  /* Dictation: the sign becomes the stop square, in the text colour. */
  .mikro.diktat { color: var(--text); }
  .mikro.diktat .zeichen { opacity: 0; transform: scale(0.6); }
  .stopp {
    position: absolute;
    left: 50%;
    top: 50%;
    width: 10px;
    height: 10px;
    margin: -5px 0 0 -5px;
    border-radius: 2.5px;
    background: currentColor;
    opacity: 0;
    transform: scale(0.6);
    pointer-events: none;
    transition: opacity 0.14s, transform 0.18s cubic-bezier(0.2, 0.9, 0.3, 1);
  }
  .mikro.diktat .stopp { opacity: 1; transform: none; }
  /* The text of the dictation is being fetched: the sign waits, dimmed. */
  .mikro.holt .zeichen { opacity: 0.45; }

  /* The hold arc: empty until a press begins, drawn to full stroke over the
     one second a hold takes — `pathLength="100"` on the outline itself is
     what lets the dash numbers below read as a plain percentage. Let go
     early and it runs back instead of vanishing. */
  .halten {
    position: absolute;
    left: 0;
    top: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
    opacity: 0;
    overflow: visible;
    transition: opacity 0.12s;
  }
  .halten rect {
    fill: none;
    stroke: var(--blau);
    stroke-width: 1.5;
    stroke-dasharray: 100;
    stroke-dashoffset: 100;
    transition: stroke-dashoffset 0.2s ease-out;
  }
  .mikro.haelt .halten { opacity: 1; }
  .mikro.haelt .halten rect {
    transition: stroke-dashoffset 1s linear;
    stroke-dashoffset: 0;
  }

  /* The conversation: a quiet blue fill, the sign and the ring in blue.
     The ring is a layer of its own: `.ring` fades it in and out, its
     ::after breathes. `--atem` is the beat (it runs all the time), `--tiefe`
     says how strongly it breathes and glides when the state changes — the
     breathing dies away instead of springing back. */
  @property --tiefe {
    syntax: '<number>';
    inherits: true;
    initial-value: 0;
  }
  @property --atem {
    syntax: '<number>';
    inherits: false;
    initial-value: 0;
  }
  .ring {
    position: absolute;
    inset: 0;
    border-radius: inherit;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.24s;
  }
  .ring::after {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: inherit;
    box-shadow: inset 0 0 0 1.5px var(--blau);
    opacity: calc(1 - 0.65 * var(--atem) * var(--tiefe));
    animation: ringatem 1.2s ease-in-out infinite;
  }
  @keyframes ringatem {
    50% { --atem: 1; }
  }
  .mikro.gespraech {
    background: color-mix(in srgb, var(--blau) 16%, transparent);
    color: var(--blau);
  }
  .mikro.gespraech .ring { opacity: 1; }
  .mikro.gespraech.denkt { --tiefe: 1; }

  /* Whoever asked for less movement gets none: the ring does not breathe and
     the sign does not scale — the fades stay, so nothing switches hard. The
     page-wide rule for less motion cuts every transition to a hundredth of a
     millisecond with `!important`; the fades of the button's own states are
     the exception, so they say their length with it as well. */
  @media (prefers-reduced-motion: reduce) {
    .ring::after { animation: none; }
    .mikro .zeichen,
    .stopp { transform: none; }
    .mikro { transition-duration: 0.24s !important; }
    .mikro .zeichen { transition-duration: 0.18s !important; }
    .stopp { transition-duration: 0.14s !important; }
    .ring { transition-duration: 0.24s !important; }
  }
</style>
