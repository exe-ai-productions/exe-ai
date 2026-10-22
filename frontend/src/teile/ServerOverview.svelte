<script>
  /* The overview of the local servers: what each one is doing, on which port,
     with which model, and the button that starts or stops it without opening
     its window — then a table of the MCP servers that are set up, each with
     its logo and the state its card on the MCP page says.

     The six servers and their order are the settings list's (`SERVER`); what
     each says comes from the report the list already keeps
     (lib/serverstand.svelte.js). The chosen model is the one a start would
     load (`selected_model`), also while the server stands; `modell` stays the
     file that runs and is what the windows read it as. A start goes out the
     way the window's own goes: on what is stored (lib/serverControl.js).

     `wired` and `total`: the wired memory and the limit the system applies to
     it, in gigabytes, for the bar above the table. */
  import { t } from '../lib/texte.svelte.js'
  import { SERVER } from '../lib/einstellungsliste.js'
  import { serverstand, refreshServerState } from '../lib/serverstand.svelte.js'
  import { toggleServer } from '../lib/serverControl.js'
  import { isBlocked, overviewRow } from '../lib/serverOverviewRows.js'
  import { agentenmodell } from '../lib/agentenserver.svelte.js'
  import { melde } from '../lib/zustand.svelte.js'
  import { api } from '../lib/api.js'
  import { openSettingsPage } from '../lib/settingsrow.js'
  import { cardsOf, zustand, setUpCards, stateText, punktFarbe, titelVon, logoVon, eigenLogoVon, schluesselVon } from '../lib/mcpCards.js'
  import Hauszeichen from './Hauszeichen.svelte'
  import OwnerMark from './OwnerMark.svelte'
  import MemoryBar from './MemoryBar.svelte'
  import Startknopf from './Startknopf.svelte'

  let { wired = null, total = null } = $props()

  /* The servers whose start or stop is under way: their button waits. */
  let busy = $state({})

  /* The MCP servers: the two answers the MCP page reads, nothing new in the
     service. A read that fails says so, as the MCP page does, and leaves the
     table without the dash: the dash says "none set up" and is only true of an
     answer that came. */
  let mcpEntries = $state([])
  let mcpStatus = $state({})
  let mcpLoaded = $state(false)
  async function loadMcp() {
    try {
      const [servers, oauth] = await Promise.all([api.serverUebersicht(), api.oauthStatus()])
      mcpEntries = servers
      mcpStatus = Object.fromEntries(oauth.map((s) => [s.server, s]))
      mcpLoaded = true
    } catch (error) {
      melde(String(error.message || error), 'fehler')
    }
  }
  $effect(() => {
    loadMcp()
  })
  const mcpRows = $derived(
    setUpCards(cardsOf(mcpEntries), mcpStatus).map((card) => {
      const stand = zustand(card, mcpStatus)
      return {
        key: schluesselVon(card),
        title: titelVon(card),
        logo: logoVon(card),
        ownLogo: eigenLogoVon(card),
        text: stateText(card, stand, t),
        color: punktFarbe(stand),
      }
    }),
  )

  const rows = $derived(
    SERVER.map((server) => ({
      ...overviewRow(server, serverstand[server.name], {
        busy: Boolean(busy[server.name]),
        agentLoading: Boolean(agentenmodell.laedt),
      }),
      report: serverstand[server.name],
    })),
  )

  async function toggle(row) {
    if (busy[row.name]) return
    busy[row.name] = true
    try {
      // What the server is doing now decides between start and stop: the
      // list's own round may be fifteen seconds old, and a server started
      // elsewhere in between would be started again.
      await refreshServerState()
      const report = serverstand[row.name]
      if (!isBlocked(row.name, report, { agentLoading: Boolean(agentenmodell.laedt) })) {
        await toggleServer(row.name, report)
      }
    } catch (error) {
      melde(String(error.message || error), 'fehler')
    } finally {
      // The button waits until the state it caused is read.
      try {
        await refreshServerState()
      } finally {
        busy[row.name] = false
      }
    }
  }
</script>

<div class="overview">
  <MemoryBar inline {wired} {total} />

  <section class="block">
    <h3 class="tafelkopf">{t('server_overview.local_servers')}</h3>
    <div class="card" role="table" aria-label={t('server_overview.local_servers')}>
      <div class="row head" role="row">
        <span role="columnheader">{t('modell.spalte_server')}</span>
        <span role="columnheader">{t('server_overview.status')}</span>
        <span role="columnheader">{t('modell.feld_port')}</span>
        <span role="columnheader">{t('modell.spalte_modell')}</span>
        <span role="columnheader"></span>
      </div>
      {#each rows as row (row.name)}
        <div class="row line" role="row">
          <span class="name" role="cell">
            <span class="tile" aria-hidden="true"><Hauszeichen zeichen={row.zeichen} groesse="gross" /></span>
            <span class="text">{t(row.titel)}</span>
          </span>
          <span class="state {row.state}" role="cell">
            {#if row.state === 'failed'}{t('status.fehler')}{:else if row.state === 'active'}{t('einstellungen.aktiv')}{:else}{t('server_overview.inactive')}{/if}
          </span>
          <span class="cell" role="cell">{row.port ?? '-'}</span>
          <span class="model" role="cell">
            {#if row.model}
              <OwnerMark mark={row.mark} letter={row.letter} size={18} />
            {/if}
            <span class="text">{row.model || '-'}</span>
          </span>
          <span class="action" role="cell">
            <Startknopf
              text={t(row.running ? 'modell.server_anhalten' : 'modell.server_starten')}
              punkt={row.running ? 'gruen' : 'still'}
              gesperrt={row.blocked}
              onTat={() => toggle(row)}
            />
          </span>
        </div>
      {/each}
    </div>
  </section>

  <section class="block">
    <h3 class="tafelkopf">{t('server_overview.mcp_heading')}</h3>
    <!-- A list of buttons, each a way in to the MCP page; its head stands on the
         same tracks as the table above, so Status stands over Status. -->
    <div class="card" role="group" aria-label={t('server_overview.mcp_heading')}>
      <div class="row head" aria-hidden="true">
        <span>{t('modell.spalte_server')}</span>
        <span>{t('server_overview.status')}</span>
        <span></span>
        <span></span>
        <span></span>
      </div>
      {#each mcpRows as row (row.key)}
        <button class="row line link" onclick={() => openSettingsPage('tools')}>
          <span class="name">
            <span class="mcplogo" aria-hidden="true">
              {#if row.logo}
                <svg viewBox={row.logo.vb} width="24" height="24">{@html row.logo.html}</svg>
              {:else if row.ownLogo}
                <img src={row.ownLogo} width="24" height="24" alt="" />
              {:else}
                <Hauszeichen zeichen="plug" groesse={24} />
              {/if}
            </span>
            <span class="text">{row.title}</span>
          </span>
          <span class="state wide {row.color}">{row.text}</span>
          <span class="chevron" aria-hidden="true"><Hauszeichen zeichen="chevron_right" groesse="klein" /></span>
        </button>
      {/each}
      {#if mcpLoaded && !mcpRows.length}
        <p class="empty">-</p>
      {/if}
    </div>
  </section>
</div>

<style>
  .overview {
    display: flex;
    flex-direction: column;
    gap: 28px;
  }
  .block {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .tafelkopf {
    margin: 0;
  }
  /* A card on the page: card glass with its fine line, as every card of the
     server windows. */
  .card {
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    border-radius: 9px;
    overflow: hidden;
  }
  .row {
    display: grid;
    grid-template-columns: minmax(0, 2.2fr) minmax(0, 0.9fr) minmax(0, 0.7fr) minmax(0, 2.2fr) 96px;
    align-items: center;
    gap: 12px;
    padding: 0 16px;
  }
  /* The type of the drawing: heads small and half-bold in the quiet text
     colour; names half-bold, port and model plain, those in the text colour. */
  .head {
    min-height: 34px;
    font-size: 11px;
    font-weight: 600;
    color: var(--text-leise);
  }
  .line {
    min-height: 56px;
    border-top: 1px solid var(--linie);
    font-size: 13px;
  }
  .name {
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
    font-weight: 600;
    color: var(--text);
  }
  /* The server's sign in a 32 px tile of card glass, as the list's rows carry them. */
  .tile {
    flex: none;
    width: 32px;
    height: 32px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
  }
  .text {
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* The state is a word in its colour — no box, no dot. */
  .state {
    font-weight: 500;
  }
  .state.active {
    color: var(--gruen-text);
  }
  .state.inactive {
    color: var(--text-still);
  }
  .state.failed,
  .state.rot {
    color: var(--rot-text);
  }
  .state.gruen {
    color: var(--gruen-text);
  }
  /* An MCP row has nothing in the port and model columns, so its state takes
     them: a long word with the names of missing keys stays on one line. */
  .state.wide {
    grid-column: 2 / 5;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .state.still {
    color: var(--text-still);
  }
  .cell {
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-weight: 400;
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .model {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
    font-weight: 400;
    color: var(--text);
  }
  /* A column of one width for both words of the button, so the cells before
     it do not move when a server comes up. */
  .action {
    display: inline-flex;
    justify-content: flex-end;
  }
  /* An MCP row: a whole-row button, the way in at its right end; its logo
     bare, 24 px, as on the MCP page. */
  .link {
    width: 100%;
    border: none;
    border-top: 1px solid var(--linie);
    background: none;
    color: var(--text);
    font: inherit;
    font-size: 13px;
    text-align: left;
    cursor: pointer;
  }
  .link:hover {
    background: var(--glass-hover);
  }
  .mcplogo {
    flex: none;
    width: 24px;
    height: 24px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--text);
  }
  .mcplogo img {
    border-radius: 4px;
  }
  .chevron {
    display: inline-flex;
    justify-content: flex-end;
    color: var(--text-still);
  }
  .empty {
    margin: 0;
    padding: 12px 16px;
    font-size: 12px;
    color: var(--text-still);
    border-top: 1px solid var(--linie);
  }
</style>
