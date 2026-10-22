<script>
  /* The language of the program: follow the device, or English, or German.
     The row shows the stored choice and nothing else, so a switch whose
     catalogue never arrives leaves it where it was. */
  import { t, texte } from '../../lib/texte.svelte.js'
  import { spracheStellen } from '../../lib/sprachwahl.svelte.js'
  import Group from '../parts/Group.svelte'
  import Pick from '../parts/Pick.svelte'

  const options = $derived([
    { value: 'auto', label: t('einstellungen.sprache_auto') },
    { value: 'en', label: t('einstellungen.sprache_englisch') },
    { value: 'de', label: t('einstellungen.sprache_deutsch') },
  ])
</script>

<Group>
  <Pick label={t('einstellungen.sprache')} value={texte.wahl} {options} onpick={spracheStellen} />
</Group>
