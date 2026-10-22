<script>
  /* The schedules and, under them, the scripts a schedule may start: the
     desktop's two parts, one under the other. A schedule is made or changed
     in the phone's sheet over the whole width, not in the desktop's pop-up. */
  import { t } from '../../lib/texte.svelte.js'
  import SettingsCronjobs from '../../teile/SettingsCronjobs.svelte'
  import Skriptordner from '../../teile/Skriptordner.svelte'
  import Sheet from '../Sheet.svelte'
</script>

<SettingsCronjobs onzahlen={() => {}} Blatt={Sheet} />
<h4 class="scripts">{t('cronjobs.abschnitt_skripte')}</h4>
<Skriptordner />

<style>
  .scripts {
    margin: 18px 10px 6px;
    color: var(--text-still);
    font: 500 var(--schrift-hinweis) var(--schrift);
  }
</style>
