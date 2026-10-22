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
     itself. The model card holds the picker with its door to the
     catalogue, and the folder; its files stand in a folding row of their
     own, under the conversion to GGUF; the check for a newer build of the
     generator sits with the generator, in the sd.cpp card.

     The page stands in the order it is drawn in: a row of two columns on
     top — the model card with the prompt preparation under it on the left,
     memory and devices on the right — then the values of one picture model
     with a choice of the folder's models at their head (the default model to
     begin with), the conversion to GGUF, the folding list of the model
     files, the generator, and the log at the foot. */
  import { api } from '../lib/api.js'
  import { pollWithoutOverlap } from '../lib/pollWithoutOverlap.js'
  import { t } from '../lib/texte.svelte.js'
  import { frage, katalogOeffnen, melde } from '../lib/zustand.svelte.js'
  import Servertafel from './Servertafel.svelte'
  import Serverreihe from './Serverreihe.svelte'
  import { serverHead } from '../lib/serverHead.svelte.js'
  import Serverabschnitt from './Serverabschnitt.svelte'
  import BuildRows from './BuildRows.svelte'
  import UpToDateMark from './UpToDateMark.svelte'
  import UpdateButton from './UpdateButton.svelte'
  import ImageServerFiles from './ImageServerFiles.svelte'
  import ImageConvert from './ImageConvert.svelte'
  import Bildmodellwerte from './Bildmodellwerte.svelte'
  import { imageFiles, loadImageFiles } from '../lib/imageModelFiles.svelte.js'
  import { familyMark, loadImageFamilies } from '../lib/imageFamilies.svelte.js'
  import BildGeraete from './BildGeraete.svelte'
  import Serverlogkopf from './Serverlogkopf.svelte'
  import Promptaufbereitung from './Promptaufbereitung.svelte'
  import {
    protokollOffen,
    oeffneProtokoll,
    setzeProtokollZeilen,
  } from '../lib/protokollfenster.svelte.js'

  /* What this page hands up to the page head (ModelleLokal.svelte), which draws
     it: the start button, the short line beside the name and the port. */
  let { head = $bindable(null) } = $props()

  let stand = $state(null)
  // The generator's further switches and the idle time, handed up by BildGeraete.svelte.
  let geraeteTeile = $state.raw(null)

  /* The running server, as `/bild/turbo` reports it: aus, bereit, zeichnet
     or fehler. */
  let server = $state(null)
  /* What each read of this page last failed with. A failure that lasts is
     said once and not at every poll, and two reads failing with the same
     sentence say it once between them; a read that gets through clears its
     own, so the same failure returning later is news again. The answer
     before a failed read stays on the page. */
  const readFailures = { server: null, stand: null }
  function readFailed(source, fehler) {
    const known = Object.values(readFailures).includes(fehler.message)
    readFailures[source] = fehler.message
    if (!known) melde(fehler.message, 'fehler')
  }
  let switching = $state(false)
  async function loadServer() {
    try {
      server = await api.turboStand()
      readFailures.server = null
    } catch (fehler) {
      readFailed('server', fehler)
    }
  }
  loadServer()
  const serverRunning = $derived(server?.zustand === 'bereit' || server?.zustand === 'zeichnet')
  // The default model, as the service reads it: empty while none is
  // chosen or its file left the folder.
  const startModel = $derived(stand?.standardmodell ?? '')
  /* The family each model's values last read (GET /bild/vorgaben): newer
     than the panel's answer where the reading of the family was just switched
     for the model. A new answer of the panel is the newest word again. */
  let read = $state({})
  $effect(() => {
    if (stand) read = {}
  })
  const families = $derived({ ...stand?.families, ...read })
  loadImageFamilies()

  /* The model whose values stand at the top: the one picked in the choice,
     else the default model, else the folder's first. */
  let viewed = $state('')
  const shown = $derived.by(() => {
    const names = imageFiles.list.map((file) => file.name)
    return [viewed, startModel].find((name) => name && names.includes(name)) ?? names[0] ?? ''
  })
  /* Once a model stands at the top it stays there: choosing another default
     model in the card must not swap the values (and drop changes not saved)
     under the hands of whoever is editing them. */
  $effect(() => {
    if (!viewed && shown) viewed = shown
  })
  const fileChoices = $derived(imageFiles.list.map((file) => {
    const mark = familyMark(families[file.name])
    return {
      wert: file.name,
      text: file.name,
      ...(mark ? { logo: mark } : { letter: file.name.slice(0, 1).toUpperCase() }),
    }
  }))
  /* The open values block, asked whether it holds changes not saved:
     switching the model asks before it throws them away. One question at a
     time. */
  let values = $state(null)
  let asking = false
  async function modellWechseln(name) {
    if (asking || name === shown) return
    if (values?.hasUnsaved()) {
      asking = true
      let yes = false
      try {
        yes = await frage(t('agenten.verwerfen_frage'))
      } finally {
        asking = false
      }
      if (!yes) return
    }
    viewed = name
  }
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
    return pollWithoutOverlap(loadServer, 3000)
  })
  /* The server's one deed. The page head (ModelleLokal.svelte) draws its
     button; the page keeps what the button says and does. */
  const tat = $derived({
    text: serverRunning ? t('modell.server_anhalten') : t('modell.server_starten'),
    // The head button knows two looks, like every server's: running or not.
    punkt: serverRunning ? 'gruen' : 'still',
    // A picture holds the one-picture lock: start and stop wait for it.
    gesperrt: switching || Boolean(server?.picture_running)
      || (!serverRunning && !server?.programm_da),
    onTat: toggleServer,
  })

  serverHead('bild', (value) => (head = value), () => ({
    tat, line: '', port: serverRunning ? server.port : null,
  }))


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
  /* The rows drawn: the list to fetch from, or where none can be fetched
     the greyed builds this machine cannot run. */
  const listedBuilds = $derived(
    variantenFehler || !varianten
      ? []
      : varianten.varianten.length ? varianten.varianten : (varianten.unavailable ?? []),
  )
  const listLocked = $derived(!pickerSteht && !variantenFehler && listedBuilds.length > 0)

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
      readFailures.stand = null
    } catch (fehler) {
      readFailed('stand', fehler)
    }
    try {
      varianten = await api.bildProgrammVarianten()
      variantenFehler = false
    } catch {
      variantenFehler = true
    }
  }
  laden()

  // Each new answer of the panel reads the list of the model files again.
  $effect(() => {
    void stand
    loadImageFiles()
  })

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
    return pollWithoutOverlap(laden, 2000)
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
    return pollWithoutOverlap(protokollLaden, 2000)
  })

  async function protokollZeigen() {
    protokollAuf = !protokollAuf
    if (protokollAuf) await protokollLaden()
  }

  async function protokollAuskoppeln() {
    await protokollLaden()
    oeffneProtokoll(t('modell.protokoll_titel'))
  }



</script>

<!-- The house's server shape (Servertafel.svelte) with the picture
     server's additions: the model card holds the default model with its
     door to the catalogue, and the folder; the values of one model stand
     right under it; the files stand in a folding row of their own with their
     family, size and state, and the conversion to GGUF has its own block;
     memory and devices have their own section, and so has the generator, with its version, its builds and the one check for
     a newer one. -->
<Servertafel
  zeichen="bild"
  modelle={(stand?.modelle ?? []).map((name) => ({ wert: name, text: name }))}
  gewaehlt={startModel}
  modellGeaendert={standardWaehlen}
  modellBeschriftung={t('bildserver.modell')}
  modellInfo={t('bildserver.info_standardmodell')}
  leerText={stand ? t('bildserver.kein_modell_lang') : ''}
  katalogTat={() => katalogOeffnen('bild')}
  speicherort="image_models"
  onOrtGeaendert={laden}
>
  {#snippet inhalt(modelCard)}
    <Serverreihe>
      {#snippet links()}
        {@render modelCard()}
        <Promptaufbereitung />
      {/snippet}
      {#snippet rechts()}
        <div class="stretch"><BildGeraete onklappe={(teile) => (geraeteTeile = teile)} /></div>
      {/snippet}
    </Serverreihe>
    {#if shown}
      <!-- Each model gets a block of its own, so nothing of one model's
           fields stays in another's. -->
      {#key shown}
        <Bildmodellwerte bind:this={values} modell={shown} listen={stand} modelle={fileChoices}
                         onwechsel={modellWechseln}
                         onfamily={(name, family) => (read[name] = family)} />
      {/key}
    {/if}
    <ImageConvert onconverted={laden} />
    <ImageServerFiles familien={families} />
    <!-- The program itself: its name (the program's own, not a word to
         translate), the version of the build on disk, its builds where there
         are several, and the one button that switches the server. -->
    <Serverabschnitt zeichen="server" titel="sd.cpp">
      {#if stand?.programm_da}
        <!-- The build tag at the end when there is one; a dash when the
             program was unpacked into the folder by hand (app/sddownload.py)
             and no tag lies on disk. The sign asks for a newer build and,
             once the check found one, fetches it; the way back to the
             tested build stands below while another one runs. -->
        <div class="zeile">
          <span class="name">{t('bildserver.version_label')}</span>
          {#if aktualisierung?.aktuell}
            <UpToDateMark />
          {/if}
          <UpdateButton found={Boolean(aktualisierung?.verfuegbar)} locked={pruefend || programmLaedt}
                        oncheck={aktualisierungLaden} onupdate={programmAktualisieren} />
          <span class="versionsmarke">{stand.bau ?? '-'}</span>
        </div>
      {/if}
      <!-- `varianten` carries three answers — still loading, the fetch
           failed, this platform has nothing to choose — checked in this
           order so a fetch failure never hides behind stale data. -->
      {#if variantenFehler}
        <div class="zeile"><span class="name v_fehler">{t('bildserver.varianten_fehler')}</span></div>
      {:else if varianten === null}
        <div class="zeile"><span class="name">{t('bildserver.lade_varianten')}</span></div>
      {/if}
      <!-- win32 only: several GPU backends on offer (app/sddownload.py) —
           the list covers both "nothing installed yet" and "one is
           installed, fetch another". Where this machine cannot run them (a
           Mac) the same four stand greyed, and the way back to the tested
           build stands under a fold, while another one runs. -->
      <BuildRows builds={listedBuilds} installed={varianten?.installiert} locked={listLocked}
                 busy={programmLaedt} restorable={Boolean(stand?.programm_da && stand.restorable)}
                 onDownload={programmHolen} onRestore={restoreProgram}>
        {#snippet status()}
          {#if pickerSteht && programmLaedt}
            <div class="zeile">
              <span class="balken"><i style="width:{Math.round(programmStand.anteil * 100)}%"></i></span>
              <span class="v_still">{Math.round(programmStand.anteil * 100)} %</span>
            </div>
          {/if}
        {/snippet}
      </BuildRows>
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
      <!-- The generator's further switches apply to the whole server: their
           fold is the last row of this section (BildGeraete.svelte keeps
           their values and saves them). -->
      {@render geraeteTeile?.schalter()}
    </Serverabschnitt>
    {@render geraeteTeile?.erweitert()}
  {/snippet}
  {#snippet unten()}
    <div class="log">
      <Serverlogkopf offen={protokollAuf} onumschalten={protokollZeigen}
                     onauskoppeln={protokollAuskoppeln} />
      {#if protokollAuf}
        <pre class="protokoll">{protokoll.join('\n') || '-'}</pre>
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
  /* The devices card stands beside the model card and the preparation: it is
     as tall as that column, and its rows share out the extra height the way
     `gewicht` does for the cards of the other pages. */
  .stretch {
    flex: 1 1 auto;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .stretch > :global(.abschnitt) {
    flex: 1 1 auto;
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
  /* Inside a card the card's rule for names (`.karte .name`, Serverabschnitt)
     is as specific as the row and the class here; which of the two wins would
     then depend on the order the two styles are written in. The card in
     front makes this one stronger, so the failure sentence of the variants
     row is red as well, whatever the order. */
  :global(.karte) .zeile .v_fehler {
    color: var(--rot-text);
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
</style>
