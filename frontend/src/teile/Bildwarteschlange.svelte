<script>
  /* How many pictures are still to come — the one drawing now plus any
     queued behind it. Shown only while there is at least one, so it takes no
     room when nothing is drawing: the header row reflows around it, and two
     of these (header and the working frame) always say the same number
     because they read the same count.

     The mark is the pictures module's own frame, so the badge and the rail
     button that opens the wall of pictures read as one thing.

     Size and colour come from wherever it is mounted — it stands in the
     foot strip, and that strip sets one size for everything in it. Nothing
     here overrides them; the count is told apart by its weight, not by
     being bigger. */
  import { zustand } from '../lib/zustand.svelte.js'
  import { t } from '../lib/texte.svelte.js'
  import Modulzeichen from './Modulzeichen.svelte'

  let { groesse = 15 } = $props()
</script>

{#if zustand.bildWarteschlange > 0}
  <span class="warteschlange" role="img"
        aria-label={t('bild.warteschlange', { zahl: zustand.bildWarteschlange })}
        title={t('bild.warteschlange', { zahl: zustand.bildWarteschlange })}>
    <span class="zahl">{zustand.bildWarteschlange}</span>
    <Modulzeichen modul="bilder" {groesse} />
  </span>
{/if}

<style>
  /* No frame. This stands in the foot strip, which is one flat line of
     quiet text end to end, and a bordered box in the middle of it reads as
     a control among labels — the same reason the memory figures lost
     theirs. The frame also made this the tallest thing in the strip by 7
     pixels, and since the strip grows upward from a fixed bottom, those 7
     pixels pushed it into the input field whenever a picture was being
     drawn.

     The breathing stays, because what it says is true — "working right
     now", unlike the lamps, which are steady because they only report a
     state. It just moves onto the number, which is the thing the eye goes
     to anyway. A glow needs something to glow; with the box gone, the
     figure is what is left. */
  .warteschlange {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    /* The strip's ink, which it sets for every reading in it. */
    color: inherit;
  }
  .zahl {
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    animation: malpuls 1.6s ease-in-out infinite;
  }
  @keyframes malpuls {
    0%, 100% { color: var(--text); text-shadow: none; }
    50% { color: var(--blau); text-shadow: 0 0 6px rgba(91, 141, 190, 0.5); }
  }
  /* Standing still it takes the colour the pulse peaks at, so what the
     motion said is still said. */
  @media (prefers-reduced-motion: reduce) {
    .zahl { animation: none; color: var(--blau); }
  }
</style>
