<script>
  /* One row of a server window: two columns, 24 px apart, tops flush.

     Both columns are stretched to the taller one, and inside each column the
     sections share out what is left over (Serverabschnitt.svelte, `gewicht`),
     so the cards that stand side by side end on one line. Under 900 px the
     two columns stand one under the other. */
  let { links, rechts } = $props()
</script>

<div class="reihe">
  <div class="spalte">{@render links?.()}</div>
  <div class="spalte">{@render rechts?.()}</div>
</div>

<style>
  .reihe {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 28px 24px;
    align-items: stretch;
  }
  .spalte {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 28px;
  }
  @media (max-width: 900px) {
    .reihe {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
