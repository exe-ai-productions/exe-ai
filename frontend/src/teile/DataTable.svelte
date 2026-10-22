<script>
  /* Rows of text as a table: the first row is the head. A table file (CSV,
     TSV) and a sheet of a workbook are set the same way — one table, the
     values as text, never as markup. */
  let { rows = [] } = $props()
</script>

<table>
  <thead>
    <tr>{#each rows[0] || [] as cell}<th>{cell}</th>{/each}</tr>
  </thead>
  <tbody>
    {#each rows.slice(1) as row}
      <tr>{#each row as cell}<td>{cell}</td>{/each}</tr>
    {/each}
  </tbody>
</table>

<style>
  table { border-collapse: collapse; font-size: 12px; }
  th, td {
    border: 1px solid var(--linie);
    padding: 4px 8px;
    text-align: left;
    color: var(--text-leise);
  }
  th { color: var(--text); }
</style>
