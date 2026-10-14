<script>
  /* The layout mode: a small window over the real chat with every control
     of the chat layout (lib/chatlayout.js).

     Every change is in force at once, so the chat behind it shows what it
     does. Nothing is stored until "Save"; "Cancel" — and anything else that
     takes the window away, a menu opening over the chat or Escape — puts
     back the layout that stood when it opened. "Standard" moves the controls
     to the factory values, still unsaved. */
  import { untrack } from 'svelte'
  import { t } from '../lib/texte.svelte.js'
  import { zustand, chatlayoutSetzen, eineSeiteOffen } from '../lib/zustand.svelte.js'
  import { CHATLAYOUT, VORGABE_CHATLAYOUT, chatlayoutAusGespeichert } from '../lib/chatlayout.js'
  import Schieberegler from './Schieberegler.svelte'
  import Zahlenfeld from './Zahlenfeld.svelte'

  const vorher = { ...zustand.chatlayout }
  let werte = $state({ ...zustand.chatlayout })
  let gesichert = false

  const schrift = CHATLAYOUT.find((r) => r.id === 'schrift')
  const regler = CHATLAYOUT.filter((r) => r.id !== 'schrift')

  /* A field mid-typing can hold a number outside its range for a moment
     ("2" on the way to "20"); the chat is shown the clamped value. The
     setter reads the state it writes, so it runs untracked: this effect
     follows the controls alone. */
  $effect(() => {
    const neu = chatlayoutAusGespeichert({ ...werte })
    untrack(() => chatlayoutSetzen(neu, false))
  })

  function schliessen() {
    zustand.layoutModusOffen = false
  }

  function sichern() {
    gesichert = true
    chatlayoutSetzen(chatlayoutAusGespeichert({ ...werte }), true)
    schliessen()
  }

  function standard() {
    Object.assign(werte, VORGABE_CHATLAYOUT)
  }

  /* Whatever ends the window without "Save" ends it like "Cancel". */
  $effect(() => () => {
    if (!gesichert) chatlayoutSetzen(vorher, false)
  })

  $effect(() => {
    if (eineSeiteOffen()) schliessen()
  })

  /* The house's prompt dialog lies above this window; its Escape is its own. */
  function taste(ereignis) {
    if (ereignis.key === 'Escape' && !zustand.frage) schliessen()
  }
</script>

<svelte:window onkeydown={taste} />

<div class="layoutmodus" role="dialog" aria-label={t('einstellungen.layout_modus')}>
  <div class="kopf">{t('einstellungen.layout_modus')}</div>

  <div class="zeile">
    <span class="etikett">{t(schrift.text)}</span>
    <div class="zahlfeld">
      <Zahlenfeld bind:wert={werte.schrift} min={schrift.von} max={schrift.bis} ganzzahlig />
    </div>
  </div>

  {#each regler as r (r.id)}
    <div class="zeile">
      <span class="etikett">{t(r.text)}</span>
      <div class="regler">
        <div class="bahn">
          <Schieberegler bind:wert={werte[r.id]} min={r.von} max={r.bis}
                         beschriftung={t(r.text)} mit_zahl={false} fuellung />
        </div>
        <output class="zahl">{werte[r.id]}{r.einheit ? ' ' + r.einheit : ''}</output>
      </div>
    </div>
  {/each}

  <div class="fuss">
    <button class="button leise" onclick={standard}>{t('einstellungen.blase_standard')}</button>
    <span class="luecke"></span>
    <button class="button" onclick={schliessen}>{t('app.abbrechen')}</button>
    <button class="button primary" onclick={sichern}>{t('app.sichern')}</button>
  </div>
</div>

<style>
  /* Over the chat's right-hand side, where the column leaves room on a
     wide window; above the chat, below every dialog. */
  .layoutmodus {
    position: fixed;
    top: 72px;
    right: 24px;
    z-index: 60;
    width: 440px;
    max-width: calc(100vw - 32px);
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 16px;
    border: 1px solid var(--linie);
    border-radius: 9px;
    background: var(--bg-erhoben);
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.35);
  }
  .kopf {
    padding-bottom: 4px;
    font-size: 15px;
    font-weight: 600;
    color: var(--text);
  }
  .zeile {
    display: flex;
    align-items: center;
    gap: 14px;
    min-height: 36px;
  }
  .etikett {
    flex: 1;
    min-width: 0;
    font-size: 14.5px;
    color: var(--text-leise);
  }
  .zahlfeld {
    flex: none;
    width: 80px;
  }
  /* The house field is 32 high; the drawing gives the layout mode's rows
     36, and its steppers stay in sight. */
  .zahlfeld :global(.zahl) {
    height: 36px;
  }
  .zahlfeld :global(.treppe) {
    opacity: 1;
  }
  .regler {
    flex: none;
    width: 188px;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .bahn {
    flex: 1;
    min-width: 0;
  }
  .zahl {
    flex: none;
    box-sizing: border-box;
    width: 80px;
    height: 36px;
    padding: 0 12px;
    display: flex;
    align-items: center;
    justify-content: flex-end;
    border-radius: 9px;
    background: var(--bg-hoch);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    font-size: 14px;
    font-variant-numeric: tabular-nums;
    color: var(--text);
  }
  .fuss {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-top: 8px;
  }
  .luecke {
    flex: 1;
  }
  /* "Default" is the quiet word beside the two glass buttons: the house
     button's size, no ground and no edge. */
  .button.leise {
    background: none;
    box-shadow: none;
  }
</style>
