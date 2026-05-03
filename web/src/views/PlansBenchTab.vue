<template>
  <div class="plans-bench-tab">

    <!-- ── Model selection ──────────────────────────────────────────────── -->
    <details class="model-picker" open>
      <summary class="picker-summary">
        <span class="picker-title">🤖 Models</span>
        <span class="picker-badge">{{ allSelectedModels.length }} selected</span>
        <button class="btn-refresh" :disabled="loadingMeta" @click.stop="loadMeta" title="Refresh">
          {{ loadingMeta ? '⏳' : '🔄' }}
        </button>
      </summary>
      <div class="picker-body">
        <div v-if="loadingMeta" class="picker-loading">Loading…</div>
        <div v-else-if="loadError" class="picker-error">{{ loadError }}</div>
        <template v-else>

          <!-- cf-orch catalog (live from coordinator) -->
          <div class="picker-group" v-if="cfOrchModels.length">
            <div class="group-header">
              <label class="group-check">
                <input
                  type="checkbox"
                  :checked="isGroupAllSelected('cforch')"
                  :indeterminate.prop="isGroupIndeterminate('cforch')"
                  @change="toggleGroup('cforch', ($event.target as HTMLInputElement).checked)"
                />
                <span class="group-label">cf-orch catalog</span>
                <span class="group-count">({{ cfOrchModels.length }})</span>
              </label>
              <span class="group-note">live from coordinator — auto-allocated per run</span>
            </div>
            <div class="model-list">
              <label v-for="m in cfOrchModels" :key="m.id" class="model-item">
                <input type="checkbox" :value="m.id" v-model="selectedModels" />
                <span class="model-key">{{ m.name }}</span>
                <span v-if="m.vram_mb" class="model-meta">{{ formatMb(m.vram_mb) }} VRAM</span>
                <span v-if="m.description" class="model-desc">{{ m.description }}</span>
              </label>
            </div>
          </div>

          <!-- Registered shortcuts -->
          <div class="picker-group">
            <div class="group-header">
              <span class="group-label">Registry shortcuts</span>
              <span class="group-count">({{ registeredModels.length }})</span>
            </div>
            <div class="model-list">
              <label v-for="m in registeredModels" :key="m.key" class="model-item">
                <input type="checkbox" :value="m.key" v-model="selectedModels" />
                <span class="model-key">{{ m.key }}</span>
                <span class="model-desc">{{ m.description }}</span>
              </label>
            </div>
          </div>

          <!-- Custom -->
          <div class="custom-model-row">
            <label class="option-label">Custom model ID:</label>
            <input
              v-model="customModel"
              class="custom-model-input"
              placeholder="e.g. granite-4.1-8b"
              @keydown.enter="addCustomModel"
            />
            <button class="btn-add-custom" :disabled="!customModel.trim()" @click="addCustomModel">Add</button>
          </div>
          <div v-if="customModels.length" class="custom-chips">
            <span v-for="m in customModels" :key="m" class="custom-chip">
              {{ m }}
              <button class="chip-remove" @click="removeCustomModel(m)">×</button>
            </span>
          </div>

        </template>
      </div>
    </details>

    <!-- ── Options ──────────────────────────────────────────────────────── -->
    <details class="options-panel">
      <summary class="picker-summary">
        <span class="picker-title">⚙️ Options</span>
      </summary>
      <div class="options-body">
        <label class="option-row">
          <input type="checkbox" v-model="useCfOrch" :disabled="running" />
          <span class="option-label">Use cf-orch coordinator</span>
          <span class="option-hint">Allocates each model via cf-orch (required for catalog models)</span>
        </label>
        <label class="option-row" :class="{ dimmed: useCfOrch }">
          <span class="option-label">Direct API base</span>
          <input
            v-model="apiBase"
            class="option-text"
            placeholder="http://localhost:8080/v1"
            :disabled="useCfOrch || running"
          />
          <span class="option-hint">Only used when cf-orch is disabled</span>
        </label>
        <div class="option-row">
          <span class="option-label">Prompts</span>
          <div class="prompt-filter">
            <label v-for="p in allPromptIds" :key="p" class="prompt-check-item">
              <input type="checkbox" :value="p" v-model="selectedPromptIds" />
              <span>{{ p }}</span>
            </label>
          </div>
          <span class="option-hint">Leave all checked to run all 10 held-out prompts</span>
        </div>
        <label class="option-row">
          <span class="option-label">Workers</span>
          <input
            v-model.number="workers"
            type="number"
            min="1"
            max="8"
            class="option-number"
            :disabled="running"
          />
          <span class="option-hint">Run N models in parallel (1 = sequential)</span>
        </label>
      </div>
    </details>

    <!-- ── Run controls ─────────────────────────────────────────────────── -->
    <div class="run-bar">
      <button
        class="btn-run"
        :disabled="running || allSelectedModels.length === 0"
        @click="startBenchmark"
      >
        {{ running ? '⏳ Running…' : results ? '🔄 Re-run' : '▶ Run Benchmark' }}
      </button>
      <button v-if="running" class="btn-cancel" @click="cancelBenchmark">✕ Cancel</button>
      <span v-if="allSelectedModels.length === 0 && !running" class="run-hint">
        Select at least one model above
      </span>
    </div>

    <!-- ── Progress log ─────────────────────────────────────────────────── -->
    <div v-if="runLog.length" class="run-log">
      <div class="run-log-header">
        <span class="run-log-title">Run log</span>
        <div class="run-log-actions">
          <button class="btn-log-action" @click="copyLog" :title="copyTooltip">{{ copyLabel }}</button>
          <button class="btn-log-action" @click="runLog = []">Clear</button>
        </div>
      </div>
      <pre class="run-log-body" ref="logEl">{{ runLog.join('\n') }}</pre>
    </div>

    <!-- ── Past runs ────────────────────────────────────────────────────── -->
    <div class="history-bar" v-if="pastRuns.length">
      <label class="history-label">📂 Past runs:</label>
      <select class="history-select" v-model="selectedRun" @change="loadRun(selectedRun)">
        <option value="">— select a past run —</option>
        <option v-for="r in pastRuns" :key="r.run_id" :value="r.run_id">
          {{ r.date }} · {{ r.models.join(', ') }} · avg {{ r.avg_score.toFixed(3) }}
        </option>
      </select>
    </div>

    <!-- ── Results ──────────────────────────────────────────────────────── -->
    <div v-if="results" class="results-section">

      <!-- Comparison table (multi-model) -->
      <template v-if="modelKeys.length > 1">
        <h2 class="results-title">Comparison</h2>
        <div class="table-wrap">
          <table class="results-table">
            <thead>
              <tr>
                <th class="col-prompt">Prompt</th>
                <th v-for="mk in modelKeys" :key="mk" class="col-model">{{ mk }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="pid in promptOrder" :key="pid">
                <td class="cell-prompt">
                  <span class="prompt-name">{{ promptName(pid) }}</span>
                  <span class="prompt-id">{{ pid }}</span>
                </td>
                <td
                  v-for="mk in modelKeys"
                  :key="mk"
                  class="cell-score"
                  :class="isBestForPrompt(mk, pid) ? 'best-score' : ''"
                >
                  {{ scoreFor(mk, pid).toFixed(3) }}
                </td>
              </tr>
              <tr class="avg-row">
                <td class="cell-prompt avg-label">Average</td>
                <td
                  v-for="mk in modelKeys"
                  :key="mk"
                  class="cell-score avg-score"
                  :class="isBestAvg(mk) ? 'best-score' : ''"
                >
                  {{ modelAvg(mk).toFixed(3) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Rubric breakdown per model -->
        <h2 class="results-title" style="margin-top:1.5rem">Rubric breakdown</h2>
        <div class="rubric-grid">
          <div v-for="mk in modelKeys" :key="mk" class="rubric-card">
            <div class="rubric-card-title">{{ mk }}</div>
            <div v-for="(label, key) in rubricLabels" :key="key" class="rubric-row">
              <span class="rubric-label">{{ label }}</span>
              <div class="rubric-bar-wrap">
                <div class="rubric-bar" :style="{ width: (rubricAvg(mk, key) * 100).toFixed(1) + '%' }"></div>
              </div>
              <span class="rubric-val">{{ rubricAvg(mk, key).toFixed(2) }}</span>
            </div>
          </div>
        </div>
      </template>

      <!-- Single model results -->
      <template v-else>
        <h2 class="results-title">Results — {{ modelKeys[0] }}</h2>
        <div class="table-wrap">
          <table class="results-table">
            <thead>
              <tr>
                <th class="col-prompt">Prompt</th>
                <th class="col-score">Score</th>
                <th class="col-words">Words</th>
                <th class="col-latency">Latency</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in singleResults"
                :key="r.prompt_id"
                class="result-row"
                :class="r.error ? 'error-row' : r.total_score >= 0.6 ? 'good-row' : r.total_score < 0.3 ? 'warn-row' : ''"
                @click="togglePromptDetail(r.prompt_id)"
              >
                <td class="cell-prompt">
                  <span class="prompt-name">{{ r.prompt_name }}</span>
                  <span class="prompt-id">{{ r.prompt_id }}</span>
                </td>
                <td class="cell-score">
                  <span class="score-pill" :style="scorePillStyle(r.total_score)">
                    {{ r.error ? 'ERR' : r.total_score.toFixed(3) }}
                  </span>
                </td>
                <td class="cell-words">{{ r.word_count || '—' }}</td>
                <td class="cell-latency">{{ r.latency_s ? r.latency_s.toFixed(1) + 's' : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Rubric breakdown for single model -->
        <div class="rubric-card single-rubric">
          <div class="rubric-card-title">Rubric breakdown</div>
          <div v-for="(label, key) in rubricLabels" :key="key" class="rubric-row">
            <span class="rubric-label">{{ label }}</span>
            <div class="rubric-bar-wrap">
              <div class="rubric-bar" :style="{ width: (rubricAvg(modelKeys[0], key) * 100).toFixed(1) + '%' }"></div>
            </div>
            <span class="rubric-val">{{ rubricAvg(modelKeys[0], key).toFixed(2) }}</span>
          </div>
        </div>

        <!-- Prompt detail panel -->
        <div v-if="expandedPrompt" class="prompt-detail">
          <div class="prompt-detail-header">
            <span>{{ expandedPrompt.prompt_name }} ({{ expandedPrompt.prompt_id }})</span>
            <button class="btn-close" @click="expandedPrompt = null">✕</button>
          </div>
          <div class="detail-grid">
            <div class="detail-section">
              <div class="detail-label">Rubric scores</div>
              <div v-for="(label, key) in rubricLabels" :key="key" class="rubric-row">
                <span class="rubric-label">{{ label }}</span>
                <div class="rubric-bar-wrap">
                  <div class="rubric-bar" :style="{ width: ((expandedPrompt.scores[key] ?? 0) * 100).toFixed(1) + '%' }"></div>
                </div>
                <span class="rubric-val">{{ (expandedPrompt.scores[key] ?? 0).toFixed(2) }}</span>
              </div>
            </div>
            <div class="detail-section">
              <div class="detail-label">Response</div>
              <pre class="detail-response">{{ expandedPrompt.response }}</pre>
            </div>
          </div>
        </div>
      </template>
    </div>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch } from 'vue'

interface ModelEntry    { key: string; description: string }
interface CfOrchModel  { id: string; name: string; vram_mb: number | null; description: string }
interface PastRun { run_id: string; filename: string; date: string; models: string[]; avg_score: number }
interface PromptResult {
  prompt_id: string
  prompt_name: string
  model_key: string
  response: string
  latency_s: number
  word_count: number
  scores: Record<string, number>
  total_score: number
  error?: string
}
type BenchResults = Record<string, PromptResult[]>

const ALL_PROMPT_IDS = ['ho_001','ho_002','ho_003','ho_004','ho_005','ho_006','ho_007','ho_008','ho_009','ho_010']

// ── State ────────────────────────────────────────────────────────────────────
const loadingMeta      = ref(false)
const loadError        = ref('')
const registeredModels = ref<ModelEntry[]>([])
const cfOrchModels     = ref<CfOrchModel[]>([])
const rubricLabels     = ref<Record<string, string>>({})

const selectedModels   = ref<string[]>([])
const customModel      = ref('')
const customModels     = ref<string[]>([])
const useCfOrch        = ref(true)
const apiBase          = ref('')
const workers          = ref(1)
const allPromptIds     = ref<string[]>(ALL_PROMPT_IDS)
const selectedPromptIds = ref<string[]>([...ALL_PROMPT_IDS])

const running   = ref(false)
const runLog    = ref<string[]>([])
const logEl     = ref<HTMLPreElement | null>(null)
const copyLabel = ref('Copy')
const copyTooltip = ref('Copy log to clipboard')

async function copyLog() {
  const text = runLog.value.join('\n')
  await navigator.clipboard.writeText(text)
  copyLabel.value = 'Copied!'
  copyTooltip.value = 'Copied!'
  setTimeout(() => {
    copyLabel.value = 'Copy'
    copyTooltip.value = 'Copy log to clipboard'
  }, 2000)
}
const results   = ref<BenchResults | null>(null)
const pastRuns  = ref<PastRun[]>([])
const selectedRun = ref('')

const expandedPromptId = ref<string | null>(null)

// ── Computed ─────────────────────────────────────────────────────────────────
const allSelectedModels = computed(() => [...selectedModels.value, ...customModels.value])

const modelKeys = computed(() => results.value ? Object.keys(results.value) : [])

const singleResults = computed((): PromptResult[] => {
  if (!results.value || modelKeys.value.length !== 1) return []
  return results.value[modelKeys.value[0]] ?? []
})

const promptOrder = computed((): string[] => {
  if (!results.value) return []
  const first = Object.values(results.value)[0] ?? []
  return first.map(r => r.prompt_id)
})

const expandedPrompt = computed((): PromptResult | null => {
  if (!expandedPromptId.value || !results.value) return null
  return singleResults.value.find(r => r.prompt_id === expandedPromptId.value) ?? null
})

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatMb(mb: number | null): string {
  if (!mb) return ''
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`
}

function isGroupAllSelected(group: 'cforch'): boolean {
  const ids = cfOrchModels.value.map(m => m.id)
  return ids.length > 0 && ids.every(id => selectedModels.value.includes(id))
}

function isGroupIndeterminate(group: 'cforch'): boolean {
  const ids = cfOrchModels.value.map(m => m.id)
  const selected = ids.filter(id => selectedModels.value.includes(id))
  return selected.length > 0 && selected.length < ids.length
}

function toggleGroup(group: 'cforch', checked: boolean) {
  const ids = cfOrchModels.value.map(m => m.id)
  if (checked) {
    selectedModels.value = [...new Set([...selectedModels.value, ...ids])]
  } else {
    selectedModels.value = selectedModels.value.filter(m => !ids.includes(m))
  }
}

function promptName(pid: string): string {
  const r = Object.values(results.value ?? {})[0]?.find(x => x.prompt_id === pid)
  return r?.prompt_name ?? pid
}

function scoreFor(mk: string, pid: string): number {
  return results.value?.[mk]?.find(r => r.prompt_id === pid)?.total_score ?? 0
}

function modelAvg(mk: string): number {
  const rows = results.value?.[mk] ?? []
  const ok = rows.filter(r => !r.error)
  if (!ok.length) return 0
  return ok.reduce((s, r) => s + r.total_score, 0) / ok.length
}

function isBestForPrompt(mk: string, pid: string): boolean {
  const best = Math.max(...modelKeys.value.map(k => scoreFor(k, pid)))
  return scoreFor(mk, pid) === best && modelKeys.value.length > 1
}

function isBestAvg(mk: string): boolean {
  const best = Math.max(...modelKeys.value.map(k => modelAvg(k)))
  return modelAvg(mk) === best && modelKeys.value.length > 1
}

function rubricAvg(mk: string, key: string): number {
  const rows = results.value?.[mk] ?? []
  const ok = rows.filter(r => !r.error && r.scores)
  if (!ok.length) return 0
  return ok.reduce((s, r) => s + (r.scores[key] ?? 0), 0) / ok.length
}

function scorePillStyle(score: number): string {
  const h = Math.round(score * 120)  // 0 = red, 120 = green
  return `background: hsl(${h}, 60%, 42%); color: #fff`
}

function togglePromptDetail(pid: string) {
  expandedPromptId.value = expandedPromptId.value === pid ? null : pid
}

// ── API calls ─────────────────────────────────────────────────────────────────
async function loadMeta() {
  loadingMeta.value = true
  loadError.value = ''
  try {
    const r = await fetch('/api/plans-bench/models')
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const data = await r.json()
    registeredModels.value = data.registry ?? []
    cfOrchModels.value     = data.cforch_models ?? []
    rubricLabels.value     = data.rubric_labels ?? {}
  } catch (e: unknown) {
    loadError.value = e instanceof Error ? e.message : String(e)
  } finally {
    loadingMeta.value = false
  }
}

async function loadPastRuns() {
  try {
    const r = await fetch('/api/plans-bench/results')
    if (!r.ok) return
    pastRuns.value = await r.json()
  } catch {
    // non-critical
  }
}

async function loadRun(runId: string) {
  if (!runId) return
  try {
    const r = await fetch(`/api/plans-bench/results/${runId}`)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    results.value = await r.json()
  } catch (e: unknown) {
    runLog.value.push(`Error loading run: ${e instanceof Error ? e.message : String(e)}`)
  }
}

function addCustomModel() {
  const key = customModel.value.trim()
  if (key && !customModels.value.includes(key)) {
    customModels.value = [...customModels.value, key]
  }
  customModel.value = ''
}

function removeCustomModel(key: string) {
  customModels.value = customModels.value.filter(m => m !== key)
}

function startBenchmark() {
  if (running.value || allSelectedModels.value.length === 0) return
  running.value = true
  runLog.value = []
  results.value = null
  expandedPromptId.value = null

  const params = new URLSearchParams({
    models: allSelectedModels.value.join(','),
    use_cforch: String(useCfOrch.value),
    api_base: apiBase.value.trim(),
    workers: String(workers.value),
    prompt_ids: selectedPromptIds.value.length < allPromptIds.value.length
      ? selectedPromptIds.value.join(',')
      : '',
  })

  const es = new EventSource(`/api/plans-bench/run?${params}`)
  es.onmessage = async (ev) => {
    const msg = JSON.parse(ev.data)
    if (msg.type === 'progress') {
      runLog.value.push(msg.message)
      await nextTick()
      if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
    } else if (msg.type === 'result') {
      results.value = msg.results
      await loadPastRuns()
    } else if (msg.type === 'complete') {
      running.value = false
      es.close()
    } else if (msg.type === 'error') {
      runLog.value.push(`ERROR: ${msg.message}`)
      running.value = false
      es.close()
    } else if (msg.type === 'cancelled') {
      runLog.value.push('Benchmark cancelled.')
      running.value = false
      es.close()
    }
  }
  es.onerror = () => {
    runLog.value.push('Connection error — benchmark may have ended unexpectedly.')
    running.value = false
    es.close()
  }
}

async function cancelBenchmark() {
  try {
    await fetch('/api/plans-bench/cancel', { method: 'POST' })
  } catch {
    // ignore
  }
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(() => {
  loadMeta()
  loadPastRuns()
})
</script>

<style scoped>
.plans-bench-tab {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

/* ── Picker / options shared ─────────────────────────────────────────── */
.model-picker,
.options-panel {
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  overflow: hidden;
}

.picker-summary {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.6rem 0.9rem;
  background: var(--color-surface-alt, #f5f7fc);
  cursor: pointer;
  user-select: none;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--color-text, #1a2540);
}

.picker-title { flex: 1 }

.picker-badge {
  background: var(--app-primary, #2A6080);
  color: #fff;
  border-radius: 1rem;
  padding: 0.15rem 0.55rem;
  font-size: 0.75rem;
}

.btn-refresh {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 0.875rem;
  padding: 0.1rem 0.3rem;
  border-radius: 0.25rem;
}
.btn-refresh:hover { background: var(--color-hover, #e8ecf7) }

.picker-body,
.options-body {
  padding: 0.75rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.picker-loading { color: var(--color-muted, #8a98b4); font-size: 0.85rem }
.picker-error   { color: var(--color-danger, #c0392b); font-size: 0.85rem }

/* ── Group headers ───────────────────────────────────────────────────── */
.picker-group { display: flex; flex-direction: column; gap: 0.4rem }

.group-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.2rem 0;
  border-bottom: 1px solid var(--color-border, #d0d7e8);
  margin-bottom: 0.2rem;
}
.group-check  { display: flex; align-items: center; gap: 0.35rem; cursor: pointer }
.group-label  { font-weight: 600; font-size: 0.82rem }
.group-count  { color: var(--color-muted, #8a98b4); font-size: 0.78rem }
.group-note   { color: var(--color-muted, #8a98b4); font-size: 0.75rem; margin-left: auto }

.model-meta   { color: var(--color-muted, #8a98b4); font-size: 0.78rem; margin-left: auto }

.dimmed { opacity: 0.45 }

/* ── Model list ──────────────────────────────────────────────────────── */
.model-list {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.model-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
  cursor: pointer;
}
.model-item:hover { color: var(--app-primary, #2A6080) }
.model-key  { font-weight: 600; min-width: 10rem }
.model-desc { color: var(--color-muted, #8a98b4); font-size: 0.8rem }

/* ── Custom model row ────────────────────────────────────────────────── */
.custom-model-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.25rem;
  flex-wrap: wrap;
}
.custom-model-input {
  flex: 1;
  min-width: 10rem;
  padding: 0.3rem 0.5rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.3rem;
  font-size: 0.85rem;
  background: var(--color-surface, #fff);
  color: var(--color-text, #1a2540);
}
.btn-add-custom {
  padding: 0.3rem 0.75rem;
  background: var(--app-primary, #2A6080);
  color: #fff;
  border: none;
  border-radius: 0.3rem;
  font-size: 0.8rem;
  cursor: pointer;
}
.btn-add-custom:disabled { opacity: 0.4; cursor: not-allowed }

.custom-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}
.custom-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  background: var(--color-surface-alt, #f5f7fc);
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 1rem;
  padding: 0.2rem 0.55rem;
  font-size: 0.8rem;
}
.chip-remove {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 0.9rem;
  color: var(--color-muted, #8a98b4);
  padding: 0;
  line-height: 1;
}

/* ── Options ─────────────────────────────────────────────────────────── */
.option-row {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  font-size: 0.85rem;
  flex-wrap: wrap;
}
.option-label {
  min-width: 8rem;
  font-weight: 500;
  color: var(--color-text, #1a2540);
  padding-top: 0.25rem;
}
.option-text {
  flex: 1;
  min-width: 14rem;
  padding: 0.3rem 0.5rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.3rem;
  font-size: 0.85rem;
  background: var(--color-surface, #fff);
  color: var(--color-text, #1a2540);
}
.option-hint { color: var(--color-muted, #8a98b4); font-size: 0.78rem; align-self: center }
.option-number {
  width: 4.5rem;
  padding: 0.3rem 0.5rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.3rem;
  font-size: 0.85rem;
  background: var(--color-surface, #fff);
  color: var(--color-text, #1a2540);
  text-align: center;
}

.prompt-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.75rem;
}
.prompt-check-item {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.8rem;
  cursor: pointer;
}

/* ── Run bar ─────────────────────────────────────────────────────────── */
.run-bar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.btn-run {
  padding: 0.5rem 1.25rem;
  background: var(--app-primary, #2A6080);
  color: #fff;
  border: none;
  border-radius: 0.4rem;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s;
}
.btn-run:disabled { opacity: 0.45; cursor: not-allowed }
.btn-run:not(:disabled):hover { opacity: 0.88 }

.btn-cancel {
  padding: 0.5rem 1rem;
  background: transparent;
  border: 1px solid var(--color-danger, #c0392b);
  color: var(--color-danger, #c0392b);
  border-radius: 0.4rem;
  font-size: 0.85rem;
  cursor: pointer;
}

.run-hint { font-size: 0.82rem; color: var(--color-muted, #8a98b4) }

/* ── Run log ─────────────────────────────────────────────────────────── */
.run-log {
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  overflow: hidden;
}
.run-log-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.4rem 0.8rem;
  background: var(--color-surface-alt, #f5f7fc);
  font-size: 0.8rem;
  font-weight: 600;
}
.run-log-actions {
  display: flex;
  gap: 0.5rem;
}
.btn-log-action {
  background: none;
  border: none;
  font-size: 0.78rem;
  color: var(--color-muted, #8a98b4);
  cursor: pointer;
  padding: 0;
}
.btn-log-action:hover {
  color: var(--color-text, #1a2540);
}
.run-log-body {
  margin: 0;
  padding: 0.7rem 0.9rem;
  font-size: 0.78rem;
  line-height: 1.5;
  max-height: 14rem;
  overflow-y: auto;
  white-space: pre-wrap;
  color: var(--color-text, #1a2540);
  background: var(--color-surface, #fff);
}

/* ── History bar ─────────────────────────────────────────────────────── */
.history-bar {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
}
.history-label  { font-size: 0.85rem; font-weight: 500 }
.history-select {
  flex: 1;
  min-width: 14rem;
  padding: 0.35rem 0.6rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.3rem;
  font-size: 0.85rem;
  background: var(--color-surface, #fff);
  color: var(--color-text, #1a2540);
}

/* ── Results section ─────────────────────────────────────────────────── */
.results-section { display: flex; flex-direction: column; gap: 1rem }

.results-title {
  font-size: 1rem;
  font-weight: 700;
  color: var(--app-primary, #2A6080);
  margin: 0;
}

.table-wrap { overflow-x: auto }

.results-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.results-table th {
  text-align: left;
  padding: 0.45rem 0.6rem;
  background: var(--color-surface-alt, #f5f7fc);
  border-bottom: 2px solid var(--color-border, #d0d7e8);
  font-weight: 600;
  white-space: nowrap;
}
.results-table td {
  padding: 0.4rem 0.6rem;
  border-bottom: 1px solid var(--color-border, #d0d7e8);
  vertical-align: middle;
}

.col-prompt { min-width: 12rem }
.col-model  { min-width: 6rem; text-align: right }
.col-score, .col-words, .col-latency { min-width: 5rem; text-align: right }

.cell-prompt {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}
.prompt-name { font-weight: 500 }
.prompt-id   { font-size: 0.75rem; color: var(--color-muted, #8a98b4) }

.cell-score, .col-model { text-align: right }

.best-score {
  background: color-mix(in srgb, var(--app-primary, #2A6080) 8%, transparent);
  font-weight: 700;
}

.avg-row td { font-weight: 700; background: var(--color-surface-alt, #f5f7fc) }
.avg-label  { font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.04em }

.score-pill {
  display: inline-block;
  min-width: 3.5rem;
  text-align: center;
  padding: 0.15rem 0.4rem;
  border-radius: 0.3rem;
  font-size: 0.8rem;
  font-weight: 700;
}

.result-row { cursor: pointer }
.result-row:hover td { background: var(--color-hover, #e8ecf7) }
.good-row td { background: color-mix(in srgb, #27ae60 6%, transparent) }
.warn-row td { background: color-mix(in srgb, #e74c3c 6%, transparent) }
.error-row td { background: color-mix(in srgb, #e74c3c 10%, transparent); opacity: 0.7 }

/* ── Rubric breakdown ────────────────────────────────────────────────── */
.rubric-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
}
.rubric-card {
  flex: 1;
  min-width: 18rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  padding: 0.75rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}
.single-rubric { max-width: 38rem }

.rubric-card-title {
  font-weight: 700;
  font-size: 0.875rem;
  color: var(--app-primary, #2A6080);
  margin-bottom: 0.25rem;
}

.rubric-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8rem;
}
.rubric-label {
  flex: 0 0 13rem;
  color: var(--color-text, #1a2540);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rubric-bar-wrap {
  flex: 1;
  height: 0.5rem;
  background: var(--color-surface-alt, #f5f7fc);
  border-radius: 0.25rem;
  overflow: hidden;
  min-width: 4rem;
}
.rubric-bar {
  height: 100%;
  background: var(--app-primary, #2A6080);
  border-radius: 0.25rem;
  transition: width 0.3s ease;
}
.rubric-val {
  min-width: 2.5rem;
  text-align: right;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

/* ── Prompt detail panel ─────────────────────────────────────────────── */
.prompt-detail {
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  overflow: hidden;
}
.prompt-detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5rem 0.9rem;
  background: var(--color-surface-alt, #f5f7fc);
  font-weight: 600;
  font-size: 0.875rem;
}
.btn-close {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 1rem;
  color: var(--color-muted, #8a98b4);
}

.detail-grid {
  display: flex;
  gap: 1rem;
  padding: 0.75rem 1rem;
  flex-wrap: wrap;
}
.detail-section {
  flex: 1;
  min-width: 14rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.detail-label {
  font-weight: 600;
  font-size: 0.8rem;
  color: var(--color-muted, #8a98b4);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.detail-response {
  font-size: 0.78rem;
  line-height: 1.55;
  max-height: 20rem;
  overflow-y: auto;
  white-space: pre-wrap;
  color: var(--color-text, #1a2540);
  margin: 0;
  background: var(--color-surface, #fff);
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.3rem;
  padding: 0.5rem 0.75rem;
}
</style>
