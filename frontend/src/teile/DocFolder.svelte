<script>
  /* The doc folder — every file in one place, as one of the tools of the
     rail beside the pictures.

     One list from the service (app/docfolder.py): what the person dropped
     into the dock, what agents and cron jobs delivered, what was uploaded
     into chats, and what a tool or a command wrote into a chat's own
     folder. In a chat it holds that chat's files and no other chat's;
     on the start page, with no chat open, every file. The one list of
     choices — on the start page only — narrows by who brought a file and
     by project; the service does the narrowing, so what is shown and what
     is asked for can never disagree. A file an agent delivered wears the
     agent mark at its document, a cron job's the stopwatch; the person's
     own files stay without one.

     It looks like the pictures next door on purpose: one row on top — the
     chooser (only on the start page), then open, move and add — the
     heading over the files, then the wall — square tiles of one size, from
     the shared wall (stil/tiles.css). What stands UNDER a tile is this
     menu's own: the file's name alone, centred, in the fixed font the
     numbers under an answer wear. Where it came from and its project stand
     beside its name in the reader.

     Every tile shows its file: a picture itself, a text file its first
     lines as text (in the browser as in the app), everything else the
     preview the app shell draws (a PDF's first page) or, where there is
     none, the page sign with the folded corner.

     A file dropped on the folder goes onto the dock — in a chat into that
     chat's own folder — and the row's folder button shows that same place;
     a tile dragged onto the chat attaches its file. A tile clicked opens
     its file in the reader (Bildschau.svelte). */
  import { untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import { docFolderFilters as filters, ORIGINS } from '../lib/docFolderFilters.svelte.js'
  import { neuigkeit } from '../lib/ereignisstrom.svelte.js'
  import { shellPreview, shellPreviews } from '../lib/thumbnails.js'
  import { agentName } from '../lib/agentmarke.js'
  import { t } from '../lib/texte.svelte.js'
  import { frage, laufVon, melde, zustand } from '../lib/zustand.svelte.js'
  import { bildZeigen, showPage } from '../lib/bildschau.svelte.js'
  import { dateiart } from '../lib/dateiarten.js'
  import { fileStart } from '../lib/fileStart.js'
  import Agentenmarke from './Agentenmarke.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Speicherortzeile from './Speicherortzeile.svelte'

  /* The shell's preview, drawn at twice the tile's size for a sharp tile on
     a dense screen, and at the size of the reader's page for that one. */
  const CARD_PREVIEW = { width: 280, height: 280 }
  const BIG_PREVIEW = { width: 900, height: 1200 }

  /* The folder shows every file in one wall; who brought a file and its
     project stand as a choice, and only on the start page. Both are kept
     in lib/docFolderFilters.svelte.js. */
  let projectsOpen = $state(false)
  let files = $state([])
  let previews = $state({})
  let dropTarget = $state(false)

  /* The chooser's entries: every project first, then the names. */
  const projectEntries = $derived([
    { wert: '', text: t('docfolder.all_projects') },
    ...zustand.projects.map((p) => ({ wert: p.id, text: p.name })),
  ])
  /* A chosen project that is archived or deleted meanwhile is no filter
     any more: the list and the label fall back to every project. The kept
     choice itself is left alone, so a project that comes back brings its
     filter back with it. */
  const chosen = $derived(
    projectEntries.find((entry) => entry.wert === filters.project) ?? projectEntries[0],
  )
  const project = $derived(chosen.wert)

  /* Whose files: the three origins on top of the same list. One of them
     chosen narrows to it, the same one chosen again shows everyone's. */
  const originEntries = $derived(
    Object.entries(ORIGINS).map(([value, key]) => ({ wert: value, text: t(key) })),
  )
  const origin = $derived(Object.hasOwn(ORIGINS, filters.origin) ? filters.origin : '')
  function originPick(value) {
    filters.origin = filters.origin === value ? '' : value
    projectsOpen = false
  }

  /* The button names what is chosen: the project, and before it the origin
     where one narrows the wall. */
  const projectLabel = $derived(
    origin ? `${t(ORIGINS[origin])} · ${chosen.text}` : chosen.text,
  )

  /* `quiet` for the asks nobody pressed a button for: a restarting service
     must not answer the clock with a toast every few seconds, and the list
     already shown stays. */
  /* The open chat, or none on the start page. In a chat the list of
     choices does not stand, so neither choice is sent: every file there is
     of that chat's project, and nothing may narrow a wall unseen. */
  const chat = $derived(zustand.aktiverChat ?? '')

  /* Only the newest ask may fill the list: switching chats while an answer
     for the previous one is still on its way must not let that answer land
     last and show the other chat's files. */
  let asked = 0
  async function load(quiet = false) {
    const ask = ++asked
    try {
      const answer = await api.docFolder(chat ? { chat } : { project, origin })
      if (ask === asked) files = answer
    } catch (error) {
      if (quiet || ask !== asked) return
      files = []
      melde(error.message, 'fehler')
    }
  }

  /* Asked again whenever a choice or the open chat changes — and on
     mounting, which is the moment the module is shown: a file delivered
     since the last look appears without a reload. */
  $effect(() => {
    void project
    void origin
    void chat
    untrack(() => load())
  })

  /* And quietly whenever the live line says the jobs changed — a run that
     ended may have delivered something. */
  let seenNews = untrack(() => neuigkeit.auftraege)
  $effect(() => {
    const news = neuigkeit.auftraege
    if (news === seenNews) return
    seenNews = news
    untrack(() => load(true))
  })

  /* Nothing announces a file arriving while a run is still going, so the
     list is asked again every few seconds while one is — the cadence the
     agents view keeps for its step logs — and not at all while none is.
     A run is a job anywhere, or the open chat's own answer: its tools write
     into the chat's folder just as a job's do. */
  const answering = $derived(Boolean(laufVon(chat)))
  const running = $derived(
    answering || zustand.auftraege.some((job) => job.state === 'laeuft' || job.state === 'wartet'),
  )
  $effect(() => {
    if (!running) return
    const clock = setInterval(() => load(true), 3000)
    return () => clearInterval(clock)
  })

  /* And once more when the chat's answer is over. A job's ending comes down
     the live line; an answer's does not, and what it wrote in its last
     moments would fall between two asks and stay unseen. Only for an
     answer that ended in the chat still open: leaving a chat in mid-answer
     is a change of chat, and that asks for itself. */
  let answeredIn = ''
  $effect(() => {
    const now = answering ? chat : ''
    if (answeredIn && answeredIn === chat && !now) untrack(() => load(true))
    answeredIn = now
  })

  function isPicture(file) {
    return (file.type || '').startsWith('image/')
  }

  /* The one type the reader shows in a frame: the browser's own viewer
     draws its pages, as for the card in a chat. */
  function isPdf(file) {
    return (file.type || '').toLowerCase() === 'application/pdf'
  }

  /* The shell's preview for everything the page cannot draw itself
     (lib/thumbnails.js keeps them for the session and asks a few at a
     time); an answer of nothing leaves the page sign. */
  async function preview(file, size) {
    const key = `${file.path}|${size.width}`
    if (!shellPreviews() || !file.path || isPicture(file) || isText(file) || key in previews) return
    previews = { ...previews, [key]: '' }
    // The shell takes a whole address, never a path of the page's own.
    const address = new URL(api.docFolderAddress(file.path), location.href).href
    const image = await shellPreview(key, address, file.name, size)
    previews = { ...previews, [key]: image }
  }

  function previewOf(file, size) {
    return previews[`${file.path}|${size.width}`] || ''
  }

  $effect(() => {
    for (const file of files) untrack(() => preview(file, CARD_PREVIEW))
  })

  /* A text file's tile shows its first lines. Only what a tile can show is
     read: the rail is at least 314 px wide, so the wall has two columns or
     more and a tile is at most 148 px wide (one more pixel and a further
     column comes in). That tile holds 251 bytes of running text at 8.5 px in
     the house font (175 of code) — measured in the browser. A smaller tile
     shows less of the same beginning. */
  const START_BYTES = 251
  let starts = $state({})
  function startKey(file) {
    return `${file.path}|${file.size}`
  }
  async function loadStart(file) {
    const key = startKey(file)
    if (!file.path || !isText(file) || key in starts) return
    starts = { ...starts, [key]: '' }
    const text = await fileStart(key, api.docFolderAddress(file.path), START_BYTES)
    starts = { ...starts, [key]: text }
  }
  $effect(() => {
    for (const file of files) untrack(() => loadStart(file))
  })
  /* Whether a tile shows text: a text file whose beginning could be read. */
  function showsText(file) {
    return Boolean(file.path) && isText(file) && starts[startKey(file)] !== null
  }
  /* Running text in the house font, everything else — code, data — in the
     fixed one. */
  const PROSE_ENDINGS = new Set(['md', 'markdown', 'txt', 'log'])
  function isCode(file) {
    return !PROSE_ENDINGS.has(endingOf(file))
  }

  /* Who a file is from — under the tile without the project, in the reader
     with it (the project chooser leaves an archived project out, like the chat
     list does; the file still names it). */
  function originOf(file) {
    return file.origin === 'user'
      ? t('docfolder.by_you')
      : t('docfolder.by_agent', { agent: agentName(file.agent) || '—' })
  }
  function originLine(file) {
    const who = originOf(file)
    const name = projectName(file)
    return name ? `${who} · ${name}` : who
  }
  function projectName(file) {
    if (!file.project_id) return ''
    return (
      [...zustand.projects, ...zustand.archive.projects]
        .find((p) => p.id === file.project_id)?.name ?? ''
    )
  }

  /* The tiles come in one after the other, the way the pictures next door
     do: from the ninth on they arrive together. The wall itself — grid,
     square, fade-in — is shared (stil/tiles.css). */
  const STAGGERED = 8

  /* --- opening -------------------------------------------------------- */

  /* What the reader can set as text: a text type, or a kind of file the
     program knows how to show. The rest — a PDF, an office file — is shown
     as the shell's picture of it, or the page sign. */
  const TEXT_TYPES = /^(text\/|application\/(json|xml|yaml|x-yaml))/
  const TEXT_ENDINGS = new Set(['txt', 'log', 'ini', 'toml', 'py', 'js', 'ts', 'sh', 'css'])
  function endingOf(file) {
    const name = String(file.name || '')
    return name.includes('.') ? name.split('.').pop().toLowerCase() : ''
  }
  function isText(file) {
    const ending = endingOf(file)
    return TEXT_TYPES.test(file.type || '') || Boolean(dateiart(ending)) || TEXT_ENDINGS.has(ending)
  }

  /* A file on the dock lives in the dock's named location; a file of a
     chat lies in that chat's own folder, which has no name to open by. */
  function folderOf(file) {
    return file.source === 'agent' ? 'agent_dock' : ''
  }

  /* The shell's picture of a page at the reader's size; the tile's own while
     the shell has none. */
  async function bigPreview(file) {
    if (!shellPreviews() || !file.path || isPicture(file)) return previewOf(file, CARD_PREVIEW)
    const address = new URL(api.docFolderAddress(file.path), location.href).href
    const image = await shellPreview(`${file.path}|${BIG_PREVIEW.width}`, address, file.name, BIG_PREVIEW)
    return image || previewOf(file, CARD_PREVIEW)
  }

  function open(file) {
    const adresse = file.path ? api.docFolderAddress(file.path) : ''
    const more = { name: file.name, origin: originLine(file), folder: folderOf(file) }
    if (isPicture(file) && adresse) {
      bildZeigen(adresse, more)
      return
    }
    if (isPdf(file) && adresse) {
      showPage({ ...more, adresse, framed: true })
      return
    }
    showPage({
      ...more,
      adresse,
      language: endingOf(file),
      loadText: adresse && isText(file)
        ? async () => {
          const answer = await fetch(adresse)
          if (!answer.ok) throw new Error(t('fehler.allgemein'))
          return answer.text()
        }
        : null,
      preview: previewOf(file, CARD_PREVIEW),
      loadPreview: adresse && !isText(file) ? () => bigPreview(file) : null,
    })
  }

  /* --- removing, dragging, dropping ----------------------------------- */

  async function remove(file) {
    const confirmed = await frage(t('agenten.ablage_weg_frage', { name: file.name }), {
      okSchluessel: 'agenten.ablage_weg',
    })
    if (!confirmed) return
    try {
      await api.agentendockEntfernen(file.id)
      melde(t('agenten.ablage_entfernt'), 'erfolg')
    } catch {
      melde(t('fehler.allgemein'), 'fehler')
    }
    await load()
  }

  function dragStart(event, file) {
    event.dataTransfer.setData(
      'application/x-exe-docfolder',
      JSON.stringify({ path: file.path, name: file.name, type: file.type || '' }),
    )
    event.dataTransfer.effectAllowed = 'copy'
  }

  /* Files put into the folder, whichever way they came: onto the dock, in
     a chat into that chat's own folder — the one route the service has for
     it. One after the other, so the wall asked for afterwards holds them
     all; a file the service refuses says so and the next one is tried.
     Every file of one drop goes where the first one went, whatever chat is
     opened while they are on their way. */
  async function add(list) {
    const into = chat
    for (const file of list) {
      try {
        await api.docFolderAdd(file, into)
      } catch (error) {
        melde(error.message, 'fehler')
      }
    }
    await load()
  }

  /* The folder row shows the place files are put into: in a chat that
     chat's own folder, on the start page the dock (the row's named
     location, which it names and opens itself). */
  function openChatFolder() {
    return api.ordnerOeffnen(chat, null)
  }

  let chatPlace = $state(null)
  $effect(() => {
    const asked = chat
    chatPlace = null
    if (!asked) return
    api.docFolderPlace(asked).then(
      (answer) => { if (asked === chat) chatPlace = answer.path },
      () => {},
    )
  })

  /* The folder lights up for a drag it will take, and for no other: one
     that carries files. Text, or one of the folder's own tiles, is let go
     here without anything happening, so the folder stays dark for it.
     While a drag is under way only the kinds it carries can be read, not
     the files themselves. */
  function takes(event) {
    return Boolean(event.dataTransfer?.types?.includes('Files'))
  }

  /* How many of the folder's elements the drag stands in. Moving onto a
     tile enters the tile before it leaves the folder, so the count falls
     to nought only when the drag has left the folder altogether or was
     called off — whether or not the browser names where it went. */
  let dragDepth = 0

  function dragEntered() {
    dragDepth += 1
  }
  function dragLeft() {
    dragDepth = Math.max(0, dragDepth - 1)
    if (!dragDepth) dropTarget = false
  }

  async function dropped(event) {
    event.preventDefault()
    dragDepth = 0
    dropTarget = false
    /* The input bar catches every drop on the window and attaches it to
       the chat; whatever is dropped here belongs to the folder alone — a
       tile let go over its own folder included. */
    event.stopPropagation()
    await add([...(event.dataTransfer?.files ?? [])])
  }
</script>

<svelte:window onclick={() => (projectsOpen = false)} />

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="modul"
  class:dropTarget
  ondragenter={dragEntered}
  ondragover={(e) => { e.preventDefault(); dropTarget = takes(e) }}
  ondragleave={dragLeft}
  ondrop={dropped}
>
  <!-- One row, the gallery's: the folder's name and path, then open and
       change. On the start page the folder is the dock, in a chat that
       chat's own folder, where its files lie and where a file dropped here
       goes. Files come in by dropping them; there is no button for it. -->
  <div class="ordnerzeile">
    <Speicherortzeile
      name="agent_dock"
      etikett={t('docfolder.ordner')}
      pathText={chat ? (chatPlace ?? '') : null}
      onaendern={load}
      onopen={chat ? openChatFolder : null}
    />
  </div>

  <!-- On the start page the files of every chat are listed: the chooser
       says whose, and which project. In a chat there is nothing to choose. -->
  {#if !chat}
    <div class="chooser-row">
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <span
        class="projekt"
        onkeydown={(e) => { if (e.key === 'Escape') projectsOpen = false }}
      >
        <button
          class="projektknopf"
          aria-haspopup="listbox"
          aria-expanded={projectsOpen}
          onclick={(e) => { e.stopPropagation(); projectsOpen = !projectsOpen }}
        >
          <span class="projektname">{projectLabel}</span>
          <span class="winkel"><Hauszeichen zeichen="pfeil_unten" groesse={14} /></span>
        </button>
        {#if projectsOpen}
          <!-- The one list: on top whose files — the person's, an agent's, a
               cron job's — then a fine line, then the projects. The two
               choices narrow together. -->
          <div class="projektliste" role="listbox">
            {#each originEntries as entry (entry.wert)}
              <button
                role="option"
                aria-selected={entry.wert === origin}
                class:an={entry.wert === origin}
                onclick={() => originPick(entry.wert)}
              >{entry.text}</button>
            {/each}
            <span class="divider" role="separator"></span>
            {#each projectEntries as entry (entry.wert)}
              <button
                role="option"
                aria-selected={entry.wert === project}
                class:an={entry.wert === project}
                onclick={() => { filters.project = entry.wert; projectsOpen = false }}
              >{entry.text}</button>
            {/each}
          </div>
        {/if}
      </span>
    </div>
  {/if}

  <div class="rollen">
    {#if files.length}
      <div class="tilewall">
        {#each files as file, n (file.source + file.id)}
          <div class="karte">
            <button
              class="kachel kachel-ein"
              class:nurzeichen={!(isPicture(file) && file.path) && !showsText(file)
                && !previewOf(file, CARD_PREVIEW)}
              style:animation-delay="{Math.min(n, STAGGERED) * 0.05}s"
              draggable={Boolean(file.path)}
              ondragstart={(e) => dragStart(e, file)}
              onclick={() => open(file)}
              title={file.name}
            >
              {#if isPicture(file) && file.path}
                <img src={api.docFolderAddress(file.path)} alt="" loading="lazy" draggable="false" />
              {:else if showsText(file)}
                <span class="blick" class:code={isCode(file)}>{starts[startKey(file)]}</span>
              {:else if previewOf(file, CARD_PREVIEW)}
                <img class="shell" src={previewOf(file, CARD_PREVIEW)} alt="" loading="lazy" draggable="false" />
              {:else}
                <!-- Nothing to preview: the page sign alone, as large as a
                     tile, with no tile behind it. -->
                <Hauszeichen zeichen="dokument_zeilen" groesse={30} />
              {/if}
            </button>
            <!-- Who brought the file, at the lower left of its document: an
                 agent's delivery wears the agent mark, a cron job's the
                 stopwatch; the person's own stay without. -->
            {#if file.origin === 'agent'}
              <span class="plakette" aria-hidden="true">
                <Agentenmarke groesse={18} />
              </span>
            {:else if file.origin === 'cronjob'}
              <span class="plakette" aria-hidden="true">
                <Hauszeichen zeichen="stopwatch" groesse={18} />
              </span>
            {/if}
            <!-- The cross takes a file off the dock, and stands on a dock
                 file only: what lies in a chat's folder — a document of
                 the chat, or a file a tool wrote there — carries none. -->
            {#if file.source === 'agent'}
              <button
                class="weg"
                onclick={() => remove(file)}
                title={t('agenten.ablage_weg')}
                aria-label={t('agenten.ablage_weg')}
              >✕</button>
            {/if}
            <span class="name" title={file.name}>{file.name}</span>
          </div>
        {/each}
      </div>
    {:else}
      <div class="tilewall"><p class="leer">{t('docfolder.empty')}</p></div>
    {/if}
  </div>

</div>

<style>
  /* The module fills what the rail gives it: the row on top, the heading
     under it, the wall scrolling — nothing else does. */
  .modul {
    position: relative;
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    transition: background 0.12s;
  }
  /* A drag the folder takes: the whole module in button glass with its
     fine edge, the glass a chosen row wears. */
  .modul.dropTarget {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
  }
  /* The folder's row: the gallery's, the same size and place. */
  .ordnerzeile {
    flex: none;
    padding: 12px 14px;
  }
  /* The chooser under it, as wide as the row; its list opens below. */
  .chooser-row {
    flex: none;
    position: relative;
    display: flex;
    padding: 0 14px 8px;
  }
  .projekt {
    flex: 1;
    min-width: 0;
    position: relative;
  }
  /* The chooser wears the house's glass button; its arrow stands in the
     middle of its height. */
  .projektknopf {
    width: 100%;
    height: 36px;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 12px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: inherit;
    font-size: 12.5px;
    text-align: left;
    cursor: pointer;
  }
  .projektname {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .winkel {
    flex: none;
    display: inline-flex;
    color: var(--text-leise);
  }
  /* The list opens under the chooser, as wide as it. */
  .projektliste {
    position: absolute;
    left: 0;
    right: 0;
    top: calc(100% + 4px);
    z-index: 3;
    display: flex;
    flex-direction: column;
    max-height: 280px;
    overflow-y: auto;
    padding: 4px;
    border-radius: 9px;
    /* Dense glass with a blur and a fine edge, like every drop-down list. */
    background: var(--glass-dropdown);
    -webkit-backdrop-filter: blur(16px);
    backdrop-filter: blur(16px);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge), 0 10px 30px rgb(0 0 0 / 0.5);
  }
  .projektliste button {
    border: none;
    background: none;
    color: var(--text-leise);
    font: inherit;
    font-size: 12px;
    text-align: left;
    border-radius: 6px;
    padding: 5px 9px;
    cursor: pointer;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .projektliste button:hover {
    background: var(--glass-hover);
    color: var(--text);
  }
  .projektliste button.an {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  /* The fine line between whose files and which project. */
  .projektliste .divider {
    flex: none;
    height: 1px;
    margin: 4px 9px;
    background: var(--linie);
  }
  /* The wall scrolls under the rows above it and ends at its line. Nothing
     fades at the top: a fade there would thin out the first row while it
     simply stands in its place. */
  .rollen {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 4px 14px 14px;
  }
  /* One tile and the two lines under it — the square, the picture filling
     it and the empty line above come from the shared wall (stil/tiles.css),
     the same the pictures stand in. Only what is THIS menu's own stays
     here: the two lines and the cross. */
  .karte {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 5px;
    min-width: 0;
  }
  .karte .kachel {
    position: relative;
    width: 100%;
    padding: 0;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  /* A file with nothing to preview: no surface, shadow or border, only the
     page sign, as large as a tile. Its strokes keep the width they have at
     30 px (5 and 4.5 on a grid of 64) however large it is drawn. */
  .tilewall .kachel.nurzeichen {
    background: none;
    box-shadow: none;
    border-color: transparent;
  }
  .kachel.nurzeichen :global(svg) {
    width: 100%;
    height: 100%;
  }
  .kachel.nurzeichen :global(svg path) {
    vector-effect: non-scaling-stroke;
    stroke-width: calc(4.5px * 30 / 64);
  }
  .kachel.nurzeichen :global(svg path:first-child) {
    stroke-width: calc(5px * 30 / 64);
  }
  /* A text file's first lines on a finer surface inside the tile, fading
     out at the bottom where the tile cuts them. */
  .blick {
    align-self: stretch;
    justify-self: stretch;
    margin: 8px;
    padding: 7px 8px;
    border-radius: 6px;
    overflow: hidden;
    background: color-mix(in srgb, var(--text) 6%, transparent);
    color: var(--text-leise);
    font: 8.5px/1.35 var(--schrift);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    -webkit-mask-image: linear-gradient(to bottom, #000 60%, transparent);
    mask-image: linear-gradient(to bottom, #000 60%, transparent);
  }
  .blick.code { font-family: var(--schrift-fest); }
  /* The name in the fixed font the numbers under an answer wear: bright in
     10 px on at most two lines, centred under its tile. */
  .name {
    padding: 0 2px;
    font-family: var(--schrift-fest);
    font-size: 10px;
    letter-spacing: -0.01em;
    overflow: hidden;
    text-align: center;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow-wrap: anywhere;
    line-height: 14px;
    height: 28px;
    color: var(--text);
  }
  /* The shell's picture of a file's first page is the tile's face, not a
     picture of its own: it takes no pointer, so a right click on it lands on
     the tile and the menu offers no "save image" for what is a page of a
     document. The tile of a real picture keeps its image as it was. */
  .shell {
    pointer-events: none;
  }
  /* Who brought the file: the bare sign inside the document, at its lower
     left — opposite the delete cross, on its line and in its box of 20.
     It has no ground and no edge of its own. A thin shade in the colour of
     the dense glass follows its strokes instead — dark under a bright sign,
     bright under a dark one — so the sign keeps its outline on a white
     page as on a dark picture; on the tile's own glass that shade is not
     seen. The 38px are the cross's: the name (28) plus the gap (5) plus
     the inset (5). The sign takes no pointer: it stands inside the tile
     now, and a click on it opens the file like a click anywhere else on
     the tile. */
  .plakette {
    position: absolute;
    left: 5px;
    bottom: 38px;
    z-index: 2;
    width: 20px;
    height: 20px;
    display: grid;
    place-items: center;
    color: var(--text);
    filter: drop-shadow(0 0 1px var(--glass-dropdown)) drop-shadow(0 0 2px var(--glass-dropdown));
    pointer-events: none;
  }
  /* The cross that takes a file out of the folder: at the document's
     bottom right — the lower left carries the sign of who brought it — and
     only while the pointer stands on it. The 38px sit 5px up from the
     tile's lower edge: the name (28) plus the gap (5) plus the inset (5). */
  .weg {
    position: absolute;
    right: 5px;
    bottom: 38px;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    border: none;
    /* Over a preview as well: the dense glass of the floating layers,
       without their blur, which a wall of tiles would pay for on every
       one of them. */
    background: var(--glass-dropdown);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text-leise);
    font-size: 11px;
    line-height: 1;
    display: grid;
    place-items: center;
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.12s;
  }
  .karte:hover .weg { opacity: 1; }
  /* Reached without a hand that hovers: a keyboard tab must not land on an
     invisible control that deletes the file, and a touch screen has no
     hover at all — the same two rules the job rows carry (ModulAgenten). */
  .weg:focus-visible { opacity: 1; }
  @media (hover: none) {
    .weg { opacity: 1; }
  }
  .weg:hover { color: var(--rot); }
</style>
