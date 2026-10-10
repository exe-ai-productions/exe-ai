<script>
  /* The schedules on the tool surface: a view, not a place to set anything
     up. Schedules are made, changed, switched and removed in Settings ›
     Cronjobs; here stand the calendar and what happens on the chosen day.

     Two sections: the calendar (ScheduleCalendar.svelte) and, beside or
     under it, the chosen day's runs (ScheduleDayRuns.svelte). Both draw the
     one calendar state (lib/schedulecalendar.svelte.js) the settings page
     draws as well. */
  import Modulabschnitte from './Modulabschnitte.svelte'
  import ScheduleCalendar from './ScheduleCalendar.svelte'
  import ScheduleDayRuns from './ScheduleDayRuns.svelte'
  import { ScheduleCalendar as Kalender } from '../lib/schedulecalendar.svelte.js'
  import { cronampel, cronjobsGesehen } from '../lib/cronjobampel.svelte.js'
  import { flaeche } from '../lib/flaeche.svelte.js'

  const kalender = new Kalender()

  /* Seen, while the day's runs are in view on today or under the month.
     The shared sign's schedule colour is fed by an entry's last outcome:
     today's rows carry it, and the month carries every day's dots, a red
     one included. Another single day does not show what turned it red. */
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
    if (listVisible && cronampel.liste && (kalender.view === 'month' || kalender.chosen === kalender.today)) {
      cronjobsGesehen()
    }
  })

  /* Wide enough, the calendar stands on the left and the day's runs on the
     right; narrower, one under the other. */
  const ABSCHNITTE = $derived([
    { name: 'kalender', spalte: 1 },
    { name: 'tag', text: kalender.listTitle, zahl: kalender.dayRows.length, spalte: 2 },
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

<Modulabschnitte abschnitte={ABSCHNITTE} {inhalt} zweispaltig={flaeche.zweispaltig} />
