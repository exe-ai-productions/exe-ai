<script>
  /* The page of the picture server: whether it runs, the model it starts
     with, one button to start or stop it, its protocol, and the program that
     draws — fetched when it is missing, updated or put back to the tested
     build by hand. */
  import { untrack } from 'svelte'
  import { api } from '../../lib/api.js'
  import { t } from '../../lib/texte.svelte.js'
  import { melde } from '../../lib/zustand.svelte.js'
  import Standpille from '../../teile/Standpille.svelte'
  import Menuezeile from '../../teile/Menuezeile.svelte'
  import Leuchtpunkt from '../../teile/Leuchtpunkt.svelte'
  import SubHead from '../parts/SubHead.svelte'
  import Group from '../parts/Group.svelte'
  import Line from '../parts/Line.svelte'
  import Pick from '../parts/Pick.svelte'
  import Action from '../parts/Action.svelte'
  import Log from '../parts/Log.svelte'
  import { serverRow } from '../servers.js'

  let { onback } = $props()

  let turbo = $state(null)
  let models = $state(null)
  let program = $state(null)
  let busy = $state(false)
  let logOpen = $state(false)
  let log = $state('')
  let lastError = null
  // Only the newest check may answer.
  let checkRun = 0
  let answer = $state(null)
  let checking = $state(false)

  const row = $derived(serverRow('image', turbo))
  const options = $derived((models?.modelle ?? []).map((name) => ({ value: name, label: name })))
  const chosen = $derived(models?.standardmodell ?? '')
  const hasProgram = $derived(Boolean(models?.programm_da))
  const fetching = $derived(Boolean(program) && !program.fertig && !program.fehler)

  async function read() {
    try {
      turbo = await api.turboStand()
      models = await api.bildmodelle()
      if (!hasProgram || fetching) program = await api.bildProgrammStand()
      if (logOpen) log = (await api.bildProtokoll()).join('\n')
      lastError = null
    } catch (error) {
      // Said once per streak: a failure that lasts would otherwise put a
      // notice on the screen at every beat.
      const text = String(error.message || error)
      if (text !== lastError) melde(text, 'fehler')
      lastError = text
    }
  }

  $effect(() => {
    read()
  })

  $effect(() => {
    const beat = setInterval(read, fetching || row.running ? 2000 : 6000)
    return () => clearInterval(beat)
  })

  async function choose(name) {
    try {
      await api.einstellungSetzen('global', 'bild_standardmodell', name)
      await read()
    } catch (error) {
      melde(String(error.message || error), 'fehler')
    }
  }

  async function toggle() {
    if (busy) return
    if (!row.running && !chosen) {
      melde(t('bildserver.kein_standardmodell'), 'fehler')
      return
    }
    busy = true
    try {
      turbo = row.running ? await api.turboStoppen() : await api.turboStarten(chosen)
    } catch (error) {
      melde(String(error.message || error), 'fehler')
    } finally {
      busy = false
    }
  }

  const take = (promise) =>
    promise.then((next) => (program = next)).catch((error) => melde(String(error.message || error), 'fehler'))

  async function check() {
    const run = ++checkRun
    checking = true
    answer = null
    try {
      const found = await api.bildProgrammAktualisierung()
      if (run === checkRun) {
        answer = found
        if (found.unreadable) melde(t('bildserver.updates_nicht_pruefbar'), 'fehler')
      }
    } catch (error) {
      if (run === checkRun) melde(String(error.message || error), 'fehler')
    } finally {
      if (run === checkRun) checking = false
    }
  }

  /* A fetch that ends clears the last answer — it spoke of the build before
     — and says so when it failed. */
  let before = false
  $effect(() => {
    if (before && !fetching) {
      answer = null
      checkRun += 1
      checking = false
      if (program?.fehler) melde(t('bildserver.generator_fehler'), 'fehler')
      untrack(read)
    }
    before = fetching
  })

  function toggleLog() {
    logOpen = !logOpen
    if (logOpen) api.bildProtokoll().then((lines) => (log = lines.join('\n'))).catch(() => {})
  }
</script>

<SubHead title={t('bildserver.titel')} {onback} />

<Group>
  <Menuezeile titel={t(row.word ?? 'status.inaktiv')} punkt={row.dot}>
    {#snippet rechts()}
      {#if row.running}<Standpille farbe={row.dot}>{t(row.word)}</Standpille>{/if}
    {/snippet}
  </Menuezeile>
</Group>

<Group>
  {#if options.length}
    <Pick label={t('bildserver.modell')} value={chosen} {options} disabled={row.running || busy} onpick={choose} />
  {:else if models}
    <Line label={t('bildserver.kein_modell_lang')} />
  {/if}
</Group>

<Group>
  <Action
    label={row.running ? t('modell.server_anhalten') : t('modell.server_starten')}
    kind={row.running ? '' : 'primary'}
    onclick={toggle}
    disabled={busy || Boolean(turbo?.picture_running) || (!row.running && !hasProgram)}
  />
</Group>

<Group>
  <Menuezeile titel={t('modell.protokoll')} onclick={toggleLog}>
    {#snippet rechts()}
      <Leuchtpunkt farbe={logOpen ? 'blau' : 'still'} groesse={9} />
    {/snippet}
  </Menuezeile>
  {#if logOpen}<Log text={log} />{/if}
</Group>

<Group title={t('bildserver.generator_holen')}>
  {#if fetching}
    <Line label={t('bildserver.generator_laedt')} value={`${Math.round(program.anteil * 100)} %`} />
  {:else if !hasProgram}
    {#if program?.fehler}<Line label={t('bildserver.generator_fehler')} />{/if}
    <Action label={t('bildserver.generator_holen')} kind="primary" onclick={() => take(api.bildProgrammHolen())} />
  {:else}
    <Line label={t('bildserver.version_zeile', { bau: models?.bau ?? '-' })} />
    {#if program?.fehler}<Line label={t('bildserver.generator_fehler')} />{/if}
    <Action label={t('bildserver.nach_updates_suchen')} onclick={check} disabled={checking} />
    {#if answer?.verfuegbar}
      <Action label={t('bildserver.generator_aktualisieren')} kind="primary" onclick={() => take(api.bildProgrammAktualisieren())} />
    {:else if answer?.aktuell}
      <Line label={t('bildserver.aktuell')} />
    {/if}
    {#if models?.restorable}
      <Action label={t('bildserver.restore_tested_build')} onclick={() => take(api.imageProgramRestore())} />
    {/if}
  {/if}
</Group>
