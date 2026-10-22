<script module>
  import { handbuchOeffnen } from '../../lib/handbuch.js'

  /* A row in the list that opens the manual in a window of its own — as the
     settings menu of the desktop does — instead of a page over the chat. */
  export const meta = {
    name: 'help', title: 'menue.hilfe', sign: 'dokument_zeilen', place: 'list', order: 37,
    action: handbuchOeffnen,
  }
</script>
