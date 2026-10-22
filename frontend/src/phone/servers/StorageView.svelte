<script>
  /* The places the program keeps its files — models, picture models,
     embedding models, pictures: where each one is, a button to show it on
     the machine and one to move it. */
  import { api } from '../../lib/api.js'
  import { t } from '../../lib/texte.svelte.js'
  import { melde } from '../../lib/zustand.svelte.js'
  import Speicherortzeile from '../../teile/Speicherortzeile.svelte'
  import SubHead from '../parts/SubHead.svelte'
  import Group from '../parts/Group.svelte'
  import Line from '../parts/Line.svelte'

  let { onback } = $props()

  let places = $state(null)

  /* What each location is called here: the server whose files it holds, or
     the thing itself. A location without a name in this list is not shown. */
  const TITLES = {
    models: 'modell.server',
    embedding_models: 'einbettungsserver.titel',
    speech_models: 'sprachserver.titel',
    image_models: 'bildserver.titel',
    images: 'bilder.bildordner',
    scripts: 'speicherorte.skripte_ordner',
  }

  $effect(() => {
    api
      .speicherorteLesen()
      .then((list) => (places = list))
      .catch((error) => melde(String(error.message || error), 'fehler'))
  })
</script>

<SubHead title={t('phone_models.storage_title')} {onback} />

<div class="places">
  {#each (places ?? []).filter((place) => TITLES[place.name]) as place (place.name)}
    <Group title={t(TITLES[place.name])}>
      <Speicherortzeile name={place.name} />
    </Group>
  {:else}
    {#if places}<Line label={t('modell.kein_modell_da')} />{/if}
  {/each}
</div>

<style>
  .places {
    --ordnerknopf: 40px;
  }
</style>
