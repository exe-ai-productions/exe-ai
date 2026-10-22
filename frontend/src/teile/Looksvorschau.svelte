<script>
  /* The small picture of one look: a window in miniature (lib/looksvorschau.js
     says what it is drawn with). "Auto" is two looks in one picture — Pearl on
     the left half, Exe on the right — as the device decides between them. */
  import { VORSCHAU, VORSCHAU_ZU_LOOK } from '../lib/looksvorschau.js'

  /* `look`: the choice the picture stands for. `eigen`: for the own
     gradient, `{ grund, hell }` as lib/looksvorschau.js `eigenVorschau`
     answers it. */
  let { look, eigen = null } = $props()

  const ebenen = $derived.by(() => {
    if (look === 'auto') {
      return [
        { ...VORSCHAU.snow, ausschnitt: 'inset(0 50% 0 0)' },
        { ...VORSCHAU.dunkel, ausschnitt: 'inset(0 0 0 50%)' },
      ]
    }
    if (look === 'eigen') {
      const satz = VORSCHAU[eigen?.hell ? 'eigen_hell' : 'eigen_dunkel']
      return [{ ...satz, grund: eigen?.grund ?? VORSCHAU.dunkel.grund }]
    }
    return [VORSCHAU[VORSCHAU_ZU_LOOK[look]] ?? VORSCHAU.dunkel]
  })
</script>

<div class="vorschau" aria-hidden="true">
  {#each ebenen as ebene, i (i)}
    <div
      class="ebene"
      style:background={ebene.grund}
      style:clip-path={ebene.ausschnitt}
      style:--tinte={ebene.tinte}
      style:--kachel={ebene.kachel}
      style:--eingabe={ebene.eingabe}
    >
      <span class="strich a"></span>
      <span class="strich b"></span>
      <span class="strich c"></span>
      <span class="strich d"></span>
      <span class="kachel"></span>
      <span class="nachricht"></span>
      <span class="zeile e"></span>
      <span class="zeile f"></span>
      <span class="eingabe"></span>
    </div>
  {/each}
</div>

<style>
  /* The picture is drawn on a canvas of 190 by 92 and scales with the card:
     every length is a number of canvas units (--u is one of them), so the
     picture keeps its proportions at any width the card has. */
  .vorschau {
    --u: calc(100cqw / 190);
    position: relative;
    aspect-ratio: 190 / 92;
    container-type: inline-size;
    border-radius: 6px;
    overflow: hidden;
  }
  .ebene {
    position: absolute;
    inset: 0;
  }
  .ebene span {
    position: absolute;
    display: block;
  }
  /* The column of lines at the left. */
  .strich {
    left: calc(8 * var(--u));
    height: calc(3 * var(--u));
    border-radius: calc(1.5 * var(--u));
    background: rgba(var(--tinte), 0.35);
  }
  .strich.a { top: calc(12 * var(--u)); width: calc(22 * var(--u)); }
  .strich.b { top: calc(20 * var(--u)); width: calc(16 * var(--u)); }
  .strich.c { top: calc(28 * var(--u)); width: calc(19 * var(--u)); }
  .strich.d { top: calc(36 * var(--u)); width: calc(14 * var(--u)); }
  .kachel {
    left: calc(40 * var(--u));
    right: calc(6 * var(--u));
    top: calc(6 * var(--u));
    height: calc(80 * var(--u));
    border-radius: calc(4 * var(--u));
    background: var(--kachel);
  }
  .nachricht {
    right: calc(16 * var(--u));
    top: calc(15 * var(--u));
    width: calc(50 * var(--u));
    height: calc(9 * var(--u));
    border-radius: calc(4 * var(--u));
    background: rgba(var(--tinte), 0.16);
  }
  .zeile {
    left: calc(52 * var(--u));
    height: calc(3 * var(--u));
    border-radius: calc(1.5 * var(--u));
    background: rgba(var(--tinte), 0.3);
  }
  .zeile.e { top: calc(34 * var(--u)); width: calc(120 * var(--u)); }
  .zeile.f { top: calc(43 * var(--u)); width: calc(92 * var(--u)); }
  .eingabe {
    left: calc(52 * var(--u));
    right: calc(18 * var(--u));
    top: calc(64 * var(--u));
    height: calc(13 * var(--u));
    border-radius: calc(4 * var(--u));
    background: var(--eingabe);
  }
</style>
