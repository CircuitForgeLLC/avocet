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
      :class="[dismissClass, { 'is-held': isHeld }]"
      :style="cardStyle"
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
import { ref, computed } from 'vue'
import { useMotion } from '../composables/useMotion'
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

// Toss gesture state
const isHeld            = ref(false)
const pickupX           = ref(0)
const pickupY           = ref(0)
const deltaX            = ref(0)
const deltaY            = ref(0)
const hoveredZone       = ref<'discard' | 'skip' | null>(null)
const hoveredBucketName = ref<string | null>(null)

// Zone threshold: 7% of viewport width on each side
const ZONE_PCT = 0.07

function onPointerDown(e: PointerEvent) {
  if (!motion.rich.value) return
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  pickupX.value = e.clientX
  pickupY.value = e.clientY
  deltaX.value = 0
  deltaY.value = 0
  isHeld.value = true
  hoveredZone.value = null
  hoveredBucketName.value = null
  emit('drag-start')
}

function onPointerMove(e: PointerEvent) {
  if (!isHeld.value) return
  deltaX.value = e.clientX - pickupX.value
  deltaY.value = e.clientY - pickupY.value

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
}

function onPointerUp(e: PointerEvent) {
  if (!isHeld.value) return
  ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
  isHeld.value = false
  emit('drag-end')
  emit('zone-hover', null)
  emit('bucket-hover', null)

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
    // Snap back — reset deltas
    deltaX.value = 0
    deltaY.value = 0
    hoveredZone.value = null
    hoveredBucketName.value = null
  }
}

function onPointerCancel(e: PointerEvent) {
  if (!isHeld.value) return
  ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
  isHeld.value = false
  deltaX.value = 0
  deltaY.value = 0
  hoveredZone.value = null
  hoveredBucketName.value = null
  emit('drag-end')
  emit('zone-hover', null)
  emit('bucket-hover', null)
}

const dismissClass = computed(() => {
  if (!props.dismissType) return null
  return `dismiss-${props.dismissType}`
})

const cardStyle = computed(() => {
  if (!motion.rich.value || !isHeld.value) return {}

  // Aura color: zone > bucket > neutral
  const aura =
    hoveredZone.value === 'discard'  ? 'rgba(244,67,54,0.25)'  :
    hoveredZone.value === 'skip'     ? 'rgba(255,152,0,0.25)'  :
    hoveredBucketName.value          ? 'rgba(42,96,128,0.20)'  :
    'transparent'

  return {
    transform:    `translate(${deltaX.value}px, ${deltaY.value}px) scale(0.35)`,
    borderRadius: '50%',
    background:   aura,
    transition:   'border-radius 150ms ease, background 150ms ease',
    cursor:       'grabbing',
    zIndex:       100,
    userSelect:   'none',
  }
})
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
}

/* Dismissal animations — dismiss class is only applied during the motion.rich await window,
   so no ancestor guard needed; :global(.rich-motion) was being miscompiled by Vue's scoped
   CSS transformer (dropping the descendant selector entirely). */
.card-wrapper.dismiss-label {
  animation: fileAway var(--card-dismiss, 350ms ease-in) forwards;
}
.card-wrapper.dismiss-discard {
  animation: crumple var(--card-dismiss, 350ms ease-in) forwards;
}
.card-wrapper.dismiss-skip {
  animation: slideUnder var(--card-skip, 300ms ease-out) forwards;
}

@keyframes fileAway {
  to { transform: translateY(-120%) scale(0.85); opacity: 0; }
}
@keyframes crumple {
  50% { transform: scale(0.95) rotate(2deg); filter: brightness(0.6) sepia(1) hue-rotate(-20deg); }
  to  { transform: scale(0) rotate(8deg); opacity: 0; }
}
@keyframes slideUnder {
  to { transform: translateX(110%) rotate(5deg); opacity: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .card-stack,
  .card-wrapper {
    transition: none;
  }
}
</style>
