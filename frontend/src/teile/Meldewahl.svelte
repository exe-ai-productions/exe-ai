<script>
  /* Everything the program does to get attention, on one page.

     It was in three places and one of them was nowhere: the sound switch
     sat under the language, the pulse of the status dots could not be
     reached at all, and how long a notice stands was a number in the code.
     A person who finds one of the three has no reason to expect the other
     two somewhere else.

     Three groups with air between them rather than one long tile stack —
     what is heard, what is read, what moves. Same tile shape as the
     appearance page next door: name left, subtitle under it, control
     right. A component cannot borrow its parent's scoped styles, so the
     tile is declared here as well, exactly as Klangwahl.svelte does.

     The sounds live here now and no longer under the language: how loud
     the program is is not a question of which words it uses, and it is
     the same question as whether it may also flash and pulse. */
  import InfoMark from './InfoMark.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import Schalter from './Schalter.svelte'
  import Zahlenfeld from './Zahlenfeld.svelte'
  import { t } from '../lib/texte.svelte.js'
  import {
    klaengeSchalten, klangwahl, nurHintergrundSchalten, pegelSetzen, probehoeren, setSound,
  } from '../lib/klaenge.svelte.js'
  import {
    meldewesen, melderSchalten, popupSekundenSetzen, popupsAusSchalten, punktSchalten,
  } from '../lib/meldewesen.svelte.js'

  /* The four dots, in the order they sit on the screen from the rail
     outwards. The key is the one the module stores under. */
  const PUNKTE = ['agenten', 'cronjob', 'terminal', 'chat']

  /* The four things worth reporting, one row each: a test button, the
     switch of its sound and the switch of its popup. */
  const MELDER = ['fertig', 'wartet', 'fehler', 'agent_cronjob']

  /* The slider's own position. It starts from the stored level and is
     handed on from here — the stored value never drives it back while it
     is being moved. */
  let pegel = $state(klangwahl.pegel)
  let uebernommen = false
  $effect(() => {
    /* Once, when the stored level has arrived from the service. */
    if (!uebernommen && klangwahl.geladen) {
      pegel = klangwahl.pegel
      uebernommen = true
    }
  })

  /* Same for the duration: the field owns its digits while a hand is on
     it, and the stored number seeds it once.

     The field is EMPTY where nothing is set and says "Auto" for it; the
     store keeps the zero, which is what the saved settings and the notice
     logic have always read as "no fixed duration"
     (frontend/src/lib/meldewesen.svelte.js). The conversion happens here, at
     the one place the two meet, rather than by teaching the stored shape a
     second spelling of the same thing. */
  let sekunden = $state(meldewesen.popupSekunden || null)
  let sekundenDa = false
  $effect(() => {
    if (!sekundenDa && meldewesen.geladen) {
      sekunden = meldewesen.popupSekunden || null
      sekundenDa = true
    }
  })
  $effect(() => {
    if (sekundenDa && (sekunden ?? 0) !== meldewesen.popupSekunden) {
      popupSekundenSetzen(sekunden ?? 0)
    }
  })
</script>

<div class="bloecke">
  <section class="block">
    <div class="blocktitel tafelkopf">{t('meldewesen.gruppe_toene')}</div>
    <div class="kachelliste">
      <div class="einstellkachel">
        <div class="zeilentext mitmarke">{t('meldewesen.toene')}<InfoMark text={t('meldewesen.info_toene')} /></div>
        <Schalter
          an={!klangwahl.aus}
          beschriftung={t('meldewesen.toene')}
          onschalten={(an) => klaengeSchalten(an)}
        />
      </div>

      <!-- A slider tile: the name and the number on one line, the slider
           over the whole width under them. -->
      <div class="einstellkachel regel">
        <div class="kopfzeile">
          <div class="zeilentext">{t('meldewesen.lautstaerke')}</div>
          <span class="zahl">{pegel}</span>
        </div>
        <!-- The slider owns its position while a hand is on it. Writing the
             state back into `value` on every event is what made the knob
             fight the finger. -->
        <input
          class="regler"
          type="range"
          min="0"
          max="100"
          bind:value={pegel}
          aria-label={t('meldewesen.lautstaerke')}
          oninput={() => pegelSetzen(pegel)}
          onchange={() => probehoeren('fertig')}
        />
      </div>

      <div class="einstellkachel">
        <div class="zeilentext mitmarke">{t('meldewesen.nur_hintergrund')}<InfoMark text={t('meldewesen.info_nur_hintergrund')} /></div>
        <Schalter
          an={klangwahl.nurHintergrund}
          beschriftung={t('meldewesen.nur_hintergrund')}
          onschalten={(an) => nurHintergrundSchalten(an)}
        />
      </div>
    </div>
  </section>

  <section class="block">
    <div class="blocktitel tafelkopf">{t('meldewesen.gruppe_meldungen')}</div>
    <div class="kachelliste">
      <!-- One row per occurrence, laid out as a table: the name, a button
           that plays its sound whatever the switches say (a sound that can
           only be judged by provoking an error would never be judged at
           all) and the switch of its sound. Whether it is also seen as a
           popup is asked in the block below, one switch to a row. No
           subtitles: the group heading and the words say the whole
           thing. -->
      <div class="einstellkachel table-head" aria-hidden="true">
        <span class="zeilentext"></span>
        <span class="test-space"></span>
        <span class="column">{t('meldewesen.spalte_ton')}</span>
      </div>
      {#each MELDER as name (name)}
        <div class="einstellkachel">
          <div class="zeilentext mitmarke">{t(`meldewesen.${name}`)}<InfoMark text={t(`meldewesen.info_${name}`)} /></div>
          <button class="probe" onclick={() => probehoeren(name)}
                  title={t('meldewesen.probe')} aria-label={t('meldewesen.probe')}>
            <Hauszeichen zeichen="speaker" groesse={20} />
          </button>
          <span class="column">
            <Schalter
              an={klangwahl.ton[name] !== false}
              beschriftung={`${t(`meldewesen.${name}`)} · ${t('meldewesen.spalte_ton')}`}
              onschalten={(an) => setSound(name, an)}
            />
          </span>
        </div>
      {/each}
    </div>
  </section>

  <section class="block popup-block">
    <div class="blocktitel tafelkopf">{t('meldewesen.spalte_popup')}</div>
    <div class="kachelliste">
      <!-- Stops every notice card from being drawn; the duration below
           stays as it was and greys out while this is on. -->
      <div class="einstellkachel">
        <div class="zeilentext mitmarke">{t('meldewesen.popups_aus')}<InfoMark text={t('meldewesen.info_popups_aus')} /></div>
        <Schalter
          an={meldewesen.popupsAus}
          beschriftung={t('meldewesen.popups_aus')}
          onschalten={(an) => popupsAusSchalten(an)}
        />
      </div>

      <div class="einstellkachel" class:grau={meldewesen.popupsAus}>
        <div class="zeilentext">{t('meldewesen.popup')}</div>
        <!-- A number, so a number field — and zero is not "no time at all"
             but the word standing in for it: a notice about a run then
             waits for that run to be looked at instead of for a clock.
             That is why there is no second switch beside this. -->
        <div class="feld">
          <Zahlenfeld
            bind:wert={sekunden}
            min={0}
            max={60}
            schritt={1}
            ganzzahlig={true}
            nullwort={t('parameter.auto')}
            gesperrt={meldewesen.popupsAus}
          />
        </div>
        <span class="einheit">{t('meldewesen.popup_einheit')}</span>
      </div>

      <!-- One row per occurrence, one switch: may its card be drawn. -->
      {#each MELDER as name (name)}
        <div class="einstellkachel">
          <div class="zeilentext mitmarke">{t(`meldewesen.${name}`)}<InfoMark text={t(`meldewesen.info_${name}`)} /></div>
          <Schalter
            an={meldewesen.melder[name] !== false}
            beschriftung={`${t(`meldewesen.${name}`)} · ${t('meldewesen.spalte_popup')}`}
            onschalten={(an) => melderSchalten(name, an)}
          />
        </div>
      {/each}
    </div>
  </section>

  <section class="block">
    <div class="blocktitel tafelkopf">{t('meldewesen.gruppe_visuell')}</div>
    <div class="kachelliste">
      {#each PUNKTE as name (name)}
        <div class="einstellkachel">
          <div class="zeilentext mitmarke">{t(`meldewesen.punkt_${name}`)}<InfoMark text={t(`meldewesen.info_punkt_${name}`)} /></div>
          <Schalter
            an={meldewesen.punkte[name] !== false}
            beschriftung={t(`meldewesen.punkt_${name}`)}
            onschalten={(an) => punktSchalten(name, an)}
          />
        </div>
      {/each}
    </div>
  </section>
</div>

<style>
  /* Air between the groups, not one wall of tiles: the gap is what says
     "these three belong together and those three do not". */
  .bloecke {
    display: flex;
    flex-direction: column;
    gap: 26px;
  }
  .block {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  /* The same small heading the settings nav uses over its groups.
     Text itself: global.css, .tafelkopf. */
  .blocktitel {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 2px;
  }
  .kachelliste {
    display: flex;
    flex-direction: column;
    gap: 0;
    padding: 0 16px;
    /* A card on the page: card glass with its fine line. */
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    border-radius: 9px;
  }
  .einstellkachel {
    border: none;
    border-radius: 0;
    padding: 12px 0;
    display: flex;
    align-items: center;
    gap: 14px;
  }
  .einstellkachel + .einstellkachel {
    border-top: 1px solid var(--linie);
  }
  /* A row whose value is set aside by another switch stays readable. */
  .einstellkachel.grau {
    opacity: 0.45;
  }
  .einstellkachel.regel {
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
  }
  .kopfzeile {
    display: flex;
    align-items: center;
    gap: 14px;
    min-width: 0;
  }
  .zeilentext {
    flex: 1;
    min-width: 0;
    font-size: 13px;
  }
  /* The mark right after the name, 6 px away, and its sentence on a line of
     its own below the name when it is open. */
  .mitmarke {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }
  .mitmarke :global(.mark) {
    margin-left: 0;
  }
  .zahl {
    flex: none;
    width: 30px;
    text-align: right;
    font-size: 13px;
    color: var(--text-leise);
    font-variant-numeric: tabular-nums;
  }
  .regler {
    flex: none;
    margin: 0;
    /* The system slider is replaced as a whole: its accent is a colour with
       a meaning of its own, and the slider states a level, not a state. */
    -webkit-appearance: none;
    appearance: none;
    height: 16px;
    background: none;
  }
  /* A thin track on the field glass and a round handle in the text colour
     — the level reads from where the handle sits, not from a fill. */
  .regler::-webkit-slider-runnable-track {
    height: 4px;
    border-radius: 9px;
    background: var(--glass-button);
  }
  .regler::-moz-range-track {
    height: 4px;
    border-radius: 9px;
    background: var(--glass-button);
  }
  .regler::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 16px;
    height: 16px;
    margin-top: -6px;
    border: none;
    border-radius: 50%;
    background: var(--text);
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.45);
  }
  .regler::-moz-range-thumb {
    width: 16px;
    height: 16px;
    border: none;
    border-radius: 50%;
    background: var(--text);
  }
  .feld {
    flex: none;
    width: 96px;
  }
  .einheit {
    flex: none;
    font-size: 13px;
    color: var(--text-leise);
  }
  /* The table's column: the name takes what is left, then the button and
     one switch column as wide as the switch itself, so the switch stands on
     the same right edge as the switches of the rows of every other group,
     and the header over it is centred on it. */
  .column {
    flex: none;
    width: 34px;
    display: flex;
    justify-content: center;
  }
  .table-head {
    padding: 8px 0 0;
  }
  .table-head .column {
    font-size: 12.5px;
    color: var(--text-leise);
  }
  .test-space {
    flex: none;
    width: 32px;
  }
  .probe {
    flex: none;
    /* A square, and the width the header leaves free over the column, so
       the columns line up. */
    width: 32px;
    height: 32px;
    padding: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    cursor: pointer;
    transition: background 0.14s, color 0.14s;
  }
  .probe:hover {
    background: var(--glass-hover);
    color: var(--text);
  }
</style>
