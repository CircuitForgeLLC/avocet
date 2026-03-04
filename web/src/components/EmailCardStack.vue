<template>
  <div
    class="card-stack"
    :class="{ 'bucket-mode': isBucketMode && motion.rich.value }"
    ref="stackEl"
    :draggable="motion.rich.value"
    @dragstart="onDragStart"
    @dragend="onDragEnd"
  >
    <!-- Depth shadow cards (visual stack effect) -->
    <div class="card-shadow card-shadow-2" aria-hidden="true" />
    <div class="card-shadow card-shadow-1" aria-hidden="true" />

    <!-- Active card -->
    <div
      class="card-wrapper"
      ref="cardEl"
      :class="dismissClass"
      :style="cardStyle"
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
import { useSwipe } from '@vueuse/core'
import { useMotion } from '../composables/useMotion'
import EmailCard from './EmailCard.vue'
import type { QueueItem } from '../stores/label'

const props = defineProps<{
  item: QueueItem
  isBucketMode: boolean
  dismissType?: 'label' | 'skip' | 'discard' | null
}>()

const emit = defineEmits<{
  label:     [name: string]
  skip:      []
  discard:   []
  'drag-start': []
  'drag-end':   []
}>()

const motion    = useMotion()
const cardEl    = ref<HTMLElement | null>(null)
const stackEl   = ref<HTMLElement | null>(null)
const isExpanded = ref(false)
const dragX     = ref(0)

const { isSwiping, lengthX } = useSwipe(cardEl, {
  threshold: 60,
  onSwipeEnd(_, dir) {
    if (dir === 'left')  emit('discard')
    if (dir === 'right') emit('skip')
    dragX.value = 0
  },
  onSwipe() {
    if (motion.rich.value) dragX.value = lengthX.value * -1
  },
})

const dismissClass = computed(() => {
  if (!props.dismissType) return null
  return `dismiss-${props.dismissType}`
})

const cardStyle = computed(() => {
  if (!motion.rich.value || !isSwiping.value) return {}
  const tilt    = dragX.value * 0.05
  const opacity = Math.abs(dragX.value) > 20 ? 0.9 : 1
  const color   = dragX.value < -20 ? 'rgba(244,67,54,0.15)'
                : dragX.value >  20 ? 'rgba(255,152,0,0.15)'
                : 'transparent'
  return {
    transform: `translateX(${dragX.value}px) rotate(${tilt}deg)`,
    opacity,
    background: color,
    transition: isSwiping.value ? 'none' : 'all 0.3s ease',
  }
})

function onDragStart(e: DragEvent) {
  if (motion.rich.value && e.dataTransfer) {
    // Custom drag ghost: small crumpled-paper ball
    const ghost = document.createElement('div')
    ghost.setAttribute('aria-hidden', 'true')
    Object.assign(ghost.style, {
      position: 'fixed',
      top: '-200px',
      left: '0',
      width: '80px',
      height: '80px',
      borderRadius: '50%',
      background: '#e4ebf5',
      border: '3px solid #2A6080',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontSize: '1.75rem',
      boxShadow: '0 4px 20px rgba(0,0,0,0.25)',
      transform: 'rotate(-5deg)',
    })
    ghost.textContent = '✉️'
    document.body.appendChild(ghost)
    e.dataTransfer.setDragImage(ghost, 40, 40)
    // Remove after browser captures — RAF is too fast, 0ms timeout works
    setTimeout(() => {
      if (document.body.contains(ghost)) document.body.removeChild(ghost)
    }, 0)
  }
  emit('drag-start')
}
function onDragEnd()   { emit('drag-end')   }
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
  transform: scale(0.25) rotate(-4deg);
  transform-origin: top center;
  border-radius: 50% !important;
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
  will-change: transform, opacity;
  transition:
    transform 280ms cubic-bezier(0.34, 1.56, 0.64, 1),
    border-radius 280ms cubic-bezier(0.34, 1.56, 0.64, 1),
    opacity 280ms ease;
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
  .card-stack.bucket-mode .card-wrapper {
    transition: none;
  }
}
</style>
