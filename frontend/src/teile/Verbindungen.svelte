<script>
  import { rollfade } from '../lib/rollfade.js'
  /* The MCP server gallery — one card per server, and each card says what
     the server is for.

     A card carries the maker's logo, the name, one line of purpose and one
     control at its foot. A server that is not yet connected shows a button
     that opens the MCP sheet — the same sheet a brand-new address goes
     through, so a browser sign-in gets no separate door from a plain key. One
     that is on file but has no valid sign-in says so beside that button. A
     server that is on file and needs nothing shows its state there instead,
     and that state is the way into the small options menu below (the switch,
     the tool count, forgetting or removing): once a server works, there is
     nothing left to ask it for.

     The list is the union of the shipped catalog and everything in
     mcp_servers.json; the file stays the one source of truth, reached
     through the card for a server of one's own at the end. Logos are our
     own embedded original vendor vectors (lib/logos.js) — nothing is
     fetched at runtime. */
  import Bereichszeichen from './Bereichszeichen.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import Schalter from './Schalter.svelte'
  import Fenster from './Fenster.svelte'
  import MCPMaske from './MCPMaske.svelte'
  import { api, ApiFehler } from '../lib/api.js'
  import { melde, frage } from '../lib/zustand.svelte.js'
  import { t } from '../lib/texte.svelte.js'
  import { LOGOS } from '../lib/logos.js'
  import { SERVERKATALOG as KATALOG, gehoertZurKachel, serverTitel } from '../lib/serverkatalog.js'

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
     connected catalogue card (`modus: 'kachel'`), or the card for a server
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

  /* A card belongs to the shipped server whose name and address an entry
     carries (`gehoertZurKachel`). An entry under a shipped name that points
     somewhere else is a server of one's own: a card of its own beside the
     shipped one, which stands as not set up. */
  const alle = $derived.by(() => [
    ...KATALOG.map((k) => ({
      katalog: k,
      eintrag: eintraege.find((e) => gehoertZurKachel(k, e)) || null,
    })),
    ...eintraege
      .filter((e) => !KATALOG.some((k) => gehoertZurKachel(k, e)))
      .map((e) => ({ katalog: null, eintrag: e })),
  ])
  /* One grid for all of them, the connected servers first; either half
     keeps the order of the list above. */
  const isConnected = (k) => ['verbunden', 'wartet'].includes(zustand(k))
  const cards = $derived([...alle.filter(isConnected), ...alle.filter((k) => !isConnected(k))])

  function zustand(kachel) {
    const { katalog, eintrag } = kachel
    if (!eintrag) return 'frei'
    if (eintrag.api_key_env && eintrag.schluessel_gesetzt === false) return 'schluessel_fehlt'
    if (!eintrag.enabled) return 'aus'
    const oertlich = katalog && katalog.anmeldung === 'keine'
    /* The browser sign-in is a question for a server reached over the
       network. An entry that starts a program on this machine has nothing
       to sign in to, whatever it is called — it runs or it does not, and
       a name it shares with a shipped server must not turn it into one
       that waits for a sign-in. */
    const oauthKachel =
      katalog && !oertlich && katalog.anmeldung !== 'schluessel' && !eintrag.api_key_env &&
      eintrag.type === 'http'
    if (oauthKachel && !status[eintrag.name]?.verbunden) return 'getrennt'
    if (eintrag.laeuft) return 'verbunden'
    return 'wartet'
  }

  const punktFarbe = (stand) =>
    stand === 'verbunden' || stand === 'wartet' ? 'gruen'
    : stand === 'getrennt' || stand === 'schluessel_fehlt' ? 'rot'
    : 'still'

  const nameVon = (k) => k.katalog?.name || k.eintrag.name
  /* What tells two cards apart: the name alone is not enough once a server
     of one's own carries the name of a shipped one. */
  const schluesselVon = (k) => `${k.katalog ? 'katalog' : 'eigen'}:${nameVon(k)}`
  const katalogNamen = new Set(KATALOG.map((k) => k.name))
  /* The shipped title and logo belong to the shipped server. A server of
     one's own under its name has its own name as the title and the house's
     plug as its sign, as every server of one's own has. */
  const istKatalogName = (k) => k.katalog || !katalogNamen.has(nameVon(k))

  /* What a server is for, in one line. The text catalogue carries a line
     for every shipped server. A server nobody knows has none, and its card
     leaves the line empty. */
  const withPurpose = new Set(KATALOG.map((k) => k.name))
  const purposeOf = (serverName) =>
    withPurpose.has(serverName) ? t(`verbindungen.zweck.${serverName}`) : ''
  const titelVon = (k) => (istKatalogName(k) ? serverTitel(nameVon(k)) : nameVon(k))
  /* The maker's logo, or nothing — then the house's plug stands in. Asked
     for the table's own entries only: a server may be called any word, also
     one every object answers to. */
  const logoVon = (k) => (istKatalogName(k) && Object.hasOwn(LOGOS, nameVon(k)) ? LOGOS[nameVon(k)] : null)
  const kachelVon = (schluessel) => alle.find((k) => schluesselVon(k) === schluessel) || null
  const offeneKachel = $derived(menue ? kachelVon(menue.schluessel) : null)

  /* A server that is not yet connected — never asked for a key, or an
     oauth one nobody has signed into — has nothing to show in the small
     menu but a way into the MCP sheet; its card carries the button into
     that sheet, for every kind, not only the plain-key one.

     Not a server whose key is missing: it is on file, with an entry to
     switch off, and the sheet does not switch it. Its card shows the state,
     which opens the small menu, and the menu carries a way into the sheet
     for the key. The sheet of a server on file does carry the removal, so
     an entry whose sign-in was abandoned can still go. */
  function brauchtVerbindung(k) {
    return ['frei', 'getrennt'].includes(zustand(k))
  }

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

  async function vergessen(eintrag) {
    if (!(await frage(t('verbindungen.vergessen_frage', { name: eintrag.name })))) return
    try {
      await api.oauthVergessen(eintrag.name)
      schliessen()
      await laden()
      nachziehen()
    } catch (error) {
      melde(errorSentence(error), 'fehler')
    }
  }

  async function entfernen(eintrag) {
    if (!(await frage(t('verbindungen.entfernen_frage', { name: eintrag.name })))) return
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

{#snippet card(k)}
  {@const name = nameVon(k)}
  {@const stand = zustand(k)}
  {@const logo = logoVon(k)}
  <div class="card" class:offen={menue?.schluessel === schluesselVon(k)} role="group" aria-label={titelVon(k)}>
    <div class="cardhead">
      <span class="logo" aria-hidden="true">
        {#if logo}
          <svg viewBox={logo.vb} width="40" height="40">{@html logo.html}</svg>
        {:else}
          <Bereichszeichen zeichen="stecker" groesse={40} />
        {/if}
      </span>
      <span class="titel">{titelVon(k)}</span>
    </div>
    <p class="purpose">{purposeOf(name)}</p>
    {#if brauchtVerbindung(k)}
      <!-- One foot line for both kinds. A server never set up shows the
           button alone. One that is on file without a valid sign-in says so
           to the left of it, in the colour of a failure: dot and words as
           plain text without a surface, so the button stays the one thing
           to press. -->
      <div class="foot">
        {#if stand === 'getrennt'}
          <span class="lost">
            <Leuchtpunkt farbe={punktFarbe(stand)} groesse={11} />
            <span class="statetext">{t('verbindungen.stand_getrennt')}</span>
          </span>
        {/if}
        <button class="connect" onclick={() => maskeOeffnen(k)}>{t('verbindungen.verbinden')}</button>
      </div>
    {:else}
      <!-- The state of a server on file, and the way into its menu. The dot
           and the words say the same thing twice on purpose: colour alone
           must not carry a state. -->
      <button
        class="state"
        data-stand={stand}
        onclick={(e) => { e.stopPropagation(); oeffnen(k, e) }}
        aria-haspopup="menu"
        aria-expanded={menue?.schluessel === schluesselVon(k)}
      >
        <Leuchtpunkt farbe={punktFarbe(stand)} groesse={11} />
        <span class="statetext">{t(`verbindungen.stand_${stand}`)}</span>
        <span class="arrow" aria-hidden="true">›</span>
      </button>
    {/if}
  </div>
{/snippet}

<div class="rollbereich" use:rollfade>
  <!-- What the page is for, said once above the cards. -->
  <div class="intro">
    <p class="introhead">{t('verbindungen.einleitung_kopf')}</p>
    <p class="introhint">{t('verbindungen.einleitung')}</p>
  </div>
  <div class="galerie">
    {#each cards as k (schluesselVon(k))}{@render card(k)}{/each}
    <!-- The way to a server nobody shipped: the same card, the house's own
         plug where a maker's logo would stand. -->
    <div class="card own" role="group" aria-label={t('verbindungen.custom_server')}>
      <div class="cardhead">
        <span class="logo" aria-hidden="true"><Bereichszeichen zeichen="stecker" groesse={40} /></span>
        <span class="titel">{t('verbindungen.custom_server')}</span>
      </div>
      <p class="purpose">{t('verbindungen.zweck.eigener')}</p>
      <div class="foot">
        <button class="connect" onclick={mcpNeuOeffnen}>{t('verbindungen.hinzufuegen')}</button>
      </div>
    </div>
  </div>
</div>

{#if menue && offeneKachel}
  {@const k = offeneKachel}
  {@const stand = zustand(k)}
  {@const name = menue.name}
  {@const logo = logoVon(k)}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="schirm" onclick={schliessen}></div>
  <div class="menue" class:oben={menue.nachOben}
       style="top:{menue.top}px; left:{menue.left}px; {menue.nachOben ? 'transform:translateY(-100%);' : ''}">
    <div class="mkopf">
      <span class="mlogo" aria-hidden="true">
        {#if logo}
          <svg viewBox={logo.vb} width="20" height="20">{@html logo.html}</svg>
        {:else}<Bereichszeichen zeichen="stecker" groesse={18} />{/if}
      </span>
      <span class="mtitel">{titelVon(k)}</span>
      <span class="mstand" data-stand={stand}>{t(`verbindungen.stand_${stand}`)}</span>
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
      <button class="mleise" onclick={() => vergessen(k.eintrag)}>{t('verbindungen.vergessen')}</button>
    {/if}
    <!-- Every server on file can be removed, a catalogue one too: removing
         it takes its entry out of the file and leaves the card to be
         connected again, with or without a key. -->
    <button class="mleise gefahr" onclick={() => entfernen(k.eintrag)}>{t('verbindungen.entfernen')}</button>
  </div>
{/if}

<Fenster art="mcp" bind:offen={mcpOffen}
         titel={mcpModus === 'neu'
           ? (mcpName || t('mcp.titel_neu'))
           : t('mcp.titel_kachel', { name: titelVon(mcpKachel) })}>
  {#snippet symbol()}
    <Hauszeichen zeichen={mcpModus === 'neu' ? 'plus' : 'plug'} groesse="mittel" />
  {/snippet}
  <MCPMaske modus={mcpModus} kachel={mcpKachel} fertig={mcpFertig}
            entfernen={mcpKachel?.eintrag ? () => entfernen(mcpKachel.eintrag) : null}
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
  .galerie {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    /* One height for every card of a group, whichever line runs longest. */
    grid-auto-rows: 1fr;
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
  .logo {
    width: 40px;
    height: 40px;
    flex: none;
    display: grid;
    place-items: center;
    color: var(--text);
  }
  .card.own .logo {
    color: var(--text-leise);
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

  /* The foot. Both forms are one size, so a row of cards keeps one line
     whether its servers are connected or not: the button in the colour of
     something to switch on, the state in the colour of what it reports —
     each on the quiet surface every coloured notice sits on, never the
     full colour behind text. */
  .connect,
  .state {
    width: 100%;
    height: 34px;
    border-radius: 9px;
    font: inherit;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }
  /* The foot of a card with a button. The button alone fills it; beside
     the words of a lost sign-in they take the width they need on one line
     and the button takes the rest, so no card of the grid grows taller. The
     words take their height from the button beside them. */
  .foot {
    display: grid;
    grid-auto-flow: column;
    grid-auto-columns: minmax(0, 1fr);
    gap: 8px;
  }
  .foot:has(.lost) {
    grid-auto-columns: auto minmax(0, 1fr);
  }
  .lost {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    font-weight: 600;
    color: var(--rot);
  }
  /* Never broken and never cut: the column of the words is as wide as they
     are. */
  .lost .statetext {
    white-space: nowrap;
    line-height: 1.2;
  }
  .connect {
    color: var(--blau);
    /* A state surface mixes its colour over the card glass. */
    background: color-mix(in srgb, var(--blau) 12%, var(--glass-card));
    border: 1px solid color-mix(in srgb, var(--blau) 28%, transparent);
  }
  .connect:hover {
    background: color-mix(in srgb, var(--blau) 18%, var(--glass-card));
  }
  .state {
    --state-colour: var(--text-leise);
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
  }
  .state[data-stand='schluessel_fehlt'] {
    --state-colour: var(--rot);
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

  /* The click-away shield sits under the menu and over everything else. */
  .schirm {
    position: fixed;
    inset: 0;
    z-index: 80;
  }
  .menue {
    position: fixed;
    z-index: 81;
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
    border-bottom: 1px solid var(--linie);
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
    color: var(--gruen);
  }
  .mstand[data-stand='getrennt'],
  .mstand[data-stand='schluessel_fehlt'] {
    color: var(--rot);
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
    color: var(--rot);
  }
</style>
