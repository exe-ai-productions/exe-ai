<script>
  /* The studio's prompt bar: floating at the foot of the surface, centred,
     the way the chat's input floats over the chat. The prompt on top; under
     it the negative (folded away until asked for), the style the prompt is
     drawn through, "Improve" with its one step back, and "Draw".

     The style list opens upwards; its last entry opens the window where the
     styles are written (StudioStyles.svelte). The styles hold for every
     chat, the choice is the chat's own.

     At the bar's left, top edges level, stands the mode: what the next
     press draws — "auto" or one kind of the chosen half. Its list opens
     upwards as well. */
  import StudioStyles from './StudioStyles.svelte'
  import { api } from '../lib/api.js'
  import { draussen } from '../lib/draussen.js'
  import {
    art, autoKind, auswahl, kindsOf, pictureMissing, stile, stileLaden, stilVon, werte,
  } from '../lib/studio.svelte.js'
  import { studioZeichnen, zeichnung } from '../lib/studiozeichnen.svelte.js'
  import { t } from '../lib/texte.svelte.js'
  import { melde, zustand } from '../lib/zustand.svelte.js'

  stileLaden()

  let negativOffen = $state(false)
  let stilOffen = $state(false)
  let stileBearbeiten = $state(false)
  // The style the chat draws through, found by its id; none once it is gone.
  const chosenStyle = $derived(stilVon(werte.stil))
  const stilName = $derived(chosenStyle?.name ?? '')

  /* "Improve": the prompt preparation of the picture server rewrites the
     prompt for the model's family and is told the name of the chosen style.
     One step back, for both fields, and no more: the question it answers
     is "that was worse, give me mine back". */
  let verbessert = $state(false)
  let vorher = $state(null)
  const kannVerbessern = $derived(!verbessert && Boolean(werte.prompt.trim()))
  async function verbessern() {
    if (!kannVerbessern) return
    verbessert = true
    const alt = { prompt: werte.prompt, negativ: werte.negativ }
    try {
      const antwort = await api.bildPromptVerbessern({
        prompt: werte.prompt, negativ: werte.negativ, modell: werte.modell,
        familie: werte.familie || auswahl.klasse, cfg: Number(werte.cfg), stil: stilName,
      })
      werte.prompt = antwort.prompt
      if (antwort.negativ) werte.negativ = antwort.negativ
      vorher = alt
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'fehler')
    } finally {
      verbessert = false
    }
  }
  function zurueck() {
    if (!vorher) return
    werte.prompt = vorher.prompt
    werte.negativ = vorher.negativ
    vorher = null
  }

  /* The mode. The list holds "auto" and every kind the model's family
     draws in the chosen half; behind "auto" it says what that would draw as
     things stand, the field shows the entry that is chosen. */
  let modeOpen = $state(false)
  const kinds = $derived(kindsOf(auswahl.medium === 'video'))
  const autoEntry = $derived(`${t('bild.art_auto')} · ${t(autoKind().text)}`)
  const modeText = $derived(auswahl.art === 'auto' ? t('bild.art_auto') : t(art().text))
  function chooseMode(value) {
    auswahl.art = value
    modeOpen = false
  }
  /* A kind that draws from a picture rests while none is there; the draw
     itself refuses it as well, whichever way it is asked. */
  const noPicture = $derived(pictureMissing())

  // Enter draws, Shift+Enter breaks the line — as in the chat's input.
  function taste(ereignis) {
    if (ereignis.key === 'Enter' && !ereignis.shiftKey && !ereignis.isComposing) {
      ereignis.preventDefault()
      studioZeichnen()
    }
  }

  // The chat keeps the style's id, '' for none.
  function stilWaehlen(id) {
    werte.stil = id
    stilOffen = false
  }
</script>

<div class="dock">
<div class="modeplace" use:draussen={() => (modeOpen = false)}>
  <button class="mode glas" aria-haspopup="listbox" aria-expanded={modeOpen}
          aria-label="{t('bild.art')}: {modeText}" onclick={() => (modeOpen = !modeOpen)}>
    <span>{modeText}</span>
    <svg class="winkel" class:auf={!modeOpen} width="11" height="11" viewBox="0 0 11 11" fill="none"
         stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M2.75 6.875L5.5 4.125L8.25 6.875" />
    </svg>
  </button>
  {#if modeOpen}
    <div class="uplist modelist glas" role="listbox" aria-label={t('bild.art')}>
      <button role="option" aria-selected={auswahl.art === 'auto'} class:an={auswahl.art === 'auto'}
              onclick={() => chooseMode('auto')}>{autoEntry}</button>
      {#each kinds as kind (kind.value)}
        <button role="option" aria-selected={auswahl.art === kind.value} class:an={auswahl.art === kind.value}
                onclick={() => chooseMode(kind.value)}>{t(kind.text)}</button>
      {/each}
    </div>
  {/if}
</div>
<div class="leiste glas" role="group" aria-label={t('bild.prompt')}>
  <textarea class="prompt" rows="1" bind:value={werte.prompt} onkeydown={taste}
            aria-label={t('bild.prompt')}></textarea>
  {#if negativOffen}
    <textarea class="prompt negativ" rows="1" bind:value={werte.negativ} aria-label={t('bild.negativ')}></textarea>
  {/if}
  <div class="reihe">
    <button class="pille" aria-expanded={negativOffen} onclick={() => (negativOffen = !negativOffen)}>
      {t('studio.negativ')}
      <svg class="winkel" class:auf={negativOffen} width="11" height="11" viewBox="0 0 11 11" fill="none"
           stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M2.75 4.125L5.5 6.875L8.25 4.125" />
      </svg>
    </button>
    <div class="stilplatz" use:draussen={() => (stilOffen = false)}>
      <button class="pille" aria-haspopup="listbox" aria-expanded={stilOffen} onclick={() => (stilOffen = !stilOffen)}>
        {t('studio.stil')}: {stilName || t('studio.stil_keiner')}
        <svg class="winkel" class:auf={!stilOffen} width="11" height="11" viewBox="0 0 11 11" fill="none"
             stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M2.75 6.875L5.5 4.125L8.25 6.875" />
        </svg>
      </button>
      {#if stilOffen}
        <div class="uplist stilliste glas" role="listbox" aria-label={t('studio.stil')}>
          <button role="option" aria-selected={!stilName} class:an={!stilName} onclick={() => stilWaehlen('')}>
            {t('studio.stil_keiner')}
          </button>
          {#each stile.liste.filter((s) => s.name) as stil (stil.id)}
            <button role="option" aria-selected={chosenStyle?.id === stil.id} class:an={chosenStyle?.id === stil.id}
                    onclick={() => stilWaehlen(stil.id)}>{stil.name}</button>
          {/each}
          <span class="trenner" aria-hidden="true"></span>
          <button onclick={() => { stilOffen = false; stileBearbeiten = true }}>{t('studio.stile_bearbeiten')}</button>
        </div>
      {/if}
    </div>
    <span class="luft"></span>
    {#if vorher}
      <button class="schlicht" onclick={zurueck}>{t('bild.verbessern_zurueck')}</button>
    {/if}
    <button class="schlicht" disabled={!kannVerbessern} onclick={verbessern} title={t('bild.verbessern_tipp')}>
      <!-- The catalogue's sparkle star, as the drawing has it. -->
      <svg width="14" height="14" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-linecap="round"
           stroke-linejoin="round" aria-hidden="true">
        <path d="M28 14 L32.5 27.5 L46 32 L32.5 36.5 L28 50 L23.5 36.5 L10 32 L23.5 27.5 Z" stroke-width="5" />
        <path d="M50 10 V22 M44 16 H56" stroke-width="4.5" />
      </svg>
      {verbessert ? t('bild.verbessern_laeuft') : t('bild.verbessern')}
    </button>
    <button class="zeichnen"
            disabled={!werte.prompt.trim() || zeichnung.bereitet || !zeichnung.losZeichnen || noPicture}
            onclick={() => studioZeichnen()}>
      <!-- How many pictures are in the works, as on the picture window's
           button. Nothing there while none is running. -->
      {#if zustand.bildWarteschlange > 0}
        <span class="zeichenzahl">{zustand.bildWarteschlange}</span>
      {/if}
      {t('bild.erzeugen')}
    </button>
  </div>
</div>
</div>

{#if stileBearbeiten}
  <StudioStyles bind:offen={stileBearbeiten} />
{/if}

<style>
  .glas {
    background: var(--glass-card);
    box-shadow: inset 0 0 0 1px var(--glass-card-line);
    border-radius: 9px;
    backdrop-filter: blur(14px);
  }
  /* The mode field and the bar at the foot of the surface, top edges
     level. The bar stands centred while the field has room at its left;
     where it has not, the field keeps its room and the bar gives way: it
     moves over, then narrows. The dock takes no pointer of its own — under
     its free ends the surface stays the surface. */
  .dock {
    position: absolute;
    left: 80px;
    right: 80px;
    bottom: 44px;
    z-index: 3;
    display: grid;
    grid-template-columns: minmax(max-content, 1fr) minmax(0, 640px) 1fr;
    align-items: start;
    pointer-events: none;
  }
  .modeplace {
    position: relative;
    justify-self: end;
    margin-right: 8px;
    pointer-events: auto;
  }
  /* As wide as the chosen entry, so every entry is read whole. */
  .mode {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 32px;
    padding: 0 10px;
    border: none;
    color: var(--text);
    font: 400 13px/18px var(--schrift);
    white-space: nowrap;
    cursor: pointer;
  }
  .mode:hover {
    background: var(--glass-hover);
  }
  .leiste {
    min-width: 0;
    pointer-events: auto;
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px 12px 10px 16px;
    box-shadow: inset 0 0 0 1px var(--glass-card-line), 0 8px 28px rgba(0, 0, 0, 0.12);
  }
  .prompt {
    width: 100%;
    min-height: 22px;
    max-height: 160px;
    padding: 0;
    border: none;
    background: none;
    resize: none;
    field-sizing: content;
    color: var(--text);
    font: 400 15px/22px var(--schrift);
    outline: none;
  }
  .prompt.negativ {
    padding-top: 6px;
    border-top: 1px solid var(--glass-card-line);
    color: var(--text-leise);
    font-size: 14px;
  }
  /* A bar too narrow for the whole row breaks it: what does not fit goes
     under, at the right end where "Draw" always stands. */
  .reihe {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    align-items: center;
    gap: 8px;
  }
  .luft {
    flex: 1;
  }
  .pille,
  .schlicht,
  .zeichnen {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 28px;
    padding: 0 10px;
    border: none;
    border-radius: 9px;
    font: 400 13px/18px var(--schrift);
    white-space: nowrap;
    cursor: pointer;
  }
  .pille {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  .schlicht {
    background: none;
    color: var(--text);
  }
  .schlicht:hover:not(:disabled) {
    background: var(--glass-hover);
  }
  .schlicht:disabled,
  .zeichnen:disabled {
    opacity: 0.45;
    cursor: default;
  }
  .zeichnen {
    padding: 0 16px;
    background: var(--text);
    color: var(--bg);
    font-weight: 600;
  }
  .zeichenzahl {
    display: inline-grid;
    place-items: center;
    min-width: 20px;
    height: 20px;
    padding: 0 5px;
    border-radius: 9px;
    background: var(--bg-erhoben);
    color: var(--text);
    font: 600 12px var(--schrift-fest, ui-monospace, monospace);
  }
  .winkel {
    transition: transform 0.15s;
  }
  .winkel.auf {
    transform: rotate(180deg);
  }
  .stilplatz {
    position: relative;
  }
  /* A list that opens upwards from its field: the styles, the modes. */
  .uplist {
    position: absolute;
    left: 0;
    bottom: calc(100% + 8px);
    display: flex;
    flex-direction: column;
    padding: 4px;
    box-shadow: inset 0 0 0 1px var(--glass-card-line), 0 8px 28px rgba(0, 0, 0, 0.14);
  }
  .uplist button {
    height: 32px;
    padding: 0 10px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text);
    font: 400 13px/18px var(--schrift);
    text-align: left;
    cursor: pointer;
  }
  .uplist button:hover,
  .uplist button.an {
    background: var(--glass-hover);
  }
  .stilliste {
    min-width: 220px;
  }
  /* As wide as its longest entry, and never narrower than its field. */
  .modelist {
    min-width: 100%;
  }
  .modelist button {
    white-space: nowrap;
  }
  .stilliste .trenner {
    height: 1px;
    margin: 4px 6px;
    background: var(--glass-card-line);
  }
</style>
