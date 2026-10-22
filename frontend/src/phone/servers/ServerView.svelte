<script>
  /* The page of one server that runs a model with llama.cpp — the model
     server, the agent server, the embedding server, the speech server and
     the clean-up server: its state, the file it starts from, its numbers,
     one button to start or stop it, and its protocol.

     It asks the server for its report while it stands: every two seconds
     while a process runs or a start was just pressed, slower otherwise.
     What it reads is the report the desktop page reads; the numbers are
     only filled in from it, never written back until a start. */
  import { t } from '../../lib/texte.svelte.js'
  import { melde, modelleLaden } from '../../lib/zustand.svelte.js'
  import Leuchtpunkt from '../../teile/Leuchtpunkt.svelte'
  import SubHead from '../parts/SubHead.svelte'
  import Group from '../parts/Group.svelte'
  import Line from '../parts/Line.svelte'
  import Pick from '../parts/Pick.svelte'
  import Field from '../parts/Field.svelte'
  import Action from '../parts/Action.svelte'
  import Log from '../parts/Log.svelte'
  import Menuezeile from '../../teile/Menuezeile.svelte'
  import ProgramSection from './ProgramSection.svelte'
  import SpeechSettings from './SpeechSettings.svelte'
  import { DRIVERS, numberTitle, seedNumbers } from './drivers.js'
  import { SERVERS, serverRow, modelOptions, startModel, gbLabel } from '../servers.js'

  /* The program every server of this page starts: a product name. */
  const PROGRAM = 'llama.cpp'

  let { kind, onback } = $props()

  const driver = $derived(DRIVERS[kind])
  // The port is the one number that belongs to the network; the rest decide what a run costs.
  const memoryFields = $derived(driver.fields.filter((name) => name !== 'port'))
  const usedMemory = $derived(row.running && report?.belegt_gb != null ? gbLabel(report.belegt_gb) : '')
  const meta = $derived(SERVERS.find((server) => server.kind === kind))

  let report = $state(null)
  let picked = $state('')
  let numbers = $state({})
  let log = $state('')
  let busy = $state(false)
  let logOpen = $state(false)
  let seeded = false
  let lastError = null

  const row = $derived(serverRow(kind, report))
  const options = $derived(
    modelOptions(report).map((option) => ({ ...option, detail: gbLabel(option.gb) })),
  )
  let remembered = $state(null)
  const model = $derived(startModel(report, picked, remembered))

  const projector = $derived(report?.projektoren?.[model] ?? null)

  let wasRunning = false

  async function read() {
    try {
      if (driver.load) {
        await driver.load()
        remembered = driver.remembered?.() || null
      }
      report = await driver.report()
      /* A run that ended hands the fields back to the stored choice: they
         held the numbers it ran with. */
      if (wasRunning && !report.laeuft) seeded = false
      wasRunning = Boolean(report.laeuft)
      /* The fields take the report's numbers once, and again while a
         process runs — a run's numbers are what it was started with. */
      if (!seeded || report.laeuft) {
        numbers = seedNumbers(kind, report)
        seeded = true
      }
      if (report.laeuft && report.modell) picked = report.modell
      if (logOpen) log = (await driver.log()).join('\n')
      lastError = null
    } catch (error) {
      /* Said once per streak: a failure that lasts would otherwise put a
         notice on the screen at every beat. */
      if (error.message !== lastError) melde(error.message, 'fehler')
      lastError = error.message
    }
  }

  $effect(() => {
    void kind
    seeded = false
    wasRunning = false
    report = null
    log = ''
    read()
  })

  $effect(() => {
    void logOpen
    if (logOpen) driver.log().then((lines) => (log = lines.join('\n'))).catch(() => {})
  })

  $effect(() => {
    const beat = setInterval(read, report?.laeuft || busy ? 2000 : 6000)
    return () => clearInterval(beat)
  })

  async function start() {
    if (!model) return
    busy = true
    try {
      await driver.start(model, numbers, report)
      logOpen = true
      await read()
      if (kind === 'model') await modelleLaden(true)
    } catch (error) {
      melde(error.message, 'fehler')
    } finally {
      busy = false
    }
  }

  async function stop() {
    busy = true
    try {
      await driver.stop()
      await read()
      if (kind === 'model') await modelleLaden()
    } catch (error) {
      melde(error.message, 'fehler')
    } finally {
      busy = false
    }
  }

  function showFolder() {
    driver.folder?.().catch((error) => melde(error.message, 'fehler'))
  }
</script>

<SubHead title={t(meta.title)} {onback} />

<Group>
  <Menuezeile
    titel={row.running ? t('modell.laeuft_port', { port: row.port ?? '-' }) : t(row.word ?? 'status.inaktiv')}
    punkt={row.dot}
  />
  {#if usedMemory && !memoryFields.length}
    <Line label={t('kopf.speicher')} value={t('modell.im_speicher', { gb: usedMemory.replace(' GB', '') })} />
  {/if}
</Group>

<Group>
  {#if options.length}
    <Pick
      label={t('modell.feld_modell')}
      value={model}
      {options}
      disabled={row.running || busy}
      onpick={(value) => (picked = value)}
    />
  {:else if report}
    <Line label={t('modell.kein_modell_da')} />
  {/if}
  {#if kind === 'speech' && model}
    <!-- A speech model without its projector does not hear at all: it is the
         other half of the model, not a choice. -->
    <Line label={projector ? t('sprachserver.projektor', { datei: projector }) : t('sprachserver.kein_projektor')} />
  {/if}
</Group>

{#if memoryFields.length}
  <Group title={t('modell.gruppe_speicher')}>
    {#if usedMemory}
      <Line label={usedMemory} />
    {/if}
    {#each memoryFields as name (name)}
      <Field
        label={t(numberTitle(name))}
        bind:value={numbers[name]}
        inputmode="numeric"
        disabled={row.running || busy}
      />
    {/each}
  </Group>
{/if}

<Group title={t('modell.gruppe_netz')}>
  <Field
    label={t(numberTitle('port'))}
    bind:value={numbers.port}
    inputmode="numeric"
    disabled={row.running || busy}
  />
</Group>

<Group>
  {#if row.running}
    <Action label={t('modell.server_anhalten')} onclick={stop} disabled={busy} />
  {:else}
    <Action label={t('modell.server_starten')} kind="primary" onclick={start} disabled={busy || !model} />
  {/if}
  {#if driver.folder}
    <Action label={t('sprachserver.ordner_zeigen')} onclick={showFolder} />
  {/if}
</Group>

{#if kind === 'speech'}
  <SpeechSettings {report} />
{/if}

<Group>
  <Menuezeile titel={t('modell.protokoll')} onclick={() => (logOpen = !logOpen)}>
    {#snippet rechts()}
      <Leuchtpunkt farbe={logOpen ? 'blau' : 'still'} groesse={9} />
    {/snippet}
  </Menuezeile>
  {#if logOpen}<Log text={log} />{/if}
</Group>

{#if kind === 'model'}
  <Group title={PROGRAM}>
    <ProgramSection {report} onrefresh={read} />
  </Group>
{/if}
