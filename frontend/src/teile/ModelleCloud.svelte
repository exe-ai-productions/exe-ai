<script>
  import { kurz } from '../lib/tokenzahl.js'
  import { untrack } from 'svelte'
  /* Cloud providers: key, catalogue, parameters — the cloud menu of the
     window row (ModelleSeite.svelte keeps its frame).

     One rule holds this menu and the local one together: the sections
     stand in the sidebar while the menu is open (Menueseite hands them
     over), and the page shows whatever is selected there. What appears
     depends only on WHAT was clicked — a provider brings its key and its
     catalogue, a model brings its parameters.

     A provider with a catalogue starts EMPTY. OpenAI reports 124 models,
     most of them for speech, images or embeddings; a preselection would be a
     list nobody ordered. */
  import Menueseite from './Menueseite.svelte'
  import Menuezeile from './Menuezeile.svelte'
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import Schalter from './Schalter.svelte'
  import Zahlenfeld from './Zahlenfeld.svelte'
  import Parametertafel from './Parametertafel.svelte'
  import Ankreuzliste from './Ankreuzliste.svelte'
  import Anbietermaske from './Anbietermaske.svelte'
  import Fensterkopf from './Fensterkopf.svelte'
  import Fenstertafel from './Fenstertafel.svelte'
  import Serverabschnitt from './Serverabschnitt.svelte'
  import Knopfreihe from './Knopfreihe.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Fensterzeichen from './Fensterzeichen.svelte'
  import { LOGOS } from '../lib/logos.js'
  import { t } from '../lib/texte.svelte.js'
  import { api } from '../lib/api.js'
  import { frage, melde, modelleLaden } from '../lib/zustand.svelte.js'
  import {
    modellwahl, auswahlLaden, istAn, schalten, anbieter,
    istGewaehlt, katalogVon, katalogSchalten, katalogAlle,
  } from '../lib/modelle.svelte.js'

  /* `offen`: this menu is the one showing. The component stays mounted
     while it is not, so the chosen provider or model and a context size
     still being typed survive a look at the local menu or at a chat. */
  let { offen = false } = $props()

  /* What the right half shows: either a provider or one of its models. */
  let gezeigt = $state(null)

  /* Which of the two `gezeigt` was set FROM — a provider with a single
     model and no catalogue (homelab, say) has that model's id equal the
     provider's own bare id (app/modellkennung.py), so `gezeigt` alone
     cannot tell the two rows apart once they carry the same value. Without
     this the provider row's own capabilities panel (vision, tool_calls,
     thinking, context, Zeitgrenze) was unreachable for exactly such a
     provider — `gewaehltesModell` always won and showed the parameter
     panel instead, whichever of the two rows was clicked. */
  let gezeigtArt = $state(null)

  /* Not a provider id and never colliding with one — an id is a name
     from the configuration, this is a word of ours. */
  const HINZU = 'hinzufuegen'

  const haeuser = $derived(anbieter())
  const gewaehltesHaus = $derived(
    haeuser.find((h) => h.id === gezeigt) ?? (gezeigt ? null : haeuser[0] ?? null),
  )
  const gewaehltesModell = $derived(
    gezeigt && gezeigtArt !== 'haus'
      ? haeuser.flatMap((h) => h.modelle).find((m) => m.id === gezeigt) ?? null
      : null,
  )
  const katalog = $derived(gewaehltesHaus ? katalogVon(gewaehltesHaus.id) : [])

  /* A provider whose maker has a mark wears it on its tile; one without
     (somebody's own server) wears the house sign. */
  const markeVon = (kennung) => (kennung && LOGOS[kennung] ? kennung : '')

  /* The context the service found. It stands in the row, quiet, left of the
     field — never in the field: the field holds what this window answered,
     and an empty one says the same word as every empty field. */
  const gefundenerKontext = $derived(
    gewaehltesHaus?.kontext && gewaehltesHaus.kontextQuelle !== 'ersatz'
      ? kurz(gewaehltesHaus.kontext)
      : null,
  )

  $effect(() => {
    if (!offen) return
    auswahlLaden()
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

{#if offen}
  <Menueseite beschriftung={t('menue.cloud')}>
    {#snippet liste()}
      <!-- The same heading the local servers' list opens with. -->
      <div class="menuegruppe">{t('modell.einrichten')}</div>
      <div class="liste">
        {#each haeuser as haus (haus.id)}
          <!-- A provider as a menu row: its maker's sign in front — the
               house's server sign for one without a logo — and, while it
               answers, how many of its models are chosen out of how many it
               offers. A missing key says so in the same place. -->
          <Menuezeile
            titel={haus.name}
            wert={haus.schluessel_env && !haus.schluessel_gesetzt
              ? t('modell.schluessel_fehlt')
              : haus.erreichbar
                ? t('modell.von_zahl')
                    .replace('{gewaehlt}', haus.modelle.length)
                    .replace('{gesamt}', haus.katalog)
                : ''}
            gewaehlt={haus.id === gewaehltesHaus?.id && !gewaehltesModell}
            onclick={() => { gezeigt = haus.id; gezeigtArt = 'haus' }}
          >
            {#snippet zeichen()}
              {#if markeVon(haus.id)}
                <svg viewBox={LOGOS[haus.id].vb} width="22" height="22" aria-hidden="true">{@html LOGOS[haus.id].html}</svg>
              {:else}
                <Hauszeichen zeichen="server" groesse="gross" />
              {/if}
            {/snippet}
          </Menuezeile>

          {#each haus.modelle as m (m.id)}
            <div
              class="listenzeile"
              class:gewaehlt={m.id === gewaehltesModell?.id}
              class:aus={!istAn(m.id)}
              role="button"
              tabindex="0"
              onclick={() => { gezeigt = m.id; gezeigtArt = 'modell' }}
              onkeydown={(e) => { if (e.key === 'Enter') { gezeigt = m.id; gezeigtArt = 'modell' } }}
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
                <Hauszeichen zeichen="haken" groesse="klein" strich={2.4} />
              </button>
            </div>
          {/each}
        {:else}
          <p class="leer">{t('modell.kein_anbieter_kurz')}</p>
        {/each}

        {#if haeuser.length}
          <!-- At the foot of the list, where a new entry would land. -->
          <div
            class="listenzeile dazu"
            class:gewaehlt={gezeigt === HINZU}
            role="button"
            tabindex="0"
            onclick={() => (gezeigt = HINZU)}
            onkeydown={(e) => { if (e.key === 'Enter') gezeigt = HINZU }}
          >
            <span class="plus" aria-hidden="true">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   stroke-width="2.5" stroke-linecap="round"><path d="M12 5 V19 M5 12 H19" /></svg>
            </span>
            <div class="wer"><div class="mname">{t('modell.anbieter_hinzufuegen')}</div></div>
          </div>
        {/if}
      </div>
    {/snippet}

    {#snippet kopf()}
      <!-- The page head: what this tab is, on the same line as the local
           tab's. No server of ours runs here, so no start button. -->
      <div class="titelblock">
        <div class="markenzeile">
          <Fensterzeichen name="cloud" groesse={36} />
          <h2 class="titel">{t('modell.cloud_titel')}</h2>
        </div>
      </div>
    {/snippet}

    {#snippet inhalt()}
      {#if gewaehltesModell}
        <Fenstertafel>
          <Fensterkopf
            zeichen="paket"
            marke={markeVon(gewaehltesModell.anbieter)}
            titel={gewaehltesModell.name}
            standfarbe={gewaehltesModell.erreichbar ? 'gruen' : 'still'}
            standtext={gewaehltesModell.erreichbar
              ? t('status.erreichbar')
              : t('status.nicht_erreichbar')}
          />
          <Parametertafel modell={gewaehltesModell} />
        </Fenstertafel>
      {:else if gewaehltesHaus}
        {@const haus = gewaehltesHaus}
        <Fenstertafel>
          <Fensterkopf
            zeichen="server"
            marke={markeVon(haus.id)}
            titel={haus.name}
            standfarbe={haus.erreichbar ? 'gruen' : 'still'}
            standtext={haus.erreichbar ? t('status.erreichbar') : t('status.nicht_erreichbar')}
          />

          {#if haus.schluessel_env}
            <!-- The name of the variable, never the key itself: the
                 interface has no login, so no secret is ever shown here.
                 Red, like in the connections gallery: a missing key does not
                 resolve by waiting, somebody has to put it in the .env. -->
            <Serverabschnitt zeichen="schluessel" titel={t('modell.schluessel')}>
              <div class="zeile" title={t('modell.schluessel_hinweis')}>
                <code class="name schluesselname">{haus.schluessel_env}</code>
                <span class="stand" class:fehlt={!haus.schluessel_gesetzt}>
                  <Leuchtpunkt farbe={haus.schluessel_gesetzt ? 'gruen' : 'rot'} groesse={11} />
                  {haus.schluessel_gesetzt
                    ? t('modell.schluessel_gesetzt')
                    : t('modell.schluessel_fehlt')}
                </span>
              </div>
            </Serverabschnitt>
          {/if}

          <!-- Set by hand, not guessed: the provider's list does not say
               whether a model sees images, uses tools or thinks. What each
               switch does rides on the row as its title, not as a line
               under it. -->
          <Serverabschnitt zeichen="werkzeug" titel={t('modell.faehigkeiten')}>
            <div class="zeile niedrig" title={t('modell.vision_erklaerung')}>
              <span class="name">{t('modell.vision_schalter')}</span>
              <Schalter
                an={haus.vision}
                beschriftung={t('modell.vision_schalter')}
                onschalten={() => visionSchalten(haus)}
              />
            </div>
            <div class="zeile niedrig" title={t('modell.werkzeuge_erklaerung')}>
              <span class="name">{t('modell.werkzeuge_schalter')}</span>
              <Schalter
                an={haus.werkzeuge}
                beschriftung={t('modell.werkzeuge_schalter')}
                onschalten={() => werkzeugeSchalten(haus)}
              />
            </div>
            <div class="zeile niedrig" title={t('modell.denken_erklaerung')}>
              <span class="name">{t('modell.denken_schalter')}</span>
              <Schalter
                an={haus.denken}
                beschriftung={t('modell.denken_schalter')}
                onschalten={() => denkenSchalten(haus)}
              />
            </div>
            <div class="zeile niedrig">
              <span class="name">{t('modell.zeitgrenze_schalter')}</span>
              <Schalter
                an={haus.zeitgrenze}
                beschriftung={t('modell.zeitgrenze_schalter')}
                onschalten={() => zeitgrenzeSchalten(haus)}
              />
            </div>
            <!-- The one number that is not a capability: how much this
                 provider can take in. Empty means what it always meant — ask
                 the server; what it said stands quietly beside the field. -->
            <div class="zeile" title={t('modell.kontext_titel')}>
              <span class="zahlname">{t('modell.kontext_feld')}</span>
              {#if !kontextEingabe && gefundenerKontext}
                <span class="gefunden">{t('modell.kontext_gefunden', { zahl: gefundenerKontext })}</span>
              {/if}
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

          <!-- Only where there is something to pick. A provider that reports
               a single model has no catalogue, and an empty list with a
               search field over it would promise a choice that does not
               exist. -->
          {#if katalog.length}
            <Serverabschnitt zeichen="raster" titel={t('liste.katalog')}>
              <div class="zeile stapel katalog">
                <Ankreuzliste
                  eintraege={katalog}
                  istAn={istGewaehlt}
                  istFest={(m) => m.angeheftet}
                  onschalten={katalogSchalten}
                  onalle={(alle) => katalogAlle(haus.id, alle)}
                />
              </div>
            </Serverabschnitt>
          {/if}

          <Knopfreihe>
            <button class="loeschknopf" onclick={() => anbieterEntfernen(haus)}>
              {t('modell.anbieter_entfernen')}
            </button>
          </Knopfreihe>
        </Fenstertafel>
      {:else if gezeigt === HINZU || !haeuser.length}
        {#if gezeigt === HINZU}
          <Anbietermaske fertig={() => (gezeigt = null)} />
        {:else}
          <!-- The empty half offers the way instead of repeating the notice
               that already stands on the left. A dashed edge says the same
               as the empty memory steps: nothing here yet, but something can
               go here. -->
          <button class="leerkachel" onclick={() => (gezeigt = HINZU)}>
            <span class="kreuz">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   stroke-width="2.2" stroke-linecap="round"><path d="M12 5 V19 M5 12 H19" /></svg>
            </span>
            <b>{t('modell.anbieter_hinzufuegen')}</b>
          </button>
        {/if}
      {/if}
    {/snippet}
  </Menueseite>
{/if}

<style>
  .liste {
    margin-top: 18px;
  }
  /* The way to a new provider stands like a provider row: its plus where
     the providers wear their sign. */
  .listenzeile.dazu {
    margin-top: 6px;
    padding-left: 10px;
    color: var(--text-leise);
  }
  .plus { display: inline-flex; justify-content: center; width: 24px; flex: none; color: var(--text-still); }

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

  /* The rows of the list: the house's sidebar row — quiet at rest, a
     lighter ground under the hand, the filled ground when chosen. */
  .listenzeile {
    display: flex;
    align-items: center;
    gap: 10px;
    /* The model's name starts under its provider's name: the row's 10, the
       sign's 24 and the 10 between them (Menuezeile.svelte). */
    padding: 7px 10px 7px 44px;
    border-radius: 9px;
    cursor: pointer;
    transition: background 0.12s;
  }
  .listenzeile:hover { background: var(--bg-erhoben); }
  .listenzeile.gewaehlt { background: var(--bg-hoch); }
  .wer { flex: 1; min-width: 0; }
  .mname {
    font-size: 13px;
    font-family: var(--schrift-fest);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .listenzeile.aus .mname { opacity: 0.42; }
  .haken {
    flex: none;
    width: 24px;
    height: 24px;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text);
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.12s, background 0.12s;
  }
  .haken.an { opacity: 1; }
  .listenzeile:hover .haken:not(.an) { opacity: 0.3; }
  .haken:hover { background: color-mix(in srgb, var(--text) 6%, transparent); }
  .haken:focus-visible { opacity: 1; outline: 2px solid var(--linie-stark); outline-offset: -2px; }

  .titelblock {
    flex: 1 1 260px;
    min-width: 0;
  }
  .markenzeile {
    display: flex;
    align-items: center;
    gap: 12px;
    color: var(--text);
  }
  .titel {
    margin: 0;
    font-size: var(--schrift-seitentitel);
    font-weight: 600;
    letter-spacing: -0.01em;
    line-height: 1.2;
    color: var(--text);
  }


  .schluesselname {
    font-family: var(--schrift-fest);
    font-size: 12.5px;
    color: var(--text-leise);
  }
  .stand {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    color: var(--gruen);
  }
  .stand.fehlt { color: var(--rot); }
  /* A measured number is a fact, not a state: brightness alone. */
  .gefunden {
    flex: none;
    font-size: 12px;
    color: var(--text-still);
    white-space: nowrap;
  }

  /* The catalogue brings its own search field and list; inside the card it
     needs no second ground and no second inset. */
  .katalog :global(.listenkarte) {
    background: none;
    padding: 0;
  }

  .leer { color: var(--text-still); font-size: 13px; padding: 6px 10px; }
</style>
