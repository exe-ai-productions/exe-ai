<script>
  /* The foot of the studio on the phone: one row of four equal fields — the
     size, the style, the negative prompt, the mask — and under it one line:
     the picture to start from, the prompt, "Improve" and "Draw". A field
     opens exactly the choice it names, as a sheet; the mask opens its page.
     A value that is set wears a dot. */
  import { api } from '../../lib/api.js'
  import {
    auswahl, pictureMissing, stileLaden, stilVon, surface, werte,
  } from '../../lib/studio.svelte.js'
  import { studioZeichnen, zeichnung } from '../../lib/studiozeichnen.svelte.js'
  import { t } from '../../lib/texte.svelte.js'
  import { melde, zustand } from '../../lib/zustand.svelte.js'
  import Hauszeichen from '../../teile/Hauszeichen.svelte'
  import MaskenZeichen from '../../teile/MaskenZeichen.svelte'
  import Sheets from './Sheets.svelte'
  import { sizeLabel } from './format.js'
  import { chooseFile } from './upload.js'

  /* `onmask()`: the way into the mask page. */
  let { onmask } = $props()

  stileLaden()

  let sheet = $state('')

  const styleSet = $derived(Boolean(stilVon(werte.stil)))
  const maskSet = $derived(surface.maskOn && surface.masked)

  // --- the prompt -----------------------------------------------------------

  let field = $state(null)
  /* The field grows with what is typed, up to four lines. */
  function grow() {
    if (!field) return
    field.style.height = 'auto'
    field.style.height = `${Math.min(field.scrollHeight, 88)}px`
  }
  $effect(() => {
    void werte.prompt
    grow()
  })

  /* "Improve": the prompt preparation of the picture server rewrites the
     prompt for the model's family and is told the name of the chosen style.
     One step back, for both fields, and no more. */
  let improving = $state(false)
  let before = $state(null)
  const canImprove = $derived(!improving && Boolean(werte.prompt.trim()))
  async function improve() {
    if (!canImprove) return
    improving = true
    const old = { prompt: werte.prompt, negativ: werte.negativ }
    try {
      const answer = await api.bildPromptVerbessern({
        prompt: werte.prompt,
        negativ: werte.negativ,
        modell: werte.modell,
        familie: werte.familie || auswahl.klasse,
        cfg: Number(werte.cfg),
        stil: stilVon(werte.stil)?.name ?? '',
      })
      werte.prompt = answer.prompt
      if (answer.negativ) werte.negativ = answer.negativ
      before = old
    } catch (error) {
      melde(String(error.message || error), 'fehler')
    } finally {
      improving = false
    }
  }
  function undoImprove() {
    if (!before) return
    werte.prompt = before.prompt
    werte.negativ = before.negativ
    before = null
  }

  /* A kind that draws from a picture rests while none is there; the draw
     itself refuses it as well, whichever way it is asked. */
  const noPicture = $derived(pictureMissing())
  const canDraw = $derived(
    Boolean(werte.prompt.trim()) && !zeichnung.bereitet && Boolean(zeichnung.losZeichnen) && !noPicture,
  )
</script>

<div class="foot">
  <div class="chips" role="group">
    <button class="chip" onclick={() => (sheet = 'size')}>{sizeLabel(werte.breite, werte.hoehe)}</button>
    <button class="chip" onclick={() => (sheet = 'style')}>
      {t('studio.stil')}{#if styleSet}<i class="dot"></i>{/if}
    </button>
    <button class="chip" onclick={() => (sheet = 'negative')}>
      {t('studio.negativ')}{#if werte.negativ.trim()}<i class="dot"></i>{/if}
    </button>
    <button class="chip" disabled={!werte.startbild} onclick={() => onmask?.()}>
      {t('studio.maske')}{#if maskSet}<i class="dot"></i>{/if}
    </button>
  </div>

  <div class="bar" role="group" aria-label={t('bild.prompt')}>
    <button class="round" onclick={chooseFile} aria-label={t('bild.startbild')}>
      <Hauszeichen zeichen="bild" groesse={20} />
    </button>
    <textarea
      rows="1"
      bind:this={field}
      bind:value={werte.prompt}
      oninput={grow}
      aria-label={t('bild.prompt')}
    ></textarea>
    {#if before}
      <button class="round" onclick={undoImprove} aria-label={t('bild.verbessern_zurueck')}>
        <MaskenZeichen name="zurueck" groesse={18} />
      </button>
    {/if}
    <button class="round" disabled={!canImprove} onclick={improve} aria-label={t('bild.verbessern')}>
      <!-- The catalogue's sparkle star, as the drawing has it. -->
      <svg width="20" height="20" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-linecap="round"
           stroke-linejoin="round" aria-hidden="true">
        <path d="M28 14 L32.5 27.5 L46 32 L32.5 36.5 L28 50 L23.5 36.5 L10 32 L23.5 27.5 Z" stroke-width="5" />
        <path d="M50 10 V22 M44 16 H56" stroke-width="4.5" />
      </svg>
    </button>
    <button class="draw" disabled={!canDraw} onclick={() => studioZeichnen()}>
      {#if zustand.bildWarteschlange > 1}<span class="count">{zustand.bildWarteschlange}</span>{/if}
      <MaskenZeichen name="pinsel" groesse={16} />
      {t('bild.erzeugen')}
    </button>
  </div>
</div>

<Sheets which={sheet} onclose={() => (sheet = '')} />

<style>
  .foot {
    flex: none;
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 6px calc(10px + env(safe-area-inset-right)) calc(8px + env(safe-area-inset-bottom))
      calc(10px + env(safe-area-inset-left));
  }
  /* Four equal fields on one line, one height. */
  .chips {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 6px;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    height: var(--feld-hoehe, 32px);
    min-width: 0;
    padding: 0 6px;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
    font: 500 13px var(--schrift);
    white-space: nowrap;
    overflow: hidden;
  }
  /* Under the keyboard there is no home bar to keep clear of. */
  :global([data-keyboard]) .foot {
    padding-bottom: 8px;
  }
  .chip:disabled {
    color: var(--text-still);
    opacity: 0.6;
  }
  .dot {
    flex: none;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--text);
  }
  .bar {
    display: flex;
    align-items: flex-end;
    gap: 4px;
    min-height: 52px;
    box-sizing: border-box;
    padding: 6px;
    border-radius: 9px;
    background: var(--kachel-eingabe, var(--bg-erhoben));
    box-shadow: 0 14px 34px -14px rgba(0, 0, 0, 0.55), 0 2px 6px -2px rgba(0, 0, 0, 0.25);
  }
  .round {
    flex: none;
    width: 40px;
    height: 40px;
    display: grid;
    place-items: center;
    padding: 0;
    border: none;
    border-radius: 50%;
    background: transparent;
    color: var(--text-leise);
  }
  .round:active {
    background: var(--bg-hoch);
    color: var(--text);
  }
  .round:disabled {
    opacity: 0.4;
  }
  textarea {
    flex: 1;
    min-width: 0;
    max-height: 88px;
    padding: 9px 4px;
    border: none;
    outline: none;
    resize: none;
    background: none;
    color: var(--text);
    /* 16 px: a smaller field makes the page zoom when it takes the focus. */
    font: 400 16px/22px var(--schrift);
    overflow-y: auto;
  }
  /* The one full button: the text colour turned into a ground. */
  .draw {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 40px;
    padding: 0 14px 0 12px;
    border: none;
    border-radius: 9px;
    background: var(--text);
    color: var(--bg);
    font: 600 14px var(--schrift);
  }
  .draw:disabled {
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text-still);
  }
  .count {
    min-width: 16px;
    padding: 0 4px;
    border-radius: 99px;
    background: var(--bg);
    color: var(--text);
    font: 600 11px/16px var(--schrift);
    text-align: center;
  }
</style>
