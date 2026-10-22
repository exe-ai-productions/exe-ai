<script>
  /* One row of a server window: two columns, 24 px apart, tops flush.

     Both columns are stretched to the taller one, and inside each column the
     sections share out what is left over (Serverabschnitt.svelte, `gewicht`),
     so the cards that stand side by side end on one line. A column in which
     no section carries a weight hands the extra height to its lowest section
     instead, so its last card reaches the foot of the column too; what
     stands in that card stays at the top. Under 900 px the two columns stand
     one under the other. */
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
  .spalte:not(:has(> :global(.abschnitt.weighted))) > :global(.abschnitt:last-child) {
    flex-grow: 1;
  }
  /* Its card grows, its rows do not: what stands in it stays at the top and
     the card's foot is the empty part. */
  .spalte:not(:has(> :global(.abschnitt.weighted))) > :global(.abschnitt:last-child .karte > .zeile) {
    flex-grow: 0;
  }
  @media (max-width: 900px) {
    .reihe {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
