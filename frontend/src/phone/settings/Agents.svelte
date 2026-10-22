<script>
  /* The agents: the list of them with the limits of the helpers above it,
     and the mask that makes or changes one. The list, the limits and the
     mask are the desktop's own parts; this page reads the files and hands
     them over. */
  import { untrack } from 'svelte'
  import { t } from '../../lib/texte.svelte.js'
  import { api } from '../../lib/api.js'
  import { melde, frage } from '../../lib/zustand.svelte.js'
  import { meldeText } from '../../lib/meldewesen.svelte.js'
  import { useSettingsValues } from '../../lib/settingsvalues.svelte.js'
  import SettingsAgents from '../../teile/SettingsAgents.svelte'
  import Agentenmaske from '../../teile/Agentenmaske.svelte'
  import Action from '../parts/Action.svelte'

  let { dirty = $bindable(false) } = $props()

  const values = useSettingsValues()
  let files = $state([])
  /* The mask standing: null, or { agent } with the agent's front matter
     (null for a new one). */
  let mask = $state(null)
  let maskChanged = $state(false)

  $effect(() => {
    dirty = Boolean(mask) && maskChanged
  })

  async function loadFiles() {
    try {
      files = await api.agentDateien()
    } catch {
      files = []
    }
  }
  $effect(() => {
    untrack(() => {
      loadFiles()
      values.helperLimitsLoad()
    })
  })

  /* Saved: the list is read again, so the agent stands in it at once. */
  async function done() {
    mask = null
    await loadFiles()
  }

  async function remove(name) {
    if (!(await frage(t('agenten.loeschen_frage', { name }), { danger: true, okSchluessel: 'agenten.delete_button' }))) return
    try {
      await api.agentLoeschen(name)
      meldeText('agenten.geloescht', { name }, 'erfolg')
      await loadFiles()
    } catch {
      melde(t('agenten.nicht_gesichert'), 'fehler')
    }
  }
</script>

{#if mask}
  <Agentenmaske agent={mask.agent} bind:geaendert={maskChanged} onfertig={done}
                onabbrechen={() => (mask = null)}
                onunlesbar={() => { mask = null; loadFiles() }} />
{:else}
  <Action label={t('agenten.neu_kurz')} onclick={() => (mask = { agent: null })} />
  <SettingsAgents dateien={files} helpersAtOnce={values.helpersAtOnce} helperSteps={values.helperSteps}
                  onbearbeiten={(agent) => (mask = { agent })} onloeschen={remove} />
{/if}
