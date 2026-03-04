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
  grid-template-columns: repeat(5, 1fr);
  gap: var(--space-2);
  transition: all var(--bucket-expand);
}

/* Mobile: 3×3 numpad layout + hired at bottom */
@media (max-width: 480px) {
  .label-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

.label-grid.bucket-mode {
  gap: var(--space-4);
  padding: var(--space-3);
}

.label-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-1);
  border: 2px solid var(--label-color, var(--color-border));
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text);
  cursor: pointer;
  font-family: var(--font-body);
  transition: all var(--bucket-expand);
  min-height: 44px;  /* touch target */
}

.label-grid.bucket-mode .label-btn {
  padding: var(--space-6) var(--space-2);
  font-size: 1.15rem;
}

.label-btn:hover,
.label-btn:focus-visible {
  background: color-mix(in srgb, var(--label-color) 12%, transparent);
}

.label-btn:focus-visible {
  outline: 2px solid var(--label-color);
  outline-offset: 2px;
}

.label-btn.is-drop-target {
  background: var(--label-color);
  color: var(--color-text-inverse, #fff);
  transform: scale(1.08);
  box-shadow: 0 0 16px color-mix(in srgb, var(--label-color) 60%, transparent);
}

.key-hint {
  font-size: 0.7rem;
  font-weight: 700;
  opacity: 0.6;
  font-family: var(--font-mono);
}

.emoji { font-size: 1.2rem; line-height: 1; }

.label-name {
  font-size: 0.65rem;
  text-align: center;
  line-height: 1.2;
  word-break: break-word;
  color: var(--color-text-muted);
}

.label-grid.bucket-mode .label-name {
  font-size: 0.75rem;
  color: var(--color-text);
}
</style>
