<script>
  /* The settings of one local model — temperature, sampling, lengths — the
     very table the desktop shows, under the model's name. */
  import { t } from '../../lib/texte.svelte.js'
  import Parametertafel from '../../teile/Parametertafel.svelte'
  import SubHead from '../parts/SubHead.svelte'

  let { model, onback } = $props()
</script>

<SubHead title={model.name} {onback} />
<div class="table">
  <Parametertafel modell={model} />
</div>

<style>
  .table {
    padding-bottom: 16px;
  }
</style>
