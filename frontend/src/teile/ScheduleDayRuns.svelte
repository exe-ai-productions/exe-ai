<script>
  /* The chosen day's runs: one row per schedule, its time (or how often it
     comes that day), its task, who does it and how the latest run went, with
     a dot in that state's colour. Nothing when the day is empty. `gross` is
     the settings' size: the time stands in a column of its own. `onopen`
     makes a row a button with a chevron (the pop-up at the day opens the
     schedule's settings from it); a row of a schedule that is gone has
     nowhere to lead and stays a plain row. */
  import { leadOf, whoOf } from '../lib/schedulecalendar.svelte.js'
  import Hauszeichen from './Hauszeichen.svelte'

  let { rows, gross = false, onopen = null } = $props()

  const colour = (c) => `var(--${c === 'still' ? 'text-still' : c})`
</script>

{#snippet inhalt(row)}
  <span class="uhr">{leadOf(row)}</span>
  <span class="was">
    <span class="eins">{row.task}</span>
    <span class="zwei">{whoOf(row)} · <span class:rot={row.failed}>{row.word}</span></span>
  </span>
  <span class="punkt" style:background={colour(row.colour)}></span>
{/snippet}

{#if rows.length}
  <div class="karte" class:gross>
    {#each rows as row, i (row.cronjob_id || `gone:${i}`)}
      {#if onopen && row.cronjob_id}
        <button class="zeile open" onclick={() => onopen(row)}>
          {@render inhalt(row)}
          <span class="arrow"><Hauszeichen zeichen="chevron_right" groesse={14} /></span>
        </button>
      {:else}
        <div class="zeile">
          {@render inhalt(row)}
        </div>
      {/if}
    {/each}
  </div>
{/if}

<style>
  /* Glass with its fine edge, the same in the rail and in the settings. */
  .karte {
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    margin-bottom: 14px;
    overflow: hidden;
  }
  .zeile {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    min-height: 50px;
    padding: 9px 12px;
    box-sizing: border-box;
    border: none;
    background: none;
    color: var(--text);
    font: inherit;
    text-align: left;
  }
  .gross .zeile {
    padding: 9px 14px;
  }
  .zeile + .zeile {
    border-top: 1px solid var(--linie);
  }
  .zeile.open {
    cursor: pointer;
    transition: background 0.12s;
  }
  .zeile.open:hover {
    background: var(--glass-hover);
  }
  /* The time of day, or how often: a column of its own where the settings
     draw it, so the tasks stand under each other. */
  .uhr {
    flex: none;
    font-variant-numeric: tabular-nums;
    font-size: 13px;
  }
  .gross .uhr {
    width: 44px;
    font-size: 14px;
  }
  .was {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .eins,
  .zwei {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .eins {
    font-size: 13px;
    color: var(--text);
  }
  .gross .eins {
    font-size: 14px;
  }
  .zwei {
    font-size: 11.5px;
    color: var(--text-still);
  }
  .gross .zwei {
    font-size: 12px;
  }
  /* A run that failed is a state, so the one word of it may carry the colour;
     who did it stays grey. */
  .zwei .rot {
    color: var(--rot-text);
  }
  /* Round because it is a dot. */
  .punkt {
    flex: none;
    width: 8px;
    height: 8px;
    border-radius: 50%;
  }
  .arrow {
    flex: none;
    display: inline-flex;
    color: var(--text-still);
  }
</style>
