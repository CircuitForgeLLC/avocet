<template>
  <div
    class="card-stack"
    :class="{ 'bucket-mode': isBucketMode && motion.rich.value }"
  >
    <!-- Depth shadow cards (visual stack effect) -->
    <div class="card-shadow card-shadow-2" aria-hidden="true" />
    <div class="card-shadow card-shadow-1" aria-hidden="true" />

    <!-- Active card -->
    <div
      class="card-wrapper"
      ref="cardEl"
      :class="{ 'is-held': isHeld }"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerCancel"
    >
      <EmailCard
        :item="item"
        :expanded="isExpanded"
        @expand="isExpanded = true"
        @collapse="isExpanded = false"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useMotion } from '../composables/useMotion'
import { useCardAnimation } from '../composables/useCardAnimation'
import EmailCard from './EmailCard.vue'
import type { QueueItem } from '../stores/label'

const props = defineProps<{
  item: QueueItem
  isBucketMode: boolean
  dismissType?: 'label' | 'skip' | 'discard' | null
}>()

const emit = defineEmits<{
  label:          [name: string]
  skip:           []
  discard:        []
  'drag-start':   []
  'drag-end':     []
  'zone-hover':   ['discard' | 'skip' | null]
  'bucket-hover': [string | null]
}>()

const motion     = useMotion()
const cardEl     = ref<HTMLElement | null>(null)
const isExpanded = ref(false)

const { pickup, setDragPosition, snapBack, animateDismiss, updateAura, reset } = useCardAnimation(cardEl, motion)

watch(() => props.dismissType, (type) => {
  if (type) animateDismiss(type)
})

// When a new card loads into the same element, clear any inline styles left by the previous animation
watch(() => props.item.id, () => {
  reset()
  isExpanded.value = false
})

// Toss gesture state
const isHeld            = ref(false)
const pickupX           = ref(0)
const pickupY           = ref(0)
const hoveredZone       = ref<'discard' | 'skip' | null>(null)
const hoveredBucketName = ref<string | null>(null)

// Zone threshold: 7% of viewport width on each side
const ZONE_PCT = 0.07

// Fling detection — Option B: speed + direction alignment
// Plain array (not ref) — drives no template state, updates on every pointermove
const FLING_SPEED_PX_S = 600   // px/s minimum to qualify as a fling
const FLING_ALIGN      = 0.707 // cos(45°) — velocity must point within 45° of horizontal
const FLING_WINDOW_MS  = 50    // rolling sample window in ms
let velocityBuf: { x: number; y: number; t: number }[] = []

function onPointerDown(e: PointerEvent) {
  if (!motion.rich.value) return
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  pickupX.value = e.clientX
  pickupY.value = e.clientY
  isHeld.value = true
  pickup()
  hoveredZone.value = null
  hoveredBucketName.value = null
  velocityBuf = []
  emit('drag-start')
}

function onPointerMove(e: PointerEvent) {
  if (!isHeld.value) return
  const dx = e.clientX - pickupX.value
  const dy = e.clientY - pickupY.value
  setDragPosition(dx, dy)

  // Rolling velocity buffer — keep only the last FLING_WINDOW_MS of samples
  const now = performance.now()
  velocityBuf.push({ x: e.clientX, y: e.clientY, t: now })
  while (velocityBuf.length > 1 && now - velocityBuf[0].t > FLING_WINDOW_MS) {
    velocityBuf.shift()
  }

  const vw = window.innerWidth
  const zone: 'discard' | 'skip' | null =
    e.clientX < vw * ZONE_PCT          ? 'discard' :
    e.clientX > vw * (1 - ZONE_PCT)   ? 'skip' :
    null
  if (zone !== hoveredZone.value) {
    hoveredZone.value = zone
    emit('zone-hover', zone)
  }

  // Bucket detection via hit-test (works through overlapping elements).
  // Optional chain guards against JSDOM in tests (doesn't implement elementsFromPoint).
  const els = document.elementsFromPoint?.(e.clientX, e.clientY) ?? []
  const bucket = els.find(el => el.hasAttribute('data-label-key'))
  const bucketName = bucket?.getAttribute('data-label-key') ?? null
  if (bucketName !== hoveredBucketName.value) {
    hoveredBucketName.value = bucketName
    emit('bucket-hover', bucketName)
  }
  updateAura(hoveredZone.value, hoveredBucketName.value)
}

function onPointerUp(e: PointerEvent) {
  if (!isHeld.value) return
  ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
  isHeld.value = false
  emit('drag-end')
  emit('zone-hover', null)
  emit('bucket-hover', null)

  // Fling detection (Option B): fires before zone check so a fast fling
  // resolves even if the pointer didn't reach the 7% edge zone
  if (hoveredZone.value === null && hoveredBucketName.value === null
      && velocityBuf.length >= 2) {
    const oldest = velocityBuf[0]
    const newest = velocityBuf[velocityBuf.length - 1]
    const dt = (newest.t - oldest.t) / 1000 // seconds
    if (dt > 0) {
      const vx    = (newest.x - oldest.x) / dt
      const vy    = (newest.y - oldest.y) / dt
      const speed = Math.sqrt(vx * vx + vy * vy)
      // Require: fast enough AND velocity points within 45° of horizontal
      if (speed >= FLING_SPEED_PX_S && Math.abs(vx) / speed >= FLING_ALIGN) {
        velocityBuf = []
        emit(vx < 0 ? 'discard' : 'skip')
        return
      }
    }
  }
  velocityBuf = []

  if (hoveredZone.value === 'discard') {
    hoveredZone.value = null
    hoveredBucketName.value = null
    emit('discard')
  } else if (hoveredZone.value === 'skip') {
    hoveredZone.value = null
    hoveredBucketName.value = null
    emit('skip')
  } else if (hoveredBucketName.value) {
    const name = hoveredBucketName.value
    hoveredZone.value = null
    hoveredBucketName.value = null
    emit('label', name)
  } else {
    // Snap back
    snapBack()
    updateAura(null, null)
    hoveredZone.value = null
    hoveredBucketName.value = null
  }
}

function onPointerCancel(e: PointerEvent) {
  if (!isHeld.value) return
  ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
  isHeld.value = false
  snapBack()
  updateAura(null, null)
  hoveredZone.value = null
  hoveredBucketName.value = null
  velocityBuf = []
  emit('drag-end')
  emit('zone-hover', null)
  emit('bucket-hover', null)
}
</script>

<style scoped>
.card-stack {
  position: relative;
  min-height: 200px;
  max-height: 2000px;  /* effectively unlimited — needed for max-height transition */
  overflow: hidden;
  transition:
    max-height 280ms cubic-bezier(0.34, 1.56, 0.64, 1),
    min-height 280ms cubic-bezier(0.34, 1.56, 0.64, 1);
}

/* Bucket mode: collapse card stack to a small pill so buckets get more room */
.card-stack.bucket-mode {
  min-height: 0;
  max-height: 90px;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  overflow: visible; /* ball must escape the collapsed stack bounds */
}

.card-stack.bucket-mode .card-shadow {
  opacity: 0;
  transition: opacity 180ms ease;
}

.card-stack.bucket-mode .card-wrapper {
  clip-path: inset(35% 15% round 0.75rem);
  opacity: 0.35;
  pointer-events: none;
}

.card-shadow {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  border-radius: var(--radius-card, 1rem);
  background: var(--color-surface-raised, #fff);
  border: 1px solid var(--color-border, #e0e4ed);
  transition: opacity 180ms ease;
}
.card-shadow-1 { transform: translateY(8px) scale(0.97); opacity: 0.6; }
.card-shadow-2 { transform: translateY(16px) scale(0.94); opacity: 0.35; }

.card-wrapper {
  position: relative;
  z-index: 1;
  border-radius: var(--radius-card, 1rem);
  background: var(--color-surface-raised, #fff);
  will-change: clip-path, opacity;
  clip-path: inset(0% 0% round 1rem);
  touch-action: none;   /* prevent scroll from stealing the gesture */
  cursor: grab;
  transition:
    clip-path 260ms cubic-bezier(0.4, 0, 0.2, 1),
    opacity 220ms ease;
}
.card-wrapper.is-held {
  cursor: grabbing;
  /* Override bucket-mode clip and opacity so the held ball renders cleanly */
  clip-path: none !important;
  opacity: 1 !important;
  pointer-events: auto !important;
}

@media (prefers-reduced-motion: reduce) {
  .card-stack,
  .card-wrapper {
    transition: none;
  }
}
</style>
