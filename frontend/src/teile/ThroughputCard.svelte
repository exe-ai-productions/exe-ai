<script>
  /* The block "Performance" at the top of a server window: the tokens per
     second of the server now, their average over the last five minutes, and
     the course of the last minute as a line with a light area under it.

     The figures are the service's own reading of the server's counters
     (app/throughput.py); this block only asks for them every two seconds,
     and only while it stands in the open window. Where there is nothing to
     say — the server is off, or made no token in the last five minutes —
     both figures read "-" (the house's sign for nothing) and the line lies flat at the bottom. The line is
     drawn in the text colour, like every sign of the house. */
  import { api } from '../lib/api.js'
  import { formatNumber } from '../lib/numberDisplay.js'
  import { pollWithoutOverlap } from '../lib/pollWithoutOverlap.js'
  import { t, texte } from '../lib/texte.svelte.js'
  import Serverabschnitt from './Serverabschnitt.svelte'

  /* Which server: 'model', 'agent', 'cleanup' or 'speech'. */
  let { server } = $props()

  let werte = $state(null)

  /* A failed ask shows nothing instead of the last figures: numbers that stop
     moving read as a server that stands still. */
  async function laden() {
    try {
      werte = await api.serverThroughput(server)
    } catch (fehler) {
      werte = null
      throw fehler
    }
  }

  $effect(() => {
    laden().catch(() => {})
    return pollWithoutOverlap(laden, 2000)
  })

  const SLICES = 30
  const HEIGHT = 64
  /* The line never touches the top edge: its highest point stands 8 px below. */
  const TOP = 8
  const history = $derived(
    werte?.history?.length === SLICES ? werte.history : new Array(SLICES).fill(0),
  )
  const highest = $derived(Math.max(...history, 0))
  const points = $derived(
    history.map((v, i) => {
      const x = (i / (SLICES - 1)) * 100
      const y = highest > 0 ? HEIGHT - (v / highest) * (HEIGHT - TOP) : HEIGHT
      return `${x.toFixed(2)},${y.toFixed(2)}`
    }),
  )
  const line = $derived(`M${points.join(' L')}`)
  const area = $derived(`${line} L100,${HEIGHT} L0,${HEIGHT} Z`)

  function figure(wert) {
    return wert == null ? '-' : formatNumber(wert, 1, texte.sprache)
  }
</script>

<Serverabschnitt titel={t('throughput.heading')}>
  <div class="leistung">
    <div class="wert">
      <span class="metric-name">{t('throughput.title')}</span>
      <span class="zahl">
        <span class="gross">{figure(werte?.now)}</span>
        <span class="einheit">{t('throughput.unit')}</span>
      </span>
      <span class="schnitt">{t('throughput.average', { value: figure(werte?.average) })}</span>
    </div>
    <svg class="verlauf" viewBox="0 0 100 {HEIGHT}" preserveAspectRatio="none" aria-hidden="true">
      <path class="flaeche" d={area} />
      <path class="linie" d={line} />
    </svg>
  </div>
</Serverabschnitt>

<style>
  .leistung {
    box-sizing: border-box;
    min-height: 106px;
    padding: 17px;
    display: flex;
    align-items: center;
    gap: 28px;
    min-width: 0;
  }
  .wert {
    flex: none;
    width: 190px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }
  .metric-name {
    font-size: 12px;
    line-height: 15px;
    color: var(--text-leise);
  }
  .zahl {
    display: flex;
    align-items: baseline;
    gap: 6px;
  }
  .gross {
    font-size: 28px;
    line-height: 34px;
    font-weight: 400;
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .einheit {
    font-size: 12px;
    line-height: 15px;
    color: var(--text-leise);
  }
  .schnitt {
    font-size: 11px;
    line-height: 15px;
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
  }
  .verlauf {
    flex: 1;
    min-width: 0;
    height: 64px;
    display: block;
    color: var(--text-leise);
  }
  .linie {
    fill: none;
    stroke: currentColor;
    stroke-width: 1.5;
    stroke-linejoin: round;
    vector-effect: non-scaling-stroke;
  }
  .flaeche {
    fill: color-mix(in srgb, currentColor 12%, transparent);
    stroke: none;
  }
</style>
