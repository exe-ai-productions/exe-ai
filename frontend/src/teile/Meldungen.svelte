<script>
  import { fly } from 'svelte/transition'
  import { backOut, cubicIn } from 'svelte/easing'
  import Werkzeugzeichen from './Werkzeugzeichen.svelte'
  import { serverLogo } from '../lib/serverlogo.svelte.js'
  import { meldungen, schliesseMeldung, holdNotice, releaseNotice } from '../lib/meldewesen.svelte.js'
  import { KOPIER_ZEICHEN, TICK_SIGN, showTick } from '../lib/markdown.js'
  import { markSeenIfOver } from '../lib/agentenampel.svelte.js'
  import { t, teile } from '../lib/texte.svelte.js'
  import { farbenLaden, farbeVon, lesbar } from '../lib/agentenfarbe.svelte.js'
  import { zustand } from '../lib/zustand.svelte.js'

  /* The notification slides out from the top of the chat and lands with an
     overshoot — backOut goes briefly past the target and springs back.
     On disappearing, upward without springing, otherwise it looks silly.

     It lies between the header and the chat: visible above the history,
     but the bar's menus stay above it. */
  const REIN = { y: -70, duration: 460, easing: backOut }
  const RAUS = { y: -40, duration: 220, easing: cubicIn }

  /* Tool notifications no longer carry an icon of their own: there
     stands the tool icon of the call (globe & co.), drawing itself in a
     loop as long as it runs — same language as the line in the chat. */
  const ZEICHEN = {
    hinweis: 'M12 21a9 9 0 100-18 9 9 0 000 18M12 11v5M12 8h.01',
    erfolg: 'M20 6L9 17l-5-5',
    /* Caution: the triangle, not the circle — a thing that went through
       but not the way it was meant to. Distinct at a glance from both the
       calm round hint and the round error. */
    warnung: 'M12 4L2.5 20h19zM12 10v4M12 17h.01',
    fehler: 'M12 21a9 9 0 100-18 9 9 0 000 18M12 7v6M12 16h.01',
  }

  /* A notice about a run knows whose it was, so the name in front of the
     sentence can be written in that agent's own colour — three notices from
     three agents used to be three identical grey lines. The colours come
     from the agent list, asked for once. */
  $effect(() => {
    farbenLaden()
  })

  /* The name and the rest, split where the reporting module put it: the
     notice names the agent separately, so this is an agreement, not a guess
     at where the sentence begins. Nothing to split, nothing splits. */
  /* What a notice is made of, in pieces. A notice that named a catalogue
     key gets split ON the template's braces (lib/texte.svelte.js) — what
     was put in at the last moment is then known exactly, not guessed from
     the finished sentence. Everything else is one piece and reads as it
     always did. */
  function stuecke(meldung) {
    if (!meldung.schluessel) return [{ fest: meldung.text }]
    return teile(meldung.schluessel, meldung.werte)
  }

  /* The cross is a hand: a notice about a run that is over, closed by it,
     counts as that run having been looked at, exactly as opening its report
     does. A clock closing it, or a fourth notice pushing it out, is not. */
  function closeByHand(meldung) {
    if (meldung.auftragId) markSeenIfOver(meldung.auftragId)
    schliesseMeldung(meldung.id)
  }

  /* Over the chat the stack begins 46 px under the edge of the tile; over a
     page with a head of its own (and over the studio) it begins under that
     head: the page hands over the edge it keeps free (lib/noticeStart.js),
     measured in the browser's pixels, and the zoom of the window, if there
     is one, is taken out here. */
  let stapelKnoten = $state(null)
  let unterKopf = $state(null)
  $effect(() => {
    const unten = zustand.menuHeadBottom
    if (unten == null || !stapelKnoten) {
      unterKopf = null
      return
    }
    const rahmen = stapelKnoten.getBoundingClientRect()
    const faktor = stapelKnoten.offsetWidth ? rahmen.width / stapelKnoten.offsetWidth : 1
    unterKopf = Math.max(0, Math.ceil((unten - rahmen.top) / faktor) + 8)
  })

  /* A mouse on the card holds its clock (a finger has no "on": a tap would
     hold the card until the next tap elsewhere). */
  /* The whole sentence goes on the clipboard (a chat's notice: its name and the
     beginning of the answer, one line each); the tick the code block's copy
     button wears is the answer, no second notice says "copied". */
  function copyNotice(ereignis, meldung) {
    const button = ereignis.currentTarget
    const text = meldung.heading ? [meldung.heading, meldung.text].filter(Boolean).join('\n') : meldung.text
    navigator.clipboard.writeText(text).then(() => showTick(button), () => {})
  }

  function geteilt(meldung) {
    const name = meldung.agent || ''
    if (!name || !meldung.text.startsWith(name)) return null
    const farbe = lesbar(farbeVon(name))
    if (!farbe) return null
    return { name, rest: meldung.text.slice(name.length), farbe }
  }
</script>

<div class="stapel" role="status" aria-live="polite" bind:this={stapelKnoten}
     style:padding-top={unterKopf != null ? `${Math.max(46, unterKopf)}px` : null}>
  {#each meldungen.liste as meldung (meldung.id)}
    <!-- Not `teile`: that is the splitter this file imports, and a
         const of that name inside the block hides it from anything
         written here later. -->
    {@const namensteil = geteilt(meldung)}
    <div class="meldung {meldung.art}" in:fly={REIN} out:fly={RAUS}
         onpointerenter={(ereignis) => { if (ereignis.pointerType === 'mouse') holdNotice(meldung.id) }}
         onpointerleave={() => releaseNotice(meldung.id)}>
      <span class="zeichen">
        {#if meldung.art === 'werkzeug'}
          <Werkzeugzeichen name={meldung.werkzeug} server={meldung.server} logo={serverLogo(meldung.server)} laeuft={true} />
        {:else}
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d={ZEICHEN[meldung.art] ?? ZEICHEN.hinweis} />
          </svg>
        {/if}
      </span>
      <!-- The agent's name in its own colour, the sentence behind it as it
           is. Without an agent, or without a colour, the whole line stands
           exactly as it did. -->
      <!-- The agent's name in its own colour, everything else in pieces:
           what was put in stands in the fixed-width face, the sentence
           around it does not. -->
      {#if meldung.heading}
        <!-- Two lines, one line each: what it is about (a chat's name) over the
             beginning of what happened. Set as text, never as markup. -->
        <span class="text two-lines">
          <span class="chat-name">{meldung.heading}</span>
          {#if meldung.text}<span class="answer-start">{meldung.text}</span>{/if}
        </span>
      {:else}
      <span class="text">{#if namensteil}<span style="color:{namensteil.farbe}">{namensteil.name}</span>{namensteil.rest}{:else}{#each stuecke(meldung) as stueck}{#if stueck.wert}<span class="gesetzt">{stueck.wert}</span>{:else}{stueck.fest}{/if}{/each}{/if}</span>
      {/if}
      <button class="copy" title={t('nachricht.kopieren')} aria-label={t('nachricht.kopieren')}
              onclick={(ereignis) => copyNotice(ereignis, meldung)}>{@html KOPIER_ZEICHEN}{@html TICK_SIGN}</button>
      <button class="zu" onclick={() => closeByHand(meldung)} aria-label={t('app.schliessen')}>
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
      </button>
    </div>
  {/each}
</div>

<style>
  .stapel {
    /* Seen while a menu page hides the chat it lives in. */
    visibility: visible;
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    z-index: 25;
    display: flex;
    flex-direction: column;
    gap: 8px;
    align-items: center;
    /* Clear of the camera notch: on a fullscreen notebook the first
       12 px sit under the housing, and a toast that starts there is a
       toast half swallowed. */
    padding-top: 46px;
    pointer-events: none;
  }
  /* Borderless and
     raised, outside the stroke of the chat mark — as a ring ON the edge,
     so the card stays exactly the same size. It hangs off var(--text)
     and is thus light in dark mode and black in light mode, like the
     mark. The kind's color lives solely in the icon, no colored edge
     anymore. */
  /* THE NOTICE'S OWN MEASUREMENTS, all of them, in one place.

     They used to be scattered: the status icons carried a 15 written into
     their markup, the tool icon brought its own 26 from a different file
     entirely (Werkzeugzeichen.svelte), and nothing here said what size an
     icon in a notice is. So one of the five hung a head taller than the
     rest and nobody could see where to fix it. The notice says it now, for
     every icon in it. */
  .meldung {
    --zeichen: 20px;
    /* One width for every notice. Growing with the text made a stack of
       them ragged down the left AND the right, and a short one put its
       cross alone at the far end of an empty row. */
    --breite: 460px;

    display: flex;
    /* Centred, not top-aligned: the icon sits in the middle of however many
       lines the sentence takes. Aligned to the top it hung under the first
       line the moment a notice ran to two. */
    align-items: center;
    gap: 9px;
    width: min(var(--breite), calc(100vw - 32px));
    /* It floats like a menu: the dense glass of the dropdown lists, blurred,
       with the glass edge as a ring ON the edge and a soft fall, no frame —
       the ring keeps the card its exact size. */
    background: var(--glass-dropdown);
    -webkit-backdrop-filter: blur(16px);
    backdrop-filter: blur(16px);
    border-radius: 9px;
    padding: 12px 15px 12px 13px;
    font-size: 13px;
    line-height: 1.45;
    box-shadow: 0 0 0 1px var(--glass-button-edge), 0 18px 40px -8px rgba(0, 0, 0, 0.55);
    pointer-events: auto;
  }
  /* One box for every icon, whatever it draws. The drawing is scaled into
     it, so no icon can bring a size of its own any more — which is exactly
     what the tool icon did. */
  .zeichen {
    flex: none;
    display: grid;
    place-items: center;
    width: var(--zeichen);
    height: var(--zeichen);
  }
  .zeichen :global(svg) {
    display: block;
    width: 100%;
    height: 100%;
  }
  .hinweis .zeichen {
    color: var(--text-leise);
  }
  .erfolg .zeichen {
    color: var(--gruen);
  }
  /* Saved, but not the whole way — the house colour for "careful". Without
     a rule of its own the mark took the row's ink and read like a passing
     remark, which is the one thing this message must not do. */
  .warnung .zeichen {
    color: var(--gelb);
  }
  .fehler .zeichen {
    color: var(--rot);
  }
  /* Nothing here: a tool mark carries its own colour now, wherever it is
     drawn (Werkzeugzeichen.svelte). Said twice it would drift. */
  .text {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
    /* Centred, because a short sentence in a fixed-width box otherwise sits
       hard left with the whole width empty beside it. */
    text-align: center;
    /* The room of the copy button beside the cross, taken on this side too,
       so the centred sentence keeps the same margin left and right. */
    padding-left: calc(var(--zeichen) + 9px);
  }
  /* At most two lines; a longer sentence ends the second one in an ellipsis.
     The whole sentence is one press of the copy button away. The notice of a
     finished chat below keeps its own two lines. */
  .text:not(.two-lines) {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    overflow: hidden;
  }
  /* A notice with a name over its sentence: both lines one line high, each
     ending in an ellipsis where it is too long. */
  .text.two-lines {
    display: flex;
    flex-direction: column;
    /* Two lines high even when the answer has no words to show. */
    min-height: 2.9em;
  }
  .two-lines .chat-name,
  .two-lines .answer-start {
    display: block;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .two-lines .chat-name {
    font-weight: 600;
    color: var(--text);
  }
  .two-lines .answer-start {
    color: var(--text-leise);
  }
  /* What was put in at the last moment: a file name, a path, a count — set
     into the sentence in the house face with even digits, weight to set it
     apart. Never the tool face: a path or a count is not a tool. */
  .gesetzt {
    font-family: var(--schrift);
    font-variant-numeric: tabular-nums;
    font-weight: 600;
  }
  /* As wide as the icon opposite it, so the centred sentence has the same
     margin on both sides — off by those few pixels it reads as almost
     centred, which is worse than not centred at all.

     Invisible until the pointer is on the notice: a cross standing alone at
     the far end of a short sentence was the hole in the row that made a
     fixed width look broken. Never hidden from a keyboard or a reader —
     opacity, not display, and it comes back on focus. */
  .zu,
  .copy {
    flex: none;
    border: none;
    background: none;
    color: var(--text-still);
    cursor: pointer;
    padding: 0;
    width: var(--zeichen);
    height: var(--zeichen);
    display: grid;
    place-items: center;
    border-radius: 9px;
    opacity: 0;
    transition: opacity 0.12s, color 0.12s;
  }
  .meldung:hover .zu,
  .meldung:hover .copy,
  .zu:focus-visible,
  .copy:focus-visible {
    opacity: 1;
  }
  /* A screen with a finger has no hover: the cross stays in sight. */
  @media (hover: none), (any-pointer: coarse) {
    .zu,
    .copy { opacity: 1; }
  }
  .zu:hover,
  .copy:hover {
    color: var(--text);
  }
  /* The copy mark and the tick of a code block share one cell and cross-fade,
     with the duration the code block takes. */
  .copy :global(svg) {
    grid-area: 1 / 1;
    transition: opacity 0.18s;
  }
  .copy :global(.code-tick) { opacity: 0; }
  .copy:global(.copied) { color: var(--text); }
  .copy:global(.copied) :global(.code-tick) { opacity: 1; }
  .copy:global(.copied) :global(svg:first-child) { opacity: 0; }
</style>
