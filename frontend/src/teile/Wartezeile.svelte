<script>
  /*
    All waiting marks of the chat in ONE place.

    Row, spacing, font size, mark size and timing live only here — every
    mark with its accompanying text thus inevitably sits in one row and
    always in the same spot. A new mark gets another `art` branch and
    inherits the layout on its own; special sizes or rows of their own
    deliberately don't exist.

    The mark stands on the answers' line, in the place of an entry's dot,
    the way the agent's sign does; beside it the three dots, the word and
    the running time (`zeit`, empty when the word already carries it).
    `nurMarke`: only the mark itself — an answer that already has text under
    way wants no word, no clock and no dots beside it.

    The mark never goes away. Its OUTER form — the frame of an answer, the
    upper line of a compaction, the web of a document, the eye of an image —
    grows out of the line once (0.7 s) and stays; only what is INSIDE it
    draws itself again and again, in rounds of 3.4 s, and fades out as it
    does. So the line that comes down to the mark always ends on something.
    The frame of an answer grows from the spot the line arrives at, the
    middle of its top edge, towards both sides.

    `finished`: the answer is over. The mark stands completely drawn and
    perfectly still, and whatever the caller puts inside (the readings)
    stands beside it.
  */
  let {
    art = 'antwort', text = '', zeit = '', beschriftung = '', nurMarke = false, finished = false,
    children,
  } = $props()
</script>

<div class="wartet" class:fertig={finished} data-art={finished ? 'antwort' : art}
     aria-label={beschriftung || text || undefined}>
  <svg class="marke" viewBox="0 0 80 64" fill="none" stroke="currentColor"
       stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <!-- EXACTLY uniform: all marks share the same
         outer geometry — frame always x4 y4 72×56 rx15, the eye spans
         the same width and lies on the same center line (y 32). Whoever
         builds a new mark here keeps to these edges. The outer form carries
         the class `outline`, what draws inside it sits in `inside`. -->
    {#if !finished && art === 'einbettung'}
      <!-- A document is being read and embedded: the SAME web-and-points
           sign as the embedding server in Hauszeichen.svelte, scaled to the
           waiting mark's body. The web is the outer form; the three points
           settle onto its corners again and again — the lines carry less
           weight than what they connect, exactly as in the still sign. -->
      <path class="strich outline" d="M12 57 L40 7 L68 44.5 Z" stroke-width="4.5" style="--laenge:170" />
      <g class="inside">
        <path class="strich zug3" d="M12 57 h.01 M40 7 h.01 M68 44.5 h.01" stroke-width="13" style="--laenge:1" />
      </g>
    {:else if !finished && art === 'vision'}
      <!-- Image recognition: the message carried an image. The SAME eye as
           the capability sign in Hauszeichen.svelte, scaled to the waiting
           mark's width — the house has exactly one eye drawing. The eye is
           the outer form, the pupil an outlined circle drawn inside it. -->
      <path class="strich outline" d="M4 32 C17 11, 63 11, 76 32 C63 53, 17 53, 4 32 Z" stroke-width="5.5" style="--laenge:160" />
      <g class="inside">
        <circle class="strich zug3" cx="40" cy="32" r="11" stroke-width="5" style="--laenge:70" />
      </g>
    {:else if !finished && art === 'verdichtung'}
      <!-- The history is being compressed: the SAME narrowing stack the
           seam in the chat wears (Nachricht.svelte, `.naht`), scaled to the
           waiting mark's body — the house draws one thing once, exactly as
           `einbettung` borrows the embedding server's web and `vision` the
           capability sign's eye.

           It says what it is by DRAWING it: the wide line first and for
           good, then the narrower and the narrowest again and again. Three
           strokes of one weight, no frame — a frame around them would say
           "chat", and this is not the chat answering, it is the program
           making room. -->
      <path class="strich outline" d="M4 18 H76" stroke-width="5.5" style="--laenge:72" />
      <g class="inside">
        <path class="strich zug2" d="M17.5 32 H62.5" stroke-width="5.5" style="--laenge:45" />
        <path class="strich zug3" d="M31 46 H49" stroke-width="5.5" style="--laenge:18" />
      </g>
    {:else}
      <!-- Answer: the chat mark, frame with arrow and baseline. The frame is
           two halves that meet where the line arrives (middle of the top
           edge) and at the middle of the bottom edge. -->
      <path class="strich outline" d="M40 4 H61 A15 15 0 0 1 76 19 V45 A15 15 0 0 1 61 60 H40"
            stroke-width="5.5" style="--laenge:116" />
      <path class="strich outline" d="M40 4 H19 A15 15 0 0 0 4 19 V45 A15 15 0 0 0 19 60 H40"
            stroke-width="5.5" style="--laenge:116" />
      <g class="inside">
        <path class="strich zug2" d="M20 22 L34 32 L20 42" stroke-width="5" style="--laenge:36" />
        <path class="strich zug3" d="M42 42 H 58" stroke-width="5" style="--laenge:16" />
      </g>
    {/if}
  </svg>
  {#if finished}
    {@render children?.()}
  {:else if !nurMarke}
    <span class="tupfen" aria-hidden="true"><i class="t1"></i><i class="t2"></i><i class="t3"></i></span>
    {#if text}<span>{text}</span>{/if}
    {#if zeit}<span class="zeit">{zeit}</span>{/if}
  {/if}
</div>

<style>
  /* One row of the line, one fixed height whatever face the mark wears
     (it is an answer's last entry, Nachricht.svelte). */
  .wartet {
    position: relative;
    display: flex;
    align-items: center;
    gap: 8px;
    height: 20px;
    font-size: 12.5px;
    line-height: 20px;
    color: var(--text-leise);
    white-space: nowrap;
  }
  /* On the line: its centre on the line's centre, exactly where a dot
     would sit (Nachricht.svelte, `.ereignis::before` and `.punkt`). */
  .marke {
    position: absolute;
    left: -29px;
    top: 0;
    width: 24px;
    height: 20px;
    overflow: visible;
  }
  .strich {
    stroke-dasharray: var(--laenge);
    stroke-dashoffset: var(--laenge);
  }
  /* The outer form grows once and holds the last keyframe. */
  .outline { animation: grow-out 0.7s cubic-bezier(0.3, 0, 0.2, 1) forwards; }
  @keyframes grow-out { to { stroke-dashoffset: 0; } }
  /* The inside starts when the outside has grown, then draws and fades in
     rounds of 3.4 s. Until it starts it is not there: the delay holds the
     base values, which are empty. */
  .inside {
    opacity: 0;
    animation: inside-breathe 3.4s linear 0.7s infinite;
  }
  .zug2 { animation: draw-first 3.4s cubic-bezier(0.45, 0, 0.25, 1) 0.7s infinite; }
  .zug3 { animation: draw-second 3.4s cubic-bezier(0.45, 0, 0.25, 1) 0.7s infinite; }
  @keyframes inside-breathe { 0%, 80% { opacity: 1; } 95%, 100% { opacity: 0; } }
  @keyframes draw-first { 0% { stroke-dashoffset: var(--laenge); } 22%, 100% { stroke-dashoffset: 0; } }
  @keyframes draw-second { 0%, 20% { stroke-dashoffset: var(--laenge); } 32%, 100% { stroke-dashoffset: 0; } }

  /* An answer that is over: everything drawn, nothing moving, the readings
     beside it in the row's own height. */
  .fertig {
    font-size: 12px;
    color: var(--text-still);
  }
  .fertig .marke { color: var(--text-leise); }
  .fertig .strich { stroke-dashoffset: 0; }
  .fertig .outline,
  .fertig .zug2,
  .fertig .zug3 { animation: none; }
  .fertig .inside { opacity: 1; animation: none; }

  /* The dots breathe out in the same rounds as the inside of the mark, and
     start with it, once the outside has grown. */
  @keyframes atemzug {
    0%, 78% { opacity: 1; }
    96%, 100% { opacity: 0; }
  }
  .tupfen {
    display: inline-flex;
    gap: 3px;
    animation: atemzug 3.4s linear 0.7s infinite;
  }
  .tupfen i {
    width: 3px;
    height: 3px;
    border-radius: 50%;
    background: currentColor;
    opacity: 0;
  }
  .zeit {
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
  }
  .t1 { animation: tupfen1 3.4s cubic-bezier(0.2, 0.9, 0.3, 1) 0.7s infinite; }
  .t2 { animation: tupfen2 3.4s cubic-bezier(0.2, 0.9, 0.3, 1) 0.7s infinite; }
  .t3 { animation: tupfen3 3.4s cubic-bezier(0.2, 0.9, 0.3, 1) 0.7s infinite; }
  @keyframes tupfen1 { 0%, 42% { opacity: 0; transform: scale(0.35); } 50%, 100% { opacity: 1; transform: scale(1); } }
  @keyframes tupfen2 { 0%, 49% { opacity: 0; transform: scale(0.35); } 57%, 100% { opacity: 1; transform: scale(1); } }
  @keyframes tupfen3 { 0%, 56% { opacity: 0; transform: scale(0.35); } 64%, 100% { opacity: 1; transform: scale(1); } }

  /* Whoever can't tolerate motion gets the finished drawing at a standstill. */
  @media (prefers-reduced-motion: reduce) {
    .marke, .marke * { animation: none !important; }
    .tupfen, .tupfen i { animation: none !important; }
    .tupfen i { opacity: 1; }
    .strich { stroke-dashoffset: 0; }
    .inside { opacity: 1; }
  }
</style>
