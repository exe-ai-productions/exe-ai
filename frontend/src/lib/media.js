/* Whether a file the picture window made is a video rather than a still
   picture — by its ending, the one thing its name says (the service names
   a video after its container, app/image_switches.py `output_suffix`). An
   animated WebP plays in a picture element and counts as a picture. Works
   on a bare name and on an address with a query behind it. */
export function isVideo(name) {
  return /\.(webm|avi)(\?|#|$)/i.test(name || '')
}
