<script>
  /* The calendar's face: the date row (‹ the day or the month ›), the switch
     between day and month, then either the day line or the month grid. The
     state is handed in (lib/schedulecalendar.svelte.js), so the tool
     surface and Settings › Cronjobs draw the same calendar on the same
     answer.

     `gross` is the settings' size. `onpick` hears a day clicked in the
     month, with the cell's place on screen, for whoever opens something
     there — the surface passes nothing and only chooses the day. */
  import { t } from '../lib/texte.svelte.js'

  let { kalender, gross = false, onpick = null } = $props()

  const colour = (c) => `var(--${c === 'still' ? 'text-still' : c})`
  const prozent = (minute) => `${(minute / 1440) * 100}%`

  function pick(day, ev) {
    kalender.choose(day)
    onpick?.(day, ev.currentTarget.getBoundingClientRect())
  }
</script>

<div class="kalender" class:gross>
  <div class="datum">
    <button class="mini" onclick={() => kalender.step(-1)}
            aria-label={t(kalender.view === 'day' ? 'cronjobs.day_previous' : 'cronjobs.month_previous')}>‹</button>
    <span class="datumtitel">{kalender.title}</span>
    <button class="mini" onclick={() => kalender.step(1)}
            aria-label={t(kalender.view === 'day' ? 'cronjobs.day_next' : 'cronjobs.month_next')}>›</button>
  </div>
  <div class="wahl" role="radiogroup" aria-label={t('cronjobs.day')}>
    <button role="radio" aria-checked={kalender.view === 'day'} class:an={kalender.view === 'day'}
            onclick={() => kalender.showDay()}>{t('cronjobs.day')}</button>
    <button role="radio" aria-checked={kalender.view === 'month'} class:an={kalender.view === 'month'}
            onclick={() => kalender.showMonth()}>{t('cronjobs.month')}</button>
  </div>

  {#if kalender.view === 'day'}
    <!-- The day: 0 to 24 o'clock, a dot for each schedule that comes once,
         a band for those that come often, and a mark for now on today. -->
    <div class="karte tageslinie">
      <div class="linie" aria-hidden="true">
        <span class="spur"></span>
        {#if kalender.band}
          <span class="band"></span>
        {/if}
        {#each kalender.dots as punkt (punkt.key)}
          <span class="termin" style:left={prozent(punkt.minute)} style:background={colour(punkt.colour)}></span>
        {/each}
        {#if kalender.chosen === kalender.today}
          <span class="jetzt" style:left={prozent(kalender.nowMinute)}></span>
        {/if}
      </div>
      <div class="stunden" aria-hidden="true">
        {#each [0, 6, 12, 18, 24] as stunde (stunde)}
          <span style:left={prozent(stunde * 60)}>{stunde}</span>
        {/each}
      </div>
    </div>
  {:else}
    <!-- A day clicked in the month is chosen, and the month stays: its
         runs stand under the calendar. -->
    <div class="karte monat">
      {#each kalender.weekdayHeads as head, i (i)}
        <span class="wt">{head}</span>
      {/each}
      {#each kalender.grid as day (day)}
        <button class="tag" class:fremd={day.slice(0, 7) !== kalender.shownMonth}
                class:gewaehlt={day === kalender.chosen} class:heutig={day === kalender.today}
                onclick={(ev) => pick(day, ev)}>
          <span class="n">{Number(day.slice(8))}</span>
          <span class="punkte">
            {#each (kalender.shaped[day] || []).slice(0, 3) as row, i (i)}
              <i style:background={colour(row.colour)}></i>
            {/each}
          </span>
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  /* The glass card every group stands on, with its fine edge — the same
     glass in the rail and in the settings, over whatever ground the look
     has; a flat colour would stand as a plate on the gradient. */
  .karte {
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    margin-bottom: 14px;
  }

  /* --- the date row and the switch ---------------------------------- */
  .datum {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 10px;
  }
  .datumtitel {
    flex: 1;
    min-width: 0;
    text-align: center;
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
  }
  .gross .datumtitel {
    font-size: 15px;
  }
  .mini {
    flex: none;
    width: 28px;
    height: 28px;
    display: grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: inherit;
    font-size: 15px;
    cursor: pointer;
  }
  .gross .mini {
    width: 34px;
    height: 34px;
    font-size: 16px;
  }
  .mini:hover {
    background: var(--glass-hover);
  }
  /* The house segment in glass across the full width: a faint glass track,
     the chosen half in button glass with a fine edge. */
  .wahl {
    display: flex;
    gap: 2px;
    padding: 3px;
    margin-bottom: 12px;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
  }
  .wahl button {
    flex: 1 1 0;
    height: 26px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    font: inherit;
    font-size: 12.5px;
    font-weight: 500;
    cursor: pointer;
  }
  .gross .wahl button {
    height: 30px;
    font-size: 13px;
  }
  .wahl button.an {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }

  /* --- the day ------------------------------------------------------ */
  .tageslinie {
    padding: 14px 12px 8px;
  }
  .gross .tageslinie {
    padding: 18px 16px 10px;
  }
  /* The line runs between the 0 and the 24 below it; dots and the mark are
     placed on it by their minute of the day. */
  .linie {
    position: relative;
    height: 14px;
    margin: 0 6px;
  }
  .spur {
    position: absolute;
    left: 0;
    right: 0;
    top: 6px;
    height: 2px;
    border-radius: 9px;
    background: var(--indicator-empty);
  }
  /* A schedule that comes often lies under the line as a band rather than
     as a hundred dots. Blue, because it is standing and switched on. */
  .band {
    position: absolute;
    left: 0;
    right: 0;
    top: 5px;
    height: 4px;
    border-radius: 9px;
    background: color-mix(in srgb, var(--blau) 45%, transparent);
  }
  /* Round because it is a dot. */
  .termin {
    position: absolute;
    top: 2.5px;
    width: 9px;
    height: 9px;
    margin-left: -4.5px;
    border-radius: 50%;
  }
  .jetzt {
    position: absolute;
    top: 0;
    width: 2px;
    height: 14px;
    margin-left: -1px;
    border-radius: 9px;
    background: var(--text);
  }
  .stunden {
    position: relative;
    height: 14px;
    margin: 6px 6px 0;
    font-size: 11px;
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
  }
  .gross .stunden {
    margin-top: 8px;
    font-size: 12px;
  }
  .stunden span {
    position: absolute;
    transform: translateX(-50%);
  }

  /* --- the month ----------------------------------------------------- */
  .monat {
    display: grid;
    grid-template-columns: repeat(7, minmax(0, 1fr));
    gap: 2px;
    padding: 8px 6px;
  }
  .gross .monat {
    padding: 10px 8px;
  }
  .wt {
    text-align: center;
    font-size: 11px;
    color: var(--text-still);
    padding: 2px 0 4px;
  }
  .gross .wt {
    font-size: 12px;
    padding-bottom: 6px;
  }
  .tag {
    height: 34px;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    font: inherit;
    font-size: 11.5px;
    color: var(--text-leise);
    font-variant-numeric: tabular-nums;
    cursor: pointer;
  }
  .gross .tag {
    height: 52px;
    gap: 4px;
    font-size: 14px;
  }
  .tag:hover {
    background: var(--glass-hover);
  }
  .tag.fremd {
    visibility: hidden;
  }
  .tag.gewaehlt {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  .tag.heutig {
    color: var(--text);
    font-weight: 700;
  }
  .punkte {
    display: flex;
    gap: 2px;
    height: 4px;
  }
  .punkte i {
    width: 4px;
    height: 4px;
    border-radius: 50%;
  }
  .gross .punkte {
    gap: 3px;
    height: 5px;
  }
  .gross .punkte i {
    width: 5px;
    height: 5px;
  }
</style>
