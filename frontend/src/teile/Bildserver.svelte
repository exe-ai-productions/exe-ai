<script>
  /* The picture server, as a tile beside the other servers.

     Its start and stop sit in the page head like theirs. Started, sd-server
     holds the default model with its kit and the machine's memory and
     devices, and every picture after the first is drawn without loading it
     again. Stopped, sd-cli draws every picture
     as before. A picture that needs another model or other start values
     restarts the server on them by itself (app/api/v1/bild.py).

     The state pill and the dot beside the tile say whether sd-server runs,
     nothing else.

     It stands in the shared shape of `Servertafel.svelte`. Its picker is
     the default model: chosen once, it draws in every chat that names no
     model of its own, for the drawing tool outside a chat and at this
     tile's start (app/bildstandardmodell.py); nothing chooses it by
     itself. The model card lists the folder and its files under it; the
     check for a newer build of the generator sits with the generator, in
     the sd.cpp card. */
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { melde } from '../lib/zustand.svelte.js'
  import Servertafel from './Servertafel.svelte'
  import Serverabschnitt from './Serverabschnitt.svelte'
  import UpToDateMark from './UpToDateMark.svelte'
  import Startknopf from './Startknopf.svelte'
  import ImageServerFiles from './ImageServerFiles.svelte'
  import BildGeraete from './BildGeraete.svelte'
  import Auswahlfeld from './Auswahlfeld.svelte'
  import InfoMark from './InfoMark.svelte'
  import Serverlogkopf from './Serverlogkopf.svelte'
  import Promptaufbereitung from './Promptaufbereitung.svelte'
  import {
    protokollOffen,
    oeffneProtokoll,
    setzeProtokollZeilen,
  } from '../lib/protokollfenster.svelte.js'

  let stand = $state(null)

  /* The colours of the server itself: off is quiet, up is green, drawing
     or still loading is blue, a server that was started and is gone is
     red. */
  const SERVER_COLOURS = { aus: 'still', bereit: 'gruen', zeichnet: 'blau', fehler: 'rot' }
  /* The running server, as `/bild/turbo` reports it: aus, bereit, zeichnet
     or fehler. */
  let server = $state(null)
  let switching = $state(false)
  async function loadServer() {
    try {
      server = await api.turboStand()
    } catch {
      server = null
    }
  }
  loadServer()
  const serverRunning = $derived(server?.zustand === 'bereit' || server?.zustand === 'zeichnet')
  // The default model, as the service reads it: empty while none is
  // chosen or its file left the folder.
  const startModel = $derived(stand?.standardmodell ?? '')
  async function standardWaehlen(name) {
    try {
      await api.einstellungSetzen('global', 'bild_standardmodell', name)
      await laden()
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }
  async function toggleServer() {
    if (switching) return
    // Nothing chooses the default model by itself: without one the tile
    // says where it is chosen.
    if (!serverRunning && !startModel) {
      melde(t('bildserver.kein_standardmodell'), 'fehler')
      return
    }
    switching = true
    try {
      server = serverRunning ? await api.turboStoppen() : await api.turboStarten(startModel)
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
      await loadServer()
    } finally {
      switching = false
    }
  }
  /* The server loads its model after the start answered, and a picture
     turns it blue; asked again while the tile is on screen. */
  $effect(() => {
    const timer = setInterval(loadServer, 3000)
    return () => clearInterval(timer)
  })
  /* The window's one deed, handed to the sd.cpp group's head line — the
     button stands in the line of the group, flush with the card
     below it, not up in the head card. */
  const tat = $derived({
    text: serverRunning ? t('modell.server_anhalten') : t('modell.server_starten'),
    // The head button knows two looks, like every server's: running or not.
    punkt: serverRunning ? 'gruen' : 'still',
    // A picture holds the one-picture lock: start and stop wait for it.
    gesperrt: switching || Boolean(server?.picture_running)
      || (!serverRunning && !server?.programm_da),
    onTat: toggleServer,
  })


  /* The generator program, on a machine that does not have it yet. A fresh
     installation used to get a flat refusal here and nowhere to go with it —
     the panel said "not set up" and there was no step that would set it up.
     Now the same place carries the step, in the shape the model server
     panel already uses: one button, then a bar while it comes down. */
  let programmStand = $state(null)
  const programmLaedt = $derived(
    Boolean(programmStand) && !programmStand.fertig && !programmStand.fehler,
  )
  const programmFehlt = $derived(Boolean(stand) && !stand.programm_da)
  // Win32's picker already covers "nothing installed yet" itself (each
  // entry is its own get-this-one button) -- the generic holen block
  // below must stay out of its way, or the two write to the same
  // programmHolen() flow with two different variant arguments at once.
  // Excludes a fresh fetch failure: laden()'s catch deliberately leaves
  // stale `varianten` standing, so a variant-route failure that leaves
  // the download route working must not read as "the picker still
  // stands" -- that would hide the one working way to install.
  const pickerSteht = $derived(Boolean(varianten?.varianten.length) && !variantenFehler)

  /* Which GPU-backend variants this machine could offer, and which one is
     actually on disk — the running/installed backend used to be invisible
     anywhere in the interface. Empty everywhere but win32 (see
     app/sddownload.py); fetched in its own try/catch so a failure here
     never wipes `stand`, the way a shared one would.

     `null` used to carry three different meanings at once -- "still
     loading", "the fetch failed", "this platform has nothing to choose"
     (a legitimate empty list) -- so a failed fetch rendered exactly like
     "no variants on this platform", silently. `variantenFehler` keeps the
     failure distinct from both other states. */
  let varianten = $state(null)
  let variantenFehler = $state(false)

  async function laden() {
    try {
      stand = await api.bildmodelle()
      // Not just "missing" -- a second variant can still be downloading
      // after the first one already made `programm_da` true, and that
      // download's own progress needs the same poll to ever move.
      if (!stand.programm_da || programmLaedt) programmStand = await api.bildProgrammStand()
    } catch {
      stand = null
    }
    try {
      varianten = await api.bildProgrammVarianten()
      variantenFehler = false
    } catch {
      variantenFehler = true
    }
  }
  laden()

  /* Whether a newer release of the generator exists — asked only when the
     button is pressed, never on opening and never inside the poll below: a
     background timer checking GitHub every two seconds while a download
     runs is the background sync the order this came from ruled out. */
  let aktualisierung = $state(null)
  let pruefend = $state(false)

  // Only the newest check may answer: a fetch landing meanwhile clears the
  // answer, and an older one arriving after that must not bring it back.
  let pruefLauf = 0

  async function aktualisierungLaden() {
    const lauf = ++pruefLauf
    pruefend = true
    // The last answer goes while the new one is asked, so it cannot stand
    // beside the running check as if it were its result.
    aktualisierung = null
    try {
      const antwort = await api.bildProgrammAktualisierung()
      if (lauf === pruefLauf) {
        aktualisierung = antwort
        // A list that could not be read compares nothing: said at the top,
        // so the button does not look as if it did nothing.
        if (antwort.unreadable) melde(t('bildserver.updates_nicht_pruefbar'), 'fehler')
      }
    } catch (fehler) {
      if (lauf === pruefLauf) melde(String(fehler.message || fehler), 'fehler')
    } finally {
      if (lauf === pruefLauf) pruefend = false
    }
  }

  /* Only while something is missing or moving. A panel that keeps asking
     after the answer stopped changing is a request every two seconds for
     nothing. `programmLaedt` alone (not just `programmFehlt`) matters now
     that a SECOND variant can be fetched while one is already installed —
     that download starts with `programmFehlt` already false. */
  $effect(() => {
    if (!programmFehlt && !programmLaedt) return
    const takt = setInterval(laden, 2000)
    return () => clearInterval(takt)
  })

  /* Once a fetch actually FINISHES the last answer is cleared — it spoke
     of the build before. starten() returning is only the download
     starting. Watching the true-to-false edge of `programmLaedt` catches
     the moment either kind of fetch (plain or update) really lands, without
     adding a second
     timer. */
  let liefLetztesMal = false
  $effect(() => {
    // The answer from before the fetch no longer says anything; the next
    // press asks again. Nothing is asked by itself.
    if (liefLetztesMal && !programmLaedt) {
      aktualisierung = null
      pruefLauf += 1
      pruefend = false
      // And the build on disk is read once more: the poll that saw the
      // fetch end read it a moment earlier, and stops with this very tick.
      laden()
    }
    liefLetztesMal = programmLaedt
  })

  function programmHolen(variante) {
    api
      .bildProgrammHolen(variante)
      .then((s) => (programmStand = s))
      .catch((fehler) => melde(String(fehler.message || fehler), 'fehler'))
  }

  /* Same shape as programmHolen() above, but through the update route: no
     variant is sent — the backend resolves which one is actually installed
     itself (app/sddownload.py), rather than trust whatever this panel's own
     `varianten` happened to hold (or not yet hold) the moment the button
     was pressed. It also re-reads the release itself rather than trust the
     build this panel showed a moment ago, so a stale offer never silently
     re-fetches what is already there. */
  function programmAktualisieren() {
    api
      .bildProgrammAktualisieren()
      .then((s) => (programmStand = s))
      .catch((fehler) => melde(String(fehler.message || fehler), 'fehler'))
  }

  /* The way back from an update: the tested build is fetched again and
     takes the place of the one installed. Offered only while another build
     than the tested one runs (`stand.restorable`). */
  function restoreProgram() {
    api
      .imageProgramRestore()
      .then((s) => (programmStand = s))
      .catch((fehler) => melde(String(fehler.message || fehler), 'fehler'))
  }

  /* The server log at the window's foot, as every server window has it:
     what sd-server said since its last start, errors included. Fetched when
     the drawer or the big window opens, and every two seconds while one of
     them stands open — a picture's progress moves faster than a click. */
  let protokoll = $state([])
  let protokollAuf = $state(false)

  async function protokollLaden() {
    try {
      protokoll = await api.bildProtokoll()
    } catch {
      protokoll = []
    }
  }

  $effect(() => {
    if (protokollOffen()) setzeProtokollZeilen(protokoll)
  })

  $effect(() => {
    if (!protokollAuf && !protokollOffen()) return
    const takt = setInterval(protokollLaden, 2000)
    return () => clearInterval(takt)
  })

  async function protokollZeigen() {
    protokollAuf = !protokollAuf
    if (protokollAuf) await protokollLaden()
  }

  async function protokollAuskoppeln() {
    await protokollLaden()
    oeffneProtokoll(t('modell.protokoll_titel'))
  }

  function groesseText(bytes) {
    return `${Math.round(bytes / (1024 * 1024))} MB`
  }


</script>

<!-- The house's server shape (Servertafel.svelte) with the picture
     server's additions: the model card holds the default model and lists
     the files with their family, size and "···"; memory and devices have
     their own section, and so has the generator, with its version, its
     builds and the one check for a newer one. -->
<Servertafel
  titel={t('bildserver.titel')}
  zeichen="bild"
  standfarbe={SERVER_COLOURS[server?.zustand] ?? 'still'}
  standtext={serverRunning ? t('status.aktiv') : t('status.inaktiv')}
  modelle={stand?.modelle ?? []}
  modellBeschriftung={t('bildserver.modell')}
  leerText={stand ? t('bildserver.kein_modell_lang') : ''}
  auswahl={false}
  speicherort="image_models"
  onOrtGeaendert={laden}
>
  {#snippet belowModel()}<ImageServerFiles reload={stand} familien={stand?.families ?? {}} />{/snippet}
  {#snippet ersteZeile()}
    <!-- The model card's first row: the one check for a newer generator.
         Up to date — the release was read and is not ahead: the house tick in
         a circle and the word beside it. Newer: the offer in the version row
         of the sd.cpp section. -->
    <button class="feldknopf" disabled={pruefend || programmLaedt || !stand?.programm_da}
            onclick={aktualisierungLaden}>
      {t('bildserver.nach_updates_suchen')}
    </button>
    {#if aktualisierung?.aktuell && stand?.programm_da}
      <UpToDateMark />
    {/if}
  {/snippet}
  {#snippet zweiteZeile()}
    <!-- The default model: every chat that names no model of its own, the
         drawing tool outside a chat and this tile's start draw with it. -->
    <span class="name mitmarke">{t('bildserver.standardmodell')}<InfoMark text={t('bildserver.info_standardmodell')} /></span>
    <div class="wahl">
      <Auswahlfeld wert={startModel} beschriftung={t('bildserver.standardmodell')}
                   eintraege={(stand?.modelle ?? []).map((name) => ({ wert: name, text: name }))}
                   gesperrt={!(stand?.modelle ?? []).length}
                   gewaehlt={standardWaehlen} />
    </div>
  {/snippet}
  {#snippet mitte()}
    <!-- The program itself: its name (the program's own, not a word to
         translate), the version of the build on disk, its builds where there
         are several, and the one button that switches the server. -->
    <BildGeraete />
    <Serverabschnitt zeichen="server" titel="sd.cpp">
      {#snippet rechts()}
        <Startknopf text={tat.text} punkt={tat.punkt} gesperrt={tat.gesperrt} onTat={tat.onTat} />
      {/snippet}
      {#if stand?.programm_da}
        <!-- The build tag when there is one; a dash when the program was
             unpacked into the folder by hand (app/sddownload.py) and no tag
             lies on disk. The update offer only ever appears for a
             tag-named build, and only after the check found one; the way
             back to the tested build stands there while another one runs. -->
        <div class="zeile">
          <span class="name">{t('bildserver.version_zeile', { bau: stand.bau ?? '—' })}</span>
          {#if stand.restorable || aktualisierung?.verfuegbar}
            <span class="buttons">
              {#if stand.restorable}
                <button class="feldknopf" disabled={programmLaedt} onclick={restoreProgram}>
                  {t('bildserver.restore_tested_build')}
                </button>
              {/if}
              {#if aktualisierung?.verfuegbar}
                <button class="feldknopf" disabled={programmLaedt} onclick={programmAktualisieren}>
                  {t('bildserver.generator_aktualisieren')}
                </button>
              {/if}
            </span>
          {/if}
        </div>
      {/if}
      <!-- `varianten` carries three answers — still loading, the fetch
           failed, this platform has nothing to choose — checked in this
           order so a fetch failure never hides behind stale data. -->
      {#if variantenFehler}
        <div class="zeile"><span class="name v_fehler">{t('bildserver.varianten_fehler')}</span></div>
      {:else if varianten === null}
        <div class="zeile"><span class="name">{t('bildserver.lade_varianten')}</span></div>
      {:else if varianten.varianten.length}
        <!-- win32 only: several GPU backends on offer (app/sddownload.py) —
             the list covers both "nothing installed yet" and "one is
             installed, fetch another". -->
        {#each varianten.varianten as v (v.variante)}
          <div class="zeile">
            <span class="name">{v.variante}</span>
            {#if v.variante === varianten.installiert}
              <span class="v_still">{t('bildserver.variante_installiert')}</span>
            {:else}
              <button class="feldknopf" disabled={programmLaedt}
                      onclick={() => programmHolen(v.variante)}>
                {t('bildserver.variante_holen', { groesse: groesseText(v.groesse) })}
              </button>
            {/if}
          </div>
        {/each}
        {#if programmLaedt}
          <div class="zeile">
            <span class="balken"><i style="width:{Math.round(programmStand.anteil * 100)}%"></i></span>
            <span class="v_still">{Math.round(programmStand.anteil * 100)} %</span>
          </div>
        {/if}
      {/if}
      <!-- The missing generator, as one row: the download button, or the
           bar while it comes down. Kept out of the way while the
           win32 picker stands, or the two would write to the same download
           flow with two different builds at once. -->
      {#if programmFehlt && !pickerSteht}
        <div class="zeile">
          {#if programmLaedt}
            <span class="name">{t('bildserver.generator_laedt')}</span>
            <span class="balken"><i style="width:{Math.round(programmStand.anteil * 100)}%"></i></span>
            <span class="v_still">{Math.round(programmStand.anteil * 100)} %</span>
          {:else}
            <!-- A fetch that ended in an error says so beside the button
               that tries again; without it the button simply stood there
               again, as if nothing had been tried. -->
            {#if programmStand?.fehler}
              <span class="v_fehler">{t('bildserver.generator_fehler')}</span>
            {/if}
            <button class="feldknopf" onclick={() => programmHolen()}>{t('bildserver.generator_holen')}</button>
          {/if}
        </div>
      {/if}
    </Serverabschnitt>
    <Promptaufbereitung />
  {/snippet}
  {#snippet unten()}
    <div class="log">
      <Serverlogkopf offen={protokollAuf} onumschalten={protokollZeigen}
                     onauskoppeln={protokollAuskoppeln} />
      {#if protokollAuf}
        <pre class="protokoll">{protokoll.join('\n') || '—'}</pre>
      {/if}
    </div>
  {/snippet}
</Servertafel>

<style>
  .protokoll {
    margin: 0;
    padding: 10px 12px;
    background: var(--code-bg);
    border: 1px solid var(--linie);
    border-radius: 9px;
    font: 400 11px/1.55 var(--schrift-fest);
    color: var(--text-leise);
    max-height: 150px;
    overflow: auto;
    white-space: pre-wrap;
  }
  /* The rows and the buttons are Serverabschnitt.svelte's; here only the
     generator's own marks. */
  .v_still {
    flex: none;
    font-size: 12px;
    line-height: 16px;
    color: var(--text-still);
    white-space: nowrap;
  }
  .v_fehler {
    color: var(--rot);
  }
  .balken {
    flex: 1;
    min-width: 0;
    height: 5px;
    border-radius: 9px;
    background: var(--bg-hoch);
    overflow: hidden;
  }
  .balken i {
    display: block;
    height: 100%;
    background: var(--blau);
    transition: width 0.3s;
  }
  /* The mark right after the name, as on the rest of this page, and its
     sentence on a line of its own below the name when it is open. */
  .mitmarke {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    white-space: normal;
  }
  .mitmarke :global(.mark) {
    margin-left: 0;
  }
</style>
