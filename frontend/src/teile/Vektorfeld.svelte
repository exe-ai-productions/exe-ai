<script>
  /* One drawing as the first layer of a surface — behind everything the
     surface carries, clipped by the surface's own corner, deaf to
     clicks. The one path for every drawing of every look that carries
     drawings.

     The sheets are inlined rather than loaded through `<img>` or
     `background-image` so their ink follows `currentColor` and can be
     themed by the look that shows them. */
  import gras from '../stil/moune/01_gras.svg?raw'
  import huegel from '../stil/moune/02_huegel.svg?raw'
  import farn from '../stil/moune/03_farn.svg?raw'
  import pusteblume from '../stil/moune/05_pusteblume.svg?raw'
  import dunes from '../stil/pearl/01_dunes.svg?raw'
  import waves from '../stil/pearl/02_waves.svg?raw'
  import shell from '../stil/pearl/03_shell.svg?raw'
  import oyster from '../stil/pearl/04_oyster.svg?raw'
  import clouds from '../stil/heaven/01_clouds.svg?raw'
  import balloons from '../stil/heaven/02_balloons.svg?raw'
  import birds from '../stil/heaven/03_birds.svg?raw'
  import paperPlane from '../stil/heaven/04_paper_plane.svg?raw'
  import wuerfel from '../stil/exe/01_wuerfel.svg?raw'
  import sternnetz from '../stil/darkmatter/01_sternnetz.svg?raw'

  /* Moune's four drawings with the weight the design gave each one
     (strength 100 % × weight × 0.34, walked to in the design); Pearl and
     Heaven take the same weights on the same surfaces, so the three looks
     with drawings read alike. */
  const ZEICHNUNGEN = {
    gras: { roh: gras, deckkraft: 0.34 },
    huegel: { roh: huegel, deckkraft: 0.289 },
    farn: { roh: farn, deckkraft: 0.34 },
    pusteblume: { roh: pusteblume, deckkraft: 0.374 },
    /* Pearl's shore: dune grass along the foot of the frame, wave lines
       in the right column below its head, a nautilus and a fan shell
       standing at the foot of the chat, an open oyster whose pearls drift
       along the input bar. */
    dunes: { roh: dunes, deckkraft: 0.34 },
    waves: { roh: waves, deckkraft: 0.289 },
    shell: { roh: shell, deckkraft: 0.34 },
    oyster: { roh: oyster, deckkraft: 0.374 },
    /* Heaven's sky: a bank of clouds along the foot of the frame, hot-air
       balloons in the right column — clear of its head and of the clouds
       at its foot —, a flock of birds rising across the chat, a paper
       plane on its dotted path in the input bar. */
    clouds: { roh: clouds, deckkraft: 0.34 },
    balloons: { roh: balloons, deckkraft: 0.289 },
    birds: { roh: birds, deckkraft: 0.34 },
    'paper-plane': { roh: paperPlane, deckkraft: 0.374 },
    /* Exe's one drawing, on the frame alone: stairs of cubes at both feet
       of the window, under the side rails, rising and fading to nothing.
       Faint — a texture of the ground, not a picture — at the weight the
       design set (18 % of the ink). Drawn by a script, so every cube is
       the same solid: its faces carry the frame's colour and hide what
       stands behind them. */
    wuerfel: { roh: wuerfel, deckkraft: 0.18 },
    /* Dark Matter's one drawing, on the frame alone, at the same weight: a
       net of lines with a four-pointed star at every knot, over the whole
       frame — a sky, showing faintly through the chat's glass. */
    sternnetz: { roh: sternnetz, deckkraft: 0.18 },
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
