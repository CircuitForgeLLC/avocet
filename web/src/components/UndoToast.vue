<template>
  <div class="undo-toast" role="status" aria-live="polite">
    <span class="toast-label">{{ label }}</span>
    <button class="undo-btn" @click="$emit('undo')">↩ Undo</button>
    <div class="timer-track" aria-hidden="true">
      <div class="timer-bar" :style="{ width: `${progress}%` }" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import type { LastAction } from '../stores/label'

const props = defineProps<{ action: LastAction }>()
const emit = defineEmits<{ undo: []; expire: [] }>()

const DURATION = 5000
const elapsed  = ref(0)
let start = 0
let raf = 0

const progress = computed(() => Math.max(0, 100 - (elapsed.value / DURATION) * 100))

const label = computed(() => {
  const name = props.action.item.subject
  if (props.action.type === 'label')   return `Labeled "${name}" as ${props.action.label}`
  if (props.action.type === 'discard') return `Discarded "${name}"`
  return `Skipped "${name}"`
})

function tick(ts: number) {
  elapsed.value = ts - start
  if (elapsed.value < DURATION) {
    raf = requestAnimationFrame(tick)
  } else {
    emit('expire')
  }
}

onMounted(() => { start = performance.now(); raf = requestAnimationFrame(tick) })
onUnmounted(() => cancelAnimationFrame(raf))
</script>

<style scoped>
.undo-toast {
  position: fixed;
  bottom: 1.5rem;
  left: 50%;
  transform: translateX(-50%);
  min-width: 280px;
  max-width: 480px;
  background: var(--color-surface-overlay, #1a2338);
  color: var(--color-text-inverse, #f0f4fc);
  border-radius: var(--radius-toast, 0.75rem);
  padding: 0.75rem 1rem 0;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  box-shadow: 0 4px 24px rgba(0,0,0,0.25);
  z-index: 1000;
}

.toast-label {
  flex: 1;
  font-size: 0.9rem;
  font-family: var(--font-body, sans-serif);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.undo-btn {
  flex-shrink: 0;
  padding: 0.3rem 0.75rem;
  border-radius: 0.375rem;
  border: 1px solid var(--app-primary, #5A9DBF);
  background: transparent;
  color: var(--app-primary, #5A9DBF);
  font-size: 0.85rem;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
  margin-bottom: 0.75rem;
}
.undo-btn:hover {
  background: var(--app-primary, #5A9DBF);
  color: #fff;
}

.timer-track {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: rgba(255,255,255,0.15);
  border-radius: 0 0 0.75rem 0.75rem;
  overflow: hidden;
}

.timer-bar {
  height: 100%;
  background: var(--app-primary, #5A9DBF);
  transition: width 0.1s linear;
}
</style>
