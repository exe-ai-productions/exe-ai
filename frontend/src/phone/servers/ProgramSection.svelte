<script>
  /* The program every llama.cpp server of this program starts: the build
     that starts, and what can be done about it, in the order it is done —
     look for a newer build, fetch the one that was found, go back to the
     tested one. Without a program the section holds the one button that
     fetches it, with the bar while it comes.

     A press here is a press for all five servers: the routes belong to the
     program, not to a server. Asked only when a button is pressed, never on
     a timer — nothing looks for updates by itself. */
  import { untrack } from 'svelte'
  import { api } from '../../lib/api.js'
  import { t } from '../../lib/texte.svelte.js'
  import { melde } from '../../lib/zustand.svelte.js'
  import Line from '../parts/Line.svelte'
  import Action from '../parts/Action.svelte'

  let { report = null, onrefresh = null } = $props()

  const hasProgram = $derived(Boolean(report?.programm))

  /* The fetch in progress, as the server reports it — read once, and every
     two seconds while one is on its way. */
  let program = $state(null)
  const fetching = $derived(Boolean(program) && !program.fertig && !program.fehler)

  async function readState() {
    try {
      program = await api.serverProgrammStand()
    } catch {
      // The page's own reading says when the server is unreachable.
    }
  }
  readState()

  $effect(() => {
    if (!fetching) return
    const timer = setInterval(readState, 2000)
    return () => clearInterval(timer)
  })

  /* The builds this machine could fetch — a list only on Windows on x64. */
  let variants = $state(null)
  async function readVariants() {
    try {
      variants = await api.serverProgrammVarianten()
    } catch {
      variants = null
    }
  }
  readVariants()
  const showVariants = $derived(
    Boolean(variants?.varianten?.length) && (!hasProgram || Boolean(report?.updatable)),
  )

  let answer = $state(null)
  let checking = $state(false)
  // Only the newest check may answer.
  let checkRun = 0

  async function check() {
    const run = ++checkRun
    checking = true
    answer = null
    try {
      const found = await api.serverProgramUpdateCheck()
      if (run === checkRun) {
        answer = found
        if (found.unreadable) melde(t('bildserver.updates_nicht_pruefbar'), 'fehler')
      }
    } catch (error) {
      if (run === checkRun) melde(error.message, 'fehler')
    } finally {
      if (run === checkRun) checking = false
    }
  }

  const take = (promise) =>
    promise.then((next) => (program = next)).catch((error) => melde(error.message, 'fehler'))

  /* A fetch that ends clears the last answer — it spoke of the build before. */
  let before = false
  $effect(() => {
    if (before && !fetching) {
      answer = null
      checkRun += 1
      checking = false
      if (program?.fehler) melde(t('bildserver.generator_fehler'), 'fehler')
      readVariants()
      untrack(() => onrefresh?.())
    }
    before = fetching
  })
</script>

<Line label={t('bildserver.version_zeile', { bau: report?.version ?? '-' })} />

{#if fetching}
  <Line label={t('modell.server_download')} value={`${Math.round(program.anteil * 100)} %`} />
{:else}
  {#if program?.fehler}<Line label={t('bildserver.generator_fehler')} />{/if}
  {#if hasProgram && report.updatable}
    <Action label={t('bildserver.nach_updates_suchen')} onclick={check} disabled={checking} />
    {#if answer?.verfuegbar}
      <Action label={t('bildserver.generator_aktualisieren')} kind="primary" onclick={() => take(api.serverProgramUpdate())} />
    {:else if answer?.aktuell}
      <Line label={t('bildserver.nach_updates_suchen')} value="✓" />
    {/if}
  {/if}
  {#if hasProgram && report.restorable}
    <Action label={t('bildserver.restore_tested_build')} onclick={() => take(api.serverProgramRestore())} />
  {/if}
  {#if showVariants}
    {#each variants.varianten as variant (variant.variante)}
      {#if variant.variante === variants.installiert}
        <Line label={variant.variante} value={t('bildserver.variante_installiert')} />
      {:else}
        <Action
          label={`${variant.variante} · ${t('bildserver.variante_holen', { groesse: `${Math.round(variant.groesse / (1024 * 1024))} MB` })}`}
          onclick={() => take(api.serverProgrammHolen(variant.variante))}
        />
      {/if}
    {/each}
  {:else if !hasProgram}
    <Action label={t('modell.server_download')} kind="primary" onclick={() => take(api.serverProgrammHolen())} />
  {/if}
{/if}
