<script>
  /* The chosen day's runs under the calendar: one row per schedule, its
     time (or how often it comes that day), its task, who does it and how
     the latest run went, with a dot in that state's colour. Nothing when
     the day is empty. `gross` is the settings' size. */
  import { leadOf, whoOf } from '../lib/schedulecalendar.svelte.js'

  let { rows, gross = false } = $props()

  const colour = (c) => `var(--${c === 'still' ? 'text-still' : c})`
</script>

{#if rows.length}
  <div class="karte" class:gross>
    {#each rows as row, i (row.cronjob_id || `gone:${i}`)}
      <div class="zeile">
        <div class="was">
          <div class="eins">
            <span class="uhr">{leadOf(row)}</span>
            <span class="aufgabe">{row.task}</span>
          </div>
          <div class="zwei" class:rot={row.failed}>{whoOf(row)} · {row.word}</div>
        </div>
        <span class="punkt" style:background={colour(row.colour)}></span>
      </div>
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
    min-height: 50px;
    padding: 9px 12px;
  }
  .gross .zeile {
    padding: 9px 14px;
  }
  .zeile + .zeile {
    border-top: 1px solid var(--linie);
  }
  .was {
    flex: 1;
    min-width: 0;
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
  .uhr {
    font-variant-numeric: tabular-nums;
    margin-right: 6px;
  }
  .zwei {
    font-size: 11.5px;
    color: var(--text-still);
  }
  .gross .zwei {
    font-size: 12px;
  }
  /* A run that failed is a state, so this one line may carry the colour. */
  .zwei.rot {
    color: var(--rot-text);
  }
  /* Round because it is a dot. */
  .punkt {
    flex: none;
    width: 8px;
    height: 8px;
    border-radius: 50%;
  }
</style>
