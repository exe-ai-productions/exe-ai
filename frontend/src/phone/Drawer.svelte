<script>
  /* The chat list, drawn as a drawer that comes in from the left edge.

     From top to bottom: the mark and the way out, the search, the new chat,
     the projects, the chats cut into days, the archive, then the pages that
     open over the chat, and the settings page at the foot. A swipe from the
     left edge opens it and a swipe back closes it (swipe.js); a tap on the
     veil closes it too.

     The drawer stays in the page while it is shut — moved out of sight and
     `inert` — so the list keeps its scroll position and its search between
     two openings. */
  import { fade } from 'svelte/transition'
  import { t, texte } from '../lib/texte.svelte.js'
  import { gruppenDatum } from '../lib/chatgruppen.js'
  import { chatListe } from '../lib/chatliste.js'
  import { runAction, renameChat, removeChat, createProject, renameProject, removeProject } from '../lib/chataktionen.js'
  import Hauszeichen from '../teile/Hauszeichen.svelte'
  import Wortmarke from '../teile/Wortmarke.svelte'
  import Modulzeichen from '../teile/Modulzeichen.svelte'
  import Agentenmarke from '../teile/Agentenmarke.svelte'
  import Leuchtpunkt from '../teile/Leuchtpunkt.svelte'
  import ChatRow from './ChatRow.svelte'
  import Sheet from './Sheet.svelte'
  import { TABS } from './work.js'
  import { workOpen } from './workbar.svelte.js'
  import { workBusyByTab } from './workState.svelte.js'
  import { phone, drawerSet } from './phone.svelte.js'
  import { PAGES, pageState, pageOpen, pageClose } from './pages.svelte.js'
  import {
    zustand, chatsLaden, chatOeffnen, neuerChat, chatAendern,
    projectUpdate, chatMoveToProject, chatArchive,
  } from '../lib/zustand.svelte.js'

  const listPages = PAGES.filter((page) => page.place !== 'foot')
  const footPages = PAGES.filter((page) => page.place === 'foot')

  /* The clock the day headings read. Its own piece of state and not a call
     to the clock inside the derivation: a derivation that reads the clock
     never notices the day change. The tick is slow because the only
     boundary that matters is midnight. */
  let now = $state(Date.now())
  $effect(() => {
    const clock = setInterval(() => (now = Date.now()), 60000)
    return () => clearInterval(clock)
  })

  const searching = $derived(Boolean(zustand.suche.trim()))
  const list = $derived(chatListe(zustand.chats, zustand.projects, searching, now))
  const pinned = $derived(list.pinned)
  const days = $derived(list.days)
  const chatsByProject = $derived(list.byProject)
  const archiveCount = $derived(zustand.archive.projects.length + zustand.archive.chats.length)

  /* Which projects and which part of the archive stand open — only for this
     page; nothing is lost when it forgets. */
  let openProjects = $state({})
  let archiveOpen = $state(false)

  /* The list is drawn from the first opening on and kept after it, so its
     scroll position and its search stay; before that a page that never opens
     the drawer pays nothing for it. */
  let everOpened = $state(false)
  $effect(() => {
    if (phone.drawer) everOpened = true
  })

  let searchTimer
  function search(value) {
    zustand.suche = value
    clearTimeout(searchTimer)
    searchTimer = setTimeout(chatsLaden, 220)
  }

  async function openChat(id) {
    if (!(await pageClose())) return
    drawerSet(false)
    return chatOeffnen(id)
  }
  async function startChat() {
    if (!(await pageClose())) return
    drawerSet(false)
    neuerChat()
  }
  function showPage(name) {
    pageOpen(name)
    drawerSet(false)
  }
  /* A tool of the work bar: the bar opens on exactly that tool. Like the
     pages, it ends a page that stands over the chat first. */
  async function showTool(name) {
    if (!(await pageClose())) return
    drawerSet(false)
    workOpen(name)
  }
  const busy = $derived(workBusyByTab())

  /* The menu sheet: `kind` says whose it is — a chat, a project, or an entry
     of the archive — and `step` turns a chat's menu into the list of
     projects it can move to. The last menu stays for the sheet to draw while
     it slides out, so the sheet does not empty before it is gone. */
  let menu = $state(null) // { kind, item, step }
  let lastMenu = $state(null)
  $effect(() => {
    if (menu) lastMenu = menu
  })
  const shown = $derived(menu ?? lastMenu)
  const menuTitle = $derived(shown?.kind.includes('project') ? shown.item.name : shown?.item.title)
  function showMenu(kind, item) {
    menu = { kind, item, step: 'main' }
  }
  /* Closes the menu and runs what was chosen; what fails is said. */
  function act(action) {
    menu = null
    return runAction(action)
  }

  /* Read from the list as it stands now: the menu was opened on a copy that
     a refresh may have outdated. */
  const pin = (chat) => {
    const live = zustand.chats.find((entry) => entry.id === chat.id) ?? chat
    return act(() => chatAendern(chat.id, { pinned: !live.pinned }))
  }
  async function rename(chat) {
    menu = null
    await renameChat(chat)
  }
  async function remove(chat) {
    menu = null
    await removeChat(chat)
  }
  const archive = (chat, put) => act(() => chatArchive(chat.id, put))
  const leaveProject = (chat) => act(() => chatMoveToProject(chat.id, null))
  function moveTo(chat, project) {
    openProjects[project.id] = true
    return act(() => chatMoveToProject(chat.id, project.id))
  }
  const archiveProject = (project, put) => act(() => projectUpdate(project.id, { archived: put }))

  async function newProject() {
    const project = await createProject()
    if (project) openProjects[project.id] = true
  }
  async function renameProjectFromMenu(project) {
    menu = null
    await renameProject(project)
  }
  async function removeProjectFromMenu(project) {
    menu = null
    await removeProject(project)
  }
</script>

{#if phone.drawer}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="veil" transition:fade={{ duration: 160 }} onclick={() => drawerSet(false)}></div>
{/if}

<aside class="drawer" class:open={phone.drawer} inert={!phone.drawer} aria-label={t('phone.chat_list')}>
  <div class="mark">
    <Wortmarke hoehe={26} />
    <button class="close" onclick={() => drawerSet(false)} aria-label={t('seitenleiste.ausblenden')}>
      <Hauszeichen zeichen="pfeil_unten" groesse={14} strich={2.6} />
    </button>
  </div>

  <div class="scroll">
    {#if everOpened}
    <button class="new" onclick={startChat}>
      <Hauszeichen zeichen="plus" groesse={15} strich={2} />
      {t('chat.neu')}
    </button>
    <label class="search">
      <Hauszeichen zeichen="lupe" groesse={15} />
      <input
        type="search"
        placeholder={t('chat.suchen')}
        aria-label={t('chat.suchen')}
        value={zustand.suche}
        oninput={(event) => search(event.currentTarget.value)}
      />
    </label>

    {#each pinned as group (group.schluessel)}
      <div class="heading">{t(group.schluessel)}</div>
      {#each group.chats as chat (chat.id)}
        <ChatRow {chat} open={openChat} more={(item) => showMenu('chat', item)} />
      {/each}
    {/each}

    {#if !searching}
      <div class="heading">{t('project.title')}</div>
      <button class="tile" onclick={newProject}>
        <Hauszeichen zeichen="plus" groesse={16} />
        {t('project.new')}
      </button>
      {#each zustand.projects as project (project.id)}
        <div class="project">
          <button
            class="tile"
            aria-expanded={Boolean(openProjects[project.id])}
            onclick={() => (openProjects[project.id] = !openProjects[project.id])}
          >
            <span class="chevron" class:open={openProjects[project.id]}>
              <Hauszeichen zeichen="pfeil_unten" groesse={12} strich={2.6} />
            </span>
            <Hauszeichen zeichen="ordner" groesse={17} />
            <span class="name">{project.name}</span>
          </button>
          <button class="more" onclick={() => showMenu('project', project)}
                  title={t('app.mehr')} aria-label={t('app.mehr')}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <circle cx="5" cy="12" r="1.7" /><circle cx="12" cy="12" r="1.7" /><circle cx="19" cy="12" r="1.7" />
            </svg>
          </button>
        </div>
        {#if openProjects[project.id]}
          {#each chatsByProject[project.id] ?? [] as chat (chat.id)}
            <ChatRow {chat} nested open={openChat} more={(item) => showMenu('chat', item)} />
          {/each}
        {/if}
      {/each}
    {/if}

    {#each days as group (group.schluessel ?? group.datum.getTime())}
      <div class="heading">
        {group.schluessel ? t(group.schluessel) : gruppenDatum(group.datum, texte.sprache)}
      </div>
      {#each group.chats as chat (chat.id)}
        <ChatRow {chat} open={openChat} more={(item) => showMenu('chat', item)} />
      {/each}
    {/each}

    {#if !zustand.chats.length}
      <div class="heading">{zustand.suche ? t('chat.keine_treffer') : t('chat.leer')}</div>
    {/if}

    {#if !searching && archiveCount}
      <button class="tile" aria-expanded={archiveOpen} onclick={() => (archiveOpen = !archiveOpen)}>
        <Hauszeichen zeichen="archive" groesse={16} />
        <span class="name">{t('archive.title')}</span>
        <small>{archiveCount}</small>
      </button>
      {#if archiveOpen}
        {#each zustand.archive.projects as project (project.id)}
          <button class="tile entry" onclick={() => showMenu('archived-project', project)}>
            <Hauszeichen zeichen="ordner" groesse={16} />
            <span class="name">{project.name}</span>
            <small>{project.chat_count}</small>
          </button>
        {/each}
        {#each zustand.archive.chats as chat (chat.id)}
          <button class="tile entry" onclick={() => showMenu('archived-chat', chat)}>
            <span class="name">{chat.title}</span>
          </button>
        {/each}
      {/if}
    {/if}

    {#each listPages as page (page.name)}
      <button class="tile" class:active={pageState.open === page.name} onclick={() => showPage(page.name)}>
        <Hauszeichen zeichen={page.sign} groesse={17} />
        <span class="name">{t(page.title)}</span>
      </button>
    {/each}
    {/if}
  </div>

  <div class="foot">
    <!-- The tools of the work bar, one cell each, two to a row so that the
         list above keeps its room; the dot says that one works. They stand in
         the foot, where they are always at hand. -->
    <div class="tools">
      {#each TABS as tab (tab.name)}
        <button class="tile" onclick={() => showTool(tab.name)}>
          <span class="tool">
            {#if tab.name === 'agenten'}
              <Agentenmarke groesse={20} />
            {:else}
              <Modulzeichen modul={tab.name} groesse={19} />
            {/if}
          </span>
          <span class="name">{t(tab.title)}</span>
          {#if busy[tab.name]}<Leuchtpunkt farbe={busy[tab.name]} groesse={9} />{/if}
        </button>
      {/each}
    </div>
    {#each footPages as page (page.name)}
      <button class="tile" class:active={pageState.open === page.name} onclick={() => showPage(page.name)}>
        <Hauszeichen zeichen={page.sign} groesse={17} />
        <span class="name">{t(page.title)}</span>
      </button>
    {/each}
  </div>
</aside>

<Sheet open={Boolean(menu)} label={menuTitle} onclose={() => (menu = null)}>
  {#if shown}
    <div class="sheet-title">{menuTitle}</div>
    {#if shown.kind === 'chat' && shown.step === 'move'}
      <button class="choice back" onclick={() => (shown.step = 'main')}>
        <span class="arrow"><Hauszeichen zeichen="pfeil_unten" groesse={13} strich={2.6} /></span>
        {t('app.zurueck')}
      </button>
      {#each zustand.projects.filter((project) => project.id !== shown.item.project_id) as project (project.id)}
        <button class="choice" onclick={() => moveTo(shown.item, project)}>
          <Hauszeichen zeichen="ordner" groesse={17} />
          {project.name}
        </button>
      {/each}
    {:else if shown.kind === 'chat'}
      {@const chat = shown.item}
      <button class="choice" onclick={() => pin(chat)}>
        {chat.pinned ? t('chat.loesen') : t('chat.anheften')}
      </button>
      <button class="choice" onclick={() => rename(chat)}>{t('chat.umbenennen')}</button>
      {#if zustand.projects.some((project) => project.id !== chat.project_id)}
        <button class="choice" onclick={() => (shown.step = 'move')}>{t('project.move_to')}</button>
      {/if}
      {#if chat.project_id}
        <button class="choice" onclick={() => leaveProject(chat)}>{t('project.remove_from')}</button>
      {/if}
      <button class="choice" onclick={() => archive(chat, true)}>{t('archive.put_away')}</button>
      <button class="choice danger" onclick={() => remove(chat)}>{t('chat.loeschen')}</button>
    {:else if shown.kind === 'project'}
      {@const project = shown.item}
      <button class="choice" onclick={() => renameProjectFromMenu(project)}>{t('chat.umbenennen')}</button>
      <button class="choice" onclick={() => archiveProject(project, true)}>{t('archive.put_away')}</button>
    {:else if shown.kind === 'archived-project'}
      {@const project = shown.item}
      <button class="choice" onclick={() => archiveProject(project, false)}>{t('archive.restore')}</button>
      <button class="choice danger" onclick={() => removeProjectFromMenu(project)}>{t('chat.loeschen')}</button>
    {:else}
      {@const chat = shown.item}
      <button class="choice" onclick={() => archive(chat, false)}>{t('archive.restore')}</button>
      <button class="choice danger" onclick={() => remove(chat)}>{t('chat.loeschen')}</button>
    {/if}
  {/if}
</Sheet>

<style>
  .veil {
    position: fixed;
    inset: 0;
    z-index: 30;
    background: rgba(0, 0, 0, 0.45);
  }
  .drawer {
    position: fixed;
    top: 0;
    bottom: 0;
    left: 0;
    z-index: 31;
    /* The seat of the sidebar in the page frame, and never more than most
       of the screen. */
    width: min(285px, 85vw);
    display: flex;
    flex-direction: column;
    padding: env(safe-area-inset-top) 8px env(safe-area-inset-bottom) calc(8px + env(safe-area-inset-left));
    background: var(--bg-seite);
    color: var(--text);
    transform: translateX(-105%);
    transition: transform 0.26s var(--anlauf-schwung), box-shadow 0.26s;
  }
  /* The edge and the fall of the shadow belong to the open drawer: shut, its
     shadow would leak in at the screen's left edge. */
  .drawer.open {
    transform: none;
    box-shadow: 0 0 0 1px var(--linie), 0 18px 40px -8px rgba(0, 0, 0, 0.55);
  }
  .mark {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 52px;
    padding: 0 4px 0 10px;
  }
  /* The way out: the arrow turned to point at the edge the drawer lives on. */
  .close {
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
  }
  .close :global(svg) {
    transform: rotate(90deg);
  }
  .scroll {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
  }
  .new,
  .search {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    height: 44px;
    margin-bottom: 8px;
    padding: 0 12px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    font: 500 13px var(--schrift);
  }
  .search {
    background: var(--kachel-eingabe);
    box-shadow: none;
    color: var(--text-still);
  }
  .search input {
    flex: 1;
    min-width: 0;
    height: 100%;
    border: none;
    outline: none;
    background: none;
    color: var(--text);
    /* 16 px: a smaller field makes the phone zoom the page in on focus. */
    font: 400 16px var(--schrift);
  }
  .search input::placeholder {
    color: var(--text-still);
  }
  .heading {
    margin: 16px 10px 4px;
    font: 500 var(--schrift-hinweis) var(--schrift);
    color: var(--text-still);
  }
  .tile {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    height: 44px;
    padding: 0 10px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    font: 400 13px var(--schrift);
    text-align: left;
  }
  .tile.active {
    background: var(--bg-hoch);
    color: var(--text);
  }
  .tile.entry {
    padding-left: 24px;
  }
  .tools {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  /* The sign of a tool stands in the column of the other rows' signs. */
  .tool {
    flex: none;
    display: inline-flex;
    width: 17px;
    justify-content: center;
  }
  .tile .name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .tile small {
    color: var(--text-still);
    font-size: 11px;
  }
  .chevron {
    display: inline-flex;
    transform: rotate(-90deg);
    transition: transform 0.16s;
  }
  .chevron.open {
    transform: none;
  }
  .project {
    display: flex;
    align-items: center;
  }
  /* The dots of a project stand in the column of the chat rows' dots: the
     same width of state dot lies to their right. */
  .project .more {
    margin-right: 26px;
  }
  .more {
    flex: none;
    display: grid;
    place-items: center;
    width: 36px;
    height: 36px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-still);
  }
  .foot {
    flex: none;
    padding-top: 6px;
    border-top: 1px solid var(--linie);
  }

  .sheet-title {
    padding: 4px 4px 10px;
    font: 600 16px var(--schrift);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .choice {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    height: var(--menuezeile);
    padding: 0 6px;
    border: none;
    border-top: 1px solid var(--linie);
    background: none;
    color: var(--text);
    font: 400 var(--schrift-text) var(--schrift);
    text-align: left;
  }
  /* The house arrow points down; turned a quarter it points back. */
  .choice.back .arrow {
    display: inline-flex;
    transform: rotate(90deg);
  }
  .choice.danger {
    color: var(--rot-text);
  }
</style>
