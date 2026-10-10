<script>
  /* How full the context is, as a small ring beside the model's name.

     The ring fills with the share of the context the chat has used; the
     figures themselves stand in a card that comes up while the pointer
     rests on it. It shows only once the model has named its context size:
     with nothing to measure against there is nothing to fill. */
  import { kontextStand, zustand } from '../lib/zustand.svelte.js'
  import { t } from '../lib/texte.svelte.js'

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
</script>

{#if visible}
  <span class="ring" role="img" aria-label={figures}>
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
    stroke: var(--blau);
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
  .ring:hover .card { opacity: 1; transform: translate(-50%, 0); }
  b { color: var(--text); font-weight: 500; font-variant-numeric: tabular-nums; }
  .bar {
    display: block;
    height: 4px;
    margin-top: 8px;
    border-radius: 2px;
    background: var(--bg-hoch);
    overflow: hidden;
  }
  .bar i { display: block; height: 100%; background: var(--blau); }

  @media (prefers-reduced-motion: reduce) {
    .fill, .card { transition: none; }
  }
</style>
