<script>
  import { rollfade } from '../lib/rollfade.js'
  import { toRoot } from '../lib/rootPortal.js'
  /* The MCP server gallery: two groups, by whether a server has an entry in
     the file. On top, "Set up": every server with an entry as a card — the
     maker's logo, the name, one line of purpose and one control at its
     foot. A server that is on file and needs nothing shows its state there,
     and that state is the way into the small options menu below (the switch,
     the tool count, forgetting or removing): once a server works, there is
     nothing left to ask it for. One that is on file but has no valid sign-in
     says so beside the grey button that opens the MCP sheet. Below, "Not set
     up": every shipped server without an entry as a wide tile with the grey
     button into that sheet — the same sheet a brand-new address goes
     through, so a browser sign-in gets no separate door from a plain key —
     and last the tile for a server of one's own.

     The list is the union of the shipped catalog and everything in
     mcp_servers.json; the file stays the one source of truth, reached
     through the last tile. A server moves up to a card with the first entry
     written for it and back down to a tile when the entry is removed. Logos
     are our own embedded original vendor vectors (lib/logos.js) — nothing is
     fetched at runtime. */
  import Bereichszeichen from './Bereichszeichen.svelte'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import Schalter from './Schalter.svelte'
  import Fenster from './Fenster.svelte'
  import MCPMaske from './MCPMaske.svelte'
  import { api, ApiFehler } from '../lib/api.js'
  import { melde, frage } from '../lib/zustand.svelte.js'
  import { t } from '../lib/texte.svelte.js'
  import { SERVERKATALOG as KATALOG } from '../lib/serverkatalog.js'
  import {
    cardsOf, zustand as stateOf, setUpCards, notSetUpCards, stateHead as headOf, stateText as textOf,
    punktFarbe, nameVon, schluesselVon, titelVon, logoVon, eigenLogoVon,
  } from '../lib/mcpCards.js'

  let { zuWerkzeugen } = $props()

  let eintraege = $state([]) // GET /tools/servers
  let status = $state({}) // server -> { verbunden, laeuft_ab }

  /* The open options menu: which card it belongs to, and where to draw it.
     Anchored to the card's foot in fixed coordinates so no scroll container
     clips it. Only ever opens for a server on file — a card still to be
     connected goes straight to the sheet below. */
  let menue = $state(null) // { name, schluessel, top, left, nachOben } | null

  /* The MCP sheet (MCPMaske.svelte) — a proper window over the settings
     window, not the anchored menu above. Reached two ways: a not-yet-
     shipped server's tile (`modus: 'kachel'`), or the tile for a server
     of one's own at the end (`modus: 'neu'`). `mcpName` is filled in by the
     sheet itself, once a fresh address answers `initialize` right away —
     the one case where the server's own name is known before anything is
     written down. */
  let mcpOffen = $state(false)
  let mcpModus = $state('neu')
  let mcpKachel = $state(null)
  let mcpName = $state('')

  /* What the message above says when a call fails: the sentence the
     service gave for its refusal — in the page's language, and for an
     unreadable server file the reason the file is no good — and the general
     one only where there is none. */
  function errorSentence(error) {
    const sentence = error instanceof ApiFehler ? error.message : ''
    return sentence || t('fehler.allgemein')
  }

  export async function laden() {
    try {
      const [server, oauth] = await Promise.all([
        api.serverUebersicht(),
        api.oauthStatus(),
      ])
      eintraege = server
      status = Object.fromEntries(oauth.map((s) => [s.server, s]))
    } catch (error) {
      melde(errorSentence(error), 'fehler')
    }
  }

  $effect(() => {
    laden()
  })

  /* The cards, the two groups and every state are worked out in
     lib/mcpCards.js, the same place the server overview reads them from. A
     card belongs to the shipped server whose name and address an entry
     carries; an entry under a shipped name that points somewhere else is a
     server of one's own: a card of its own beside the shipped one, which
     stands as not set up. A server with an entry is a card, the connected
     and starting ones first; one without is a tile. `zustand` stays the one
     place that tells them apart. */
  const alle = $derived(cardsOf(eintraege))
  const setUp = $derived(setUpCards(alle, status))
  const notSetUp = $derived(notSetUpCards(alle, status))
  const zustand = (kachel) => stateOf(kachel, status)
  const stateHead = (stand) => headOf(stand, t)
  const stateText = (k, stand) => textOf(k, stand, t)

  /* What a server is for, in one line. The text catalogue carries a line
     for every shipped server. A server nobody knows has none, and its card
     leaves the line empty. */
  const withPurpose = new Set(KATALOG.map((k) => k.name))
  const purposeOf = (serverName) =>
    withPurpose.has(serverName) ? t(`verbindungen.zweck.${serverName}`) : ''
  /* Only a card on file has a menu: an entry taken out from elsewhere turns
     its card into a tile, and the menu goes with it. */
  const kachelVon = (schluessel) => setUp.find((k) => schluesselVon(k) === schluessel) || null
  const offeneKachel = $derived(menue ? kachelVon(menue.schluessel) : null)

  function maskeOeffnen(k) {
    mcpKachel = k
    mcpModus = 'kachel'
    mcpName = ''
    mcpOffen = true
  }

  /* Open the options menu of a server on file, placed just under the foot
     of its card — or above when the bottom of the window is too close. */
  function oeffnen(k, ereignis) {
    const name = nameVon(k)
    const schluessel = schluesselVon(k)
    if (menue?.schluessel === schluessel) {
      menue = null
      return
    }
    const r = ereignis.currentTarget.getBoundingClientRect()
    const platzUnten = window.innerHeight - r.bottom
    const nachOben = platzUnten < 240
    menue = {
      name,
      schluessel,
      top: nachOben ? r.top - 8 : r.bottom + 8,
      left: Math.min(r.left, window.innerWidth - 244),
      nachOben,
    }
  }
  function schliessen() {
    menue = null
  }

  function mcpNeuOeffnen() {
    mcpKachel = null
    mcpModus = 'neu'
    mcpName = ''
    mcpOffen = true
  }

  function mcpFertig() {
    mcpOffen = false
    laden()
    nachziehen()
  }

  function nachziehen() {
    setTimeout(laden, 1200)
    setTimeout(laden, 5000)
  }

  async function kippen(eintrag) {
    try {
      await api.serverSchreiben(eintrag.name, { enabled: !eintrag.enabled })
      await laden()
      nachziehen()
    } catch (error) {
      melde(errorSentence(error), 'fehler')
    }
  }

  /* The question names the server as its card does; the entry is still
     reached under the key of the file. */
  async function vergessen(eintrag, serverTitle) {
    if (!(await frage(t('verbindungen.vergessen_frage', { name: serverTitle })))) return
    try {
      await api.oauthVergessen(eintrag.name)
      schliessen()
      await laden()
      nachziehen()
    } catch (error) {
      melde(errorSentence(error), 'fehler')
    }
  }

  async function entfernen(eintrag, serverTitle) {
    if (!(await frage(t('verbindungen.entfernen_frage', { name: serverTitle })))) return
    try {
      await api.serverEntfernen(eintrag.name)
      schliessen()
      mcpOffen = false
      await laden()
      nachziehen()
    } catch (error) {
      melde(errorSentence(error), 'fehler')
    }
  }

  function angeboten(eintrag, werkzeug) {
    return eintrag.allowed_tools === null || eintrag.allowed_tools.includes(werkzeug)
  }
  const werkzeugzahl = (eintrag) =>
    eintrag?.laeuft && eintrag.alle_werkzeuge?.length
      ? `${eintrag.alle_werkzeuge.filter((w) => angeboten(eintrag, w.name)).length}/${eintrag.alle_werkzeuge.length}`
      : null
</script>

<svelte:window
  onfocus={() => laden()}
  onresize={schliessen}
  onkeydown={(e) => { if (e.key === 'Escape') schliessen() }}
/>

{#snippet mark(k, size)}
  {@const logo = logoVon(k)}
  {#if logo}
    <svg viewBox={logo.vb} width={size} height={size}>{@html logo.html}</svg>
  {:else if eigenLogoVon(k)}
    <img class="eigenlogo" src={eigenLogoVon(k)} width={size} height={size} alt="" />
  {:else}
    <Bereichszeichen zeichen="stecker" groesse={size} />
  {/if}
{/snippet}

{#snippet card(k)}
  {@const name = nameVon(k)}
  {@const stand = zustand(k)}
  <div class="card" class:offen={menue?.schluessel === schluesselVon(k)} role="group" aria-label={titelVon(k)}>
    <div class="cardhead">
      <span class="logo" aria-hidden="true">{@render mark(k, 40)}</span>
      <span class="titel">{titelVon(k)}</span>
    </div>
    <p class="purpose">{purposeOf(name)}</p>
    {#if stand === 'getrennt'}
      <!-- On file without a valid sign-in: it says so to the left of the
           button, in the colour of a failure — dot and words as plain text
           without a surface, so the button stays the one thing to press. -->
      <div class="foot">
        <span class="lost">
          <Leuchtpunkt farbe={punktFarbe(stand)} groesse={11} />
          <span class="statetext">{t('verbindungen.stand_getrennt')}</span>
        </span>
        <button class="button" onclick={() => maskeOeffnen(k)}>{t('verbindungen.verbinden')}</button>
      </div>
    {:else}
      <!-- The state of a server on file, and the way into its menu. The dot
           and the words say the same thing twice on purpose: colour alone
           must not carry a state. -->
      <button
        class="state"
        data-stand={stand}
        title={stateText(k, stand)}
        onclick={(e) => { e.stopPropagation(); oeffnen(k, e) }}
        aria-haspopup="menu"
        aria-expanded={menue?.schluessel === schluesselVon(k)}
      >
        <Leuchtpunkt farbe={punktFarbe(stand)} groesse={11} />
        <span class="statetext">{stateText(k, stand)}</span>
        <span class="arrow" aria-hidden="true">›</span>
      </button>
    {/if}
  </div>
{/snippet}

<!-- A shipped server without an entry: logo, name, what it is for, and the
     grey button into the sheet. -->
{#snippet tile(k)}
  <div class="tile" role="group" aria-label={titelVon(k)}>
    <span class="tilelogo" aria-hidden="true">{@render mark(k, 36)}</span>
    <span class="tiletext">
      <span class="titel">{titelVon(k)}</span>
      <span class="purpose">{purposeOf(nameVon(k))}</span>
    </span>
    <button class="button" onclick={() => maskeOeffnen(k)}>{t('verbindungen.verbinden')}</button>
  </div>
{/snippet}

<div class="rollbereich" use:rollfade>
  <!-- What the page is for, said once above the groups. -->
  <div class="intro">
    <p class="introhead">{t('verbindungen.einleitung_kopf')}</p>
    <p class="introhint">{t('verbindungen.einleitung')}</p>
  </div>
  {#if setUp.length}
    <section class="section">
      <h3 class="sectionhead">
        <span class="sectionname">{t('verbindungen.section_set_up')}</span>
        <span class="sectioncount">{setUp.length}</span>
      </h3>
      <div class="galerie">
        {#each setUp as k (schluesselVon(k))}{@render card(k)}{/each}
      </div>
    </section>
  {/if}
  <section class="section">
    <h3 class="sectionhead">
      <span class="sectionname">{t('verbindungen.section_not_set_up')}</span>
      <span class="sectioncount">{notSetUp.length}</span>
    </h3>
    <div class="tiles">
      {#each notSetUp as k (schluesselVon(k))}{@render tile(k)}{/each}
      <!-- The way to a server nobody shipped: the same tile, the house's own
           plug where a maker's logo would stand. -->
      <div class="tile own" role="group" aria-label={t('verbindungen.custom_server')}>
        <span class="tilelogo" aria-hidden="true"><Bereichszeichen zeichen="stecker" groesse={36} /></span>
        <span class="tiletext">
          <span class="titel">{t('verbindungen.custom_server')}</span>
          <span class="purpose">{t('verbindungen.zweck.eigener')}</span>
        </span>
        <button class="button" onclick={mcpNeuOeffnen}>{t('verbindungen.hinzufuegen')}</button>
      </div>
    </div>
  </section>
</div>

{#if menue && offeneKachel}
  {@const k = offeneKachel}
  {@const stand = zustand(k)}
  {@const name = menue.name}
  {@const logo = logoVon(k)}
  <!-- The menu and its click-away shield stand at the root of the page, not
       inside the scroller above: drawn inside the scroller's scroll-fade
       mask they painted the area under the first row of cards black. -->
  <div class="menu-layer" use:toRoot>
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
    <div class="schirm" onclick={schliessen}></div>
    <div class="menue" class:oben={menue.nachOben}
         style="top:{menue.top}px; left:{menue.left}px; {menue.nachOben ? 'transform:translateY(-100%);' : ''}">
      <div class="mkopf">
        <span class="mlogo" aria-hidden="true">
          {#if logo}
            <svg viewBox={logo.vb} width="20" height="20">{@html logo.html}</svg>
          {:else if eigenLogoVon(k)}
            <img class="eigenlogo" src={eigenLogoVon(k)} width="20" height="20" alt="" />
          {:else}<Bereichszeichen zeichen="stecker" groesse={18} />{/if}
        </span>
        <span class="mtitel">{titelVon(k)}</span>
        <span class="mstand" data-stand={stand}>{stateHead(stand)}</span>
      </div>

      <!-- Reached once a server is connected or at least configured: a
           card that still needs connecting carries the button into the MCP
           sheet instead. A server on file whose key is missing comes here,
           and the sheet is one row away. The sheet opens before the menu
           closes: `k` follows the open menu and is gone once it closes. -->
      {#if stand === 'schluessel_fehlt'}
        <button class="mzeile alsknopf" onclick={() => { maskeOeffnen(k); schliessen() }}>
          <span>{t('verbindungen.verbinden')}</span>
          <span class="mwert">›</span>
        </button>
      {/if}
      <div class="mzeile">
        <span>{t('verbindungen.aktiv')}</span>
        <Schalter an={k.eintrag.enabled} beschriftung={t('verbindungen.aktiv')}
                  onschalten={() => kippen(k.eintrag)} />
      </div>
      {#if werkzeugzahl(k.eintrag)}
        <button class="mzeile alsknopf" onclick={() => { schliessen(); zuWerkzeugen() }}>
          <span>{t('verbindungen.werkzeuge')}</span>
          <span class="mwert">{werkzeugzahl(k.eintrag)} ›</span>
        </button>
      {/if}
      {#if status[name]?.verbunden}
        <button class="mleise" onclick={() => vergessen(k.eintrag, titelVon(k))}>{t('verbindungen.vergessen')}</button>
      {/if}
      <!-- Every server on file can be removed, a catalogue one too: removing
           it takes its entry out of the file and leaves the card to be
           connected again, with or without a key. -->
      <button class="mleise gefahr" onclick={() => entfernen(k.eintrag, titelVon(k))}>{t('verbindungen.entfernen')}</button>
    </div>
  </div>
{/if}

<Fenster art="mcp" bind:offen={mcpOffen}
         titel={mcpModus === 'neu'
           ? (mcpName || t('mcp.titel_neu'))
           : t('mcp.titel_kachel', { name: titelVon(mcpKachel) })}>
  <MCPMaske modus={mcpModus} kachel={mcpKachel} fertig={mcpFertig}
            entfernen={mcpKachel?.eintrag ? () => entfernen(mcpKachel.eintrag, titelVon(mcpKachel)) : null}
            bind:name={mcpName} />
</Fenster>

<style>
  .rollbereich {
    overflow-y: auto;
    flex: 1;
    min-height: 0;
    padding: 2px;
  }
  /* The two lines above the cards: a section heading and, under it, the
     quiet hint of the settings pages. */
  .intro {
    padding: 2px 2px 14px;
  }
  .introhead {
    margin: 0;
    font-size: var(--schrift-abschnitt);
    font-weight: 600;
  }
  .introhint {
    margin: 2px 0 0;
    font-size: var(--schrift-hinweis);
    color: var(--text-still);
  }
  /* The two groups, each under its heading: the name half bold, the count
     quiet beside it. */
  .section {
    margin-bottom: 28px;
  }
  .sectionhead {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin: 0 0 10px;
    font-size: 13px;
    line-height: 16px;
  }
  .sectionname {
    font-weight: 600;
    color: var(--text-leise);
  }
  .sectioncount {
    font-weight: 400;
    color: var(--text-still);
  }
  /* Three columns at about a thousand pixels of page, four at the full
     width; one column on a phone, where the minimum gives way. */
  .galerie {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(300px, 100%), 1fr));
    /* One height for every card of a group, whichever line runs longest. */
    grid-auto-rows: 1fr;
    gap: 12px;
    align-content: start;
  }
  /* The wide tiles: two columns at about a thousand pixels, three at the
     full width. Every row is as tall as its tallest tile, at least 88. */
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(400px, 100%), 1fr));
    grid-auto-rows: minmax(88px, auto);
    gap: 12px;
    align-content: start;
  }

  /* A card reads from top to bottom: who it is, what it is for, what to do
     with it. The foot sits at the bottom edge whatever the line above it
     needs, so the controls of a row stand on one line. */
  .card {
    /* A card on the page: card glass with its fine line. */
    border: 1px solid var(--glass-card-line);
    border-radius: 9px;
    background: var(--glass-card);
    color: var(--text);
    padding: 14px 14px 12px;
    min-height: 150px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    transition: background 0.12s;
  }
  .card:hover,
  .card.offen {
    background: color-mix(in srgb, var(--text) 8%, var(--glass-card));
  }
  .cardhead {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .eigenlogo {
    object-fit: contain;
    display: block;
  }
  .logo {
    width: 40px;
    height: 40px;
    flex: none;
    display: grid;
    place-items: center;
    color: var(--text);
  }
  /* A tile: the logo at thirty-six, the name over its line, the grey button
     at the right edge. */
  .tile {
    border: 1px solid var(--glass-card-line);
    border-radius: 9px;
    background: var(--glass-card);
    color: var(--text);
    padding: 14px 16px;
    display: grid;
    grid-template-columns: 36px minmax(0, 1fr) auto;
    align-items: center;
    column-gap: 14px;
    transition: background 0.12s;
  }
  .tilelogo {
    width: 36px;
    height: 36px;
    display: grid;
    place-items: center;
    color: var(--text);
  }
  .tile.own .tilelogo {
    color: var(--text-leise);
  }
  .tiletext {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .tile .titel {
    font-size: 14px;
  }
  .tile .purpose {
    flex: none;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    overflow: hidden;
  }
  .titel {
    min-width: 0;
    font-size: 15px;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .purpose {
    flex: 1;
    margin: 0;
    font-size: 12.5px;
    line-height: 1.4;
    color: var(--text-leise);
  }

  /* The foot. Both forms are one height, so a row of cards keeps one line
     whether its servers are connected or not: the state in the colour of
     what it reports on the quiet surface every coloured notice sits on,
     never the full colour behind text — or, for a server whose sign-in is
     gone, the words of that on no surface and the grey house button. */
  .state {
    width: 100%;
    height: 34px;
    border-radius: 9px;
    font: inherit;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }
  /* The words stand left, the button right, on one line: the button is as
     wide as its word needs and as tall as the state button of a card beside
     it, so no card of the grid grows taller. */
  .foot {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .foot .button {
    flex: none;
    height: 34px;
    margin-left: auto;
    padding-top: 0;
    padding-bottom: 0;
  }
  .lost {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    font-weight: 600;
    color: var(--rot-text);
  }
  /* Never broken and never cut: the words are as wide as they are. */
  .lost .statetext {
    white-space: nowrap;
    line-height: 1.2;
  }
  .state {
    --state-colour: var(--text-leise);
    /* The same state as written words: the dot, the surface and the line
       keep the plain colour, the type takes the form made for text. */
    --state-ink: var(--text-leise);
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 12px;
    text-align: left;
    color: var(--state-colour);
    background: color-mix(in srgb, var(--state-colour) 12%, var(--glass-card));
    border: 1px solid color-mix(in srgb, var(--state-colour) 28%, transparent);
  }
  .state:hover {
    background: color-mix(in srgb, var(--state-colour) 18%, var(--glass-card));
  }
  .state[data-stand='verbunden'],
  .state[data-stand='wartet'] {
    --state-colour: var(--gruen);
    --state-ink: var(--gruen-text);
  }
  .state[data-stand='schluessel_fehlt'] {
    --state-colour: var(--rot);
    --state-ink: var(--rot-text);
  }
  .state .statetext {
    color: var(--state-ink);
  }
  .statetext {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .arrow {
    margin-left: auto;
    font-size: 18px;
    line-height: 1;
    color: var(--text-leise);
  }

  /* Only the carrier that moves the two layers to the root; it draws
     nothing and takes no room. */
  .menu-layer {
    display: contents;
  }
  /* The click-away shield sits under the menu. Both stand at the root, at
     the level the settings page itself has (20) plus one and two: over
     the page, under the notifications (25), every window's veil (70) and the
     status strip (80). */
  .schirm {
    position: fixed;
    inset: 0;
    z-index: 21;
  }
  .menue {
    position: fixed;
    z-index: 22;
    width: 236px;
    /* It floats over the page, so it wears the dense glass of every
       drop-down list, not the page's thin card glass. */
    background: var(--glass-dropdown);
    -webkit-backdrop-filter: blur(16px);
    backdrop-filter: blur(16px);
    border: 1px solid transparent;
    /* 9 — a menu is something you operate, and the palette gives controls
       9. Every menu in the program wears the same one. */
    border-radius: 9px;
    box-shadow: 0 0 0 1px var(--glass-button-edge), 0 18px 40px -8px rgba(0, 0, 0, 0.55);
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .mkopf {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-bottom: 8px;
    /* The page's card line: the menu stands at the root, where the page's
       own --linie (set in Seitenrahmen.svelte) no longer reaches it. */
    border-bottom: 1px solid var(--glass-card-line);
  }
  .mlogo {
    width: 20px;
    height: 20px;
    flex: none;
    display: grid;
    place-items: center;
    color: var(--text);
  }
  .mtitel {
    font-size: 13px;
    font-weight: 600;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mstand {
    font-size: 12px;
    color: var(--text-still);
    flex: none;
  }
  .mstand[data-stand='verbunden'],
  .mstand[data-stand='wartet'] {
    color: var(--gruen-text);
  }
  .mstand[data-stand='getrennt'],
  .mstand[data-stand='schluessel_fehlt'] {
    color: var(--rot-text);
  }
  .mzeile {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    font-size: 12.5px;
  }
  .mzeile.alsknopf {
    border: none;
    background: none;
    color: var(--text-leise);
    font: inherit;
    font-size: 12.5px;
    padding: 2px 0;
    cursor: pointer;
    text-align: left;
    width: 100%;
  }
  .mzeile.alsknopf:hover {
    color: var(--text);
  }
  .mwert {
    color: var(--text-still);
  }
  .mleise {
    border: none;
    background: none;
    color: var(--text-still);
    font: inherit;
    font-size: 12px;
    padding: 4px 2px;
    border-radius: 9px;
    cursor: pointer;
    text-align: left;
  }
  .mleise:hover {
    color: var(--text);
  }
  .mleise.gefahr:hover {
    color: var(--rot-text);
  }
</style>
