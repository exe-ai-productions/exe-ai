<script>
  /* Settings › Cronjobs: the schedules on the left, split into active and
     inactive, each with its next run under it; on the right the calendar the
     tool surface shows as well (ScheduleCalendar.svelte on
     lib/schedulecalendar.svelte.js) — and under it nothing. Everything else
     stands in one pop-up, which has three views:

     - the day: a day clicked in the month opens the pop-up beside it with
       that day's runs (ScheduleDayRuns.svelte) and "New cronjob" at its foot;
       a run opens the settings of its schedule in the same pop-up, ‹ leads
       back to the day;
     - the schedule in full: a schedule clicked on the left opens the pop-up
       beside its row, unfolding to the right over the calendar — when it
       runs and when next, what it does, how it is scheduled, its last five
       runs (each a row that unfolds onto what the run wrote), and what one
       can do with it;
     - the form (ScheduleForm.svelte): "New cronjob", a script picked off the
       folder, or the pen of a schedule.

     A schedule is made in the calendar and nowhere else. The pop-up is a
     popover — a click beside it or Escape closes it. Where the page is given
     a `Blatt` (the phone's sheet from the bottom edge) the same views stand
     in that sheet instead, over the whole width, and the veil closes it.
     Everything that changes a schedule goes through the routes and the form,
     so there is one way to create, change, pause, start and delete a
     schedule. `onzahlen` hands the counts to the menu row. */
  import { tick, untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import { zeitpunkt, tag } from '../lib/zeitpunkt.js'
  import { t, texte } from '../lib/texte.svelte.js'
  import { frage, melde, zustand } from '../lib/zustand.svelte.js'
  import { neuigkeit } from '../lib/ereignisstrom.svelte.js'
  import { dayIn } from '../lib/clock.js'
  import { popupPlace } from '../lib/popupPlace.js'
  import { skriptwahl, skriptWahlLeeren } from '../lib/skriptwahl.svelte.js'
  import { formFromEntry, uhrzeit } from '../lib/terminform.js'
  import { kalender } from '../lib/schedulecalendar.svelte.js'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Schalter from './Schalter.svelte'
  import ScheduleForm from './ScheduleForm.svelte'
  import ScheduleCalendar from './ScheduleCalendar.svelte'
  import ScheduleDayRuns from './ScheduleDayRuns.svelte'
  import Agentenverlauf from './Agentenverlauf.svelte'
  import { agentName } from '../lib/agentmarke.js'
  import { grundtext } from '../lib/auftragsmelder.js'
  import { rollfade } from '../lib/rollfade.js'
  import { runReport } from '../lib/runreport.js'

  let { onzahlen, Blatt = null } = $props()

  /* How many runs the history shows: the last five, as drawn. */
  const LETZTE = 5
  /* The pop-up's distance from what opened it, and from the window's edge. */
  const ABSTAND = 10
  const RAND = 12

  /* Held while this page stands: the clock and the loading run for it. */
  $effect(() => kalender.hold())

  let zeilen = $state([])
  let laeufe = $state([])
  /* Whether the list has been read once: "no schedule at all" is only true
     after that, not while the first answer is on its way. */
  let loaded = $state(false)
  let gewaehlt = $state('')
  /* What the pop-up shows: `{ kind: 'day' }` the chosen day's runs,
     `{ kind: 'detail', id, fromDay }` a schedule in full (`fromDay`: it was
     reached from the day, so ‹ leads back), `{ kind: 'form', entry, script }`
     the form. Null: the pop-up is closed. */
  let view = $state(null)
  let startet = $state('')
  let popup = $state(null)
  /* The view the sheet shows: the last one opened, kept while the sheet
     flies out so it does not empty before it is gone. */
  let shown = $state(null)
  $effect.pre(() => {
    if (view) shown = view
  })
  let rechtsteil = $state(null)

  /* Read on opening, and again quietly whenever a schedule fires or a run
     ends: "next run", the dot and the history change with either. A quiet
     answer older than a change made here is dropped (`edits`). */
  let edits = 0
  /* A schedule was made, changed, paused or removed here: the list's quiet
     answers older than this are dropped. The calendar asks again on the
     service's announcement of the change, here as in every other window. */
  function scheduleChanged() {
    edits += 1
  }
  async function laden(quiet = false) {
    const vorher = edits
    try {
      const [neu, runs] = await Promise.all([api.cronjobs(), api.cronjobLaeufeAlle()])
      if (quiet && edits !== vorher) return
      zeilen = neu
      laeufe = runs
      loaded = true
    } catch (fehler) {
      if (!quiet) melde(String(fehler.message || fehler), 'fehler')
    }
  }
  $effect(() => {
    untrack(() => laden())
  })
  let gesehen = untrack(() => neuigkeit.termine + neuigkeit.auftraege)
  $effect(() => {
    const neu = neuigkeit.termine + neuigkeit.auftraege
    if (neu === gesehen) return
    gesehen = neu
    untrack(() => laden(true))
  })

  const aktive = $derived(zeilen.filter((z) => z.aktiv))
  const inaktive = $derived(zeilen.filter((z) => !z.aktiv))
  $effect(() => {
    onzahlen?.(aktive.length, zeilen.length)
  })

  /* Nothing is chosen on opening: the calendar stands on the right. A
     schedule that is gone leaves its pop-up shut. */
  const shownId = $derived(view?.kind === 'detail' ? view.id : '')
  const zeile = $derived(zeilen.find((z) => z.id === shownId) ?? null)
  $effect(() => {
    if (view?.kind === 'detail' && loaded && !zeile) geschlossen()
  })

  /* A script picked off the folder under this page (Skriptordner.svelte)
     opens the pop-up with it, over the calendar's left edge — the pick
     carries no place of its own; the count, not the name, so a second
     click on the same file opens it again. Leaving spends the pick. */
  $effect(() => {
    void skriptwahl.lauf
    if (!skriptwahl.name) return
    const name = skriptwahl.name
    untrack(() => {
      gewaehlt = ''
      view = { kind: 'form', entry: null, script: name }
      /* The column's left edge, read afresh each time the pop-up is placed. */
      zeigen({
        getBoundingClientRect() {
          const spalte = rechtsteil.getBoundingClientRect()
          return { left: spalte.left, right: spalte.left, top: spalte.top }
        },
      })
    })
  })
  $effect(() => () => skriptWahlLeeren())

  /* A schedule clicked on the left opens its pop-up beside its row, and the
     row stands chosen while it is open; the same one clicked again shuts it. */
  function waehlen(z, ev) {
    if (gewaehlt === z.id) {
      geschlossen()
      return
    }
    /* The press that opens the click also lets the pop-up's light dismiss
       shut it; if that came first, the click must not open the same one
       again. */
    if (lightClosed.id === z.id && performance.now() - lightClosed.time < 300) {
      lightClosed = { id: '', time: 0 }
      return
    }
    gewaehlt = z.id
    view = { kind: 'detail', id: z.id, fromDay: false }
    zeigen(ev.currentTarget)
  }
  /* A day clicked in the month: its runs stand in the pop-up beside the day. */
  function tagGeklickt(day, anker) {
    gewaehlt = ''
    view = { kind: 'day' }
    zeigen(anker)
  }
  /* The plus a day shows while there is no schedule at all: the form, beside
     that day, with the day already in it. */
  function plusClicked(day, anker) {
    gewaehlt = ''
    view = { kind: 'form', entry: null }
    zeigen(anker)
  }
  /* A run in the day's list: the schedule's settings, in the same pop-up. */
  function openRun(row) {
    view = { kind: 'detail', id: row.cronjob_id, fromDay: true }
  }
  function backToDay() {
    view = { kind: 'day' }
  }
  function newOnDay() {
    view = { kind: 'form', entry: null }
  }
  function bearbeiten() {
    view = { kind: 'form', entry: zeile }
  }
  /* What the pop-up hangs on: the element that opened it (or anything that
     can say where it stands, `getBoundingClientRect`). Its place is read
     each time the pop-up is set, so a column that scrolls takes the pop-up
     along. */
  let anker = null
  /* The pop-up beside what opened it: to its right where there is room,
     else to its left, and never past the window's edge (`popupPlace`). The
     browser would centre a popover; this one is placed by hand. */
  async function zeigen(neuerAnker) {
    // A sheet opens with the view itself and has no opener to stand beside.
    if (Blatt) return
    anker = neuerAnker
    await tick()
    if (!popup) return
    if (!popup.matches(':popover-open')) popup.showPopover()
    popup.focus()
    platzieren()
  }
  function platzieren() {
    // An opener that left the page (the month turned) leaves the pop-up where it is.
    if (!popup || !anker || anker.isConnected === false) return
    /* At most as tall as the window leaves room: placed, it is moved up as
       far as the window's edge, and what is longer scrolls inside — the two
       buttons at the form's foot stay in reach in a small window. */
    popup.style.maxHeight = `${Math.max(window.innerHeight - 2 * RAND, 0)}px`
    const stelle = popupPlace(
      anker.getBoundingClientRect(),
      { breite: popup.offsetWidth, hoehe: popup.offsetHeight },
      { breite: window.innerWidth, hoehe: window.innerHeight },
      ABSTAND,
      RAND,
    )
    popup.style.left = `${stelle.left}px`
    popup.style.top = `${stelle.top}px`
  }
  /* The view changed inside the open pop-up (a run, ‹, the pen): it is taller
     or shorter now, so it is set again, and the focus goes back to the pop-up
     — what held it (the button that was pressed) is gone, and Escape is heard
     from the pop-up. */
  $effect(() => {
    void view
    if (!popup || Blatt || !popup.matches(':popover-open')) return
    tick().then(() => {
      popup?.focus()
      platzieren()
    })
  })
  /* While the pop-up stands, whatever scrolls (the right column, the page)
     or resizes moves it after its opener — once per frame. */
  $effect(() => {
    if (!view || Blatt) return
    let bild = 0
    const nachfuehren = (ereignis) => {
      // What scrolls inside the pop-up (its text field, a list) moves nothing.
      if (ereignis?.target instanceof Node && popup?.contains(ereignis.target)) return
      cancelAnimationFrame(bild)
      bild = requestAnimationFrame(platzieren)
    }
    window.addEventListener('scroll', nachfuehren, true)
    window.addEventListener('resize', nachfuehren)
    return () => {
      cancelAnimationFrame(bild)
      window.removeEventListener('scroll', nachfuehren, true)
      window.removeEventListener('resize', nachfuehren)
    }
  })
  /* Closed by a click beside it or Escape: the view goes, and what was typed
     in the form with it. */
  let lightClosed = { id: '', time: 0 }
  function umgeschaltet(ev) {
    if (ev.newState !== 'closed' || !view) return
    lightClosed = { id: gewaehlt, time: performance.now() }
    geschlossen()
  }
  /* Escape closes the pop-up — the browser's own light dismiss — and
     nothing above it: the window's key handler would otherwise take the
     settings page down with it. The pop-up holds the focus for that. */
  function taste(ev) {
    if (ev.key === 'Escape') ev.stopPropagation()
  }
  /* `own` is the view the answer belongs to. A save that is answered late
     finds another view standing (the pop-up was opened again meanwhile):
     the row is saved and the lists are asked again, but the pop-up that
     stands now is not that answer's to close. */
  function geschlossen(row, own = view) {
    if (own !== view) {
      if (row) {
        scheduleChanged()
        laden()
      }
      return
    }
    view = null
    gewaehlt = ''
    anker = null
    skriptWahlLeeren()
    if (popup?.matches(':popover-open')) popup.hidePopover()
    if (row) {
      scheduleChanged()
      laden()
    }
  }

  /* The dot of a row: red when the last run failed or the entry cannot
     start, yellow while it waits for a model, otherwise blue when on and
     grey when off. */
  function punkt(z) {
    if (z.letzter_ausgang === 'gescheitert' || z.agent_missing || z.agent_broken || z.skript_nicht_startbar) return 'rot'
    if (z.wartet_auf_modell) return 'gelb'
    return z.aktiv ? 'blau' : 'still'
  }
  /* What leads a row: the time of day the form reads out of the schedule
     (daily, weekly, monthly, once), or the cron expression itself. */
  const wann = (z) => uhrzeit(z.zeitplan) || formFromEntry(z, dayIn(new Date(), zustand.timezone)).time || z.zeitplan
  const titel = (z) => z.skript || z.task
  /* What names a view for a screen reader: the day, the schedule, or the form. */
  function viewName(a) {
    if (!a) return ''
    if (a.kind === 'day') return kalender.listTitle
    if (a.kind === 'detail') return zeile ? titel(zeile) : ''
    return t(a.entry ? 'cronjobs.form_change' : 'cronjobs.neuer_cronjob')
  }

  /* The rhythm beside a schedule, read the way the form reads it. */
  const wochentage = $derived.by(() => {
    const locale = texte.sprache === 'de' ? 'de-DE' : 'en-GB'
    return Array.from({ length: 7 }, (_, i) =>
      new Date(2026, 0, 5 + i).toLocaleDateString(locale, { weekday: 'short' }))
  })
  function rhythmus(z) {
    const f = formFromEntry(z, dayIn(new Date(), zustand.timezone))
    switch (f.repeat) {
      case 'once':
        return z.datum || z.zeitplan.includes('T')
          ? t('cronjobs.einmal_am', { datum: tag(f.day) })
          : t('cronjobs.once')
      case 'daily':
        return t('cronjobs.taeglich')
      case 'weekly':
        return f.weekdays.map((chip) => wochentage[chip]).join(', ')
      case 'monthly':
        return t('cronjobs.monthly_on', { tag: f.monthDay })
      default:
        return t('cronjobs.repeat_custom')
    }
  }
  const moment = (stempel) => zeitpunkt(stempel, zustand.timezone)

  /* Off because the failure count reached its limit: only the counter
     brings a switched-off entry's failures level with it, and switching the
     entry back on clears the count. */
  function angehalten(zeile) {
    return !zeile.aktiv && zeile.fehlversuche >= zeile.fehlergrenze
  }

  /* Off because it did what it was asked: told to stop on its goal, the
     goal reported, and now off. Finished, not paused. */
  function abgeschlossen(zeile) {
    return !zeile.aktiv && zeile.ziel_stilllegen && !!zeile.ziel_erreicht_am
  }

  /* Off and its goal never reported. A fact about the goal, not a reason
     for being off, so it stands beside the state line, not inside it. */
  function zielverfehlt(zeile) {
    return !zeile.aktiv && !!zeile.ziel && !zeile.ziel_erreicht_am
  }

  /* Why the chosen schedule stands where it stands, in the line under its
     head, in the colour of that state — exactly one answer: finished,
     stopped by its failures, its agent file gone or broken, waiting for a model, its
     script not startable. With none of these, when it runs next. */
  function zustandszeile(z) {
    if (abgeschlossen(z))
      return { text: t('cronjobs.abgeschlossen', { wann: moment(z.ziel_erreicht_am) }), farbe: 'gruen' }
    if (angehalten(z))
      return { text: t(z.fehlversuche === 1 ? 'cronjobs.angehalten_eins' : 'cronjobs.angehalten', { n: z.fehlversuche }), farbe: 'rot' }
    if (z.agent_missing) return { text: t('cronjobs.agent_fehlt'), farbe: 'rot' }
    if (z.agent_broken)
      return {
        text: z.agent_broken_line
          ? t('cronjobs.agent_kaputt_zeile', { zeile: z.agent_broken_line })
          : t('cronjobs.agent_kaputt'),
        farbe: 'rot',
      }
    if (z.wartet_auf_modell) return { text: t('cronjobs.wartet_auf_modell'), farbe: 'gelb' }
    if (z.skript_nicht_startbar)
      return { text: t('cronjobs.skript_nicht_startbar', { grund: z.skript_nicht_startbar }), farbe: 'rot' }
    if (z.naechste_faelligkeit)
      return { text: t('cronjobs.naechste_faelligkeit', { wann: moment(z.naechste_faelligkeit) }), farbe: '' }
    return null
  }
  const lage = $derived(zeile ? zustandszeile(zeile) : null)

  /* A failed run's reason in words. One without a fixed reason carries its
     error inline, which belongs in the report, not in this row. */
  function grund(lauf) {
    if (!lauf.grund) return ''
    const text = grundtext({ end_reason: lauf.grund })
    return text === lauf.grund ? t('jobs.grund.fehler_allgemein') : text
  }

  /* The runs of the chosen schedule, newest first. */
  const eigene = $derived(
    zeile
      ? laeufe.filter((l) => l.cronjob_id === zeile.id).sort((a, b) => (a.wann < b.wann ? 1 : -1))
      : [],
  )

  /* The runs that stand unfolded, each with what it wrote: a run's id is
     in here while its row is open, with nothing behind it until its report
     has arrived. A run is a job, so the report is read where the agents
     view reads a run's: off the job itself, by the run's id
     (lib/runreport.js says what of it is shown). */
  let reports = $state({})

  /* An answer counts only for a row that is still waiting for it: one that
     was folded meanwhile, or has its report already, is left as it is. */
  async function reportLoad(id) {
    try {
      const report = runReport(await api.auftrag(id))
      if (reports[id] === null) reports = { ...reports, [id]: report }
    } catch (fehler) {
      if (reports[id] !== null) return
      /* Nothing to show for it: the row folds again and says why. */
      runFold(id)
      melde(String(fehler.message || fehler), 'fehler')
    }
  }
  function runFold(id) {
    const rest = { ...reports }
    delete rest[id]
    reports = rest
  }
  function runToggle(id) {
    if (id in reports) return runFold(id)
    reports = { ...reports, [id]: null }
    reportLoad(id)
  }

  async function umschalten(z, an) {
    const vorher = z.aktiv
    z.aktiv = an
    try {
      const neu = an ? await api.cronjobFortsetzen(z.id) : await api.cronjobPausieren(z.id)
      scheduleChanged()
      Object.assign(z, neu)
    } catch (fehler) {
      z.aktiv = vorher
      melde(String(fehler.message || fehler), 'fehler')
    }
  }

  async function starten(z) {
    if (startet) return
    startet = z.id
    try {
      const { notice, ...neu } = await api.cronjobStarten(z.id)
      edits += 1
      Object.assign(z, neu)
      // Where the model was still coming up the service says so itself, in
      // the language of the request; the run follows without a second press.
      melde(notice || t('cronjobs.gestartet'), 'erfolg')
      laden(true)
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    } finally {
      startet = ''
    }
  }

  async function loeschen(z) {
    const was = z.skript || z.task
    const ja = await frage(t('cronjobs.loeschen_frage', { aufgabe: was }), {
      okSchluessel: 'cronjobs.entfernen',
      danger: true,
    })
    if (!ja) return
    try {
      await api.cronjobLoeschen(z.id)
      scheduleChanged()
      await laden()
      melde(t('cronjobs.geloescht'), 'erfolg')
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }
</script>

<!-- The list stays on the left; the calendar on the right, and under it
     nothing: the day and the schedule open in the pop-up. -->
<div class="cronjobs-page">
<div class="zweispaltig">
  <div class="liste" use:rollfade>
    {#each [[t('cronjobs.aktiv'), aktive], [t('cronjobs.inaktiv'), inaktive]] as [name, gruppe] (name)}
      <div class="gruppe"><span>{name}</span><i></i><span class="zahl">{gruppe.length}/{zeilen.length}</span></div>
      {#each gruppe as z (z.id)}
        <button class="zeile" class:gewaehlt={gewaehlt === z.id} class:aus={!z.aktiv}
                onclick={(ev) => waehlen(z, ev)}>
          <span class="wann">{wann(z)}</span>
          <span class="middle">
            <span class="name" title={titel(z)}>{titel(z)}</span>
            {#if z.aktiv && z.naechste_faelligkeit}
              <span class="next">{moment(z.naechste_faelligkeit)}</span>
            {/if}
          </span>
          <Leuchtpunkt farbe={punkt(z)} groesse={9} />
        </button>
      {/each}
    {/each}
  </div>

  <div class="rechtsteil" use:rollfade bind:this={rechtsteil}>
    <ScheduleCalendar {kalender} gross onpick={tagGeklickt} empty={loaded && zeilen.length === 0}
                      onplus={plusClicked} />
  </div>
</div>
</div>

<!-- What stands in the pop-up, or in the sheet where there is one. -->
{#snippet viewContent(own)}
  {#if own.kind === 'day'}
    <div class="dayview">
      <div class="abschnitt">
        <span>{kalender.listTitle}</span><i></i>
        <span class="zahl">{kalender.dayRows.length}</span>
      </div>
      <div class="scrollarea">
        <ScheduleDayRuns rows={kalender.dayRows} gross onopen={openRun} />
      </div>
      <button class="new" onclick={newOnDay}>
        <Hauszeichen zeichen="plus" groesse={15} />
        {t('cronjobs.neuer_cronjob')}
      </button>
    </div>
  {:else if own.kind === 'detail'}
    {#if zeile}
      <div class="einzel">
        <div class="kopf">
          {#if own.fromDay}
            <button class="back" onclick={backToDay} aria-label={t('app.zurueck')} title={t('app.zurueck')}>
              <Hauszeichen zeichen="chevron_left" groesse={16} />
            </button>
          {/if}
          <div class="titel">
            <strong>{wann(zeile)} · {rhythmus(zeile)}</strong>
            {#if lage}
              <span class="unter {lage.farbe}">{lage.text}</span>
            {/if}
          </div>
        </div>
        <div class="activerow">
          <span>{t('cronjobs.aktiv')}</span>
          <Schalter an={zeile.aktiv} beschriftung={t('cronjobs.aktiv')} onschalten={(an) => umschalten(zeile, an)} />
        </div>

        <div class="abschnitt"><span>{t('cronjobs.aufgabe')}</span><i></i></div>
        <div class="kasten-text">{zeile.skript || zeile.task}</div>
        {#if !zeile.skript && zeile.ziel}
          <!-- The goal it watches for, and whether it was ever reported:
               not the state above, a fact about the goal beside it. -->
          <div class="ziel">
            <span>{t('cronjobs.ziel', { ziel: zeile.ziel })}</span>
            {#if zielverfehlt(zeile)}
              <span>{t('cronjobs.ziel_nicht_erreicht')}</span>
            {/if}
            {#if zeile.laeufe_ohne_ruf > 0}
              <span>{t('cronjobs.ohne_zielmeldung', { n: zeile.laeufe_ohne_ruf })}</span>
            {/if}
          </div>
        {/if}

        <div class="abschnitt"><span>{t('cronjobs.zeitplan')}</span><i></i></div>
        <div class="karte raster">
          <div class="zelle"><span class="klein">{t('cronjobs.field_kind')}</span><span>{t(`cronjobs.kind_${zeile.kind}`)}</span></div>
          <div class="zelle">
            <span class="klein">{t('cronjobs.kind_agent')}</span>
            <span>{zeile.kind === 'agent' ? agentName(zeile.agent) : '-'}</span>
          </div>
          <div class="zelle"><span class="klein">{t('cronjobs.field_repeat')}</span><span>{rhythmus(zeile)}</span></div>
          <div class="zelle"><span class="klein">{t('cronjobs.field_time')}</span><span>{wann(zeile)}</span></div>
        </div>

        <div class="abschnitt">
          <span>{t('cronjobs.letzte_laeufe')}</span><i></i>
          <span class="zahl">{Math.min(LETZTE, eigene.length)}/{eigene[0]?.total || eigene.length}</span>
        </div>
        {#if eigene.length}
          <!-- One row per run: when, and how it ended. A click unfolds the
               row onto what the run wrote, a second click folds it again. -->
          <div class="karte">
            {#each eigene.slice(0, LETZTE) as lauf (lauf.id)}
              <div class="run">
                <button class="lauf" aria-expanded={lauf.id in reports} onclick={() => runToggle(lauf.id)}>
                  <span class="foldarrow" class:offen={lauf.id in reports}>
                    <Hauszeichen zeichen="chevron_right" groesse={12} />
                  </span>
                  <span class="moment">{moment(lauf.wann)}</span>
                  {#if lauf.status === 'gescheitert'}
                    <span class="gescheitert">{t('jobs.zustand.gescheitert')}{grund(lauf) ? ` · ${grund(lauf)}` : ''}</span>
                  {:else}
                    <span>{t('jobs.zustand.fertig')}</span>
                  {/if}
                </button>
                {#if reports[lauf.id]}
                  <div class="report">
                    {#if reports[lauf.id].steps.length}
                      <Agentenverlauf schritte={reports[lauf.id].steps} />
                    {/if}
                    {#if reports[lauf.id].text}
                      <p class="report-text">{reports[lauf.id].text}</p>
                    {/if}
                  </div>
                {/if}
              </div>
            {/each}
          </div>
        {/if}

        <!-- Off means off: a schedule switched off does not run, so its start
             button is out rather than earning a refusal. Start stands at the
             left, the two things one can do with the schedule at the right,
             one size. -->
        <div class="knoepfe">
          <button class="knopf" disabled={!zeile.aktiv || Boolean(startet)} onclick={() => starten(zeile)}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor"
                 stroke-width="2.2" stroke-linejoin="round" aria-hidden="true"><path d="M8.5 6 L18.5 12 L8.5 18 Z" /></svg>
            {t('cronjobs.jetzt_starten')}
          </button>
          <span class="signpair">
            <button class="signbutton" onclick={bearbeiten}
                    aria-label={t('skills.bearbeiten')} title={t('skills.bearbeiten')}>
              <Hauszeichen zeichen="stift" groesse={16} />
            </button>
            <button class="signbutton danger" onclick={() => loeschen(zeile)}
                    aria-label={t('jobs.loeschen')} title={t('jobs.loeschen')}>
              <Hauszeichen zeichen="trash" groesse={16} />
            </button>
          </span>
        </div>
      </div>
    {/if}
  {:else}
    <ScheduleForm entry={own.entry} day={own.entry ? kalender.today : kalender.chosen}
                  script={own.script ?? ''} onclose={(row) => geschlossen(row, own)} />
  {/if}
{/snippet}

{#if Blatt}
  <!-- The sheet the day, a schedule or its form stands in, where there is
       one. The view it last held stays in it while it flies out. -->
  <Blatt open={view !== null} onclose={() => geschlossen()}
         label={viewName(shown)}>
    {#each shown ? [shown] : [] as own (own)}
      {@render viewContent(own)}
    {/each}
  </Blatt>
{:else}
  <!-- The pop-up the day, a schedule or its form stands in: beside the day
       clicked, or beside the row. -->
  <div class="popup" popover="auto" role="dialog" tabindex="-1"
       aria-label={viewName(view)}
       bind:this={popup} ontoggle={umgeschaltet} onkeydown={taste}>
    <!-- One pass per view object: `own` keeps the view this instance was made
         for, where a `{@const}` would follow `view` to the next one. -->
    {#each view ? [view] : [] as own (own)}
      {@render viewContent(own)}
    {/each}
  </div>
{/if}

<style>
  /* The page asks for its own width, not the window's (see the agents page);
     it takes the room the page leaves, like the grid inside it. */
  .cronjobs-page {
    container: cronjobs-page / inline-size;
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  /* As tall as the room the page leaves it: each column scrolls in itself,
     so the scripts under the schedules never move out of sight. */
  .zweispaltig {
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-columns: minmax(240px, 330px) 1fr;
    gap: 28px;
  }
  .liste,
  .rechtsteil {
    min-height: 0;
    overflow-y: auto;
  }
  @container cronjobs-page (max-width: 640px) {
    .zweispaltig {
      grid-template-columns: 1fr;
    }
  }
  .liste {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .gruppe,
  .abschnitt {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .gruppe {
    margin: 14px 12px 4px;
    font: 500 var(--schrift-hinweis) var(--schrift);
    color: var(--text-still);
  }
  .gruppe:first-child {
    margin-top: 0;
  }
  .gruppe i,
  .abschnitt i {
    flex: 1;
    border-top: 1px solid var(--linie);
  }
  .abschnitt {
    margin: 20px 0 10px;
    font: 600 var(--schrift-abschnitt) var(--schrift);
    color: var(--text);
  }
  .zahl {
    font: 400 var(--schrift-hinweis) var(--schrift);
    color: var(--text-still);
  }
  .zeile {
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
    min-height: 40px;
    padding: 6px 12px;
    box-sizing: border-box;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text);
    font: 400 var(--schrift-text) var(--schrift);
    text-align: left;
    cursor: pointer;
    transition: background 0.12s;
  }
  .zeile:hover {
    background: color-mix(in srgb, var(--text) 4%, transparent);
  }
  .zeile.gewaehlt {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    font-weight: 500;
  }
  /* Wide enough for a five-field cron expression that repeats every quarter hour. */
  .wann {
    flex: none;
    width: 104px;
    font-family: var(--schrift-fest);
    font-size: 12px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .middle {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .name {
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* The next run of a switched-on schedule, small under its name, in digits. */
  .next {
    font-size: var(--schrift-hinweis);
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
  }

  .einzel {
    min-width: 0;
    min-height: 0;
    overflow-y: auto;
  }
  .kopf {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  /* ‹ back to the day's runs: a sign button of the house's size. */
  .back {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    cursor: pointer;
  }
  .back:hover {
    background: var(--glass-hover);
  }
  /* The name "Active" stands before its switch, where it can be read. */
  .activerow {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-top: 12px;
    font-size: 13px;
  }
  .titel {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .titel strong {
    font-size: 15px;
    font-weight: 600;
  }
  .unter {
    font-size: var(--schrift-hinweis);
    color: var(--text-still);
  }
  .kasten-text {
    padding: 14px 16px;
    border-radius: 9px;
    background: var(--glass-card);
    font-size: 13px;
    line-height: 1.6;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .karte {
    border-radius: 9px;
    background: var(--glass-card);
  }
  /* The four facts stand two by two: the pop-up is one column wide. */
  .raster {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    padding: 14px 16px;
  }
  .zelle {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
    font-size: 14px;
    overflow-wrap: break-word;
  }
  .klein {
    font-size: var(--schrift-hinweis);
    color: var(--text-still);
  }
  /* The row is the button that unfolds it: the whole width takes the
     click, and it reads as the plain row it was. */
  .lauf {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 10px 16px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text);
    font: 400 13px var(--schrift);
    text-align: left;
    cursor: pointer;
    transition: background 0.12s;
  }
  .lauf:hover {
    background: color-mix(in srgb, var(--text) 4%, transparent);
  }
  /* The chevron before the time turns down while the run is unfolded. */
  .foldarrow {
    flex: none;
    display: inline-flex;
    color: var(--text-still);
    transition: transform 0.12s;
  }
  .foldarrow.offen {
    transform: rotate(90deg);
  }
  .run + .run {
    border-top: 1px solid var(--linie);
  }
  /* What the run wrote, under its row: the transcript as the run card
     draws it, and a result that is not one of its sentences in the size of
     those sentences and on their left edge, with its own line breaks. */
  .report {
    padding: 0 16px 12px;
  }
  .report-text {
    margin: 8px 0 0 20px;
    font-size: 14.5px;
    line-height: 22px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .moment {
    flex: none;
    font-family: var(--schrift-fest);
    font-size: 12.5px;
    color: var(--text-still);
  }
  .gescheitert {
    color: var(--rot-text);
  }
  /* The state line takes its state's colour (house rule: colour is state). */
  .unter.rot {
    color: var(--rot-text);
  }
  .unter.gelb {
    color: var(--gelb-text);
  }
  .unter.gruen {
    color: var(--gruen-text);
  }
  .ziel {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin-top: 8px;
    font-size: var(--schrift-hinweis);
    color: var(--text-still);
  }
  /* Start at the left, the two signs at the right. */
  .knoepfe {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-top: 22px;
  }
  .knopf {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    min-width: 140px;
    height: 36px;
    padding: 0 16px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    font: 500 13px var(--schrift);
    cursor: pointer;
    transition: background 0.12s;
  }
  .knopf:hover:not(:disabled) {
    background: var(--glass-hover);
  }
  .knopf:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .signpair {
    display: inline-flex;
    gap: 8px;
  }
  /* The pen and the bin: sign buttons of one size, the bin in the colour of
     deleting — and only the bin. */
  .signbutton {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    cursor: pointer;
  }
  .signbutton:hover {
    background: var(--glass-hover);
  }
  .signbutton.danger {
    color: var(--rot-text);
  }

  /* The day: the heading with its count, the runs rolling in their own
     room, "New cronjob" at the foot. */
  .dayview {
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .dayview .abschnitt {
    margin: 0 0 10px;
  }
  .scrollarea {
    min-height: 0;
    overflow-y: auto;
  }
  .new {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    height: 36px;
    padding: 0 12px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    font: 500 13px var(--schrift);
    cursor: pointer;
    transition: color 0.12s, background 0.12s;
  }
  .new:hover {
    color: var(--text);
    background: var(--glass-hover);
  }

  /* On the phone a word breaks only where it does not fit a line at all;
     Start stands over the whole width, the two signs under it, each as tall
     as a fingertip needs and with the face of the other buttons of the
     phone. */
  :global(html[data-phone]) .zelle {
    overflow-wrap: break-word;
  }
  :global(html[data-phone]) .knoepfe {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    grid-auto-flow: row;
  }
  :global(html[data-phone]) .knopf {
    height: 44px;
  }
  :global(html[data-phone]) .signpair {
    justify-content: flex-end;
  }
  :global(html[data-phone]) .signbutton {
    width: 44px;
    height: 44px;
  }
  :global(html[data-phone]) .back {
    width: 44px;
    height: 44px;
  }
  :global(html[data-phone]) .new {
    height: 44px;
  }

  /* The pop-up: the dropdown's dense glass, over everything, placed by hand
     beside what opened it — the browser's own centring is undone. As wide
     as the form needs to stand in one column. */
  .popup {
    position: fixed;
    inset: auto;
    margin: 0;
    width: 340px;
    padding: 14px 16px 16px;
    border: none;
    border-radius: 9px;
    /* Taller than the room the window leaves (`platzieren`), what is inside
       scrolls in itself: the day's runs, a schedule in full, the form's
       fields. A list opened in the form is a popover of its own in the top
       layer (Auswahlfeld.svelte), so this clips nothing of it. */
    overflow: hidden;
    background: var(--glass-dropdown);
    color: var(--text);
    box-shadow: 0 18px 40px -8px rgba(0, 0, 0, 0.55), inset 0 0 0 1px var(--glass-button-edge);
    -webkit-backdrop-filter: blur(16px);
    backdrop-filter: blur(16px);
  }
  /* A column only while it stands open: a display set on the closed
     element would show it. */
  .popup:popover-open {
    display: flex;
    flex-direction: column;
  }
  .popup:focus {
    outline: none;
  }
  .popup::backdrop {
    background: none;
  }
</style>
