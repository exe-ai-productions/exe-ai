/* The doc folder's filters: which project the start page stands on, and
   whose files it shows.

   The wall shows every file in one piece — no view switch; who brought a
   file is told by the plaque on its tile. Two things are left as a choice,
   both in the one list of the folder's row and only on the start page: the
   project, and the origin — the person's own files, an agent's, or a cron
   job's. Each is empty for "all of them", and they narrow together.

   `ORIGINS` are the three origins in the order the list shows them, by the
   names the service gives them (app/docfolder.py), each with the catalogue
   key of its word — written out, so every key stands in the source whole.

   Its own module for the same reason the preview's tabs and the
   terminal's runs have one: the rail mounts the doc folder only while it is
   the tool shown, so state kept in the component fell back on every switch
   to another tool and on every close of the rail. Kept here it stands for
   as long as the window is open. Memory only — after a reload every file
   is shown. */
export const ORIGINS = {
  user: 'docfolder.origin_user',
  agent: 'docfolder.origin_agent',
  cronjob: 'docfolder.origin_cronjob',
}

export const docFolderFilters = $state({ project: '', origin: '' })
