<template>
  <div class="llm-eval-tab">

    <!-- Task Selection -->
    <details class="model-picker" open>
      <summary class="picker-summary">
        <span class="picker-title">📋 Task Selection</span>
        <span class="picker-badge">{{ llmTaskBadge }}</span>
        <button class="picker-bulk-btn" @click.stop.prevent="selectAllTasks()">All</button>
        <button class="picker-bulk-btn" @click.stop.prevent="clearAllTasks()">None</button>
      </summary>
      <div class="picker-body">
        <div v-if="llmTasksLoading" class="picker-loading">Loading tasks…</div>
        <div v-else-if="Object.keys(llmTasksByType).length === 0" class="picker-empty">
          No tasks found — check API connection.
        </div>
        <template v-else>
          <div v-for="(tasks, type) in llmTasksByType" :key="type" class="picker-category">
            <label class="picker-cat-header">
              <input
                type="checkbox"
                :checked="isTaskTypeAllSelected(tasks)"
                :indeterminate="isTaskTypeIndeterminate(tasks)"
                @change="toggleTaskType(tasks, ($event.target as HTMLInputElement).checked)"
              />
              <span class="picker-cat-name">{{ type }}</span>
              <span class="picker-cat-count">({{ tasks.length }})</span>
            </label>
            <div class="picker-model-list">
              <label v-for="t in tasks" :key="t.id" class="picker-model-row">
                <input
                  type="checkbox"
                  :checked="selectedLlmTasks.has(t.id)"
                  @change="toggleLlmTask(t.id, ($event.target as HTMLInputElement).checked)"
                />
                <span class="picker-model-name" :title="t.name">{{ t.name }}</span>
              </label>
            </div>
          </div>
        </template>
      </div>
    </details>

    <!-- Model Selection -->
    <details class="model-picker" open>
      <summary class="picker-summary">
        <span class="picker-title">🎯 Model Selection</span>
        <span class="picker-badge">{{ llmModelBadge }}</span>
        <button class="picker-bulk-btn" @click.stop.prevent="selectAllModels()">All</button>
        <button class="picker-bulk-btn" @click.stop.prevent="clearAllModels()">None</button>
      </summary>
      <div class="picker-body">
        <div v-if="llmModelsLoading" class="picker-loading">Loading models…</div>
        <div v-else-if="Object.keys(llmModelsByService).length === 0" class="picker-empty">
          No models found — check cf-orch connection.
        </div>
        <template v-else>
          <div v-for="(models, service) in llmModelsByService" :key="service" class="picker-category">
            <label class="picker-cat-header">
              <input
                type="checkbox"
                :checked="isServiceAllSelected(models)"
                :indeterminate="isServiceIndeterminate(models)"
                @change="toggleService(models, ($event.target as HTMLInputElement).checked)"
              />
              <span class="picker-cat-name">{{ service }}</span>
              <span class="picker-cat-count">({{ models.length }})</span>
            </label>
            <div class="picker-model-list">
              <label v-for="m in models" :key="m.id" class="picker-model-row">
                <input
                  type="checkbox"
                  :checked="selectedLlmModels.has(m.id)"
                  @change="toggleLlmModel(m.id, ($event.target as HTMLInputElement).checked)"
                />
                <span class="picker-model-name" :title="m.name">{{ m.name }}</span>
                <span class="picker-adapter-type" v-if="m.tags.length">{{ m.tags.join(', ') }}</span>
              </label>
            </div>
          </div>
        </template>
      </div>
    </details>

    <!-- Node Selection -->
    <div class="node-picker" v-if="llmNodes.length > 0">
      <span class="node-picker-label">Nodes:</span>
      <label
        v-for="node in llmNodes"
        :key="node.node_id"
        class="node-chip"
        :class="{ 'node-chip--off': !enabledNodes.has(node.node_id), 'node-chip--offline': !node.online }"
        :title="node.online ? `${node.node_id} — ${node.gpus.length} GPU(s)` : `${node.node_id} — offline`"
      >
        <input
          type="checkbox"
          class="node-chip-check"
          :checked="enabledNodes.has(node.node_id)"
          :disabled="!node.online || llmRunning"
          @change="toggleNode(node.node_id, ($event.target as HTMLInputElement).checked)"
        />
        {{ node.node_id }}
        <span class="node-chip-status" v-if="!node.online">offline</span>
      </label>
      <span class="node-picker-hint">
        {{ enabledNodeIds.length === llmNodes.filter(n => n.online).length
            ? 'auto-routing (all nodes)'
            : `restricted to: ${enabledNodeIds.join(', ')}` }}
      </span>
    </div>

    <!-- Run Controls -->
    <div class="run-controls">
      <button
        class="btn-run"
        :disabled="llmRunning || selectedLlmTasks.size === 0 || selectedLlmModels.size === 0"
        @click="startLlmBenchmark"
      >
        {{ llmRunning ? '⏳ Running…' : '▶ Run LLM Eval' }}
      </button>
      <button v-if="llmRunning" class="btn-cancel" @click="cancelLlmBenchmark">✕ Cancel</button>
      <input
        v-model="llmJudgeUrl"
        class="judge-url-input"
        placeholder="Judge URL — leave empty to skip LLM judge scoring"
        :disabled="llmRunning"
        title="Optional: URL of a running cf-text service (e.g. http://10.1.10.158:8008). When set, each LLM response gets a secondary score from the judge model — adds a 'judge' column to results. Empty = primary quality scoring only."
      />
      <label class="workers-label" title="Run this many models concurrently (requires multiple GPUs)">
        <span class="workers-prefix">workers</span>
        <input
          v-model.number="llmWorkers"
          type="number"
          min="1"
          max="8"
          class="workers-input"
          :disabled="llmRunning"
        />
      </label>
      <span v-if="selectedLlmTasks.size === 0 || selectedLlmModels.size === 0" class="run-hint">
        Select at least one task and one model to run.
      </span>
    </div>

    <!-- Progress log -->
    <div v-if="llmRunning || llmRunLog.length" class="run-log">
      <div class="run-log-title">
        <span>{{ llmRunning ? '⏳ Running LLM eval…' : llmError ? '❌ Failed' : '✅ Done' }}</span>
        <button class="btn-ghost" @click="llmRunLog = []; llmError = ''">Clear</button>
      </div>
      <div class="log-lines" ref="llmLogEl">
        <div
          v-for="(line, i) in llmRunLog"
          :key="i"
          class="log-line"
          :class="{ 'log-error': line.startsWith('ERROR') || line.startsWith('[error]') }"
        >{{ line }}</div>
      </div>
      <p v-if="llmError" class="run-error">{{ llmError }}</p>
    </div>

    <!-- Results table -->
    <template v-if="llmResults.length > 0">
      <h2 class="chart-title">LLM Eval Results</h2>
      <div class="heatmap-scroll">
        <table class="heatmap llm-results-table">
          <thead>
            <tr>
              <th class="hm-label-col">Model</th>
              <th class="hm-model-col">overall</th>
              <th v-if="llmHasJudge" class="hm-model-col hm-judge-col">judge</th>
              <th v-for="col in llmTaskTypeCols" :key="col" class="hm-model-col">{{ col }}</th>
              <th class="hm-model-col">tok/s</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in llmResults" :key="row.model_id">
              <td class="hm-label-cell llm-model-name-cell" :title="row.model_id">{{ row.model_name }}</td>
              <td
                class="hm-value-cell"
                :class="{ 'bt-best': llmBestByCol['overall'] === row.model_id }"
              >{{ pct(row.avg_quality_score) }}</td>
              <td
                v-if="llmHasJudge"
                class="hm-value-cell hm-judge-cell"
                :class="{ 'bt-best': llmBestByCol['judge'] === row.model_id }"
                title="LLM-as-judge secondary score"
              >{{ row.avg_judge_score != null ? pct(row.avg_judge_score) : '—' }}</td>
              <td
                v-for="col in llmTaskTypeCols"
                :key="col"
                class="hm-value-cell"
                :class="{ 'bt-best': llmBestByCol[col] === row.model_id }"
              >{{ row.quality_by_task_type[col] != null ? pct(row.quality_by_task_type[col]) : '—' }}</td>
              <td class="hm-value-cell llm-tps-cell">{{ row.avg_tokens_per_sec.toFixed(1) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="heatmap-hint">Run LLM Eval to refresh. Green = best per column.</p>
    </template>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { useApiFetch } from '../composables/useApi'

// ── Types ───────────────────────────────────────────────────────────────────
interface CfOrchTask {
  id: string
  name: string
  type: string
  prompt: string
  system: string
}

interface CfOrchModel {
  name: string
  id: string
  service: string
  tags: string[]
  vram_estimate_mb?: number
}

interface CfOrchNode {
  node_id: string
  online: boolean
  gpus: { gpu_id: number; name: string; vram_total_mb: number; vram_free_mb: number }[]
}

interface LlmModelResult {
  model_name: string
  model_id: string
  node_id: string
  avg_tokens_per_sec: number
  avg_completion_ms: number
  avg_quality_score: number
  avg_judge_score: number | null
  finetune_candidates: number
  error_count: number
  quality_by_task_type: Record<string, number>
  judge_score_by_task_type?: Record<string, number>
}

// ── State ───────────────────────────────────────────────────────────────────
const llmTasks        = ref<CfOrchTask[]>([])
const llmTasksLoading = ref(false)
const llmModels       = ref<CfOrchModel[]>([])
const llmModelsLoading = ref(false)

const selectedLlmTasks  = ref<Set<string>>(new Set())
const selectedLlmModels = ref<Set<string>>(new Set())

const llmRunning     = ref(false)
const llmRunLog      = ref<string[]>([])
const llmError       = ref('')
const llmResults     = ref<LlmModelResult[]>([])
const llmEventSource = ref<EventSource | null>(null)
const llmLogEl       = ref<HTMLElement | null>(null)
const llmJudgeUrl    = ref('')
const llmWorkers     = ref(1)
const llmNodes       = ref<CfOrchNode[]>([])
const enabledNodes   = ref<Set<string>>(new Set())

// ── Computed ────────────────────────────────────────────────────────────────
const llmTasksByType = computed((): Record<string, CfOrchTask[]> => {
  const groups: Record<string, CfOrchTask[]> = {}
  for (const t of llmTasks.value) {
    if (!groups[t.type]) groups[t.type] = []
    groups[t.type].push(t)
  }
  return groups
})

const llmModelsByService = computed((): Record<string, CfOrchModel[]> => {
  const groups: Record<string, CfOrchModel[]> = {}
  for (const m of llmModels.value) {
    if (!groups[m.service]) groups[m.service] = []
    groups[m.service].push(m)
  }
  return groups
})

const llmTaskBadge = computed(() => {
  const total = llmTasks.value.length
  if (total === 0) return 'No tasks available'
  const sel = selectedLlmTasks.value.size
  if (sel === total) return `All tasks (${total})`
  return `${sel} of ${total} tasks selected`
})

const llmModelBadge = computed(() => {
  const total = llmModels.value.length
  if (total === 0) return 'No models available'
  const sel = selectedLlmModels.value.size
  if (sel === total) return `All models (${total})`
  return `${sel} of ${total} selected`
})

const llmTaskTypeCols = computed(() => {
  const types = new Set<string>()
  for (const r of llmResults.value) {
    for (const k of Object.keys(r.quality_by_task_type ?? {})) types.add(k)
  }
  return [...types].sort()
})

const llmHasJudge = computed(() =>
  llmResults.value.some(r => r.avg_judge_score != null)
)

const enabledNodeIds = computed(() =>
  llmNodes.value.filter(n => n.online && enabledNodes.value.has(n.node_id)).map(n => n.node_id)
)

const llmBestByCol = computed((): Record<string, string> => {
  const best: Record<string, string> = {}
  if (llmResults.value.length === 0) return best

  let bestId = '', bestVal = -Infinity
  for (const r of llmResults.value) {
    if (r.avg_quality_score > bestVal) { bestVal = r.avg_quality_score; bestId = r.model_id }
  }
  best['overall'] = bestId

  if (llmHasJudge.value) {
    bestId = ''; bestVal = -Infinity
    for (const r of llmResults.value) {
      if (r.avg_judge_score != null && r.avg_judge_score > bestVal) {
        bestVal = r.avg_judge_score; bestId = r.model_id
      }
    }
    best['judge'] = bestId
  }

  for (const col of llmTaskTypeCols.value) {
    bestId = ''; bestVal = -Infinity
    for (const r of llmResults.value) {
      const v = r.quality_by_task_type?.[col]
      if (v != null && v > bestVal) { bestVal = v; bestId = r.model_id }
    }
    best[col] = bestId
  }
  return best
})

// ── Helpers ─────────────────────────────────────────────────────────────────
function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`
}

// Task picker helpers
function isTaskTypeAllSelected(tasks: CfOrchTask[]): boolean {
  return tasks.length > 0 && tasks.every(t => selectedLlmTasks.value.has(t.id))
}
function isTaskTypeIndeterminate(tasks: CfOrchTask[]): boolean {
  const some = tasks.some(t => selectedLlmTasks.value.has(t.id))
  return some && !isTaskTypeAllSelected(tasks)
}
function toggleLlmTask(id: string, checked: boolean) {
  const next = new Set(selectedLlmTasks.value)
  checked ? next.add(id) : next.delete(id)
  selectedLlmTasks.value = next
}
function toggleTaskType(tasks: CfOrchTask[], checked: boolean) {
  const next = new Set(selectedLlmTasks.value)
  for (const t of tasks) {
    checked ? next.add(t.id) : next.delete(t.id)
  }
  selectedLlmTasks.value = next
}

// Model picker helpers
function isServiceAllSelected(models: CfOrchModel[]): boolean {
  return models.length > 0 && models.every(m => selectedLlmModels.value.has(m.id))
}
function isServiceIndeterminate(models: CfOrchModel[]): boolean {
  const some = models.some(m => selectedLlmModels.value.has(m.id))
  return some && !isServiceAllSelected(models)
}
function toggleLlmModel(id: string, checked: boolean) {
  const next = new Set(selectedLlmModels.value)
  checked ? next.add(id) : next.delete(id)
  selectedLlmModels.value = next
}
function toggleService(models: CfOrchModel[], checked: boolean) {
  const next = new Set(selectedLlmModels.value)
  for (const m of models) {
    checked ? next.add(m.id) : next.delete(m.id)
  }
  selectedLlmModels.value = next
}
function selectAllTasks()  { selectedLlmTasks.value  = new Set(llmTasks.value.map(t => t.id)) }
function clearAllTasks()   { selectedLlmTasks.value  = new Set() }
function selectAllModels() { selectedLlmModels.value = new Set(llmModels.value.map(m => m.id)) }
function clearAllModels()  { selectedLlmModels.value = new Set() }
function toggleNode(id: string, checked: boolean) {
  const next = new Set(enabledNodes.value)
  checked ? next.add(id) : next.delete(id)
  enabledNodes.value = next
}

// ── Data loaders ─────────────────────────────────────────────────────────────
async function loadLlmTasks() {
  llmTasksLoading.value = true
  const { data } = await useApiFetch<{ tasks: CfOrchTask[]; types: string[] }>('/api/cforch/tasks')
  llmTasksLoading.value = false
  if (data?.tasks) {
    llmTasks.value = data.tasks
    selectedLlmTasks.value = new Set(data.tasks.map(t => t.id))
  }
}

async function loadLlmModels() {
  llmModelsLoading.value = true
  const { data } = await useApiFetch<{ models: CfOrchModel[] }>('/api/cforch/models')
  llmModelsLoading.value = false
  if (data?.models) {
    llmModels.value = data.models
    selectedLlmModels.value = new Set(data.models.map(m => m.id))
  }
}

async function loadLlmResults() {
  const { data } = await useApiFetch<LlmModelResult[]>('/api/cforch/results')
  if (Array.isArray(data) && data.length > 0) {
    llmResults.value = data
  }
}

async function loadLlmConfig() {
  const { data } = await useApiFetch<{ judge_url?: string }>('/api/cforch/config')
  if (data?.judge_url && !llmJudgeUrl.value) {
    llmJudgeUrl.value = data.judge_url
  }
}

async function loadLlmNodes() {
  const { data } = await useApiFetch<{ nodes: CfOrchNode[] }>('/api/cforch/nodes')
  if (data?.nodes) {
    llmNodes.value = data.nodes
    enabledNodes.value = new Set(data.nodes.filter(n => n.online).map(n => n.node_id))
  }
}

// ── Run / cancel ──────────────────────────────────────────────────────────────
function startLlmBenchmark() {
  llmRunning.value = true
  llmRunLog.value  = []
  llmError.value   = ''

  const params = new URLSearchParams()
  const taskIds = [...selectedLlmTasks.value].join(',')
  if (taskIds) params.set('task_ids', taskIds)
  const modelIds = [...selectedLlmModels.value].join(',')
  if (modelIds) params.set('model_ids', modelIds)
  if (llmJudgeUrl.value.trim()) params.set('judge_url', llmJudgeUrl.value.trim())
  if (llmWorkers.value > 1) params.set('workers', String(llmWorkers.value))
  const onlineNodeIds = llmNodes.value.filter(n => n.online).map(n => n.node_id)
  const isRestricted = enabledNodeIds.value.length < onlineNodeIds.length
  if (isRestricted && enabledNodeIds.value.length > 0) {
    params.set('node_ids', enabledNodeIds.value.join(','))
  }

  const es = new EventSource(`/api/cforch/run?${params}`)
  llmEventSource.value = es

  es.onmessage = async (e: MessageEvent) => {
    const msg = JSON.parse(e.data)
    if (msg.type === 'progress' && typeof msg.message === 'string') {
      llmRunLog.value.push(msg.message)
      await nextTick()
      llmLogEl.value?.scrollTo({ top: llmLogEl.value.scrollHeight, behavior: 'smooth' })
    } else if (msg.type === 'result' && Array.isArray(msg.summary)) {
      llmResults.value = msg.summary
    } else if (msg.type === 'complete') {
      llmRunning.value = false
      es.close()
      llmEventSource.value = null
    } else if (msg.type === 'error' && typeof msg.message === 'string') {
      llmError.value = msg.message
      llmRunning.value = false
      es.close()
      llmEventSource.value = null
    }
  }

  es.onerror = () => {
    if (llmRunning.value) llmError.value = 'Connection lost'
    llmRunning.value = false
    es.close()
    llmEventSource.value = null
  }
}

async function cancelLlmBenchmark() {
  llmEventSource.value?.close()
  llmEventSource.value = null
  llmRunning.value = false
  await fetch('/api/cforch/cancel', { method: 'POST' }).catch(() => {})
}

onMounted(() => {
  loadLlmTasks()
  loadLlmModels()
  loadLlmResults()
  loadLlmConfig()
  loadLlmNodes()
})
</script>

<style scoped>
.llm-eval-tab {
  display: flex;
  flex-direction: column;
  gap: 1.75rem;
}

/* ── Buttons ────────────────────────────────────────────── */
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

.btn-cancel {
  padding: 0.45rem 0.9rem;
  background: transparent;
  border: 1px solid var(--color-text-secondary, #6b7a99);
  color: var(--color-text-secondary, #6b7a99);
  border-radius: 0.4rem;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-cancel:hover {
  background: color-mix(in srgb, var(--color-text-secondary, #6b7a99) 12%, transparent);
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

/* ── Run controls row ───────────────────────────────────── */
.run-controls {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.run-hint {
  font-size: 0.8rem;
  color: var(--color-text-secondary, #6b7a99);
}

.judge-url-input {
  flex: 1;
  min-width: 14rem;
  max-width: 24rem;
  padding: 0.35rem 0.6rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.375rem;
  background: var(--color-surface, #fff);
  color: var(--color-text, #1a2338);
  font-size: 0.8rem;
  font-family: var(--font-mono, monospace);
}
.judge-url-input:disabled { opacity: 0.5; }
.judge-url-input::placeholder { color: var(--color-text-secondary, #6b7a99); }

.workers-label {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.8rem;
  color: var(--color-text-secondary, #6b7a99);
  white-space: nowrap;
}
.workers-prefix { font-family: var(--font-mono, monospace); }
.workers-input {
  width: 3.2rem;
  padding: 0.35rem 0.4rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.375rem;
  background: var(--color-surface, #fff);
  color: var(--color-text, #1a2338);
  font-size: 0.8rem;
  font-family: var(--font-mono, monospace);
  text-align: center;
}
.workers-input:disabled { opacity: 0.5; }

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

/* ── Chart title ────────────────────────────────────────── */
.chart-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--color-text, #1a2338);
  margin: 0;
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

.hm-value-cell {
  padding: 0.35rem 0.5rem;
  text-align: center;
  font-family: var(--font-mono, monospace);
  font-variant-numeric: tabular-nums;
  border-top: 1px solid var(--color-border, #d0d7e8);
  cursor: default;
}

.heatmap-hint {
  font-size: 0.75rem;
  color: var(--color-text-secondary, #6b7a99);
  margin: 0;
}

/* LLM-specific table styles */
.llm-results-table .bt-best {
  color: var(--color-success, #3a7a32);
  font-weight: 700;
  background: color-mix(in srgb, var(--color-success, #3a7a32) 8%, transparent);
}

.llm-model-name-cell {
  font-family: var(--font-mono, monospace);
  font-size: 0.75rem;
  white-space: nowrap;
  max-width: 16rem;
  overflow: hidden;
  text-overflow: ellipsis;
  background: var(--color-surface, #fff);
  border-top: 1px solid var(--color-border, #d0d7e8);
  padding: 0.35rem 0.6rem;
  position: sticky;
  left: 0;
}

.llm-tps-cell {
  font-family: var(--font-mono, monospace);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.hm-judge-col {
  background: color-mix(in srgb, var(--color-surface-raised, #e4ebf5) 80%, #c6d5f5);
}
.hm-judge-cell {
  background: color-mix(in srgb, var(--color-surface, #fff) 85%, #c6d5f5);
  font-style: italic;
  opacity: 0.9;
}

/* ── Model Picker ───────────────────────────────────────── */
.model-picker {
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  overflow: hidden;
}

.picker-summary {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.65rem 0.9rem;
  cursor: pointer;
  user-select: none;
  list-style: none;
  background: var(--color-surface-raised, #e4ebf5);
}
.picker-summary::-webkit-details-marker { display: none; }
.picker-summary::before { content: '▶  '; font-size: 0.65rem; color: var(--color-text-secondary, #6b7a99); }
details[open] .picker-summary::before { content: '▼  '; }

.picker-title {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--color-text, #1a2338);
}

.picker-badge {
  font-size: 0.75rem;
  color: var(--color-text-secondary, #6b7a99);
  background: var(--color-surface, #fff);
  border: 1px solid var(--color-border, #d0d7e8);
  padding: 0.15rem 0.5rem;
  border-radius: 1rem;
  font-family: var(--font-mono, monospace);
  margin-left: auto;
}

.picker-bulk-btn {
  padding: 0.1rem 0.45rem;
  font-size: 0.7rem;
  font-family: var(--font-mono, monospace);
  background: var(--color-surface, #fff);
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.25rem;
  color: var(--color-text-secondary, #6b7a99);
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
  flex-shrink: 0;
}
.picker-bulk-btn:hover {
  background: var(--app-primary, #2A6080);
  color: #fff;
  border-color: var(--app-primary, #2A6080);
}

.picker-body {
  padding: 0.75rem;
  border-top: 1px solid var(--color-border, #d0d7e8);
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.picker-loading, .picker-empty {
  font-size: 0.85rem;
  color: var(--color-text-secondary, #6b7a99);
  padding: 0.5rem 0;
}

.picker-category {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.picker-cat-header {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.82rem;
  font-weight: 700;
  color: var(--color-text, #1a2338);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  cursor: pointer;
}

.picker-cat-name { /* inherits from cat-header */ }

.picker-cat-count {
  font-weight: 400;
  color: var(--color-text-secondary, #6b7a99);
  font-family: var(--font-mono, monospace);
  font-size: 0.75rem;
  text-transform: none;
  letter-spacing: 0;
}

.picker-model-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.75rem;
  padding-left: 1.4rem;
}

.picker-model-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.82rem;
  cursor: pointer;
  color: var(--color-text, #1a2338);
}

.picker-model-name {
  font-family: var(--font-mono, monospace);
  font-size: 0.78rem;
  white-space: nowrap;
  max-width: 18ch;
  overflow: hidden;
  text-overflow: ellipsis;
}

.picker-adapter-type {
  font-size: 0.68rem;
  color: var(--color-text-secondary, #6b7a99);
  background: var(--color-surface-raised, #e4ebf5);
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.25rem;
  padding: 0.05rem 0.3rem;
  font-family: var(--font-mono, monospace);
}

@media (max-width: 600px) {
  .picker-model-list { padding-left: 0; }
  .picker-model-name { max-width: 14ch; }
}

/* ── Node picker ────────────────────────────────────── */
.node-picker {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  background: var(--color-surface-raised, #e4ebf5);
}

.node-picker-label {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--color-text-secondary, #6b7a99);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  white-space: nowrap;
}

.node-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.2rem 0.55rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 1rem;
  background: var(--color-surface, #fff);
  font-size: 0.78rem;
  font-family: var(--font-mono, monospace);
  color: var(--color-text, #1a2338);
  cursor: pointer;
  transition: background 0.12s, opacity 0.12s;
}
.node-chip--off {
  opacity: 0.45;
  background: transparent;
}
.node-chip--offline {
  opacity: 0.35;
  cursor: not-allowed;
  font-style: italic;
}
.node-chip-check { accent-color: var(--app-primary, #2A6080); }
.node-chip-status {
  font-size: 0.66rem;
  color: var(--color-text-secondary, #6b7a99);
}

.node-picker-hint {
  font-size: 0.72rem;
  color: var(--color-text-secondary, #6b7a99);
  font-family: var(--font-mono, monospace);
  margin-left: auto;
}
</style>
