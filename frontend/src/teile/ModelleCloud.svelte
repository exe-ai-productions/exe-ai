<script>
  import { kurz } from '../lib/tokenzahl.js'
  import { untrack } from 'svelte'
  /* Cloud providers: key, catalogue, parameters — the cloud menu of the
     window row (ModelleSeite.svelte keeps its frame).

     The sidebar carries the list of the settings. The page: the head with the
     button for a new provider, and under it two columns — on the left the
     providers, each with the models chosen out of it, and the way to a new
     provider at the foot; on the right the providers as a table, and under it
     two equal columns, the chosen provider's card with the parameters of one
     of its models, and its catalogue. A click on a row of the table or of the
     left column chooses the provider; the sign beside a ticked model of the
     catalogue (or a click on a model of the left column) opens that model's
     parameters.

     A cloud model has ONE state, its tick in the catalogue (modelle.svelte.js
     `istAn`): ticked is on, unticked is off.

     A provider with a catalogue starts EMPTY. OpenAI reports 124 models,
     most of them for speech, images or embeddings; a preselection would be a
     list nobody ordered. */
  import Menueseite from './Menueseite.svelte'
  import Menuezeile from './Menuezeile.svelte'
  import SettingsNav from './SettingsNav.svelte'
  import Schalter from './Schalter.svelte'
  import Zahlenfeld from './Zahlenfeld.svelte'
  import Parametertafel from './Parametertafel.svelte'
  import Ankreuzliste from './Ankreuzliste.svelte'
  import Anbietermaske from './Anbietermaske.svelte'
  import Fenster from './Fenster.svelte'
  import ProviderTable from './ProviderTable.svelte'
  import Serverreihe from './Serverreihe.svelte'
  import Serverabschnitt from './Serverabschnitt.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import Fensterzeichen from './Fensterzeichen.svelte'
  import { LOGOS } from '../lib/logos.js'
  import { t, texte } from '../lib/texte.svelte.js'
  import { api } from '../lib/api.js'
  import { frage, melde, modelleLaden, zustand } from '../lib/zustand.svelte.js'
  import {
    modellwahl, auswahlLaden, istAn, schalten, anbieterAlle, alleAnbieterLaden,
    istGewaehlt, katalogVon, katalogSchalten, katalogAlle,
    isUsedForRuns, setUseForRuns, loadRunApprovals,
  } from '../lib/modelle.svelte.js'

  /* `offen`: this menu is the one showing. The component stays mounted
     while it is not, so the chosen provider or model and a context size
     still being typed survive a look at the local menu or at a chat. */
  let { offen = false } = $props()

  /* What the page shows: a provider, or one of its models (the left column
     sets either). */
  let gezeigt = $state(null)

  /* Which of the two `gezeigt` was set FROM — a provider with a single
     model and no catalogue (homelab, say) has that model's id equal the
     provider's own bare id (app/modellkennung.py), so `gezeigt` alone
     cannot tell the two rows apart once they carry the same value. */
  let gezeigtArt = $state(null)

  /* The model whose parameters stand under the card, set by the sign of a
     catalogue row or by a model of the left column. A model that is not
     one of the shown provider's picked ones falls back to its first. */
  let openModelId = $state(null)

  /* The pop-up that adds a provider. */
  let maskOpen = $state(false)

  const haeuser = $derived(anbieterAlle())
  const gewaehltesHaus = $derived.by(() => {
    if (gezeigt && gezeigtArt === 'modell') {
      const owner = haeuser.find((h) => h.modelle.some((m) => m.id === gezeigt))
      if (owner) return owner
    }
    return haeuser.find((h) => h.id === gezeigt) ?? haeuser[0] ?? null
  })
  const paramsModel = $derived(
    gewaehltesHaus
      ? (gewaehltesHaus.modelle.find((m) => m.id === openModelId) ?? gewaehltesHaus.modelle[0] ?? null)
      : null,
  )
  const katalog = $derived(gewaehltesHaus ? katalogVon(gewaehltesHaus.id) : [])

  /* A provider whose maker has a mark wears it; one without (somebody's own
     server) wears the house sign. */
  const markeVon = (kennung) => (kennung && LOGOS[kennung] ? kennung : '')

  /* A provider that does not answer and is not waiting for its key: it keeps
     its place, with a quiet dot and the words, and shows nothing it has —
     what it has is not known. One with its key missing says that instead. */
  const antwortetNicht = (haus) =>
    !haus.erreichbar && !(haus.schluessel_env && !haus.schluessel_gesetzt)

  /* The context the service found. It stands quietly under the field's name
     — never in the field: the field holds what this window answered, and an
     empty one says the same word as every empty field. */
  const gefundenerKontext = $derived(
    gewaehltesHaus?.kontext && gewaehltesHaus.kontextQuelle !== 'ersatz'
      ? kurz(gewaehltesHaus.kontext, texte.sprache)
      : null,
  )

  /* The cells of the providers table. The words are made here — the table
     only lays them out. A key is a variable's name in the tooltip, never its
     value; "-" stands where a provider has no key or does not answer. */
  const tableRows = $derived(
    haeuser.map((haus) => ({
      id: haus.id,
      name: haus.name,
      logo: markeVon(haus.id) ? LOGOS[haus.id] : null,
      keyState: haus.schluessel_env ? (haus.schluessel_gesetzt ? 'set' : 'missing') : null,
      keyText: haus.schluessel_env
        ? haus.schluessel_gesetzt
          ? t('modell.schluessel_gesetzt')
          : t('modell.schluessel_fehlt')
        : '-',
      keyTitle: haus.schluessel_env
        ? `${haus.schluessel_env}\n${t('modell.schluessel_hinweis')}`
        : '',
      modelsText: haus.erreichbar
        ? t('modell.von_zahl').replace('{gewaehlt}', haus.modelle.length).replace('{gesamt}', haus.katalog)
        : '-',
      stateText: haus.erreichbar
        ? t('status.erreichbar')
        : antwortetNicht(haus)
          ? t('status.not_responding')
          : t('status.nicht_erreichbar'),
      reachable: haus.erreichbar,
      notResponding: antwortetNicht(haus),
      reason: haus.erreichbar ? '' : haus.grund || '',
    })),
  )

  const catalogCount = $derived(
    gewaehltesHaus
      ? t('modell.von_zahl')
          .replace('{gewaehlt}', gewaehltesHaus.modelle.length)
          .replace('{gesamt}', gewaehltesHaus.katalog)
      : '',
  )

  $effect(() => {
    if (!offen) return
    auswahlLaden()
    loadRunApprovals()
  })

  /* The full list — the unreachable providers too — is read when the menu
     opens and again whenever the chat's list was read anew (every add,
     removal or switch ends in such a read), so a provider that went down
     or was just created shows here at once. */
  $effect(() => {
    if (!offen) return
    void zustand.modelle
    alleAnbieterLaden()
  })

  /* The vision word, by hand: a cloud provider's model list says nothing
     about what its models can see, so detection has nothing to detect.
     Whoever knows their model takes images says it here — the entry lands
     in the configuration and the attachment button follows it. */
  async function visionSchalten(haus) {
    try {
      await api.anbieterFaehigkeiten(haus.id, { vision: !haus.vision })
      await modelleLaden()
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }

  /* The thinking word, by hand, for the same reason as vision above: an MLX
     server has no /props to sniff, so nothing detects it. Without the word
     the capability stays "no" and the thinking button in the chat does
     nothing at all — a control that lies. */
  async function denkenSchalten(haus) {
    try {
      await api.anbieterFaehigkeiten(haus.id, { thinking: !haus.denken })
      await modelleLaden()
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }

  /* The tool word, by hand, and the one with teeth: while it is off the
     request carries no tools at all, so the model is never offered any.
     One that knows the format anyway writes the call from memory — and
     without the template's instruction it writes it broken, which arrives
     as plain text in the chat. Measured against an MLX server: with the
     word set the very same model answers with structured tool calls. */
  async function werkzeugeSchalten(haus) {
    try {
      await api.anbieterFaehigkeiten(haus.id, { tool_calls: !haus.werkzeuge })
      await modelleLaden()
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }

  /* The "Zeitgrenze" switch: on, a model call is cut off after 600 s of
     silence, same as it always was. A server this window's own
     user trusts to eventually answer — however long a quiet stretch takes —
     is switched off for, since `group` alone calls it "cloud" whether or
     not that trust is there. */
  async function zeitgrenzeSchalten(haus) {
    try {
      await api.anbieterZeitgrenze(haus.id, !haus.zeitgrenze)
      await modelleLaden()
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }

  /* The context window, said by hand for the providers that never name one.
     A local server answers it itself and Anthropic's model list carries it,
     so this field is only ever the last resort — and it was the one number
     that lived in the configuration with no way to reach it from here.

     Held in its own state rather than bound straight to the provider row:
     the row is rebuilt from the service on every reload, and typing into a
     value that keeps being replaced under the cursor is unusable. */
  let kontextEingabe = $state(null)
  let kontextFuer = null
  let kontextZeit

  $effect(() => {
    const haus = gewaehltesHaus
    if (!haus || haus.id === kontextFuer) return
    kontextFuer = haus.id
    // The OWN value only. Filled from whichever number is in force,
    // the field turned a measured size into a stored choice the
    // moment anything else on the page was saved.
    kontextEingabe = haus.kontextEigen ?? null
  })

  /* Saved on change, not on a button: the three switches above save the
     moment they are flipped, and one control in the same column that needs
     a second click would be the odd one out. Delayed, so typing a five-digit
     number is one save and not five. */
  $effect(() => {
    const wert = kontextEingabe
    const haus = untrack(() => gewaehltesHaus)
    if (!haus || haus.id !== kontextFuer) return
    if ((untrack(() => haus.kontextEigen) ?? null) === wert) return
    clearTimeout(kontextZeit)
    kontextZeit = setTimeout(() => kontextSichern(haus.id, wert), 450)
    return () => clearTimeout(kontextZeit)
  })

  async function kontextSichern(kennung, wert) {
    try {
      await api.anbieterKontext(kennung, wert || null)
      await modelleLaden()
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }

  /* Removes a provider — the way out of the mistake that had none. Its key
     line leaves the .env with it, unless another provider reads the same
     variable; the question says which of the two happens. */
  async function anbieterEntfernen(haus) {
    const frageSchluessel = haus.key_goes_with_provider
      ? 'modell.anbieter_loeschen_frage_mit_schluessel'
      : 'modell.anbieter_loeschen_frage'
    const ja = await frage(t(frageSchluessel, { name: haus.name }), {
      okSchluessel: 'modell.anbieter_entfernen',
      danger: true,
    })
    if (!ja) return
    try {
      await api.anbieterLoeschen(haus.id)
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
      return
    }
    // The removal already happened — a failed refresh below is its own
    // problem and must not read as "the provider is still there".
    if (gezeigt === haus.id) {
      gezeigt = null
      gezeigtArt = null
    }
    melde(t('modell.anbieter_entfernt'), 'erfolg')
    try {
      await modelleLaden(true)
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    }
  }
</script>

{#snippet card(haus)}
  <!-- The provider's card: who it is and whether it answers, then what its
       models can do, set by hand — the provider's list does not say whether a
       model sees images, uses tools or thinks. What each switch does stands as
       the title of its sign. -->
  <Serverabschnitt>
    <div class="zeile provider-head">
      <span class="logo-30" aria-hidden="true">
        {#if markeVon(haus.id)}
          <svg viewBox={LOGOS[haus.id].vb} width="30" height="30">{@html LOGOS[haus.id].html}</svg>
        {:else}
          <Hauszeichen zeichen="server" groesse={28} />
        {/if}
      </span>
      <span class="provider-name">{haus.name}</span>
      <span class="state-word" class:reachable={haus.erreichbar} class:not-responding={antwortetNicht(haus)}>
        {#if antwortetNicht(haus)}
          <Leuchtpunkt farbe="still" groesse={7} />
          {t('status.not_responding')}
        {:else}
          {haus.erreichbar ? t('status.erreichbar') : t('status.nicht_erreichbar')}
        {/if}
      </span>
    </div>
    {#if !haus.erreichbar && haus.grund}
      <!-- The provider's own sentence about refusing, whole and wrapping. -->
      <div class="zeile reason-row">
        <p class="reason">{haus.grund}</p>
      </div>
    {/if}
    <div class="zeile niedrig">
      <span class="label-block">
        <span class="label">{t('modell.vision_schalter')}</span>
        <span class="info" role="img" aria-label={t('modell.vision_erklaerung')} title={t('modell.vision_erklaerung')}>
          <Hauszeichen zeichen="info" groesse={14} />
        </span>
      </span>
      <Schalter
        an={haus.vision}
        label={t('modell.vision_schalter')}
        onschalten={() => visionSchalten(haus)}
      />
    </div>
    <div class="zeile niedrig">
      <span class="label-block">
        <span class="label">{t('modell.werkzeuge_schalter')}</span>
        <span class="info" role="img" aria-label={t('modell.werkzeuge_erklaerung')} title={t('modell.werkzeuge_erklaerung')}>
          <Hauszeichen zeichen="info" groesse={14} />
        </span>
      </span>
      <Schalter
        an={haus.werkzeuge}
        label={t('modell.werkzeuge_schalter')}
        onschalten={() => werkzeugeSchalten(haus)}
      />
    </div>
    <div class="zeile niedrig">
      <span class="label-block">
        <span class="label">{t('modell.denken_schalter')}</span>
        <span class="info" role="img" aria-label={t('modell.denken_erklaerung')} title={t('modell.denken_erklaerung')}>
          <Hauszeichen zeichen="info" groesse={14} />
        </span>
      </span>
      <Schalter
        an={haus.denken}
        label={t('modell.denken_schalter')}
        onschalten={() => denkenSchalten(haus)}
      />
    </div>
    <div class="zeile niedrig">
      <span class="label-block">
        <span class="label">{t('modell.zeitgrenze_schalter')}</span>
      </span>
      <Schalter
        an={haus.zeitgrenze}
        label={t('modell.zeitgrenze_schalter')}
        onschalten={() => zeitgrenzeSchalten(haus)}
      />
    </div>
    <!-- The one number that is not a capability: how much this provider can
         take in. Empty means what it always meant — ask the server; what it
         said stands quietly under the name. -->
    <div class="zeile" title={t('modell.kontext_titel')}>
      <span class="label-block stacked-name">
        <span class="label">{t('modell.kontext_feld')}</span>
        {#if !kontextEingabe && gefundenerKontext}
          <span class="subline">{t('modell.kontext_gefunden', { zahl: gefundenerKontext })}</span>
        {/if}
      </span>
      <div class="zahlplatz">
        <Zahlenfeld
          bind:wert={kontextEingabe}
          min={0}
          max={10000000}
          schritt={1024}
          ganzzahlig
          nullwort={t('parameter.auto')}
        />
      </div>
    </div>
  </Serverabschnitt>
{/snippet}

{#snippet singleModels(haus)}
  <!-- A provider whose models have no catalogue to tick in (a single model):
       one row for each, the model's name, the sign for its parameters and the
       tick — the tick away takes the model out of the model choice and leaves
       the provider where it is. -->
  <Serverabschnitt>
    {#each haus.modelle as m (m.id)}
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <div
        class="zeile model-row"
        class:open={m.id === paramsModel?.id}
        role="button"
        tabindex="0"
        aria-pressed={istAn(m.id)}
        onclick={() => schalten(m.id, !istAn(m.id))}
        onkeydown={(e) => {
          if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault()
            schalten(m.id, !istAn(m.id))
          }
        }}
      >
        <span class="model-name">{m.name}</span>
        {#if istAn(m.id)}
          <button
            class="sign-button"
            aria-label={t('parameter.titel')}
            title={t('parameter.titel')}
            onclick={(e) => { e.stopPropagation(); openModelId = m.id }}
            onkeydown={(e) => e.stopPropagation()}
          >
            <Hauszeichen zeichen="settings_two" groesse={16} />
          </button>
          <span class="end-tick" aria-hidden="true">
            <Hauszeichen zeichen="haken" groesse="klein" strich={2.4} />
          </span>
        {/if}
      </div>
    {/each}
  </Serverabschnitt>
{/snippet}

{#snippet paramsBlock()}
  {#if paramsModel}
    <!-- Whether a run the program places itself may be sent to this model
         when none of the two local servers can take it. Nothing is on until
         it is ticked here. -->
    <Serverabschnitt>
      <div class="zeile niedrig">
        <span class="name">{t('modell.fuer_agenten')}</span>
        <Schalter
          an={isUsedForRuns(paramsModel.id)}
          beschriftung={t('modell.fuer_agenten')}
          onschalten={(neu) => setUseForRuns(paramsModel.id, neu)}
        />
      </div>
    </Serverabschnitt>
    <Parametertafel modell={paramsModel} withName />
  {/if}
{/snippet}

{#snippet catalogCard(haus)}
  <Serverabschnitt gewicht={1}>
    <!-- The head is the card's first row: the name, its figure, a hairline
         under it. It keeps its height when the card grows. -->
    <div class="zeile duenn catalog-head">
      <span class="catalog-title">{t('liste.katalog')}</span>
      <span class="catalog-count">{catalogCount}</span>
    </div>
    <div class="zeile stapel katalog">
      <Ankreuzliste
        eintraege={katalog}
        istAn={istGewaehlt}
        istFest={(m) => m.angeheftet}
        onschalten={katalogSchalten}
        onalle={(alle) => katalogAlle(haus.id, alle)}
        tickEnd
        isOpen={(m) => m.id === paramsModel?.id}
      >
        {#snippet rowAction(m)}
          <button
            class="sign-button"
            aria-label={t('parameter.titel')}
            title={t('parameter.titel')}
            onclick={() => (openModelId = m.id)}
          >
            <Hauszeichen zeichen="settings_two" groesse={15} />
          </button>
        {/snippet}
      </Ankreuzliste>
    </div>
  </Serverabschnitt>
{/snippet}

{#snippet providers()}
  <!-- The left column: the heading over its card, as the table on the right
       has its own, so the two headings and the two cards each stand on one
       line. In the card: each provider as a menu row — its maker's sign in
       front, the house's server sign for one without a logo — and, while it
       answers, how many of its models are chosen out of how many it offers; a
       missing key says so in the same place. Under an answering provider
       stand its chosen models. One that does not answer stands alone: what it
       has is not known. -->
  <div class="links">
  <h3 class="tafelkopf">{t('modell.einrichten')}</h3>
  <nav class="providers" aria-label={t('modell.einrichten')}>
    {#each haeuser as haus (haus.id)}
      <Menuezeile
        titel={haus.name}
        size="list"
        nameGivesWay
        gewaehlt={haus.id === gewaehltesHaus?.id}
        onclick={() => { gezeigt = haus.id; gezeigtArt = 'haus' }}
      >
        {#snippet zeichen()}
          {#if markeVon(haus.id)}
            <svg viewBox={LOGOS[haus.id].vb} width="18" height="18" aria-hidden="true">{@html LOGOS[haus.id].html}</svg>
          {:else}
            <Hauszeichen zeichen="server" groesse={18} />
          {/if}
        {/snippet}
        {#snippet rechts()}
          {#if haus.schluessel_env && !haus.schluessel_gesetzt}
            <span class="count missing">{t('modell.schluessel_fehlt')}</span>
          {:else if antwortetNicht(haus)}
            <span class="count not-responding">
              <Leuchtpunkt farbe="still" groesse={7} />
              {t('status.not_responding')}
            </span>
          {:else if haus.erreichbar}
            <span class="count">
              {t('modell.von_zahl').replace('{gewaehlt}', haus.modelle.length).replace('{gesamt}', haus.katalog)}
            </span>
          {/if}
        {/snippet}
      </Menuezeile>

      {#if haus.erreichbar}
        {#each haus.modelle as m (m.id)}
          <div
            class="listenzeile"
            class:gewaehlt={m.id === paramsModel?.id}
            class:aus={!istAn(m.id)}
            role="button"
            tabindex="0"
            aria-current={m.id === paramsModel?.id ? 'true' : undefined}
            onclick={() => { gezeigt = m.id; gezeigtArt = 'modell'; openModelId = m.id }}
            onkeydown={(e) => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); gezeigt = m.id; gezeigtArt = 'modell'; openModelId = m.id } }}
          >
            <div class="wer"><div class="mname">{m.name}</div></div>
            <!-- Chosen or not, as a list says it: a tick on the chosen
                 ones, an empty place on the others; a click on it turns
                 the model on or off, a click on the row opens its page. -->
            <button
              class="haken"
              class:an={istAn(m.id)}
              aria-pressed={istAn(m.id)}
              aria-label={m.name}
              onclick={(e) => { e.stopPropagation(); schalten(m.id, !istAn(m.id)) }}
              onkeydown={(e) => e.stopPropagation()}
            >
              <Hauszeichen zeichen="haken" groesse={14} strich={2.4} />
            </button>
          </div>
        {/each}
      {/if}
    {:else}
      <p class="leer">{t('modell.kein_anbieter_kurz')}</p>
    {/each}

    {#if haeuser.length}
      <!-- At the foot of the column, where a new entry would land. -->
      <div
        class="listenzeile dazu"
        class:gewaehlt={maskOpen}
        role="button"
        tabindex="0"
        onclick={() => (maskOpen = true)}
        onkeydown={(e) => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); maskOpen = true } }}
      >
        <span class="plus" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2.5" stroke-linecap="round"><path d="M12 5 V19 M5 12 H19" /></svg>
        </span>
        <div class="wer"><div class="mname">{t('modell.anbieter_hinzufuegen')}</div></div>
      </div>
    {/if}
  </nav>
  </div>
{/snippet}

{#snippet rightSide()}
  {#if gewaehltesHaus}
    {@const haus = gewaehltesHaus}
    <ProviderTable
      rows={tableRows}
      chosen={haus.id}
      onchoose={(id) => { gezeigt = id; gezeigtArt = 'haus' }}
      onremove={(id) => {
        const owner = haeuser.find((h) => h.id === id)
        if (owner) anbieterEntfernen(owner)
      }}
    />

    <!-- Two equal columns where the provider has a catalogue: its card
         with the parameters on the left, the catalogue on the right.
         Without one the card, its models and the parameters stand alone,
         and no empty column is left beside them. -->
    {#if katalog.length}
      <Serverreihe>
        {#snippet links()}
          {@render card(haus)}
          {@render paramsBlock()}
        {/snippet}
        {#snippet rechts()}
          {@render catalogCard(haus)}
        {/snippet}
      </Serverreihe>
    {:else}
      <div class="single-column">
        {@render card(haus)}
        {#if haus.erreichbar && haus.modelle.length}
          {@render singleModels(haus)}
        {/if}
        {@render paramsBlock()}
      </div>
    {/if}
  {:else}
    <!-- The empty half offers the way instead of repeating the notice
         that already stands on the left. A dashed edge says the same
         as the empty memory steps: nothing here yet, but something can
         go here. -->
    <button class="leerkachel" onclick={() => (maskOpen = true)}>
      <span class="kreuz">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2.2" stroke-linecap="round"><path d="M12 5 V19 M5 12 H19" /></svg>
      </span>
      <b>{t('modell.anbieter_hinzufuegen')}</b>
    </button>
  {/if}
{/snippet}

{#if offen}
  <Menueseite label={t('menue.cloud')}>
    {#snippet liste()}
      <SettingsNav current="cloud" />
    {/snippet}

    {#snippet kopf()}
      <!-- The page head: what this tab is, and the way to a new provider at
           its far end. No server of ours runs here, so no start button. -->
      <div class="titelblock">
        <div class="markenzeile">
          <span class="kasten"><Fensterzeichen name="cloud" groesse={22} /></span>
          <h2 class="titel">{t('modell.cloud_titel')}</h2>
        </div>
      </div>
      <button class="new-button" onclick={() => (maskOpen = true)}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
        {t('modell.anbieter_hinzufuegen')}
      </button>
    {/snippet}

    {#snippet inhalt()}
      <div class="two-columns">
        {@render providers()}
        <div class="right">
          {@render rightSide()}
        </div>
      </div>
    {/snippet}
  </Menueseite>

  <Fenster art="provider" bind:offen={maskOpen} titel={t('modell.anbieter_hinzufuegen')}>
    <Anbietermaske fertig={() => (maskOpen = false)} />
  </Fenster>
{/if}

<style>
  /* Two columns in the page: the providers at 300 px on the left, what the
     chosen provider holds on the right. Both are as high as the taller of
     the two. */
  .two-columns {
    display: grid;
    grid-template-columns: 300px minmax(0, 1fr);
    gap: 24px;
    align-items: stretch;
  }
  /* The heading over its card, the gap the table on the right keeps too
     (ProviderTable.svelte); the card takes what is left of the column. */
  .links {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .links .tafelkopf {
    margin: 0;
  }
  .providers {
    flex: 1;
    padding: 6px 10px;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .right { min-width: 0; container-type: inline-size; }
  /* The page keeps less room than the window: the card and the catalogue
     stand over each other as soon as the room beside the column is short. */
  @container (max-width: 640px) {
    .right :global(.reihe) { grid-template-columns: minmax(0, 1fr); }
  }
  /* Narrow window: the providers stand over the page instead of beside it. */
  @media (max-width: 900px) {
    .two-columns { grid-template-columns: minmax(0, 1fr); gap: 16px; }
  }

  /* The count of a provider's chosen models stands where a menu row keeps
     its value, whole — the name gives way — and a missing key says so in the
     same place, in red. */
  .count {
    flex: none;
    margin-left: auto;
    font-size: 11px;
    color: var(--text-still);
    white-space: nowrap;
  }
  .count.missing { color: var(--rot-text); }
  /* A provider that does not answer: a quiet dot and the words, as the row of
     the drawing has them. */
  .count.not-responding {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    color: var(--text-leise);
  }

  /* The way to a new provider stands like a model row: its plus where the
     models wear their tick. */
  .listenzeile.dazu {
    min-height: 40px;
    padding: 0 10px;
    gap: 12px;
    color: var(--text-leise);
  }
  .listenzeile.dazu .mname { font: 500 13px var(--schrift); }
  .plus { display: inline-flex; justify-content: center; width: 18px; flex: none; color: var(--text-leise); }
  /* The tile stands in for the empty content — a dashed edge says nothing
     is here yet, but something can go here. */
  .leerkachel {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 11px;
    width: 100%; min-height: 240px;
    border: 1px dashed var(--linie-stark); border-radius: 9px;
    background: none; color: var(--text-leise); font: inherit;
    padding: 24px 20px; cursor: pointer;
    transition: border-color 0.12s, color 0.12s, background 0.12s;
  }
  .leerkachel:hover { border-color: var(--text); color: var(--text); background: var(--blase); }
  .leerkachel b { font-size: 14px; font-weight: 600; }
  .kreuz {
    width: 34px; height: 34px; border-radius: 99px;
    border: 1px solid currentColor; display: grid; place-items: center;
  }

  /* The model rows of the left column: quiet at rest, a lighter ground under
     the hand, the button glass when chosen (the column itself is card glass). */
  .listenzeile {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 32px;
    box-sizing: border-box;
    /* The model's name starts under its provider's name: the row's 10, the
       sign's 18 and the 12 between them (Menuezeile.svelte). */
    padding: 5px 10px 5px 40px;
    border-radius: 9px;
    cursor: pointer;
    transition: background 0.12s;
  }
  .listenzeile:hover { background: color-mix(in srgb, var(--text) 4%, transparent); }
  .listenzeile.gewaehlt {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
  }
  .wer { flex: 1; min-width: 0; }
  .mname {
    font-size: var(--schrift-hinweis);
    font-family: var(--schrift-fest);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .listenzeile.aus .mname { opacity: 0.42; }
  .haken {
    flex: none;
    width: 22px;
    height: 22px;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--gruen);
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.12s, background 0.12s;
  }
  .haken.an { opacity: 1; }
  .listenzeile:hover .haken:not(.an) { opacity: 0.3; }
  /* Without a hover the empty tick stands as quiet as it does under the
     pointer. */
  @media (hover: none), (any-pointer: coarse) {
    .haken:not(.an) { opacity: 0.3; }
  }
  .haken:hover { background: color-mix(in srgb, var(--text) 6%, transparent); }
  .haken:focus-visible { opacity: 1; outline: 2px solid var(--linie-stark); outline-offset: -2px; }

  /* The page head: the cloud sign in a 40 px box of card glass, the title,
     and the button for a new provider at the far end. */
  .titelblock {
    flex: 1 1 260px;
    min-width: 0;
  }
  .markenzeile {
    display: flex;
    align-items: center;
    gap: 14px;
    color: var(--text);
  }
  .kasten {
    width: 40px;
    height: 40px;
    flex: none;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 9px;
    /* The glass of a button with its fine line, drawn inside the box. */
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  .titel {
    margin: 0;
    font-size: var(--schrift-seitentitel);
    font-weight: 400;
    line-height: 1.3;
    color: var(--text);
  }
  .new-button {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    height: 36px;
    padding: 0 18px;
    border: none;
    border-radius: 9px;
    /* A main button, so button glass with its fine edge; only Send is filled. */
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: 500 13px var(--schrift);
    cursor: pointer;
    transition: background 0.12s;
  }
  .new-button:hover {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
  }

  /* Without a catalogue the parts stand one under the other. */
  .single-column {
    display: flex;
    flex-direction: column;
    gap: 28px;
  }

  /* The card's head row: the logo alone, the name, the state as a word right
     behind it. */
  .right .provider-head.zeile { gap: 12px; }
  .logo-30 {
    flex: none;
    width: 30px;
    height: 30px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--text);
  }
  .provider-name {
    flex: 0 1 auto;
    min-width: 0;
    font-size: 17px;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .state-word {
    flex: none;
    font-size: 12px;
    font-weight: 500;
    color: var(--text-still);
  }
  .state-word.reachable { color: var(--gruen-text); }
  /* What the provider said about refusing: its sentence, in the hint size
     and the quiet ink, as long as it is. */
  .reason {
    margin: 0;
    min-width: 0;
    font-size: var(--schrift-hinweis);
    color: var(--text-leise);
    white-space: normal;
    overflow-wrap: anywhere;
  }
  .state-word.not-responding {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    font-weight: 400;
    color: var(--text-leise);
  }

  /* A switch row: its name, the sign that explains it, then the switch at
     the far end of the row (the row is a flex row; the name takes the room). */
  .label-block {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  /* Nothing is cut off: where the card is narrow the name takes a second
     line. */
  .label {
    font-size: 13px;
    font-weight: 600;
    line-height: 18px;
    color: var(--text);
    overflow-wrap: anywhere;
  }
  .info {
    flex: none;
    display: inline-flex;
    color: var(--text-still);
    cursor: help;
  }
  /* The number's name with its quiet line under it. */
  .stacked-name {
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
  }
  .subline {
    font-size: 12px;
    color: var(--text-leise);
    opacity: 0.6;
    white-space: nowrap;
  }

  /* The rows of a provider whose model has no catalogue: a name at the left,
     the parameters' sign and the tick at the right end; the row of the model
     whose parameters stand open is on a lighter ground. */
  .model-row { min-height: 48px; padding-top: 8px; padding-bottom: 8px; gap: 12px; border-radius: 9px; cursor: pointer; outline: none; }
  .model-row:hover { background: var(--glass-hover); }
  .model-row:focus-visible { box-shadow: inset 0 0 0 2px var(--linie-stark); }
  .model-row.open { background: var(--glass-button); }
  .model-name {
    flex: 1;
    min-width: 0;
    font-size: 13px;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .end-tick { flex: none; display: inline-flex; width: 22px; justify-content: center; color: var(--text); }
  .sign-button {
    flex: none;
    width: 28px;
    height: 28px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }
  .sign-button:hover { background: var(--glass-hover); color: var(--text); }
  .sign-button:focus-visible { outline: 2px solid var(--linie-stark); outline-offset: -2px; }

  .right .catalog-head.zeile.duenn {
    min-height: 56px;
    padding: 10px 16px;
    gap: 10px;
  }
  /* The catalogue's row stands without an inset of its own: the search, the
     entries and the foot are rows of the card, edge to edge. */
  .right .katalog.zeile.stapel {
    padding: 0;
    gap: 0;
  }
  .catalog-title { font-size: 15px; font-weight: 600; color: var(--text); }
  .catalog-count {
    font-size: 12px;
    color: var(--text-leise);
    font-variant-numeric: tabular-nums;
  }
  /* The catalogue brings its own search field and list; its list takes the
     height the card is given (the list rolls in itself, the foot stays at
     the bottom). */
  .katalog :global(.listenkarte) {
    flex: 1 1 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .katalog :global(.liste) {
    flex: 1 1 0;
    min-height: 200px;
    max-height: none;
  }

  .leer { color: var(--text-still); font-size: 13px; padding: 6px 10px; }
</style>
