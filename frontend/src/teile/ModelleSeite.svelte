<script>
  /* The models: local and cloud, two menus of the window row, each with a
     sign of its own. This frame stands while either is open — it lies over
     the main area (Seitenrahmen.svelte) and keeps both menus mounted while
     closed, so each keeps what was chosen in it: a server, a provider, a
     number still being typed and saved a moment later. A click on a chat
     in the sidebar closes it, and so do a new chat, a run or the agent
     form asked for from the sidebar, Escape and a second click on the sign
     of the open menu (lib/zustand.svelte.js, `seitenSchliessen`). */
  import Seitenrahmen from './Seitenrahmen.svelte'
  import ModelleLokal from './ModelleLokal.svelte'
  import ModelleCloud from './ModelleCloud.svelte'
  import { t } from '../lib/texte.svelte.js'
  import { zustand } from '../lib/zustand.svelte.js'
</script>

<Seitenrahmen
  offen={zustand.lokalOffen || zustand.cloudOffen}
  beschriftung={zustand.cloudOffen ? t('menue.cloud') : t('menue.lokal')}
>
  <ModelleLokal offen={zustand.lokalOffen} />
  <ModelleCloud offen={zustand.cloudOffen} />
</Seitenrahmen>
