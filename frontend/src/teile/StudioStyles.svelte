<script>
  /* "Edit styles": a card over the drawing surface. The styles on the
     left, the one picked on the right with its name, its text — where
     `{prompt}` stands for the prompt — and its negative. Every change is
     kept as it is typed; a style whose name is emptied is gone once the
     card shuts. The styles hold for every chat (app/bildstile.py), and a
     chat keeps its style by the style's id: a new name reaches every chat
     that draws through it. */
  import Hauszeichen from './Hauszeichen.svelte'
  import { newStyleId, stile, stileLaden, stileSpeichern, werte } from '../lib/studio.svelte.js'
  import { t } from '../lib/texte.svelte.js'

  let { offen = $bindable(false) } = $props()

  let gewaehlt = $state(0)
  const stil = $derived(stile.liste[gewaehlt] ?? null)

  /* Written a moment after the last keystroke, not with every letter. */
  let takt = null
  function geaendert() {
    clearTimeout(takt)
    takt = setTimeout(stileSpeichern, 400)
  }

  /* A chat that chose its style before styles had ids names it by the
     name it had. Before that name changes, the open chat is moved over to
     the style's id, so the style stays picked in it. */
  function nameAnfang() {
    if (werte.stil && werte.stil === stil.name) werte.stil = stil.id
  }

  function neu() {
    const namen = new Set(stile.liste.map((s) => s.name))
    let name = t('studio.neuer_stil')
    for (let n = 2; namen.has(name); n += 1) name = `${t('studio.neuer_stil')} ${n}`
    stile.liste.push({ id: newStyleId(), name, text: '{prompt}', negativ: '' })
    gewaehlt = stile.liste.length - 1
    geaendert()
  }

  async function schliessen() {
    clearTimeout(takt)
    await stileSpeichern()
    await stileLaden()
    offen = false
  }

  function taste(ereignis) {
    if (ereignis.key === 'Escape') schliessen()
  }
</script>

<svelte:window onkeydown={taste} />

<div class="karte" role="dialog" aria-modal="false" aria-label={t('studio.stile_titel')}>
  <div class="kopf">
    <span class="titel">{t('studio.stile_titel')}</span>
    <button class="zu" onclick={schliessen} aria-label={t('app.schliessen')} title={t('app.schliessen')}>
      <Hauszeichen zeichen="kreuz" groesse={12} />
    </button>
  </div>
  <div class="innen">
    <div class="liste">
      {#each stile.liste as eintrag, i (eintrag.id)}
        <button class:an={i === gewaehlt} onclick={() => (gewaehlt = i)}>{eintrag.name || '—'}</button>
      {/each}
      <!-- Nothing is added to a list that could not be read. -->
      <button class="neu" onclick={neu} disabled={!stile.geladen}>
        <Hauszeichen zeichen="plus" groesse={12} />
        {t('studio.neuer_stil')}
      </button>
    </div>
    {#if stil}
      <div class="felder">
        <label>
          <span>{t('agenten.name')}</span>
          <input type="text" bind:value={stil.name} onfocus={nameAnfang} oninput={geaendert} />
        </label>
        <label>
          <span>{t('studio.stil_text')}</span>
          <textarea rows="3" bind:value={stil.text} oninput={geaendert}></textarea>
        </label>
        <label>
          <span>{t('studio.negativ')}</span>
          <textarea rows="2" bind:value={stil.negativ} oninput={geaendert}></textarea>
        </label>
      </div>
    {/if}
  </div>
</div>

<style>
  .karte {
    position: absolute;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -60%);
    z-index: 6;
    width: min(600px, calc(100% - 48px));
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 18px;
    border-radius: 9px;
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line), 0 16px 48px rgba(0, 0, 0, 0.18);
    backdrop-filter: blur(18px);
    color: var(--text);
    font: 400 13px/18px var(--schrift);
  }
  .kopf {
    display: flex;
    align-items: center;
  }
  .titel {
    flex: 1;
    font-size: 16px;
    font-weight: 600;
  }
  .zu {
    display: grid;
    place-items: center;
    width: 26px;
    height: 26px;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text-leise);
    cursor: pointer;
  }
  .zu:hover {
    background: var(--glass-hover);
    color: var(--text);
  }
  .innen {
    display: grid;
    grid-template-columns: 160px 1fr;
    gap: 16px;
  }
  .liste {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .liste button {
    display: flex;
    align-items: center;
    gap: 8px;
    height: 34px;
    padding: 0 10px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .liste button:hover {
    background: var(--glass-hover);
  }
  .liste button.an {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
  }
  .liste .neu {
    color: var(--text-leise);
  }
  .liste .neu:disabled {
    opacity: 0.4;
    cursor: default;
  }
  .felder {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .felder label {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .felder span {
    color: var(--text-leise);
  }
  .felder input,
  .felder textarea {
    width: 100%;
    padding: 8px 12px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--feldstrich);
    color: var(--text);
    font: inherit;
    font-size: 13px;
    resize: vertical;
    outline: none;
  }
</style>
