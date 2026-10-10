<script>
  /* The further sd.cpp switches of one window block, drawn from the
     service's table (lib/imageSwitches.svelte.js, app/image_switches.py).
     Each switch is one row, in the table's order; the rows sit straight in
     the block's grid, so the search finds them like every other row.

     Every value starts unset, and unset is what the service reads as "send
     nothing". A switch that acts only beside another (the detector, the
     cache mode, VAE tiles, the IP-Adapter) stays visible and is shut while
     that one is off. A row that is only on or off wears the house's switch.

     The rows carry the class `switchrow`; whoever draws them sets their
     measures through it. */
  import Auswahlfeld from './Auswahlfeld.svelte'
  import Bildablage from './Bildablage.svelte'
  import InfoMark from './InfoMark.svelte'
  import Schalter from './Schalter.svelte'
  import { api } from '../lib/api.js'
  import { imageSwitches } from '../lib/imageSwitches.svelte.js'
  import { t } from '../lib/texte.svelte.js'

  /* `conditions`: what is on beside the table — { ad_model, photomaker,
     hires, high_noise, video }. `upload`: lays a picture down on the
     service and answers with the name it got, or null. `keys`: only these
     rows of the group, for a group whose rows stand in more than one place. */
  let { group, values = $bindable({}), conditions = {}, upload, keys = null } = $props()

  /* The label names the field and nothing else: the ⓘ beside it stands
     outside the label, keeps its own name and stays a key stop of its own
     (InfoMark.svelte). Each field gets an id the label points at, unique
     for every block that draws these rows. */
  const uid = $props.id()
  const fieldId = (row) => `${uid}-${row.key}`

  // A row acting on a video only, or on a still picture only, is shown
  // only for what is drawn — the service drops it everywhere else.
  const rows = $derived(imageSwitches.list.filter((row) => row.group === group
    && (!keys || keys.includes(row.key))
    && (row.video == null || row.video === Boolean(conditions.video))))

  // A row that needs one of several things (split by "|") acts once any is on.
  function met(row) {
    if (!row.needs) return true
    return row.needs.split('|').some((name) =>
      name in conditions ? Boolean(conditions[name]) : Boolean(values[name]))
  }

  function set(key, value) {
    values = { ...values, [key]: value }
  }

  function setNumber(row, text) {
    if (text === '' || text === null) return set(row.key, '')
    const number = Number(text)
    // A whole-number switch folds a typed fraction, as the window's other
    // whole-number fields do, rather than have the draw refused for it.
    if (!Number.isFinite(number)) return set(row.key, '')
    set(row.key, row.kind === 'int' ? Math.trunc(number) : number)
  }

  async function pickPicture(key, file) {
    const name = await upload(file)
    if (!name) return false
    set(key, name)
    return true
  }
</script>

{#each rows as row (row.key)}
  {#if row.kind === 'picture'}
    <div class="feld switchrow" class:gesperrt={!met(row)}>
      <span>{t(`bild.sw_${row.key}`)}<InfoMark text={t(`bild.info_sw_${row.key}`)} /></span>
      <Bildablage url={values[row.key] ? api.bildAdresse(values[row.key]) : ''}
                  waehlen={(file) => pickPicture(row.key, file)}
                  loesen={() => set(row.key, '')} />
    </div>
  {:else if row.kind === 'int' || row.kind === 'float'}
    <div class="feld switchrow" class:gesperrt={!met(row)}>
      <span><label for={fieldId(row)}>{t(`bild.sw_${row.key}`)}</label><InfoMark text={t(`bild.info_sw_${row.key}`)} /></span>
      <input id={fieldId(row)} class="feldein" type="number" step={row.kind === 'int' ? 1 : 'any'}
             min={row.low ?? undefined} max={row.high ?? undefined}
             value={values[row.key] ?? ''} disabled={!met(row)}
             oninput={(e) => setNumber(row, e.currentTarget.value)} />
    </div>
  {:else if row.kind === 'text'}
    <div class="feld switchrow" class:gesperrt={!met(row)}>
      <span><label for={fieldId(row)}>{t(`bild.sw_${row.key}`)}</label><InfoMark text={t(`bild.info_sw_${row.key}`)} /></span>
      <input id={fieldId(row)} class="feldein" type="text" value={values[row.key] ?? ''} disabled={!met(row)}
             oninput={(e) => set(row.key, e.currentTarget.value)} />
    </div>
  {:else if row.kind === 'bool'}
    <div class="feld switchrow" class:gesperrt={!met(row)}>
      <span><label for={fieldId(row)}>{t(`bild.sw_${row.key}`)}</label><InfoMark text={t(`bild.info_sw_${row.key}`)} /></span>
      <div class="toggle">
        <Schalter id={fieldId(row)} an={Boolean(values[row.key])} beschriftung={t(`bild.sw_${row.key}`)}
                  gesperrt={!met(row)} onschalten={(on) => set(row.key, on)} />
      </div>
    </div>
  {:else}
    <div class="feld switchrow" class:gesperrt={!met(row)}>
      <span>{t(`bild.sw_${row.key}`)}<InfoMark text={t(`bild.info_sw_${row.key}`)} /></span>
      <Auswahlfeld wert={values[row.key] ?? ''}
                   beschriftung={t(`bild.sw_${row.key}`)} gesperrt={!met(row)}
                   gewaehlt={(value) => set(row.key, value)}
                   search={row.kind === 'file'} searchLabel={t('app.suchen')}
                   eintraege={row.kind === 'file'
                     ? [{ wert: '', text: t('bild.adetailer_keins') },
                        ...(imageSwitches.files[row.folder] ?? []).map((name) => ({ wert: name, text: name }))]
                     : [{ wert: '', text: t('parameter.auto') },
                        ...row.choices.map((choice) => ({ wert: choice, text: choice }))]} />
    </div>
  {/if}
{/each}

<style>
  /* The switch stands at the right end of the room a row gives its control. */
  .toggle {
    display: flex;
    justify-content: flex-end;
  }
</style>
