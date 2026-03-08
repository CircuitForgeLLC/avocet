import { type Ref } from 'vue'
import { animate, spring, utils } from 'animejs'

const BALL_SCALE      = 0.55
const BALL_RADIUS     = '50%'
const CARD_RADIUS     = '1rem'
const PICKUP_Y_OFFSET = 80     // px above finger
const PICKUP_DURATION = 200

// Anime.js v4: spring() takes an object { mass, stiffness, damping, velocity }
const SNAP_SPRING = spring({ mass: 1, stiffness: 80, damping: 10 })

interface Motion { rich: Ref<boolean> }

export function useCardAnimation(
  cardEl: Ref<HTMLElement | null>,
  motion: Motion,
) {
  function pickup() {
    if (!motion.rich.value || !cardEl.value) return
    // Anime.js v4: animate(target, params) — all props + timing in one object
    animate(cardEl.value, {
      scale:        BALL_SCALE,
      borderRadius: BALL_RADIUS,
      y:            -PICKUP_Y_OFFSET,
      duration:     PICKUP_DURATION,
      ease:         SNAP_SPRING,
    })
  }

  function setDragPosition(dx: number, dy: number) {
    if (!cardEl.value) return
    // utils.set() for instant (no-animation) position update — keeps Anime cache consistent
    utils.set(cardEl.value, { x: dx, y: dy - PICKUP_Y_OFFSET })
  }

  function snapBack() {
    if (!motion.rich.value || !cardEl.value) return
    animate(cardEl.value, {
      x:            0,
      y:            0,
      scale:        1,
      borderRadius: CARD_RADIUS,
      ease:         SNAP_SPRING,
    })
  }

  function animateDismiss(type: 'label' | 'skip' | 'discard') {
    if (!motion.rich.value || !cardEl.value) return
    const el = cardEl.value
    if (type === 'label') {
      animate(el, { y: '-120%', scale: 0.85, opacity: 0, duration: 280, ease: 'out(3)' })
    } else if (type === 'discard') {
      // Anime.js v4 keyframe array: array of param objects, each can have its own duration
      animate(el, {
        keyframes: [
          { scale: 0.95, rotate: 2,  filter: 'brightness(0.6) sepia(1) hue-rotate(-20deg)', duration: 140 },
          { scale: 0,    rotate: 8,  opacity: 0,                                             duration: 210 },
        ],
      })
    } else if (type === 'skip') {
      animate(el, { x: '110%', rotate: 5, opacity: 0, duration: 260, ease: 'out(2)' })
    }
  }

  const AURA_COLORS = {
    discard: 'rgba(244, 67, 54, 0.25)',
    skip:    'rgba(255, 152,  0, 0.25)',
    bucket:  'rgba(42,  96, 128, 0.20)',
    none:    'transparent',
  } as const

  function updateAura(zone: 'discard' | 'skip' | null, bucket: string | null) {
    if (!cardEl.value) return
    const color =
      zone === 'discard' ? AURA_COLORS.discard :
      zone === 'skip'    ? AURA_COLORS.skip    :
      bucket             ? AURA_COLORS.bucket  :
      AURA_COLORS.none
    utils.set(cardEl.value, { background: color })
  }

  function reset() {
    if (!cardEl.value) return
    // Instantly restore initial card state — called when a new item loads into the same element
    utils.set(cardEl.value, {
      x:            0,
      y:            0,
      scale:        1,
      opacity:      1,
      rotate:       0,
      borderRadius: CARD_RADIUS,
      background:   'transparent',
      filter:       'none',
    })
  }

  return { pickup, setDragPosition, snapBack, animateDismiss, updateAura, reset }
}
