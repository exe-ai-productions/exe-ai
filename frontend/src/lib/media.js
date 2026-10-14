/* Whether a file is a still picture the page can draw as one — by its
   ending, the one thing its name says. These four are the page's whole
   list, and the endings the service shows as pictures too
   (app/api/v1/bilder.py, `ANZEIGBARE_ENDUNGEN`). Works on a bare name and
   on an address with a query behind it. */
export function isPicture(name) {
  return /\.(png|jpg|jpeg|webp)(\?|#|$)/i.test(name || '')
}

/* Whether a file the picture window made is a video rather than a still
   picture — by its ending, the one thing its name says (the service names
   a video after its container, app/image_switches.py `output_suffix`). An
   animated WebP plays in a picture element and counts as a picture. Works
   on a bare name and on an address with a query behind it. */
export function isVideo(name) {
  return /\.(webm|avi)(\?|#|$)/i.test(name || '')
}
