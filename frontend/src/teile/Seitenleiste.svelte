<script>
  import { rollfade } from '../lib/rollfade.js'
  import { fade, fly } from 'svelte/transition'
  import { slideIfDrawn } from '../lib/slideIfDrawn.js'
  import { flip } from 'svelte/animate'
  import { t, texte } from '../lib/texte.svelte.js'
  import { gruppenDatum } from '../lib/chatgruppen.js'
  import { chatListe } from '../lib/chatliste.js'
  import { runAction, renameChat, removeChat, createProject, renameProject, removeProject } from '../lib/chataktionen.js'
  import Chatzeile from './Chatzeile.svelte'
  import ProjectRow from './ProjectRow.svelte'
  import ArchiveList from './ArchiveList.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Wortmarke from './Wortmarke.svelte'
  import Fensterzeichen from './Fensterzeichen.svelte'
  import { system, keyNames } from '../lib/keyNames.js'
  import StudioBasics from './StudioBasics.svelte'
  import { windowButtonsInPage, RAIL_WIDTH, MARK_LEFT, RAIL_TOP, GRAB_HEIGHT } from '../lib/windowButtons.svelte.js'
  import { studio, studioSichtbar, studioSchalten, studioSchliessen } from '../lib/studio.svelte.js'
  import {
    zustand, chatsLaden, chatOeffnen, neuerChat, chatAendern,
    blattWechseln, seitenleisteSchalten,
    menueFensterOeffnen, sucheZeigen, seitenSchliessen, seiteOffenFuer, eineSeiteOffen,
    istSeitenleisteSchmal,
    projectUpdate, chatMoveToProject, chatArchive,
} from '../lib/zustand.svelte.js'

  /* The key of the chat search, as the system writes it. */
  const sucheTaste = $derived(system === 'mac' ? '⌘K' : `${keyNames().Control}+K`)

  /* Whether one of the menus of the settings stands open: the settings, the
     local models, the cloud providers, the catalogue. They are one place now,
     reached from the list of the settings, and the gear stands for all four. */
  const einstellungenOffen = () =>
    ['prompt', 'lokal', 'cloud', 'katalog'].some((name) => seiteOffenFuer(name))

  /* A chat clicked in the list is where the hand wants to be: the page over
     the main area gives way to it — and so it does for a new chat and for
     the agent form, which open under it on the chat and the tool surface. */
  function chatAusDerListe(id) {
    seitenSchliessen()
    return chatOeffnen(id)
  }
  /* Whether the sidebar is standing open: the drawer on a narrow window,
     the column beside the chat otherwise. */
  function sidebarOpen() {
    return istSeitenleisteSchmal() ? zustand.seitenleisteOffen : !zustand.seitenleisteEingeklappt
  }
  /* Whether the chat list is what the sidebar shows right now. */
  const chatsAn = () =>
    !eineSeiteOffen() && !studio.offen && zustand.seitenblatt === 'chats' && sidebarOpen()
  /* The chat list again: a menu page and the studio give way and the sheet
     is the chats; a folded sidebar unfolds with it. While the list already
     stands there, the same sign folds the sidebar — the sidebar's own
     button and ⌘B do just that. */
  function chatsZeigen() {
    if (chatsAn()) {
      seitenleisteSchalten()
      return
    }
    seitenSchliessen()
    studioSchliessen()
    blattWechseln('chats')
    if (!sidebarOpen()) seitenleisteSchalten()
  }
  function neuerChatAusDerListe() {
    seitenSchliessen()
    neuerChat()
  }

  function einstellungenOeffnen() {
    zustand.promptStart = 'darstellung'
    menueFensterOeffnen('prompt')
  }

  /* A row of the section column was picked: on a narrow window the drawer
     has done its job and gives the content back. */
  function abschnittGewaehlt() {
    if (istSeitenleisteSchmal()) zustand.seitenleisteOffen = false
  }

  let suchZeit
  /* One menu for every row of the list: `kind` says whose it is — a chat,
     a project, or an entry of the archive — and `picking` turns a chat's
     menu into the list of projects it can move to. */
  let menue = $state(null) // { kind, item, x, y, picking }

  /* The list cut into days. `heute` is deliberately its own piece of
     state and not a call to the clock inside the derivation: a derivation
     that reads the clock never notices when the clock moves on, and the
     "Today" heading would keep the name of the day the window was opened
     on. The tick is slow because the only boundary that matters is
     midnight. */
  let jetzt = $state(Date.now())
  $effect(() => {
    const uhr = setInterval(() => (jetzt = Date.now()), 60000)
    return () => clearInterval(uhr)
  })
  const searching = $derived(Boolean(zustand.suche.trim()))
  const liste = $derived(chatListe(zustand.chats, zustand.projects, searching, jetzt))
  const pinnedGroups = $derived(liste.pinned)
  const dayGroups = $derived(liste.days)

  /* Which projects stand open. Only for this window: nothing is lost when
     it forgets. */
  let openProjects = $state({})

  /* Which days stand folded, by the key their group is listed under: the
     name of the heading for today and yesterday, the day itself beyond
     that. Only for this window, like the projects. A day opens for as long
     as a search runs: a hit under a folded heading would stay out of
     sight. */
  let foldedDays = $state({})
  const dayKey = (gruppe) => gruppe.schluessel ?? gruppe.datum.getTime()

  const chatsByProject = $derived(liste.byProject)

  function suchen(wert) {
    zustand.suche = wert
    clearTimeout(suchZeit)
    suchZeit = setTimeout(chatsLaden, 220)
  }


  function placeMenu(ereignis, kind, item) {
    ereignis.preventDefault()
    menue = {
      kind,
      item,
      x: Math.min(ereignis.clientX, innerWidth - 220),
      y: Math.min(ereignis.clientY, innerHeight - 180),
      picking: false,
    }
  }
  function menueOeffnen(ereignis, chat) {
    placeMenu(ereignis, 'chat', chat)
  }
  function projectMenu(ereignis, project) {
    placeMenu(ereignis, 'project', project)
  }

  /* Closes the menu and runs what was chosen; what fails is said. */
  function act(action) {
    menue = null
    return runAction(action)
  }

  async function anheften(chat) {
    menue = null
    await chatAendern(chat.id, { pinned: !chat.pinned })
  }
  async function umbenennen(chat) {
    menue = null
    await renameChat(chat)
  }
  async function loeschen(chat) {
    menue = null
    await removeChat(chat)
  }

  function archiveChat(chat, archived) {
    return act(() => chatArchive(chat.id, archived))
  }
  function removeFromProject(chat) {
    return act(() => chatMoveToProject(chat.id, null))
  }
  function archiveProject(project, archived) {
    return act(() => projectUpdate(project.id, { archived }))
  }
  function moveToProject(chat, project) {
    openProjects[project.id] = true
    return act(() => chatMoveToProject(chat.id, project.id))
  }
  function dropIntoProject(chatId, project) {
    const chat = zustand.chats.find((entry) => entry.id === chatId)
    if (!chat || chat.project_id === project.id) return
    moveToProject(chat, project)
  }

  /* A new project starts with an empty name field and opens at once, so
     the chats dragged in next have somewhere visible to land. */
  async function newProject() {
    menue = null
    const project = await createProject()
    if (project) openProjects[project.id] = true
  }
  async function renameProjectFromMenu(project) {
    menue = null
    await renameProject(project)
  }
  async function deleteProject(project) {
    menue = null
    await removeProject(project)
  }
</script>

<svelte:window onclick={() => (menue = null)} />

{#if zustand.seitenleisteOffen}
  <!-- Under 480px the open drawer takes most of the screen, and a chat
       dimmed behind it is what says the drawer, not the chat, has the
       hand's attention — same reasoning as every other `.schleier` in the
       house (Frage.svelte, Protokollfenster.svelte). Above 480px the CSS
       below keeps this invisible: the drawer there leaves enough of the
       chat showing that dimming it would be noise. -->
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div
    class="schleier"
    transition:fade={{ duration: 120 }}
    onclick={() => seitenleisteSchalten()}
  ></div>
{/if}

{#snippet fusszeichen()}
  <!-- The five signs at the foot, spread evenly: the way back out of any menu
       and out of the studio (the chat list), a new chat, a new project, the
       pictures, and the settings last. -->
  <button
    class="zk"
    class:aktiv={chatsAn()}
    onclick={chatsZeigen}
    title={t('jobs.bereich_chats')}
    aria-label={t('jobs.bereich_chats')}
  >
    <Fensterzeichen name="chats" groesse={24} />
  </button>
  <button class="zk" onclick={neuerChatAusDerListe} title={t('chat.neu')} aria-label={t('chat.neu')}>
    <Hauszeichen zeichen="plus" groesse={24} />
  </button>
  <button class="zk" onclick={newProject} title={t('project.new')} aria-label={t('project.new')}>
    <!-- The open folder, with the plus of a new one, fills less of its box
         than the other signs of the bar, so it is asked two larger — the same
         step the right rail's folder takes. -->
    <Hauszeichen zeichen="folder_plus" groesse={26} />
  </button>
  <!-- The picture studio: a view of its own rather than a menu page — a
       second click closes it. -->
  <button class="zk" class:aktiv={studioSichtbar()} onclick={studioSchalten}
          title={t('studio.titel')} aria-label={t('studio.titel')}>
    <Fensterzeichen name="studio" groesse={24} />
  </button>
  <button class="zk" class:aktiv={einstellungenOffen()} onclick={einstellungenOeffnen}
          title={t('menue.settings')} aria-label={t('menue.settings')}>
    <Hauszeichen zeichen="gear" groesse={24} />
  </button>
{/snippet}

{#snippet leistenzeichen()}
  <!-- The sidebar sign of the house catalogue (static/zeichen/index.html):
       a window with its left column, as large as the window signs at the
       foot of the sidebar. -->
  <svg width="24" height="24" viewBox="0 0 64 64" fill="none" stroke="currentColor"
       stroke-width="5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <rect x="9" y="13" width="46" height="38" rx="8" />
    <path d="M25 13 V51" />
  </svg>
{/snippet}

<!-- The folded sidebar: a narrow bar of signs that never goes away — the way
     back in and the search at the top, the five signs of the foot below.
     On the desktop it stands while the sidebar is folded; below 760px it
     always stands, and the full sidebar opens over the chat from it. -->
<nav class="zeichenleiste" class:zeigt={zustand.seitenleisteEingeklappt} style:--rail-width="{RAIL_WIDTH}px" style:--rail-top="{RAIL_TOP}px">
  <!-- Where the window buttons stand over the bar: the strip from the top to
       the first sign grabs the window. -->
  {#if windowButtonsInPage}
    <div class="grab-strip" style:height="{GRAB_HEIGHT}px" aria-hidden="true"></div>
  {/if}
  <button
    class="zk"
    onclick={() => seitenleisteSchalten()}
    title={t('seitenleiste.einblenden')}
    aria-label={t('seitenleiste.einblenden')}
  >
    {@render leistenzeichen()}
  </button>
  <button class="zk" onclick={sucheZeigen} title={t('chat.suchen')} aria-label={t('chat.suchen')}>
    <svg width="24" height="24" viewBox="0 0 64 64" fill="none" stroke="currentColor"
         stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <circle cx="27" cy="27" r="15" stroke-width="5" /><path d="M37.6 37.6 L53 53" stroke-width="5" />
    </svg>
  </button>
  <span class="frei"></span>
  {@render fusszeichen()}
</nav>

<aside
  class="seitenleiste"
  class:offen={zustand.seitenleisteOffen}
  class:eingeklappt={zustand.seitenleisteEingeklappt}
  class:zieht={zustand.seitenZieht}
  style:--seiten-breite={zustand.seitenBreite + 'px'}
>
  <!-- The mark and, beside it, the button that folds the sidebar to its
       icon bar. The window has no header any more: this is where the
       program says its name. -->
  <div class="markenkopf" class:grab={windowButtonsInPage} style:--mark-left="{MARK_LEFT}px">
    <Wortmarke hoehe={32} />
    <button
      class="zk"
      onclick={() => seitenleisteSchalten()}
      title={t('seitenleiste.ausblenden')}
      aria-label={t('seitenleiste.ausblenden')}
    >
      {@render leistenzeichen()}
    </button>
  </div>
  <!-- A hairline under the mark, clear of both edges. Every sheet of the
       sidebar — the chats and each menu — starts right under it, so
       switching between them leaves the first row where it was. -->
  <div class="kopfstrich" aria-hidden="true"></div>

  <!-- While a menu or the studio is open, the chat's own head gives way
       with the chat list; the menu sheet and the studio bring their own. -->
  {#if zustand.seitenblatt === 'chats' && !eineSeiteOffen() && !studio.offen}
    <!-- The search: a new chat and a new project are signs at the foot. -->
    <div class="suchfeld">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" />
      </svg>
      <input
        id="suchfeld"
        placeholder={t('chat.suchen')}
        aria-label={t('chat.suchen')}
        value={zustand.suche}
        oninput={(e) => suchen(e.currentTarget.value)}
      />
      <kbd class="taste">{sucheTaste}</kbd>
    </div>
  {/if}

  {#if eineSeiteOffen()}
    <!-- A menu is open: its sections stand where the chat list stood. The
         window row at the foot stays put; its first sign, the chats, is the
         way back, and the sign of the open menu takes the menu away too. -->
    {#if zustand.menuSections}
      <!-- The click is delegation, not a control: every row inside is one,
           and picking any of them closes the drawer on a narrow window.
           Same reasoning as the veil below. -->
      <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
      <nav
        class="menueliste"
        use:rollfade={40}
        aria-label={zustand.menuSections.label}
        onclick={abschnittGewaehlt}
      >
        {@render zustand.menuSections.snippet?.()}
      </nav>
    {/if}
  {:else if studio.offen}
    <!-- The studio is open: its basics stand where the chat list stood. -->
    <StudioBasics />
  {/if}

  <!-- The chat sheet rides in from the left when it first appears — the
       turn of a page, not a hard cut. While a menu stands open it steps
       aside without being taken down, so its scroll position, its search
       field and its rows are the same ones when it comes back; that step
       aside is a plain swap, no second entry. -->
  <div class="blatt" hidden={eineSeiteOffen() || studio.offen || zustand.seitenblatt !== 'chats'}
       in:fly={{ x: -36, duration: 220 }}>

  <!-- Melts out over its last 40 px while more chats lie below, like the
       menu's section column. -->
  <div class="liste" use:rollfade={40}>
    <!-- Pinned first, then today, yesterday, and one heading per day
         beyond that. The headings are the same ones the pinned group has
         always worn — a date is a section of the list, not a new kind of
         thing, so it gets no look of its own. -->
    {#snippet chatGroup(gruppe)}
      {@const day = gruppe.schluessel !== 'chat.angeheftet'}
      {@const folded = day && !searching && Boolean(foldedDays[dayKey(gruppe)])}
      {#if day}
        <!-- A day folds like a project: a small arrow before its name. -->
        <button
          class="gruppe tafelkopf day"
          aria-expanded={!folded}
          onclick={() => (foldedDays[dayKey(gruppe)] = !foldedDays[dayKey(gruppe)])}
          transition:slideIfDrawn={{ duration: 160 }}
        >
          <span class="chevron" class:open={!folded}><Hauszeichen zeichen="pfeil_unten" groesse={12} strich={2.6} /></span>
          {gruppe.schluessel ? t(gruppe.schluessel) : gruppenDatum(gruppe.datum, texte.sprache)}
        </button>
      {:else}
        <div class="gruppe tafelkopf" transition:slideIfDrawn={{ duration: 160 }}>
          {t(gruppe.schluessel)}
        </div>
      {/if}
      {#if !folded}
        <div transition:slideIfDrawn={{ duration: 160 }}>
          {#each gruppe.chats as chat (chat.id)}
            <div animate:flip={{ duration: 220 }} transition:slideIfDrawn={{ duration: 180 }}>
              <Chatzeile {chat} oeffnen={chatAusDerListe} menue={menueOeffnen} />
            </div>
          {/each}
        </div>
      {/if}
    {/snippet}

    {#each pinnedGroups as gruppe (gruppe.schluessel)}
      {@render chatGroup(gruppe)}
    {/each}

    <!-- The projects, under the pinned chats and above the days. -->
    {#if !searching && zustand.projects.length}
      <div class="projects">
        {#each zustand.projects as project (project.id)}
          <div transition:slideIfDrawn={{ duration: 160 }}>
            <ProjectRow
              {project}
              open={Boolean(openProjects[project.id])}
              onToggle={() => (openProjects[project.id] = !openProjects[project.id])}
              menu={projectMenu}
              onDropChat={(chatId) => dropIntoProject(chatId, project)}
            />
            {#if openProjects[project.id]}
              <div transition:slideIfDrawn={{ duration: 160 }}>
                {#each chatsByProject[project.id] ?? [] as chat (chat.id)}
                  <div animate:flip={{ duration: 220 }} transition:slideIfDrawn={{ duration: 180 }}>
                    <Chatzeile {chat} nested oeffnen={chatAusDerListe} menue={menueOeffnen} />
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}

    {#each dayGroups as gruppe (gruppe.schluessel ?? gruppe.datum.getTime())}
      {@render chatGroup(gruppe)}
    {/each}

    {#if !zustand.chats.length}
      <div class="gruppe tafelkopf">{zustand.suche ? t('chat.keine_treffer') : t('chat.leer')}</div>
    {/if}

    {#if !searching}
      <ArchiveList menu={placeMenu} />
    {/if}
  </div>
  </div>

  <!-- The five signs of the foot. -->
  <div class="fensterzeile">
    {@render fusszeichen()}
  </div>
</aside>

{#if menue}
  <div
    class="kontextmenue"
    role="menu"
    tabindex="-1"
    style="left:{menue.x}px; top:{menue.y}px; max-height:calc(100vh - {menue.y + 8}px); max-width:calc(100vw - {menue.x + 8}px)"
    transition:fade={{ duration: 100 }}
    onclick={(e) => e.stopPropagation()}
    onkeydown={(e) => { if (e.key === 'Escape') menue = null }}
  >
    {#if menue.kind === 'chat' && menue.picking}
      {#each zustand.projects.filter((project) => project.id !== menue.item.project_id) as project (project.id)}
        <button role="menuitem" title={project.name} onclick={() => moveToProject(menue.item, project)}>
          <Hauszeichen zeichen="ordner" groesse={16} />
          <span class="wort">{project.name}</span>
        </button>
      {/each}
    {:else if menue.kind === 'chat'}
      {@const chat = menue.item}
      <button role="menuitem" onclick={() => anheften(chat)}>
        {chat.pinned ? t('chat.loesen') : t('chat.anheften')}
      </button>
      <button role="menuitem" onclick={() => umbenennen(chat)}>{t('chat.umbenennen')}</button>
      {#if zustand.projects.some((project) => project.id !== chat.project_id)}
        <button role="menuitem" aria-haspopup="menu" onclick={() => (menue.picking = true)}>
          <span class="wort">{t('project.move_to')}</span>
          <span class="weiter"><Hauszeichen zeichen="pfeil_unten" groesse={11} strich={2.6} /></span>
        </button>
      {/if}
      {#if chat.project_id}
        <button role="menuitem" onclick={() => removeFromProject(chat)}>
          {t('project.remove_from')}
        </button>
      {/if}
      <button role="menuitem" onclick={() => archiveChat(chat, true)}>
        {t('archive.put_away')}
      </button>
    {:else if menue.kind === 'project'}
      {@const project = menue.item}
      <button role="menuitem" onclick={() => renameProjectFromMenu(project)}>{t('chat.umbenennen')}</button>
      <button role="menuitem" onclick={() => archiveProject(project, true)}>
        {t('archive.put_away')}
      </button>
    {:else if menue.kind === 'archived-project'}
      {@const project = menue.item}
      <button role="menuitem" onclick={() => archiveProject(project, false)}>
        {t('archive.restore')}
      </button>
      <button role="menuitem" class="gefahr" onclick={() => deleteProject(project)}>{t('chat.loeschen')}</button>
    {:else}
      {@const chat = menue.item}
      <button role="menuitem" onclick={() => archiveChat(chat, false)}>
        {t('archive.restore')}
      </button>
      <button role="menuitem" class="gefahr" onclick={() => loeschen(chat)}>{t('chat.loeschen')}</button>
    {/if}
  </div>
{/if}

<style>
  /* A word on the frame is written in the frame's own ink: when the user
     repaints the gradient, one colour covers the whole sidebar (the
     setters write --rahmen-text); without a choice every level keeps the
     look's own text colour. */
  .seitenleiste {
    /* The starting width; from then on the seam's drag handle writes the
       width inline and remembers it. A custom property, not a raw `width`,
       so a narrow-screen rule below can still set a flat width of its own —
       an inline `width` would outrank any stylesheet rule regardless of a
       media query, which is exactly how the open drawer used to inherit
       the desktop's dragged width under 760px. */
    width: var(--seiten-breite, 285px);
    flex: none;
    display: flex;
    flex-direction: column;
    /* It lies on the frame itself, without a ground of its own: the
       frame's gradient shows through, and no line — the air before the
       chat's surface is the seam. */
    transition: width 0.22s cubic-bezier(0.2, 0.9, 0.3, 1);
  }
  /* While the hand drags the seam, the edge must sit under it — an easing
     that trails behind the pointer reads as lag, not as polish. */
  .seitenleiste.zieht {
    transition: none;
  }
  /* Folded, the full sidebar goes away and the icon bar stands in its place
     (`.zeichenleiste`). */
  .seitenleiste.eingeklappt {
    width: 0;
    overflow: hidden;
  }

  /* The icon bar: the folded sidebar, and below 760px the one that always
     stands. */
  .zeichenleiste {
    display: none;
    flex: none;
    width: var(--rail-width, 52px);
    flex-direction: column;
    align-items: center;
    gap: 4px;
    padding: var(--rail-top, 12px) 0 12px;
    position: relative;
  }
  /* The strip over the first sign that grabs the window, where the window
     buttons stand over the bar: they sit on it, so they take no drag. */
  .grab-strip {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    -webkit-app-region: drag;
  }
  .zeichenleiste.zeigt {
    display: flex;
  }
  .frei { flex: 1; }
  /* The house's sign button: a square, no frame, a ground only under the
     hand or while its window stands open. */
  .zk {
    width: 40px;
    height: 40px;
    flex: none;
    display: grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--rahmen-text, var(--text-still));
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }
  .zk:hover { background: var(--glass-hover); color: var(--text-leise); }
  /* Glass, not a solid fill: the frame shows through, a fine edge holds the
     shape. The edge is an inset shadow so the button keeps its 40 px. */
  .zk.aktiv {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }

  /* The mark and the folding button, one row at the top. The mark stands
     on the frame and wears the frame's ink; the override is scoped to this
     head because the same mark stands on solid grounds elsewhere. */
  .markenkopf :global(.marke) {
    color: var(--rahmen-text, var(--text));
  }
  .markenkopf {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 14px 12px 12px var(--mark-left, 18px);
  }
  /* The first row grabs the window where the window buttons stand in it; the
     button that folds the sidebar stays a button. */
  .markenkopf.grab {
    -webkit-app-region: drag;
  }
  .markenkopf.grab :global(button) {
    -webkit-app-region: no-drag;
  }
  /* The five signs of the foot, spread evenly over one row. */
  /* At the foot even when the list above it is folded away: the top margin
     takes whatever room is left. */
  .fensterzeile {
    flex: none;
    margin-top: auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    /* No gap of its own: five 40 px signs and a gap of 10 px are wider than
       the drawer's 224 px of room, and the last sign would reach out of the
       drawer into the window it is hidden beside. */
    gap: 0;
    padding: 4px 12px 12px;
  }
  @media (prefers-reduced-motion: reduce) {
    .seitenleiste { transition: none; }
  }
  /* One sheet at a time; the container keeps the column shape while a
     sheet rides in. */
  .blatt {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  /* The search reads as a quiet row until it is used: no frame, a ground
     only under the hand or while typing. */
  .suchfeld {
    margin: 0 12px 10px;
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 7px 12px;
    /* 9 like every other small control. */
    border-radius: 9px;
    color: var(--rahmen-text, var(--text-still));
    transition: background 0.12s;
  }
  .suchfeld:hover,
  .suchfeld:focus-within {
    background: var(--bg-erhoben);
    /* On its own ground the field takes the look's ink back — the frame's
       ink was mixed against the gradient, not against this fill. */
    color: var(--text);
  }
  .suchfeld:hover input,
  .suchfeld:focus-within input {
    color: var(--text);
  }
  /* The key of the search, at the field's right end. */
  .taste {
    flex: none;
    padding: 1px 6px;
    border-radius: 6px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--rahmen-text, var(--text-still));
    font: 500 var(--schrift-hinweis) var(--schrift);
  }
  .suchfeld input {
    border: none;
    background: none;
    outline: none;
    color: var(--rahmen-text, var(--text));
    font: inherit;
    font-size: var(--schrift-text);
    width: 100%;
    min-width: 0;
  }
  /* The day headings stand back behind the chats they group: the house
     heading's face (global.css, .tafelkopf), smaller and still. */
  .gruppe.tafelkopf {
    padding: 14px 10px 6px;
    font-size: 13px;
    font-weight: 500;
    color: var(--rahmen-text, var(--text-still));
  }
  /* A day's heading is a button across the row: the arrow, then the name. */
  .gruppe.tafelkopf.day {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    border: none;
    background: none;
    text-align: left;
    cursor: pointer;
  }
  .gruppe.tafelkopf.day .chevron {
    display: inline-flex;
    transform: rotate(-90deg);
    transition: transform 0.2s;
  }
  .gruppe.tafelkopf.day .chevron.open {
    transform: none;
  }
  @media (prefers-reduced-motion: reduce) {
    .gruppe.tafelkopf.day .chevron { transition: none; }
  }
  .kopfstrich {
    flex: none;
    margin: 0 18px 14px;
    border-top: 1px solid color-mix(in srgb, var(--rahmen-text, var(--text)) 16%, transparent);
  }
  /* Both columns that stand in the sidebar's middle scroll on their own:
     the chat list, and the section column of the open menu where it stood.
     They take what is left between the head and the window row, so the
     row stands under the list, never over its last chats. */
  .liste,
  .menueliste {
    overflow-y: auto;
    flex: 1;
    min-height: 0;
  }
  .liste {
    padding: 0 12px;
  }
  /* The rows of a menu list stand 8 px from the sidebar's edge. */
  .menueliste {
    padding: 0 8px;
  }
  /* A menu's first heading starts flush under the hairline, at the same
     height as the chats' search and the first row of a menu without one. */
  .menueliste :global(.menuegruppe:first-child) {
    margin-top: 0;
  }
  /* The section column ends clear of the window row at the foot. */
  .menueliste {
    padding-bottom: 24px;
  }
  /* A sheet that stepped aside while a menu is open: mounted, not drawn. */
  .blatt[hidden] {
    display: none;
  }
  .kontextmenue {
    position: fixed;
    z-index: 50;
    background: var(--bg-erhoben);
    /* 9 — a menu is something you operate, and the palette gives
       controls 9. Every menu in the program wears the same one. A raised
       card with a hairline ring and a soft fall, no frame. */
    border-radius: 9px;
    padding: 5px;
    min-width: 180px;
    box-shadow: 0 0 0 1px var(--linie), 0 18px 40px -8px rgba(0, 0, 0, 0.55);
  }
  .kontextmenue {
    overflow-y: auto;
  }
  .kontextmenue button {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    text-align: left;
    border: none;
    background: none;
    color: var(--text);
    font: inherit;
    font-size: 13px;
    padding: 7px 11px;
    border-radius: 9px;
    cursor: pointer;
  }
  .kontextmenue button:hover {
    background: var(--bg-hoch);
  }
  .kontextmenue .gefahr:hover {
    background: color-mix(in srgb, var(--rot) 12%, var(--bg-erhoben));
  }
  .kontextmenue .wort {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .kontextmenue .weiter {
    display: inline-flex;
    color: var(--text-still);
    transform: rotate(-90deg);
  }
  .projects {
    margin-top: 6px;
  }

  .schleier {
    display: none;
  }

  @media (width < 760px) {
    /* The icon bar always stands on a narrow window; the full sidebar opens
       over the chat from it. */
    .zeichenleiste {
      display: flex;
    }
    .seitenleiste {
      position: absolute;
      z-index: 40;
      height: 100%;
      /* The shipped narrow measure, always — never the desktop column's
         dragged width, however far that was pulled. Plain CSS
         beats the custom property above only because it sets `width`
         directly instead of through `var()`; same specificity, later rule. */
      width: 248px;
      /* A drawer lies over the chat, so here it needs a ground: the
         frame's gradient, laid over the drawer itself — it slides, and a
         ground fixed to the window would not slide with it. */
      background: var(--frame);
      box-shadow: 0 0 40px rgba(0, 0, 0, 0.3);
      transform: translateX(-100%);
      transition: transform 0.22s cubic-bezier(0.2, 0.9, 0.3, 1);
    }
    .seitenleiste.offen {
      transform: none;
    }
    /* On the phone the collapsed state means nothing: the bar lies over the
       chat as a drawer and is closed until opened. So it keeps its full
       width and its full contents here — `offen` decides, not `eingeklappt`.
       The desktop rule for `.eingeklappt` (width: 0, unconditional, further
       up this file) carries the same two-class specificity as this one; a
       phone that collapsed the sidebar back when it was still a desktop
       (`seitenleisteEingeklappt` survives the resize, only `seitenleisteOffen`
       is narrow-only) would otherwise show a drawer that IS open but has no
       width at all — repeating `width` here, not just the border and the
       overflow, is what keeps this later rule the one that wins. */
    .seitenleiste.eingeklappt {
      width: 248px;
      overflow: visible;
    }
  }

  /* Narrower still, the 248px measure itself would leave too little of the
     phone's own width to read comfortably — the drawer takes most of the
     screen instead, and what little chat remains behind it is dimmed. */
  @media (max-width: 480px) {
    .seitenleiste.offen {
      width: 85vw;
    }
    .schleier {
      display: block;
      position: fixed;
      inset: 0;
      z-index: 39;
      background: rgba(0, 0, 0, 0.4);
    }
  }
</style>
