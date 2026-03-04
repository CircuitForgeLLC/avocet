<template>
  <div
    class="card-stack"
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

function onDragStart() { emit('drag-start') }
function onDragEnd()   { emit('drag-end')   }
</script>

<style scoped>
.card-stack {
  position: relative;
  min-height: 200px;
}

.card-shadow {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  border-radius: var(--radius-card, 1rem);
  background: var(--color-surface-raised, #fff);
  border: 1px solid var(--color-border, #e0e4ed);
}
.card-shadow-1 { transform: translateY(8px) scale(0.97); opacity: 0.6; }
.card-shadow-2 { transform: translateY(16px) scale(0.94); opacity: 0.35; }

.card-wrapper {
  position: relative;
  z-index: 1;
  border-radius: var(--radius-card, 1rem);
  background: var(--color-surface-raised, #fff);
  will-change: transform, opacity;
}

/* Dismissal animations — only active under .rich-motion on root */
:global(.rich-motion) .card-wrapper.dismiss-label {
  animation: fileAway var(--card-dismiss, 350ms ease-in) forwards;
}
:global(.rich-motion) .card-wrapper.dismiss-discard {
  animation: crumple var(--card-dismiss, 350ms ease-in) forwards;
}
:global(.rich-motion) .card-wrapper.dismiss-skip {
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
</style>
