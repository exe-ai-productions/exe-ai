<!--
  The head of a kit: a chevron that folds it, the word, how many of its parts
  are there, and what is still missing. One head for every place a kit is
  shown, so the two cannot drift apart.

  `there` and `all` count the parts; `there` left out shows no count.
  `countRight` moves the count to the right end; `rest` is a short text on
  what is missing, and always stands there.
-->
<script>
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import { t } from '../lib/texte.svelte.js'

  let { open = false, there = null, all = 0, countRight = false, rest = '', onToggle } = $props()
</script>

<button class="kitkopf tafelkopf" aria-expanded={open} onclick={() => onToggle?.()}>
  <svg class="winkel" class:auf={open} width="11" height="11" viewBox="0 0 11 11" fill="none"
       stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"
       aria-hidden="true">
    <path d="M4.125 2.75L6.875 5.5L4.125 8.25" />
  </svg>
  <span>{t('bildserver.bausatz')}</span>
  {#if there != null}
    <span class="stand" class:rechts={countRight}>
      <Leuchtpunkt farbe={there === all ? 'gruen' : 'still'} groesse={10} />
      {t('bildserver.teile_da', { da: there, alle: all })}
    </span>
  {/if}
  {#if rest}<span class="rest">{rest}</span>{/if}
</button>

<style>
  .kitkopf {
    width: 100%;
    height: 26px;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0;
    border: none;
    background: none;
    color: var(--text);
    cursor: pointer;
    text-align: left;
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
  .stand {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    font-weight: 400;
    letter-spacing: 0;
    text-transform: none;
    color: var(--text-still);
  }
  .stand.rechts,
  .rest {
    margin-left: auto;
  }
  .rest {
    font: 500 12px var(--schrift);
    letter-spacing: 0;
    text-transform: none;
    color: var(--text-still);
  }
</style>
