<script>
  /* The first start of the phone page — the one page that makes the program
     yours: what to be called, the language, the look. Shown once per
     installation, and answered on the machine as much as on the phone: what
     it asks lives in the settings afterwards.

     Only the three looks of the phone page are offered, Exe, Pearl and Snow. */
  import { t, texte, spracheWaehlen } from '../lib/texte.svelte.js'
  import Wortmarke from '../teile/Wortmarke.svelte'
  import { begruessung, anredeSpeichern, erststartNoetig } from '../lib/begruessung.svelte.js'
  import { LOOK_EXE, LOOK_PEARL, LOOK_SNOW } from './look.js'

  /* `look` is the look standing now (`dunkel` or `hell`); a pick is handed up
     through `onlook`, which saves it. */
  let { look, onlook } = $props()

  let shown = $state(false)
  let name = $state('')
  /* The click shows the wish at once, so the segment follows the hand — and
     falls back to the language that is really loaded the moment the wish is
     gone. `null` means: no switch on its way. Never a guess: a segment that
     claims German over an English page would lie. */
  let wish = $state(null)
  const language = $derived(wish ?? texte.sprache)
  let attempt = 0
  let failed = $state(false)
  let busy = false

  $effect(() => {
    if (!shown && erststartNoetig()) {
      name = begruessung.vorschlag
      shown = true
    }
  })

  async function pickLanguage(value) {
    const mine = ++attempt
    wish = value
    failed = false
    try {
      await spracheWaehlen(value)
    } catch {
      /* A switch whose catalogue does not arrive never happens: the wish is
         dropped below, so the segment stands on the language the page really
         speaks — and this says so. */
      if (mine === attempt) failed = true
    } finally {
      if (mine === attempt) wish = null
    }
  }

  async function finish() {
    if (busy) return
    busy = true
    try {
      /* One row holds the answered first start and the name, and writing a
         row replaces it: one write carries both. */
      begruessung.erststart = true
      await anredeSpeichern(name || begruessung.vorschlag, true)
      shown = false
    } catch {
      /* The row was not written: the page stays, and says so. */
      begruessung.erststart = false
      failed = true
    } finally {
      busy = false
    }
  }
</script>

{#if shown}
  <div class="page" role="dialog" aria-modal="true" aria-label={t('erststart.titel')}>
    <div class="head">
      <Wortmarke hoehe={34} zentriert />
      <h1>{t('erststart.titel')}</h1>
      <p>{t('erststart.satz')}</p>
    </div>
    <div class="rows">
      <label class="row">
        <span class="label">
          <span class="t">{t('erststart.anrede')}</span>
          <span class="u">{t('erststart.anrede_unter')}</span>
        </span>
        <input bind:value={name} placeholder={begruessung.vorschlag} aria-label={t('erststart.anrede')} />
      </label>
      <div class="row">
        <span class="label"><span class="t">{t('erststart.sprache')}</span></span>
        <div class="segment">
          <button aria-pressed={language === 'de'} onclick={() => pickLanguage('de')}>
            {t('einstellungen.sprache_deutsch')}
          </button>
          <button aria-pressed={language === 'en'} onclick={() => pickLanguage('en')}>
            {t('einstellungen.sprache_englisch')}
          </button>
        </div>
      </div>
      {#if failed}
        <p class="failure">{t('fehler.allgemein')}</p>
      {/if}
      <div class="row">
        <span class="label"><span class="t">{t('erststart.erscheinung')}</span></span>
        <div class="segment">
          <button aria-pressed={look === LOOK_EXE} onclick={() => onlook(LOOK_EXE)}>
            {t('einstellungen.dunkel')}
          </button>
          <button aria-pressed={look === LOOK_PEARL} onclick={() => onlook(LOOK_PEARL)}>
            {t('einstellungen.hell')}
          </button>
          <button aria-pressed={look === LOOK_SNOW} onclick={() => onlook(LOOK_SNOW)}>
            {t('einstellungen.snow')}
          </button>
        </div>
      </div>
    </div>
    <div class="foot">
      <span class="ready"><span class="dot"></span>{t('erststart.bereit')}</span>
      <button class="done" onclick={finish}>{t('erststart.fertig')}</button>
    </div>
  </div>
{/if}

<style>
  .page {
    position: fixed;
    inset: 0;
    z-index: 65;
    display: flex;
    flex-direction: column;
    padding: calc(28px + env(safe-area-inset-top)) 18px calc(18px + env(safe-area-inset-bottom));
    background: var(--bg);
    color: var(--text);
    overflow-y: auto;
  }
  .head {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 7px;
    margin-bottom: 22px;
  }
  h1 {
    margin: 0;
    font: 600 22px var(--schrift);
    letter-spacing: -0.01em;
  }
  p {
    margin: 0;
    color: var(--text-still);
    font-size: var(--schrift-hinweis);
  }
  .rows {
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  /* A step above the page, one row after the other joined at the corners. */
  .row {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 56px;
    padding: 6px 14px;
    background: var(--bg-hoch);
  }
  .row:first-child {
    border-radius: 9px 9px 0 0;
  }
  .row:last-child {
    border-radius: 0 0 9px 9px;
  }
  .label {
    flex: 1;
    min-width: 0;
  }
  .t {
    display: block;
    font-weight: 600;
    font-size: 13px;
  }
  .u {
    display: block;
    font-size: 11.5px;
    color: var(--text-still);
  }
  input {
    width: 140px;
    height: 36px;
    padding: 0 10px;
    border: none;
    border-radius: 9px;
    background: color-mix(in srgb, var(--text) 7%, var(--bg-hoch));
    color: var(--text);
    /* 16 px: a smaller field makes the phone zoom the page in on focus. */
    font: 400 16px var(--schrift);
  }
  .segment {
    display: flex;
    padding: 3px;
    border-radius: 9px;
    background: color-mix(in srgb, var(--text) 7%, var(--bg-hoch));
  }
  .segment button {
    min-width: 56px;
    height: 34px;
    padding: 0 10px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    font: 400 13px var(--schrift);
  }
  .segment button[aria-pressed='true'] {
    background: color-mix(in srgb, var(--text) 14%, var(--bg-hoch));
    color: var(--text);
  }
  .failure {
    padding: 6px 10px;
    margin: 8px 0;
    border-radius: 9px;
    background: color-mix(in srgb, var(--rot) 12%, var(--bg));
    color: var(--rot-text);
  }
  .foot {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: auto;
    padding-top: 22px;
  }
  .ready {
    display: flex;
    align-items: center;
    gap: 7px;
    flex: 1;
    font-size: 11.5px;
    color: var(--text-still);
  }
  .dot {
    width: 7px;
    height: 7px;
    border-radius: 99px;
    background: var(--gruen);
  }
  .done {
    height: 48px;
    padding: 0 28px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: 500 14px var(--schrift);
  }
  .done:active {
    background: var(--glass-hover);
  }
</style>
