<script>
  /* Why a server's last start failed, while that is its state: the build of
     the server does not know the architecture of the model. A line that
     stands on the server's page, not a notice that passes. Every server
     page carries it from its own answer, so a start nobody watched leaves
     its reason where the next visit finds it. */
  import { t } from '../lib/texte.svelte.js'

  let { arch = null } = $props()
</script>

{#if arch}
  <p class="start-error">{t('modell.unknown_architecture', { arch })}</p>
{/if}

<style>
  .start-error {
    margin: 0;
    color: var(--rot);
    font-size: 13px;
  }
</style>
