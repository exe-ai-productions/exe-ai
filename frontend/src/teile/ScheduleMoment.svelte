<script>
  /* The day and the time of day of a schedule, as the house's own fields
     instead of the browser's date and time masks (`mode`).

     `day` shows the chosen day in a field; the field opens a month — the
     month grid of the schedule calendar, Monday to Sunday, with the arrows
     for the month before and after, today set apart and the chosen day lit —
     and a day clicked is the answer.

     `time` is a field of text that opens a list of the times of day, a
     quarter of an hour apart (`TIMES`, lib/terminform.js). The list is a
     help, not a limit: a time such as 9:07 is typed, and read the way the
     schedule reads it (`readTime`). What cannot be read is marked invalid and
     is no value — the form stays unsaveable until there is one. A press on
     another field shuts an open list, so two never stand open together.

     The list stands in the top layer, as a popover of its own, so no pop-up
     around the field can cut it off; it is placed under the field by hand
     (above where the room below is short), the way the house's selection
     field places its list. It shuts on a click or a key outside it, on
     Escape (which is the list's own: the pop-up holding the form does not
     hear it) and when the page moves from under it. */
  import { t } from '../lib/texte.svelte.js'
  import { ScheduleCalendar, dateOf } from '../lib/schedulecalendar.svelte.js'
  import { TIMES, readTime } from '../lib/terminform.js'
  import Hauszeichen from './Hauszeichen.svelte'

  let { mode, value = $bindable(''), label = '', id = undefined } = $props()

  let open = $state(false)
  let place = $state(null)
  let pop = $state(null)
  let anchor = $state(null)
  let input = $state(null)
  let walked = $state(-1)

  /* The month on show is a calendar of its own, only for its grid, its
     titles and its arrows: nothing is loaded for it. */
  const month = new ScheduleCalendar()

  /* What is typed in the time field, and whether it can be read. */
  let typed = $state(value)
  const invalid = $derived(mode === 'time' && typed.trim() !== '' && readTime(typed) === null)
  $effect(() => {
    if (mode === 'time' && value !== (readTime(typed) ?? '')) typed = value
  })

  const dayText = $derived(
    value
      ? dateOf(value).toLocaleDateString(month.locale, {
          day: 'numeric', month: 'short', year: 'numeric',
        })
      : '',
  )

  const GAP = 4
  const EDGE = 12
  const HEIGHT = { day: 300, time: 260 }
  const MIN_WIDTH = { day: 252, time: 0 }

  function show() {
    open = true
    if (mode === 'day') month.shownMonth = (value || month.today).slice(0, 7)
    else walked = Math.max(0, indexNear(readTime(typed) ?? value))
  }

  function shut() {
    open = false
    walked = -1
  }

  function toggle() {
    if (open) shut()
    else show()
  }

  /* The entry of the list a time stands at, or just before when it is not
     in the list — 9:07 stands at 9:00. */
  function indexNear(time) {
    if (!time) return 0
    return Math.max(0, TIMES.findLastIndex((entry) => entry <= time))
  }

  /* Placed under the field, as wide as the field (a month at least as wide
     as it needs), over it where the room under it is short. */
  function placed() {
    if (!pop || !anchor) return
    const box = anchor.getBoundingClientRect()
    const width = Math.max(box.width, MIN_WIDTH[mode])
    const left = Math.max(EDGE, Math.min(box.left, window.innerWidth - width - EDGE))
    const below = window.innerHeight - box.bottom - GAP - EDGE
    const above = box.top - GAP - EDGE
    const down = below >= Math.min(HEIGHT[mode], 160) || below >= above
    pop.style.left = `${left}px`
    pop.style.width = `${width}px`
    pop.style.maxHeight = `${Math.max(down ? below : above, 0)}px`
    if (down) {
      pop.style.top = `${box.bottom + GAP}px`
      pop.style.bottom = 'auto'
    } else {
      pop.style.top = 'auto'
      pop.style.bottom = `${window.innerHeight - box.top + GAP}px`
    }
  }

  $effect(() => {
    if (!open || !pop) return
    if (!pop.matches(':popover-open')) pop.showPopover()
    placed()
    /* A press outside the field and its list shuts the list; the page
       scrolling away from under it, or a resize, takes it away. */
    const outside = (event) => {
      if (pop?.contains(event.target) || anchor?.contains(event.target)) return
      shut()
    }
    const away = (event) => {
      if (event.type === 'scroll' && pop?.contains(event.target)) return
      if (event.type === 'scroll' && !(event.target instanceof Node && event.target.contains(anchor))) return
      shut()
    }
    window.addEventListener('pointerdown', outside, true)
    window.addEventListener('scroll', away, true)
    window.addEventListener('resize', away)
    return () => {
      window.removeEventListener('pointerdown', outside, true)
      window.removeEventListener('scroll', away, true)
      window.removeEventListener('resize', away)
    }
  })

  /* The time list opens on the chosen time and the walk keeps it in view. */
  $effect(() => {
    if (!open || mode !== 'time' || walked < 0 || !pop) return
    pop.querySelector(`[data-entry="${walked}"]`)?.scrollIntoView({ block: 'nearest' })
  })

  function pickDay(day) {
    value = day
    shut()
    anchor?.querySelector('button')?.focus()
  }

  function pickTime(time) {
    value = time
    typed = time
    shut()
    input?.focus()
  }

  /* What is typed is the value as soon as it can be read, and none until
     then. */
  function typing() {
    value = readTime(typed) ?? ''
  }

  /* Leaving the field sets a readable time in its own form ("9:07" becomes
     "09:07"). */
  function settle() {
    const read = readTime(typed)
    if (read) typed = read
  }

  function timeKeys(event) {
    if (event.isComposing || event.keyCode === 229) return
    const { key } = event
    if (key === 'Escape' && open) {
      event.stopPropagation()
      event.preventDefault()
      shut()
      return
    }
    if (key === 'ArrowDown' || key === 'ArrowUp') {
      event.preventDefault()
      if (!open) show()
      else walked = Math.min(TIMES.length - 1, Math.max(0, walked + (key === 'ArrowDown' ? 1 : -1)))
      return
    }
    if (key === 'Enter' && open) {
      event.preventDefault()
      if (walked >= 0) pickTime(TIMES[walked])
      return
    }
    if (key === 'Tab' && open) shut()
  }

  function dayKeys(event) {
    if (event.key === 'Escape' && open) {
      event.stopPropagation()
      event.preventDefault()
      shut()
    }
  }

  /* Escape is the open list's own, wherever the cursor stands in it. */
  function popKeys(event) {
    if (event.key !== 'Escape') return
    event.stopPropagation()
    event.preventDefault()
    shut()
    anchor?.querySelector(mode === 'time' ? 'input' : 'button')?.focus()
  }
</script>

<div class="platz" bind:this={anchor}>
  {#if mode === 'day'}
    <button type="button" class="feld" class:offen={open} {id} role="combobox"
            aria-haspopup="dialog" aria-expanded={open} aria-label={label || undefined}
            onclick={toggle} onkeydown={dayKeys}>
      <span class="text">{dayText}</span>
      <Hauszeichen zeichen="chevron_down" groesse={11} />
    </button>
  {:else}
    <div class="feld zeit" class:offen={open} class:ungueltig={invalid}>
      <input bind:this={input} {id} type="text" inputmode="numeric" autocomplete="off"
             spellcheck="false" bind:value={typed} role="combobox"
             aria-haspopup="listbox" aria-expanded={open} aria-invalid={invalid || undefined}
             aria-label={label || undefined}
             oninput={typing} onblur={settle} onkeydown={timeKeys} />
      <button type="button" class="winkel" tabindex="-1" aria-label={label || undefined}
              aria-expanded={open} onclick={toggle}>
        <Hauszeichen zeichen="chevron_down" groesse={11} />
      </button>
    </div>
  {/if}

  {#if open}
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <div class="klapp" class:monat={mode === 'day'} popover="manual" bind:this={pop}
         role="presentation" onkeydown={popKeys}>
      {#if mode === 'day'}
        <div class="datum">
          <span class="titel">{month.title}</span>
          <button type="button" class="mini" aria-label={t('cronjobs.month_previous')}
                  onclick={() => month.step(-1)}>
            <Hauszeichen zeichen="chevron_left" groesse={14} />
          </button>
          <button type="button" class="mini" aria-label={t('cronjobs.month_next')}
                  onclick={() => month.step(1)}>
            <Hauszeichen zeichen="chevron_right" groesse={14} />
          </button>
        </div>
        <div class="raster">
          {#each month.weekdayHeads as head, index (index)}
            <span class="wt">{head}</span>
          {/each}
          {#each month.grid as day (day)}
            <button type="button" class="tag" class:fremd={day.slice(0, 7) !== month.shownMonth}
                    class:gewaehlt={day === value} class:heutig={day === month.today}
                    aria-pressed={day === value} onclick={() => pickDay(day)}>
              {Number(day.slice(8))}
            </button>
          {/each}
        </div>
      {:else}
        <div class="liste" role="listbox" aria-label={label || undefined}>
          {#each TIMES as entry, index (entry)}
            <button type="button" role="option" tabindex="-1" data-entry={index}
                    class:dran={index === walked} aria-selected={entry === value}
                    onmouseenter={() => (walked = index)} onclick={() => pickTime(entry)}>
              <span class="haken">
                {#if entry === value}
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                       stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M4 12.5 L9.5 18 L20 6.5" />
                  </svg>
                {/if}
              </span>
              <span class="eintrag">{entry}</span>
            </button>
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .platz {
    position: relative;
    min-width: 0;
  }

  /* The measure of the house's selection field: glass with the field
     outline, the one field height. */
  .feld {
    width: 100%;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    gap: 8px;
    font: inherit;
    font-size: 13px;
    line-height: 1.3;
    color: var(--text);
    min-height: 32px;
    background: var(--glass-button);
    border: 1px solid var(--feldstrich);
    border-radius: 9px;
    padding: 6px 10px 6px 12px;
    cursor: pointer;
    text-align: left;
  }
  .feld:hover,
  .feld.offen,
  .feld:focus-within {
    background: color-mix(in srgb, var(--text) 5%, var(--glass-button));
  }
  .text {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .feld :global(svg) {
    flex: none;
    color: var(--text-still);
  }
  .feld.offen :global(svg) {
    transform: rotate(180deg);
  }

  /* The time field: the text and the chevron share one outline. */
  .zeit {
    padding: 0 4px 0 12px;
    cursor: text;
  }
  .zeit input {
    flex: 1;
    min-width: 0;
    height: 30px;
    padding: 0;
    font: inherit;
    font-size: 13px;
    font-variant-numeric: tabular-nums;
    color: var(--text);
    background: none;
    border: none;
    outline: none;
  }
  .winkel {
    flex: none;
    display: grid;
    place-items: center;
    width: 26px;
    height: 26px;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
    cursor: pointer;
  }
  /* A time that cannot be read: the outline in the colour of a failure. */
  .zeit.ungueltig {
    border-color: var(--rot);
  }

  /* Under the field, in the top layer, placed by hand (`placed`). */
  .klapp {
    position: fixed;
    inset: auto;
    margin: 0;
    padding: 0;
    color: inherit;
    background: var(--glass-dropdown);
    -webkit-backdrop-filter: blur(16px);
    backdrop-filter: blur(16px);
    border: 1px solid var(--glass-button-edge);
    border-radius: 9px;
    box-shadow: 0 18px 40px -8px rgba(0, 0, 0, 0.55);
    overflow: hidden;
  }
  .klapp:popover-open {
    display: flex;
    flex-direction: column;
  }
  .klapp.monat {
    padding: 8px 8px 10px;
  }

  /* --- the month ----------------------------------------------------- */
  .datum {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 8px;
  }
  .titel {
    flex: 1;
    min-width: 0;
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
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
  .mini:hover {
    background: var(--glass-hover);
  }
  .raster {
    display: grid;
    grid-template-columns: repeat(7, minmax(0, 1fr));
    gap: 2px;
  }
  .wt {
    text-align: center;
    font-size: 11px;
    color: var(--text-still);
    padding: 2px 0 4px;
  }
  .tag {
    height: 32px;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
    font: inherit;
    font-size: 12px;
    color: var(--text-leise);
    font-variant-numeric: tabular-nums;
    cursor: pointer;
  }
  .tag:hover {
    background: var(--glass-hover);
  }
  .tag.fremd {
    opacity: 0.45;
  }
  .tag.heutig {
    color: var(--text);
    font-weight: 700;
  }
  .tag.gewaehlt {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }

  /* --- the times ----------------------------------------------------- */
  .liste {
    flex: 1 1 auto;
    min-height: 0;
    max-height: 260px;
    overflow-y: auto;
    padding: 4px;
  }
  .liste button {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 7px;
    font: inherit;
    font-size: 13px;
    color: var(--text);
    background: none;
    border: none;
    border-radius: 9px;
    padding: 7px 8px;
    cursor: pointer;
    text-align: left;
  }
  .liste button.dran {
    background: var(--glass-button);
  }
  .haken {
    flex: none;
    width: 12px;
    display: inline-flex;
    color: var(--text-leise);
  }
  .eintrag {
    font-variant-numeric: tabular-nums;
  }
</style>
