<template>
  <div class="voice-tab">

    <!-- ── Controls row ──────────────────────────────────────────────────── -->
    <div class="voice-controls">

      <!-- Model picker -->
      <details class="model-picker" open>
        <summary class="picker-summary">
          <span class="picker-title">🎙 Models</span>
          <span class="picker-badge">{{ selectedCount }} selected</span>
          <button class="btn-refresh" :disabled="modelsLoading" @click.stop="loadModels" title="Refresh model list">
            {{ modelsLoading ? '⏳' : '🔄' }}
          </button>
        </summary>
        <div class="picker-body">
          <div v-if="modelsLoading" class="picker-loading">Loading models…</div>
          <div v-else-if="loadError" class="picker-error">{{ loadError }}</div>
          <template v-else>

            <!-- Ollama group -->
            <div class="picker-group" v-if="ollamaModels.length">
              <div class="group-header">
                <label class="group-check">
                  <input
                    type="checkbox"
                    :checked="isGroupAllSelected('ollama')"
                    :indeterminate="isGroupIndeterminate('ollama')"
                    @change="toggleGroup('ollama', ($event.target as HTMLInputElement).checked)"
                  />
                  <span class="group-label">Ollama</span>
                  <span class="group-count">({{ ollamaModels.length }})</span>
                </label>
                <span class="group-note">auto-synced with Models view</span>
              </div>
              <div class="model-list">
                <label v-for="m in ollamaModels" :key="m.id" class="model-item">
                  <input type="checkbox" :value="m.id" v-model="selectedModels" />
                  <span class="model-name">{{ m.name }}</span>
                  <span v-if="m.size_mb" class="model-meta">{{ formatMb(m.size_mb) }}</span>
                </label>
              </div>
            </div>

            <!-- cf-text group -->
            <div class="picker-group" v-if="cftextModels.length">
              <div class="group-header">
                <label class="group-check">
                  <input
                    type="checkbox"
                    :checked="isGroupAllSelected('cf-text')"
                    :indeterminate="isGroupIndeterminate('cf-text')"
                    @change="toggleGroup('cf-text', ($event.target as HTMLInputElement).checked)"
                  />
                  <span class="group-label">cf-text (cf-orch)</span>
                  <span class="group-count">({{ cftextModels.length }})</span>
                </label>
                <span class="group-note">GGUFs via coordinator — enable cf-orch below</span>
              </div>
              <div class="model-list">
                <label v-for="m in cftextModels" :key="m.id" class="model-item">
                  <input type="checkbox" :value="m.id" v-model="selectedModels" />
                  <span class="model-name">{{ m.name }}</span>
                  <span v-if="m.vram_mb" class="model-meta">{{ formatMb(m.vram_mb) }} VRAM</span>
                </label>
              </div>
            </div>

            <div v-if="!ollamaModels.length && !cftextModels.length" class="picker-empty">
              No models available — check Ollama and cf-orch connections.
            </div>

          </template>
        </div>
      </details>

      <!-- Options panel -->
      <details class="options-panel">
        <summary class="picker-summary">
          <span class="picker-title">⚙️ Options</span>
        </summary>
        <div class="options-body">
          <label class="option-row">
            <input type="checkbox" v-model="useCforch" :disabled="running" />
            <span class="option-label">Use cf-orch backend</span>
            <span class="option-hint">Routes generation through cf-text instead of ollama</span>
          </label>
          <label class="option-row" :class="{ dimmed: !useCforch }">
            <span class="option-label">Max VRAM (MB)</span>
            <input
              type="number"
              v-model.number="maxVram"
              :disabled="running || !useCforch"
              min="1024"
              max="24576"
              step="512"
              class="option-number"
            />
            <span class="option-hint">Skip models exceeding this VRAM limit</span>
          </label>
          <label class="option-row">
            <span class="option-label">Parallel workers</span>
            <input
              type="number"
              v-model.number="workers"
              :disabled="running"
              min="1"
              max="16"
              step="1"
              class="option-number"
            />
            <span class="option-hint">Models to score simultaneously (1 = sequential)</span>
          </label>
          <label class="option-row">
            <input type="checkbox" v-model="includeLarge" :disabled="running" />
            <span class="option-label">Include large models (30B+)</span>
            <span class="option-hint">Off by default — these take much longer</span>
          </label>
        </div>
      </details>

    </div>

    <!-- ── Run controls ──────────────────────────────────────────────────── -->
    <div class="run-bar">
      <button class="btn-run" :disabled="running || selectedCount === 0" @click="startBenchmark">
        {{ running ? '⏳ Running…' : results.length ? '🔄 Re-run' : '▶ Run Benchmark' }}
      </button>
      <button v-if="running" class="btn-cancel" @click="cancelBenchmark">✕ Cancel</button>
      <span v-if="selectedCount === 0 && !running" class="run-hint">Select at least one model above</span>
    </div>

    <!-- ── Progress log ──────────────────────────────────────────────────── -->
    <div v-if="runLog.length" class="run-log">
      <div class="run-log-header">
        <span class="run-log-title">Run log</span>
        <button class="btn-clear" @click="runLog = []">Clear</button>
      </div>
      <pre class="run-log-body" ref="logEl">{{ runLog.join('\n') }}</pre>
    </div>

    <!-- ── Past runs picker ─────────────────────────────────────────────── -->
    <div class="history-bar" v-if="pastRuns.length">
      <label class="history-label">📂 Past runs:</label>
      <select class="history-select" v-model="selectedRun" @change="loadRun(selectedRun)">
        <option value="">— select a past run —</option>
        <option v-for="r in pastRuns" :key="r.filename" :value="r.filename">
          {{ r.date }} · {{ r.model_count }} model{{ r.model_count !== 1 ? 's' : '' }} · top {{ r.top_score }}/100
        </option>
      </select>
    </div>

    <!-- ── Results table ─────────────────────────────────────────────────── -->
    <div v-if="results.length" class="results-section">
      <div class="results-header">
        <h2 class="results-title">Rankings</h2>
        <button
          class="btn-corrections"
          :disabled="sendingCorrections"
          @click="sendToCorrections"
          title="Push all outputs from this run into the Corrections review queue"
        >
          {{ sendingCorrections ? '⏳ Sending…' : correctionsMsg || '✍️ Send to Corrections' }}
        </button>
      </div>
      <div class="results-table-wrap">
        <table class="results-table">
          <thead>
            <tr>
              <th>Rank</th>
              <th>Model</th>
              <th>Score</th>
              <th>Latency</th>
              <th title="Em-dash count">—</th>
              <th title="Filler phrase hits">Fillers</th>
              <th title="Semicolons">;</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(r, i) in results"
              :key="r.model_id"
              class="result-row"
              :class="{ 'top-row': i === 0 }"
              @click="toggleExpanded(r.model_id)"
            >
              <td class="rank-cell">{{ medal(i) }}</td>
              <td class="model-cell">
                <span class="model-name-text">{{ r.model_id }}</span>
              </td>
              <td class="score-cell">
                <span class="score-pill" :style="scorePillStyle(r.avg_score)">
                  {{ r.avg_score.toFixed(0) }}
                </span>
              </td>
              <td class="latency-cell">{{ formatLatency(r.avg_latency_ms) }}</td>
              <td class="violation-cell" :class="{ 'has-violation': r.total_em_dashes > 0 }">
                {{ r.total_em_dashes }}
              </td>
              <td class="violation-cell" :class="{ 'has-violation': r.total_filler_hits > 0 }">
                {{ r.total_filler_hits }}
              </td>
              <td class="violation-cell" :class="{ 'has-violation': r.total_semicolons > 0 }">
                {{ r.total_semicolons }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Expandable sample outputs -->
      <div v-for="r in results" :key="'exp-' + r.model_id">
        <div v-if="expandedModels.has(r.model_id)" class="sample-outputs">
          <div class="sample-header">
            <strong>{{ r.model_id }}</strong>
            <button class="btn-collapse" @click="toggleExpanded(r.model_id)">✕ Close</button>
          </div>
          <div v-for="pr in r.prompt_results" :key="pr.tag" class="sample-prompt">
            <div class="sample-tag">
              <span class="tag-name">{{ pr.tag }}</span>
              <span class="tag-score">{{ pr.score.toFixed(0) }}/100</span>
              <span class="tag-latency">{{ formatLatency(pr.latency_ms) }}</span>
            </div>
            <pre class="sample-text">{{ pr.output || '(no output)' }}</pre>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch } from 'vue'

// ── Types ───────────────────────────────────────────────────────────────────

interface VoiceModel {
  id: string
  name: string
  source: 'ollama' | 'cf-text'
  size_mb?: number | null
  vram_mb?: number | null
  description?: string
}

interface PromptResult {
  tag: string
  output: string
  score: number
  latency_ms: number
  signals: Record<string, unknown>
}

interface ModelResult {
  model_id: string
  avg_score: number
  avg_latency_ms: number
  total_filler_hits: number
  total_em_dashes: number
  total_semicolons: number
  prompt_results: PromptResult[]
}

interface PastRun {
  filename: string
  date: string
  model_count: number
  top_score: number
}

// ── State ───────────────────────────────────────────────────────────────────

const ollamaModels  = ref<VoiceModel[]>([])
const cftextModels  = ref<VoiceModel[]>([])
const selectedModels = ref<string[]>([])
const modelsLoading  = ref(false)
const loadError      = ref('')

const useCforch    = ref(false)
const maxVram      = ref(7200)
const workers      = ref(1)
const includeLarge = ref(false)

const running   = ref(false)
const runLog    = ref<string[]>([])
const logEl     = ref<HTMLPreElement | null>(null)

const results       = ref<ModelResult[]>([])
const pastRuns      = ref<PastRun[]>([])
const selectedRun   = ref('')
const expandedModels    = ref(new Set<string>())
const sendingCorrections = ref(false)
const correctionsMsg     = ref('')

// ── Computed ─────────────────────────────────────────────────────────────────

const selectedCount = computed(() => selectedModels.value.length)

function isGroupAllSelected(source: string): boolean {
  const group = source === 'ollama' ? ollamaModels.value : cftextModels.value
  return group.length > 0 && group.every(m => selectedModels.value.includes(m.id))
}

function isGroupIndeterminate(source: string): boolean {
  const group = source === 'ollama' ? ollamaModels.value : cftextModels.value
  const count = group.filter(m => selectedModels.value.includes(m.id)).length
  return count > 0 && count < group.length
}

// ── Actions ──────────────────────────────────────────────────────────────────

async function loadModels() {
  modelsLoading.value = true
  loadError.value = ''
  try {
    const resp = await fetch('/api/voice/models')
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    ollamaModels.value  = data.ollama  ?? []
    cftextModels.value  = data.cf_text ?? []
  } catch (e: unknown) {
    loadError.value = `Failed to load models: ${e instanceof Error ? e.message : String(e)}`
  } finally {
    modelsLoading.value = false
  }
}

async function loadPastRuns() {
  try {
    const resp = await fetch('/api/voice/results')
    if (resp.ok) pastRuns.value = await resp.json()
  } catch { /* non-fatal */ }
}

async function loadRun(filename: string) {
  if (!filename) return
  try {
    const resp = await fetch(`/api/voice/results/${filename}`)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    results.value = await resp.json()
    expandedModels.value.clear()
  } catch (e: unknown) {
    runLog.value.push(`[error] Failed to load ${filename}: ${e instanceof Error ? e.message : String(e)}`)
  }
}

function toggleGroup(source: string, checked: boolean) {
  const group = source === 'ollama' ? ollamaModels.value : cftextModels.value
  const ids = group.map(m => m.id)
  if (checked) {
    const newSet = new Set([...selectedModels.value, ...ids])
    selectedModels.value = [...newSet]
  } else {
    selectedModels.value = selectedModels.value.filter(id => !ids.includes(id))
  }
}

function toggleExpanded(modelId: string) {
  if (expandedModels.value.has(modelId)) {
    expandedModels.value.delete(modelId)
  } else {
    expandedModels.value.add(modelId)
  }
  expandedModels.value = new Set(expandedModels.value)
}

function startBenchmark() {
  if (running.value || selectedCount.value === 0) return
  running.value = true
  runLog.value = []
  results.value = []
  expandedModels.value.clear()

  const params = new URLSearchParams({
    models:        selectedModels.value.join(','),
    use_cforch:    String(useCforch.value),
    max_vram:      String(maxVram.value),
    workers:       String(workers.value),
    include_large: String(includeLarge.value),
  })

  const es = new EventSource(`/api/voice/run?${params}`)

  es.onmessage = async (ev) => {
    try {
      const msg = JSON.parse(ev.data)
      if (msg.type === 'progress') {
        runLog.value.push(msg.message)
        await nextTick()
        if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
      } else if (msg.type === 'result') {
        results.value = msg.results ?? []
        await loadPastRuns()
      } else if (msg.type === 'complete') {
        running.value = false
        es.close()
      } else if (msg.type === 'error') {
        runLog.value.push(`[error] ${msg.message}`)
        running.value = false
        es.close()
      }
    } catch { /* ignore parse errors */ }
  }

  es.onerror = () => {
    if (running.value) {
      runLog.value.push('[error] Connection lost')
      running.value = false
    }
    es.close()
  }
}

async function cancelBenchmark() {
  try {
    await fetch('/api/voice/cancel', { method: 'POST' })
  } finally {
    running.value = false
    runLog.value.push('[cancelled]')
  }
}

async function sendToCorrections() {
  if (!selectedRun.value || sendingCorrections.value) return
  sendingCorrections.value = true
  correctionsMsg.value = ''
  try {
    const resp = await fetch('/api/voice/send-to-corrections', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: selectedRun.value, model_ids: [] }),
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    correctionsMsg.value = `✓ ${data.imported} added to Corrections`
  } catch (e: unknown) {
    correctionsMsg.value = `Error: ${e instanceof Error ? e.message : String(e)}`
  } finally {
    sendingCorrections.value = false
  }
}

// ── Formatting helpers ────────────────────────────────────────────────────────

function formatMb(mb: number): string {
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`
}

function formatLatency(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`
}

function medal(index: number): string {
  return ['🥇', '🥈', '🥉'][index] ?? `#${index + 1}`
}

function scorePillStyle(score: number): Record<string, string> {
  const hue = Math.round((score / 100) * 120)  // 0=red, 120=green
  return {
    background: `hsl(${hue} 60% 88%)`,
    color:      `hsl(${hue} 60% 28%)`,
  }
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────

// Auto-enable cf-orch when cf-text models are selected
watch(selectedModels, (ids) => {
  const hasCftext = ids.some(id => cftextModels.value.find(m => m.id === id))
  if (hasCftext) useCforch.value = true
})

onMounted(async () => {
  await Promise.all([loadModels(), loadPastRuns()])
  // Auto-load the latest results if any exist
  if (pastRuns.value.length) {
    selectedRun.value = pastRuns.value[0].filename
    await loadRun(pastRuns.value[0].filename)
  }
})
</script>

<style scoped>
.voice-tab {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1rem 0;
}

/* ── Controls ─────────────────────────────────────────────────────────────── */

.voice-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: flex-start;
}

.model-picker,
.options-panel {
  flex: 1;
  min-width: 280px;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  background: var(--color-surface, #f4f7fc);
  overflow: hidden;
}

.picker-summary {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.65rem 0.85rem;
  cursor: pointer;
  user-select: none;
  font-size: 0.9rem;
  font-weight: 600;
  list-style: none;
}

.picker-summary::-webkit-details-marker { display: none; }

.picker-title { flex: 1; color: var(--color-text, #1a2338); }
.picker-badge {
  background: var(--app-primary, #2A6080);
  color: #fff;
  border-radius: 9999px;
  padding: 0.1rem 0.5rem;
  font-size: 0.72rem;
  font-weight: 700;
}

.btn-refresh {
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 0.85rem;
  padding: 0.1rem 0.25rem;
  border-radius: 0.25rem;
  color: var(--color-text-secondary, #6b7a99);
}
.btn-refresh:hover { background: var(--color-border, #d0d7e8); }
.btn-refresh:disabled { opacity: 0.5; cursor: not-allowed; }

.picker-body,
.options-body {
  padding: 0.75rem;
  border-top: 1px solid var(--color-border, #d0d7e8);
}

.picker-loading, .picker-empty {
  color: var(--color-text-secondary, #6b7a99);
  font-size: 0.85rem;
  padding: 0.25rem 0;
}

.picker-error {
  color: #b91c1c;
  font-size: 0.85rem;
}

/* ── Model groups ──────────────────────────────────────────────────────────── */

.picker-group {
  margin-bottom: 0.75rem;
}
.picker-group:last-child { margin-bottom: 0; }

.group-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.4rem;
}

.group-check {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  color: var(--color-text, #1a2338);
}

.group-count {
  color: var(--color-text-secondary, #6b7a99);
  font-weight: 400;
  font-size: 0.8rem;
}

.group-note {
  margin-left: auto;
  font-size: 0.72rem;
  color: var(--color-text-secondary, #6b7a99);
  font-style: italic;
}

.model-list {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  padding-left: 1.25rem;
  max-height: 220px;
  overflow-y: auto;
}

.model-item {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.82rem;
  cursor: pointer;
  padding: 0.15rem 0;
}

.model-name { flex: 1; font-family: var(--font-mono, monospace); }

.model-meta {
  font-size: 0.72rem;
  color: var(--color-text-secondary, #6b7a99);
}

/* ── Options ──────────────────────────────────────────────────────────────── */

.option-row {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.35rem 0;
  cursor: pointer;
  font-size: 0.85rem;
}

.option-label { font-weight: 500; white-space: nowrap; }

.option-hint {
  flex: 1;
  font-size: 0.75rem;
  color: var(--color-text-secondary, #6b7a99);
  margin-left: auto;
  text-align: right;
}

.option-number {
  width: 90px;
  padding: 0.2rem 0.4rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.25rem;
  font-size: 0.85rem;
  background: var(--color-bg, #fff);
  color: var(--color-text, #1a2338);
}

.option-row.dimmed { opacity: 0.45; pointer-events: none; }

/* ── Run bar ──────────────────────────────────────────────────────────────── */

.run-bar {
  display: flex;
  align-items: center;
  gap: 0.65rem;
}

.btn-run {
  padding: 0.5rem 1.25rem;
  border: none;
  border-radius: 0.375rem;
  background: var(--app-primary, #2A6080);
  color: #fff;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-run:hover:not(:disabled) { background: color-mix(in srgb, var(--app-primary, #2A6080) 80%, #000); }
.btn-run:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-cancel {
  padding: 0.5rem 0.9rem;
  border: 1px solid #f85149;
  border-radius: 0.375rem;
  background: transparent;
  color: #b91c1c;
  font-size: 0.85rem;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-cancel:hover { background: #fee2e2; }

.run-hint {
  font-size: 0.8rem;
  color: var(--color-text-secondary, #6b7a99);
}

/* ── Run log ──────────────────────────────────────────────────────────────── */

.run-log {
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  overflow: hidden;
}

.run-log-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.4rem 0.75rem;
  background: var(--color-surface, #f4f7fc);
  border-bottom: 1px solid var(--color-border, #d0d7e8);
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-text-secondary, #6b7a99);
}

.run-log-title { text-transform: uppercase; letter-spacing: 0.05em; }

.btn-clear {
  border: none;
  background: transparent;
  font-size: 0.75rem;
  color: var(--color-text-secondary, #6b7a99);
  cursor: pointer;
  padding: 0.1rem 0.3rem;
  border-radius: 0.25rem;
}
.btn-clear:hover { background: var(--color-border, #d0d7e8); }

.run-log-body {
  margin: 0;
  padding: 0.65rem 0.85rem;
  font-size: 0.78rem;
  font-family: var(--font-mono, monospace);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 260px;
  overflow-y: auto;
  background: var(--color-bg, #fff);
  color: var(--color-text, #1a2338);
}

/* ── History bar ──────────────────────────────────────────────────────────── */

.history-bar {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  font-size: 0.85rem;
}

.history-label { font-weight: 500; white-space: nowrap; }

.history-select {
  flex: 1;
  padding: 0.3rem 0.5rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.375rem;
  background: var(--color-surface, #f4f7fc);
  color: var(--color-text, #1a2338);
  font-size: 0.85rem;
}

/* ── Results table ────────────────────────────────────────────────────────── */

.results-section { display: flex; flex-direction: column; gap: 0.75rem; }

.results-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.results-title {
  font-size: 1rem;
  font-weight: 700;
  color: var(--color-text, #1a2338);
  margin: 0;
}

.btn-corrections {
  padding: 0.4rem 0.9rem;
  border: 1px solid var(--app-primary, #2A6080);
  border-radius: 0.375rem;
  background: transparent;
  color: var(--app-primary, #2A6080);
  font-size: 0.83rem;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s, color 0.15s;
}
.btn-corrections:hover:not(:disabled) {
  background: var(--app-primary, #2A6080);
  color: #fff;
}
.btn-corrections:disabled { opacity: 0.55; cursor: not-allowed; }

.results-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
}

.results-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}

.results-table th {
  padding: 0.5rem 0.75rem;
  text-align: left;
  background: var(--color-surface, #f4f7fc);
  border-bottom: 1px solid var(--color-border, #d0d7e8);
  font-size: 0.78rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-secondary, #6b7a99);
  white-space: nowrap;
}

.result-row {
  cursor: pointer;
  transition: background 0.1s;
}
.result-row:hover { background: color-mix(in srgb, var(--app-primary, #2A6080) 6%, transparent); }
.result-row.top-row { font-weight: 600; }

.result-row td {
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--color-border, #d0d7e8);
}
.result-row:last-child td { border-bottom: none; }

.rank-cell   { width: 2.5rem; text-align: center; font-size: 1.1rem; }
.model-cell  { font-family: var(--font-mono, monospace); word-break: break-all; }
.score-cell  { width: 5rem; text-align: center; }
.latency-cell { width: 5rem; text-align: right; color: var(--color-text-secondary, #6b7a99); }
.violation-cell { width: 4rem; text-align: center; color: var(--color-text-secondary, #6b7a99); }
.violation-cell.has-violation { color: #b91c1c; font-weight: 700; }

.score-pill {
  display: inline-block;
  padding: 0.15rem 0.55rem;
  border-radius: 9999px;
  font-weight: 700;
  font-size: 0.82rem;
}

/* ── Sample outputs ───────────────────────────────────────────────────────── */

.sample-outputs {
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  overflow: hidden;
}

.sample-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.85rem;
  background: var(--color-surface, #f4f7fc);
  border-bottom: 1px solid var(--color-border, #d0d7e8);
  font-size: 0.85rem;
}

.btn-collapse {
  border: none;
  background: transparent;
  font-size: 0.78rem;
  color: var(--color-text-secondary, #6b7a99);
  cursor: pointer;
}

.sample-prompt {
  padding: 0.65rem 0.85rem;
  border-bottom: 1px solid var(--color-border, #d0d7e8);
}
.sample-prompt:last-child { border-bottom: none; }

.sample-tag {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.35rem;
  font-size: 0.8rem;
}

.tag-name  { font-weight: 600; color: var(--color-text, #1a2338); }
.tag-score { color: var(--app-primary, #2A6080); font-weight: 700; }
.tag-latency { color: var(--color-text-secondary, #6b7a99); margin-left: auto; }

.sample-text {
  margin: 0;
  font-size: 0.82rem;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
  background: var(--color-bg, #fff);
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.35rem;
  padding: 0.5rem 0.65rem;
  color: var(--color-text, #1a2338);
  font-family: inherit;
}

@media (max-width: 640px) {
  .voice-controls { flex-direction: column; }
  .model-picker, .options-panel { min-width: 0; }
  .option-hint { display: none; }
  .group-note { display: none; }
}
</style>
