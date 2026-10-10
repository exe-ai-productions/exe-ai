<script>
  /* Adding a cloud provider — the way out of a window that had none.

     It fits inside the right half of the list window and does not make it
     any bigger: the window sizes are settled, and one that grows for one
     purpose is the beginning of four different windows.

     Three kinds, and the third carries the other two: for anything
     OpenAI-compatible only the address differs, so somebody's own server in
     their own network costs no extra mask. */
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { melde, modelleLaden } from '../lib/zustand.svelte.js'
  import { LOGOS } from '../lib/logos.js'
  import Fensterkopf from './Fensterkopf.svelte'
  import Fenstertafel from './Fenstertafel.svelte'
  import Serverabschnitt from './Serverabschnitt.svelte'
  import Knopfreihe from './Knopfreihe.svelte'

  let { fertig } = $props()

  // Each kind wears its maker's mark; the own server has no maker, so it
  // wears the program's own.
  const ARTEN = [
    { id: 'anthropic', name: 'Anthropic', marke: 'anthropic' },
    { id: 'openai', name: 'OpenAI', marke: 'openai' },
    { id: 'eigen', name: null, marke: 'exe' },
  ]

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
        melde(t('modell.anbieter_da_nicht_erreichbar'), 'warnung')
      }
      fertig?.()
    } catch (fehler) {
      melde(fehler.message, 'fehler')
    } finally {
      arbeitet = false
    }
  }
</script>

<Fenstertafel>
  <Fensterkopf zeichen="plus" titel={t('modell.anbieter_hinzufuegen')} />

  <!-- One card: which kind on the first row, then what that kind needs —
       the own server its name and address, every kind its key. -->
  <Serverabschnitt zeichen="wolke" titel={t('modell.anbieter_waehlen')}>
    <div class="zeile wahlzeile">
      {#each ARTEN as a}
        <button class="art" class:an={art === a.id} onclick={() => (art = a.id)}>
          <svg class="marke" viewBox={LOGOS[a.marke].vb} width="20" height="20" aria-hidden="true">{@html LOGOS[a.marke].html}</svg>
          <span class="wort">{a.name ?? t('modell.eigener')}</span>
        </button>
      {/each}
    </div>
    {#if eigen}
      <div class="zeile">
        <label class="regelname" for="am-kennung">{t('modell.eigener_name')}</label>
        <input id="am-kennung" class="eingabe" bind:value={kennung} placeholder={t('modell.eigener_name_beispiel')} />
      </div>
      <div class="zeile">
        <label class="regelname" for="am-url">{t('modell.eigener_adresse')}</label>
        <input id="am-url" class="eingabe" bind:value={url} placeholder={t('modell.eigener_adresse_beispiel')} />
      </div>
    {/if}
    <!-- Where the key goes rides on the row as its title: it stays on this
         machine, and only whether one is there is ever shown. -->
    <div class="zeile" title={t('modell.schluessel_hinweis')}>
      <label class="regelname" for="am-schluessel">{t('modell.schluessel')}</label>
      <input id="am-schluessel" class="eingabe" type="password" bind:value={schluessel} autocomplete="off" />
    </div>
  </Serverabschnitt>

  <!-- The house's main button and its plain sibling, in the row at the
       foot of the page. -->
  <Knopfreihe>
    <button class="button" onclick={() => fertig?.()}>{t('modell.abbrechen')}</button>
    <button class="button primary" onclick={verbinden} disabled={!bereit || arbeitet}>
      {t('modell.verbinden')}
    </button>
  </Knopfreihe>
</Fenstertafel>

<style>

  /* The three kinds side by side, equally wide, on the first row of the
     card. */
  .zeile.wahlzeile {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
  }
  .art {
    height: 36px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    font: 500 13px/18px var(--schrift);
    padding: 0 12px;
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
  }
  .marke { flex: none; }
  .wort {
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .art:hover { color: var(--text); background: var(--glass-hover); }
  /* Chosen is a fact about the form, not a state of the program — so it is
     marked by brightness, never by colour. */
  .art.an { background: var(--glass-button); box-shadow: inset 0 0 0 1px var(--glass-button-edge); color: var(--text); }

  /* A field takes the row but for its name. */
  .eingabe {
    flex: 1;
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

  /* The foot's buttons are the house button (`.button`, stil/global.css);
     only the press is this mask's own. */
  .button:active:not(:disabled) { transform: scale(0.975); }
</style>
