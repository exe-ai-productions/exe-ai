<script>
  /* One curated model up close: who made it, what it can do, what the
     machine holds, and one row per build with whether it fits, how big it is
     and one tap to fetch it with its companions (a vision projector, a speed
     module). A build that lies here says so; one being fetched shows how far
     it is and can be cancelled. */
  import { t } from '../../lib/texte.svelte.js'
  import {
    ZUBEHOER_ZIEL, SORTE_LABEL, brauchtMaschine, passendeFassung, passt,
  } from '../../lib/modellempfehlungen.js'
  import { api } from '../../lib/api.js'
  import { melde } from '../../lib/zustand.svelte.js'
  import { familyOf, loadImageFamilies } from '../../lib/imageFamilies.svelte.js'
  import Leuchtpunkt from '../../teile/Leuchtpunkt.svelte'
  import SubHead from '../parts/SubHead.svelte'
  import Group from '../parts/Group.svelte'
  import Line from '../parts/Line.svelte'
  import Action from '../parts/Action.svelte'
  import { feed, enqueue, cancelDownload } from '../downloadFeed.svelte.js'
  import { buildState, buildProgress, planBuild, planDownload, gigabytes } from '../catalog.js'

  let { card, art, memory = null, onback } = $props()

  /* Full keys in a map, not built inside t(): a composed key would read as a
     broken one to the interface-text check. */
  const CAN = {
    werkzeug: 'katalog.kann_winkel',
    auge: 'katalog.kann_auge',
    gluehbirne: 'katalog.kann_gluehbirne',
    blitz: 'katalog.kann_blitz',
  }

  loadImageFamilies()

  const recommended = $derived(passendeFassung(card, memory))
  const first = $derived(card.fassungen[0])
  const hasPage = $derived(typeof first?.id === 'string' && first.id.includes('/'))
  /* Where a card's files go: an accessory carries its own place, anything
     else lands in the kind of the page it was opened on. */
  const route = $derived(card.zubehoer ? (ZUBEHOER_ZIEL[card.sorte] ?? { art }) : { art })

  const fitWord = (build) => {
    if (!passt(build, memory)) return t('katalog.braucht_maschine', { gb: brauchtMaschine(build) })
    return build === recommended
      ? t('katalog.empfohlen_fuer', { gb: memory })
      : t('katalog.passt_fuer', { gb: memory })
  }

  const stateWord = (build) => {
    const phase = buildState(build, feed.present, feed.stand)
    if (phase === 'bereit') return t('katalog.im_ordner')
    if (phase === 'laedt') return `${buildProgress(build, feed.stand)?.percent ?? 0} %`
    return t('katalog.herunterladen')
  }

  /* The part being fetched, in words, so a projector that follows its model
     is not mistaken for the model going round again. */
  const partWord = (progress) =>
    progress?.part === 'mmproj'
      ? t('modell.augen')
      : progress?.part === 'drafter'
        ? t('modell.feld_drafter')
        : ''

  /* A picture or video build comes the way a found file does: its row is
     looked up in the repository, the head of the file names its kit (text
     encoders, VAE) and the parts come with it. Where the hub or the head
     cannot be read, the file alone is fetched. A pair (Wan 2.2 A14B) brings
     its second model. */
  async function fetchPicture(build) {
    let full = null
    try {
      const list = await api.modellDateien(build.id, 'bild')
      const row = list.dateien.find((entry) => entry.datei === build.datei)
      if (row) full = await api.fileHead(build.id, row)
    } catch {
      full = null
    }
    const plan = planDownload({
      repo: build.id,
      file: full ?? { datei: build.datei, local_name: build.ziel },
      projector: null,
      present: feed.present,
      partLists: feed.partLists,
    })
    const partner = build.partner
    if (partner && !feed.present.includes(partner.ziel)) {
      const job = { repo: build.id, datei: partner.datei, ziel: partner.ziel }
      plan.queue.splice(plan.queue.length > 0 && plan.queue[0].datei === build.datei ? 1 : 0, 0, job)
    }
    for (const tie of plan.ties) {
      try {
        await api.modellHolen(tie.repo, tie.datei, tie.ziel, tie.gehoert_zu, tie.rolle, 'bild', tie.unterordner)
      } catch (error) {
        melde(error.message, 'fehler')
      }
    }
    if (plan.queue.length) await enqueue(plan.queue, 'bild')
  }

  async function fetchBuild(build) {
    if (card.bild && !card.zubehoer) return fetchPicture(build)
    const { art: kind, queue } = planBuild({
      build,
      present: feed.present,
      route,
      targets: ZUBEHOER_ZIEL,
    })
    if (queue.length) await enqueue(queue, kind)
  }

  /* An accessory's kind and, where it is bound to a model family, that
     family — an SD 1.5 file on an XL model was a real mishap, so the answer
     stands on the page. A picture model names its class the same way. */
  const kindWord = $derived(card.zubehoer ? t(SORTE_LABEL[card.sorte] ?? 'katalog.sorte_vae') : '')
  const classWord = $derived(card.klasse ? (familyOf(card.klasse)?.label ?? card.klasse) : '')
  const name = $derived(card.nameKey ? t(card.nameKey) : card.name)
</script>

<SubHead title={name} {onback} />

<Group>
  <Line label={card.von} />
  {#if kindWord}<Line label={kindWord} />{/if}
  {#if classWord}<Line label={classWord} />{/if}
  {#each card.zubehoer ? [] : (card.faehigkeiten ?? []) as ability (ability)}
    <Line label={t(CAN[ability])} value="" />
  {/each}
  {#if memory}<Line label={t('modell.vram_label')} value={`${memory} GB`} />{/if}
</Group>

<Group>
  <div class="sentence">{t(card.langsatz ?? card.satz)}</div>
  {#if hasPage}
    <Action label={t('editor.quelle_hf')} onclick={() => window.open(`https://huggingface.co/${first.id}`, '_blank')} />
  {/if}
</Group>

<Group title={t('katalog.dateien')}>
  {#each card.fassungen as build (build.id + build.datei)}
    {@const phase = buildState(build, feed.present, feed.stand)}
    {@const progress = buildProgress(build, feed.stand)}
    <button class="build" class:recommended={build === recommended} onclick={() => fetchBuild(build)}>
      <span class="who">
        <span class="name">{build.name}</span>
        <span class="fit">{fitWord(build)}</span>
        {#if progress}
          <span class="fit">
            {partWord(progress) ? `${partWord(progress)} · ` : ''}{gigabytes(progress.loaded)} / {gigabytes(progress.total)} GB
          </span>
        {/if}
      </span>
      <span class="state">{t('modell.gb', { zahl: build.groesse })} · {stateWord(build)}</span>
      {#if phase !== 'neu'}
        <Leuchtpunkt farbe={phase === 'bereit' ? 'gruen' : 'blau'} groesse={11} />
      {/if}
    </button>
  {/each}
  {#if card.fassungen.some((build) => buildState(build, feed.present, feed.stand) === 'laedt')}
    <Action label={t('katalog.abbrechen')} onclick={cancelDownload} />
  {/if}
</Group>

<style>
  .sentence {
    padding: 6px 12px 6px 10px;
    color: var(--text-leise);
    font: 400 var(--schrift-text) var(--schrift);
    line-height: 1.45;
  }
  .build {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    min-height: var(--menuezeile);
    box-sizing: border-box;
    padding: 6px 12px 6px 10px;
    border: none;
    border-radius: 9px;
    background: none;
    color: var(--rahmen-text, var(--text-leise));
    font: 500 var(--schrift-text) var(--schrift);
    text-align: left;
  }
  .build:active {
    background: color-mix(in srgb, var(--text) 4%, transparent);
  }
  .recommended .name {
    color: var(--text);
  }
  .who {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .name {
    overflow-wrap: anywhere;
  }
  .fit {
    color: var(--text-still);
    font: 400 var(--schrift-hinweis) var(--schrift);
  }
  .state {
    flex: none;
    color: var(--text-still);
    font: 400 var(--schrift-hinweis) var(--schrift);
    font-variant-numeric: tabular-nums;
  }
</style>
