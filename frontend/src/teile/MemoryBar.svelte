<script>
  /* The memory the system keeps resident, as one bar with its figures:
     "Wired Memory · x GB of y GB". It is the part a loaded model's weights
     live in, which is why it stands in the head of the local models and not
     the sum of everything in use (that one stays in the header's pill).

     `wired` and `total` are gigabytes or null. A platform that has no wired
     figure (it exists on macOS only) shows a dash in its place and still
     the machine's total, with an empty bar; with neither there is only the
     dash. Never a guess. The decimal sign follows the language.

     `inline`: the bar of the server overview — the name, the track and the
     figures in one line, without the sign. */
  import { t, texte } from '../lib/texte.svelte.js'
  import { formatNumber } from '../lib/numberDisplay.js'
  import Hauszeichen from './Hauszeichen.svelte'

  let { wired = null, total = null, inline = false } = $props()

  const known = $derived(wired !== null && wired !== undefined && Boolean(total))
  const share = $derived(known ? Math.min(100, Math.max(0, (wired / total) * 100)) : 0)
  const figures = $derived(
    total
      ? t('modell.wired_von', {
          wired: known ? formatNumber(wired, 1, texte.sprache) : '-',
          total: formatNumber(total, 1, texte.sprache),
        })
      : '-',
  )
</script>

{#if inline}
  <div class="bar inline" role="group" aria-label={t('modell.wired_label')}>
    <span class="label">{t('modell.wired_label')}</span>
    <div class="track" role={known ? 'progressbar' : null} aria-hidden={known ? null : 'true'}
         aria-valuemin={known ? 0 : null} aria-valuemax={known ? 100 : null}
         aria-valuenow={known ? Math.round(share) : null} aria-label={known ? t('modell.wired_label') : null}>
      <i style:width="{share}%"></i>
    </div>
    <span class="figures">{figures}</span>
  </div>
{:else}
<div class="bar" role="group" aria-label={t('modell.wired_label')}>
  <span class="sign"><Hauszeichen zeichen="chip_bolt" groesse="klein" /></span>
  <div class="middle">
    <div class="line"><span>{t('modell.wired_label')}</span><span class="dot" aria-hidden="true">·</span><span class="figures">{figures}</span></div>
    <!-- Without a value the track is only a line: nothing to announce. -->
    <div class="track" role={known ? 'progressbar' : null} aria-hidden={known ? null : 'true'}
         aria-valuemin={known ? 0 : null} aria-valuemax={known ? 100 : null}
         aria-valuenow={known ? Math.round(share) : null} aria-label={known ? t('modell.wired_label') : null}>
      <i style:width="{share}%"></i>
    </div>
  </div>
</div>
{/if}

<style>
  .bar {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 190px;
    color: var(--text-leise);
  }
  /* The sign stands on the line of the name, not between the name and the
     track: it is the sign of the name. It sits in a box as high as one line
     of the name (`1lh`), so the two stay together whatever the type size. */
  .bar:not(.inline) {
    align-items: flex-start;
    font-size: 12.5px;
    line-height: 1.4;
  }
  .sign {
    flex: none;
    display: inline-flex;
    align-items: center;
    height: 1lh;
  }
  .middle {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .line {
    display: flex;
    align-items: baseline;
    gap: 6px;
    height: 1lh;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .dot {
    color: var(--text-still);
  }
  .figures {
    color: var(--text);
  }
  /* The track and its fill, round at both ends like every bar of the
     program; the fill keeps the quiet reading colour, memory is a fact and
     no state. */
  /* One line: the name, the track filling what is left, the figures. */
  .inline {
    gap: 16px;
    font-size: 12.5px;
    font-variant-numeric: tabular-nums;
  }
  .inline .track {
    flex: 1;
    min-width: 0;
  }
  .inline .figures {
    white-space: nowrap;
  }
  .track {
    height: 4px;
    border-radius: 9px;
    background: var(--bg-hoch);
    overflow: hidden;
  }
  .track i {
    display: block;
    height: 100%;
    border-radius: 9px;
    background: var(--text-leise);
  }
</style>
