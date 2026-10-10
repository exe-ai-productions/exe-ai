<script>
  /* Mark and lettering as one unit.

     Deliberately **no** single SVG anymore: its viewBox was 300 units
     wide, but the drawing ended at 186. The empty remainder on the right
     belonged to the box and pulled the mark to the left when centering —
     invisible in the header, clearly visible in the empty chat. Putting
     logo and text side by side makes the box as wide as the drawing, on
     every device, no matter how wide the font renders there.

     The measurements come from the old SVG: box 40 units tall, type 20,
     mark 35x28, gap 16. Relative to the font size that is 1.75em wide,
     1.4em tall, 0.8em gap.

     The color is inherited, so it flips along by itself on mode change. */
  /* `mitText = false` shows only the drawing. The watermark behind the
     chat needs that: there the symbol grows to window size, and a
     lettering next to it would be meters tall. As a switch here and not
     as a second drawing elsewhere — there is exactly one wordmark. */
  let { hoehe = 26, zentriert = false, mitText = true } = $props()
</script>

<div class="marke" class:zentriert class:nurzeichen={!mitText} role="img"
     aria-label="Exe AI" style="font-size:{hoehe / 2}px">
  <svg viewBox="0 0 35 28" fill="none" stroke="currentColor"
       stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <rect x="1.35" y="1.35" width="32.3" height="25.3" rx="7.5" stroke-width="2.7" />
    <path d="M9.5 10 L15.5 14.5 L9.5 19" stroke-width="2.5" />
    <path d="M20 19 H 27" stroke-width="2.5" />
  </svg>
  {#if mitText}<span>Exe AI</span>{/if}
</div>

<style>
  .marke {
    display: flex;
    align-items: center;
    gap: 0.8em;
    color: var(--text);
    font-family: var(--schrift);
    font-weight: 600;
    letter-spacing: -0.02em;
    line-height: 1;
    white-space: nowrap;
    user-select: none;
  }
  svg {
    width: 1.75em;
    height: 1.4em;
    flex: none;
    display: block;
    /* The rounded box is drawn flush against the viewBox: the rect sits at
       y 1.35 with a 2.7 stroke, so half the stroke lands exactly on 0 and
       on 28. An SVG clips to its viewport by default, and at the sizes
       this renders at the outermost half pixel of the top and bottom
       stroke falls outside it — the box comes out flat-topped and
       flat-bottomed. Painting past the viewport costs no layout: the
       element's box stays the size it was. */
    overflow: visible;
  }
  /* Where the mark sits centred, the optical centre counts, not the box's.
     The centre that matters runs from the left edge of the drawing to where
     the ink of the last letter actually ends — the advance width carries a
     little air past it that belongs to no glyph. The ink therefore sits left
     of the box's centre, and the block moves right by half that air to
     stand over the input field below.

     Measured in the system face of macOS at 27.5 px type, to an eighth of
     a pixel, ink ending on the I of "AI": the ink starts 0.22 px inside the
     box and ends 1.45 px before its right edge, so its centre lies 0.625 px
     left of the box's — hence 0.023em to the right. Relative, so it holds
     at every size. The value belongs to the lettering and its face: any
     change to the wording has to be measured again rather than guessed.

     Centred, drawing and word also stand closer than in a row of the
     header: 0.45em, so the two read as one sign above the greeting.

     Left-aligned neither applies: there the ink should start at the edge,
     and it does so without compensation. */
  .zentriert {
    gap: 0.45em;
    transform: translateX(0.023em);
  }
  /* Without the lettering there is nothing to compensate and nothing to
     flow around: the drawing fills the box the watermark gives it. The
     viewBox's aspect ratio is preserved in the process. */
  .nurzeichen {
    gap: 0;
    transform: none;
  }
  .nurzeichen svg {
    width: 100%;
    height: 100%;
  }
</style>
