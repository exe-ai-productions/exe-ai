<script module>
  export const meta = { name: 'models-cloud', title: 'menue.cloud', sign: 'wolke', place: 'list', order: 32 }
</script>

<script>
  /* The cloud providers on the phone: the list of what is connected, a page
     for each provider and the page that adds one. */
  import { t } from '../../lib/texte.svelte.js'
  import { zustand } from '../../lib/zustand.svelte.js'
  import { anbieterAlle, alleAnbieterLaden, auswahlLaden } from '../../lib/modelle.svelte.js'
  import Menuezeile from '../../teile/Menuezeile.svelte'
  import Hauszeichen from '../../teile/Hauszeichen.svelte'
  import Group from '../parts/Group.svelte'
  import Line from '../parts/Line.svelte'
  import ProviderView from '../cloud/ProviderView.svelte'
  import AddProvider from '../cloud/AddProvider.svelte'

  /* The view inside the page: the list, one provider (by id) or the form. */
  let view = $state({ at: 'list', id: null })

  const houses = $derived(anbieterAlle())
  const shown = $derived(houses.find((house) => house.id === view.id) ?? null)

  /* The full list, the unreachable providers too, is read when the page
     opens and whenever the chat's list was read anew. */
  $effect(() => {
    auswahlLaden()
  })
  $effect(() => {
    void zustand.modelle
    alleAnbieterLaden()
  })

  const toList = () => (view = { at: 'list', id: null })
</script>

{#if view.at === 'add'}
  <AddProvider onback={toList} ondone={toList} />
{:else if view.at === 'house' && shown}
  <ProviderView house={shown} onback={toList} onremoved={toList} />
{:else}
  <Group title={t('modell.cloud_titel')}>
    {#each houses as house (house.id)}
      <Menuezeile
        titel={house.name}
        wert={house.schluessel_env && !house.schluessel_gesetzt
          ? t('modell.schluessel_fehlt')
          : house.erreichbar
            ? t('modell.von_zahl', { gewaehlt: house.modelle.length, gesamt: house.katalog })
            : ''}
        punkt={house.erreichbar ? 'gruen' : null}
        onclick={() => (view = { at: 'house', id: house.id })}
      >
        {#snippet zeichen()}<Hauszeichen zeichen="server" groesse="gross" />{/snippet}
      </Menuezeile>
    {:else}
      <Line label={t('modell.kein_anbieter_kurz')} />
    {/each}
    <Menuezeile titel={t('modell.anbieter_hinzufuegen')} onclick={() => (view = { at: 'add', id: null })}>
      {#snippet zeichen()}<Hauszeichen zeichen="plus" groesse="gross" />{/snippet}
    </Menuezeile>
  </Group>
{/if}
