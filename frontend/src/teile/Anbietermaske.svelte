<script>
  /* Adding a cloud provider — the way out of a window that had none.

     The content of a pop-up (the page opens it with `Fenster`, which brings
     the title and the veil): a selection field for the kind, its fields
     under it, and the two words at the foot.

     Three kinds, and the third carries the other two: for anything
     OpenAI-compatible only the address differs, so somebody's own server in
     their own network costs no extra mask. */
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { melde, modelleLaden } from '../lib/zustand.svelte.js'
  import { LOGOS } from '../lib/logos.js'
  import Auswahlfeld from './Auswahlfeld.svelte'

  let { fertig } = $props()

  // Each kind wears its maker's mark; the own server has no maker, so it
  // wears the program's own.
  const kinds = $derived([
    { wert: 'anthropic', text: 'Anthropic', logo: LOGOS.anthropic },
    { wert: 'openai', text: 'OpenAI', logo: LOGOS.openai },
    { wert: 'eigen', text: t('modell.eigener'), logo: LOGOS.exe },
  ])

  let art = $state('anthropic')
  let schluessel = $state('')
  let kennung = $state('')
  let url = $state('')
  let arbeitet = $state(false)

  const eigen = $derived(art === 'eigen')
  const bereit = $derived(
    schluessel.trim().length >= 8 && (!eigen || (kennung.trim() && url.trim())),
  )

  async function verbinden() {
    arbeitet = true
    try {
      const angelegt = await api.anbieterHinzufuegen({
        art,
        schluessel: schluessel.trim(),
        kennung: eigen ? kennung.trim() : null,
        url: eigen ? url.trim() : null,
      })
      // The key is gone from here the moment it is saved: it lives in one
      // file on this machine and nowhere else, least of all in a browser.
      schluessel = ''
      // "The models appear by themselves" is this line — a fresh check,
      // because the regular one comes only every half minute.
      await modelleLaden(true)
      // The endpoint already checked reachability once, right when it was
      // added — this is that same result, not a second guess. Silence on
      // the server's end is not a success, even though the entry is saved.
      if (angelegt.erreichbar) {
        melde(t('modell.anbieter_da'), 'erfolg')
      } else {
        melde(angelegt.hinweis || t('modell.anbieter_da_nicht_erreichbar'), 'warnung')
      }
      fertig?.()
    } catch (fehler) {
      melde(fehler.message, 'fehler')
    } finally {
      arbeitet = false
    }
  }
</script>

<div class="mask">
  <!-- Which kind first, then what that kind needs — the own server its name
       and address, every kind its key. A label stands over its field. -->
  <div class="field-block">
    <label class="tafelkopf" for="am-art">{t('modell.anbieter_waehlen')}</label>
    <Auswahlfeld id="am-art" bind:wert={art} eintraege={kinds} beschriftung={t('modell.anbieter_waehlen')} />
  </div>
  {#if eigen}
    <div class="field-block">
      <label class="tafelkopf" for="am-kennung">{t('modell.eigener_name')}</label>
      <input id="am-kennung" class="eingabe" bind:value={kennung} placeholder={t('modell.eigener_name_beispiel')} />
    </div>
    <div class="field-block">
      <label class="tafelkopf" for="am-url">{t('modell.eigener_adresse')}</label>
      <input id="am-url" class="eingabe" bind:value={url} placeholder={t('modell.eigener_adresse_beispiel')} />
    </div>
  {/if}
  <!-- Where the key goes rides on the row as its title: it stays on this
       machine, and only whether one is there is ever shown. -->
  <div class="field-block" title={t('modell.schluessel_hinweis')}>
    <label class="tafelkopf" for="am-schluessel">{t('modell.schluessel')}</label>
    <input id="am-schluessel" class="eingabe" type="password" bind:value={schluessel} autocomplete="off" />
  </div>

  <!-- The house's main button and its plain sibling, in the row at the
       foot. -->
  <div class="foot">
    <button class="button" onclick={() => fertig?.()}>{t('modell.abbrechen')}</button>
    <button class="button primary" onclick={verbinden} disabled={!bereit || arbeitet}>
      {t('modell.verbinden')}
    </button>
  </div>
</div>

<style>
  .mask {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .field-block {
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
  }

  /* A field takes the width of the pop-up. */
  .eingabe {
    width: 100%;
    min-width: 0;
    height: 32px;
    box-sizing: border-box;
    /* A field on glass: glass with the house's field outline. */
    border: 1px solid var(--feldstrich);
    border-radius: 9px;
    background: var(--glass-button);
    color: var(--text);
    font: 400 13px/18px var(--schrift);
    padding: 0 12px;
  }
  .eingabe:focus { outline: 2px solid var(--linie-stark); outline-offset: -2px; }

  .foot {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    margin-top: 4px;
  }
  /* The foot's buttons are the house button (`.button`, stil/global.css);
     only the press is this mask's own. */
  .button:active:not(:disabled) { transform: scale(0.975); }
</style>
