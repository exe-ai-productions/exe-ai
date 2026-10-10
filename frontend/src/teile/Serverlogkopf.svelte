<script>
  /* The head line of a server's log: an arrow that folds it open, its name,
     and a small button right beside the name that opens it in a window of
     its own. The same line in every server window; what the log holds and
     how it is fetched stays with the window. */
  import Hauszeichen from './Hauszeichen.svelte'
  import { t } from '../lib/texte.svelte.js'

  let { offen = false, onumschalten = null, onauskoppeln = null } = $props()
</script>

<div class="logkopf">
  <button class="klapp" onclick={onumschalten} aria-expanded={offen}>
    <svg class="winkel" class:auf={offen} width="11" height="11" viewBox="0 0 11 11" fill="none"
         stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"
         aria-hidden="true">
      <path d="M4.125 2.75L6.875 5.5L4.125 8.25" />
    </svg>
    {t('modell.protokoll')}
  </button>
  <button class="aus" onclick={onauskoppeln}
          title={t('modell.protokoll_vergroessern')}
          aria-label={t('modell.protokoll_vergroessern')}>
    <Hauszeichen zeichen="auskoppeln" groesse="klein" />
  </button>
</div>

<style>
  .logkopf {
    display: flex;
    align-items: center;
    gap: 10px;
    height: 48px;
  }
  .klapp {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 0;
    border: none;
    background: none;
    color: var(--text);
    font: 500 13px var(--schrift);
    cursor: pointer;
  }
  .winkel {
    flex: none;
    color: var(--text-still);
    transition: transform 0.15s;
  }
  .winkel.auf {
    transform: rotate(90deg);
  }
  @media (prefers-reduced-motion: reduce) {
    .winkel {
      transition: none;
    }
  }
  /* A sign button on the field ground, the small size. */
  .aus {
    flex: none;
    width: 24px;
    height: 24px;
    padding: 0;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 9px;
    background: var(--bg-hoch);
    color: var(--text-leise);
    cursor: pointer;
  }
  .aus:hover {
    background: color-mix(in srgb, var(--text) 6%, var(--bg-hoch));
    color: var(--text);
  }
</style>
