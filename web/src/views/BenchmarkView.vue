<template>
  <div class="bench-view">
    <header class="bench-header">
      <h1 class="page-title">🏁 Benchmark</h1>
      <div class="header-actions">
        <label class="slow-toggle" :class="{ disabled: running }">
          <input type="checkbox" v-model="includeSlow" :disabled="running" />
          Include slow models
        </label>
        <button
          class="btn-run"
          :disabled="running"
          @click="startBenchmark"
        >
          {{ running ? '⏳ Running…' : results ? '🔄 Re-run' : '▶ Run Benchmark' }}
        </button>
      </div>
    </header>

    <!-- Trained models badge row -->
    <div v-if="fineTunedModels.length > 0" class="trained-models-row">
      <span class="trained-label">Trained:</span>
      <span
        v-for="m in fineTunedModels"
        :key="m.name"
        class="trained-badge"
        :title="m.base_model_id ? `Base: ${m.base_model_id} · ${m.sample_count ?? '?'} samples` : m.name"
      >
        {{ m.name }}
        <span v-if="m.val_macro_f1 != null" class="trained-f1">
          F1 {{ (m.val_macro_f1 * 100).toFixed(1) }}%
        </span>
      </span>
    </div>

    <!-- Progress log -->
    <div v-if="running || runLog.length" class="run-log">
      <div class="run-log-title">
        <span>{{ running ? '⏳ Running benchmark…' : runError ? '❌ Failed' : '✅ Done' }}</span>
        <button class="btn-ghost" @click="runLog = []; runError = ''">Clear</button>
      </div>
      <div class="log-lines" ref="logEl">
        <div
          v-for="(line, i) in runLog"
          :key="i"
          class="log-line"
          :class="{ 'log-error': line.startsWith('ERROR') || line.startsWith('[error]') }"
        >{{ line }}</div>
      </div>
      <p v-if="runError" class="run-error">{{ runError }}</p>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="status-notice">Loading…</div>

    <!-- No results yet -->
    <div v-else-if="!results" class="status-notice empty">
      <p>No benchmark results yet.</p>
      <p class="hint">Click <strong>Run Benchmark</strong> to score all default models against your labeled data.</p>
    </div>

    <!-- Results -->
    <template v-else>
      <p class="meta-line">
        <span>{{ results.sample_count.toLocaleString() }} labeled emails</span>
        <span class="sep">·</span>
        <span>{{ modelCount }} model{{ modelCount === 1 ? '' : 's' }}</span>
        <span class="sep">·</span>
        <span>{{ formatDate(results.timestamp) }}</span>
      </p>

      <!-- Macro-F1 chart -->
      <section class="chart-section">
        <h2 class="chart-title">Macro-F1 (higher = better)</h2>
        <div class="bar-chart">
          <div v-for="row in f1Rows" :key="row.name" class="bar-row">
            <span class="bar-label" :title="row.name">{{ row.name }}</span>
            <div class="bar-track">
              <div
                class="bar-fill"
                :style="{ width: `${row.pct}%`, background: scoreColor(row.value) }"
              />
            </div>
            <span class="bar-value" :style="{ color: scoreColor(row.value) }">
              {{ row.value.toFixed(3) }}
            </span>
          </div>
        </div>
      </section>

      <!-- Latency chart -->
      <section class="chart-section">
        <h2 class="chart-title">Latency (ms / email, lower = better)</h2>
        <div class="bar-chart">
          <div v-for="row in latencyRows" :key="row.name" class="bar-row">
            <span class="bar-label" :title="row.name">{{ row.name }}</span>
            <div class="bar-track">
              <div
                class="bar-fill latency-fill"
                :style="{ width: `${row.pct}%` }"
              />
            </div>
            <span class="bar-value">{{ row.value.toFixed(1) }} ms</span>
          </div>
        </div>
      </section>

      <!-- Per-label F1 heatmap -->
      <section class="chart-section">
        <h2 class="chart-title">Per-label F1</h2>
        <div class="heatmap-scroll">
          <table class="heatmap">
            <thead>
              <tr>
                <th class="hm-label-col">Label</th>
                <th v-for="name in modelNames" :key="name" class="hm-model-col" :title="name">
                  {{ name }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="label in labelNames" :key="label">
                <td class="hm-label-cell">
                  <span class="hm-emoji">{{ LABEL_META[label]?.emoji ?? '🏷️' }}</span>
                  {{ label.replace(/_/g, '\u00a0') }}
                </td>
                <td
                  v-for="name in modelNames"
                  :key="name"
                  class="hm-value-cell"
                  :style="{ background: heatmapBg(f1For(name, label)), color: heatmapFg(f1For(name, label)) }"
                  :title="`${name} / ${label}: F1 ${f1For(name, label).toFixed(3)}, support ${supportFor(name, label)}`"
                >
                  {{ f1For(name, label).toFixed(2) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="heatmap-hint">Hover a cell for precision / recall / support. Color: 🟢 ≥ 0.7 · 🟡 0.4–0.7 · 🔴 &lt; 0.4</p>
      </section>
    </template>

    <!-- Fine-tune section -->
    <details class="ft-section">
      <summary class="ft-summary">Fine-tune a model</summary>
      <div class="ft-body">
        <div class="ft-controls">
          <label class="ft-field">
            <span class="ft-field-label">Model</span>
            <select v-model="ftModel" class="ft-select" :disabled="ftRunning">
              <option value="deberta-small">deberta-small (100M, fast)</option>
              <option value="bge-m3">bge-m3 (600M — stop Peregrine vLLM first)</option>
            </select>
          </label>
          <label class="ft-field">
            <span class="ft-field-label">Epochs</span>
            <input
              v-model.number="ftEpochs"
              type="number" min="1" max="20"
              class="ft-epochs"
              :disabled="ftRunning"
            />
          </label>
          <button
            class="btn-run ft-run-btn"
            :disabled="ftRunning"
            @click="startFinetune"
          >
            {{ ftRunning ? '⏳ Training…' : '▶ Run fine-tune' }}
          </button>
        </div>

        <div v-if="ftRunning || ftLog.length || ftError" class="run-log ft-log">
          <div class="run-log-title">
            <span>{{ ftRunning ? '⏳ Training…' : ftError ? '❌ Failed' : '✅ Done' }}</span>
            <button class="btn-ghost" @click="ftLog = []; ftError = ''">Clear</button>
          </div>
          <div class="log-lines" ref="ftLogEl">
            <div
              v-for="(line, i) in ftLog"
              :key="i"
              class="log-line"
              :class="{ 'log-error': line.startsWith('ERROR') || line.startsWith('[error]') }"
            >{{ line }}</div>
          </div>
          <p v-if="ftError" class="run-error">{{ ftError }}</p>
        </div>
      </div>
    </details>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { useApiFetch, useApiSSE } from '../composables/useApi'

// ── Label metadata (same as StatsView) ──────────────────────────────────────
const LABEL_META: Record<string, { emoji: string }> = {
  interview_scheduled: { emoji: '🗓️' },
  offer_received:      { emoji: '🎉' },
  rejected:            { emoji: '❌' },
  positive_response:   { emoji: '👍' },
  survey_received:     { emoji: '📋' },
  neutral:             { emoji: '⬜' },
  event_rescheduled:   { emoji: '🔄' },
  digest:              { emoji: '📰' },
  new_lead:            { emoji: '🤝' },
  hired:               { emoji: '🎊' },
}

// ── Types ────────────────────────────────────────────────────────────────────
interface FineTunedModel {
  name: string
  base_model_id?: string
  val_macro_f1?: number
  timestamp?: string
  sample_count?: number
}

interface PerLabel { f1: number; precision: number; recall: number; support: number }
interface ModelResult {
  macro_f1: number
  accuracy: number
  latency_ms: number
  per_label: Record<string, PerLabel>
}
interface BenchResults {
  timestamp: string | null
  sample_count: number
  models: Record<string, ModelResult>
}

// ── State ────────────────────────────────────────────────────────────────────
const results     = ref<BenchResults | null>(null)
const loading     = ref(true)
const running     = ref(false)
const runLog      = ref<string[]>([])
const runError    = ref('')
const includeSlow = ref(false)
const logEl       = ref<HTMLElement | null>(null)

// Fine-tune state
const fineTunedModels  = ref<FineTunedModel[]>([])
const ftModel          = ref('deberta-small')
const ftEpochs         = ref(5)
const ftRunning        = ref(false)
const ftLog            = ref<string[]>([])
const ftError          = ref('')
const ftLogEl          = ref<HTMLElement | null>(null)

// ── Derived ──────────────────────────────────────────────────────────────────
const modelNames = computed(() => Object.keys(results.value?.models ?? {}))
const modelCount = computed(() => modelNames.value.length)

const labelNames = computed(() => {
  const canonical = Object.keys(LABEL_META)
  const inResults = new Set(
    modelNames.value.flatMap(n => Object.keys(results.value!.models[n].per_label))
  )
  return [...canonical.filter(l => inResults.has(l)), ...[...inResults].filter(l => !canonical.includes(l))]
})

const f1Rows = computed(() => {
  if (!results.value) return []
  const rows = modelNames.value.map(name => ({
    name,
    value: results.value!.models[name].macro_f1,
  }))
  rows.sort((a, b) => b.value - a.value)
  const max = rows[0]?.value || 1
  return rows.map(r => ({ ...r, pct: Math.round((r.value / max) * 100) }))
})

const latencyRows = computed(() => {
  if (!results.value) return []
  const rows = modelNames.value.map(name => ({
    name,
    value: results.value!.models[name].latency_ms,
  }))
  rows.sort((a, b) => a.value - b.value) // fastest first
  const max = rows[rows.length - 1]?.value || 1
  return rows.map(r => ({ ...r, pct: Math.round((r.value / max) * 100) }))
})

// ── Helpers ──────────────────────────────────────────────────────────────────
function f1For(model: string, label: string): number {
  return results.value?.models[model]?.per_label[label]?.f1 ?? 0
}
function supportFor(model: string, label: string): number {
  return results.value?.models[model]?.per_label[label]?.support ?? 0
}

function scoreColor(v: number): string {
  if (v >= 0.7) return 'var(--color-success, #4CAF50)'
  if (v >= 0.4) return 'var(--app-accent, #B8622A)'
  return 'var(--color-error, #ef4444)'
}

function heatmapBg(v: number): string {
  // Blend red→yellow→green using the F1 value
  if (v >= 0.7) return `color-mix(in srgb, #4CAF50 ${Math.round(v * 100)}%, #1a2338 ${Math.round((1 - v) * 80)}%)`
  if (v >= 0.4) return `color-mix(in srgb, #FF9800 ${Math.round(v * 120)}%, #1a2338 40%)`
  return `color-mix(in srgb, #ef4444 ${Math.round(v * 200 + 30)}%, #1a2338 60%)`
}
function heatmapFg(v: number): string {
  return v >= 0.5 ? '#fff' : 'rgba(255,255,255,0.75)'
}

function formatDate(iso: string | null): string {
  if (!iso) return 'unknown date'
  const d = new Date(iso)
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

// ── Data loading ─────────────────────────────────────────────────────────────
async function loadResults() {
  loading.value = true
  const { data } = await useApiFetch<BenchResults>('/api/benchmark/results')
  loading.value = false
  if (data && Object.keys(data.models).length > 0) {
    results.value = data
  }
}

// ── Benchmark run ─────────────────────────────────────────────────────────────
function startBenchmark() {
  running.value = true
  runLog.value  = []
  runError.value = ''

  const url = `/api/benchmark/run${includeSlow.value ? '?include_slow=true' : ''}`
  useApiSSE(
    url,
    async (event) => {
      if (event.type === 'progress' && typeof event.message === 'string') {
        runLog.value.push(event.message)
        await nextTick()
        logEl.value?.scrollTo({ top: logEl.value.scrollHeight, behavior: 'smooth' })
      }
      if (event.type === 'error' && typeof event.message === 'string') {
        runError.value = event.message
      }
    },
    async () => {
      running.value = false
      await loadResults()
    },
    () => {
      running.value = false
      if (!runError.value) runError.value = 'Connection lost'
    },
  )
}

async function loadFineTunedModels() {
  const { data } = await useApiFetch<FineTunedModel[]>('/api/finetune/status')
  if (Array.isArray(data)) fineTunedModels.value = data
}

function startFinetune() {
  if (ftRunning.value) return
  ftRunning.value = true
  ftLog.value     = []
  ftError.value   = ''

  const params = new URLSearchParams({ model: ftModel.value, epochs: String(ftEpochs.value) })
  useApiSSE(
    `/api/finetune/run?${params}`,
    async (event) => {
      if (event.type === 'progress' && typeof event.message === 'string') {
        ftLog.value.push(event.message)
        await nextTick()
        ftLogEl.value?.scrollTo({ top: ftLogEl.value.scrollHeight, behavior: 'smooth' })
      }
      if (event.type === 'error' && typeof event.message === 'string') {
        ftError.value = event.message
      }
    },
    async () => {
      ftRunning.value = false
      await loadFineTunedModels()
      startBenchmark()          // auto-trigger benchmark to refresh charts
    },
    () => {
      ftRunning.value = false
      if (!ftError.value) ftError.value = 'Connection lost'
    },
  )
}

onMounted(() => {
  loadResults()
  loadFineTunedModels()
})
</script>

<style scoped>
.bench-view {
  max-width: 860px;
  margin: 0 auto;
  padding: 1.5rem 1rem 4rem;
  display: flex;
  flex-direction: column;
  gap: 1.75rem;
}

.bench-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.75rem;
}

.page-title {
  font-family: var(--font-display, var(--font-body, sans-serif));
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--app-primary, #2A6080);
  margin: 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.slow-toggle {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
  color: var(--color-text-secondary, #6b7a99);
  cursor: pointer;
  user-select: none;
}
.slow-toggle.disabled { opacity: 0.5; pointer-events: none; }

.btn-run {
  padding: 0.45rem 1.1rem;
  border-radius: 0.375rem;
  border: none;
  background: var(--app-primary, #2A6080);
  color: #fff;
  font-size: 0.88rem;
  font-family: var(--font-body, sans-serif);
  cursor: pointer;
  transition: opacity 0.15s;
}
.btn-run:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-run:not(:disabled):hover { opacity: 0.85; }

/* ── Run log ────────────────────────────────────────────── */
.run-log {
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  overflow: hidden;
  font-family: var(--font-mono, monospace);
  font-size: 0.78rem;
}

.run-log-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.4rem 0.75rem;
  background: var(--color-surface-raised, #e4ebf5);
  border-bottom: 1px solid var(--color-border, #d0d7e8);
  font-size: 0.8rem;
  color: var(--color-text-secondary, #6b7a99);
}

.btn-ghost {
  background: none;
  border: none;
  color: var(--color-text-secondary, #6b7a99);
  cursor: pointer;
  font-size: 0.78rem;
  padding: 0.1rem 0.3rem;
  border-radius: 0.2rem;
}
.btn-ghost:hover { background: var(--color-border, #d0d7e8); }

.log-lines {
  max-height: 200px;
  overflow-y: auto;
  padding: 0.5rem 0.75rem;
  background: var(--color-surface, #fff);
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.log-line { color: var(--color-text, #1a2338); line-height: 1.5; }
.log-line.log-error { color: var(--color-error, #ef4444); }

.run-error {
  margin: 0;
  padding: 0.4rem 0.75rem;
  background: color-mix(in srgb, var(--color-error, #ef4444) 10%, transparent);
  color: var(--color-error, #ef4444);
  font-size: 0.82rem;
  font-family: var(--font-mono, monospace);
}

/* ── Status notices ─────────────────────────────────────── */
.status-notice {
  color: var(--color-text-secondary, #6b7a99);
  font-size: 0.9rem;
  padding: 1rem;
}
.status-notice.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 3rem 1rem;
  text-align: center;
}
.hint { font-size: 0.85rem; opacity: 0.75; }

/* ── Meta line ──────────────────────────────────────────── */
.meta-line {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  font-size: 0.85rem;
  color: var(--color-text-secondary, #6b7a99);
  font-family: var(--font-mono, monospace);
  flex-wrap: wrap;
}
.sep { opacity: 0.4; }

/* ── Chart sections ─────────────────────────────────────── */
.chart-section {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.chart-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--color-text, #1a2338);
  margin: 0;
}

/* ── Bar charts ─────────────────────────────────────────── */
.bar-chart {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.bar-row {
  display: grid;
  grid-template-columns: 14rem 1fr 5rem;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.82rem;
}

.bar-label {
  font-family: var(--font-mono, monospace);
  font-size: 0.76rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--color-text, #1a2338);
}

.bar-track {
  height: 16px;
  background: var(--color-surface-raised, #e4ebf5);
  border-radius: 99px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 99px;
  transition: width 0.5s cubic-bezier(0.16, 1, 0.3, 1);
}

.latency-fill { background: var(--app-primary, #2A6080); opacity: 0.65; }

.bar-value {
  text-align: right;
  font-family: var(--font-mono, monospace);
  font-size: 0.8rem;
  font-variant-numeric: tabular-nums;
}

/* ── Heatmap ────────────────────────────────────────────── */
.heatmap-scroll {
  overflow-x: auto;
  border-radius: 0.5rem;
  border: 1px solid var(--color-border, #d0d7e8);
}

.heatmap {
  border-collapse: collapse;
  min-width: 100%;
  font-size: 0.78rem;
}

.hm-label-col {
  text-align: left;
  min-width: 11rem;
  padding: 0.4rem 0.6rem;
  background: var(--color-surface-raised, #e4ebf5);
  font-weight: 600;
  border-bottom: 1px solid var(--color-border, #d0d7e8);
  position: sticky;
  left: 0;
}

.hm-model-col {
  min-width: 5rem;
  max-width: 8rem;
  padding: 0.4rem 0.5rem;
  background: var(--color-surface-raised, #e4ebf5);
  border-bottom: 1px solid var(--color-border, #d0d7e8);
  font-family: var(--font-mono, monospace);
  font-size: 0.7rem;
  text-overflow: ellipsis;
  overflow: hidden;
  white-space: nowrap;
  text-align: center;
}

.hm-label-cell {
  padding: 0.35rem 0.6rem;
  background: var(--color-surface, #fff);
  border-top: 1px solid var(--color-border, #d0d7e8);
  white-space: nowrap;
  font-family: var(--font-mono, monospace);
  font-size: 0.74rem;
  position: sticky;
  left: 0;
}

.hm-emoji { margin-right: 0.3rem; }

.hm-value-cell {
  padding: 0.35rem 0.5rem;
  text-align: center;
  font-family: var(--font-mono, monospace);
  font-variant-numeric: tabular-nums;
  border-top: 1px solid rgba(255,255,255,0.08);
  cursor: default;
  transition: filter 0.15s;
}
.hm-value-cell:hover { filter: brightness(1.15); }

.heatmap-hint {
  font-size: 0.75rem;
  color: var(--color-text-secondary, #6b7a99);
  margin: 0;
}

/* ── Mobile tweaks ──────────────────────────────────────── */
@media (max-width: 600px) {
  .bar-row { grid-template-columns: 9rem 1fr 4rem; }
  .bar-label { font-size: 0.7rem; }
  .bench-header { flex-direction: column; align-items: flex-start; }
}

/* ── Trained models badge row ──────────────────────────── */
.trained-models-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 0.75rem;
  background: var(--color-surface-raised, #e4ebf5);
  border-radius: 0.5rem;
  border: 1px solid var(--color-border, #d0d7e8);
}

.trained-label {
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--color-text-secondary, #6b7a99);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  flex-shrink: 0;
}

.trained-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.2rem 0.55rem;
  background: var(--app-primary, #2A6080);
  color: #fff;
  border-radius: 1rem;
  font-family: var(--font-mono, monospace);
  font-size: 0.76rem;
  cursor: default;
}

.trained-f1 {
  background: rgba(255,255,255,0.2);
  border-radius: 0.75rem;
  padding: 0.05rem 0.35rem;
  font-size: 0.7rem;
  font-weight: 700;
}

/* ── Fine-tune section ──────────────────────────────────── */
.ft-section {
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  overflow: hidden;
}

.ft-summary {
  padding: 0.65rem 0.9rem;
  cursor: pointer;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--color-text, #1a2338);
  user-select: none;
  list-style: none;
  background: var(--color-surface-raised, #e4ebf5);
}
.ft-summary::-webkit-details-marker { display: none; }
.ft-summary::before { content: '▶  '; font-size: 0.65rem; color: var(--color-text-secondary, #6b7a99); }
details[open] .ft-summary::before { content: '▼  '; }

.ft-body {
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  border-top: 1px solid var(--color-border, #d0d7e8);
}

.ft-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: flex-end;
}

.ft-field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.ft-field-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--color-text-secondary, #6b7a99);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.ft-select {
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.375rem;
  background: var(--color-surface, #fff);
  font-size: 0.85rem;
  color: var(--color-text, #1a2338);
  min-width: 220px;
}
.ft-select:disabled { opacity: 0.55; }

.ft-epochs {
  width: 64px;
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.375rem;
  background: var(--color-surface, #fff);
  font-size: 0.85rem;
  color: var(--color-text, #1a2338);
  text-align: center;
}
.ft-epochs:disabled { opacity: 0.55; }

.ft-run-btn { align-self: flex-end; }

.ft-log { margin-top: 0; }

@media (max-width: 600px) {
  .ft-controls { flex-direction: column; align-items: stretch; }
  .ft-select { min-width: 0; width: 100%; }
}
</style>
