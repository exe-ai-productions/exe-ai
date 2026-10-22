<script>
  /* "Convert to GGUF" in the picture server, in two tabs. GGUF: one file of
     the folder, the type a smaller copy of it is written in, and the sign that
     converts (app/api/v1/image_tools.py); beneath them the one switch for the
     importance matrix — for every file at once, kept with the machine's other
     picture settings, on until it is turned off — and the folder where an
     own matrix of a file can be laid, which converting reads. FP16: a copy of
     a file whose weights are mostly BF16, with those weights as FP16
     (ImageConvertFp16.svelte). Whichever tab converts, the bar and the cross
     are the block's, and the lock is one: a conversion at a time. */
  import { api } from '../lib/api.js'
  import { t } from '../lib/texte.svelte.js'
  import { meldeText } from '../lib/meldewesen.svelte.js'
  import { melde } from '../lib/zustand.svelte.js'
  import { imageFiles, loadImageFiles } from '../lib/imageModelFiles.svelte.js'
  import Serverabschnitt from './Serverabschnitt.svelte'
  import Auswahlfeld from './Auswahlfeld.svelte'
  import Schalter from './Schalter.svelte'
  import Hauszeichen from './Hauszeichen.svelte'
  import TabSwitch from './TabSwitch.svelte'
  import ImageConvertFp16 from './ImageConvertFp16.svelte'
  import DownloadRow from './DownloadRow.svelte'
  import { pictureProgress, watchPictureProgress } from '../lib/pictureProgress.svelte.js'

  /* Called after a conversion has made a new file, so the page reads its own
     state again — the list of the default model among it. */
  let { onconverted } = $props()

  const SCHLUESSEL = 'bildgeraete'

  // Only a file a copy gets smaller from is offered, and only its own types.
  const convertible = $derived(imageFiles.list.filter((file) => file.convert_types?.length))
  let source = $state('')
  let weightType = $state('')
  let running = $state(false)
  let tab = $state('gguf')
  const current = $derived(convertible.find((file) => file.name === source) ?? convertible[0])
  /* The share of the conversion, from the one answer every surface of a
     running picture reads: asked only while a conversion runs. */
  $effect(() => {
    if (running) return watchPictureProgress()
  })
  const percent = $derived(Math.round(Math.min(Math.max(pictureProgress.share, 0), 1) * 100))
  const stopConverting = () => api.bildZeichnenStoppen().catch(() => {})
  $effect(() => {
    if (current && source !== current.name) source = current.name
  })
  $effect(() => {
    if (current && !current.convert_types.includes(weightType)) weightType = current.convert_types[0]
  })

  /* The switch stays shut until the stored value is read, and while a change
     is on its way: it never shows a value nobody stored. */
  let imatrix = $state(true)
  let imatrixBusy = $state(true)
  api
    .einstellungAufgeloest(SCHLUESSEL)
    .then((answer) => {
      imatrix = answer?.wert?.imatrix !== false
      imatrixBusy = false
    })
    .catch(() => {})

  /* One conversion, whichever tab asked for it: the bar runs while the call
     is open; stopped on request is no failure, as with a stopped picture —
     nothing is told, and the choice stands as it did before the start. */
  async function runConversion(call) {
    if (running) return
    running = true
    try {
      const answer = await call()
      meldeText('bildserver.umgewandelt', { datei: answer.file }, 'erfolg')
      if (answer.capped) meldeText('bildserver.capped_values', { n: answer.capped }, 'warnung')
      loadImageFiles()
      onconverted?.()
    } catch (error) {
      if (error.status !== 499) melde(String(error.message || error), 'fehler')
    } finally {
      running = false
    }
  }

  const startConverting = () => current && runConversion(() => api.convertModel(current.name, weightType))
  const startFp16 = (name) => runConversion(() => api.convertFp16(name))

  async function switchImatrix(on) {
    const before = imatrix
    imatrix = on
    imatrixBusy = true
    try {
      await api.collectImatrix(on)
      loadImageFiles()
    } catch (error) {
      imatrix = before
      melde(String(error.message || error), 'fehler')
    } finally {
      imatrixBusy = false
    }
  }
</script>

<Serverabschnitt zeichen="shrink" titel={t('bildserver.gguf_konvertierung')}>
  <div class="zeile tabs">
    <TabSwitch bind:wert={tab} label={t('bildserver.gguf_konvertierung')}
               eintraege={[
                 { wert: 'gguf', text: t('bildserver.tab_gguf') },
                 { wert: 'fp16', text: t('bildserver.tab_fp16') },
               ]} />
  </div>
  {#if tab === 'gguf'}
    <div class="zeile">
      <span class="zeilentitel">{t('bildserver.datei')}</span>
      <div class="dateiwahl">
        <Auswahlfeld bind:wert={source} beschriftung={t('bildserver.datei')}
                     eintraege={convertible.map((file) => ({ wert: file.name, text: file.name }))}
                     gesperrt={running || !convertible.length} />
      </div>
    </div>
    <div class="zeile">
      <span class="zeilentitel">{t('bild.weight_type')}</span>
      <div class="typwahl">
        <Auswahlfeld bind:wert={weightType} beschriftung={t('bild.weight_type')}
                     eintraege={(current?.convert_types ?? []).map((kind) => ({ wert: kind, text: kind }))}
                     gesperrt={running || !current} />
      </div>
      <button class="zeichenknopf" disabled={running || !current} onclick={startConverting}
              title={running ? t('bildserver.umwandeln_laeuft') : t('bildserver.umwandeln')}
              aria-label={running ? t('bildserver.umwandeln_laeuft') : t('bildserver.umwandeln')}>
        <Hauszeichen zeichen="shrink" groesse="klein" />
      </button>
    </div>
  {:else}
    <ImageConvertFp16 {running} onconvert={startFp16} />
  {/if}
  {#if running}
    <div class="zeile running">
      <DownloadRow status="laedt" compact {percent} onCancel={stopConverting} />
    </div>
  {/if}
  {#if tab === 'gguf'}
  <div class="zeile imatrix">
    <span class="text">
      <span class="zeilentitel">{t('bildserver.imatrix')}</span>
      <span class="satz">{t('bildserver.imatrix_satz')}</span>
    </span>
    <button class="zeichenknopf" onclick={() => api.bildordnerOeffnen().catch(() => {})}
            title={t('sprachserver.ordner_zeigen')} aria-label={t('sprachserver.ordner_zeigen')}>
      <Hauszeichen zeichen="ordner" groesse="klein" />
    </button>
    <Schalter an={imatrix} beschriftung={t('bildserver.imatrix')} gesperrt={imatrixBusy}
              onschalten={switchImatrix} />
  </div>
  {/if}
</Serverabschnitt>

<style>
  /* The rows are Serverabschnitt.svelte's; here only their parts. */
  .zeilentitel {
    flex: 1;
    min-width: 0;
    font-size: 13px;
    font-weight: 600;
    line-height: 18px;
    color: var(--text);
  }
  .dateiwahl {
    flex: none;
    width: 300px;
  }
  .typwahl {
    flex: none;
    width: 160px;
  }
  /* The Imatrix row names the switch and says in one line what it is for. */
  .zeile.imatrix {
    min-height: 64px;
  }
  .text {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .text .zeilentitel {
    flex: none;
  }
  .satz {
    font-size: 12px;
    line-height: 17px;
    color: var(--text-leise);
  }
  /* A sign on a button of button glass, 34 like the other buttons of a card. */
  .zeichenknopf {
    flex: none;
    width: 34px;
    height: 34px;
    padding: 0;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 9px;
    background: var(--glass-button);
    box-shadow: inset 0 0 0 1px var(--glass-button-edge);
    color: var(--text-leise);
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }
  .zeichenknopf:hover:not(:disabled) {
    background: color-mix(in srgb, var(--text) 6%, var(--glass-button));
    color: var(--text);
  }
  .zeichenknopf:disabled {
    cursor: default;
    opacity: 0.5;
  }
</style>
