<script>
  /* The sheet that connects an MCP server without anyone typing JSON.

     One field for a brand-new server: an address. The program asks the
     server what it wants (`api.mcpSondieren`, one unauthenticated
     `initialize`) rather than a person guessing between "via login" and
     "via program" — of eight checked programs, none has that switch; Claude
     Desktop takes an address and fills in the rest itself. A known
     catalogue tile (`modus: 'kachel'`) already knows its own kind, so it
     skips the asking and shows the right row straight away.

     Both ends at the same place: once the server answers — right away, or
     after a key or a browser sign-in — its tools stand in the right
     column, three states a click cycles through, written back as the two
     lists the registry actually reads (app/tools/registry.py). */
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import Hauszeichen from './Hauszeichen.svelte'
  import {
    apiKeyUmgebungsname, grundfelder as grundfelderAus, listenAusZustaenden,
    naechsterZustand, serverKennung, timeLimitFromField, zustandAusEintrag,
  } from '../lib/mcpWerkzeuge.js'

  /* `entfernen`: takes a server's entry out of the file. Given by the page
     only for a card that has an entry; it asks first and closes the sheet. */
  let { modus, kachel = null, fertig, entfernen = null, name = $bindable('') } = $props()

  const istNeu = modus === 'neu'
  /* Where an existing tile's own data comes from: the shipped catalogue for
     a known server, or its own file entry for one nobody shipped — a tile
     reached through the raw JSON editor (Werkzeug-Datei) can be missing a
     key with no catalogue entry to fall back on at all. A custom entry
     never carries `anmeldung` of its own — it only ever reaches this sheet
     through the `schluessel_fehlt` state, so naming a key is the one thing
     it can mean. */
  const quelle = istNeu ? null : (kachel.katalog ?? kachel.eintrag)
  // The catalogue's own word for a browser sign-in is 'oauth'
  // (serverkatalog.js) — this sheet's own state names it 'anmeldung',
  // the same word `sondieren()` returns for a freshly typed address.
  const anmeldungKachel = istNeu ? null : (
    quelle.anmeldung === 'oauth' ? 'anmeldung' : (quelle.anmeldung ?? (quelle.api_key_env ? 'schluessel' : null))
  )

  let adresse = $state(istNeu ? '' : (quelle.url || ''))
  /* A tile whose program wants the address of one's own instance (SearXNG:
     nothing of ours to put in): the sheet asks for it, empty, and the entry
     is written only with it. */
  const fragtAdresse = !istNeu && !kachel.eintrag && !!quelle.address_env
  let eigeneAdresse = $state('')
  let apiKey = $state('')
  // oauth_kennung only: a client id created by hand at the provider
  // (Verbindungen.svelte's own small menu used to ask for this the same
  // way — Google issues no dynamic registration).
  let kennung = $state('')
  let geheimnis = $state('')
  let arbeitet = $state(false)
  let fehler = $state('')
  let verbunden = $state(false)
  let werkzeuge = $state([]) // [{ name, zustand }]
  /* How many seconds one call to this server may take; empty means the
     default (app/tools/mcp_client.py). Read back from the entry once the
     server answers, written with the two lists below. */
  let timeLimit = $state('')
  let gespeicherterName = $state(istNeu ? '' : quelle.name)

  /* What the connect step needs: `undefined` while a new address has not
     been asked yet, `null` once it answered outright, otherwise what it
     asked for. A known tile already knows its own kind, so it starts
     there and never sits at `undefined`. */
  let verlangt = $state(istNeu ? undefined : anmeldungKachel)

  // A sign-in ('anmeldung', or 'oauth_kennung' with its own client id) is
  // done through the row's own "Im Browser anmelden" button — the main
  // one has nothing to submit for either.
  const bereit = $derived(
    verlangt === 'schluessel' ? apiKey.trim().length > 0
    : verlangt === 'anmeldung' || verlangt === 'oauth_kennung' ? false
    : istNeu ? adresse.trim().length > 0
    : fragtAdresse ? eigeneAdresse.trim().length > 0
    : true,
  )

  /* The tile's own preselected tools (Recraft: generate, image-to-image,
     background removal, inpaint) — carried over from the small menu's old
     `verbinden()`, which this sheet now replaces for every not-yet-connected
     tile: the browser sign-in gets the same one door the plain key already
     had. */
  function grundfelder() {
    return grundfelderAus(quelle, kachel.eintrag, {
      mitSchluessel: apiKey.trim().length > 0,
      adresse: eigeneAdresse.trim(),
    })
  }

  /* The server needs a moment to start after the entry is written — the
     registry restarts in the background (app/api/v1/werkzeuge.py). Asked
     for again rather than once: a cold MCP process (npx, first pip run) can
     take longer than a single round trip, and a browser sign-in the person
     is still doing takes longer still. */
  async function werkzeugeLesen(serverName, versuche) {
    for (let versuch = 0; versuch < versuche; versuch++) {
      await new Promise((weiter) => setTimeout(weiter, versuch === 0 ? 500 : 1500))
      const liste = await api.serverUebersicht()
      const eintrag = liste.find((s) => s.name === serverName)
      if (eintrag?.laeuft) {
        werkzeuge = eintrag.alle_werkzeuge.map((w) => ({
          name: w.name,
          zustand: zustandAusEintrag(w.name, eintrag),
        }))
        timeLimit = eintrag.timeout ?? ''
        return true
      }
    }
    return false
  }

  /* A tile of a server the program starts itself has no address to write.
     Not on file — its entry was removed — the entry the program ships comes
     back and the fields go on top of it (app/api/v1/werkzeuge.py). One that
     names its own program ships no entry: it is written from the tile. */
  const shippedServer = !istNeu && !kachel.eintrag && !quelle.url && !quelle.command

  /* A tile the file holds no matching entry for. Its first write goes as a
     new entry: the file may hold a server of one's own under the same name
     (another address), and merged into that one, the tile would overwrite
     it. The service refuses a name that is taken, with its own sentence.
     Once this sheet has written the entry, it is its own. */
  const ohneEintrag = !istNeu && !kachel.eintrag
  let eintragGeschrieben = $state(false)
  const erstesSchreiben = () => ohneEintrag && !eintragGeschrieben

  async function anlegenUndVerbinden(serverName, felder, versuche = 8) {
    // New unless it is the entry this sheet itself wrote a moment ago: a
    // second try at connecting is the same server, not a clash with another
    // one — but a different id is checked again.
    await api.serverSchreiben(serverName, felder, {
      neu: (istNeu && serverName !== gespeicherterName) || erstesSchreiben(),
      shipped: shippedServer,
    })
    eintragGeschrieben = true
    gespeicherterName = serverName
    apiKey = ''
    if (await werkzeugeLesen(serverName, versuche)) {
      verbunden = true
    } else {
      fehler = t('mcp.nicht_erreichbar')
    }
  }

  /* A typed address nobody has asked yet: one unauthenticated `initialize`
     decides what the second click is for. The server's own name only
     exists once it has actually answered — the two paths below cannot
     have it yet, so they work from the address itself. */
  async function sondieren() {
    const url = adresse.trim()
    let antwort
    try {
      antwort = await api.mcpSondieren(url)
    } catch (e) {
      fehler = e.message || t('fehler.allgemein')
      return
    }
    if (antwort.verlangt === null) {
      const serverName = serverKennung(antwort.name || url)
      if (!serverName) {
        fehler = t('mcp.name_ungueltig')
        return
      }
      await anlegenUndVerbinden(serverName, { type: 'http', url })
      // Named only once the entry exists — a refused id keeps the old title.
      name = antwort.name || name
      return
    }
    verlangt = antwort.verlangt
  }

  function hostSlug(url) {
    try {
      return serverKennung(new URL(url).hostname)
    } catch {
      return serverKennung(url)
    }
  }

  async function schluesselVerbinden() {
    const url = adresse.trim()
    const serverName = hostSlug(url)
    if (!serverName) {
      fehler = t('mcp.name_ungueltig')
      return
    }
    const felder = { type: 'http', url }
    if (apiKey.trim()) {
      felder.api_key_env = apiKeyUmgebungsname(serverName)
      felder.api_key = apiKey.trim()
    }
    await anlegenUndVerbinden(serverName, felder)
  }

  async function verbinden() {
    if (!bereit || arbeitet) return
    arbeitet = true
    fehler = ''
    try {
      if (istNeu) {
        if (verlangt === undefined) {
          await sondieren()
        } else if (verlangt === 'schluessel') {
          await schluesselVerbinden()
        }
        return
      }
      // A known tile with a plain key: the same write the old menu did.
      const felder = grundfelder()
      if (apiKey.trim()) {
        felder.api_key_env = quelle.api_key_env
        felder.api_key = apiKey.trim()
      }
      await anlegenUndVerbinden(gespeicherterName, felder)
    } catch (e) {
      fehler = e.message || t('fehler.allgemein')
    } finally {
      arbeitet = false
    }
  }

  /* The browser sign-in — reachable from a fresh address once it asked for
     one, or straight away from a known oauth tile. Writes a working entry
     first: `POST /tools/oauth/start` only knows servers already on file
     (app/api/v1/werkzeuge.py), the same order the old menu wrote in. The
     server's own name is not known yet either way — only a successful
     `initialize` carries it, and that happens after the sign-in, inside
     the registry this sheet does not reach into. */
  async function browserAnmelden() {
    if (arbeitet) return
    arbeitet = true
    fehler = ''
    try {
      const serverName = istNeu ? hostSlug(adresse.trim()) : quelle.name
      if (istNeu) {
        if (!serverName) {
          fehler = t('mcp.name_ungueltig')
          return
        }
        await api.serverSchreiben(
          serverName,
          { type: 'http', url: adresse.trim(), enabled: true },
          { neu: serverName !== gespeicherterName },
        )
      } else {
        await api.serverSchreiben(serverName, grundfelder(), { neu: erstesSchreiben() })
        eintragGeschrieben = true
      }
      gespeicherterName = serverName
      const daten = { server: serverName }
      if (kennung) {
        daten.client_id = kennung
        if (geheimnis) daten.client_secret = geheimnis
      }
      const { url } = await api.oauthStart(daten)
      window.open(url, '_blank')
      // Up to three minutes: a browser sign-in is a person's own pace, not
      // a cold process start.
      if (await werkzeugeLesen(serverName, 90)) {
        verbunden = true
      } else {
        fehler = t('mcp.nicht_erreichbar')
      }
    } catch (e) {
      fehler = e.message || t('fehler.allgemein')
    } finally {
      arbeitet = false
    }
  }

  async function uebernehmen() {
    arbeitet = true
    fehler = ''
    try {
      const { allowed_tools, needs_confirmation } = listenAusZustaenden(werkzeuge)
      await api.serverSchreiben(gespeicherterName, {
        allowed_tools, needs_confirmation, timeout: timeLimitFromField(timeLimit),
      })
      fertig?.()
    } catch (e) {
      fehler = e.message || t('fehler.allgemein')
    } finally {
      arbeitet = false
    }
  }

  function kippen(werkzeug) {
    werkzeug.zustand = naechsterZustand(werkzeug.zustand)
  }
</script>

<div class="mcp">
  <div class="spalten">
    <div class="spalte">
      {#if istNeu}
        <label class="feldblock">
          <span class="tafelkopf"><Hauszeichen zeichen="wolke" groesse="klein" />{t('mcp.url')}</span>
          <input class="eingabe" bind:value={adresse} disabled={verlangt !== undefined}
                 spellcheck="false" autocapitalize="off" />
        </label>
      {/if}
      {#if fragtAdresse}
        <label class="feldblock">
          <span class="tafelkopf"><Hauszeichen zeichen="wolke" groesse="klein" />{t('modell.eigener_adresse')}</span>
          <input class="eingabe" bind:value={eigeneAdresse}
                 spellcheck="false" autocapitalize="off"
                 onkeydown={(e) => { if (e.key === 'Enter' && bereit && !arbeitet) verbinden() }} />
        </label>
      {/if}
      {#if verlangt === 'schluessel'}
        <label class="feldblock">
          <span class="tafelkopf"><Hauszeichen zeichen="schluessel" groesse="klein" />{t('mcp.api_key')}</span>
          <input class="eingabe" type="password" bind:value={apiKey} autocomplete="off"
                 onkeydown={(e) => { if (e.key === 'Enter' && bereit) verbinden() }} />
        </label>
      {:else if verlangt === 'anmeldung' || verlangt === 'oauth_kennung'}
        {#if verlangt === 'oauth_kennung'}
          <!-- The manual path: a self-created client id (Google issues no
               dynamic registration) — the same two fields the small menu
               used to ask for. -->
          <label class="feldblock">
            <span class="tafelkopf"><Hauszeichen zeichen="schluessel" groesse="klein" />{t('verbindungen.kennung')}</span>
            <input class="eingabe" bind:value={kennung}
                   spellcheck="false" autocapitalize="off" />
          </label>
          <label class="feldblock">
            <span class="tafelkopf"><Hauszeichen zeichen="schluessel" groesse="klein" />{t('verbindungen.geheimnis')}</span>
            <input class="eingabe" type="password" bind:value={geheimnis} autocomplete="off" />
          </label>
        {/if}
        <div class="feldblock">
          <span class="tafelkopf"><Hauszeichen zeichen="person" groesse="klein" />{t('mcp.anmeldung')}</span>
          <div class="anmeldezeile">
            <button class="button" disabled={arbeitet || (verlangt === 'oauth_kennung' && !kennung)}
                    onclick={browserAnmelden}>
              {t('mcp.im_browser_anmelden')}
            </button>
          </div>
        </div>
      {/if}
      {#if verbunden}
        <label class="feldblock">
          <span class="tafelkopf"><Hauszeichen zeichen="stoppuhr" groesse="klein" />{t('mcp.zeitgrenze')}</span>
          <span class="limit-row">
            <input class="eingabe limit" type="number" min="1" step="1" inputmode="numeric"
                   placeholder="300" bind:value={timeLimit} />
            <span class="unit">{t('mcp.zeitgrenze_einheit')}</span>
          </span>
        </label>
      {/if}
      <div class="fuellung"></div>
      {#if fehler}<p class="fehlertext">{fehler}</p>{/if}
      <div class="knopfzeile">
        {#if verbunden}
          <button class="button primary" disabled={arbeitet} onclick={uebernehmen}>
            {t('mcp.uebernehmen')}
          </button>
        {:else if verlangt !== 'anmeldung' && verlangt !== 'oauth_kennung'}
          <button class="button primary" disabled={!bereit || arbeitet} onclick={verbinden}>
            {t('verbindungen.verbinden')}
          </button>
        {/if}
        <button class="button" disabled={arbeitet} onclick={() => fertig?.()}>
          {t('app.abbrechen')}
        </button>
        {#if !istNeu && kachel.eintrag && entfernen}
          <button class="button" disabled={arbeitet} onclick={() => entfernen()}>
            {t('verbindungen.entfernen')}
          </button>
        {/if}
      </div>
    </div>
    <div class="trenner"></div>
    <div class="spalte">
      <div class="tafelkopf zeile"><Hauszeichen zeichen="werkzeug" groesse="klein" />{t('mcp.tools_titel')}</div>
      {#if istNeu && verlangt === undefined}
        <!-- Nothing has been asked yet, so nothing can be listed — the
             sign fills the column rather than a sentence explaining an
             empty shelf. -->
        <div class="werkzeugfeld leer">
          <Hauszeichen zeichen="plug" groesse={76} strich={3} />
        </div>
      {:else}
        <div class="werkzeugfeld">
          <div class="werkzeuge">
            {#each werkzeuge as werkzeug (werkzeug.name)}
              <button type="button" class="wz" data-stand={werkzeug.zustand} onclick={() => kippen(werkzeug)}>
                <span class="name">{werkzeug.name}</span>
                <span class="stand">{t(`werkzeuge.${werkzeug.zustand}`)}</span>
              </button>
            {:else}
              <p class="leertext">{t(verbunden ? 'mcp.keine_werkzeuge' : 'mcp.noch_nicht_verbunden')}</p>
            {/each}
          </div>
        </div>
      {/if}
      {#if verbunden}
        <div class="stand-zeile">
          <span class="lampe"></span>
          <span class="wort">{t('mcp.online')}</span>
          <span class="strich">·</span>
          {t('mcp.tools_zahl', { n: werkzeuge.length })}
        </div>
      {/if}
    </div>
  </div>
</div>

<style>
  .mcp { display: flex; flex-direction: column; flex: 1; min-height: 0; }

  /* Two columns with a hairline between them, equal height — a hairline as
     a grid column of its own costs both sides the same, where a border on
     one side ate into it instead (the same shape Anbietermaske.svelte's own
     field pair now uses). */
  .spalten {
    display: grid; grid-template-columns: 1fr 1px 1fr; gap: 18px;
    align-items: stretch; flex: 1; min-height: 0;
  }
  .trenner { background: none; }
  .spalte { display: flex; flex-direction: column; min-width: 0; min-height: 0; }

  /* The house section heading: a word in a line of its own with a hairline
     running off to the right (Sprachserver.svelte:287) — a field label and
     a section heading are the same thing, a word over a block saying what
     the block is. Text itself: global.css, .tafelkopf. Only the flex row
     around it is this panel's own. */
  .tafelkopf {
    display: flex; align-items: center; gap: 8px;
  }
  .feldblock .tafelkopf, .zeile { margin: 2px 0 6px; }
  .feldblock .tafelkopf::after, .zeile::after {
    content: ''; flex: 1; border-top: 1px solid var(--linie);
  }
  .zeile { display: flex; align-items: center; gap: 8px; }

  .feldblock { display: block; margin-bottom: 10px; flex: none; }
  .eingabe {
    display: block; width: 100%; margin-top: 8px; margin-bottom: 8px;
    /* A field on glass: glass with the house's field outline. */
    border: 1px solid var(--feldstrich); border-radius: 9px;
    background: var(--glass-button); color: var(--text);
    font: 400 13px/1.4 var(--schrift);
    padding: 8px 11px;
    height: 32px;
  }
  .feldblock .eingabe { margin-bottom: 0; }
  .eingabe:focus { outline: 2px solid var(--linie-stark); outline-offset: -2px; }
  .eingabe:disabled { opacity: 0.6; }

  .anmeldezeile { display: flex; align-items: center; gap: 9px; margin-top: 7px; }

  /* The number and its unit on one line; the field is as wide as a few
     digits need, not the column. */
  .limit-row { display: flex; align-items: center; gap: 9px; }
  .eingabe.limit { width: 96px; font-variant-numeric: tabular-nums; }
  .unit { margin-top: 8px; font-size: 12px; color: var(--text-still); }

  .fuellung { flex: 1; min-height: 8px; }
  .fehlertext { font-size: 11.5px; color: var(--rot); margin: 0 0 8px; line-height: 1.4; }

  .knopfzeile {
    display: flex; gap: 7px; align-items: center; flex: none;
    margin-top: 10px; padding-top: 4px; border-top: none;
  }
  /* The buttons of the mask are the house button (`.button`, stil/global.css). */

  /* Rolls inside the fixed frame rather than growing it — a server with
     fifty tools must draw the same size sheet as one with six
     (Fenster.svelte's `mcp` art). No visible scrollbar, the house rule
     everywhere else. */
  .werkzeugfeld { position: relative; flex: 1; min-height: 0; display: flex; }
  .werkzeugfeld.leer { display: grid; place-items: center; color: var(--text-still); opacity: 0.16; }
  .werkzeuge {
    display: flex; flex-direction: column; gap: 4px;
    flex: 1; min-height: 0; overflow-y: auto; padding-bottom: 4px;
    scrollbar-width: none; -ms-overflow-style: none;
  }
  .werkzeuge::-webkit-scrollbar { width: 0; height: 0; }
  .werkzeuge > * { flex: none; }
  .leertext { font-size: 12px; color: var(--text-still); margin: 4px 2px; }

  .wz {
    display: flex; justify-content: space-between; align-items: center; gap: 10px;
    padding: 8px 12px; cursor: pointer; width: 100%; font: inherit; text-align: left;
    border: 1px solid var(--glass-card-line); border-radius: 9px; background: var(--glass-card);
    transition: border-color 0.12s;
  }
  .wz:hover { background: color-mix(in srgb, var(--text) 8%, var(--glass-card)); }
  .wz .name {
    font: 400 12.5px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--text);
  }
  .wz .stand { font-size: 12px; color: var(--text-still); }
  /* an = ready to run, fragt = the house's warning colour (waiting for a
     yes), aus = dimmed and struck through — the same three-colour language
     the rest of the program already uses for state. */
  .wz[data-stand='an'] .stand { color: var(--gruen); }
  .wz[data-stand='fragt'] .stand { color: var(--gelb); }
  .wz[data-stand='aus'] { opacity: 0.5; }
  .wz[data-stand='aus'] .name { text-decoration: line-through; }

  .stand-zeile {
    display: flex; align-items: center; gap: 8px; flex: none;
    margin-top: 10px; padding-top: 4px; border-top: none;
    font: 400 12px/1 var(--schrift);
    letter-spacing: normal; color: var(--text-still); white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .stand-zeile .lampe { width: 6px; height: 6px; border-radius: 50%; background: var(--gruen); flex: none; }
  .stand-zeile .wort { color: var(--gruen); }
  .stand-zeile .strich { color: var(--text-still); }
</style>
