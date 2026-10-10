<script>
  /* A PDF, drawn by the browser's own viewer: the one file the program
     shows that is not text. The rail beside the chat and the view over the
     window both show it through this frame, so the viewer is asked for the
     same things in both and its rim is cut the same way.

     Three switches for the viewer ride behind the hash of the address.
     Left alone, the viewer draws a dark bar of its own over the pages —
     page number, zoom, rotate, a download of its own — where the house
     already has its download, and a strip of small pages beside them where
     it finds the room. `toolbar=0` takes the bar away and `navpanes=0` the
     strip. Without its bar the viewer sets the page larger than the frame,
     so `view=FitH` fits it to the frame's width. Only the frame gets the
     switches: whoever saves the file goes by the plain address.

     Not sandboxed: a sandboxed frame may not load the viewer. What it
     shows is this service's own file route, and that route says "show"
     for a PDF and for nothing else. */
  let { address, title } = $props()
  const frameAddress = $derived(address ? `${address}#toolbar=0&navpanes=0&view=FitH` : '')
</script>

<div class="cut">
  <iframe {title} src={frameAddress}></iframe>
</div>

<style>
  /* The viewer lays a dark rim around the sheet it draws: the room for the
     page's shadow, a few pixels that grow with the width of the frame.
     Inside a rounded page that rim took the corners — the rounding cut the
     rim, and the white sheet stood square inside it.

     So the frame is a little wider than what holds it and starts a little
     above it, and this layer cuts it at the holder's own rounding: the rim
     falls outside, the sheet reaches the edge and wears the corners of
     whatever it lies in. The rim is a share of the width, so the overhang
     is one too. The shares are those of a sheet of A4 or Letter fitted to
     the width; a sheet of another shape keeps a hairline of the rim or
     loses one of its own edge. Whatever holds the frame is positioned and
     has a size of its own. */
  .cut {
    position: absolute;
    inset: 0;
    overflow: hidden;
    border-radius: inherit;
    container-type: inline-size;
  }
  iframe {
    position: absolute;
    top: -0.45cqw;
    left: -0.63cqw;
    width: calc(100% + 1.26cqw);
    height: calc(100% + 0.45cqw);
    border: none;
  }
</style>
