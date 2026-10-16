<script>
  /* The house's one window frame: veil, box, title —
     nothing else. What goes in the window is brought by the caller.

     Extracted because three windows each maintained the same frame once
     (system prompt, settings, new job) — and more are coming.

     Anchored at the top, not centered: otherwise the window grows apart
     upward AND downward while typing. If it gets taller than the screen,
     the veil scrolls — the window as a whole, never a region inside it.
     That's the scrollbar rule: none where none has to be. */
  import { fade, scale } from 'svelte/transition'
  import { t } from '../lib/texte.svelte.js'
  import { cubicIn } from 'svelte/easing'
  import { toRoot } from '../lib/rootPortal.js'

  /* At least three window kinds open from inside `.anlauf` (the wordmark
     and input group) or a sibling menu that shares its ancestor chain —
     `bild` itself, `werk` (the mask editor, opened from INSIDE the picture
     window), `frage` (the working-folder picker, three entries up in the
     same plus-menu). `.anlauf` carries `position:relative; z-index:1` so
     it can stand above the watermark behind it (App.svelte), and that
     makes it a stacking context of its own: a `.schleier` nested inside it
     is worth exactly `.anlauf`'s 1 from outside, no matter what z-index it
     carries internally — so the header band's z-index:3 (needed there so
     ITS OWN dropdown clears the scrolling chat below it) paints over
     whichever of these windows is open, and two windows opened one from
     the other inside `.anlauf` have no reliable order between them either.

     Reparenting every veil onto `#wurzel` — the same zoomed root
     everything else already answers to, so --stufenfaktor still reaches it
     — puts all of them in the ONE stacking context that already resolves
     correctly against the header band (70 outranks 3), and turns the
     window-over-window question into plain DOM order: whichever opens
     LATER is appended later, and later siblings paint on top at equal
     z-index — exactly "the one opened from the other stands over it",
     just decided by append order now instead of nesting. Applied to every
     kind rather than picking the three known today: the next window
     opened from inside some future menu is this same bug waiting to
     happen, and a blanket reparent costs nothing for a window that was
     never trapped in the first place — it simply becomes #wurzel's next
     child in the order it opened, which is already where it painted.

     No silent fallback if `#wurzel` is missing: every window in the house
     depends on it existing, so a caller that cannot find it has a broken
     page, not a window that quietly fails to appear — the same "loud is
     right" rule main.js already applies when it can't find the same
     element. */
  /* `symbol` is an optional icon before the title — the job dialog puts
     the agent mark there. As a snippet and not a fixed component, so the
     frame doesn't have to know what fills it. */
  /* Two kinds of window, and the kind decides the size — not the caller.
     Five widths grew here over time (460, 480, 560, 780, 880), and they only
     stand out when two windows are opened one after the other. A single
     `art` instead of a free width is on purpose: a caller cannot pick 780
     and forget the height that belongs to it, which is exactly how the
     settings window drifted 279 px away from the other three.

       frage  460 wide, height follows the content — one question with one
              answer (choose a folder, start a job). Three rows in a box of
              fixed height would stand mostly empty.

       liste  900 wide and a body of FIXED height — everything with a side
              list (settings, models, tools). They are opened one after the
              other and switched between, so any difference reads as a jump.
              The width grew from 780 when the server form's labels started
              wrapping into three lines; the side lists keep their measure,
              so all the new room goes to the content half.

       vorschau  the widest, and taller — it holds a document that was
              written to be looked at. A page squeezed into a list window
              would be judged by the squeeze and not by the page.

     Every width is a `min(…, 92vw)` and every height a `clamp`, so the
     numbers are ceilings for a large screen and never a floor on a small
     one. That is what makes one set of numbers work from a laptop to a 5K
     display: the window takes the room it is given and stops where reading
     would turn into scanning.

     Equal height used to be called impossible here, and that was wrong: it
     is impossible only while a window grows with its content. With a fixed
     body and scrolling inside — the bars are invisible house-wide — every
     window of one kind is the same, whether three rows stand in it or
     thirty. */
  /* galerie: the model catalogue. Wider than a list window so a three-up
     card grid breathes, and a touch taller — a gallery is looked at, not
     scanned down a side list. Still capped to the app area by the same
     min()/clamp() as the others. */
  // `bild` computes its own width below (94vw/--stufenfaktor, no ceiling:
  // it fills the room on every screen; the ACTIVE interface stage's zoom
  // divided back out, not a number copied
  // from it: a stage written here as a constant silently stops cancelling
  // the moment the stage changes) — no entry needed here.
  const BREITE = {
    frage: '460px', liste: '1280px', vorschau: '1200px', galerie: '1040px',
    lesen: '500px', mcp: '740px',
  }
  /* `lesen` and `mcp` are the two kinds that also hold a HEIGHT. Every other
     window is as tall as what it holds, which is right for a form: it has a
     known number of fields and a bottom. A task window has neither — two
     lines for one task, forty for the next — and a window that jumped
     between those two sizes on consecutive clicks is a window that moves its
     own close button out from under the pointer. One box, always the same, and
     what does not fit scrolls inside it.

     `mcp` carries the same problem for a different reason: its tool list
     answers a live server, six rows for one, fifty for the next — a sheet
     that grew with the answer would show a different size for every server
     it was opened on. */
  const HOEHE = { lesen: '650px', mcp: '520px' }

  /* `werk` is the one kind without a number: a workbench window takes the
     size of the work on its table — a canvas window hugs its canvas, tall
     for a portrait, broad for a landscape — where every other kind holds a
     width so its content cannot push it around. */

  /* `schrumpfen` closes the window the way the first-start window does:
     it collapses to a point instead of fading. Reserved for a window whose
     closing IS the start of something — the work then appears where the
     window went, and the eye follows it there. The mechanic is the
     first-start window's; only the numbers live here now, so both breathe
     the same way. */
  /* `zurueck` turns the window into a step: an arrow appears in the top-left
     corner and runs it. Closing still closes everything — the arrow is the
     way back, not a second close button. */
  let {
    offen = $bindable(false), titel = '', art = 'frage', symbol, schrumpfen = false,
    zurueck = null, kopf, children,
  } = $props()
</script>

{#if offen}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="schleier" class:weit={art === 'vorschau' || art === 'werk' || art === 'liste'}
       class:liste={art === 'liste'} transition:fade={{ duration: 150 }}
       use:toRoot
       onclick={(e) => { if (e.target === e.currentTarget) offen = false }}>
    <div class="popup" class:liste={art === 'liste'} class:vorschau={art === 'vorschau'}
         class:gehalten={Boolean(HOEHE[art])}
         class:galerie={art === 'galerie'} class:bild={art === 'bild'} class:mitweg={Boolean(zurueck)}
         style={art === 'werk'
           ? 'width:fit-content;max-width:calc(92vw / var(--stufenfaktor))'
           : art === 'bild'
             ? 'width:calc(94vw / var(--stufenfaktor))'
             : `width:min(${BREITE[art] ?? BREITE.frage}, calc(92vw / var(--stufenfaktor)))`
               + (HOEHE[art] ? `;height:min(${HOEHE[art]}, calc(84vh / var(--stufenfaktor)))` : '')}
         transition:scale={schrumpfen
           ? { duration: 420, start: 0.03, opacity: 0, easing: cubicIn }
           : { duration: 190, start: 0.97 }}>
      <!-- A window whose body carries its own drawn heading passes an
           empty title; a second plain-text title above it would say the
           same thing twice. -->
      {#if zurueck}
        <!-- Sits above the body and outside the title, because a window whose
             body carries its own drawn heading passes no title at all — and
             the way back has to be there either way. -->
        <button class="zurueck" onclick={zurueck} aria-label={t('app.zurueck')} title={t('app.zurueck')}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M15 5 8 12l7 7" />
          </svg>
        </button>
      {/if}
      {#if kopf}
        <!-- A caller-drawn control that rides in the header's top-right corner
             (the picture window hangs its Image-Turbo there). Absolutely
             placed so it never disturbs the title or the back-arrow. -->
        <div class="fensterkopf">{@render kopf()}</div>
      {/if}
      {#if titel || symbol}
        <h3>{@render symbol?.()}{titel}</h3>
      {/if}
      <div class="leib">{@render children?.()}</div>
    </div>
  </div>
{/if}

<style>
  .schleier {
    position: fixed;
    /* The right edge reaches PAST the window on purpose: hidden scrollbars
       are the house rule, but WebKit paints its overlay scrollbar for this
       scroller regardless of the hiding CSS — a grey thumb floating over
       the dialog. Pushed offscreen it can paint where nobody sees it; the
       extra right padding gives the width back, so the dialog stays
       centred on the visible window. */
    inset: 0 -28px 0 0;
    background: rgba(0, 0, 0, 0.45);
    z-index: 70;
    display: flex;
    justify-content: center;
    align-items: flex-start;
    padding: calc(13vh / var(--stufenfaktor)) 44px calc(6vh / var(--stufenfaktor)) 16px;
    overflow-y: auto;
  }
  /* The arrow rides in the top-left corner, and the window makes room for
     it rather than laying it over whatever is there: the catalogue draws its
     own mark exactly in that spot, and an arrow on top of a mark is two
     things fighting for one corner. The room appears only where an arrow
     does, so every window without one looks exactly as it always did. */
  .popup {
    position: relative;
  }
  .popup.mitweg > h3,
  .popup.mitweg > .leib {
    padding-left: 34px;
  }
  .zurueck {
    position: absolute;
    top: 12px;
    left: 12px;
    z-index: 1;
    width: 28px;
    height: 28px;
    box-sizing: border-box;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    border-radius: 99px;
    /* Button glass with its fine edge, like every button on glass. */
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text-leise);
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }
  .zurueck:hover {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
    color: var(--text);
  }
  .popup {
    /* A floating layer: the dense glass of the dropdown lists, so the veil
       and what lies under it shine through; the controls inside step up
       from it onto cards and fields. The blur sits on a layer of its own
       below (next rule): a backdrop filter ON the window would make it the
       containing block of every fixed-positioned list inside it, and a
       dropdown choice would open at the wrong place. */
    background: var(--glass-dropdown);
    isolation: isolate;
    /* 9 — one radius for every edge in the program. A window is no
       different from the controls in it. */
    border-radius: 9px;
    /* The glass edge and a soft fall set the window off, not a bright
       ring. A ring ON the edge (box-shadow), not a border, so the window
       keeps its exact size. */
    box-shadow: 0 0 0 1px var(--glass-button-edge), 0 28px 70px -12px rgba(0, 0, 0, 0.55);
    padding: 16px 18px 14px;
  }
  /* The blur under the window's content: the window is a stacking context
     of its own (isolation above), so -1 lies above its ground and below
     everything in it, and the filter never touches the window itself. */
  .popup::before {
    content: '';
    position: absolute;
    inset: 0;
    z-index: -1;
    border-radius: inherit;
    -webkit-backdrop-filter: blur(16px);
    backdrop-filter: blur(16px);
    pointer-events: none;
  }
  /* A window told to hold a height becomes a column: the title keeps its
     own room at the top and the body takes whatever is left, scrolling
     inside itself. `min-height: 0` is what lets it shrink at all — a flex
     child refuses to go below its content without it, and the box would
     grow past the height it was given. The bar itself is hidden by the
     house rule in global.css, so nothing shows but the text moving. */
  .popup.gehalten {
    display: flex;
    flex-direction: column;
  }
  .popup.gehalten > .leib {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    /* A column too, so a body with a foot — a row of buttons that belongs
       at the bottom edge — can push it there with `margin-top: auto`
       instead of trailing after the text. With more content than fits, the
       auto margin collapses and the whole thing scrolls, exactly as it
       would have without it. */
    display: flex;
    flex-direction: column;
  }
  h3 {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0 0 12px;
    font-size: 16px;
    font-weight: 600;
    flex: none;
  }
  /* Snug under the top frame: a wide pill reads its top gap along its whole
     width, so the gap above must be clearly smaller than the gap beside it
     for the pill to sit IN the corner instead of floating below it. */
  .fensterkopf {
    position: absolute;
    top: 8px;
    right: 15px;
    z-index: 2;
    display: flex;
    align-items: center;
    /* Controls that sit side by side need a seam, or the two read as one
       wide control with a line drawn through it. */
    gap: 8px;
  }

  /* The body. For a question it follows the content; for a list window it is
     the one number that makes them all the same height.

     clamp and not a bare `min(62vh, …)`: in embedded views the browser
     sometimes reports no window height at all, `vh` resolves to 0, and the
     window collapses to a line. The lower bound in pixels keeps it standing
     there too. */
  /* The tall settings window: its veil is `.schleier.weit.liste` (4vh above,
     3vh below), so 93vh is what it leaves — and the frame around the body —
     the popup's own padding, the title and the line under it — takes about
     96 of those pixels. Asking for the rest by subtraction instead of
     guessing a vh number is what keeps it from overflowing on a short
     window: at 790 the old `74vh` wanted 585 where only 558 were free,
     which is why the left column's last entry was cut off. */
  /* The ceiling is 1182 and not 980 because the tabs do not carry the same
     number of switch rows: the field is `flex: 1` in each of them, so every
     row above it comes off the field. Measured with both tabs at a body of
     676 px and again at 980 px: the instruction field
     stood at 82 and 386, the memory field at 284 and 588 — a constant
     difference of 202 px, because both fields grow one for one with the
     body. 980 + 202 = 1182 is therefore the ceiling at which the
     instruction field stands as tall as the memory field stands today. Not
     a chosen number; it follows from the two readings above.
     `calc(93vh - 96px)` still caps it above, so a short window gets exactly
     what it got before and nothing scrolls. */
  .popup.liste .leib {
    height: clamp(440px, calc(93vh / var(--stufenfaktor) - 96px), 1182px);
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  /* A preview window stands higher up and starts lower down than the
     others: a document wants the height, and the drop from the top edge
     that suits a question would take it away on a laptop screen. */
  /* Only the vertical padding changes here. The right side keeps the 44px
     that pay back the 28px this layer is pushed off-screen by — write a plain
     value there and the hidden scrollbar lands back inside the window. */
  .schleier.weit { padding: calc(6vh / var(--stufenfaktor)) 44px calc(5vh / var(--stufenfaktor)) 16px; }
  /* The settings window sits higher and reaches lower than the other wide
     ones: its left column is a list of every section the program has, and
     at 6vh above it the last entry was cut off with 23 pixels missing —
     measured, not guessed. The margin above a window is worth less than a
     column one can read to the end. */
  .schleier.weit.liste { padding: calc(4vh / var(--stufenfaktor)) 44px calc(3vh / var(--stufenfaktor)) 16px; }

  /* Taller than a list window, for the same reason it is wider. */
  .popup.vorschau .leib {
    height: clamp(380px, calc(68vh / var(--stufenfaktor)), 900px);
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  /* The gallery body: one fixed height so the catalogue keeps its measure
     whether four cards stand in it or twelve. The ceiling of 720 matches
     the kind's intended size; the grid scrolls inside, bars invisible. */
  .popup.galerie .leib {
    height: clamp(480px, calc(74vh / var(--stufenfaktor)), 720px);
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  /* The picture window's body is FIXED height, never content-driven — its
     own tabs scroll inside instead. The budget is the viewport MINUS
     everything else that stands between it and the screen edge: `.schleier`
     spends 19vh of its own (13vh top + 6vh bottom, above) — leaving 81vh —
     and `.popup` spends 30px more (its own 16px+14px padding).

     The vh term is divided by --stufenfaktor, the px term is not — that is
     not an oversight. `.schleier`'s own padding is written divided too
     (above), so it costs the same TRUE fraction of the screen at every
     stage; the 81vh here is what is left of the true, un-zoomed viewport
     once `.schleier` has taken its (now correctly constant) share, so it
     divides exactly like a plain viewport height would. `.popup`'s padding
     is plain px and was never divided anywhere: it is meant to grow with
     the interface, the same as every other pixel measurement in the house,
     so it is charged here exactly as it renders.

     `min()`, not `clamp()`: a FLOOR is exactly what clipped the window in
     the first place — a small screen at a large interface stage can leave
     less room than any fixed minimum would demand, and honouring a floor
     over the room actually available is the whole bug. No ceiling either:
     the picture window fills the room on every screen, and a larger one
     gives the pictures more of it. */
  .popup.bild .leib {
    height: calc(81vh / var(--stufenfaktor, 1) - 30px);
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  /* On a narrow screen the fixed body would push everything into a
     letterbox — there the window may grow and the page scrolls. */
  @media (max-width: 720px) {
    .popup.liste .leib { height: auto; }
    .popup.vorschau .leib { height: clamp(320px, 70vh, 560px); }
    .popup.galerie .leib { height: auto; }
    /* On a narrow screen the picture window's body grows with its content
       and the page scrolls, like every other kind at this width. */
    .popup.bild .leib { height: auto; }
  }
</style>
