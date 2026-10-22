<script>
  /* What holds a Word document, a spreadsheet or a presentation: the way a
     PDF is held (PdfFrame.svelte) — it fills its holder, rolls inside itself
     with no bar on show, wears the holder's corners and says "reading" until
     the file stands, or what any failure says. The three views put their
     drawing in as `children`.

     Whatever holds this is positioned and has a size of its own. */
  import { t } from '../lib/texte.svelte.js'

  let { host = $bindable(null), phase = 'reading', name = '', children } = $props()
</script>

<div class="office" bind:this={host} tabindex="0" role="document" aria-label={name}>
  {#if phase === 'failed'}
    <p class="note failure">{t('fehler.allgemein')}</p>
  {:else if phase === 'reading'}
    <p class="note">{t('nachricht.dokument_liest')}</p>
  {/if}
  {@render children?.()}
</div>

<style>
  .office {
    position: absolute;
    inset: 0;
    overflow: auto;
    border-radius: inherit;
    background: var(--bg-hoch);
    outline: none;
  }
  .note {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    margin: 0;
    color: var(--text-still);
    font-size: 12.5px;
    pointer-events: none;
  }
  .note.failure { color: var(--rot-text); }
</style>
