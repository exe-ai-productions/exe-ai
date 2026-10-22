<script module>
  export const meta = { name: 'settings', title: 'menue.settings', sign: 'erscheinung', place: 'foot', order: 90 }
</script>

<script>
  /* The settings of the program on the phone: a list in the groups of the
     desktop's settings window, and a page behind each row with its own way
     back. The pages are the desktop's own parts where those stand alone
     (sounds, shortcuts, skills, schedules, connections, agents) and the
     phone's own where the desktop's page is a part of a larger window
     (language, look, the texts). */
  import { untrack } from 'svelte'
  import { t, texte } from '../../lib/texte.svelte.js'
  import { api } from '../../lib/api.js'
  import { frage } from '../../lib/zustand.svelte.js'
  import { klangwahl } from '../../lib/klaenge.svelte.js'
  import { handbuchOeffnen } from '../../lib/handbuch.js'
  import Hauszeichen from '../../teile/Hauszeichen.svelte'
  import Menuezeile from '../../teile/Menuezeile.svelte'
  import Updatezeile from '../../teile/Updatezeile.svelte'
  import Meldewahl from '../../teile/Meldewahl.svelte'
  import Shortcuts from '../../teile/Shortcuts.svelte'
  import Skillmaske from '../../teile/Skillmaske.svelte'
  import Verbindungen from '../../teile/Verbindungen.svelte'
  import Group from '../parts/Group.svelte'
  import SubHead from '../parts/SubHead.svelte'
  import { ENTRIES, GROUPS, TEXT_KINDS, shownLook } from '../settings.js'
  import { lookPick } from '../phone.svelte.js'
  import { pageOpen, pageLeave } from '../pages.svelte.js'
  import Language from '../settings/Language.svelte'
  import Look from '../settings/Look.svelte'
  import TextFile from '../settings/TextFile.svelte'
  import Agents from '../settings/Agents.svelte'
  import Cronjobs from '../settings/Cronjobs.svelte'

  /* The page standing: null for the list, else the name of an entry. */
  let at = $state(null)
  /* Whether the page standing holds something not yet saved. */
  let dirty = $state(false)

  const discard = () => frage(t('agenten.verwerfen_frage'))

  /* Leaving the page by its own back button or from the drawer asks the same
     question while something is unsaved. */
  $effect(() => {
    if (!dirty) return
    pageLeave.guard = discard
    return () => {
      if (pageLeave.guard === discard) pageLeave.guard = null
    }
  })

  async function back() {
    if (dirty && !(await discard())) return
    dirty = false
    at = null
    countsRead()
  }

  function open(key) {
    /* The tools have a page of their own on the phone, with the servers. */
    if (key === 'werkzeuge') {
      pageOpen('tools')
      return
    }
    dirty = false
    at = key
  }

  /* The live state behind the subtitles, read when the page opens. */
  let skills = $state({ total: 0, offered: 0 })
  let cron = $state({ total: 0, active: 0 })
  function countsRead() {
    api.skillsVerwaltung().then((list) => {
      skills = { total: list.length, offered: list.filter((entry) => entry.auto).length }
    }).catch(() => {})
    api.cronjobs().then((list) => {
      cron = { total: list.length, active: list.filter((entry) => entry.aktiv).length }
    }).catch(() => {})
  }
  $effect(() => {
    untrack(countsRead)
  })

  function sub(key) {
    switch (key) {
      case 'sprache':
        return t(texte.sprache === 'de' ? 'einstellungen.sprache_deutsch' : 'einstellungen.sprache_englisch')
      case 'meldungen':
        return t(klangwahl.aus ? 'einstellungen.toene_aus' : 'einstellungen.toene_an')
      case 'darstellung':
        return t('einstellungen.' + shownLook(lookPick.mode))
      case 'skills':
        return `${skills.offered}/${skills.total}`
      case 'cronjobs':
        return `${cron.active}/${cron.total}`
      default:
        return ''
    }
  }
</script>

{#if at}
  <SubHead title={t(ENTRIES[at].title)} onback={back} />
  <div class="view">
    {#if at === 'sprache'}
      <Language />
    {:else if at === 'darstellung'}
      <Look />
    {:else if at === 'meldungen'}
      <Meldewahl />
    {:else if at === 'shortcuts'}
      <Shortcuts />
    {:else if at === 'skills'}
      <Skillmaske />
    {:else if at === 'cronjobs'}
      <Cronjobs />
    {:else if at === 'agent'}
      <Agents bind:dirty />
    {:else if at === 'tools'}
      <Verbindungen zuWerkzeugen={() => pageOpen('tools')} />
    {:else if TEXT_KINDS.includes(at)}
      {#key at}<TextFile kind={at} bind:dirty />{/key}
    {/if}
  </div>
{:else}
  {#each GROUPS as group (group.name)}
    <Group title={t(group.title)}>
      {#each group.entries as key (key)}
        <Menuezeile titel={t(ENTRIES[key].title)} wert={sub(key)} onclick={() => open(key)}>
          {#snippet zeichen()}<Hauszeichen zeichen={ENTRIES[key].sign} groesse="gross" />{/snippet}
        </Menuezeile>
      {/each}
    </Group>
  {/each}
  <div class="apart">
    <Menuezeile titel={t('menue.hilfe')} onclick={handbuchOeffnen}>
      {#snippet zeichen()}<Hauszeichen zeichen="hilfe" groesse="gross" />{/snippet}
    </Menuezeile>
  </div>
  <Updatezeile />
{/if}

<style>
  .apart {
    margin-top: 18px;
  }
  .view {
    padding-bottom: 24px;
  }
</style>
