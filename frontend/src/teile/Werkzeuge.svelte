<script>
  /* The tools: everything the model can call, in one place — a part of the
     settings page, right under the servers they come from.

     Same rule as the local and cloud tabs of the Models page: left the
     list, right whatever is selected. What appears on the right depends only
     on WHAT was clicked — a source brings its catalogue, a tool brings what
     it does.

     The built-in tool is the first source. It belongs in this list even
     though no server delivers it: from where the model stands there is no
     difference, and a list that leaves out the one tool that always works
     would be lying by omission.

     Picking and switching are two different things here, on purpose — see
     lib/werkzeuge.svelte.js. */
  import { onMount } from 'svelte'
  import Standpille from './Standpille.svelte'
  import Schalter from './Schalter.svelte'
  import Ankreuzliste from './Ankreuzliste.svelte'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import Werkzeugzeichen from './Werkzeugzeichen.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import { LOGOS } from '../lib/logos.js'
  import { rollfade } from '../lib/rollfade.js'
  import { t } from '../lib/texte.svelte.js'
  import { melde } from '../lib/zustand.svelte.js'
  import {
    werkzeugansicht, quellen, aktivStand, EINGEBAUTE_NAMEN, auswahlAufloesen,
    istAn, schalten, istGewaehlt, katalogSchalten, katalogAlle, werkzeugeLaden,
  } from '../lib/werkzeuge.svelte.js'

  let { zuVerbindungen } = $props()

  /* What the right half shows: either a source or one of its tools. */
  const ansicht = werkzeugansicht

  const listen = $derived(quellen())
  /* The selection carries its kind and, for a tool, the row it came from —
     see `auswahlAufloesen`. With a tool open, `quelleDesWerkzeugs` is that
     row and `gewaehlteQuelle` stays empty; with a source open, the other
     way round. */
  const auswahl = $derived(auswahlAufloesen(listen, ansicht.gezeigt))
  const gewaehltesWerkzeug = $derived(auswahl.werkzeug)
  const quelleDesWerkzeugs = $derived(auswahl.werkzeug ? auswahl.quelle : null)
  const gewaehlteQuelle = $derived(auswahl.werkzeug ? null : auswahl.quelle)

  function quelleZeigen(quelle) {
    ansicht.gezeigt = { art: 'quelle', id: quelle.id }
  }
  function werkzeugZeigen(quelle, werkzeug) {
    ansicht.gezeigt = { art: 'werkzeug', name: werkzeug.name, quelle: quelle.id }
  }
  function istGezeigt(quelle, werkzeug) {
    return gewaehltesWerkzeug?.name === werkzeug.name && quelleDesWerkzeugs?.id === quelle.id
  }

  function quellenName(quelle) {
    if (!quelle.eingebaut) return quelle.name
    const schluessel = EINGEBAUTE_NAMEN[quelle.kennung]
    return schluessel ? t(schluessel) : quelle.kennung
  }

  /* Why a source is quiet — the same distinction the gallery makes: switched
     off by hand is not the same as unreachable. */
  function stand(quelle) {
    if (quelle.laeuft) return null
    return quelle.enabled === false ? 'ausgeschaltet' : 'nicht_verbunden'
  }

  async function katalogKippen(eintrag, gewaehlt) {
    try {
      await katalogSchalten(gewaehlteQuelle.eintrag, eintrag.name, gewaehlt)
    } catch {
      melde(t('fehler.allgemein'), 'fehler')
    }
  }

  async function katalogGanz(alle) {
    try {
      await katalogAlle(gewaehlteQuelle.eintrag, alle)
    } catch {
      melde(t('fehler.allgemein'), 'fehler')
    }
  }

  /* Fetched again every time the section is shown: a server added or
     switched off under Connections, the section next door, changes what
     belongs here, and nothing else would tell this list. */
  onMount(() => {
    werkzeugeLaden()
  })

  // Which source boxes are unfolded (ansicht.aufgeklappt) — every box starts
  // folded, so the list reads as sources first and commands on demand.
</script>

<div class="werkzeugseite">
  <div class="zaehler">
    {t('werkzeuge.aktiv_zahl', aktivStand(listen))}
  </div>

  <div class="zwei">
    <div class="links" use:rollfade>
      {#each listen as quelle (quelle.id)}
        <!-- A source and its tools in one raised box, like a settings group:
             the source carries the sign, name and its dotted status; each
             tool below it a name and a switch. -->
        <div class="qbox">
          <div
            class="qkopf"
            class:gewaehlt={quelle.id === gewaehlteQuelle?.id && !gewaehltesWerkzeug}
          >
          <button
            class="qeintrag"
            onclick={() => quelleZeigen(quelle)}
          >
            <!-- The sign says WHICH KIND of source this is: a built-in one
                 draws its own mark, a registered server its brand, and one
                 nobody drew a brand for the house's plug. Never the name
                 alone — a server called "clock" beside the built-in clock
                 would otherwise wear the same sign as the clock. -->
            <span class="qzeichen">
              {#if !quelle.eingebaut && LOGOS[quelle.kennung]}
                <svg viewBox={LOGOS[quelle.kennung].vb} width="18" height="18">{@html LOGOS[quelle.kennung].html}</svg>
              {:else if quelle.eingebaut}
                <Werkzeugzeichen server={quelle.kennung} eingebaut={true} />
              {:else}
                <Hauszeichen zeichen="plug" groesse={18} />
              {/if}
            </span>
            <div class="qmitte">
              <div class="qname">{quellenName(quelle)}</div>
              <div class="qsatz">
                {#if stand(quelle)}
                  {t(`werkzeuge.${stand(quelle)}`)}
                {:else}
                  {t('werkzeuge.von_zahl')
                    .replace('{an}', quelle.werkzeuge.filter((w) => istAn(w.name)).length)
                    .replace('{gesamt}', quelle.eingebaut
                      ? quelle.werkzeuge.length
                      : quelle.katalog.length)}
                {/if}
              </div>
            </div>
            <Leuchtpunkt
              farbe={quelle.laeuft ? 'gruen' : stand(quelle) === 'ausgeschaltet' ? 'gelb' : 'still'}
              groesse={11}
            />
          </button>
            {#if quelle.laeuft && quelle.werkzeuge.length}
              <button
                class="qklapp"
                class:auf={ansicht.aufgeklappt[quelle.id]}
                onclick={() => (ansicht.aufgeklappt[quelle.id] = !ansicht.aufgeklappt[quelle.id])}
                aria-expanded={Boolean(ansicht.aufgeklappt[quelle.id])}
                aria-label={ansicht.aufgeklappt[quelle.id] ? t('werkzeuge.zuklappen') : t('werkzeuge.aufklappen')}
                title={ansicht.aufgeklappt[quelle.id] ? t('werkzeuge.zuklappen') : t('werkzeuge.aufklappen')}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6" /></svg>
              </button>
            {/if}
          </div>

          {#if quelle.laeuft && ansicht.aufgeklappt[quelle.id]}
            {#each quelle.werkzeuge as werkzeug (werkzeug.name)}
              <!-- svelte-ignore a11y_no_static_element_interactions -->
              <div
                class="weintrag"
                class:gewaehlt={istGezeigt(quelle, werkzeug)}
                class:aus={!istAn(werkzeug.name)}
                role="button"
                tabindex="0"
                onclick={() => werkzeugZeigen(quelle, werkzeug)}
                onkeydown={(e) => { if (e.key === 'Enter') werkzeugZeigen(quelle, werkzeug) }}
              >
                <span class="wname werkzeugname">{werkzeug.anzeige ?? werkzeug.name}</span>
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <span onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()}>
                  <Schalter
                    an={istAn(werkzeug.name)}
                    beschriftung={werkzeug.anzeige ?? werkzeug.name}
                    onschalten={(an) => schalten(werkzeug.name, an)}
                  />
                </span>
              </div>
            {/each}
          {/if}
        </div>
      {/each}
    </div>

    <div class="rechts" use:rollfade>
      {#if gewaehltesWerkzeug}
        <div class="kopfkarte">
          <div class="min">
            <div class="gross">{gewaehltesWerkzeug.anzeige ?? gewaehltesWerkzeug.name}</div>
            <div class="unter">
              {quelleDesWerkzeugs ? quellenName(quelleDesWerkzeugs) : ''}
            </div>
          </div>
          <Standpille farbe={istAn(gewaehltesWerkzeug.name) ? 'blau' : 'still'}>
            {t(istAn(gewaehltesWerkzeug.name) ? 'status.aktiv' : 'status.inaktiv')}
          </Standpille>
        </div>

        {#if gewaehltesWerkzeug.beschreibung}
          <h4 class="tafelkopf">{t('werkzeuge.was_es_tut')}</h4>
          <p class="fliess">{gewaehltesWerkzeug.beschreibung}</p>
        {/if}

        <h4 class="tafelkopf">{t('werkzeuge.verhalten')}</h4>
        <!-- A statement, not a control. Whether a tool asks first stands in
             the server entry; a switch here would promise something this
             window cannot keep. Brightness only — this is a fact about the
             tool, not a state of it. -->
        <div class="regel">
          <div class="regeltext">
            {t('werkzeuge.fragt_vorher')}
          </div>
          <span class="wert">
            {t(gewaehltesWerkzeug.needs_confirmation ? 'app.ja' : 'app.nein')}
          </span>
        </div>
      {:else if gewaehlteQuelle}
        <div class="kopfkarte">
          <div class="min">
            <div class="gross schrift">{quellenName(gewaehlteQuelle)}</div>
            <!-- A server REPORTS its tools; the built-in one does not report
                 anything, it simply is one. Counting it would also read
                 "1 Werkzeuge" — a plural over a single thing. -->
            <div class="unter">
              {gewaehlteQuelle.eingebaut
                ? t('werkzeuge.eingebaut_unter')
                : t('werkzeuge.gemeldet_zahl').replace('{zahl}', gewaehlteQuelle.katalog.length)}
            </div>
          </div>
          <Standpille farbe={gewaehlteQuelle.laeuft ? 'gruen' : 'still'}>
            {gewaehlteQuelle.laeuft
              ? t('status.erreichbar')
              : t(`werkzeuge.${stand(gewaehlteQuelle)}`)}
          </Standpille>
        </div>

        <!-- Only where there is something to pick. The built-in tool has no
             catalogue, and a search field over an empty list would promise a
             choice that does not exist. -->
        {#if gewaehlteQuelle.katalog.length}
          <h4 class="tafelkopf">{t('liste.katalog')}</h4>
          <Ankreuzliste
            namensklasse="werkzeugname"
            eintraege={gewaehlteQuelle.katalog}
            istAn={(e) => istGewaehlt(gewaehlteQuelle.eintrag, e.name)}
            onschalten={katalogKippen}
            onalle={katalogGanz}
          />
        {:else if gewaehlteQuelle.eingebaut}
          {#if gewaehlteQuelle.werkzeuge.length}
            <div class="eliste">
              {#each gewaehlteQuelle.werkzeuge as werkzeug (werkzeug.name)}
                <button class="eeintrag" onclick={() => werkzeugZeigen(gewaehlteQuelle, werkzeug)}>
                  <span class="ezeichen">
                    <Werkzeugzeichen name={werkzeug.name} server={werkzeug.quelle} eingebaut={true} />
                  </span>
                  <div class="emitte">
                    <div class="ename werkzeugname">{werkzeug.name}</div>
                    <div class="esatz">{t(`werkzeuge.eingebaut_satz.${werkzeug.name}`)}</div>
                  </div>
                </button>
              {/each}
            </div>
          {/if}
        {/if}

        {#if !gewaehlteQuelle.eingebaut}
          <button class="knopfleise" onclick={zuVerbindungen}>
            {t('werkzeuge.verbindung_einrichten')}
          </button>
        {/if}
      {/if}
    </div>
  </div>
</div>

<style>
  /* The part fills what the settings page leaves under its head; the two
     halves scroll inside it, the bars invisible house-wide. */
  .werkzeugseite {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .zaehler { font-size: 11.5px; color: var(--text-still); margin: 0 0 10px; }
  .zwei {
    display: flex;
    gap: 0;
    flex: 1;
    min-height: 0;
  }
  .links {
    width: 268px;
    flex: none;
    padding: 12px 10px;
    overflow-y: auto;
  }

  /* Each source is a row with its tools indented under it — rows on the
     ground without boxes. */
  .qbox {
    margin-top: 2px;
  }
  .qbox:first-child { margin-top: 0; }
  .qeintrag {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    min-height: 36px;
    text-align: left;
    border: none;
    background: none;
    color: var(--text-leise);
    font: inherit;
    padding: 6px 8px 6px 10px;
    cursor: pointer;
    transition: background 0.12s;
  }
  .qzeichen {
    width: 20px;
    height: 20px;
    flex: none;
    display: grid;
    place-items: center;
    color: inherit;
  }
  .qzeichen :global(svg) { width: 18px; height: 18px; }
  .qmitte { flex: 1; min-width: 0; }
  .qname {
    font-size: 13px;
    font-weight: 400;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .qsatz {
    font-size: 11.5px;
    color: var(--text-still);
    margin-top: 1px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .weintrag {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 10px 6px 40px;
    border-radius: 9px;
    cursor: pointer;
    transition: background 0.12s;
  }
  .weintrag:hover { background: color-mix(in srgb, var(--text) 4%, transparent); }
  .weintrag.gewaehlt { background: var(--glass-button); }
  /* Only the layout — the type comes from `.werkzeugname` (stil/global.css). */
  .wname {
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .weintrag.aus .wname { opacity: 0.42; }

  .rechts { flex: 1; padding: 12px 0 34px 24px; min-width: 0; overflow-y: auto; }
  .kopfkarte {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 0 2px 6px;
  }
  .min { flex: 1; min-width: 0; }
  .gross {
    font-size: 17px;
    font-weight: 600;
    font-family: var(--schrift-fest);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* A source carries a name, not an identifier — the fixed-width face is for
     what the model types. */
  .gross.schrift { font-family: inherit; font-size: 20px; letter-spacing: -0.01em; }
  .unter { font-size: 12.5px; color: var(--text-still); margin-top: 4px; }

  /* Text itself: global.css, .tafelkopf. */
  h4 {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 22px 0 10px;
  }
  h4::after {
    content: '';
    flex: 1;
    border-top: 1px solid var(--linie);
  }
  .fliess { font-size: 13px; color: var(--text-leise); margin: 10px 0 0; }

  /* One row per built-in tool — same icon-name-subtext shape as a source's
     own row on the left, so the two lists read as one language. */
  /* One card, a hairline between its rows. */
  .eliste { margin-top: 14px; padding: 0 16px; background: var(--glass-card); box-shadow: inset 0 0 0 1px var(--glass-card-line); border-radius: 9px; }
  .eeintrag {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    text-align: left;
    border: none;
    border-top: 1px solid var(--linie);
    background: none;
    color: var(--text);
    font: inherit;
    padding: 10px 0;
    cursor: pointer;
    transition: background 0.12s;
  }
  .eliste .eeintrag:first-child { border-top: none; }
  .eeintrag:hover .esatz { color: var(--text-leise); }
  .ezeichen {
    width: 28px;
    height: 28px;
    flex: none;
    border-radius: 9px;
    background: var(--glass-button);
    display: grid;
    place-items: center;
    color: var(--text-leise);
  }
  .ezeichen :global(svg) { width: 18px; height: 18px; }
  .emitte { flex: 1; min-width: 0; }
  /* Only the layout — the type comes from `.werkzeugname` (stil/global.css).
     Left here it would win: a component selector carries Svelte's scoping
     class as well, so it outweighs the house rule by one. */
  .ename {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .esatz {
    font-size: 11px;
    color: var(--text-still);
    margin-top: 1px;
  }

  .regel {
    display: flex;
    align-items: center;
    gap: 12px;
    border-radius: 9px;
    /* A card on the page: card glass with its fine line. */
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    padding: 12px 16px;
  }
  .regeltext { flex: 1; min-width: 0; font-size: 13px; }
  .wert { flex: none; font-size: 13px; color: var(--text-leise); }

  .knopfleise {
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    font: inherit;
    font-size: 13px;
    padding: 6px 12px;
    margin-top: 12px;
    cursor: pointer;
  }
  .knopfleise:hover { background: var(--glass-hover); }

  @media (max-width: 720px) {
    .zwei { flex-direction: column; flex: none; }
    .links { width: 100%; }
    .rechts { padding-left: 0; }
  }
  /* The fold control sits beside the source entry, never inside it — a
     button in a button is not a thing, and the entry keeps its whole face
     for choosing the source. */
  /* The highlight belongs to the whole head, not to the entry alone —
     otherwise the fold control keeps the raised colour and shows up as a
     darker rectangle beside the chosen source. */
  .qkopf {
    display: flex;
    align-items: stretch;
    border-radius: 9px;
    transition: background 0.12s;
  }
  .qkopf:hover { background: color-mix(in srgb, var(--text) 4%, transparent); }
  .qkopf.gewaehlt { background: var(--glass-button); }
  .qkopf.gewaehlt .qeintrag { color: var(--text); }
  .qkopf.gewaehlt .qname { font-weight: 500; }
  .qkopf :global(.qeintrag) {
    flex: 1;
    min-width: 0;
  }
  .qklapp {
    flex: none;
    border: none;
    background: none;
    color: var(--text-still);
    padding: 0 12px 0 4px;
    cursor: pointer;
    display: grid;
    place-items: center;
  }
  .qklapp:hover {
    color: var(--text);
  }
  .qklapp svg {
    transition: transform 0.15s;
  }
  .qklapp.auf svg {
    transform: rotate(180deg);
  }
</style>
