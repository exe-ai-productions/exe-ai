<script>
  /* Everything a llama.cpp server is started with, as one set of controls.

     Two pages show it: the model server (Modellserver.svelte) and the agent
     server (Agentserver.svelte). They start two different processes with two
     different lifetimes and two different places to keep their numbers — but
     the numbers themselves are the same numbers, because it is the same
     engine underneath. Kept as two copies they would have drifted the first
     time somebody added a lever to one of them, and the second page would
     have been "the one that is missing something" forever after.

     It owns no state and remembers nothing. Every value is bound in from
     the page above, and the page decides where it lives — each server's own
     setting, one key per server (app/runnermodellwahl.py,
     app/agentenmodellwahl.py). The persistence stays out of here because the
     two keys are two keys: a component that remembered things would have to
     be told which one it is writing into, and would be two components again.

     `teil` says which half of the sheet a caller wants, because the pages
     put the groups into two columns: the model
     server shows `module` and `fein` on the right, `speicher` on the left.
     One instance per half, the same one home for the shared rules.

     The one thing it keeps is whether the advanced drawer stands open,
     which is not a setting but a state of the page one is looking at.

     `kennung` prefixes the field ids so two of these can exist in one
     document without two elements answering to the same name. The model
     server passes `rs`, which is what its fields were called before this
     component existed. */
  import { untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import { t, texte } from '../lib/texte.svelte.js'
  import { formatGb } from '../lib/numberDisplay.js'
  import { IDLE_MINUTEN_MAX } from '../lib/feineinstellungen.js'
  import Auswahlfeld from './Auswahlfeld.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Schalter from './Schalter.svelte'
  import Schieberegler from './Schieberegler.svelte'
  import Serverabschnitt from './Serverabschnitt.svelte'
  import Zahlenfeld from './Zahlenfeld.svelte'

  /* `vorladen` is `null` on a server that has no preload switch to show
     (the speech server: nothing here ever starts by itself ahead of time)
     and a boolean on the two that do — the model server and the agent slot
     (the same lever on both). `null`
     hides the row the same way `schaetzung`/`maschineGb` hide their own
     line below, rather than a second flag next to a value that would then
     have to agree with it. */

  let {
    kennung = 'rs',
    /* Which half of the sheet: 'module' (the two plug-in rows), 'speicher'
       (context, layers, threads, MoE), 'fein' (the advanced drawer with
       preload, parallel requests and port), 'leerlauf' (the advanced drawer
       with the idle time alone, for the servers that have nothing else to
       set there) — or 'alles' for the whole sheet in one column. */
    teil = 'alles',
    /* A running server is not edited, it is stopped first — the same rule
       both pages follow, so it arrives as one flag rather than being decided
       field by field in here. */
    gesperrt = false,

    /* Which sections a page shows. On by default, so the two pages that were
       here first are untouched — a third one turns off what its server has no
       answer for. A speech server takes no speed module (nothing drafts a
       transcription) and its projector is not a module but a requirement, so
       a row offering "none" would offer a server that cannot hear; and the
       engine levers below are for fitting a big chat model onto a small card,
       which is not the question a one-gigabyte speech model asks.

       Switched off rather than a second set of sliders built next door: the
       three numbers ARE the same three numbers, and a copy of them would
       drift the first time somebody changed one. */
    module = true,
    erweitert = true,
    /* A one-gigabyte speech model has no experts to put anywhere: the row
       is left out there rather than shown switched off. */
    moe = true,
    /* Left out where the server has no window to set — the voice reads one
       answer to a fixed text and is done, so a context row there would be a
       setting nobody could justify. Shown everywhere else. */
    kontextzeile = true,

    drafter = $bindable(''),
    drafterauswahl = [],
    drafterGewaehlt = () => {},

    vision = $bindable(''),
    visionauswahl = [],
    visionGewaehlt = () => {},

    kontext = $bindable(8192),
    kontextstufen = [],
    /* The window's bounds as the field takes them: a server whose window has
       narrower bounds than the engine's names them. */
    kontextMin = 512,
    kontextMax = 1048576,
    /* `null` is "Auto": no count is sent and the engine places the layers. */
    schichten = $bindable(null),
    maxSchichten = 99,
    faeden = $bindable(0),
    maxFaeden = 8,

    vorladen = $bindable(null),
    /* Whether a run the program places itself may land on this server — the
       approval, `null` on a server that has no runs (hides the row like
       `vorladen`). It is no start value, so it is not locked while the
       server runs, and it is written the moment it is switched
       (`onuseforruns`) instead of with the numbers. */
    useForRuns = null,
    onuseforruns = null,

    /* The two levers only the embedding server has: how the vectors of a
       text are pooled, and the batch size a text may have. `null` leaves the
       row out, like `vorladen` above. The pooling choice names its entries
       ("" is the model's own kind); the batch stands between its floor and
       the window. */
    pooling = $bindable(null),
    poolingauswahl = [],
    batch = $bindable(null),
    batchMin = 2048,
    /* The cache rows (the 8-bit cache and the shared cache) are for a server
       that holds a conversation; the embedding server has none. */
    kvZeilen = true,

    fein = $bindable({ kv_cache: 'f16', flash_attention: 'auto', moe_auf_cpu: false, festnageln: false }),
    /* Experts on the CPU as one number: above
       zero names a count, empty means off. */
    moeSchichten = $bindable(null),
    parallel = $bindable(null),
    maxParallel = 64,

    /* Minutes without a request after which the server frees its model;
       empty is never. `undefined` leaves the row out (a page that has no such
       field), `null` is the empty field. */
    idle = $bindable(undefined),

    port = $bindable(8080),

    /* What the start is expected to cost, and what the machine has. Both
       come from above because only the page knows which model list the
       estimate was drawn from. Absent, the row simply does not appear. The
       machine's whole memory is only what the plan is measured against where
       the system names no limit of its own for wired memory. */
    schaetzung = null,
    maschineGb = null,
  } = $props()

  const kurzK = (n) => (n ? Math.round(n / 1024) + 'k' : '')

  /* The cache's stages and flash attention's answers. A cache below 16 bit
     needs flash attention, so "off" stands in the list but cannot be taken
     while the cache is smaller — and a cache made smaller takes "off" back
     to Auto, so the pair that is shown can run. */
  const kvChoices = $derived([
    { wert: 'f16', text: t('modell.kv_f16') },
    { wert: 'q8_0', text: t('modell.kv_q8') },
    { wert: 'q5_0', text: t('modell.kv_q5') },
    { wert: 'q4_0', text: t('modell.kv_q4') },
  ])
  const flashChoices = $derived([
    { wert: 'auto', text: t('modell.flash_auto') },
    { wert: 'on', text: t('modell.flash_an') },
    { wert: 'off', text: t('modell.flash_inaktiv'), gesperrt: fein.kv_cache !== 'f16' },
  ])
  function kvChosen(neu) {
    if (neu !== 'f16' && fein.flash_attention === 'off') fein.flash_attention = 'auto'
  }

  /* Open on start: every lever of the server stands in view, and the head
     still folds the drawer away for whoever does not need it. */
  let erweitertOffen = $state(true)

  /* The MoE track needs a plain number; "off" is the empty field, and so is
     a zero. Both sides are kept in step, each effect reading only the side
     it follows and writing the other without reading it back: reading both
     would let the field's effect put the track back to where the field
     stands before the track's effect has told the field where the hand left
     it, and the track could not be dragged from an empty field. */
  let moeRegler = $state(0)
  $effect(() => {
    const ziel = moeSchichten ?? 0
    untrack(() => {
      if (moeRegler !== ziel) moeRegler = ziel
      if (moeSchichten === 0) moeSchichten = null
    })
  })
  $effect(() => {
    const spur = moeRegler
    untrack(() => {
      const ziel = spur > 0 ? spur : null
      if (moeSchichten !== ziel) moeSchichten = ziel
    })
  })

  /* The layer track needs a plain number; "Auto" is the empty field. It
     stands at the end of the track, the place "All" stands — the track says
     nothing more than the field here. Both sides are kept in step, each with
     its own equality guard, so the two effects cannot chase each other: the
     hand moving the track makes the field a number, and a field that was
     emptied stays empty while the track still rests at its end. */
  let schichtenRegler = $state(maxSchichten)
  /* Each effect reads only the side it follows and writes the other without
     reading it back: reading both would let the field's effect put the track
     back to where the field stands before the track's effect has told the
     field where the hand left it. */
  $effect(() => {
    const ziel = schichten === null || schichten === undefined ? maxSchichten : schichten
    untrack(() => {
      if (schichtenRegler !== ziel) schichtenRegler = ziel
    })
  })
  $effect(() => {
    const spur = schichtenRegler
    untrack(() => {
      if ((schichten === null || schichten === undefined) && spur === maxSchichten) return
      if (schichten !== spur) schichten = spur
    })
  })

  /* With several slots that do not share the cache, one request gets the
     window divided by their number: the window names that value next to the
     context it shows. */
  const jeAnfrage = $derived(
    parallel > 1 && fein.kv_unified === false && kontext > 0
      ? Math.floor(kontext / parallel)
      : null,
  )

  /* The plan is measured against the limit the system applies to wired
     memory, the one the bar in the page head uses: the limit it reports, else
     its whole memory, else what the page knows of the machine. Read once, and
     only where a plan is shown. */
  let blick = $state(null)
  let blickGefragt = false
  $effect(() => {
    if (!schaetzung || blickGefragt) return
    blickGefragt = true
    api.speicherBlick().then((antwort) => (blick = antwort)).catch(() => {})
  })
  const grenzeGb = $derived(blick?.wired_limit_gb ?? blick?.gesamt_gb ?? maschineGb)

  // How many rows the storage card holds (Serverabschnitt.svelte, `gewicht`).
  const zeigtSchaetzung = $derived(Boolean(schaetzung && grenzeGb))
  // The rows of the advanced card, for the share each column gets.
  const feinZeilen = $derived(
    3 + (kvZeilen ? 3 : 0) + (vorladen !== null ? 1 : 0) + (useForRuns !== null ? 1 : 0)
      + (pooling !== null ? 1 : 0) + (batch !== null ? 1 : 0)
      + (idle !== undefined ? 1 : 0),
  )
  const speicherZeilen = $derived(
    (kontextzeile ? 1 : 0) + 2 + (moe ? 1 : 0) + (zeigtSchaetzung ? 1 : 0),
  )
  /* The planned share of that limit, for the bar in the last row: 0 to 100. */
  const belegt = $derived(
    zeigtSchaetzung ? Math.min(100, Math.max(0, (schaetzung.gesamt / grenzeGb) * 100)) : 0,
  )
</script>

{#if (teil === 'module' || teil === 'alles') && module}
  <Serverabschnitt zeichen="werkzeug" titel={t('modell.gruppe_module')} gewicht={2}>
    <!-- The modules in one card: one choice made twice over — which small
         model helps the big one. -->
    <div class="zeile">
      <svg class="modulzeichen blitzfarbe" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13 3 L5 13.5 H10.5 L9.5 21 L17.5 10.5 H12 Z" /></svg>
      <label class="name" for="{kennung}-drafter">{t('modell.feld_speedmodul')}</label>
      <div class="wahl">
        <Auswahlfeld
          id="{kennung}-drafter"
          bind:wert={drafter}
          eintraege={drafterauswahl}
          {gesperrt}
          beschriftung={t('modell.feld_speedmodul')}
          gewaehlt={drafterGewaehlt}
        />
      </div>
    </div>
    <div class="zeile">
      <svg class="modulzeichen augenfarbe" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 12 C6 6.5, 18 6.5, 21.5 12 C18 17.5, 6 17.5, 2.5 12 Z" /><circle cx="12" cy="12" r="3" /></svg>
      <label class="name" for="{kennung}-vision">{t('modell.feld_vision')}</label>
      <div class="wahl">
        <Auswahlfeld
          id="{kennung}-vision"
          bind:wert={vision}
          eintraege={visionauswahl}
          {gesperrt}
          beschriftung={t('modell.feld_vision')}
          gewaehlt={visionGewaehlt}
        />
      </div>
    </div>
  </Serverabschnitt>
{/if}

{#if teil === 'speicher' || teil === 'alles'}
  <Serverabschnitt zeichen="chip_bolt" titel={t('modell.gruppe_speicher')} gewicht={speicherZeilen}>
    <!-- The numbers that decide what a run costs: name and field, the
         track under them. -->
    {#if kontextzeile}
      <div class="zeile regel">
        <div class="kopfzeile">
          <label class="regelname" for="{kennung}-kontext">{t('modell.feld_kontext')}</label>
          {#if jeAnfrage}
            <span class="jeanfrage">{parallel} × {kurzK(jeAnfrage)}</span>
          {/if}
          <div class="zahlplatz">
            <Zahlenfeld bind:wert={kontext} {gesperrt} min={kontextMin} max={kontextMax} schritt={1024} />
          </div>
        </div>
        <!-- Dragged for the steps everybody needs, typed for the one case that
             is not a step at all: a context above 128k. -->
        <Schieberegler
          id="{kennung}-kontext"
          bind:wert={kontext}
          stufen={kontextstufen}
          {gesperrt}
          beschriftung={t('modell.feld_kontext')}
          anzeige={kurzK}
          mit_zahl={false}
          fuellung
        />
      </div>
    {/if}
    <div class="zeile regel">
      <div class="kopfzeile">
        <label class="regelname" for="{kennung}-schichten">{t('modell.feld_schichten')}</label>
        <div class="zahlplatz">
          <Zahlenfeld bind:wert={schichten} {gesperrt} min={0} max={maxSchichten}
                      ganzzahlig nullwort={t('parameter.auto')} />
        </div>
      </div>
      <Schieberegler
        id="{kennung}-schichten"
        bind:wert={schichtenRegler}
        min={0}
        max={maxSchichten}
        {gesperrt}
        beschriftung={t('modell.feld_schichten')}
        endtext={t('modell.schichten_alle')}
        mit_zahl={false}
        fuellung
      />
    </div>
    <div class="zeile regel">
      <div class="kopfzeile">
        <label class="regelname" for="{kennung}-faeden">{t('modell.feld_faeden')}</label>
        <div class="zahlplatz">
          <Zahlenfeld bind:wert={faeden} {gesperrt} min={0} max={maxFaeden} />
        </div>
      </div>
      <Schieberegler
        id="{kennung}-faeden"
        bind:wert={faeden}
        min={0}
        max={maxFaeden}
        {gesperrt}
        beschriftung={t('modell.feld_faeden')}
        endtext={t('modell.faeden_auto')}
        mit_zahl={false}
        fuellung
      />
    </div>
    {#if moe}
      <div class="zeile regel">
        <div class="kopfzeile">
          <label class="regelname" for="{kennung}-moe">{t('modell.feld_moe')}</label>
          <div class="zahlplatz">
            <Zahlenfeld bind:wert={moeSchichten} {gesperrt} min={0} max={999}
                        nullwort={t('parameter.auto')} />
          </div>
        </div>
        <!-- One number like the three above it: a count above zero, "off"
             for none. -->
        <Schieberegler
          id="{kennung}-moe"
          bind:wert={moeRegler}
          min={0}
          max={999}
          {gesperrt}
          beschriftung={t('modell.feld_moe')}
          endtext={t('modell.schichten_alle')}
          mit_zahl={false}
          fuellung
        />
      </div>
    {/if}
    {#if zeigtSchaetzung}
      <!-- What the start of this server's own model is planned to take of the
           wired memory: the name, a bar and the two numbers. -->
      <div class="zeile wired">
        <span class="wiredname">{t('modell.wired_label')}</span>
        <span class="balken" aria-hidden="true"><i style:width="{belegt}%"></i></span>
        <span class="schaetz">{t('modell.wired_von', { wired: formatGb(schaetzung.gesamt, texte.sprache), total: formatGb(grenzeGb, texte.sprache) })}</span>
      </div>
    {/if}
  </Serverabschnitt>
{/if}

{#if teil === 'netzwerk' || teil === 'alles'}
  <Serverabschnitt zeichen="netzwerk" titel={t('modell.gruppe_netz')} gewicht={1}>
    <div class="zeile">
      <label class="zahlname" for="{kennung}-port">{t('modell.feld_port')}</label>
      <div class="zahlplatz">
        <Zahlenfeld id="{kennung}-port" bind:wert={port} {gesperrt} min={1024} max={65535} />
      </div>
    </div>
  </Serverabschnitt>
{/if}

<!-- Open on start (see `erweitertOffen`); the head folds it away. -->
{#if (teil === 'fein' || teil === 'alles') && erweitert}
  <Serverabschnitt klappbar bind:offen={erweitertOffen} titel={t('modell.gruppe_erweitert')}
                   gewicht={feinZeilen}>
    {#if pooling !== null}
      <div class="zeile niedrig">
        <label class="name" for="{kennung}-pooling">{t('modell.feld_pooling')}</label>
        <div class="wahl schmal">
          <Auswahlfeld id="{kennung}-pooling" bind:wert={pooling} eintraege={poolingauswahl}
                       {gesperrt} beschriftung={t('modell.feld_pooling')} />
        </div>
      </div>
    {/if}
    {#if batch !== null}
      <div class="zeile niedrig">
        <label class="zahlname" for="{kennung}-batch">{t('modell.feld_batch')}</label>
        <div class="zahlplatz">
          <Zahlenfeld id="{kennung}-batch" bind:wert={batch} {gesperrt}
                      min={batchMin} max={Math.max(batchMin, kontext)} schritt={1024} ganzzahlig />
        </div>
      </div>
    {/if}
    {#if kvZeilen}
    <div class="zeile niedrig">
      <label class="name" for="{kennung}-kv">{t('modell.feld_kv')}</label>
      <div class="wahl">
        <Auswahlfeld id="{kennung}-kv" bind:wert={fein.kv_cache} eintraege={kvChoices}
                     {gesperrt} beschriftung={t('modell.feld_kv')} gewaehlt={kvChosen} />
      </div>
    </div>
    <div class="zeile niedrig">
      <label class="name" for="{kennung}-flash">{t('modell.feld_flash')}</label>
      <div class="wahl">
        <Auswahlfeld id="{kennung}-flash" bind:wert={fein.flash_attention} eintraege={flashChoices}
                     {gesperrt} beschriftung={t('modell.feld_flash')} />
      </div>
    </div>
    {/if}
    <div class="zeile niedrig">
      <span class="name">{t('modell.feld_mlock')}</span>
      <Schalter an={fein.festnageln} {gesperrt}
                beschriftung={t('modell.feld_mlock')}
                onschalten={() => (fein.festnageln = !fein.festnageln)} />
    </div>
    {#if vorladen !== null}
      <div class="zeile niedrig">
        <span class="name">{t('modell.laeuft_gerade')}</span>
        <Schalter an={vorladen} {gesperrt}
                  beschriftung={t('modell.laeuft_gerade')}
                  onschalten={(neu) => (vorladen = neu)} />
      </div>
    {/if}
    {#if useForRuns !== null}
      <div class="zeile niedrig">
        <span class="name">{t('modell.fuer_agenten')}</span>
        <Schalter an={useForRuns}
                  beschriftung={t('modell.fuer_agenten')}
                  onschalten={(neu) => onuseforruns?.(neu)} />
      </div>
    {/if}
    <div class="zeile niedrig">
      <label class="zahlname" for="{kennung}-parallel">{t('modell.feld_parallel')}</label>
      <div class="zahlplatz">
        <Zahlenfeld id="{kennung}-parallel" bind:wert={parallel} {gesperrt}
                    min={0} max={maxParallel} ganzzahlig
                    nullwort={t('parameter.auto')} />
      </div>
    </div>
    {#if kvZeilen}
    <div class="zeile niedrig">
      <!-- Shared by default; with the slot count on Auto the engine turns it
           on itself, so the switch stands on and cannot be moved. -->
      <span class="name">{t('modell.feld_kv_unified')}</span>
      <Schalter an={!parallel || fein.kv_unified !== false} gesperrt={gesperrt || !parallel}
                beschriftung={t('modell.feld_kv_unified')}
                onschalten={() => (fein.kv_unified = fein.kv_unified === false)} />
    </div>
    {/if}
    {#if idle !== undefined}
      <div class="zeile niedrig">
        <label class="zahlname" for="{kennung}-idle">{t('modell.feld_idle_ttl')}</label>
        <div class="zahlplatz">
          <Zahlenfeld id="{kennung}-idle" bind:wert={idle} {gesperrt}
                      min={0} max={IDLE_MINUTEN_MAX} ganzzahlig nullwort="-" />
        </div>
      </div>
    {/if}
    <div class="zeile niedrig">
      <label class="zahlname" for="{kennung}-port">{t('modell.feld_port')}</label>
      <div class="zahlplatz">
        <Zahlenfeld id="{kennung}-port" bind:wert={port} {gesperrt} min={1024} max={65535} />
      </div>
    </div>
  </Serverabschnitt>
{/if}

<!-- The servers with nothing else to set under "Advanced": the idle time alone. -->
{#if teil === 'leerlauf' && erweitert}
  <Serverabschnitt klappbar bind:offen={erweitertOffen} titel={t('modell.gruppe_erweitert')} gewicht={1}>
    <div class="zeile niedrig">
      <label class="zahlname" for="{kennung}-idle">{t('modell.feld_idle_ttl')}</label>
      <div class="zahlplatz">
        <Zahlenfeld id="{kennung}-idle" bind:wert={idle} {gesperrt}
                    min={0} max={IDLE_MINUTEN_MAX} ganzzahlig nullwort="-" />
      </div>
    </div>
  </Serverabschnitt>
{/if}

<style>
  /* The rows and their parts (name, slider, field, picker) are
     Serverabschnitt.svelte's; here only what these cards add. */
  /* The module rows: a sign 18 wide, 12 px from its name. */
  .zeile:has(.modulzeichen) {
    gap: 12px;
  }
  .modulzeichen {
    flex: none;
  }
  /* By palette name, like the catalogue tag and the input bar: one
     capability, one colour, in every appearance. */
  .blitzfarbe { color: var(--blau); }
  .augenfarbe { color: var(--violett); }
  /* The wired-memory row (an ordinary row of the card, Serverabschnitt.svelte):
     its name, a bar on a track of the strong line colour and the numbers. */
  div.zeile.wired {
    gap: 14px;
  }
  .wiredname {
    flex: none;
    font: 600 13px/18px var(--schrift);
    color: var(--text);
    white-space: nowrap;
  }
  .balken {
    flex: 1;
    min-width: 0;
    height: 6px;
    border-radius: 3px;
    background: var(--linie-stark);
    overflow: hidden;
  }
  .balken i {
    display: block;
    height: 100%;
    background: var(--gruen);
  }
  /* The pooling picker is 160 wide as drawn; the row's own rule is 232. */
  .wahl.schmal {
    width: 160px;
  }
  .jeanfrage {
    flex: none;
    font-size: 12px;
    line-height: 16px;
    color: var(--text-still);
    white-space: nowrap;
  }
  .schaetz {
    flex: none;
    font-size: 13px;
    line-height: 18px;
    color: var(--text-leise);
    white-space: nowrap;
  }
</style>
