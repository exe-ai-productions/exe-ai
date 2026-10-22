<script>
  /* One source of tools on a phone page: what it is, whether it answers,
     the tools of it that are on (each with its switch) and, for a server
     that offers more than it was asked for, the catalogue to pick from. */
  import { t } from '../../lib/texte.svelte.js'
  import { melde } from '../../lib/zustand.svelte.js'
  import { istAn, schalten, istGewaehlt, katalogSchalten } from '../../lib/werkzeuge.svelte.js'
  import Menuezeile from '../../teile/Menuezeile.svelte'
  import SubHead from '../parts/SubHead.svelte'
  import Group from '../parts/Group.svelte'
  import Line from '../parts/Line.svelte'
  import Toggle from '../parts/Toggle.svelte'

  let { source, title, quiet, dim, onback } = $props()

  async function guarded(work) {
    try {
      await work()
    } catch {
      melde(t('fehler.allgemein'), 'fehler')
    }
  }
</script>

<SubHead {title} {onback} />

<Group>
  <Menuezeile
    titel={quiet ? t(quiet) : t('status.erreichbar')}
    punkt={source.laeuft ? 'gruen' : dim ? 'gelb' : null}
  />
</Group>

{#if source.laeuft && source.werkzeuge.length}
  <Group title={t('werkzeuge.titel')}>
    {#each source.werkzeuge as tool (tool.name)}
      <Toggle
        label={tool.anzeige ?? tool.name}
        on={istAn(tool.name)}
        onswitch={() => guarded(() => schalten(tool.name, !istAn(tool.name)))}
      />
    {/each}
  </Group>
{:else}
  <Group><Line label={t('werkzeuge.gemeldet_zahl', { zahl: 0 })} /></Group>
{/if}

{#if source.katalog.length}
  <Group title={t('liste.katalog')}>
    <Line label={t('werkzeuge.von_zahl', { an: source.werkzeuge.length, gesamt: source.katalog.length })} />
    {#each source.katalog as entry (entry.id)}
      <Toggle
        label={entry.name}
        on={istGewaehlt(source.eintrag, entry.name)}
        onswitch={() => guarded(() => katalogSchalten(source.eintrag, entry.name, !istGewaehlt(source.eintrag, entry.name)))}
      />
    {/each}
  </Group>
{/if}
