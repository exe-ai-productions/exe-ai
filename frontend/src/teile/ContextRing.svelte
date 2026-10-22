<script>
  /* How full the context is, as a small ring beside the model's name.

     The ring fills with the share of the context the chat has used; the
     figures themselves stand in a card that comes up while the pointer
     rests on it or the keyboard's focus is on it. It shows only once the model has named its context size:
     with nothing to measure against there is nothing to fill.

     On a screen with no pointer (`tippbar`) the ring is a button of its own:
     a tap opens the figures in a small glass window under the head, a tap
     anywhere else shuts it. */
  import { kontextStand, zustand, aktuellesModell } from '../lib/zustand.svelte.js'
  import { t, texte } from '../lib/texte.svelte.js'

  let { tippbar = false } = $props()

  const reading = $derived(kontextStand())
  const visible = $derived(Boolean(zustand.modellId && reading.gesamt))

  /* The circle the arc runs on: radius 6 in a 16 grid, so the stroke keeps
     a pixel of air to the edge. */
  const RADIUS = 6
  const CIRCUMFERENCE = 2 * Math.PI * RADIUS
  const arc = $derived(((reading.anteil / 100) * CIRCUMFERENCE).toFixed(2))
  /* Never "0 %" once something is in the context: a sliver of one percent
     says "a little", a zero says "nothing", and the latter would be wrong. */
  const percent = $derived(reading.genutzt ? Math.max(1, Math.round(reading.anteil)) : 0)

  function short(number) {
    if (!number) return '0'
    return number >= 1000 ? Math.round(number / 1000) + 'k' : String(number)
  }
  const figures = $derived(
    t('kontext.auslastung', { genutzt: short(reading.genutzt), gesamt: short(reading.gesamt) }),
  )

  /* The tapped window carries the exact figures, as the model counts them. */
  const exact = (number) => Number(number).toLocaleString(texte.sprache)
  const exactFigures = $derived(
    t('kontext.auslastung', { genutzt: exact(reading.genutzt), gesamt: exact(reading.gesamt) }),
  )
  const modelName = $derived(aktuellesModell()?.name ?? '')
  /* Over four fifths the fill turns yellow: the context is running short. */
  const FULL = 80
  const nearlyFull = $derived(reading.anteil >= FULL)

  let open = $state(false)
  $effect(() => {
    if (!visible) open = false
  })
  function tapElsewhere(event) {
    if (open && !event.target.closest?.('.tippring, .pop')) open = false
  }
</script>

<svelte:window onpointerdown={tapElsewhere} onkeydown={(event) => event.key === 'Escape' && (open = false)} />

{#if visible && tippbar}
  <button class="tippring" aria-label={figures} aria-expanded={open} aria-haspopup="dialog"
          onclick={() => (open = !open)}>
    <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
      <circle class="track" cx="12" cy="12" r="9.5" />
      {#if reading.genutzt}
        <circle class="fill" class:voll={nearlyFull} cx="12" cy="12" r="9.5"
                stroke-dasharray="{((reading.anteil / 100) * 59.69).toFixed(2)} 59.69" />
      {/if}
    </svg>
  </button>
  {#if open}
    <div class="pop" role="dialog" aria-label={t('modell.kontext')}>
      <b>{t('modell.kontext')} {percent} %</b>
      <span class="bar"><i style:width="{reading.genutzt ? Math.max(1, reading.anteil) : 0}%"></i></span>
      <span class="zahlen">{exactFigures}{modelName ? ` · ${modelName}` : ''}</span>
    </div>
  {/if}
{:else if visible}
  <!-- Reachable by key: with the focus the card shows what the pointer
       shows. -->
  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <span class="ring" role="img" aria-label={figures} tabindex="0">
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <circle class="track" cx="8" cy="8" r={RADIUS} />
      <!-- An empty context draws no arc: a round cap on a zero-length dash
           would still paint a dot. -->
      {#if reading.genutzt}
        <circle class="fill" cx="8" cy="8" r={RADIUS}
                stroke-dasharray="{arc} {CIRCUMFERENCE.toFixed(2)}" />
      {/if}
    </svg>
    <span class="card">
      {t('modell.kontext')} <b>{figures}</b> · {percent} %
      <span class="bar"><i style:width="{reading.genutzt ? Math.max(1, reading.anteil) : 0}%"></i></span>
    </span>
  </span>
{/if}

<style>
  .ring {
    position: relative;
    display: inline-flex;
    align-items: center;
    padding: 0 3px;
    flex: none;
  }
  /* Starts at twelve o'clock, like every dial. */
  svg { transform: rotate(-90deg); }
  circle { fill: none; stroke-width: 2.4; }
  .track { stroke: var(--indicator-empty); }
  .fill {
    stroke: var(--text);
    stroke-linecap: round;
    transition: stroke-dasharray 0.5s cubic-bezier(0.3, 0.9, 0.3, 1);
  }

  /* Above the ring, centred on it, and only while the pointer rests there. */
  .card {
    position: absolute;
    bottom: calc(100% + 14px);
    left: 50%;
    transform: translate(-50%, 4px);
    background: var(--bg-erhoben);
    border-radius: 9px;
    box-shadow: 0 0 0 1px var(--linie), 0 16px 36px -8px rgba(0, 0, 0, 0.5);
    padding: 10px 12px;
    font-size: 12px;
    color: var(--text-leise);
    white-space: nowrap;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.15s, transform 0.15s;
    z-index: 7;
  }
  .ring:hover .card,
  .ring:focus-visible .card { opacity: 1; transform: translate(-50%, 0); }
  .ring:focus-visible { outline: 2px solid var(--linie-stark); outline-offset: -2px; border-radius: 9px; }
  b { color: var(--text); font-weight: 500; font-variant-numeric: tabular-nums; }
  .bar {
    display: block;
    height: 4px;
    margin-top: 8px;
    border-radius: 2px;
    background: var(--bg-hoch);
    overflow: hidden;
  }
  .bar i { display: block; height: 100%; background: var(--text); }

  /* The tapped ring: a button of the head's own size, the ring a little
     larger, filled in the text colour (yellow when it runs short). */
  .tippring {
    flex: none;
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    padding: 0;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--text);
  }
  .tippring:active { background: var(--bg-hoch); }
  .tippring circle { stroke-width: 2.6; }
  .tippring .fill { stroke: var(--text); }
  .tippring .fill.voll { stroke: var(--gelb); }
  .pop {
    position: fixed;
    top: calc(env(safe-area-inset-top) + 54px);
    right: 10px;
    z-index: 45;
    display: flex;
    flex-direction: column;
    gap: 2px;
    width: min(240px, calc(100vw - 20px));
    padding: 10px 12px;
    border-radius: 9px;
    background: var(--glass-dropdown);
    -webkit-backdrop-filter: blur(16px);
    backdrop-filter: blur(16px);
    box-shadow: 0 0 0 1px var(--glass-button-edge), 0 18px 40px -8px rgba(0, 0, 0, 0.55);
    color: var(--text-leise);
    font-size: 12px;
    line-height: 1.5;
  }
  .pop .zahlen { font-variant-numeric: tabular-nums; }
  .pop .bar i { background: var(--text); }

  @media (prefers-reduced-motion: reduce) {
    .fill, .card { transition: none; }
  }
</style>
