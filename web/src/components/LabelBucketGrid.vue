<template>
  <div class="label-grid" :class="{ 'bucket-mode': isBucketMode }" role="group" aria-label="Label buttons">
    <button
      v-for="label in labels"
      :key="label.key"
      data-testid="label-btn"
      class="label-btn"
      :class="{ 'is-drop-target': dragOverLabel === label.name }"
      :style="{ '--label-color': label.color }"
      :aria-label="`Label as ${label.name.replace(/_/g, ' ')} (key: ${label.key})`"
      @click="$emit('label', label.name)"
      @dragover.prevent="dragOverLabel = label.name"
      @dragleave="dragOverLabel = null"
      @drop.prevent="onDrop(label.name)"
    >
      <span class="key-hint" aria-hidden="true">{{ label.key }}</span>
      <span class="emoji" aria-hidden="true">{{ label.emoji }}</span>
      <span class="label-name">{{ label.name.replace(/_/g, '\u00a0') }}</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

interface Label { name: string; emoji: string; color: string; key: string }

const props = defineProps<{ labels: Label[]; isBucketMode: boolean }>()
const emit  = defineEmits<{ label: [name: string] }>()

const dragOverLabel = ref<string | null>(null)

function onDrop(name: string) {
  dragOverLabel.value = null
  emit('label', name)
}
</script>

<style scoped>
.label-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.5rem;
  transition: gap var(--bucket-expand, 250ms cubic-bezier(0.34, 1.56, 0.64, 1)),
              padding var(--bucket-expand, 250ms cubic-bezier(0.34, 1.56, 0.64, 1));
}

/* 10th button (hired / key h) — centered below the 3×3 like a numpad 0 */
.label-btn:last-child {
  grid-column: 1 / -1;
  max-width: calc(33.333% - 0.34rem);
  justify-self: center;
}

.label-grid.bucket-mode {
  gap: 1rem;
  padding: 1rem;
}

.label-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.25rem;
  min-height: 44px;          /* Touch target */
  padding: 0.5rem 0.25rem;
  border-radius: 0.5rem;
  border: 2px solid var(--label-color, #607D8B);
  background: transparent;
  color: var(--color-text, #1a2338);
  cursor: pointer;
  transition: min-height var(--bucket-expand, 250ms cubic-bezier(0.34, 1.56, 0.64, 1)),
              padding var(--bucket-expand, 250ms cubic-bezier(0.34, 1.56, 0.64, 1)),
              border-width var(--bucket-expand, 250ms cubic-bezier(0.34, 1.56, 0.64, 1)),
              font-size var(--bucket-expand, 250ms cubic-bezier(0.34, 1.56, 0.64, 1)),
              background var(--transition, 200ms ease),
              transform var(--transition, 200ms ease),
              box-shadow var(--transition, 200ms ease),
              opacity var(--transition, 200ms ease);
  font-family: var(--font-body, sans-serif);
}

.label-grid.bucket-mode .label-btn {
  min-height: 80px;
  padding: 1rem 0.5rem;
  border-width: 3px;
  font-size: 1.1rem;
}

.label-btn.is-drop-target {
  background: var(--label-color, #607D8B);
  color: #fff;
  transform: scale(1.08);
  box-shadow: 0 0 16px color-mix(in srgb, var(--label-color, #607D8B) 60%, transparent);
}

.label-btn:hover:not(.is-drop-target) {
  background: color-mix(in srgb, var(--label-color, #607D8B) 12%, transparent);
}

.key-hint {
  font-size: 0.65rem;
  font-family: var(--font-mono, monospace);
  opacity: 0.55;
  line-height: 1;
}

.emoji {
  font-size: 1.25rem;
  line-height: 1;
}

.label-name {
  font-size: 0.7rem;
  text-align: center;
  line-height: 1.2;
  word-break: break-word;
  hyphens: auto;
}

/* Reduced-motion fallback */
@media (prefers-reduced-motion: reduce) {
  .label-grid,
  .label-btn {
    transition: none;
  }
}
</style>
