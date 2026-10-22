<script>
  /* The schedules on the tool surface: a view, not a place to set anything
     up. Schedules are made, changed, switched and removed in Settings ›
     Cronjobs; here stand the calendar and what happens on the chosen day.

     Two sections, one under the other in every width: the calendar
     (ScheduleCalendar.svelte) and the chosen day's runs
     (ScheduleDayRuns.svelte). Both draw the one calendar state
     (lib/schedulecalendar.svelte.js) the settings page draws as well. */
  import Modulabschnitte from './Modulabschnitte.svelte'
  import ScheduleCalendar from './ScheduleCalendar.svelte'
  import ScheduleDayRuns from './ScheduleDayRuns.svelte'
  import { kalender } from '../lib/schedulecalendar.svelte.js'
  import { cronampel, cronjobsGesehen } from '../lib/cronjobampel.svelte.js'

  /* Held while this face stands: the clock and the loading run for it. */
  $effect(() => kalender.hold())

  /* Seen, while the day's runs are in view. The shared sign's schedule
     colour is fed by an entry's last outcome: the month carries every day's
     dots, a red one included. */
  let listHead = $state(null)
  let listVisible = $state(false)
  $effect(() => {
    if (!listHead) return
    const wache = new IntersectionObserver(([eintrag]) => {
      listVisible = eintrag.isIntersecting
    })
    wache.observe(listHead)
    return () => wache.disconnect()
  })
  $effect(() => {
    if (listVisible && cronampel.liste) {
      cronjobsGesehen()
    }
  })

  /* The calendar on top, the day's runs under it, in every width. */
  const ABSCHNITTE = $derived([
    { name: 'kalender' },
    { name: 'tag', text: kalender.listTitle, zahl: kalender.dayRows.length },
  ])
</script>

{#snippet inhalt(name)}
  {#if name === 'kalender'}
    <ScheduleCalendar {kalender} />
  {:else if name === 'tag'}
    <div bind:this={listHead}>
      <ScheduleDayRuns rows={kalender.dayRows} />
    </div>
  {/if}
{/snippet}

<Modulabschnitte abschnitte={ABSCHNITTE} {inhalt} />
