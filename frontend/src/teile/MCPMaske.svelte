<script>
  /* The sheet that connects an MCP server without anyone typing JSON.

     One field for a brand-new server: an address. The program asks the
     server what it wants (`api.mcpSondieren`, one unauthenticated
     `initialize`) rather than a person guessing between "via login" and
     "via program" — of eight checked programs, none has that switch; Claude
     Desktop takes an address and fills in the rest itself. A known
     catalogue tile (`modus: 'kachel'`) already knows its own kind, so it
     skips the asking and shows the right row straight away.

     Every card and every new address opens the same sheet: the way the
     server reports itself on top (a browser sign-in, or nothing to sign in
     to), then always "own app" (client id, secret, the return address to
     enter at the provider, an https return address of one's own) and "API
     key" (the key and the header it goes in). A server that runs here, as a
     program, has nothing to sign in to and shows neither.

     Both ends at the same place: once the server answers — right away, or
     after a key or a browser sign-in — its tools stand in the right
     column, three states a click cycles through, written back as the two
     lists the registry actually reads (app/tools/registry.py). */
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import Hauszeichen from './Hauszeichen.svelte'
  import {
    apiKeyUmgebungsname, grundfelder as grundfelderAus, headerFields, headersWithoutKey, keyVariableOf, listenAusZustaenden,
    naechsterZustand, serverKennung, stateWordKey, timeLimitFromField, zustandAusEintrag,
  } from '../lib/mcpWerkzeuge.js'

  /* `entfernen`: takes a server's entry out of the file. Given by the page
     only for a card that has an entry; it asks first and closes the sheet. */
  let { modus, kachel = null, fertig, entfernen = null, name = $bindable('') } = $props()

  /* The sign-in through the browser replaces a key the entry had: both
     would go out together, and the lamp would look for a variable nobody
     reads any more. */
  const signInFields = () => ({
    auth: 'oauth', api_key_env: null, headers: headersWithoutKey(kachel?.eintrag?.headers),
  })

  const istNeu = modus === 'neu'
  /* Where an existing tile's own data comes from: the shipped catalogue for
     a known server, or its own file entry for one nobody shipped — a tile
     reached through the raw JSON editor (Werkzeug-Datei) can be missing a
     key with no catalogue entry to fall back on at all. A custom entry
     carries no `anmeldung` of its own; its browser sign-in is the `auth`
     field of the entry, and without that field it reaches this sheet through
     the `schluessel_fehlt` state, where naming a key is the one thing it can
     mean. */
  const quelle = istNeu ? null : (kachel.katalog ?? kachel.eintrag)
  // The catalogue's own word for a browser sign-in is 'oauth'
  // (serverkatalog.js) — this sheet's own state names it 'anmeldung',
  // the same word `sondieren()` returns for a freshly typed address.
  const anmeldungKachel = istNeu ? null : (
    quelle.anmeldung === 'oauth' || quelle.auth === 'oauth' ? 'anmeldung'
    : (quelle.anmeldung ?? ((quelle.api_key_env || keyVariableOf(quelle.headers)) ? 'schluessel' : null))
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
  /* The header the key goes in: `Authorization` carries it as `Bearer …`,
     any other name carries it as it is (a server that wants `X-Goog-Api-Key`
     rejects a Bearer). An entry whose key already stands in a header shows
     that header's name. */
  const keyHeaders = istNeu ? {} : (kachel.eintrag?.headers ?? {})
  // The variable a key header of the entry already reads: a new key goes to it.
  const usedVariable = keyVariableOf(keyHeaders)
  let headerName = $state(
    Object.keys(keyHeaders).find((name) => keyHeaders[name].includes('${')) ?? 'Authorization',
  )
  /* The return address the person enters at the provider: the one this
     service really uses, or — with an https address of one's own in the
     field — that one. A provider that takes nothing but https (Slack) gets
     the address a forwarding of the person's own leads back here. */
  let ownRedirect = $state('')
  let defaultRedirect = $state('')
  let copied = $state(false)
  let redirectField
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

  /* A server reached over the network has something to sign in to; one that
     runs here as a program does not. */
  const overNetwork = istNeu || !!quelle.url
  // Once the server answers, what is left to set is its tools and its time
  // limit: the ways in make room.
  const showWays = $derived(overNetwork && !verbunden)
  const hasKey = $derived(apiKey.trim().length > 0)
  // The way the server reports: a sign-in through the browser ('anmeldung',
  // or 'oauth_kennung' with its own client id) is done through its own
  // button; a key goes with "connect".
  const browserWay = $derived(verlangt === 'anmeldung' || verlangt === 'oauth_kennung')
  const headerNameValid = $derived(/^[A-Za-z0-9!#$%&'*+.^_`|~-]+$/.test(headerName.trim()))
  const bereit = $derived(
    hasKey ? headerNameValid && (!istNeu || adresse.trim().length > 0)
    : verlangt === 'schluessel' || browserWay ? false
    : istNeu ? adresse.trim().length > 0
    : fragtAdresse ? eigeneAdresse.trim().length > 0
    : true,
  )
  const shownRedirect = $derived(ownRedirect.trim() || defaultRedirect)

  if (overNetwork) {
    api.oauthRedirect().then((antwort) => { defaultRedirect = antwort.redirect_uri }, () => {})
    if (!istNeu) {
      api.oauthStatus().then((liste) => {
        const own = liste.find((e) => e.server === quelle.name)?.redirect_uri
        // Not over what the person has typed in the meantime.
        if (own && !ownRedirect) ownRedirect = own
      }, () => {})
    }
  }

  async function copyRedirect() {
    if (!shownRedirect) return
    try {
      await navigator.clipboard.writeText(shownRedirect)
    } catch {
      // A page over plain http has no clipboard of its own to write to.
      redirectField?.select()
      if (!document.execCommand('copy')) return
    }
    copied = true
    setTimeout(() => { copied = false }, 1500)
  }

  /* What a typed key writes: the header it goes in, the variable in the
     .env the entry names it by (the shipped one where the server has one),
     and the key itself, which the service puts in the .env and out of the
     file. A key replaces any way the entry had before. */
  function keyFields(serverName) {
    const umgebungsname = quelle?.api_key_env || usedVariable || apiKeyUmgebungsname(serverName)
    return { ...headerFields(umgebungsname, headerName, keyHeaders), api_key: apiKey.trim() }
  }

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
    await anlegenUndVerbinden(serverName, { type: 'http', url, ...keyFields(serverName) })
  }

  async function verbinden() {
    if (!bereit || arbeitet) return
    arbeitet = true
    fehler = ''
    try {
      if (istNeu) {
        if (hasKey) {
          await schluesselVerbinden()
        } else if (verlangt === undefined) {
          await sondieren()
        }
        return
      }
      // A known tile: its own preselection, and a key with the header it goes in.
      const felder = grundfelder()
      if (hasKey) Object.assign(felder, keyFields(gespeicherterName))
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
          { type: 'http', url: adresse.trim(), enabled: true, ...signInFields() },
          { neu: serverName !== gespeicherterName },
        )
      } else {
        await api.serverSchreiben(
          serverName, { ...grundfelder(), ...signInFields() }, { neu: erstesSchreiben() },
        )
        eintragGeschrieben = true
      }
      gespeicherterName = serverName
      const daten = { server: serverName }
      if (kennung) {
        daten.client_id = kennung
        if (geheimnis) daten.client_secret = geheimnis
      }
      if (ownRedirect.trim()) daten.redirect_uri = ownRedirect.trim()
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
      <div class="fields">
        {#if istNeu}
          <label class="feldblock">
            <span class="label">{t('mcp.url')}</span>
            <input class="eingabe" bind:value={adresse} disabled={verlangt !== undefined}
                   spellcheck="false" autocapitalize="off" />
          </label>
        {/if}
        {#if fragtAdresse}
          <label class="feldblock">
            <span class="label">{t('modell.eigener_adresse')}</span>
            <input class="eingabe" bind:value={eigeneAdresse}
                   spellcheck="false" autocapitalize="off"
                   onkeydown={(e) => { if (e.key === 'Enter' && bereit && !arbeitet) verbinden() }} />
          </label>
        {/if}
        {#if browserWay && !verbunden}
          <!-- The way the server reports itself: a sign-in through the
               browser. With a client id in the fields below it signs in with
               that app. -->
          <div class="feldblock">
            <span class="label">{t('mcp.anmeldung')}</span>
            <div class="anmeldezeile">
              <button class="button" disabled={arbeitet || (verlangt === 'oauth_kennung' && !kennung)}
                      onclick={browserAnmelden}>
                {t('mcp.im_browser_anmelden')}
              </button>
            </div>
          </div>
        {/if}
        {#if showWays}
          <div class="heading">{t('mcp.eigene_app')}</div>
          <!-- The manual path: a self-created client id (Google issues no
               dynamic registration) — the same two fields the small menu
               used to ask for. -->
          <div class="pair">
            <label class="feldblock">
              <span class="label">{t('verbindungen.kennung')}</span>
              <input class="eingabe" bind:value={kennung}
                     spellcheck="false" autocapitalize="off" />
            </label>
            <label class="feldblock">
              <span class="label">{t('verbindungen.geheimnis')}</span>
              <input class="eingabe" type="password" bind:value={geheimnis} autocomplete="off" />
            </label>
          </div>
          <div class="feldblock">
            <span class="label">{t('mcp.rueckleitung')}</span>
            <div class="copyrow">
              <input class="eingabe" readonly value={shownRedirect} bind:this={redirectField}
                     aria-label={t('mcp.rueckleitung')} spellcheck="false" />
              <button class="button" data-copied={copied} disabled={!shownRedirect} onclick={copyRedirect}>
                {t('nachricht.kopieren')}
              </button>
            </div>
          </div>
          <label class="feldblock">
            <span class="label">{t('mcp.eigene_rueckleitung')}</span>
            <input class="eingabe" bind:value={ownRedirect}
                   spellcheck="false" autocapitalize="off" />
          </label>
          <div class="pair">
            <label class="feldblock">
              <span class="label">{t('mcp.api_key')}</span>
              <input class="eingabe" type="password" bind:value={apiKey} autocomplete="off"
                     onkeydown={(e) => { if (e.key === 'Enter' && bereit) verbinden() }} />
            </label>
            <label class="feldblock">
              <span class="label">{t('mcp.kopfzeile')}</span>
              <input class="eingabe" bind:value={headerName}
                     spellcheck="false" autocapitalize="off" />
            </label>
          </div>
        {/if}
        {#if verbunden}
          <label class="feldblock">
            <span class="label">{t('mcp.zeitgrenze')}</span>
            <span class="limit-row">
              <input class="eingabe limit" type="number" min="1" step="1" inputmode="numeric"
                     placeholder="300" bind:value={timeLimit} />
              <span class="unit">{t('mcp.zeitgrenze_einheit')}</span>
            </span>
          </label>
        {/if}
      </div>
      {#if fehler}<p class="fehlertext">{fehler}</p>{/if}
    </div>
    <div class="trenner"></div>
    <div class="spalte">
      <div class="heading">{t('mcp.tools_titel')}</div>
      {#if istNeu && verlangt === undefined && !verbunden}
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
                <span class="stand">{t(stateWordKey(werkzeug.zustand))}</span>
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
  <!-- The buttons stand under both columns, as wide as the widest and one
       line each: three of them did not fit into a single column. -->
  <div class="knopfzeile">
    {#if verbunden}
      <button class="button primary" disabled={arbeitet} onclick={uebernehmen}>
        {t('mcp.uebernehmen')}
      </button>
    {:else}
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

  /* A field's label is a small quiet line over the field, with no sign and
     no rule; a section heading ("Own app", "Tools") is half bold in the text
     colour, one step above it. */
  .label {
    display: block; margin-bottom: 6px;
    font-size: 12px; line-height: 15px; color: var(--text-leise);
  }
  .heading {
    margin: 2px 0 6px;
    font-size: 13px; line-height: 16px; font-weight: 600; color: var(--text);
  }

  .feldblock { display: block; margin-bottom: 10px; flex: none; }
  .eingabe {
    display: block; width: 100%; margin-top: 0; margin-bottom: 8px;
    /* A field on glass: glass with the house's field outline. */
    border: 1px solid var(--feldstrich); border-radius: 9px;
    background: var(--glass-button); color: var(--text);
    font: 400 13px/1.4 var(--schrift);
    padding: 8px 11px;
    height: 34px;
  }
  .feldblock .eingabe { margin-bottom: 0; }
  .eingabe:focus { outline: 2px solid var(--linie-stark); outline-offset: -2px; }
  .eingabe:disabled { opacity: 0.6; }

  .anmeldezeile { display: flex; align-items: center; gap: 9px; }

  /* The number and its unit on one line; the field is as wide as a few
     digits need, not the column. */
  .limit-row { display: flex; align-items: center; gap: 9px; }
  .eingabe.limit { width: 96px; font-variant-numeric: tabular-nums; }
  .unit { font-size: 12px; color: var(--text-still); }

  /* The fields roll inside the fixed frame, the buttons stay in sight — no
     visible scrollbar, the house rule (like the tool list on the right). */
  .fields {
    flex: 1; min-height: 0; overflow-y: auto; padding-bottom: 4px;
    scrollbar-width: none; -ms-overflow-style: none;
  }
  .fields::-webkit-scrollbar { width: 0; height: 0; }
  .fields > * { flex: none; }
  .fields > .heading { margin-top: 6px; }

  /* Two fields side by side, so the sheet fits its frame with little rolling. */
  .pair { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .pair .feldblock { min-width: 0; }

  /* The return address and the button that copies it on one line. */
  .copyrow { display: flex; align-items: center; gap: 9px; }
  .copyrow .eingabe { flex: 1; min-width: 0; }
  /* The label stays, so the row does not jump: the word turns green. */
  .copyrow button[data-copied='true'] { color: var(--gruen-text); }
  .fehlertext { font-size: 11.5px; color: var(--rot-text); margin: 0 0 8px; line-height: 1.4; }

  /* One grid column per button, every column as wide as the widest one: the
     buttons come out the same width and height. From a window of 720 px
     (the narrowest the program opens) no label breaks; on a phone the sheet
     is narrower than the row, so the row stays inside it and the labels may
     break there. */
  .knopfzeile {
    display: grid; grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); gap: 7px;
    width: max-content; max-width: 100%; align-self: flex-end; flex: none;
    margin-top: 10px; padding-top: 4px;
  }
  @media (min-width: 720px) {
    .knopfzeile .button { white-space: nowrap; }
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
    font: 400 12.5px/1.4 var(--schrift-fest); color: var(--text);
  }
  .wz .stand { font-size: 12px; color: var(--text-still); }
  /* an = ready to run, fragt = the house's warning colour (waiting for a
     yes), aus = dimmed and struck through — the same three-colour language
     the rest of the program already uses for state. */
  .wz[data-stand='an'] .stand { color: var(--gruen-text); }
  .wz[data-stand='fragt'] .stand { color: var(--gelb-text); }
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
  .stand-zeile .wort { color: var(--gruen-text); }
  .stand-zeile .strich { color: var(--text-still); }
</style>
