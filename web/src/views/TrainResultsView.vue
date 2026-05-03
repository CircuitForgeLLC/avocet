<template>
  <div class="train-results-view">
    <header class="view-header">
      <h1 class="page-title">Training Results</h1>
      <button class="refresh-btn" :disabled="loading" @click="loadResults" aria-label="Refresh">&#x1F504;</button>
    </header>

    <div v-if="error" class="error-notice" role="alert">
      {{ error }}
      <button class="btn-retry" @click="loadResults">Retry</button>
    </div>

    <div v-if="loading" class="loading-state" aria-live="polite">Loading…</div>

    <div v-if="!error && results.length === 0 && !loading" class="empty-notice">
      No training results yet. Completed jobs will appear here.
    </div>

    <div v-if="results.length > 0" class="results-table-wrap">
      <table class="results-table">
        <thead>
          <tr>
            <th>Run</th>
            <th>Type</th>
            <th>Base Model</th>
            <th class="th-numeric">Macro F1</th>
            <th class="th-numeric">Accuracy</th>
            <th class="th-numeric">Samples</th>
            <th class="th-numeric">Duration</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in results" :key="r.id">
            <td class="td-id" :title="r.id">{{ r.id.slice(0, 8) }}</td>
            <td>
              <span class="type-chip">{{ r.model_type }}</span>
            </td>
            <td class="td-model" :title="r.base_model">{{ shortModel(r.base_model) }}</td>
            <td class="td-numeric">
              <span class="metric-val" :class="scoreClass(r.val_macro_f1)">
                {{ formatPct(r.val_macro_f1) }}
              </span>
            </td>
            <td class="td-numeric">{{ formatPct(r.val_accuracy) }}</td>
            <td class="td-numeric">{{ r.sample_count.toLocaleString() }}</td>
            <td class="td-numeric">{{ formatDuration(r.duration_seconds) }}</td>
            <td class="td-actions">
              <RouterLink
                v-if="r.model_type === 'classifier'"
                :to="`/fleet?model=${encodeURIComponent(r.base_model)}`"
                class="register-btn btn-sm-link"
              >
                Register in Fleet
              </RouterLink>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { RouterLink } from 'vue-router'

interface TrainResult {
  id: string
  job_id: string
  model_type: string
  base_model: string
  val_macro_f1: number | null
  val_accuracy: number | null
  sample_count: number
  duration_seconds: number | null
  created_at: string
}

const results = ref<TrainResult[]>([])
const loading = ref(false)
const error   = ref<string | null>(null)

async function loadResults() {
  loading.value = true
  error.value   = null
  try {
    const res = await fetch('/api/train/results')
    if (!res.ok) {
      error.value = `Failed to load results (HTTP ${res.status}).`
      return
    }
    const raw = await res.json() as { results?: TrainResult[] }
    results.value = Array.isArray(raw?.results) ? raw.results : []
  } catch {
    error.value = 'Network error loading results.'
  } finally {
    loading.value = false
  }
}

function formatPct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  if (mins === 0) return `${secs}s`
  return `${mins}m ${secs}s`
}

function shortModel(model: string): string {
  const parts = model.split('/')
  return parts[parts.length - 1] ?? model
}

function scoreClass(f1: number | null | undefined): string {
  if (f1 == null) return ''
  if (f1 >= 0.85) return 'score-great'
  if (f1 >= 0.75) return 'score-good'
  return 'score-fair'
}

onMounted(() => loadResults())
</script>

<style scoped>
.train-results-view {
  max-width: 860px;
  margin: 0 auto;
  padding: 1.5rem 1rem 4rem;
  display: flex;
  flex-direction: column;
  gap: 1.75rem;
}

.view-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.page-title {
  font-family: var(--font-display, var(--font-body, sans-serif));
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--app-primary, #2A6080);
  margin: 0;
  flex: 1;
}

.refresh-btn {
  background: transparent;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.375rem;
  cursor: pointer;
  font-size: 1rem;
  padding: 0.3rem 0.5rem;
  transition: background 0.15s;
}

.refresh-btn:hover:not(:disabled) { background: var(--color-surface-raised, #e4ebf5); }
.refresh-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.error-notice {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  background: color-mix(in srgb, var(--color-error, #c0392b) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--color-error, #c0392b) 30%, transparent);
  border-radius: var(--radius-md, 0.5rem);
  color: var(--color-error, #c0392b);
  font-size: 0.88rem;
}

.btn-retry {
  padding: 0.2rem 0.55rem;
  border-radius: 0.25rem;
  border: 1px solid var(--color-error, #c0392b);
  background: transparent;
  color: var(--color-error, #c0392b);
  cursor: pointer;
  font-size: 0.82rem;
}

.empty-notice {
  color: var(--color-text-muted, #4a5c7a);
  font-size: 0.9rem;
  padding: 0.75rem;
  border: 1px dashed var(--color-border, #a8b8d0);
  border-radius: var(--radius-md, 0.5rem);
}

.loading-state {
  color: var(--color-text-muted, #4a5c7a);
  font-size: 0.9rem;
  padding: 0.75rem;
}

.results-table-wrap { overflow-x: auto; }

.results-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}

.results-table th {
  text-align: left;
  padding: 0.4rem 0.6rem;
  background: var(--color-surface-raised, #f5f7fc);
  color: var(--color-text-muted, #4a5c7a);
  font-size: 0.78rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  border-bottom: 1px solid var(--color-border, #a8b8d0);
  white-space: nowrap;
}

.th-numeric { text-align: right; }

.results-table td {
  padding: 0.5rem 0.6rem;
  border-bottom: 1px solid var(--color-border-light, #ccd5e6);
  vertical-align: middle;
}

.td-id {
  font-family: var(--font-mono, monospace);
  font-size: 0.78rem;
  color: var(--color-text-muted, #4a5c7a);
}

.td-model {
  font-family: var(--font-mono, monospace);
  font-size: 0.82rem;
  max-width: 16ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.td-numeric {
  text-align: right;
  font-family: var(--font-mono, monospace);
  font-variant-numeric: tabular-nums;
  font-size: 0.82rem;
}

.td-actions { text-align: right; }

.metric-val { font-weight: 600; }
.score-great { color: var(--color-success, #3a7a32); }
.score-good  { color: var(--color-warning, #d4891a); }
.score-fair  { color: var(--color-text-muted, #4a5c7a); }

.type-chip {
  font-size: 0.72rem;
  font-family: var(--font-mono, monospace);
  padding: 0.1rem 0.4rem;
  border-radius: 0.25rem;
  background: var(--color-surface-alt, #dde4f0);
  color: var(--color-text, #1a2338);
}

.btn-sm-link {
  font-size: 0.78rem;
  padding: 0.2rem 0.55rem;
  border-radius: 0.3rem;
  border: 1px solid var(--app-primary, #2A6080);
  color: var(--app-primary, #2A6080);
  background: transparent;
  text-decoration: none;
  white-space: nowrap;
  display: inline-block;
  transition: background 0.1s;
}

.btn-sm-link:hover {
  background: color-mix(in srgb, var(--app-primary, #2A6080) 10%, transparent);
}

@media (max-width: 600px) {
  .results-table th:nth-child(6),
  .results-table td:nth-child(6),
  .results-table th:nth-child(7),
  .results-table td:nth-child(7) {
    display: none;
  }
}
</style>
