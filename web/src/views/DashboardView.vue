<template>
  <div class="dashboard-view">
    <header class="dashboard-header">
      <h1 class="page-title">📊 Dashboard</h1>
      <button class="refresh-btn" :disabled="loading" @click="load" aria-label="Refresh dashboard">
        🔄
      </button>
    </header>

    <div v-if="loading && !data" class="loading-state">Loading…</div>

    <div v-if="error" class="error-notice" role="alert">
      {{ error }}
      <button class="btn-retry" @click="load">Retry</button>
    </div>

    <div v-if="data" class="flywheel-grid">

      <!-- ① Data card -->
      <div class="stage-card" data-stage="data">
        <div class="card-header">
          <span class="card-step">①</span>
          <h2 class="card-title">Data</h2>
        </div>
        <div class="card-body">
          <p class="card-metric">
            <strong class="metric-value">{{ data.labeled_since_last_eval.toLocaleString() }}</strong>
            <span class="metric-label"> labeled since last eval</span>
          </p>
        </div>
      </div>

      <!-- ② Eval card -->
      <div class="stage-card" data-stage="eval">
        <div class="card-header">
          <span class="card-step">②</span>
          <h2 class="card-title">Eval</h2>
        </div>
        <div class="card-body">
          <div class="bench-run-table">
            <div
              v-for="(run, type) in data.recent_bench_runs"
              :key="type"
              class="bench-run-row"
            >
              <span class="bench-type-label">{{ BENCH_LABELS[type as BenchType] ?? type }}</span>
              <span class="bench-run-time" :class="{ 'metric-muted': !run.timestamp }">
                {{ run.timestamp ? formatBenchTs(run.timestamp) : '—' }}
              </span>
              <span v-if="run.score != null" class="bench-run-score">
                {{ formatScore(run.score) }}
              </span>
            </div>
          </div>
        </div>
        <div v-if="data.signals.eval_to_train" class="card-cta">
          <RouterLink to="/train/jobs" class="cta-btn">Queue Finetune</RouterLink>
        </div>
        <div v-if="data.signals.data_to_eval" class="card-cta">
          <RouterLink to="/eval/benchmark" class="cta-btn">Run Eval</RouterLink>
        </div>
      </div>

      <!-- ③ Train card -->
      <div class="stage-card" data-stage="train">
        <div class="card-header">
          <span class="card-step">③</span>
          <h2 class="card-title">Train</h2>
        </div>
        <div class="card-body">
          <template v-if="data.active_jobs.length > 0">
            <div
              v-for="job in data.active_jobs"
              :key="job.id"
              class="job-row"
            >
              <span class="job-key">{{ job.model_key }}</span>
              <span class="status-pill" :class="`status-${job.status}`">{{ job.status }}</span>
            </div>
          </template>
          <p v-else class="card-metric metric-muted">No active jobs</p>

          <p v-if="data.corrections_export_ready > 0" class="card-metric">
            <strong class="metric-value">{{ data.corrections_export_ready }}</strong>
            <span class="metric-label"> corrections ready</span>
          </p>
        </div>
        <div v-if="data.signals.train_to_fleet" class="card-cta">
          <RouterLink to="/fleet" class="cta-btn">Register in Fleet</RouterLink>
        </div>
      </div>

    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'

interface ActiveJob {
  id: string
  type: string
  model_key: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
}

interface DashboardSignals {
  data_to_eval: boolean
  eval_to_train: boolean
  train_to_fleet: boolean
}

interface BenchRun {
  timestamp: string | null
  metric: string | null
  score: number | null
}

type BenchType = 'classifier' | 'llm' | 'style' | 'plans'

interface DashboardData {
  labeled_since_last_eval: number
  last_eval_timestamp: string | null
  last_eval_best_score: number | null
  active_jobs: ActiveJob[]
  corrections_export_ready: number
  recent_bench_runs: Record<BenchType, BenchRun>
  signals: DashboardSignals
}

const BENCH_LABELS: Record<BenchType, string> = {
  classifier: 'Classifier',
  llm:        'LLM Eval',
  style:      'Style',
  plans:      'Planning',
}

const data    = ref<DashboardData | null>(null)
const loading = ref(false)
const error   = ref<string | null>(null)

function formatBenchTs(ts: string): string {
  const date = new Date(ts)
  if (!isNaN(date.getTime())) {
    const diff = Date.now() - date.getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1)  return 'just now'
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24)  return `${hrs}h ago`
    return `${Math.floor(hrs / 24)}d ago`
  }
  // Non-ISO: show as-is (plans bench uses "YYYY-MM-DD HH:MM")
  return ts.length > 16 ? ts.slice(0, 16) : ts
}

function formatScore(score: number): string {
  return `${(score * 100).toFixed(1)}%`
}

async function load() {
  loading.value = true
  error.value   = null
  try {
    const res = await fetch('/api/dashboard')
    if (!res.ok) {
      error.value = `Could not load dashboard (HTTP ${res.status}).`
      return
    }
    data.value = await res.json() as DashboardData
  } catch {
    error.value = 'Network error. Is the Avocet API running?'
  } finally {
    loading.value = false
  }
}

onMounted(() => load())
</script>

<style scoped>
.dashboard-view {
  max-width: 860px;
  margin: 0 auto;
  padding: 1.5rem 1rem 4rem;
  display: flex;
  flex-direction: column;
  gap: 1.75rem;
}

.dashboard-header {
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

/* ── Flywheel grid ── */
.flywheel-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}

@media (max-width: 680px) {
  .flywheel-grid {
    grid-template-columns: 1fr;
  }
}

/* ── Stage cards ── */
.stage-card {
  background: var(--color-surface-raised, #f5f7fc);
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: var(--radius-lg, 1rem);
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  box-shadow: var(--shadow-sm);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  border-bottom: 1px solid var(--color-border, #d0d7e8);
  padding-bottom: 0.6rem;
}

.card-step {
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--app-primary, #2A6080);
  flex-shrink: 0;
}

.card-title {
  font-family: var(--font-display, var(--font-body, sans-serif));
  font-size: 1rem;
  font-weight: 600;
  color: var(--color-text, #1a2338);
  margin: 0;
}

.card-body {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  flex: 1;
}

.card-metric {
  margin: 0;
  font-size: 0.875rem;
  color: var(--color-text, #1a2338);
}

.metric-value {
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--app-primary, #2A6080);
}

.metric-label {
  color: var(--color-text-muted, #4a5c7a);
}

.metric-muted { color: var(--color-text-muted, #4a5c7a); }

.card-cta { margin-top: auto; }

.cta-btn {
  display: block;
  width: 100%;
  text-align: center;
  padding: 0.5rem;
  background: var(--app-primary, #2A6080);
  color: #fff;
  border-radius: 0.375rem;
  text-decoration: none;
  font-size: 0.875rem;
  font-weight: 600;
  transition: background 0.15s;
}

.cta-btn:hover { background: color-mix(in srgb, var(--app-primary, #2A6080) 85%, black); }

/* ── Bench run table ── */
.bench-run-table {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.bench-run-row {
  display: grid;
  grid-template-columns: 6rem 1fr auto;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.82rem;
}

.bench-type-label {
  font-weight: 600;
  color: var(--color-text, #1a2338);
  font-size: 0.78rem;
}

.bench-run-time {
  color: var(--color-text-secondary, #6b7a99);
  font-size: 0.78rem;
}

.bench-run-score {
  font-family: var(--font-mono, monospace);
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--app-primary, #2A6080);
  background: color-mix(in srgb, var(--app-primary, #2A6080) 10%, transparent);
  padding: 0.1rem 0.35rem;
  border-radius: 0.25rem;
}

/* ── Job pills ── */
.job-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
}

.job-key {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text, #1a2338);
}

.status-pill {
  font-size: 0.75rem;
  padding: 0.15rem 0.45rem;
  border-radius: 100px;
  font-weight: 600;
  flex-shrink: 0;
  background: var(--color-surface-raised, #e4ebf5);
  color: var(--color-text-muted, #4a5c7a);
}

.status-pill.status-running  { background: #d4f4e0; color: #1a7a3a; }
.status-pill.status-queued   { background: #fef3cd; color: #856404; }
.status-pill.status-failed   { background: #fde8e8; color: #842029; }
.status-pill.status-completed { background: #e0f0ff; color: #0c5481; }

/* ── State indicators ── */
.loading-state {
  color: var(--color-text-muted, #4a5c7a);
  font-size: 0.9rem;
}

.error-notice {
  background: #fde8e8;
  color: #842029;
  border: 1px solid #f5c2c7;
  border-radius: 0.5rem;
  padding: 0.75rem 1rem;
  font-size: 0.875rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.btn-retry {
  background: transparent;
  border: 1px solid currentColor;
  border-radius: 0.25rem;
  color: inherit;
  cursor: pointer;
  font-size: 0.75rem;
  padding: 0.2rem 0.5rem;
  margin-left: auto;
}
</style>
