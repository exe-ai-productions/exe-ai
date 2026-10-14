<script>
  /* One drawing as the first layer of a surface — behind everything the
     surface carries, clipped by the surface's own corner, deaf to
     clicks. The one path for every drawing of the look that carries
     drawings.

     The sheets are inlined rather than loaded through `<img>` or
     `background-image` so their ink follows `currentColor` and can be
     themed by the look that shows them. */
  import gras from '../stil/moune/01_gras.svg?raw'
  import huegel from '../stil/moune/02_huegel.svg?raw'
  import farn from '../stil/moune/03_farn.svg?raw'
  import pusteblume from '../stil/moune/05_pusteblume.svg?raw'

  /* Moune's four drawings with the weight the design gave each one
     (strength 100 % × weight × 0.34, walked to in the design). Moune is the
     one look that carries drawings. */
  const ZEICHNUNGEN = {
    gras: { roh: gras, deckkraft: 0.34 },
    huegel: { roh: huegel, deckkraft: 0.289 },
    farn: { roh: farn, deckkraft: 0.34 },
    pusteblume: { roh: pusteblume, deckkraft: 0.374 },
  }

  let { art } = $props()

  /* An unknown or missing name yields an empty drawing rather than a dead
     window: a surface without its drawing, not a blank app. `hasOwn` so a
     name off the table's prototype chain cannot slip through. */
  const gewaehlt = $derived(
    Object.hasOwn(ZEICHNUNGEN, art) ? ZEICHNUNGEN[art] : { roh: '', deckkraft: 0 },
  )

  /* The sheets carry a style tag written for a page of their own; inlined
     it would reach every element on THIS page, so it is dropped here and
     this component's own style sets the same rule, scoped to these paths.

     The pattern writes its angle brackets with a space class between
     bracket and name, so this file never holds a literal style tag: the
     tooling's block scanner would take it for the component's own style
     block and lose the script around it. */
  const zeichnung = $derived(gewaehlt.roh.replace(/<\s*style[\s\S]*?<\/\s*style>/i, ''))
</script>

<div class="vektorfeld" style:opacity={gewaehlt.deckkraft} aria-hidden="true">
  {@html zeichnung}
</div>

<style>
  .vektorfeld {
    position: absolute;
    inset: 0;
    /* No stacking level of its own: each surface sets one where its
       content is not layered — the surfaces whose content is positioned
       (chat, frame) need none, the others push the drawing to -1 in
       their own rules. */
    /* The surface's own corner clips the drawing — each tile is rounded
       and the drawing must end at that edge. */
    border-radius: inherit;
    overflow: hidden;
    pointer-events: none;
    color: var(--vek);
  }
  .vektorfeld :global(svg) {
    display: block;
    width: 100%;
    height: 100%;
  }
  /* The hairline stays 1.2px at every size, on these paths alone. */
  .vektorfeld :global(svg *) {
    vector-effect: non-scaling-stroke;
  }
</style>
