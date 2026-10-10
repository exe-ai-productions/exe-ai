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

    Timing: 3.4 s, stroke draw via stroke-dasharray/-offset, breather at
    the end, then the three dots settle in — exactly the grammar of the
    chat loading mark (3.11).
  */
  let { art = 'antwort', text = '', zeit = '', beschriftung = '' } = $props()
</script>

<div class="wartet" aria-label={beschriftung || text || undefined}>
  <svg class="marke" viewBox="0 0 80 64" fill="none" stroke="currentColor"
       stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <!-- EXACTLY uniform: all marks share the same
         outer geometry — frame always x4 y4 72×56 rx15, the eye spans
         the same width and lies on the same center line (y 32). Whoever
         builds a new mark here keeps to these edges. -->
    {#if art === 'einbettung'}
      <!-- A document is being read and embedded: the SAME web-and-points
           sign as the embedding server in Hauszeichen.svelte, scaled to the
           waiting mark's body. The web draws first, then the three points
           settle onto its corners — the lines carry less weight than what
           they connect, exactly as in the still sign. -->
      <path class="strich zug2" d="M12 57 L40 7 L68 44.5 Z" stroke-width="4.5" style="--laenge:170" />
      <path class="strich zug3" d="M12 57 h.01 M40 7 h.01 M68 44.5 h.01" stroke-width="13" style="--laenge:1" />
    {:else if art === 'vision'}
      <!-- Image recognition: the message carried an image. The SAME eye as
           the capability sign in Hauszeichen.svelte, scaled to the waiting
           mark's width — the house has exactly one eye drawing. The pupil is
           an outlined circle like the sign's, drawn as a stroke of its own. -->
      <path class="strich zug2" d="M4 32 C17 11, 63 11, 76 32 C63 53, 17 53, 4 32 Z" stroke-width="5.5" style="--laenge:160" />
      <circle class="strich zug3" cx="40" cy="32" r="11" stroke-width="5" style="--laenge:70" />
    {:else if art === 'verdichtung'}
      <!-- The history is being compressed: the SAME narrowing stack the
           seam in the chat wears (Nachricht.svelte, `.naht`), scaled to the
           waiting mark's body — the house draws one thing once, exactly as
           `einbettung` borrows the embedding server's web and `vision` the
           capability sign's eye.

           It says what it is by DRAWING it: the wide line first, then the
           narrower, then the narrowest. Three strokes of one weight, no
           frame — a frame around them would say "chat", and this is not the
           chat answering, it is the program making room. -->
      <path class="strich rahmen" d="M4 18 H76" stroke-width="5.5" style="--laenge:72" />
      <path class="strich zug2" d="M17.5 32 H62.5" stroke-width="5.5" style="--laenge:45" />
      <path class="strich zug3" d="M31 46 H49" stroke-width="5.5" style="--laenge:18" />
    {:else}
      <!-- Answer: the chat mark, frame with arrow and baseline. -->
      <rect class="strich rahmen" x="4" y="4" width="72" height="56" rx="15"
            stroke-width="5.5" style="--laenge:250" />
      <path class="strich zug2" d="M20 22 L34 32 L20 42" stroke-width="5" style="--laenge:36" />
      <path class="strich zug3" d="M42 42 H 58" stroke-width="5" style="--laenge:16" />
    {/if}
  </svg>
  <span class="tupfen" aria-hidden="true"><i class="t1"></i><i class="t2"></i><i class="t3"></i></span>
  {#if text}<span>{text}</span>{/if}
  {#if zeit}<span class="zeit">{zeit}</span>{/if}
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
    animation: atemzug 3.4s linear infinite;
  }
  @keyframes atemzug {
    0%, 78% { opacity: 1; }
    96%, 100% { opacity: 0; }
  }
  .strich {
    stroke-dasharray: var(--laenge);
    stroke-dashoffset: var(--laenge);
  }
  .rahmen { animation: ziehen1 3.4s cubic-bezier(0.45, 0, 0.25, 1) infinite; }
  .zug2 { animation: ziehen2 3.4s cubic-bezier(0.45, 0, 0.25, 1) infinite; }
  .zug3 { animation: ziehen3 3.4s cubic-bezier(0.45, 0, 0.25, 1) infinite; }
  @keyframes ziehen1 { 0% { stroke-dashoffset: var(--laenge); } 22%, 100% { stroke-dashoffset: 0; } }
  @keyframes ziehen2 { 0%, 18% { stroke-dashoffset: var(--laenge); } 30%, 100% { stroke-dashoffset: 0; } }
  @keyframes ziehen3 { 0%, 28% { stroke-dashoffset: var(--laenge); } 37%, 100% { stroke-dashoffset: 0; } }

  /* The dots breathe out with the drawing, as they did inside it. */
  .tupfen {
    display: inline-flex;
    gap: 3px;
    animation: atemzug 3.4s linear infinite;
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
  .t1 { animation: tupfen1 3.4s cubic-bezier(0.2, 0.9, 0.3, 1) infinite; }
  .t2 { animation: tupfen2 3.4s cubic-bezier(0.2, 0.9, 0.3, 1) infinite; }
  .t3 { animation: tupfen3 3.4s cubic-bezier(0.2, 0.9, 0.3, 1) infinite; }
  @keyframes tupfen1 { 0%, 42% { opacity: 0; transform: scale(0.35); } 50%, 100% { opacity: 1; transform: scale(1); } }
  @keyframes tupfen2 { 0%, 49% { opacity: 0; transform: scale(0.35); } 57%, 100% { opacity: 1; transform: scale(1); } }
  @keyframes tupfen3 { 0%, 56% { opacity: 0; transform: scale(0.35); } 64%, 100% { opacity: 1; transform: scale(1); } }

  /* Whoever can't tolerate motion gets the finished drawing at a standstill. */
  @media (prefers-reduced-motion: reduce) {
    .marke, .marke * { animation: none !important; }
    .tupfen, .tupfen i { animation: none !important; }
    .tupfen i { opacity: 1; }
    .strich { stroke-dashoffset: 0; }
  }
</style>
