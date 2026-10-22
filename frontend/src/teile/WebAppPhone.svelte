<script>
  /* The phone beside the web app's setup: three shots of the phone page run
     through its screen, one after the other. The mouse wheel or a drag
     pages through them by hand, a dot jumps to one, and the run waits while
     the pointer is on the phone — or for good where the person has asked
     the system for less motion. */
  import { t } from '../lib/texte.svelte.js'
  import chat from '../assets/web-app/chat.jpg'
  import studio from '../assets/web-app/image-studio.jpg'
  import settings from '../assets/web-app/settings.jpg'

  const SHOTS = [
    { src: chat, name: 'webapp.picture_chat' },
    { src: studio, name: 'webapp.picture_image_studio' },
    { src: settings, name: 'webapp.picture_settings' },
  ]
  /* The screen's width in pixels: the strip moves by exactly one of it. */
  const SCREEN_WIDTH = 278
  const ADVANCE_MS = 3500
  /* Wheel notches that arrive within this are one flick, not several. */
  const WHEEL_LOCK_MS = 450
  const DRAG_PIXELS = 30

  let index = $state(0)
  let paused = $state(false)
  let dragging = $state(false)
  let dragStart = null
  let lastWheel = 0
  const reducedMotion =
    typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

  const show = (n) => {
    index = (n + SHOTS.length) % SHOTS.length
  }

  /* The run restarts from every hand on it, so a picture just chosen is
     not turned away from a moment later. */
  let timer = null
  function restartRun() {
    clearInterval(timer)
    if (reducedMotion) return
    timer = setInterval(() => {
      if (!paused && !dragging) show(index + 1)
    }, ADVANCE_MS)
  }
  $effect(() => {
    restartRun()
    return () => clearInterval(timer)
  })

  const page = (n) => {
    show(n)
    restartRun()
  }

  function onWheel(event) {
    event.preventDefault()
    const now = Date.now()
    if (now - lastWheel < WHEEL_LOCK_MS) return
    lastWheel = now
    const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY
    page(index + (delta > 0 ? 1 : -1))
  }

  function onDown(event) {
    dragStart = event.clientX
    dragging = true
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function onUp(event) {
    dragging = false
    if (dragStart === null) return
    const moved = event.clientX - dragStart
    dragStart = null
    if (Math.abs(moved) > DRAG_PIXELS) page(index + (moved < 0 ? 1 : -1))
  }
</script>

<div class="field">
  <div
    class="phone"
    class:dragging
    role="group"
    aria-label={t('webapp.phone')}
    title={t('webapp.browse')}
    onwheel={onWheel}
    onpointerdown={onDown}
    onpointerup={onUp}
    onpointercancel={onUp}
    onmouseenter={() => (paused = true)}
    onmouseleave={() => (paused = false)}
  >
    <div class="screen">
      <div class="strip" style="transform: translateX({-SCREEN_WIDTH * index}px)">
        {#each SHOTS as shot (shot.src)}
          <img src={shot.src} alt={t(shot.name)} draggable="false" />
        {/each}
      </div>
    </div>
  </div>
  <div class="dots">
    {#each SHOTS as shot, number (shot.src)}
      <button
        class:on={number === index}
        aria-label={t(shot.name)}
        aria-current={number === index}
        onclick={() => page(number)}
      ></button>
    {/each}
  </div>
  <div class="caption">{t(SHOTS[index].name)}</div>
</div>

<style>
  .field {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 14px;
    flex: none;
  }
  /* The device: a black body with a rim, the screen inset by its bezel.
     The two black and grey values are the phone, not the house's palette. */
  .phone {
    width: 300px;
    height: 652px;
    padding: 11px;
    border-radius: 52px;
    background: #0b0b0a;
    box-shadow: 0 0 0 2px #3a3a37, 0 24px 60px rgba(0, 0, 0, 0.45);
    cursor: grab;
    user-select: none;
    touch-action: pan-y;
  }
  .phone.dragging {
    cursor: grabbing;
  }
  .screen {
    width: 100%;
    height: 100%;
    border-radius: 42px;
    overflow: hidden;
    background: #1c1c1a;
  }
  .strip {
    display: flex;
    height: 100%;
    transition: transform 0.55s cubic-bezier(0.3, 0.7, 0.2, 1);
  }
  @media (prefers-reduced-motion: reduce) {
    .strip {
      transition: none;
    }
  }
  img {
    width: 278px;
    height: 100%;
    flex: none;
    object-fit: cover;
    object-position: top;
    pointer-events: none;
  }
  .dots {
    display: flex;
    gap: 8px;
  }
  .dots button {
    width: 8px;
    height: 8px;
    padding: 0;
    border: none;
    border-radius: 50%;
    background: var(--feldstrich);
    cursor: pointer;
  }
  .dots button.on {
    background: var(--text);
  }
  .caption {
    font-size: 12.5px;
    color: var(--text-still);
  }
</style>
