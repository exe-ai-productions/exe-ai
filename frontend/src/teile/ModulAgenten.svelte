<script>
  /* The agents view — the agents on the tool surface, one column that
     scrolls as a whole (Modulabschnitte.svelte). The schedules are a tool
     of their own (ModulCronjobs.svelte, opened from Arbeitsleiste.svelte).

     The parts, top to bottom, in this order on purpose:

       Running        what is waiting (yellow) and what is running (blue),
                      each a card with its context bar; the card unfolds its
                      step log.
       Reports        every job that produced one, one row each in one
                      card; a click opens the report in the reader. The
                      cross asks before it deletes.

     The agents themselves are listed, created, changed and deleted in
     Settings › Agents; this view is about work, not about who does it. An
     empty part shows its heading and its count and nothing else.

     The list itself is refreshed on a quiet cadence while the panel is
     open; a failed fetch stays quiet too — this is an overview, and a
     restarting service must not answer it with a toast salvo. */
  import Modulabschnitte from './Modulabschnitte.svelte'
  import Agentenverlauf from './Agentenverlauf.svelte'
  import { untrack } from 'svelte'
  import Kontextstrich from './Kontextstrich.svelte'
  import Benutzerfrage from './Benutzerfrage.svelte'
  import { api } from '../lib/api.js'
  import { answerAgentQuestion } from '../lib/agentchat.svelte.js'
  import { dateiart, dateiFakten, dateiHerunterladen } from '../lib/dateiarten.js'
  import { dateienAus } from '../lib/markdown.js'
  import Hauszeichen from './Hauszeichen.svelte'
  /* The one distinction both displays of a run share — handed on to a
     continuation, or a real ending. It stands in a file of its own because
     this list and the dot on the rail disagreed about the same run while
     each of them kept a copy of it. */
  import { weitergereicht } from '../lib/laufstand.js'
  /* And the other one they share: which endings have a row here at all.
     The dot can only lose its colour through a row that is opened, so it
     must not colour for a run this list leaves out. */
  import { auftragGesehen, worthReading } from '../lib/agentenampel.svelte.js'
  import { showPage, showReport } from '../lib/bildschau.svelte.js'
  import { farbenSetzen, farbeVon, lesbar } from '../lib/agentenfarbe.svelte.js'
  import { zeitpunkt } from '../lib/zeitpunkt.js'
  import { grundtext } from '../lib/auftragsmelder.js'
  import { agentName } from '../lib/agentmarke.js'
  import { t } from '../lib/texte.svelte.js'
  import { flaeche } from '../lib/flaeche.svelte.js'
  import {
    auftragLoeschen, frage, melde, zustand, auftraegeStillLaden,
  } from '../lib/zustand.svelte.js'

  /* What is running comes first: a run in flight is the one thing on this
     view somebody may still have to act on — a question to answer, a run
     to stop — and it must not sit under lists that grow all day. */
  const ABSCHNITTE = $derived([
    { name: 'aktiv', titel: 'agenten.abschnitt_aktiv', zahl: aktive.length, spalte: 1 },
    {
      name: 'bericht',
      titel: 'agenten.abschnitt_bericht',
      zahl: `${gezeigteBerichte.length}/${berichte.length}`,
      spalte: 2,
    },
  ])

  /* Every job that has something to show for itself, newest first — the
     list arrives in updated_at DESC already.

     A report, OR an ending worth reading. That second half is not a
     widening for its own sake: measured on the running service, a run
     stopped at its time limit in the middle of a tool call has produced no
     text at all (``ergebnis or None``, app/api/v1/auftraege.py), and so it
     appeared in this list not at all — while its row in the sidebar said
     'gescheitert' and offered nothing to click through to. The one run
     whose only news IS the reason was the one run the reason could not
     reach.

     'unterbrochen' belongs in that half for the same reason and was
     missing from it: a run a service restart cut off has no result either
     (it never got to write one), so the branch meant to draw it quietly
     could never be reached at all. Since d9f6e3c that is what the end of
     the service does to every running script, which makes it the normal
     case rather than the rare one.

     And a chain is ONE piece of work, not one per link. A dead model
     server restarts a job every couple of minutes up to MAX_NEUSTARTS, and
     each link left a row here — ten rows about one disturbance, nine of
     them about work that carried on. So a handed-on link steps aside as
     soon as anything newer of the same work exists: the run that carried
     on, or the one that finally ended it. `work_id` is what says "same
     work" — the chain's origin, read off ``ursprung_id`` on the route
     (app/api/v1/schemas.py). Nothing is swallowed silently: the last link,
     the one with nothing behind it, is exactly the row that stays.

     `gesehen` collects EVERY job walked past, not only the ones kept — a
     link is superseded by a continuation that is still running just as
     much as by one that has ended.

     A schedule's run that was stopped is listed too: it is the one place
     that run can still be seen. Left as it was for every other ending: a
     finished run with nothing to say, and an abort by hand, are not news.

     Which endings those are is written down once, in `worthReading`
     (lib/agentenampel.svelte.js), and read from there by this list and by
     the dot on the rail. What stays here is the part only a list can
     decide: which link of a chain is the one to show. */
  const berichte = $derived.by(() => {
    const gesehen = new Set()
    const zeilen = []
    for (const auftrag of zustand.auftraege) {
      const werk = auftrag.work_id ?? auftrag.id
      const zeigen = worthReading(auftrag) && !(weitergereicht(auftrag) && gesehen.has(werk))
      gesehen.add(werk)
      if (zeigen) zeilen.push(auftrag)
    }
    return zeilen
  })

  /* Five reports stand at first; "more" adds five, "less" goes back to
     five. A day of schedules writes dozens, and an endless list pushed the
     newest ones' neighbours out of reach of the eye. */
  const PAGE = 5
  let shownReports = $state(PAGE)
  const gezeigteBerichte = $derived(berichte.slice(0, shownReports))
  const moreCount = $derived(Math.min(PAGE, berichte.length - gezeigteBerichte.length))

  /* The files a report wrote, read from its text the way its file cards
     are (the same names), for the chips on its row. */
  const reportFiles = $derived(
    new Map(gezeigteBerichte.map((auftrag) => [auftrag.id, dateienAus(auftrag.result ?? '')])),
  )
  function fileOpen(event, datei) {
    // The chip sits on the row; the row itself opens the report.
    event.stopPropagation()
    showPage({
      name: datei.name,
      language: datei.art,
      text: datei.inhalt,
      download: () => dateiHerunterladen(datei.name, datei.inhalt, dateiart(datei.art)?.typ),
    })
  }

  /* A report opens as a page in the reader: who, what, how it ended, and
     its text with the files it wrote. Opening it is reading it — the run's
     mark is cleared the same moment. */
  function berichtOeffnen(auftrag) {
    auftragGesehen(auftrag.id)
    showReport({
      name: `${auftrag.agent || 'agent'}-${auftrag.id}`,
      agent: auftrag.agent,
      colour: lesbar(farbeVon(auftrag.agent)),
      task: auftrag.task,
      time: zeitpunkt(auftrag.updated_at),
      state: auftrag.state,
      chain: auftrag.parent_id ? kettenwort(auftrag) : '',
      reason: grundtext(auftrag),
      timedOut: auftrag.end_reason === 'zeitgrenze',
      text: auftrag.result ?? '',
      facts: dateiFakten,
    })
  }

  /* The colour of the bar and the dot on an unopened row: what the run did,
     in the palette's own word. Green for a report that stands unread, red
     for a run that broke. Everything already looked at gets nothing —
     which is what makes the one that has not stand out. */
  /* How a report's run ended, as the colour of its dot: failed red, done
     green, anything else (stopped, cut off by a restart) quiet. */
  function endColour(auftrag) {
    if (auftrag.state === 'gescheitert') return 'rot'
    return auftrag.state === 'fertig' ? 'gruen' : 'text-still'
  }

  /* Why a run ended, in words — for every ending that is not a plain
     'fertig'.

     The catalogue block `jobs.grund.*` has translated these since 9ea2274
     and had not one reader in the whole program. The reason WAS written:
     into the step log, as the `ende` step — and the step log only opens for
     a run that is waiting or running. The ending is the very moment a run
     leaves that list for this one, so the line carrying it was gone from
     the screen in the same breath it was written. A red schedule and no way
     to find out why.

     So it stands here instead: on the finished run's report, which is
     where somebody who wants to know goes looking. Read from `end_reason`,
     which every job row has carried all along (app/api/v1/schemas.py) — no
     field had to travel for this.

     Nothing for a run that simply finished: a clean run must look exactly
     as it looked before, and 'fertig geworden' under every good report
     would be noise nobody reads past the second day.

     The expression itself lives in frontend/src/lib/auftragsmelder.js, with
     the rest of what an ended run has to say: the notice that goes up when
     a run ends reaches for the same sentence, and one expression written
     down twice is how two displays of the same run come apart. */

  /* The middle: what is waiting or running right now, waiting first — the
     same order the sidebar list keeps, because yellow is the row that
     needs a hand. */
  const aktive = $derived([
    ...zustand.auftraege.filter((a) => a.state === 'wartet'),
    ...zustand.auftraege.filter((a) => a.state === 'laeuft'),
  ])

  /* The agents, read for their colours: every run and report here wears
     its agent's colour. NOT on the three second cadence the jobs ride: an
     agent file changes when somebody saves one, not while a run works, so
     it is read once and again whenever the mask closes. */
  let agenten = $state([])
  async function agentenLaden() {
    try {
      agenten = await api.agenten()
    } catch {
      agenten = []
    }
    /* The one place that already holds the list fills the colour table from
       it, so the panels that show an agent's name without the list — the
       schedules, the notices — do not each fetch it again. */
    farbenSetzen(agenten)
  }
  $effect(() => {
    agentenLaden()
  })

  /* Which active rows are unfolded, and each one's step log. The log rides
     the same 3-second cadence as the list — enough to watch a run work
     without a second live channel. */
  let offene = $state(new Set())
  let protokolle = $state({})

  async function schritteLaden(id) {
    try {
      protokolle = { ...protokolle, [id]: (await api.auftrag(id)).schritte ?? [] }
    } catch {
      /* The cadence retries. */
    }
  }

  function klappen(id) {
    const neu = new Set(offene)
    if (neu.has(id)) {
      neu.delete(id)
    } else {
      neu.add(id)
      schritteLaden(id)
    }
    offene = neu
  }

  /* The job list is not asked for here anymore: the live line says when it
     changed and fetches it once (lib/ereignisstrom.svelte.js).

     The step log keeps a timer, and deliberately: a running run writes
     steps continuously, and no event answers that, so the timer stays
     rather than being replaced by a promise nobody keeps.

     What it does not do is run while nothing is going on. It ticks only
     while a run is alive or a step list is unfolded, which is the only time
     the answer can change; with the panel open over a quiet list it asks
     nothing at all. */

  const etwasLaeuft = $derived(
    zustand.auftraege.some((a) => a.state === 'laeuft' || a.state === 'wartet'),
  )

  $effect(() => {
    if (!etwasLaeuft && !offene.size) return
    const uhr = setInterval(() => {
      for (const id of offene) schritteLaden(id)
    }, 3000)
    return () => clearInterval(uhr)
  })

  /* A row picked elsewhere — the agents sheet, the start window — lands
     here: unfold it and bring it into view. Read once and cleared, so the
     next unfold is a fresh gesture. */
  $effect(() => {
    const id = zustand.auftragAusgewaehlt
    if (!id) return
    zustand.auftragAusgewaehlt = null
    if (!offene.has(id)) klappen(id)
    requestAnimationFrame(() => {
      document.getElementById('modul-auftrag-' + id)?.scrollIntoView({ block: 'nearest' })
    })
  })

  /* The answer to a run's own question. One route for both cases: a run
     that is still holding the call open takes it into that call, and a run
     a restart took away is carried on from its own status with the question
     and this answer in its assignment. The window does not decide which —
     the service knows, and whoever answers should not have to.

     The same way in as the chat's box, so a question answered here leaves
     the box at once rather than standing there for a second answer. */
  function frageBeantworten(auftrag, antwort) {
    return answerAgentQuestion(auftrag.id, auftrag.question?.aufruf_id, antwort)
  }

  /* The cancel on a running row: asked for, not gone wrong — the run ends
     with whatever it has. A schedule's run that was stopped stands under
     the reports from then on; the schedule itself is switched on and off
     in Settings › Schedules only. */
  async function abbrechen(auftrag) {
    try {
      await api.auftragAbbrechen(auftrag.id)
      await auftraegeStillLaden()
    } catch {
      melde(t('fehler.allgemein'), 'fehler')
    }
  }

  /* Asked first, like every other delete: a report is gone for good, with
     its log. */
  async function berichtWeg(auftrag) {
    const ja = await frage(t('jobs.loeschen_frage'), { okSchluessel: 'jobs.loeschen' })
    if (!ja) return
    try {
      await auftragLoeschen(auftrag.id)
      melde(t('jobs.geloescht'), 'erfolg')
    } catch {
      melde(t('fehler.allgemein'), 'fehler')
    }
  }

  /* The copy button on a code block must do what it does in the chat
     (Nachricht.svelte): a button that answers to nothing would be lying.
     Delegated from the container, same as there, because the markup only
     exists at runtime — the shared handler lives beside the button's
     creator in lib/markdown.js.

     A file box is NOT handled here any more: it is a Dateikarte now and
     brings its own clicks. */
  /* Who started this run, when a run did. A branch nobody can see is a
     branch nobody can stop — so a run an agent asked for says so on its own
     row, and names the run above it.

     Looked up in the list this panel already holds: the parent is a job
     like any other, so nothing has to travel for this. A parent that has
     been deleted leaves the mark without a name rather than nothing at
     all — the run IS still a branch. */
  function elternteil(auftrag) {
    if (!auftrag?.parent_id) return null
    return zustand.auftraege.find((a) => a.id === auftrag.parent_id) ?? null
  }
  function kettenwort(auftrag) {
    const eltern = elternteil(auftrag)
    return t('jobs.gestartet_von', { agent: eltern ? agentName(eltern.agent) : '—' })
  }

  /* An agent's name in its own colour, wherever this panel writes one.
     Empty for an agent that picked none — then the row is drawn exactly as
     it was before the field existed. */
  function agentfarbe(name) {
    const wert = lesbar(farbeVon(name))
    return wert ? `color:${wert}` : ''
  }

</script>

{#snippet inhalt(name)}
  {#if name === 'bericht'}
    {#if berichte.length}
      <!-- One card, one row per report: the task, when and who, the files it
           wrote as chips, and a dot in the colour of how it ended. A click
           on the text opens the report in the reader; the cross asks first.
           A fresh report takes the top of the list. -->
      <div class="karte zeilen">
        {#each gezeigteBerichte as auftrag (auftrag.id)}
          <div class="bzeile">
            <div class="bwas">
              <button class="btext" onclick={() => berichtOeffnen(auftrag)}>
                <span class="beins">{auftrag.task}</span>
                <span class="bzwei" class:rot={auftrag.state === 'gescheitert'}>
                  {zeitpunkt(auftrag.updated_at)} · <span style={agentfarbe(auftrag.agent)}>{agentName(auftrag.agent)}</span>
                </span>
              </button>
              {#if reportFiles.get(auftrag.id)?.length}
                <span class="dateien">
                  {#each reportFiles.get(auftrag.id) as datei (datei.name)}
                    <button class="datei-chip" onclick={(e) => fileOpen(e, datei)} title={datei.name}>
                      <Hauszeichen zeichen="dokument" groesse={13} />
                      <span>{datei.name}</span>
                    </button>
                  {/each}
                </span>
              {/if}
            </div>
            <button
              class="bweg"
              onclick={() => berichtWeg(auftrag)}
              title={t('jobs.loeschen')}
              aria-label={t('jobs.loeschen')}
            >✕</button>
            <span class="bpunkt" style:background={`var(--${endColour(auftrag)})`}></span>
          </div>
        {/each}
      </div>
      {#if moreCount > 0 || gezeigteBerichte.length > PAGE}
        <!-- More and less side by side, the same size; each only while it
             does something. -->
        <div class="knopfreihe">
          {#if moreCount > 0}
            <button class="breitknopf" onclick={() => (shownReports += PAGE)}>
              {t('agenten.weitere', { n: moreCount })}
            </button>
          {/if}
          {#if gezeigteBerichte.length > PAGE}
            <button class="breitknopf" onclick={() => (shownReports = PAGE)}>
              {t('agenten.weniger')}
            </button>
          {/if}
        </div>
      {/if}
    {/if}
  {:else if name === 'aktiv'}
    {#if aktive.length}
      {#each aktive as auftrag (auftrag.id)}
        <!-- One run, one card: its state dot, the task, the agent, and the
             context bar with its percentage; the card unfolds its
             transcript, and the stop control stands in there and nowhere
             else — every run under it has its own. A run an agent
             started is drawn one step in, under the run that asked for it:
             the indent is the chain, and the mark says which run it hangs
             from. -->
        <div class="alauf" class:kind={Boolean(auftrag.parent_id)}
             id={'modul-auftrag-' + auftrag.id}>
          <div class="karte laufkarte">
            <div class="laufkopf">
              <button class="lauftitel" onclick={() => klappen(auftrag.id)}
                      aria-expanded={offene.has(auftrag.id)} title={auftrag.task}>
                <span class="laufpunkt" class:wartet={auftrag.state === 'wartet'} aria-hidden="true"></span>
                <span class="laufaufgabe">{auftrag.task}</span>
              </button>
            </div>
            <div class="laufagent" style={agentfarbe(auftrag.agent)}>{agentName(auftrag.agent)}</div>
            <!-- The run's newest context reading, off the job list, which the
                 live line reloads the moment a reading is written. -->
            <div class="laufstrich">
              <Kontextstrich prozent={auftrag.kontext?.prozent} />
            </div>
            {#if offene.has(auftrag.id)}
              {#if auftrag.parent_id}
                <p class="bkette">↳ {kettenwort(auftrag)}</p>
              {/if}
              <div class="transcript-head">
                <button class="stopp" onclick={() => abbrechen(auftrag)}
                        title={t('jobs.abbrechen')} aria-label={t('jobs.abbrechen')}>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                    <rect x="6.5" y="6.5" width="11" height="11" rx="2" />
                  </svg>
                </button>
              </div>
              {#if protokolle[auftrag.id]?.length}
                <Agentenverlauf schritte={protokolle[auftrag.id]} laeuft={auftrag.state === 'laeuft'} />
              {/if}
            {/if}
          </div>
          <!-- The question stays OUTSIDE the card, and that is the point: it
               is the one thing on this run somebody has to act on, and a
               question that only appears once the card is unfolded is a
               question nobody sees. The banner names the agent, and the
               buttons are the chat's own — one component, so a question
               looks the same wherever it is answered. -->
          <!-- A run a chat started asks in that chat's box as well
               (lib/agentchat.svelte.js); it stands here beside its
               transcript too, so a question from a chat in the archive, or
               from a schedule, always has a place to be answered. -->
          {#if auftrag.state === 'wartet' && auftrag.question?.frage}
            <div class="wartebanner">
              {t('jobs.banner', { agent: agentName(auftrag.agent) })}
            </div>
            <div class="wartefrage">
              <Benutzerfrage
                eng={flaeche.eng}
                frage={auftrag.question}
                antworten={(wert) => frageBeantworten(auftrag, wert)}
              />
            </div>
            {#if !auftrag.generation_id}
              <!-- The run behind the question did not survive the restart.
                   The buttons still work: the answer is carried into the
                   continuation instead of into a call that no longer
                   exists. Said out loud, because the run comes back a minute
                   later rather than picking up mid-sentence. -->
              <p class="warteweg">{t('jobs.frage_nach_neustart')}</p>
            {/if}
          {/if}
        </div>
      {/each}
    {/if}
  {/if}
{/snippet}


<div class="ansicht">
  <!-- A new job: one wide button over the content. -->
  <div class="knopfreihe oben">
    <button class="breitknopf" onclick={() => (zustand.auftragStartenOffen = true)}>
      <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M7 4.5 L19 12 L7 19.5 Z" />
      </svg>
      {t('jobs.starten')}
    </button>
  </div>
  <Modulabschnitte abschnitte={ABSCHNITTE} {inhalt} zweispaltig={flaeche.zweispaltig} />
</div>

<style>
  /* The glass card every group of this view stands on, with its fine
     edge — the same glass the calendar next door wears. */
  .karte {
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
  }

  /* --- the running cards -------------------------------------------- */
  .laufkarte {
    padding: 11px 12px 10px 14px;
  }
  .laufkopf {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .lauftitel {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 0;
    border: none;
    background: none;
    font: inherit;
    font-size: 13px;
    font-weight: 500;
    text-align: left;
    color: var(--text);
    cursor: pointer;
  }
  /* Running is blue, waiting for you is yellow — the dot is the state.
     Round because it is a dot. */
  .laufpunkt {
    flex: none;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--blau);
  }
  .laufpunkt.wartet {
    background: var(--gelb);
  }
  .laufaufgabe {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .laufagent {
    margin: 3px 0 0 16px;
    font-size: 12px;
    color: var(--text-still);
  }
  /* The house context line, set flush under the card's own text. */
  .laufstrich :global(.strich) {
    padding: 8px 0 0 16px;
  }
  /* The view: the button row, then the sections, which scroll. */
  .ansicht {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  /* The report rows: agent carries the weight, the task trails quietly and
     truncates rather than wrapping into a second title. */
  /* A row of wide buttons, all the same size: the new job over the
     content, more and less under the reports. */
  .knopfreihe {
    display: flex;
    gap: 8px;
    margin-top: 8px;
  }
  .knopfreihe.oben {
    flex: none;
    margin: 0;
    padding: 4px var(--rand, 14px) 14px;
  }
  .breitknopf {
    flex: 1 1 0;
    min-width: 0;
    height: 36px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: inherit;
    font-size: 12.5px;
    font-weight: 500;
    cursor: pointer;
    white-space: nowrap;
  }
  .breitknopf:hover { background: var(--glass-hover); }
  /* The files of a report under its row: chips with the document sign and
     the name in the fixed font. */
  .dateien {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 6px;
  }
  .datei-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    max-width: 100%;
    height: 24px;
    padding: 0 9px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: 11.5px var(--schrift-fest);
    cursor: pointer;
  }
  .datei-chip:hover { background: var(--glass-hover); }
  .datei-chip :global(svg) {
    flex: none;
    color: var(--text-leise);
  }
  .datei-chip span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* The report rows: one card, rows parted by a hairline. */
  .zeilen {
    overflow: hidden;
  }
  .bzeile {
    display: flex;
    align-items: center;
    gap: 6px;
    min-height: 50px;
    padding: 9px 12px;
  }
  .bzeile + .bzeile {
    border-top: 1px solid var(--linie);
  }
  .bwas {
    flex: 1;
    min-width: 0;
  }
  .btext {
    display: flex;
    flex-direction: column;
    width: 100%;
    padding: 0;
    border: none;
    background: none;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .beins,
  .bzwei {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .beins {
    font-size: 13px;
    color: var(--text);
  }
  .bzwei {
    font-size: 11.5px;
    color: var(--text-still);
  }
  .bzwei.rot {
    color: var(--rot-text);
  }
  /* Round because it is a dot. */
  .bpunkt {
    flex: none;
    width: 8px;
    height: 8px;
    margin-left: 4px;
    border-radius: 50%;
  }
  /* The chain mark inside an opened row. Belonging is a fact, not a state,
     so it works on brightness — none of the four colours. */
  .bkette {
    margin: 0 0 6px;
    font-size: 11.5px;
    color: var(--text-still);
  }
  /* The cross comes under the hand — on the card the pointer is on, and
     always on a screen without a pointer — red only under the pointer
     itself, and it asks before it deletes. */
  .bweg {
    flex: none;
    border: none;
    background: none;
    color: var(--text-still);
    font-size: 11px;
    line-height: 1;
    padding: 6px 8px;
    margin-right: 6px;
    border-radius: 9px;
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.12s, color 0.12s;
  }
  .bzeile:hover .bweg,
  .bweg:focus-visible {
    opacity: 1;
  }
  @media (hover: none) {
    .bweg { opacity: 1; }
  }
  .bweg:hover {
    color: var(--rot);
  }

  /* Waiting for a person is a STATE, so it may carry the colour — the quiet
     form of it, never the full colour behind text, mixed over the card's
     glass so the banner stays see-through like the card it lies on. */
  .wartebanner {
    margin: 6px 0 0;
    padding: 6px 9px;
    border: none;
    background: color-mix(in srgb, var(--gelb) 12%, var(--glass-card));
    border-radius: 9px;
    font-size: 12px;
    line-height: 1.45;
    color: var(--text);
  }
  .wartefrage {
    margin: 6px 0 4px;
  }
  .warteweg {
    margin: 6px 0 4px;
    font-size: 11.5px;
    line-height: 1.5;
    color: var(--text-still);
  }

  .alauf + .alauf {
    margin-top: 6px;
  }
  /* One step in for a run another run started. The indent IS the chain —
     it says without a word that this card hangs off the one above it. */
  .alauf.kind {
    padding-left: 14px;
  }

  /* The stop, a sign button beside the task: red under the pointer, because
     what it does ends a run. */
  /* The transcript's own head: the stop control, the one place a run is
     stopped. */
  .transcript-head {
    display: flex;
    justify-content: flex-end;
    margin: 6px 0 2px;
  }
  .stopp {
    flex: none;
    width: 26px;
    height: 26px;
    display: grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text-leise);
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }
  .stopp:hover {
    background: color-mix(in srgb, var(--rot) 14%, var(--glass-button));
    color: var(--rot-text);
  }
</style>
