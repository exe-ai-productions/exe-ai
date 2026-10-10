<script>
  /* Settings › Cronjobs: the schedules on the left, split into active and
     inactive; on the right the calendar the tool surface shows as well
     (ScheduleCalendar.svelte on lib/schedulecalendar.svelte.js), and under
     it either the chosen day's runs or — once a schedule is clicked on the
     left — that schedule in full: when it runs and when next, what it does,
     how it is scheduled, its last five runs — each a row that unfolds onto
     what the run wrote — and the three things one can do with it.

     A schedule is made in the calendar and nowhere else: a day clicked in
     the month opens the form (ScheduleForm.svelte) in a pop-up beside that
     day, with the day already in it; "Change" opens the same pop-up beside
     its button with the schedule's values. The pop-up is a popover — a
     click beside it or Escape closes it. Everything that changes a schedule
     goes through the routes and the form, so there is one way to create,
     change, pause, start and delete a schedule. `onzahlen` hands the counts
     to the menu row. */
  import { tick, untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import { zeitpunkt, tag } from '../lib/zeitpunkt.js'
  import { t, texte } from '../lib/texte.svelte.js'
  import { frage, melde, zustand } from '../lib/zustand.svelte.js'
  import { neuigkeit } from '../lib/ereignisstrom.svelte.js'
  import { dayIn } from '../lib/clock.js'
  import { skriptwahl, skriptWahlLeeren } from '../lib/skriptwahl.svelte.js'
  import { formFromEntry, uhrzeit } from '../lib/terminform.js'
  import { ScheduleCalendar as Kalender } from '../lib/schedulecalendar.svelte.js'
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

  let { onzahlen } = $props()

  /* How many runs the history shows: the last five, as drawn. */
  const LETZTE = 5
  /* The pop-up's distance from what opened it, and from the window's edge. */
  const ABSTAND = 10
  const RAND = 12

  const kalender = new Kalender()

  let zeilen = $state([])
  let laeufe = $state([])
  let gewaehlt = $state('')
  let form = $state(null)
  let startet = $state('')
  let popup = $state(null)
  let rechtsteil = $state(null)

  /* Read on opening, and again quietly whenever a schedule fires or a run
     ends: "next run", the dot and the history change with either. A quiet
     answer older than a change made here is dropped (`edits`). */
  let edits = 0
  async function laden(quiet = false) {
    const vorher = edits
    try {
      const [neu, runs] = await Promise.all([api.cronjobs(), api.cronjobLaeufeAlle()])
      if (quiet && edits !== vorher) return
      zeilen = neu
      laeufe = runs
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

  /* Nothing is chosen on opening: the calendar and the day stand on the
     right. A chosen schedule that is gone leaves the day in view again. */
  $effect(() => {
    if (gewaehlt && !zeilen.some((z) => z.id === gewaehlt)) gewaehlt = ''
  })
  const zeile = $derived(zeilen.find((z) => z.id === gewaehlt) ?? null)

  /* A script picked off the folder under this page (Skriptordner.svelte)
     opens the pop-up with it, over the calendar's left edge — the pick
     carries no place of its own; the count, not the name, so a second
     click on the same file opens it again. Leaving spends the pick. */
  $effect(() => {
    void skriptwahl.lauf
    if (!skriptwahl.name) return
    const name = skriptwahl.name
    untrack(() => {
      form = { entry: null, script: name }
      const spalte = rechtsteil.getBoundingClientRect()
      zeigen({ left: spalte.left, right: spalte.left, top: spalte.top })
    })
  })
  $effect(() => () => skriptWahlLeeren())

  /* A schedule clicked on the left stands in full under the calendar; the
     same one clicked again gives the day its place back. */
  function waehlen(z) {
    gewaehlt = gewaehlt === z.id ? '' : z.id
  }
  /* A day clicked in the month: its runs stand under the calendar, and the
     pop-up opens beside the day for a new schedule on it. */
  function tagGeklickt(day, anker) {
    gewaehlt = ''
    form = { entry: null }
    zeigen(anker)
  }
  function bearbeiten(ev) {
    form = { entry: zeile }
    zeigen(ev.currentTarget.getBoundingClientRect())
  }
  /* The pop-up beside what opened it (`anker`, a rect on screen): to its
     right where there is room, else to its left, and never past the
     window's bottom edge. The browser would centre a popover; this one is
     placed by hand. */
  async function zeigen(anker) {
    await tick()
    if (!popup) return
    if (!popup.matches(':popover-open')) popup.showPopover()
    popup.focus()
    const breite = popup.offsetWidth
    const hoehe = popup.offsetHeight
    let x = anker.right + ABSTAND
    if (x + breite > window.innerWidth - RAND) x = anker.left - ABSTAND - breite
    let y = anker.top
    if (y + hoehe > window.innerHeight - RAND) y = window.innerHeight - RAND - hoehe
    popup.style.left = `${Math.max(RAND, x)}px`
    popup.style.top = `${Math.max(RAND, y)}px`
  }
  /* Closed by a click beside it or Escape: the form goes, and what was
     typed in it with it. */
  function umgeschaltet(ev) {
    if (ev.newState === 'closed' && form) geschlossen()
  }
  /* Escape closes the pop-up — the browser's own light dismiss — and
     nothing above it: the window's key handler would otherwise take the
     settings page down with it. The pop-up holds the focus for that. */
  function taste(ev) {
    if (ev.key === 'Escape') ev.stopPropagation()
  }
  function geschlossen(row) {
    form = null
    skriptWahlLeeren()
    if (popup?.matches(':popover-open')) popup.hidePopover()
    if (row) {
      edits += 1
      laden()
    }
  }

  /* The dot of a row: red when the last run failed or the entry cannot
     start, yellow while it waits for a model, otherwise blue when on and
     grey when off. */
  function punkt(z) {
    if (z.letzter_ausgang === 'gescheitert' || z.agent_fehlt || z.skript_nicht_startbar) return 'rot'
    if (z.wartet_auf_modell) return 'gelb'
    return z.aktiv ? 'blau' : 'still'
  }
  /* What leads a row: the time of day the form reads out of the schedule
     (daily, weekly, monthly, once), or the cron expression itself. */
  const wann = (z) => uhrzeit(z.zeitplan) || formFromEntry(z, dayIn(new Date(), zustand.timezone)).time || z.zeitplan
  const titel = (z) => z.skript || z.task

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
     stopped by its failures, its agent file gone, waiting for a model, its
     script not startable. With none of these, when it runs next. */
  function zustandszeile(z) {
    if (abgeschlossen(z))
      return { text: t('cronjobs.abgeschlossen', { wann: moment(z.ziel_erreicht_am) }), farbe: 'gruen' }
    if (angehalten(z))
      return { text: t('cronjobs.angehalten', { n: z.fehlversuche }), farbe: 'rot' }
    if (z.agent_fehlt) return { text: t('cronjobs.agent_fehlt'), farbe: 'rot' }
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
      edits += 1
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
      const neu = await api.cronjobStarten(z.id)
      edits += 1
      Object.assign(z, neu)
      melde(t('cronjobs.gestartet'), 'erfolg')
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
    })
    if (!ja) return
    try {
      await api.cronjobLoeschen(z.id)
      edits += 1
      await laden()
      melde(t('cronjobs.geloescht'), 'erfolg')
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }
</script>

<!-- The list stays on the left; the calendar on the right, and under it
     the day or the chosen schedule. -->
<div class="zweispaltig">
  <div class="liste" use:rollfade>
    {#each [[t('cronjobs.aktiv'), aktive], [t('cronjobs.inaktiv'), inaktive]] as [name, gruppe] (name)}
      <div class="gruppe"><span>{name}</span><i></i><span class="zahl">{gruppe.length}/{zeilen.length}</span></div>
      {#each gruppe as z (z.id)}
        <button class="zeile" class:gewaehlt={gewaehlt === z.id} class:aus={!z.aktiv}
                onclick={() => waehlen(z)}>
          <span class="wann">{wann(z)}</span>
          <span class="name" title={titel(z)}>{titel(z)}</span>
          <Leuchtpunkt farbe={punkt(z)} groesse={9} />
        </button>
      {/each}
    {/each}
  </div>

  <div class="rechtsteil" use:rollfade bind:this={rechtsteil}>
    <ScheduleCalendar {kalender} gross onpick={tagGeklickt} />

    {#if zeile}
    <div class="einzel">
      <div class="kopf">
        <span class="kasten"><Hauszeichen zeichen="stopwatch" groesse="mittel" /></span>
        <div class="titel">
          <strong>{wann(zeile)} · {rhythmus(zeile)}</strong>
          {#if lage}
            <span class="unter {lage.farbe}">{lage.text}</span>
          {/if}
        </div>
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
          <span>{zeile.kind === 'agent' ? agentName(zeile.agent) : '—'}</span>
        </div>
        <div class="zelle"><span class="klein">{t('cronjobs.field_repeat')}</span><span>{rhythmus(zeile)}</span></div>
        <div class="zelle"><span class="klein">{t('cronjobs.field_time')}</span><span>{wann(zeile)}</span></div>
      </div>

      <div class="abschnitt">
        <span>{t('cronjobs.letzte_laeufe')}</span><i></i>
        <span class="zahl">{Math.min(LETZTE, eigene.length)}/{eigene.length}</span>
      </div>
      {#if eigene.length}
        <!-- One row per run: when, and how it ended. A click unfolds the
             row onto what the run wrote, a second click folds it again. -->
        <div class="karte">
          {#each eigene.slice(0, LETZTE) as lauf (lauf.id)}
            <div class="run">
              <button class="lauf" aria-expanded={lauf.id in reports} onclick={() => runToggle(lauf.id)}>
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
           button is out rather than earning a refusal. -->
      <div class="knoepfe">
        <button class="knopf" disabled={!zeile.aktiv || Boolean(startet)} onclick={() => starten(zeile)}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor"
               stroke-width="2.2" stroke-linejoin="round" aria-hidden="true"><path d="M8.5 6 L18.5 12 L8.5 18 Z" /></svg>
          {t('cronjobs.jetzt_starten')}
        </button>
        <button class="knopf" onclick={bearbeiten}>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 3l4 4L8 20l-5 1 1-5L17 3z" /></svg>
          {t('skills.bearbeiten')}
        </button>
        <button class="knopf gefahr" onclick={() => loeschen(zeile)}>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M3 6h18" /><path d="M8 6V4h8v2" /><path d="M6 6l1 14h10l1-14" />
          </svg>
          {t('jobs.loeschen')}
        </button>
      </div>
    </div>
    {:else}
      <div class="abschnitt">
        <span>{kalender.listTitle}</span><i></i>
        <span class="zahl">{kalender.dayRows.length}</span>
      </div>
      <ScheduleDayRuns rows={kalender.dayRows} gross />
    {/if}
  </div>
</div>

<!-- The pop-up a schedule is made or changed in: beside the day clicked,
     or beside "Change". -->
<div class="popup" popover="auto" role="dialog" tabindex="-1"
     aria-label={t(form?.entry ? 'cronjobs.form_change' : 'cronjobs.neuer_cronjob')}
     bind:this={popup} ontoggle={umgeschaltet} onkeydown={taste}>
  {#if form}
    {#key form}
      <ScheduleForm entry={form.entry} day={form.entry ? kalender.today : kalender.chosen}
                    script={form.script ?? ''} onclose={geschlossen} />
    {/key}
  {/if}
</div>

<style>
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
  @media (max-width: 860px) {
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
  .name {
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .einzel {
    min-width: 0;
  }
  .kopf {
    display: flex;
    align-items: center;
    gap: 14px;
  }
  .kasten {
    width: 44px;
    height: 44px;
    flex: none;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 9px;
    background: var(--glass-card);
    color: var(--text);
  }
  .titel {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .titel strong {
    font-size: 17px;
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
  .raster {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    padding: 14px 16px;
  }
  .zelle {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
    font-size: 14px;
    overflow-wrap: anywhere;
  }
  .klein {
    font-size: var(--schrift-hinweis);
    color: var(--text-still);
  }
  /* The row is the button that unfolds it: the whole width takes the
     click, and it reads as the plain row it was. */
  .lauf {
    display: flex;
    align-items: baseline;
    gap: 14px;
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
  /* Side by side, one size: the widest label sets the width of all three. */
  .knoepfe {
    display: inline-grid;
    grid-auto-columns: 1fr;
    grid-auto-flow: column;
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
    background: var(--glass-card);
    color: var(--text);
    font: 500 13px var(--schrift);
    cursor: pointer;
    transition: background 0.12s;
  }
  .knopf:hover:not(:disabled) {
    background: color-mix(in srgb, var(--text) 8%, var(--glass-card));
  }
  .knopf:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .knopf.gefahr {
    color: var(--rot-text);
  }

  /* The pop-up: the dropdown's dense glass, over everything, placed by hand
     beside what opened it — the browser's own centring is undone. As wide
     as the form needs to stand in one column. */
  .popup {
    position: fixed;
    inset: auto;
    margin: 0;
    width: 320px;
    padding: 14px 16px 16px;
    border: none;
    border-radius: 9px;
    background: var(--glass-dropdown);
    color: var(--text);
    box-shadow: 0 18px 40px -8px rgba(0, 0, 0, 0.55), inset 0 0 0 1px var(--glass-button-edge);
    -webkit-backdrop-filter: blur(16px);
    backdrop-filter: blur(16px);
  }
  .popup:focus {
    outline: none;
  }
  .popup::backdrop {
    background: none;
  }
</style>
