<script>
  /* The calendar's face: the date row (the month, "Today" and the two
     chevrons) and the month grid. The state is handed in
     (lib/schedulecalendar.svelte.js), so the tool surface and Settings ›
     Cronjobs draw the same calendar on the same answer. There is only the
     month: a day is read in the list of its runs.

     `gross` is the settings' size: a tile for each day with its number at
     the upper left, the names of its schedules (a stroke in the state's
     colour and the name) and "+n" where they do not all fit; days of the
     neighbouring months dimmed instead of left out; a ring round today;
     the "Today" button. The rail's size has the calendar week in a column
     of its own at the left, the weekdays in two letters (the weekend a shade
     quieter and laid on a faint surface), each number in a circle at the
     middle of its row with the dots of its schedules at a fixed place under
     it — or, from four runs on, the count of them — today as a filled
     circle, the chosen day as a ring, and the days of the neighbouring
     months pale but present.

     `onpick` hears a day clicked in the month, with the cell itself, for
     whoever opens something there and wants to stay beside it — the surface
     passes nothing and only chooses the day. `empty` says that no schedule
     exists at all: a day then shows a plus under the pointer, and a click on
     it goes to `onplus` instead of `onpick`. */
  import { t } from '../lib/texte.svelte.js'
  import Hauszeichen from './Hauszeichen.svelte'

  let { kalender, gross = false, onpick = null, empty = false, onplus = null } = $props()

  /* The names a tile can hold; further schedules are counted in "+n". */
  const NAMES = 3

  /* More runs than this in a day: the rail says how many instead of dots. */
  const DOTS = 3

  const colour = (c) => `var(--${c === 'still' ? 'text-still' : c})`

  function pick(day, ev) {
    kalender.choose(day)
    if (empty && onplus) onplus(day, ev.currentTarget)
    else onpick?.(day, ev.currentTarget)
  }
</script>

<div class="kalender" class:gross>
  <div class="datum">
    <span class="datumtitel">{kalender.title}</span>
    <button class="today" onclick={() => kalender.toToday()}>{t('chat.heute')}</button>
    <button class="mini" onclick={() => kalender.step(-1)} aria-label={t('cronjobs.month_previous')}>
      <Hauszeichen zeichen="chevron_left" groesse={gross ? 16 : 14} />
    </button>
    <button class="mini" onclick={() => kalender.step(1)} aria-label={t('cronjobs.month_next')}>
      <Hauszeichen zeichen="chevron_right" groesse={gross ? 16 : 14} />
    </button>
  </div>

  <!-- A day clicked in the month is chosen, and the month stays. -->
  <div class="karte monat" class:week={!gross}>
    {#if !gross}<span class="kw kopfkw">{t('cronjobs.week_short')}</span>{/if}
    {#each kalender.weekdayShort as head, i (i)}
      <span class="wt" class:weekend={i > 4}>{head}</span>
    {/each}
    {#each kalender.grid as day, i (day)}
      {@const rows = kalender.shaped[day] || []}
      {@const runs = rows.reduce((sum, row) => sum + (Number(row.count) || 1), 0)}
      {#if !gross && i % 7 === 0}<span class="kw">{kalender.weeks[i / 7]}</span>{/if}
      <button class="tag" class:fremd={day.slice(0, 7) !== kalender.shownMonth}
              class:gewaehlt={day === kalender.chosen} class:heutig={day === kalender.today}
              class:weekend={i % 7 > 4}
              class:empty
              onclick={(ev) => pick(day, ev)}>
        <span class="n">{Number(day.slice(8))}</span>
        {#if gross}
          <span class="names">
            {#each rows.slice(0, NAMES) as row, i (i)}
              <span class="entry" title={row.task}>
                <i style:background={colour(row.colour)}></i>
                <span class="text">{row.task}</span>
              </span>
            {/each}
            {#if rows.length > NAMES}
              <span class="more">+{rows.length - NAMES}</span>
            {/if}
          </span>
          {#if empty}
            <span class="plus" aria-hidden="true"><Hauszeichen zeichen="plus" groesse={16} /></span>
          {/if}
        {:else if runs > DOTS}
          <span class="count">{runs}</span>
        {:else}
          <span class="punkte">
            {#each rows.slice(0, DOTS) as row, i (i)}
              <i style:background={colour(row.colour)}></i>
            {/each}
          </span>
        {/if}
      </button>
    {/each}
  </div>
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

  /* --- the date row -------------------------------------------------- */
  .datum {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 10px;
  }
  .datumtitel {
    flex: 1;
    min-width: 0;
    text-align: left;
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
    cursor: pointer;
  }
  .gross .mini {
    width: 34px;
    height: 34px;
  }
  .mini:hover,
  .today:hover {
    background: var(--glass-hover);
  }
  /* "Today": the house button's face, the height of the chevrons beside it. */
  .today {
    flex: none;
    height: 34px;
    padding: 0 14px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: 500 13px var(--schrift);
    cursor: pointer;
  }
  /* The rail's date row is the smaller one: "Today" at the height of the
     chevrons beside it. */
  .kalender:not(.gross) .today {
    height: 28px;
    padding: 0 10px;
    font-size: 12px;
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
  /* The rail's month: the calendar week first, then the seven days. The
     rows stand 2 px apart and the columns none — a day keeps its 2 px at
     either side itself. */
  .monat.week {
    grid-template-columns: 26px repeat(7, minmax(0, 1fr));
    gap: 2px 0;
    padding: 8px 6px 10px;
  }
  .wt {
    text-align: center;
    font-size: 11px;
    color: var(--text-still);
    padding: 2px 0 4px;
  }
  .gross .wt {
    text-align: left;
    font-size: 12px;
    padding: 0 0 6px 8px;
  }
  .week .wt {
    font-weight: 500;
    padding: 4px 0 8px;
  }
  .week .wt.weekend {
    color: color-mix(in srgb, var(--text-still) 70%, transparent);
  }
  /* The calendar week: the head says "KW" or "Wk", each row its number. */
  .kw {
    display: grid;
    place-items: center;
    font-size: 10px;
    color: color-mix(in srgb, var(--text-still) 75%, transparent);
    font-variant-numeric: tabular-nums;
  }
  .kw.kopfkw {
    padding: 4px 0 8px;
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
  /* The settings' day is a tile: the number at its upper left, the names
     under it, each one line. */
  .gross .tag {
    position: relative;
    height: auto;
    min-height: 104px;
    min-width: 0;
    align-items: stretch;
    justify-content: flex-start;
    gap: 5px;
    padding: 6px 7px 7px;
    font-size: 12px;
    text-align: left;
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    background: var(--glass-card);
  }
  .tag:hover {
    background: var(--glass-hover);
  }
  /* A day of the neighbouring month: pale but there, and it can be chosen,
     in the rail as in the settings, where its schedules still stand. */
  .tag.fremd {
    opacity: 0.32;
  }
  .gross .tag.fremd {
    opacity: 0.45;
  }
  .gross .tag.gewaehlt {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  .gross .tag.heutig {
    color: var(--text);
    font-weight: 700;
  }
  /* The rail's day: a fixed row, the number in a circle at its middle and
     the dots at a place of their own under it, so the number never moves
     for a day with runs. The weekend lies on a faint surface of the house
     glass. */
  .week .tag {
    position: relative;
    display: block;
    height: 40px;
    margin: 0 2px;
    border-radius: 10px;
    color: var(--text);
    font-size: 13px;
    font-weight: 500;
  }
  .week .tag:hover {
    background: none;
  }
  .week .tag.weekend {
    background: color-mix(in srgb, var(--glass-hover) 40%, transparent);
  }
  .week .n {
    position: absolute;
    left: 50%;
    top: 5px;
    transform: translateX(-50%);
    width: 26px;
    height: 26px;
    display: grid;
    place-items: center;
    border-radius: 50%;
    line-height: 1;
  }
  .week .tag:hover .n {
    background: var(--glass-hover);
  }
  .week .tag.weekend .n {
    color: var(--text-leise);
  }
  /* Chosen: a ring, drawn as the border of a layer of its own like the one
     round today's number in the settings — a border snaps to whole device
     pixels where an inset shadow does not. */
  .week .tag.gewaehlt .n::after {
    content: '';
    position: absolute;
    inset: 0;
    box-sizing: border-box;
    border: 1.5px solid var(--text-leise);
    border-radius: inherit;
    pointer-events: none;
  }
  /* Today: a filled circle in the look's own ink, the number in its ground
     colour — no colour of its own, readable in a light look and a dark one. */
  .week .tag.heutig .n,
  .week .tag.heutig:hover .n {
    background: var(--text);
    color: var(--bg);
    font-weight: 700;
  }
  /* Today and chosen: the ring stands round the circle, with a gap. */
  .week .tag.heutig.gewaehlt .n::after {
    inset: -3.5px;
  }
  /* The number: a ring round today's. */
  .gross .n {
    align-self: flex-start;
    display: inline-grid;
    place-items: center;
    min-width: 24px;
    height: 24px;
    padding: 0 4px;
    box-sizing: border-box;
    border-radius: 12px;
    font-size: 13px;
    position: relative;
  }
  /* The ring is a border of its own layer: a border snaps to whole device
     pixels where an inset shadow of the same width does not and shows a
     half-lit inner edge at 100 % and 150 %, and a layer of its own leaves
     the size of the number as it was. */
  .gross .tag.heutig .n::after {
    content: '';
    position: absolute;
    inset: 0;
    box-sizing: border-box;
    border: 1.5px solid var(--text);
    border-radius: inherit;
    pointer-events: none;
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
  .week .punkte {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 3px;
    justify-content: center;
    gap: 3px;
  }
  /* From four runs on, the count of them stands where the dots stood. */
  .count {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 1px;
    text-align: center;
    font-size: 9.5px;
    font-weight: 600;
    line-height: 8px;
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
  }
  .names {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }
  /* A stroke in the state's colour and the name, cut where the width ends. */
  .entry {
    display: flex;
    align-items: center;
    gap: 5px;
    min-width: 0;
    font-size: 11.5px;
    color: var(--text);
  }
  .entry i {
    flex: none;
    width: 3px;
    height: 12px;
    border-radius: 2px;
  }
  .entry .text {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .more {
    font-size: 11.5px;
    color: var(--text-still);
    padding-left: 8px;
  }
  /* With no schedule at all a day offers the plus under the pointer. */
  .plus {
    position: absolute;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    opacity: 0;
    color: var(--text-leise);
    transition: opacity 0.12s;
  }
  .tag.empty:hover .plus,
  .tag.empty:focus-visible .plus {
    opacity: 1;
  }
</style>
