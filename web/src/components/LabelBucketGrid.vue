<template>
  <div class="label-grid" :class="{ 'bucket-mode': isBucketMode }" role="group" aria-label="Label buttons">
    <button
      v-for="label in displayLabels"
      :key="label.key"
      data-testid="label-btn"
      :data-label-key="label.name"
      class="label-btn"
      :class="{ 'is-drop-target': props.hoveredBucket === label.name }"
      :style="{ '--label-color': label.color }"
      :aria-label="`Label as ${label.name.replace(/_/g, ' ')} (key: ${label.key})`"
      @click="$emit('label', label.name)"
    >
      <span class="key-hint" aria-hidden="true">{{ label.key }}</span>
      <span class="emoji" aria-hidden="true">{{ label.emoji }}</span>
      <span class="label-name">{{ label.name.replace(/_/g, '\u00a0') }}</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Label { name: string; emoji: string; color: string; key: string }

const props = defineProps<{
  labels: Label[]
  isBucketMode: boolean
  hoveredBucket?: string | null
}>()
const emit = defineEmits<{ label: [name: string] }>()

// Numpad layout: reverse the row order of numeric keys (7-8-9 on top, 1-2-3 on bottom)
// Non-numeric keys (e.g. 'h' for hired) stay pinned after the grid.
const displayLabels = computed(() => {
  const numeric = props.labels.filter(l => !isNaN(Number(l.key)))
  const other   = props.labels.filter(l =>  isNaN(Number(l.key)))
  const rows: Label[][] = []
  for (let i = 0; i < numeric.length; i += 3) rows.push(numeric.slice(i, i + 3))
  return [...rows.reverse().flat(), ...other]
})
</script>

<style scoped>
.label-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.5rem;
  transition: gap var(--bucket-expand, 250ms cubic-bezier(0.34, 1.56, 0.64, 1)),
              padding var(--bucket-expand, 250ms cubic-bezier(0.34, 1.56, 0.64, 1));
}

/* 10th button (hired / key h) — full-width bar below the 3×3 */
.label-btn:last-child {
  grid-column: 1 / -1;
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
