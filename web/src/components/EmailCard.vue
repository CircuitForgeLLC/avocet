<template>
  <article class="email-card" :class="{ expanded }">
    <header class="card-header">
      <h2 class="subject">{{ item.subject }}</h2>
      <div class="meta">
        <span class="from" :title="item.from">{{ item.from }}</span>
        <time class="date" :datetime="item.date">{{ item.date }}</time>
      </div>
    </header>

    <div class="card-body">
      <p class="body-text">{{ displayBody }}</p>
    </div>

    <footer class="card-footer">
      <button
        v-if="!expanded"
        data-testid="expand-btn"
        class="expand-btn"
        aria-label="Expand full email"
        @click="$emit('expand')"
      >
        Show more ↓
      </button>
      <button
        v-else
        data-testid="collapse-btn"
        class="expand-btn"
        aria-label="Collapse email"
        @click="$emit('collapse')"
      >
        Show less ↑
      </button>
    </footer>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { QueueItem } from '../stores/label'

const props = defineProps<{ item: QueueItem; expanded?: boolean }>()
defineEmits<{ expand: []; collapse: [] }>()

const PREVIEW_LINES = 6

const displayBody = computed(() => {
  if (props.expanded) return props.item.body
  const lines = props.item.body.split('\n').slice(0, PREVIEW_LINES).join('\n')
  return lines.length < props.item.body.length ? lines + '…' : lines
})
</script>

<style scoped>
.email-card {
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  font-family: var(--font-body);
  box-shadow: var(--shadow-md);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.subject {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--color-text);
  margin: 0;
  line-height: 1.4;
}

.meta {
  display: flex;
  gap: var(--space-4);
  font-size: 0.875rem;
  color: var(--color-text-muted);
  margin-top: var(--space-2);
  flex-wrap: wrap;
}

.body-text {
  color: var(--color-text);
  font-size: 0.9375rem;
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: break-word;
  margin: 0;
}

.card-footer {
  display: flex;
  justify-content: flex-end;
}

.expand-btn {
  background: none;
  border: none;
  color: var(--app-primary);
  cursor: pointer;
  font-size: 0.875rem;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  transition: opacity var(--transition);
}

.expand-btn:hover { opacity: 0.75; }
.expand-btn:focus-visible {
  outline: 2px solid var(--app-primary);
  outline-offset: 3px;
}
</style>
