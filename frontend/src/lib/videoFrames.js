/* The frames of a control video as pictures, taken by the browser itself.

   sd.cpp reads a control video as a row of pictures (sd-cli
   `--control-video`: a folder of frames in name order; the server's
   `control_frames`: pictures in order). The browser plays every video it can
   show, so it is the one decoder at hand on every system: the video is
   stepped through at the frame rate the new video is drawn at, and each
   frame is drawn onto a
   canvas and handed back as a PNG file. Nothing is installed for it, and no
   file leaves the machine before the frames go up like any other picture. */

function once(element, name) {
  return new Promise((resolve, reject) => {
    const done = () => { element.removeEventListener('error', failed); resolve() }
    const failed = () => {
      element.removeEventListener(name, done)
      reject(new Error(element.error?.message || 'video'))
    }
    element.addEventListener(name, done, { once: true })
    element.addEventListener('error', failed, { once: true })
  })
}

function png(canvas) {
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/png'))
}

/**
 * Up to `count` frames of `file`, `fps` of them to a second of the video,
 * from its start — fewer when the video ends first.
 */
export async function videoFrames(file, fps, count) {
  const address = URL.createObjectURL(file)
  const video = document.createElement('video')
  video.muted = true
  video.preload = 'auto'
  video.src = address
  try {
    await once(video, 'loadeddata')
    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const context = canvas.getContext('2d')
    const frames = []
    for (let index = 0; index < count; index += 1) {
      const time = index / fps
      if (time > video.duration) break
      // The first frame is there once the data is: no seek to wait for.
      if (index > 0) {
        video.currentTime = time
        await once(video, 'seeked')
      }
      context.drawImage(video, 0, 0)
      const blob = await png(canvas)
      if (!blob) break
      frames.push(new File([blob], `frame-${index}.png`, { type: 'image/png' }))
    }
    return frames
  } finally {
    video.removeAttribute('src')
    video.load()
    URL.revokeObjectURL(address)
  }
}
