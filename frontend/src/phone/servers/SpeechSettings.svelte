<script>
  /* What the speech server page of the desktop holds beside its start: the
     dictation (spoken language, instruction, auto-send), the clean-up (who
     tidies the text, and its instruction), the conversation model with its
     layers and threads, the conversation (read aloud, keep loaded, pause,
     voice sample, voice language, instruction) and the five generation
     values of the voice.

     Every value is one key of the stored setting the service reads on each
     request (`lib/diktat.svelte.js`), written as it is changed and only when
     it moved away from the works answer (`../speech.js`). The works answers
     come with the speech report as `diktat_vorgaben`, so "Reset" puts back
     exactly what the service would use. A text is written when the focus
     leaves it, and once more when the page goes. */
  import { t } from '../../lib/texte.svelte.js'
  import { melde } from '../../lib/zustand.svelte.js'
  import { diktat, standLaden, werteSetzen } from '../../lib/diktat.svelte.js'
  import { SPRACHEN } from '../../lib/diktatsprachen.js'
  import { STIMMSPRACHEN } from '../../lib/stimmsprachen.js'
  import Group from '../parts/Group.svelte'
  import Pick from '../parts/Pick.svelte'
  import Field from '../parts/Field.svelte'
  import Area from '../parts/Area.svelte'
  import Toggle from '../parts/Toggle.svelte'
  import Action from '../parts/Action.svelte'
  import {
    AUTO, PARAMETERS, PAUSE, SILENT_ROUNDS, WAIT, cleanerOptions, numberText, parseNumber,
    shownNumber, shownSwitch, shownText, worthStoring,
  } from '../speech.js'

  let { report } = $props()

  const works = $derived(report?.diktat_vorgaben ?? {})
  const cores = $derived(report?.kerne ?? 8)

  $effect(() => {
    standLaden()
  })

  function store(values) {
    return werteSetzen(values).catch(() => {
      melde(t('fehler.einstellung_speichern'), 'fehler')
      throw new Error('store')
    })
  }

  /* The text fields and the number fields keep a copy to type into, filled
     once when both halves are in: the stored answers come from the setting,
     the works answers from the report. A field filled from half of that would
     write the other half's placeholder back the moment somebody typed. */
  let mirrored = $state(false)
  let texts = $state({ anweisung: '', bereinigung_anweisung: '', gespraechsanweisung: '' })
  let numbers = $state({})

  /* The number fields: the stored key, its bounds, and the works answer. */
  const NUMBER_FIELDS = $derived([
    ...PARAMETERS.map((p) => ({ ...p, work: works[p.key], empty: true, auto: true })),
    { key: 'stimmschichten', min: 0, max: 99, step: 1, whole: true, work: works.stimmschichten ?? null, empty: true },
    { key: 'stimmfaeden', min: 0, max: cores, step: 1, whole: true, work: works.stimmfaeden, empty: false },
    { key: 'conversation_pause_seconds', ...PAUSE, whole: false, work: null, empty: true },
    { key: 'conversation_wait_seconds', ...WAIT, whole: false, work: null, empty: true },
    { key: 'conversation_silent_rounds', ...SILENT_ROUNDS, whole: true, work: null, empty: true },
  ])
  const spec = (key) => NUMBER_FIELDS.find((field) => field.key === key)

  $effect(() => {
    if (mirrored || !diktat.geladen || !report) return
    for (const key of Object.keys(texts)) texts[key] = shownText(diktat[key], works[key])
    for (const field of NUMBER_FIELDS) {
      numbers[field.key] = numberText(shownNumber(diktat[field.key], field.work), field)
    }
    mirrored = true
  })

  /* What was last sent for each field, so the same value is never asked for
     twice: a text left a moment after it was written would otherwise queue
     its write a second time behind the first. */
  const sent = {}

  function commitText(key) {
    const value = texts[key]
    if (!mirrored || value === sent[key] || !worthStoring(value, diktat[key], works[key])) return
    sent[key] = value
    store({ [key]: value }).catch(() => {
      sent[key] = undefined
      texts[key] = shownText(diktat[key], works[key])
    })
  }

  function reset(key) {
    texts[key] = works[key] ?? ''
    commitText(key)
  }

  function commitNumber(key) {
    const field = spec(key)
    const shown = () => numberText(shownNumber(diktat[key], field.work), field)
    const value = parseNumber(numbers[key], field)
    if (value === undefined || (value === null && !field.empty)) {
      numbers[key] = shown()
      return
    }
    numbers[key] = numberText(value, field)
    // An empty generation value of the voice is "Auto", stored as the word.
    const kept = value === null && field.auto ? AUTO : value
    if (kept === sent[key] || !worthStoring(kept, diktat[key], field.work)) return
    sent[key] = kept
    store({ [key]: kept }).catch(() => {
      sent[key] = undefined
      numbers[key] = shown()
    })
  }

  /* What was typed a moment before the page goes is not lost with the focus:
     a tap on a button does not always take it off a field. */
  $effect(() => () => {
    for (const key of Object.keys(texts)) commitText(key)
    for (const field of NUMBER_FIELDS) if (field.key in numbers) commitNumber(field.key)
  })

  /* A switch is flipped from what was last asked for, not from what the
     stored setting shows: that follows only when the write has been made, and
     a second tap before then would send the same value again. */
  let asked = $state({})
  function flip(key, shown) {
    const next = !(asked[key] ?? shown)
    asked[key] = next
    store({ [key]: next })
      .catch(() => {})
      .finally(() => delete asked[key])
  }

  const language = $derived(shownText(diktat.sprache, works.sprache) || 'auto')
  const languages = $derived([
    { value: 'auto', label: t('sprache.name_auto') },
    ...SPRACHEN.map((code) => ({ value: code, label: t(`sprache.name_${code}`) })),
  ])
  const cleaner = $derived(shownText(diktat.bereinigung, works.bereinigung) || 'aus')
  const cleaners = $derived(
    cleanerOptions(
      {
        aus: t('sprachserver.bereinigung_aus'),
        putzmodell: t('sprachserver.bereinigung_putzmodell'),
        putzmodellLeer: t('sprachserver.bereinigung_putzmodell_leer'),
        modell: t('sprachserver.bereinigung_modell'),
        agent: t('sprachserver.bereinigung_agent'),
      },
      Boolean(diktat.putzmodell),
    ),
  )
  const none = $derived({ value: '', label: t('sprachserver.stimme_keine') })
  /* A voice model of the speech folder or a voice of the system, in the one
     list; the chosen name says which speaks. */
  const knownVoices = $derived([
    none,
    ...(report?.modelle ?? []).map((m) => ({ value: m.name, label: m.name, detail: `${m.groesse_gb} GB` })),
    ...(report?.system_voices ?? []).map((v) => ({ value: v.name, label: v.name, detail: v.language })),
  ])
  // Nothing stored is the voice of the system this machine starts with.
  const voice = $derived(diktat.stimme ?? works.stimme ?? '')
  /* A stored name the lists no longer carry still stands in the field under
     its own name, so the field never shows empty while a voice is stored. */
  const voices = $derived(
    voice && !knownVoices.some((e) => e.value === voice)
      ? [...knownVoices, { value: voice, label: voice }]
      : knownVoices,
  )
  /* While a voice of the system is chosen the fields that act on a voice
     model stay visible and cannot be moved. */
  const systemVoice = $derived((report?.system_voices ?? []).some((v) => v.name === voice))
  const samples = $derived([none, ...(report?.stimmproben ?? []).map((name) => ({ value: name, label: name }))])
  const voiceLanguages = $derived([
    none,
    ...STIMMSPRACHEN.map((code) => ({ value: code, label: t(`sprache.name_${code}`) })),
  ])

  const autoSend = $derived(asked.automatik ?? shownSwitch(diktat.automatik, works.automatik, false))
  const readAloud = $derived(asked.vorlesen ?? shownSwitch(diktat.vorlesen, works.vorlesen, true))
  const keepLoaded = $derived(
    asked.keep_model_in_memory ?? shownSwitch(diktat.keep_model_in_memory, works.keep_model_in_memory, false),
  )

  const label = {
    anweisung: () => `${t('sprachserver.gruppe_diktat')} ${t('sprachserver.feld_anweisung')}`,
    bereinigung_anweisung: () => `${t('sprachserver.gruppe_bereinigung')} ${t('sprachserver.feld_anweisung')}`,
    gespraechsanweisung: () => `${t('sprachserver.gruppe_gespraech')} ${t('sprachserver.feld_gespraechsanweisung')}`,
  }
  const resetLabel = (key) => `${t('sprachserver.zuruecksetzen')} ${label[key]()}`
</script>

{#if diktat.geladen && report}
  <Group title={t('sprachserver.gruppe_diktat')}>
    <Pick label={t('sprachserver.feld_sprache')} value={language} options={languages}
          onpick={(value) => store({ sprache: value }).catch(() => {})} />
    <Area label={label.anweisung()} rows={4} bind:value={texts.anweisung} onchange={() => commitText('anweisung')} />
    <Action label={resetLabel('anweisung')} onclick={() => reset('anweisung')} />
    <Toggle label={t('sprachserver.feld_automatik')} on={autoSend}
            onswitch={() => flip('automatik', autoSend)} />
  </Group>

  <Group title={t('sprachserver.gruppe_bereinigung')}>
    <Pick label={t('sprachserver.feld_bereinigung')} value={cleaner} options={cleaners}
          onpick={(value) => store({ bereinigung: value }).catch(() => {})} />
    <Area label={label.bereinigung_anweisung()} rows={4} bind:value={texts.bereinigung_anweisung}
          onchange={() => commitText('bereinigung_anweisung')} />
    <Action label={resetLabel('bereinigung_anweisung')} onclick={() => reset('bereinigung_anweisung')} />
  </Group>

  <Group title={t('sprachserver.gruppe_gespraechsmodell')}>
    <Pick label={t('sprachserver.feld_stimme')} value={voice} options={voices}
          onpick={(value) => store({ stimme: value }).catch(() => {})} />
    <Field label={t('modell.feld_schichten')} bind:value={numbers.stimmschichten} inputmode="numeric"
           placeholder={t('parameter.auto')} disabled={systemVoice}
           onchange={() => commitNumber('stimmschichten')} />
    <Field label={t('modell.feld_faeden')} bind:value={numbers.stimmfaeden} inputmode="numeric"
           disabled={systemVoice} onchange={() => commitNumber('stimmfaeden')} />
  </Group>

  <Group title={t('sprachserver.gruppe_gespraech')}>
    <Toggle label={t('sprachserver.feld_vorlesen')} on={readAloud}
            onswitch={() => flip('vorlesen', readAloud)} />
    <Toggle label={t('sprachserver.keep_model_loaded')} on={keepLoaded}
            onswitch={() => flip('keep_model_in_memory', keepLoaded)} />
    <Field label={t('sprachserver.pause_before_sending')} bind:value={numbers.conversation_pause_seconds}
           inputmode="decimal" placeholder={t('parameter.auto')}
           onchange={() => commitNumber('conversation_pause_seconds')} />
    <Field label={t('sprachserver.wait_for_speech')} bind:value={numbers.conversation_wait_seconds}
           inputmode="decimal" placeholder={t('parameter.auto')}
           onchange={() => commitNumber('conversation_wait_seconds')} />
    <Field label={t('sprachserver.rounds_without_speech')} bind:value={numbers.conversation_silent_rounds}
           inputmode="numeric" placeholder={t('parameter.auto')}
           onchange={() => commitNumber('conversation_silent_rounds')} />
    <Pick label={t('sprachserver.feld_stimmprobe')} value={diktat.stimmprobe ?? ''} options={samples}
          disabled={systemVoice} onpick={(value) => store({ stimmprobe: value }).catch(() => {})} />
    <Pick label={t('sprachserver.feld_stimmsprache')} value={diktat.stimmsprache ?? ''} options={voiceLanguages}
          disabled={systemVoice} onpick={(value) => store({ stimmsprache: value }).catch(() => {})} />
    <Area label={label.gespraechsanweisung()} rows={4} bind:value={texts.gespraechsanweisung}
          onchange={() => commitText('gespraechsanweisung')} />
    <Action label={resetLabel('gespraechsanweisung')} onclick={() => reset('gespraechsanweisung')} />
  </Group>

  <Group title={t('sprachserver.gruppe_parameter')}>
    {#each PARAMETERS as p (p.key)}
      <Field label={t(p.label)} bind:value={numbers[p.key]} inputmode="decimal"
             placeholder={t('parameter.auto')} disabled={systemVoice} onchange={() => commitNumber(p.key)} />
    {/each}
  </Group>
{/if}
