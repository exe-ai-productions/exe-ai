<script>
  /* The answer of a check for a newer build that found none: the house tick
     in a circle and the word beside it, in the colour of "ready". One mark
     for every server window that offers the check, so the two never drift
     into two different ticks. */
  import { t } from '../lib/texte.svelte.js'
</script>

<span class="uptodate">
  <span class="ring" aria-hidden="true">
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4 12.5 L9.5 18 L20 6.5" />
    </svg>
  </span>{t('bildserver.aktuell')}
</span>

<style>
  .uptodate {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--gruen);
  }
  .ring {
    display: inline-grid;
    place-items: center;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    border: 1px solid currentColor;
  }
</style>
