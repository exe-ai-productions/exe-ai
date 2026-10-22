<script>
  /* One cloud provider on a phone page: whether it answers, its key, the
     four things said by hand (images, tools, thinking, time limit), the
     context size, the models it offers and the way to remove it. */
  import { api } from '../../lib/api.js'
  import { t } from '../../lib/texte.svelte.js'
  import { frage, melde, modelleLaden } from '../../lib/zustand.svelte.js'
  import { istAn, schalten, katalogVon, katalogSchalten, istGewaehlt } from '../../lib/modelle.svelte.js'
  import Menuezeile from '../../teile/Menuezeile.svelte'
  import SubHead from '../parts/SubHead.svelte'
  import Group from '../parts/Group.svelte'
  import Line from '../parts/Line.svelte'
  import Field from '../parts/Field.svelte'
  import Toggle from '../parts/Toggle.svelte'
  import Action from '../parts/Action.svelte'
  import { contextValue, contextFound } from '../cloud.js'

  let { house, onback, onremoved } = $props()

  const catalogue = $derived(katalogVon(house.id))
  const found = $derived(contextFound(house))

  /* The typed context size is kept here and saved when the field is left —
     typing into a value that the next reload replaces is unusable. */
  let context = $state('')
  let contextFor = null
  $effect(() => {
    if (house.id === contextFor) return
    contextFor = house.id
    context = house.kontextEigen == null ? '' : String(house.kontextEigen)
  })

  async function guarded(work) {
    try {
      await work()
      await modelleLaden()
    } catch (error) {
      melde(String(error.message || error), 'fehler')
    }
  }

  const setCapability = (field) => () =>
    guarded(() => api.anbieterFaehigkeiten(house.id, field))

  const saveContext = () => {
    const value = contextValue(context)
    if (value === undefined) {
      context = house.kontextEigen == null ? '' : String(house.kontextEigen)
      return
    }
    if ((house.kontextEigen ?? null) === value) return
    guarded(() => api.anbieterKontext(house.id, value))
  }

  async function remove() {
    const question = house.key_goes_with_provider
      ? 'modell.anbieter_loeschen_frage_mit_schluessel'
      : 'modell.anbieter_loeschen_frage'
    const yes = await frage(t(question, { name: house.name }), {
      okSchluessel: 'modell.anbieter_entfernen',
    })
    if (!yes) return
    try {
      await api.anbieterLoeschen(house.id)
    } catch (error) {
      melde(String(error.message || error), 'fehler')
      return
    }
    melde(t('modell.anbieter_entfernt'), 'erfolg')
    onremoved?.()
    try {
      await modelleLaden(true)
    } catch (error) {
      melde(String(error.message || error), 'fehler')
    }
  }
</script>

<SubHead title={house.name} {onback} />

<Group>
  <Menuezeile
    titel={house.erreichbar ? t('status.erreichbar') : t('status.nicht_erreichbar')}
    punkt={house.erreichbar ? 'gruen' : null}
  />
  {#if !house.erreichbar && house.grund}
    <Line label={house.grund} />
  {/if}
</Group>

{#if house.schluessel_env}
  <Group title={t('modell.schluessel')}>
    <Menuezeile
      titel={house.schluessel_env}
      wert={house.schluessel_gesetzt ? t('modell.schluessel_gesetzt') : t('modell.schluessel_fehlt')}
      punkt={house.schluessel_gesetzt ? 'gruen' : 'rot'}
    />
  </Group>
{/if}

<Group title={t('modell.faehigkeiten')}>
  <Toggle label={t('modell.vision_schalter')} on={house.vision} onswitch={setCapability({ vision: !house.vision })} />
  <Toggle label={t('modell.werkzeuge_schalter')} on={house.werkzeuge} onswitch={setCapability({ tool_calls: !house.werkzeuge })} />
  <Toggle label={t('modell.denken_schalter')} on={house.denken} onswitch={setCapability({ thinking: !house.denken })} />
  <Toggle label={t('modell.zeitgrenze_schalter')} on={house.zeitgrenze} onswitch={() => guarded(() => api.anbieterZeitgrenze(house.id, !house.zeitgrenze))} />
  <Field label={t('modell.kontext_feld')} bind:value={context} inputmode="numeric" onchange={saveContext} />
  {#if !context && found}
    <Line label={t('modell.kontext_gefunden', { zahl: found })} />
  {/if}
</Group>

{#if house.modelle.length}
  <Group title={t('modell.feld_modell')}>
    {#each house.modelle as model (model.id)}
      <Toggle label={model.name} on={istAn(model.id)} onswitch={() => schalten(model.id, !istAn(model.id))} />
    {/each}
  </Group>
{/if}

{#if catalogue.length}
  <Group title={t('liste.katalog')}>
    {#each catalogue as model (model.id)}
      <Toggle
        label={model.name ?? model.modell}
        on={istGewaehlt(model)}
        disabled={Boolean(model.angeheftet)}
        onswitch={() => katalogSchalten(model, !istGewaehlt(model))}
      />
    {/each}
  </Group>
{/if}

<Group>
  <Action label={t('modell.anbieter_entfernen')} kind="danger" onclick={remove} />
</Group>
