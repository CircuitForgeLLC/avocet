<template>
  <div class="stats-view">
    <h1 class="page-title">📊 Statistics</h1>

    <div v-if="loading" class="loading">Loading…</div>

    <div v-else-if="error" class="error-notice" role="alert">
      {{ error }} <button class="btn-secondary" @click="load">Retry</button>
    </div>

    <template v-else>
      <p class="total-count">
        <strong>{{ stats.total.toLocaleString() }}</strong> emails labeled total
      </p>

      <div v-if="stats.total === 0" class="empty-notice">
        No labeled emails yet — go to <strong>Label</strong> to start labeling.
      </div>

      <div v-else class="label-bars">
        <div
          v-for="row in rows"
          :key="row.name"
          class="bar-row"
        >
          <span class="bar-emoji" aria-hidden="true">{{ row.emoji }}</span>
          <span class="bar-label">{{ row.name.replace(/_/g, '\u00a0') }}</span>
          <div class="bar-track" :title="`${row.count} (${row.pct}%)`">
            <div
              class="bar-fill"
              :style="{ width: `${row.pct}%`, background: row.color }"
            />
          </div>
          <span class="bar-count">{{ row.count.toLocaleString() }}</span>
        </div>
      </div>

      <div class="file-info">
        <span class="file-path">Score file: <code>data/email_score.jsonl</code></span>
        <span class="file-size">{{ fileSizeLabel }}</span>
      </div>

      <div class="action-bar">
        <button class="btn-secondary" @click="load">🔄 Refresh</button>
        <a class="btn-secondary" href="/api/stats/download" download="email_score.jsonl">
          ⬇️ Download
        </a>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useApiFetch } from '../composables/useApi'

interface StatsResponse {
  total: number
  counts: Record<string, number>
  score_file_bytes: number
}

// Canonical label order + metadata
const LABEL_META: Record<string, { emoji: string; color: string }> = {
  interview_scheduled: { emoji: '🗓️', color: '#4CAF50' },
  offer_received:      { emoji: '🎉', color: '#2196F3' },
  rejected:            { emoji: '❌', color: '#F44336' },
  positive_response:   { emoji: '👍', color: '#FF9800' },
  survey_received:     { emoji: '📋', color: '#9C27B0' },
  neutral:             { emoji: '⬜', color: '#607D8B' },
  event_rescheduled:   { emoji: '🔄', color: '#FF5722' },
  digest:              { emoji: '📰', color: '#00BCD4' },
  new_lead:            { emoji: '🤝', color: '#009688' },
  hired:               { emoji: '🎊', color: '#FFC107' },
}

const CANONICAL_ORDER = Object.keys(LABEL_META)

const stats   = ref<StatsResponse>({ total: 0, counts: {}, score_file_bytes: 0 })
const loading = ref(true)
const error   = ref('')

const rows = computed(() => {
  const max = Math.max(...Object.values(stats.value.counts), 1)
  const allLabels = [
    ...CANONICAL_ORDER,
    ...Object.keys(stats.value.counts).filter(k => !CANONICAL_ORDER.includes(k)),
  ].filter(k => stats.value.counts[k] > 0)

  return allLabels.map(name => {
    const count = stats.value.counts[name] ?? 0
    const meta  = LABEL_META[name] ?? { emoji: '🏷️', color: '#607D8B' }
    return {
      name,
      count,
      emoji: meta.emoji,
      color: meta.color,
      pct: Math.round((count / max) * 100),
    }
  })
})

const fileSizeLabel = computed(() => {
  const b = stats.value.score_file_bytes
  if (b === 0) return '(file not found)'
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${(b / 1024 / 1024).toFixed(2)} MB`
})

async function load() {
  loading.value = true
  error.value   = ''
  const { data, error: err } = await useApiFetch<StatsResponse>('/api/stats')
  loading.value = false
  if (err || !data) {
    error.value = 'Could not reach Avocet API.'
  } else {
    stats.value = data
  }
}

onMounted(load)
</script>

<style scoped>
.stats-view {
  max-width: 640px;
  margin: 0 auto;
  padding: 1.5rem 1rem 4rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.page-title {
  font-family: var(--font-display, var(--font-body, sans-serif));
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--app-primary, #2A6080);
}

.total-count {
  font-size: 1rem;
  color: var(--color-text-secondary, #6b7a99);
}

.label-bars {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.bar-row {
  display: grid;
  grid-template-columns: 1.5rem 11rem 1fr 3.5rem;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.88rem;
}

.bar-emoji { text-align: center; }

.bar-label {
  font-family: var(--font-mono, monospace);
  font-size: 0.78rem;
  color: var(--color-text, #1a2338);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bar-track {
  height: 14px;
  background: var(--color-surface-raised, #e4ebf5);
  border-radius: 99px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 99px;
  transition: width 0.4s ease;
}

.bar-count {
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: var(--color-text-secondary, #6b7a99);
  font-size: 0.82rem;
}

.file-info {
  display: flex;
  align-items: center;
  gap: 1rem;
  font-size: 0.8rem;
  color: var(--color-text-secondary, #6b7a99);
}

.file-path code {
  font-family: var(--font-mono, monospace);
  background: var(--color-surface-raised, #e4ebf5);
  padding: 0.1rem 0.3rem;
  border-radius: 0.2rem;
}

.action-bar {
  display: flex;
  gap: 0.75rem;
  align-items: center;
}

.btn-secondary {
  padding: 0.4rem 0.9rem;
  border-radius: 0.375rem;
  border: 1px solid var(--color-border, #d0d7e8);
  background: var(--color-surface, #fff);
  color: var(--color-text, #1a2338);
  font-size: 0.85rem;
  cursor: pointer;
  text-decoration: none;
  font-family: var(--font-body, sans-serif);
  transition: background 0.15s;
}

.btn-secondary:hover {
  background: var(--color-surface-raised, #e4ebf5);
}

.loading, .error-notice, .empty-notice {
  color: var(--color-text-secondary, #6b7a99);
  font-size: 0.9rem;
  padding: 1rem;
}

@media (max-width: 480px) {
  .bar-row {
    grid-template-columns: 1.5rem 1fr 1fr 3rem;
  }
  .bar-label {
    display: none;
  }
}
</style>
