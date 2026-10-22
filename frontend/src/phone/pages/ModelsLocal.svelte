<script module>
  export const meta = { name: 'models-local', title: 'menue.lokal', sign: 'server', place: 'list', order: 31 }
</script>

<script>
  /* The models that run on this machine, on the phone: the list of its
     servers with their state, the quick picker, the settings of each model
     and the places the files are kept. A tap on a server opens its page. */
  import { t } from '../../lib/texte.svelte.js'
  import { lokale, istAn, schalten, auswahlLaden } from '../../lib/modelle.svelte.js'
  import { api } from '../../lib/api.js'
  import Menuezeile from '../../teile/Menuezeile.svelte'
  import Hauszeichen from '../../teile/Hauszeichen.svelte'
  import Group from '../parts/Group.svelte'
  import Toggle from '../parts/Toggle.svelte'
  import ServerView from '../servers/ServerView.svelte'
  import ImageServerView from '../servers/ImageServerView.svelte'
  import StorageView from '../servers/StorageView.svelte'
  import ModelParams from '../servers/ModelParams.svelte'
  import { DRIVERS } from '../servers/drivers.js'
  import { SERVERS, serverRow } from '../servers.js'

  /* The view inside the page: the list, a server, the places or the
     settings of one model. */
  let view = $state({ at: 'list', id: null })
  const toList = () => (view = { at: 'list', id: null })

  /* What each server last said about itself; empty until it answers, and
     left as it was when a reading fails. */
  let reports = $state({})

  async function readAll() {
    await Promise.all(
      SERVERS.map(async (server) => {
        try {
          reports[server.kind] =
            server.kind === 'image' ? await api.turboStand() : await DRIVERS[server.kind].report()
        } catch {
          // A server that does not answer keeps its last state on the list.
        }
      }),
    )
  }

  $effect(() => {
    if (view.at !== 'list') return
    auswahlLaden()
    readAll()
    const beat = setInterval(readAll, 6000)
    return () => clearInterval(beat)
  })

  const models = $derived(lokale())
  const shown = $derived(models.find((model) => model.id === view.id) ?? null)
</script>

{#if view.at === 'server'}
  {#if view.id === 'image'}
    <ImageServerView onback={toList} />
  {:else}
    <ServerView kind={view.id} onback={toList} />
  {/if}
{:else if view.at === 'storage'}
  <StorageView onback={toList} />
{:else if view.at === 'params' && shown}
  <ModelParams model={shown} onback={toList} />
{:else}
  <Group title={t('modell.einrichten')}>
    {#each SERVERS as server (server.kind)}
      {@const row = serverRow(server.kind, reports[server.kind])}
      <Menuezeile
        titel={t(server.title)}
        wert={row.running ? (row.model ?? '') : ''}
        punkt={row.dot}
        onclick={() => (view = { at: 'server', id: server.kind })}
      >
        {#snippet zeichen()}<Hauszeichen zeichen={server.sign} groesse="gross" />{/snippet}
      </Menuezeile>
    {/each}
  </Group>

  {#if models.length}
    <Group title={t('modell.schnellwahl_titel')}>
      {#each models as model (model.id)}
        <Toggle label={model.name} on={istAn(model.id)} onswitch={() => schalten(model.id, !istAn(model.id))} />
      {/each}
    </Group>

    <Group title={t('parameter.titel')}>
      {#each models as model (model.id)}
        <Menuezeile titel={model.name} onclick={() => (view = { at: 'params', id: model.id })} />
      {/each}
    </Group>
  {/if}

  <Group>
    <Menuezeile titel={t('phone_models.storage_title')} onclick={() => (view = { at: 'storage', id: null })}>
      {#snippet zeichen()}<Hauszeichen zeichen="ordner" groesse="gross" />{/snippet}
    </Menuezeile>
  </Group>
{/if}
