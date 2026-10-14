<script>
  /* The one form for a schedule — a new one, or one opened from its card.
     It stands in the pop-up beside the day clicked in the calendar, or
     beside "Change", and it is fields only: one column, no surface and no
     frame of its own.

     It writes no rows itself. A new schedule goes through the route that
     hands the fields to the cronjob tool, a changed one through the tool's
     own `update` — the same doors a chat goes through, with every rule that
     guards an entry still in front of them. A change sends only the fields
     that differ, so what was not touched stays exactly as it was.

     The kind decides the fields: an agent gets a task, a script its file, a
     reminder its text. Once a schedule exists its kind stays — the tool
     refuses a change of kind, and a control offering one would lie. */
  import { untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import { t, texte } from '../lib/texte.svelte.js'
  import { melde, zustand } from '../lib/zustand.svelte.js'
  import { zeitpunkt } from '../lib/zeitpunkt.js'
  import { changedSchedule, chipOf, formFromEntry, storedFromForm } from '../lib/terminform.js'
  import Auswahlfeld from './Auswahlfeld.svelte'
  import { OHNE_AGENT } from '../lib/agentmarke.js'

  let { entry = null, day, script = '', onclose } = $props()

  /* The fields, read once from what the form was opened with. */
  const initial = untrack(() => ({
    kind: entry ? entry.kind : script ? 'script' : 'agent',
    task: entry && entry.kind !== 'script' ? entry.task : '',
    agent: entry && entry.kind === 'agent' && entry.agent !== OHNE_AGENT ? entry.agent : '',
    script: entry ? entry.skript || '' : script,
    /* A new schedule is a one-off on the day it was made from; "daily" is
       the user's own choice. */
    ...(entry ? formFromEntry(entry, day) : { ...formFromEntry(null, day), repeat: 'once' }),
  }))
  let kind = $state(initial.kind)
  let task = $state(initial.task)
  let agent = $state(initial.agent)
  let scriptName = $state(initial.script)
  let repeat = $state(initial.repeat)
  let time = $state(initial.time)
  let chosenDay = $state(initial.day)
  let weekdays = $state(initial.weekdays)
  let monthDay = $state(initial.monthDay)
  let cron = $state(initial.cron)
  let saving = $state(false)

  /* The kind and the rhythm as the house's selection field, each entry
     named by the interface language. The values are the ones the form
     stores (lib/terminform.js, `REPEATS`) and the service answers with. */
  const kindChoice = $derived([
    { wert: 'agent', text: t('cronjobs.kind_agent') },
    { wert: 'script', text: t('cronjobs.kind_script') },
    { wert: 'reminder', text: t('cronjobs.kind_reminder') },
  ])
  const repeatChoice = $derived([
    { wert: 'once', text: t('cronjobs.repeat_once') },
    { wert: 'daily', text: t('cronjobs.repeat_daily') },
    { wert: 'weekly', text: t('cronjobs.repeat_weekly') },
    { wert: 'monthly', text: t('cronjobs.repeat_monthly') },
    { wert: 'custom', text: t('cronjobs.repeat_custom') },
  ])

  let agents = $state([])
  $effect(() => {
    api.agenten().then((list) => (agents = list)).catch(() => {})
  })
  /* "No agent" for every schedule, an old one whose agent is gone among
     them: it is the way to make that one run again. The agent a schedule
     names that no file stands behind any more is listed as it is, so the
     field shows what is stored. */
  const agentChoice = $derived([
    { wert: '', text: t('cronjobs.ohne_agent') },
    ...agents.map((a) => ({ wert: a.name, text: a.name })),
    ...(initial.agent && agents.length && !agents.some((a) => a.name === initial.agent)
      ? [{ wert: initial.agent, text: initial.agent }]
      : []),
  ])

  /* Weekday chips, Monday first, named by the interface language. */
  const chipNames = $derived.by(() => {
    const locale = texte.sprache === 'de' ? 'de-DE' : 'en-GB'
    const monday = new Date(2026, 0, 5)
    return Array.from({ length: 7 }, (_, i) =>
      new Date(monday.getFullYear(), 0, 5 + i).toLocaleDateString(locale, { weekday: 'short' }))
  })

  function toggleWeekday(chip) {
    weekdays = weekdays.includes(chip) ? weekdays.filter((d) => d !== chip) : [...weekdays, chip]
  }

  /* Picking a day for a weekly schedule starts with that day's weekday. */
  $effect(() => {
    if (repeat === 'weekly' && !untrack(() => weekdays.length)) weekdays = [chipOf(untrack(() => chosenDay))]
  })

  /* What a typed expression means: its next runs, read by the service on
     its own clock. Asked a moment after the typing stops. */
  let customLine = $state('')
  let customFault = $state(false)
  $effect(() => {
    if (repeat !== 'custom') return
    const phrase = cron.trim()
    if (!phrase) {
      customLine = ''
      return
    }
    const wait = setTimeout(async () => {
      try {
        const next = await api.cronjobPreview(phrase)
        customFault = false
        customLine = t('cronjobs.naechste_faelligkeit', {
          wann: next.map((moment) => zeitpunkt(moment, zustand.timezone)).join(' · '),
        })
      } catch (fault) {
        customFault = true
        customLine = String(fault.message || fault)
      }
    }, 300)
    return () => clearTimeout(wait)
  })

  const form = () => ({ repeat, time, day: chosenDay, weekdays, monthDay, cron })

  const complete = $derived(
    (kind === 'script' ? Boolean(scriptName.trim()) : Boolean(task.trim()))
      && (repeat === 'custom' ? Boolean(cron.trim()) : Boolean(time))
      && (repeat !== 'once' || Boolean(chosenDay))
      && (repeat !== 'weekly' || weekdays.length > 0)
      && (repeat !== 'monthly' || (Number.isInteger(monthDay) && monthDay >= 1 && monthDay <= 31))
      && !saving,
  )

  async function create() {
    const stored = storedFromForm(form())
    return api.cronjobAnlegen({
      ...stored,
      task: kind === 'script' ? '' : task.trim(),
      agent: kind === 'agent' ? agent || null : null,
      skript: kind === 'script' ? scriptName.trim() : null,
      reminder: kind === 'reminder',
    })
  }

  /* Only what differs from what the form opened with. */
  async function change() {
    const fields = changedSchedule(entry, form(), day)
    if (kind !== 'script' && task.trim() !== initial.task) fields.task = task.trim()
    if (kind === 'agent' && agent !== initial.agent) fields.agent = agent
    if (kind === 'script' && scriptName.trim() !== initial.script) fields.skript = scriptName.trim()
    if (!Object.keys(fields).length) return entry
    return api.cronjobChange(entry.id, fields)
  }

  async function save() {
    if (!complete) return
    saving = true
    try {
      const row = entry ? await change() : await create()
      melde(t(entry ? 'cronjobs.changed' : 'cronjobs.angelegt'), 'erfolg')
      onclose(row)
    } catch (fault) {
      /* The tool's own sentence, verbatim — it names what is wrong. */
      melde(String(fault.message || fault), 'fehler')
    } finally {
      saving = false
    }
  }
</script>

<div class="form">
  <div class="fields">
    <div class="head">{t(entry ? 'cronjobs.form_change' : 'cronjobs.neuer_cronjob')}</div>

    <div class="field">
      <span>{t('cronjobs.field_kind')}</span>
      <Auswahlfeld bind:wert={kind} eintraege={kindChoice} gesperrt={Boolean(entry)} />
    </div>

    {#if kind === 'agent'}
      <label class="field">
        <span>{t('cronjobs.aufgabe')}</span>
        <textarea bind:value={task} rows="2"></textarea>
      </label>
      <div class="field">
        <span>{t('cronjobs.kind_agent')}</span>
        <Auswahlfeld bind:wert={agent} eintraege={agentChoice} />
      </div>
    {:else if kind === 'script'}
      <label class="field">
        <span>{t('cronjobs.field_script')}</span>
        <input class="fixed" bind:value={scriptName} />
      </label>
    {:else}
      <label class="field">
        <span>{t('cronjobs.field_text')}</span>
        <textarea bind:value={task} rows="2"></textarea>
      </label>
    {/if}

    <div class="field">
      <span>{t('cronjobs.field_repeat')}</span>
      <Auswahlfeld bind:wert={repeat} eintraege={repeatChoice} />
      {#if repeat === 'weekly'}
        <div class="chips">
          {#each chipNames as name, chip (chip)}
            <button class:on={weekdays.includes(chip)} aria-pressed={weekdays.includes(chip)}
                    onclick={() => toggleWeekday(chip)}>{name}</button>
          {/each}
        </div>
      {/if}
    </div>

    {#if repeat === 'custom'}
      <label class="field">
        <span>{t('cronjobs.cron_phrase')}</span>
        <input class="fixed" bind:value={cron} />
        {#if customLine}
          <span class="explain" class:fault={customFault}>{customLine}</span>
        {/if}
      </label>
    {:else}
      <div class="pair">
        {#if repeat === 'once'}
          <label class="field">
            <span>{t('cronjobs.day')}</span>
            <input type="date" bind:value={chosenDay} />
          </label>
        {:else if repeat === 'monthly'}
          <label class="field">
            <span>{t('cronjobs.day_of_month')}</span>
            <input type="number" min="1" max="31" bind:value={monthDay} />
          </label>
        {/if}
        <label class="field">
          <span>{t('cronjobs.field_time')}</span>
          <input type="time" bind:value={time} />
        </label>
      </div>
    {/if}
  </div>

  <div class="foot">
    <button onclick={() => onclose(null)}>{t('app.abbrechen')}</button>
    <button class="primary" disabled={!complete} onclick={save}>{t('cronjobs.save')}</button>
  </div>
</div>

<style>
  /* Fields only: the form stands on the ground of the pop-up that holds it. */
  .form {
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-height: 0;
  }
  /* The part that scrolls where the pop-up is shorter than the form; the
     foot below it never does. The small side room keeps a focus ring whole. */
  .fields {
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-height: 0;
    overflow-y: auto;
    padding: 0 2px;
    margin: 0 -2px;
  }
  .head {
    font-size: 14px;
    font-weight: 600;
    color: var(--text);
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
    font-size: 11.5px;
    color: var(--text-still);
  }
  .field input,
  .field textarea {
    font: inherit;
    font-size: 13px;
    line-height: 1.35;
    color: var(--text);
    /* Glass with the house's field outline — the same fill and edge the
       selection fields beside them carry, so every field in the pop-up
       reads alike. */
    background: var(--glass-button);
    border: 1px solid var(--feldstrich);
    border-radius: 9px;
    padding: 6px 10px;
    min-height: 32px;
    resize: vertical;
    /* The calendar and clock of the browser follow the look
       (`--feld-farbschema`, global.css); a page that names no scheme gives
       them the light one. */
    color-scheme: var(--feld-farbschema, normal);
  }
  .field input:focus,
  .field textarea:focus {
    outline: none;
    background: color-mix(in srgb, var(--text) 5%, var(--glass-button));
  }
  .field .fixed {
    font-family: var(--schrift-fest);
    font-size: 12px;
  }
  .explain {
    font-size: 11.5px;
    color: var(--text-still);
  }
  .explain.fault {
    color: var(--rot-text);
  }
  .pair {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 8px;
  }
  /* Seven days in one row, however narrow the column: each chip gives up
     its padding before the row gives up a day. The chosen one is brighter,
     not coloured — a choice is not a state. */
  .chips {
    display: flex;
    gap: 3px;
    margin-top: 4px;
  }
  .chips button {
    flex: 1 1 0;
    min-width: 0;
    border: none;
    border-radius: 9px;
    padding: 4px 0;
    overflow: hidden;
    text-overflow: ellipsis;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text-leise);
    font: inherit;
    font-size: 12px;
    cursor: pointer;
  }
  .chips button.on {
    background: color-mix(in srgb, var(--text) 14%, var(--glass-button));
    color: var(--text);
  }
  /* Side by side, one size: both buttons take half the row. */
  .foot {
    flex: none;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
  }
  .foot button {
    font: inherit;
    font-size: 12px;
    height: 32px;
    padding: 0 14px;
    border: none;
    border-radius: 9px;
    cursor: pointer;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text);
  }
  .foot .primary {
    background: var(--text);
    box-shadow: none;
    color: var(--bg);
  }
  .foot .primary:disabled {
    opacity: 0.45;
    cursor: default;
  }
</style>
