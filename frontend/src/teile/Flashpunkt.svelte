<!-- Flash attention at a glance: a filled dot and one word, left of the
     server readout in the header. It is never switched here and never was —
     the server decides by itself whether it can use it, and this line only
     reports what it actually does. Grey while nothing runs (there is nothing
     to report yet), green while it is on, red while a running server does
     without it: that is the one case worth seeing, because it costs speed.

     Its own component beside `Serverpunkt.svelte`, and it stays its own: the
     two stand next to each other because they show different things.

     What the two DO share is where the answer comes from. Both used to
     fetch `/runner` every five seconds; the service announces its state now
     and both read it out of `serverzustand.svelte.js`. Neither fetches
     anything: the one ask a window still needs belongs to the line itself
     (`verbinden`, lib/ereignisstrom.svelte.js). -->
<script>
  import Leuchtpunkt from './Leuchtpunkt.svelte'
  import { serverzustand } from '../lib/serverzustand.svelte.js'
  import { t } from '../lib/texte.svelte.js'

  /* One mapping decides dot AND word — two separate ternary chains would
     drift apart on exactly the case that matters. */
  const lage = $derived(
    !serverzustand.laeuft || serverzustand.flash_aktiv == null
      ? { punkt: 'still', wort: 'modell.flash_unbekannt' }
      : serverzustand.flash_aktiv
        ? { punkt: 'gruen', wort: 'modell.flash_aktiv' }
        : { punkt: 'rot', wort: 'modell.flash_inaktiv' },
  )
</script>

<span class="gruppe" title={t(lage.wort)}>
  <Leuchtpunkt farbe={lage.punkt} groesse={9} />
  <span class="wort">{t('modell.feld_flash')}</span>
</span>

<style>
  .gruppe {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    min-width: 0;
  }
  .wort {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
  }
</style>
