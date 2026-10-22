<script>
  /* The files of one found repository: what each is, its size, and one tap
     to fetch it with whatever belongs to it (a projector, the parts of a
     picture model). A file that lies here already says so; one being fetched
     shows how far it is. */
  import { api } from '../../lib/api.js'
  import { t } from '../../lib/texte.svelte.js'
  import { melde } from '../../lib/zustand.svelte.js'
  import { LOGOS } from '../../lib/logos.js'
  import Leuchtpunkt from '../../teile/Leuchtpunkt.svelte'
  import SubHead from '../parts/SubHead.svelte'
  import Group from '../parts/Group.svelte'
  import Line from '../parts/Line.svelte'
  import { feed, enqueue } from '../downloadFeed.svelte.js'
  import { planDownload, localName, shortCount } from '../catalog.js'

  let { hit, art, onback } = $props()

  let files = $state(null)
  let projector = $state(null)
  let heads = new Map()

  $effect(() => {
    const repo = hit.id
    files = null
    projector = null
    heads = new Map()
    api
      .modellDateien(repo, art)
      .then((answer) => {
        if (repo !== hit.id) return
        files = answer.dateien
        projector = answer.mmproj
      })
      .catch((error) => {
        melde(error.message, 'fehler')
        files = []
      })
  })

  const isThere = (file) => !file.collision && feed.present.includes(localName(file))
  const isFetching = (file) =>
    Boolean(feed.stand) && !feed.stand.fertig && !feed.stand.fehler && feed.stand.datei === localName(file)

  /* A picture file brings its kit with its head: the tap waits for the
     row's answer, so a model is never fetched without its parts. */
  async function headOf(file) {
    if (art !== 'bild') return file
    let pending = heads.get(file.datei)
    if (!pending) {
      pending = api.fileHead(hit.id, file)
      heads.set(file.datei, pending)
      pending.catch(() => heads.delete(file.datei))
    }
    return pending
  }

  async function fetchFile(file) {
    let full
    try {
      full = await headOf(file)
    } catch (error) {
      melde(error.message, 'fehler')
      return
    }
    const plan = planDownload({
      repo: hit.id,
      file: full,
      projector,
      present: feed.present,
      partLists: feed.partLists,
    })
    for (const tie of plan.ties) {
      try {
        await api.modellHolen(tie.repo, tie.datei, tie.ziel, tie.gehoert_zu, tie.rolle, 'bild', tie.unterordner)
      } catch (error) {
        melde(error.message, 'fehler')
      }
    }
    if (plan.queue.length) await enqueue(plan.queue, art)
  }

  /* A file that lies here can still be missing parts: a picture model's kit
     is read from its head when it is tapped, so there is nothing to fetch
     only if the plan comes out empty. */
  const tappable = (file) =>
    !isFetching(file) && (!isThere(file) || art === 'bild' || Boolean(file.bausatz))

  function stateOf(file) {
    if (isFetching(file)) return `${Math.round((feed.stand.anteil ?? 0) * 100)} %`
    if (isThere(file)) return t('downloads.fertig')
    return t('katalog.herunterladen')
  }
</script>

<SubHead title={hit.name} {onback} />

<Group>
  <Line label={hit.anbieter} value={`${shortCount(hit.ladungen)} ↓`} />
  <Line label={t('katalog.von_hf')} value={hit.id} />
</Group>

<Group title={t('katalog.dateien')}>
  {#if files === null}
    <Line label={t('modell.suche_laeuft')} />
  {:else if !files.length}
    <Line label={t('modell.keine_treffer')} />
  {/if}
  {#each files ?? [] as file (file.datei)}
    <button class="file" onclick={() => tappable(file) && fetchFile(file)}>
      <span class="name">{localName(file)}</span>
      <span class="state">{file.groesse_gb.toFixed(1)} GB · {stateOf(file)}</span>
      {#if isThere(file) || isFetching(file)}
        <Leuchtpunkt farbe={isThere(file) ? 'gruen' : 'blau'} groesse={11} />
      {/if}
    </button>
  {/each}
</Group>

<style>
  /* The name wraps, the state keeps its place: a long file name never
     pushes the progress out of the row. */
  .file {
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
  .file:active {
    background: color-mix(in srgb, var(--text) 4%, transparent);
  }
  .name {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .state {
    flex: none;
    color: var(--text-still);
    font: 400 var(--schrift-hinweis) var(--schrift);
    font-variant-numeric: tabular-nums;
  }
</style>
