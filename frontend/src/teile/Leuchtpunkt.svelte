<script>
  /* A status dot: one filled disc, standing still.

     It used to wear a stroked ring and, in the chat list, three little
     performances — breathing, flashing, trading brightness with its ring.
     In the running program none of that survived the distance to the
     screen: the ring ate the disc's diameter, and the motion made the
     colour harder to read rather than easier. So the dot is now the
     simplest thing that can carry a state — a full disc in the state's own
     colour, big enough to be read at arm's length, with a fine standing
     glow and nothing that moves.

     `farbe` follows the house rule: colour means state, never decoration.

       gruen  done, ready, connected, reachable
       blau   running, active, switched on
       gelb   waiting, and caution
       rot    failed, off, unreachable, dangerous
       still  no state worth a colour — a fact, not a state
       leer   nothing to report. A small quiet disc, not an empty ring:
              it holds a row's geometry without claiming to be a state.

     `groesse` is the diameter of the disc that is drawn, in pixels: a caller
     that says 9 gets a disc of 9. The box the layout sees is two pixels
     wider — one pixel of air on each side.

     `atmet` is off by default, so every existing caller draws exactly what
     it always did — see test_leuchtpunkt.py, which renders the compiled
     component and measures the box, the disc and the class list rather than
     trusting the source. Turned on, the glow breathes between the same two
     states the standing glow already sits between, just further apart — the
     fill itself never moves, which is the one thing the reduced-motion
     header above forbids touching. */
  let { farbe = 'gruen', groesse = 10, atmet = false } = $props()

  /* The box is what the layout sees: the disc and one pixel of air around
     it. */
  const kasten = $derived(groesse + 2)
  const mitte = $derived(kasten / 2)

  /* The disc is as wide as the caller says, except for the dot that says
     nothing: it is drawn two pixels smaller in the same box, because a row
     with nothing to report should not weigh as much as one that has
     something to say. */
  const scheibe = $derived(farbe === 'leer' ? groesse - 2 : groesse)
</script>

<svg
  class="lp"
  class:atmet
  data-farbe={farbe}
  width={kasten}
  height={kasten}
  viewBox="0 0 {kasten} {kasten}"
  aria-hidden="true"
>
  <circle class="scheibe" data-farbe={farbe} cx={mitte} cy={mitte} r={scheibe / 2} />
</svg>

<style>
  .lp {
    display: inline-block;
    flex: none;
    vertical-align: middle;
    /* Without this the glow never leaves the box: an SVG viewport clips its
       own content, and there is one pixel of air around the disc. */
    overflow: visible;
  }
  /* The glow hangs off the whole drawing and not off the circle inside it.
     On the circle it was clipped twice over — once by the SVG viewport and
     once by the filter region, which defaults to a tenth of the shape's own
     box and so cut a 2.5px blur down to well under a pixel. */
  .lp[data-farbe='gruen'] {
    filter: drop-shadow(0 0 2.5px color-mix(in srgb, var(--gruen) 55%, transparent));
  }
  .lp[data-farbe='blau'] {
    filter: drop-shadow(0 0 2.5px color-mix(in srgb, var(--blau) 55%, transparent));
  }
  .lp[data-farbe='gelb'] {
    filter: drop-shadow(0 0 2.5px color-mix(in srgb, var(--gelb) 55%, transparent));
  }
  .lp[data-farbe='rot'] {
    filter: drop-shadow(0 0 2.5px color-mix(in srgb, var(--rot) 55%, transparent));
  }

  /* `atmet`: the same drop-shadow, breathing between a lighter and a
     stronger version of itself — never through the disc's own fill, which
     is the difference from the old ring-and-flash days this file's own
     header warns against. The glow breathes while the fill stays full —
     a dot that drops to half opacity is half invisible half the time. */
  .lp.atmet[data-farbe='gruen'] { animation: atmen-gruen 2.2s ease-in-out infinite; }
  .lp.atmet[data-farbe='blau'] { animation: atmen-blau 2.2s ease-in-out infinite; }
  .lp.atmet[data-farbe='gelb'] { animation: atmen-gelb 2.2s ease-in-out infinite; }
  .lp.atmet[data-farbe='rot'] { animation: atmen-rot 2.2s ease-in-out infinite; }
  @keyframes atmen-gruen {
    0%, 100% { filter: drop-shadow(0 0 3px color-mix(in srgb, var(--gruen) 60%, transparent)); }
    50% { filter: drop-shadow(0 0 7px color-mix(in srgb, var(--gruen) 85%, transparent)); }
  }
  @keyframes atmen-blau {
    0%, 100% { filter: drop-shadow(0 0 3px color-mix(in srgb, var(--blau) 60%, transparent)); }
    50% { filter: drop-shadow(0 0 7px color-mix(in srgb, var(--blau) 85%, transparent)); }
  }
  @keyframes atmen-gelb {
    0%, 100% { filter: drop-shadow(0 0 3px color-mix(in srgb, var(--gelb) 60%, transparent)); }
    50% { filter: drop-shadow(0 0 7px color-mix(in srgb, var(--gelb) 85%, transparent)); }
  }
  @keyframes atmen-rot {
    0%, 100% { filter: drop-shadow(0 0 3px color-mix(in srgb, var(--rot) 60%, transparent)); }
    50% { filter: drop-shadow(0 0 7px color-mix(in srgb, var(--rot) 85%, transparent)); }
  }
  /* Disabling the animation falls back to the standing glow declared above
     — still lit, just not moving. Nothing to redeclare here.

     `[data-farbe]` here, not just `.lp.atmet`: @media narrows WHETHER a
     rule applies, never HOW STRONGLY — the four colour rules above each
     carry two classes plus an attribute selector, and a bare `.lp.atmet`
     is one selector lighter, so it would lose the cascade and the
     animation would keep running under reduced motion regardless of this
     block. Matching the attribute (any value) brings this rule to the
     same specificity, and it wins on being the later declaration. */
  @media (prefers-reduced-motion: reduce) {
    .lp.atmet[data-farbe] { animation: none; }
  }

  .scheibe {
    /* The dot changes state more often than anything else in the bar, and a
       colour that snaps reads as a redraw rather than as a change. */
    transition: fill 0.3s;
  }
  .scheibe[data-farbe='gruen'] { fill: var(--gruen); }
  .scheibe[data-farbe='blau'] { fill: var(--blau); }
  .scheibe[data-farbe='gelb'] { fill: var(--gelb); }
  .scheibe[data-farbe='rot'] { fill: var(--rot); }
  /* A fact, not a state — and so no glow either. */
  .scheibe[data-farbe='still'] { fill: var(--text-still); }
  .scheibe[data-farbe='leer'] { fill: var(--linie-stark); }
</style>
