<script>
  /* A job's context reading, drawn as a hairline under the head of its
     tile — the running one and the finished report alike, one component in
     both places.

     Deliberately not the chat's context ring (ContextRing.svelte): a tile in
     a 260px rail reads a line better than a dial, and a colour that changes
     with the value reads as play rather than as a reading. So: 2px, rounded ends, one fixed colour — the green
     the chat's bar wears in its normal range — and the number at the end in
     the fixed face.

     `prozent` is the reading's own percentage, as the service wrote it into
     the run's `kontext` step (app/kontextverbrauch.py). Without one the
     component draws nothing: a run that has not reported yet, or one whose
     model does not say how large its window is, has no line to show.
     The number is written the way the house writes a percentage — the
     catalogue's one form for it, which the image progress reads too. */
  import { t } from '../lib/texte.svelte.js'

  let { prozent = null } = $props()

  const wert = $derived(
    typeof prozent === 'number' && Number.isFinite(prozent) ? prozent : null,
  )
  /* The bar cannot grow past its groove; the number can, and says so — a
     reading over 100 % is exactly what the line is there to show. */
  const breite = $derived(wert === null ? 0 : Math.max(0, Math.min(100, wert)))
</script>

{#if wert !== null}
  <div class="strich">
    <span class="rinne" aria-hidden="true">
      <span class="fuellung" style="width:{breite}%"></span>
    </span>
    <span class="zahl">{t('bild.fortschritt_prozent', { zahl: Math.round(wert) })}</span>
  </div>
{/if}

<style>
  /* Its own line under the head: it starts where the text of the head
     starts (10px padding, 11px chevron, 8px gap — Klappkachel.svelte) and
     runs to the tile's right edge, less the head's own 10px. The number
     stands right under the tile's control (Cancel, the cross); the 5px on
     top keep the head's own 8px between the two. */
  .strich {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 5px 10px 7px 29px;
  }
  /* A quiet groove under the fill. */
  .rinne {
    position: relative;
    flex: 1;
    min-width: 0;
    height: 2px;
    border-radius: 9px;
    background: color-mix(in srgb, var(--text-still) 22%, transparent);
    overflow: hidden;
  }
  .fuellung {
    position: absolute;
    inset: 0 auto 0 0;
    border-radius: 9px;
    background: var(--gruen);
    transition: width 0.5s cubic-bezier(0.3, 0.9, 0.3, 1);
  }
  /* A reading like the head's own value (Klappkachel.svelte `.wert`):
     fixed face, 10.5px, even digits. Five characters wide, so the line does
     not jump when the number grows a digit. */
  .zahl {
    flex: none;
    min-width: 5ch;
    text-align: right;
    font-family: var(--schrift-fest);
    font-size: 10.5px;
    line-height: 1.25;
    color: var(--text-still);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  @media (prefers-reduced-motion: reduce) {
    .fuellung { transition: none; }
  }
</style>
