<script>
  /* Adding a cloud provider: which kind, then what that kind needs — the
     own server its name and address, every kind its key. The key leaves
     this page the moment it is saved. */
  import { api } from '../../lib/api.js'
  import { t } from '../../lib/texte.svelte.js'
  import { melde, modelleLaden } from '../../lib/zustand.svelte.js'
  import Pick from '../parts/Pick.svelte'
  import SubHead from '../parts/SubHead.svelte'
  import Group from '../parts/Group.svelte'
  import Field from '../parts/Field.svelte'
  import Action from '../parts/Action.svelte'
  import { providerReady } from '../cloud.js'

  let { onback, ondone } = $props()

  const KINDS = $derived([
    { value: 'anthropic', label: 'Anthropic' },
    { value: 'openai', label: 'OpenAI' },
    { value: 'eigen', label: t('modell.eigener') },
  ])

  let kind = $state('anthropic')
  let key = $state('')
  let id = $state('')
  let url = $state('')
  let busy = $state(false)

  const own = $derived(kind === 'eigen')
  const ready = $derived(providerReady(kind, { key, id, url }))

  async function connect() {
    busy = true
    try {
      const created = await api.anbieterHinzufuegen({
        art: kind,
        schluessel: key.trim(),
        kennung: own ? id.trim() : null,
        url: own ? url.trim() : null,
      })
      key = ''
      await modelleLaden(true)
      melde(
        created.erreichbar ? t('modell.anbieter_da') : created.hinweis || t('modell.anbieter_da_nicht_erreichbar'),
        created.erreichbar ? 'erfolg' : 'warnung',
      )
      ondone?.()
    } catch (error) {
      melde(error.message, 'fehler')
    } finally {
      busy = false
    }
  }
</script>

<SubHead title={t('modell.anbieter_hinzufuegen')} {onback} />

<Group>
  <Pick label={t('modell.anbieter_waehlen')} value={kind} options={KINDS} onpick={(value) => (kind = value)} />
  {#if own}
    <Field label={t('modell.eigener_name')} bind:value={id} />
    <Field label={t('modell.eigener_adresse')} bind:value={url} inputmode="url" />
  {/if}
  <Field label={t('modell.schluessel')} bind:value={key} secret />
</Group>

<Group>
  <Action label={t('modell.verbinden')} kind="primary" onclick={connect} disabled={!ready || busy} />
  <Action label={t('modell.abbrechen')} onclick={onback} />
</Group>
