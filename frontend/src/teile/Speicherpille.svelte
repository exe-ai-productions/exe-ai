<!-- How much of the machine's one pool is in use, as "39 / 64 GB". It
     shows the MACHINE's memory, not this program's — the honest ceiling for
     any model plan on shared-memory hardware.

     It was a pill with a filling bar behind the figures while it stood in
     the header. Down in the foot strip it is figures and nothing else: the
     strip is 10.5px of quiet text end to end, and a bordered, filled box in
     the middle of it read as a control among labels.

     The figures stay quiet however full the machine gets: they are a
     reading, not a warning, and no colour of their own sits in the strip.
     Whole gigabytes only: a tenth flickering every two seconds moved the
     centred strip left and right, and nobody plans a model to the tenth. -->
<script>
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { pollWithoutOverlap } from '../lib/pollWithoutOverlap.js'
  import { t } from '../lib/texte.svelte.js'

  let belegt = $state(null)
  let gesamt = $state(null)

  async function lesen() {
    try {
      const m = await api.speicherBlick()
      belegt = m.belegt_gb
      gesamt = m.gesamt_gb
    } catch {
      /* Leave the last reading standing rather than blinking to blank. */
    }
  }

  onMount(() => {
    lesen()
    return pollWithoutOverlap(lesen, 2000)
  })

</script>

{#if gesamt != null}
  <span class="wert" title={t('kopf.speicher_titel')}
    >{belegt != null ? Math.round(belegt) : '-'} / {Math.round(gesamt)} GB</span
  >
{/if}

<style>
  /* Monospace, because the left figure changes every few seconds and a
     proportional one would make the whole strip twitch as the digits
     change width. Inherits its size and colour from the strip — it is one
     reading among the others, not the loud one. */
  .wert {
    flex: none;
    font-family: var(--schrift-fest);
    font-weight: 500;
    white-space: nowrap;
  }
</style>
