<script>
  import { kurz } from '../lib/tokenzahl.js'
  /* Local models: what runs on this machine, and how it is set — the local
     menu of the window row (ModelleSeite.svelte keeps its frame).

     In the sidebar stands the list of the settings (SettingsNav.svelte),
     the same on every page that carries it; the row chosen in it is this
     page's: "Local models", or one of the six servers. The page itself is
     what is chosen, under the page head. "Local models" shows the quick
     picker as a table and, under it, the parameters of a model picked from
     it. A server shows its sign and name and its window alone: its form, its
     log, or the first-run steps. Both heads carry the facts of the machine. */
  import Menueseite from './Menueseite.svelte'
  import MemoryBar from './MemoryBar.svelte'
  import QuickPickTable from './QuickPickTable.svelte'
  import ServerOverview from './ServerOverview.svelte'
  import Parametertafel from './Parametertafel.svelte'
  import Fensterkopf from './Fensterkopf.svelte'
  import Fenstertafel from './Fenstertafel.svelte'
  import Modellserver from './Modellserver.svelte'
  import Agentserver from './Agentserver.svelte'
  import Einbettungsserver from './Einbettungsserver.svelte'
  import Sprachserver from './Sprachserver.svelte'
  import Bereinigungsserver from './Bereinigungsserver.svelte'
  import Bildserver from './Bildserver.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Standpille from './Standpille.svelte'
  import Startknopf from './Startknopf.svelte'
  import SettingsNav from './SettingsNav.svelte'
  import { api } from '../lib/api.js'
  import { pollWithoutOverlap } from '../lib/pollWithoutOverlap.js'
  import { t, texte } from '../lib/texte.svelte.js'
  import { zustand } from '../lib/zustand.svelte.js'
  import { serverstandHalten, reportServerState } from '../lib/serverstand.svelte.js'
  import { SERVER as SERVER_PAGES } from '../lib/einstellungsliste.js'
  import { modellMarke } from '../lib/anbieterzeichen.js'
  import { modellwahl, auswahlLaden, istAn, schalten, lokale } from '../lib/modelle.svelte.js'
  import { HAUPTMODELL, SLOT_ENDPUNKT } from '../lib/agentenserver.svelte.js'

  /* `offen`: this menu is the one showing. The component stays mounted
     while it is not, so the chosen server survives a look at the cloud
     menu or at a chat; only its markup and its polling stop. */
  let { offen = false } = $props()

  /* What the page shows: "Local models", a clicked model's parameters under
     it, or a server. Clicking never changes what you are chatting with. */
  /* The kinds of server, each with its own row, its own folder and its
     own port. One entry for all of them was how an embedding model ended
     up in the language model's picker and its start ran against a port that
     was already taken. */
  /* The agent server, second in the list — right under the model server,
     because it is the other one that holds a chat model, and the two are
     read one after the other. */
  const AGENT = 'agent'
  const EINBETTUNG = 'einbettung'
  /* The speech server, between the embedding server and the picture one —
     it holds a model the same way the three above it do. */
  const SPRACHE = 'sprache'
  /* The clean-up server, right under the speech server: it is the small
     model that tidies what the speech server heard, and since it starts by
     hand it reads best beside the one it belongs to. */
  const BEREINIGUNG = 'bereinigung'
  const BILD = 'bild'
  /* The page's own name, for "Local models": the table and, where one was
     picked, a model's parameters — no server window. */
  const LOCAL = 'lokal'
  /* The overview of all six servers: one page of its own, no server window. */
  const OVERVIEW = 'overview'
  let gezeigt = $state(LOCAL)
  /* A row of the settings list names what to show — a server, or "Local
     models": read once, then cleared, so the next plain open starts where it
     was left. */
  $effect(() => {
    if (offen && zustand.lokalWunsch) {
      gezeigt = zustand.lokalWunsch
      zustand.lokalWunsch = null
    }
  })

  /* What the other servers report, from the one place the list and the overview
     read their dots from (lib/serverstand.svelte.js): asked for while this page
     stands, on one rhythm. */
  $effect(() => {
    if (!offen) return
    return serverstandHalten()
  })

  /* The agent server's models have no group here: they are no model of the
     chat's choice, so there is nothing for a switch to switch. */
  const modelle = $derived(lokale().filter((m) => m.anbieter !== SLOT_ENDPUNKT))
  /* The agent server's own file stands in the table as a row without a
     switch, so its parameters can be opened from there; it is no model of the
     chat's choice. */
  const agentFiles = $derived(lokale().filter((m) => m.anbieter === SLOT_ENDPUNKT))
  const modell = $derived([...modelle, ...agentFiles].find((m) => m.id === gezeigt) ?? null)
  /* Who made a model, as its row in the quick picker names it. */
  const makerOf = (m) => m.anbieter_name || m.anbieter
  /* The chosen model's head wears the same mark its row in the quick picker
     finds; with none known the head keeps its house sign. */
  const kopfMarke = $derived(modell ? modellMarke(modell.name, makerOf(modell)) : null)
  const anzahlAn = $derived(modelle.filter((m) => istAn(m.id)).length)
  const reise = $derived(modelle.length === 0)

  $effect(() => {
    if (!offen) return
    auswahlLaden()
  })


  /* The runner's report feeds the head and the server list: machine total,
     whether the server runs, on which port, with which speed module. */
  let auskunft = $state(null)
  /* The machine's memory, wired part and total, asked on the runner's beat. */
  let speicher = $state(null)
  const maschineGb = $derived(auskunft?.speicher_gb ?? null)
  const laeuft = $derived(Boolean(auskunft?.laeuft))

  /* A fresh machine has nothing in the folder; a machine with files but no
     running server is a different, quieter state. The two get different
     words below. */
  const ordnerLeer = $derived((auskunft?.modelle?.length ?? 0) === 0)
  $effect(() => {
    if (!offen) return
    let active = true
    const holen = () =>
      Promise.all([
        api.runnerAuskunft().then((a) => {
          // An answer that lands after the page closed is not handed on.
          if (!active) return
          auskunft = a
          /* The model server's dot in the list follows this faster beat. */
          reportServerState('server', a)
        }).catch(() => {}),
        api.speicherBlick().then((a) => (speicher = a)).catch(() => {}),
      ])
    holen()
    const stop = pollWithoutOverlap(holen, 3000)
    return () => {
      active = false
      stop()
    }
  })

  /* Which server's page is shown, or none: the entry of the list of servers
     the chosen name belongs to. Its sign and name head the page. */
  const serverPage = $derived(SERVER_PAGES.find((page) => page.name === gezeigt) ?? null)
  /* What the shown server's page hands up for the head: its start button, the
     short line beside its name and its port. Every page names itself, so what
     a page left behind is never taken for the next one's. */
  let serverHead = $state.raw(null)
  const head = $derived(serverPage && serverHead?.page === gezeigt ? serverHead : null)
  /* The row of the settings list this page stands for. */
  const overview = $derived(gezeigt === OVERVIEW)
  /* The wired memory is measured against the limit the system applies to it,
     and only where none can be read against the machine's whole memory. */
  const wiredTotal = $derived(speicher?.wired_limit_gb ?? speicher?.gesamt_gb ?? maschineGb)
  const currentRow = $derived(overview ? OVERVIEW : serverPage ? `server:${serverPage.name}` : 'lokal')

  const dialektName = (d) =>
    d === 'openai' ? t('modell.eigener_unter') : ({ llama_cpp: 'llama.cpp', mlx: 'MLX' }[d] ?? d)

  /* The quick picker's rows: the models of the chat's choice with their
     switch, then the agent server's own file without one. The server's name
     is the one the window row calls it. */
  const serverName = (m) =>
    m.anbieter === HAUPTMODELL
      ? t('modell.server')
      : m.anbieter === SLOT_ENDPUNKT
        ? t('agentserver.titel')
        : m.anbieter_name || m.anbieter
  const rows = $derived(
    [...modelle, ...agentFiles].map((m) => ({
      id: m.id,
      name: m.name,
      maker: makerOf(m),
      server: serverName(m),
      context: m.context_tokens,
      framework: dialektName(m.dialekt),
      reachable: m.erreichbar,
      switchable: m.anbieter !== SLOT_ENDPUNKT,
      on: istAn(m.id),
    })),
  )
</script>

{#if offen}
  <Menueseite beschriftung={t('menue.lokal')} fuellen={Boolean(modell)} fillsFoot={Boolean(modell)}>
    {#snippet liste()}
      <SettingsNav current={currentRow} />
    {/snippet}

    {#snippet kopf()}
      <!-- The page head: what this tab is, what the machine holds, and where a
           server is shown, its short line and the one button that starts or
           stops it. -->
      <div class="titelblock">
        <div class="markenzeile">
          {#if overview}
            <span class="kasten"><Hauszeichen zeichen="ranking_bars" groesse={22} /></span>
            <h2 class="titel">{t('server_overview.heading')}</h2>
          {:else if serverPage}
            <span class="kasten"><Hauszeichen zeichen={serverPage.zeichen} groesse={22} /></span>
            <h2 class="titel">{t(serverPage.titel)}</h2>
            {#if head?.line}<span class="kurzzeile" title={head.line}>{head.line}</span>{/if}
          {:else}
            <span class="kasten"><Hauszeichen zeichen="raster" groesse={22} /></span>
            <h2 class="titel">{t('einstellungen.lokale_modelle')}</h2>
            {#if !reise}
              <span class="zahlpille"><Standpille farbe="count">{t('modell.aktiv_zahl', { zahl: anzahlAn })}</Standpille></span>
            {/if}
          {/if}
        </div>
      </div>
      <!-- The wired memory as one bar, and beside it where the server answers.
           A dash for the port while nothing runs, so the line does not jump
           when a server comes up. The overview carries the bar in its own body
           instead. -->
      {#if !overview}
        <div class="aktionen">
          <MemoryBar wired={speicher?.wired_gb ?? null} total={wiredTotal} />
          <div class="fakten">
            <span>{t('kopf.port')}: {serverPage ? (head?.port ?? '-') : laeuft ? (auskunft?.port ?? '-') : '-'}</span>
          </div>
          {#if head?.tat}
            <Startknopf text={head.tat.text} punkt={head.tat.punkt} gesperrt={head.tat.gesperrt} onTat={head.tat.onTat} />
          {/if}
        </div>
      {/if}
    {/snippet}

    {#snippet inhalt()}
      {#if overview}
        <ServerOverview wired={speicher?.wired_gb ?? null} total={wiredTotal} />
      {:else if serverPage}
        {#if gezeigt === AGENT}
          <Agentserver bind:head={serverHead} />
        {:else if gezeigt === EINBETTUNG}
          <Einbettungsserver bind:head={serverHead} />
        {:else if gezeigt === SPRACHE}
          <Sprachserver bind:head={serverHead} />
        {:else if gezeigt === BEREINIGUNG}
          <Bereinigungsserver bind:head={serverHead} />
        {:else if gezeigt === BILD}
          <Bildserver bind:head={serverHead} />
        {:else}
          <Modellserver bind:head={serverHead} />
        {/if}
      {:else}
        <QuickPickTable
          {rows}
          chosen={gezeigt}
          emptyText={t(ordnerLeer ? 'modell.kein_modell_satz' : 'modell.nichts_laeuft')}
          onchoose={(id) => (gezeigt = id)}
          onswitch={(id, an) => schalten(id, an)}
        />
        {#if modell}
          <Fenstertafel grow>
            <Fensterkopf
              marke={kopfMarke}
              zeichen="paket"
              titel={modell.name}
              unter={(modell.context_tokens ? `${kurz(modell.context_tokens, texte.sprache)} ${t('modell.kontext')} · ` : '')
                + dialektName(modell.dialekt)}
              standfarbe={modell.erreichbar ? 'gruen' : 'still'}
              standtext={modell.erreichbar ? t('status.erreichbar') : t('status.nicht_erreichbar')}
            />
            <!-- One line, and brightness only. The mismatch is a fact about
                 this entry, not a state of the server — the server is
                 answering perfectly well. Nothing is offered to fix it either:
                 the configuration is the user's own file, and a program that
                 edits it behind their back is worse than one that points at
                 the mistake. -->
            {#if modell.dialekt_verdacht}
              <p class="verdachtszeile">{t('modell.dialekt_verdacht')}</p>
            {/if}
            <Parametertafel {modell} />
          </Fenstertafel>
        {/if}
      {/if}
    {/snippet}
  </Menueseite>
{/if}

<style>
  .titelblock {
    flex: 1 1 260px;
    min-width: 0;
  }
  .markenzeile {
    display: flex;
    align-items: center;
    gap: 14px;
    color: var(--text);
    min-width: 0;
  }
  /* The server's short line beside its name: quiet, and the one thing that
     gives way — the name and the button always stand whole. */
  .kurzzeile {
    min-width: 0;
    margin-left: 4px;
    font-size: 12.5px;
    color: var(--text-leise);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* The page's mark: the sign in a 40 px box of button glass. */
  .kasten {
    width: 40px;
    height: 40px;
    flex: none;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 9px;
    /* The glass of a button with its fine line, drawn inside the box. */
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  .titel {
    flex: none;
    white-space: nowrap;
    margin: 0;
    font-size: var(--schrift-seitentitel);
    font-weight: 400;
    line-height: 1.3;
  }
  /* 12 px from the title: the head's gap less two. Where the head runs out
     of room the pill gives way, so it never paints over the memory bar. */
  .zahlpille {
    display: inline-flex;
    min-width: 0;
    overflow: hidden;
    margin-left: -2px;
  }
  .aktionen {
    flex: none;
    display: flex;
    align-items: center;
    gap: 18px;
  }
  .fakten {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12.5px;
    color: var(--text-leise);
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }

  /* No colour word anywhere in here. Yellow would read as "wait", red as
     "broken", and this is neither — it is a fact about the entry, which the
     house answers with brightness. */
  .verdachtszeile {
    margin: -16px 0 0;
    font-size: 11.5px;
    line-height: 1.5;
    color: var(--text-still);
  }

  @media (max-width: 720px) {
    .aktionen {
      flex-wrap: wrap;
    }
  }
</style>
