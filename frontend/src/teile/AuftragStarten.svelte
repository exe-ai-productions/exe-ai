<script>
  /* Start dialog for jobs — the rest of 6.5.

     Built from the house's one window kit: frame from
     `Fenster`, task field from `WachsendesFeld` (grows with the text,
     monospace, no scrollbars — same mechanics as in the system-prompt
     window), selection rows from `StilleWahl`. This component now only
     assembles and starts.

     Pick an agent (only playable ones — broken files don't show up in
     /agents anyway, see 6.3), pick one of the two servers a run may take,
     type in the task. After starting, the view switches to the jobs
     section and unfolds the new card right away.

     The button to open it sits in the sidebar — where "Neuer Chat" is
     for the chats. That's why the open state lives in the shared state,
     not here. */
  import Auftragfenster from './Auftragfenster.svelte'
  import StilleWahl from './StilleWahl.svelte'
  import Startordnerpillen from './Startordnerpillen.svelte'
  import Klappwahl from './Klappwahl.svelte'
  import {
    berechtigungsmodus, berechtigungsmodusLaden, berechtigungsmodusSetzen, modusOptionen,
  } from '../lib/berechtigungsmodus.svelte.js'
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { zustand, auftraegeLaden, melde, seiteZeigen } from '../lib/zustand.svelte.js'
  import { HAUPTMODELL, SLOT_ENDPUNKT } from '../lib/agentenserver.svelte.js'
  import { anbieten } from '../lib/arbeitsleiste.svelte.js'

  let { offen = $bindable(false) } = $props()

  const modusListe = $derived(modusOptionen('agent'))

  let agenten = $state([])
  let agentName = $state('')
  let aufgabe = $state('')
  /* The server standing in the row: one of the two below, and nothing else.
     Its value goes out unchanged as the run's `endpoint_id` — which of the
     two really takes the run is read off the server, not decided here (see
     `lauf`). */
  let endpointId = $state(SLOT_ENDPUNKT)
  let ordner = $state([])
  let startet = $state(false)
  /* What the server answers for each of the two entries: the model a run
     would land on if this entry stood in the row. Read, not worked out — the
     window used to compute this itself from the reachable list and its own
     reading of the tool rule, and the two could part company, naming an
     endpoint the run then never went to, a paid provider among them.
     Filled by the effect below, one answer per entry. */
  let lauf = $state({})
  /* And the same question for the row's own entry, asked WITHOUT the tool
     rule — the answer the row's server would give if the tools did not
     matter. It is what tells a detour from a fallback (see `umgeleitet`). */
  let laufOhne = $state(undefined)

  const agent = $derived(agenten.find((a) => a.name === agentName) || null)

  /* The two servers a run may take, and no others: the main
     model first, the agent server below it, both under the names the house
     already uses for them — the agent server's own window names the main
     model the same way. This window starts an AGENT, and an agent runs on
     one of these two. */
  const SERVER = [HAUPTMODELL, SLOT_ENDPUNKT]

  /* The row offers what the SERVER answers for each of the two: the model a
     run would land on if this entry stood there. So the row says what
     happens instead of promising something — with the agent server not
     answering, its own second line names the main model that takes over. */
  const auswahl = $derived([
    {
      id: HAUPTMODELL,
      name: t('modell.agentenmodell_hauptmodell'),
      quelle: lauf[HAUPTMODELL]?.name,
    },
    {
      id: SLOT_ENDPUNKT,
      name: t('agentserver.titel'),
      quelle: lauf[SLOT_ENDPUNKT]?.name,
    },
  ])

  /* Which of the two entries the row stands on, by name — the note below
     needs it, and so does the start button. */
  const zeilenName = $derived(auswahl.find((e) => e.id === endpointId)?.name || '')

  /* Neither server answering means no run at all: the start would refuse it
     (400), and saying so here is more honest than a button that fails after
     the click.

     "Not answered YET" is not that case — the two answers come over the wire
     while the window is already open, and a window that says "no model" for
     that half second says something untrue. So this waits for both. */
  const keinModell = $derived(
    SERVER.every((id) => lauf[id] && lauf[id].endpoint_id !== undefined) &&
      !SERVER.some((id) => lauf[id]?.endpoint_id),
  )

  $effect(() => {
    if (!offen) return
    agentName = ''
    aufgabe = ''
    ordner = []
    /* The agent server stands in the row whenever the window opens — a run
       starts on it, which is what it is there for — and the main
       model takes over when it is not there: the server's own decision, not
       this window's. */
    endpointId = SLOT_ENDPUNKT
    lauf = {}
    laufOhne = undefined
    api
      .agenten()
      .then((daten) => {
        agenten = daten
        /* The play mark on an agent tile opens this dialog FOR that agent:
           the wish is read once and cleared, so the next plain open starts
           neutral again. */
        const gewuenscht = zustand.auftragStartenAgent
        zustand.auftragStartenAgent = null
        if (gewuenscht && daten.some((a) => a.name === gewuenscht)) {
          agentName = gewuenscht
        } else if (daten.length) {
          agentName = daten[0].name
        }
      })
      .catch(() => melde(t('agenten.nicht_geladen'), 'fehler'))
    if (!berechtigungsmodus.geladen) berechtigungsmodusLaden()
  })

  /* Does this agent work through tools at all? The same question the server
     asks itself (`benutzt_werkzeuge`): `tools:` left out of the front matter
     means every approved tool, an explicit empty list is the deliberate
     opposite. `/agents` carries the list, so this is read, not fetched. */
  const benutztWerkzeuge = $derived(Boolean(agent) && agent.tools?.length !== 0)
  const werkzeugeMoeglich = $derived(benutztWerkzeuge && Boolean(zustand.features?.mcp))

  /* What each of the two entries would lead to — asked of the server, and
     asked for BOTH of them: the menu carries a second line under each, and a
     line that is only right for the one nobody picked is worse than none.

     Deliberately not derived from `lauf` (that would be a circle: this effect
     writes what would read it) — the two ids are a constant.

     Read and not used, the line below: the reachable list is reloaded on a
     clock (App.svelte, every 30 s), and a server that comes up while the
     window stands open has to be asked again — without it the row keeps
     saying "no model reachable" for a server that is there. */
  $effect(() => {
    if (!offen) return
    void zustand.modelle.length
    const braucht = werkzeugeMoeglich
    const reihe = endpointId
    for (const id of SERVER) {
      api
        .laufmodell(id, braucht)
        .then((a) => {
          lauf = { ...lauf, [id]: { endpoint_id: a.endpoint_id || '', name: a.name || '' } }
        })
        .catch(() => {
          /* NOT "nothing answers": a question that could not be asked leaves
             the row as it is, and an unknown is not a no. */
          lauf = { ...lauf, [id]: null }
        })
    }
    /* The same question once more without the tool rule. The two answers
       differ exactly when that rule moved the run — which is what the note
       below is about, read from the same place the run is booked instead of
       from the reachable list's own copy of it. */
    api
      .laufmodell(reihe, false)
      .then((a) => {
        if (endpointId === reihe) laufOhne = a.endpoint_id || ''
      })
      .catch(() => {
        if (endpointId === reihe) laufOhne = undefined
      })
  })

  /* Whether the run leaves the server the row names — and only for the one
     reason the note below is about: this agent needs tools and the server in
     the row cannot give them. A row whose server is not there is not
     a detour, it is the fallback the row's second line already names —
     and there the two answers above agree. */
  const umgeleitet = $derived(
    Boolean(lauf[endpointId]?.endpoint_id) &&
      Boolean(laufOhne) &&
      laufOhne !== lauf[endpointId].endpoint_id,
  )

  /* What is missing names the page that supplies it: this dialog closes,
     the page opens. Both open states live in the shared state precisely so
     one window can open the other. */
  function agentAnlegen() {
    offen = false
    zustand.promptStart = 'agent:'
    seiteZeigen('prompt')
  }
  function modelleOeffnen() {
    offen = false
    seiteZeigen('lokal')
  }

  async function starten() {
    if (!agentName || !aufgabe.trim() || !endpointId) return
    startet = true
    try {
      const daten = {
        agent: agentName,
        task: aufgabe.trim(),
        /* The server the row stands on, as this run's pick. Both entries are
           servers this program starts itself, and the server reads a pick of
           the agent server as the first entry of its own order
           (`agentenmodellwahl.lauf_kennung`) — so a preselection nobody made
           can never be what refuses a run: the main model takes over when the
           agent server is not there. */
        endpoint_id: endpointId,
        folders: ordner.length ? ordner : null,
      }
      const auftrag = await api.auftragStarten(daten)
      offen = false
      /* The run shows in the work rail's agents module — brought forward
         with the fresh row selected, so the start is seen, not believed. */
      await auftraegeLaden()
      zustand.auftragAusgewaehlt = auftrag.id
      anbieten('agenten')
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    } finally {
      startet = false
    }
  }
</script>

{#snippet kopf()}
  {#if keinModell}
    <!-- What is missing, as a row like the others: the field and its state.
         The way to fix it stands in the foot. -->
    <div class="zeile">
      <span class="beschriftung">{t('jobs.modell_waehlen')}</span>
      <span class="fehlt">{t('fehler.kein_modell_verfuegbar')}</span>
    </div>
  {:else if !agenten.length}
    <div class="zeile">
      <span class="beschriftung">{t('jobs.agent_waehlen')}</span>
      <span class="fehlt">{t('jobs.keine_agenten')}</span>
    </div>
  {:else}
    <!-- Quiet rows like the model picker in the input bar: no frame,
         just name and chevron. -->
    <div class="zeile">
      <span class="beschriftung">{t('jobs.agent_waehlen')}</span>
      <StilleWahl
        bind:wert={agentName}
        eintraege={agenten}
        leerText={t('jobs.keine_agenten')}
        beschriftung={t('jobs.agent_waehlen')}
      />
    </div>

    <div class="zeile">
      <span class="beschriftung">{t('jobs.modell_waehlen')}</span>
      <StilleWahl
        bind:wert={endpointId}
        eintraege={auswahl}
        leerText={t('fehler.kein_modell_verfuegbar')}
        beschriftung={t('jobs.modell_waehlen')}
      />
    </div>

    {#if umgeleitet}
      <!-- What the button about to be pressed really does. The row above
           shows the server it stands on; the run goes elsewhere because this
           agent needs tools and that server has none. Both are true, and only
           one of them was on screen. -->
      <p class="umleitung">
        <svg viewBox="0 0 64 64" width="15" height="15" fill="none" stroke="currentColor"
             stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M20 8 V56" stroke-width="5" />
          <path d="M20 12 C36 12 44 15 44 22" stroke-width="4.5" />
          <rect x="37" y="22" width="14" height="14" rx="3" stroke-width="5" />
          <path d="M44 36 C44 43 36 50 20 50" stroke-width="4.5" />
        </svg>
        <span>{t('jobs.laeuft_auf', {
          modell: lauf[endpointId]?.name,
          feld: zeilenName,
        })}</span>
      </p>
    {/if}
  {/if}
{/snippet}

{#snippet unterFeld()}
  <!-- The folders this job may read. Picked here they win over the agent's
       own; left empty, the agent's file decides. A job has no chat, so the
       permission is set here or in the agent, nowhere else. -->
  <div class="ordnerzeile">
    <span class="beschriftung">{t('jobs.ordner_titel')}</span>
    <Startordnerpillen bind:ordner />
  </div>
{/snippet}

{#snippet fussLinks()}
  <!-- The page that supplies what is missing, first in the left corner. -->
  {#if keinModell}
    <button class="button" onclick={modelleOeffnen}>{t('modell.feld_modell')}</button>
  {:else if !agenten.length}
    <button class="button" onclick={agentAnlegen}>{t('agenten.titel')}</button>
  {/if}
  <!-- The permission mode for agent runs — Tor 3. Left corner: it belongs
       to the run about to start, not to the accept/decline pair on the
       right. -->
  <Klappwahl
    optionen={modusListe}
    wert={berechtigungsmodus.agent}
    aufWahl={(neu) => berechtigungsmodusSetzen('agent', neu)}
    beschriftung={t('berechtigungen.modus_beschriftung')}
    kompakt
  />
{/snippet}

<Auftragfenster
  bind:offen
  titel={t('jobs.starten')}
  werkzeugnamen={agent ? agent.tools ?? null : []}
  bind:text={aufgabe}
  feldbeschriftung={t('jobs.aufgabe_platzhalter')}
  startbar={Boolean(agentName && endpointId && aufgabe.trim() && !startet)}
  aufStarten={starten}
  aufAbbrechen={() => (offen = false)}
  {kopf}
  {unterFeld}
  {fussLinks}
/>

<style>
  /* A missing model or agent is a state that stops the start: red. */
  .fehlt {
    font-size: 13px;
    color: var(--rot-text);
  }
  .zeile {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    padding: 8px 0;
  }
  .beschriftung {
    font-size: 13px;
  }
  /* Directly under the row it corrects, quiet but not grey-on-grey: it is
     not a footnote, it is what the start button does. */
  .umleitung {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    margin: -2px 0 4px;
    font-size: 12px;
    line-height: 1.5;
    color: var(--text-still);
  }
  .umleitung svg {
    flex: none;
    margin-top: 1px;
  }
  /* Label above, pills below — the pills wrap, so a side-by-side row would
     break as soon as a second folder joins. */
  .ordnerzeile {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px 0 2px;
  }
  /* The way to what is missing, in the foot's left corner: the house
     button (`.button`, stil/global.css), the same as "Cancel" beside it, so
     the foot reads as one row of equals. Only the gap that keeps it off
     the permission picker is this window's own. */
  .button {
    margin-right: 8px;
  }
</style>
