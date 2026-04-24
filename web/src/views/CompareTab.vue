<template>
  <div class="compare-tab">

    <!-- Source toggle -->
    <div class="source-toggle" role="group" aria-label="Prompt source">
      <button class="source-btn" :class="{ active: promptSource === 'tasks' }" @click="promptSource = 'tasks'">
        📋 cf-orch Tasks
      </button>
      <button class="source-btn" :class="{ active: promptSource === 'style' }" @click="promptSource = 'style'">
        ✍️ Writing Style Prompts
      </button>
    </div>

    <!-- Task selector (cf-orch tasks) -->
    <details v-if="promptSource === 'tasks'" class="model-picker" open>
      <summary class="picker-summary">
        <span class="picker-title">📋 Pick a Task</span>
        <span class="picker-badge">{{ cmpSelectedTask ? cmpSelectedTask.name : 'None selected' }}</span>
      </summary>
      <div class="picker-body">
        <div v-if="llmTasksLoading" class="picker-loading">Loading tasks…</div>
        <div v-else-if="llmTasks.length === 0" class="picker-empty">No tasks found — check cforch config.</div>
        <template v-else>
          <div v-for="(tasks, type) in llmTasksByType" :key="type" class="picker-category">
            <span class="picker-cat-name picker-cat-section">{{ type }}</span>
            <div class="picker-model-list">
              <label v-for="t in tasks" :key="t.id" class="picker-model-row">
                <input
                  type="radio"
                  name="cmp-task"
                  :checked="cmpSelectedTask?.id === t.id"
                  @change="selectCmpTask(t)"
                />
                <span class="picker-model-name" :title="t.name">{{ t.name }}</span>
              </label>
            </div>
          </div>
        </template>
      </div>
    </details>

    <!-- Writing style prompt selector -->
    <details v-if="promptSource === 'style'" class="model-picker" open>
      <summary class="picker-summary">
        <span class="picker-title">✍️ Pick a Writing Style Prompt</span>
        <span class="picker-badge">{{ selectedVoicePrompt ? selectedVoicePrompt.tag : 'None selected' }}</span>
      </summary>
      <div class="picker-body">
        <div class="picker-model-list style-prompt-list">
          <label v-for="vp in STYLE_PROMPTS" :key="vp.tag" class="picker-model-row style-prompt-row">
            <input
              type="radio"
              name="cmp-style-prompt"
              :checked="selectedVoicePrompt?.tag === vp.tag"
              @change="selectVoicePrompt(vp)"
            />
            <span class="style-prompt-tag">{{ vp.tag }}</span>
            <span class="style-prompt-title">{{ vp.thread_title }}</span>
          </label>
        </div>
      </div>
    </details>

    <!-- Prompt editor + model picker (shown once a prompt source is ready) -->
    <template v-if="promptSource === 'tasks' ? !!cmpSelectedTask : !!selectedVoicePrompt">
      <label class="prompt-label" for="cmp-prompt">Prompt</label>
      <textarea
        id="cmp-prompt"
        class="cmp-prompt-editor"
        v-model="cmpPrompt"
        rows="6"
      />

      <!-- Ollama model picker -->
      <details class="model-picker" open>
        <summary class="picker-summary">
          <span class="picker-title">🤖 Ollama Models</span>
          <span class="picker-badge">{{ cmpSelectedModels.size }} / {{ ollamaLlmModels.length }}</span>
        </summary>
        <div class="picker-body">
          <label class="picker-cat-header">
            <input
              type="checkbox"
              :checked="cmpSelectedModels.size === ollamaLlmModels.length"
              :indeterminate="cmpSelectedModels.size > 0 && cmpSelectedModels.size < ollamaLlmModels.length"
              @change="toggleAllCmpModels(($event.target as HTMLInputElement).checked)"
            />
            <span class="picker-cat-name">All ollama models</span>
          </label>
          <div class="picker-model-list">
            <label v-for="m in ollamaLlmModels" :key="m.id" class="picker-model-row">
              <input
                type="checkbox"
                :checked="cmpSelectedModels.has(m.id)"
                @change="toggleCmpModel(m.id, ($event.target as HTMLInputElement).checked)"
              />
              <span class="picker-model-name">{{ m.name }}</span>
              <span class="picker-adapter-type">{{ m.tags.slice(0, 3).join(', ') }}</span>
            </label>
          </div>
        </div>
      </details>

      <!-- Run controls -->
      <div class="run-controls">
        <button
          class="btn-run"
          :disabled="cmpRunning || cmpSelectedModels.size === 0"
          @click="startCompare"
        >{{ cmpRunning ? '⏳ Running…' : '⚖️ Compare Models' }}</button>
        <button v-if="cmpRunning" class="btn-cancel" @click="cancelCompare">✕ Cancel</button>
      </div>

      <!-- Progress log -->
      <div v-if="cmpLog.length > 0" class="run-log">
        <div class="log-lines">
          <div v-for="(line, i) in cmpLog" :key="i" class="log-line">{{ line }}</div>
        </div>
      </div>

      <!-- Side-by-side results -->
      <template v-if="cmpResults.length > 0">
        <h2 class="chart-title">Side-by-Side Responses</h2>
        <div class="cmp-results-grid">
          <div
            v-for="r in cmpResults"
            :key="r.model"
            class="cmp-result-card"
            :class="{ 'cmp-error': !!r.error }"
          >
            <div class="cmp-result-header">
              <span class="cmp-model-name">{{ r.model }}</span>
              <span class="cmp-meta">
                <template v-if="r.error"><span class="err-badge">error</span></template>
                <template v-else>{{ (r.elapsed_ms / 1000).toFixed(1) }}s</template>
              </span>
            </div>
            <pre v-if="r.error" class="cmp-error-text">{{ r.error }}</pre>
            <pre v-else class="cmp-response">{{ r.response }}</pre>
          </div>
        </div>
      </template>
    </template>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
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

interface CmpResult {
  model: string
  response: string
  elapsed_ms: number
  error: string | null
}

interface VoicePrompt {
  tag: string
  thread_title: string
  thread_body: string
}

// ── Writing style prompts (mirrors TEST_PROMPTS in benchmark_style.py) ──────
const STYLE_SYSTEM = "You are a writing assistant. Your job is to write a Reddit reply that matches the user's voice — casual, direct, community-first. No em dashes. No filler phrases. No semicolons. Short punchy sentences."

const STYLE_PROMPTS: VoicePrompt[] = [
  {
    tag: 'selfhosted_ai_fatigue',
    thread_title: "Anyone else getting tired of re-explaining their setup every time an AI model forgets?",
    thread_body: "Every session I start over. My whole hardware setup, what tools I use, what I've already tried. It's exhausting. There has to be a better way.",
  },
  {
    tag: 'privacy_local_llm',
    thread_title: "What's the point of running local LLMs if the apps still phone home?",
    thread_body: "I went through all the trouble of setting up ollama and now I find out the frontend I'm using is sending telemetry. Kind of defeats the purpose.",
  },
  {
    tag: 'solarpunk_tech',
    thread_title: "What does solarpunk computing actually look like in practice?",
    thread_body: "I keep seeing the aesthetic but not a lot of concrete examples of people living it out with their tech choices. What does it mean day to day?",
  },
  {
    tag: 'nd_tools',
    thread_title: "Tools that actually help with executive function vs ones that just add friction",
    thread_body: "I've tried a dozen productivity apps and most of them require more executive function to maintain than they save. What actually sticks for you?",
  },
  {
    tag: 'data_ownership',
    thread_title: "Who actually owns your data when you use a 'free' AI tool?",
    thread_body: "Read the ToS on three different AI assistants today. In all three cases your inputs can be used for training, shared with partners, and retained indefinitely. Is this just accepted now?",
  },
  {
    tag: 'digital_culture',
    thread_title: "The internet used to feel like it belonged to everyone. What happened?",
    thread_body: "I grew up on forums, IRC, personal homepages. Now everything is a platform owned by someone trying to extract value from the community that built it.",
  },
]

// ── State ───────────────────────────────────────────────────────────────────
const llmTasks        = ref<CfOrchTask[]>([])
const llmTasksLoading = ref(false)
const llmModels       = ref<CfOrchModel[]>([])

const promptSource        = ref<'tasks' | 'style'>('tasks')
const cmpSelectedTask     = ref<CfOrchTask | null>(null)
const selectedVoicePrompt = ref<VoicePrompt | null>(null)
const cmpSystemPrompt     = ref('')
const cmpPrompt           = ref('')
const cmpSelectedModels   = ref<Set<string>>(new Set())
const cmpRunning          = ref(false)
const cmpLog              = ref<string[]>([])
const cmpResults          = ref<CmpResult[]>([])
const cmpEventSource      = ref<EventSource | null>(null)

// ── Computed ────────────────────────────────────────────────────────────────
const ollamaLlmModels = computed(() =>
  llmModels.value.filter(m => m.service === 'ollama')
)

const llmTasksByType = computed((): Record<string, CfOrchTask[]> => {
  const groups: Record<string, CfOrchTask[]> = {}
  for (const t of llmTasks.value) {
    if (!groups[t.type]) groups[t.type] = []
    groups[t.type].push(t)
  }
  return groups
})

// ── Helpers ─────────────────────────────────────────────────────────────────
function selectCmpTask(t: CfOrchTask) {
  cmpSelectedTask.value = t
  cmpPrompt.value = t.prompt || ''
  cmpSystemPrompt.value = t.system || ''
  cmpResults.value = []
  cmpLog.value = []
}

function selectVoicePrompt(vp: VoicePrompt) {
  selectedVoicePrompt.value = vp
  cmpPrompt.value = `Thread: ${vp.thread_title}\n\n${vp.thread_body}\n\nWrite a reply:`
  cmpSystemPrompt.value = STYLE_SYSTEM
  cmpResults.value = []
  cmpLog.value = []
}

function toggleCmpModel(id: string, checked: boolean) {
  const next = new Set(cmpSelectedModels.value)
  checked ? next.add(id) : next.delete(id)
  cmpSelectedModels.value = next
}

function toggleAllCmpModels(checked: boolean) {
  cmpSelectedModels.value = checked
    ? new Set(ollamaLlmModels.value.map(m => m.id))
    : new Set()
}

// ── Data loaders ──────────────────────────────────────────────────────────────
async function loadLlmTasks() {
  llmTasksLoading.value = true
  const { data } = await useApiFetch<{ tasks: CfOrchTask[]; types: string[] }>('/api/cforch/tasks')
  llmTasksLoading.value = false
  if (data?.tasks) {
    llmTasks.value = data.tasks
  }
}

async function loadLlmModels() {
  const { data } = await useApiFetch<{ models: CfOrchModel[] }>('/api/cforch/models')
  if (data?.models) {
    llmModels.value = data.models
    // Pre-select all ollama models
    cmpSelectedModels.value = new Set(
      data.models.filter(m => m.service === 'ollama').map(m => m.id)
    )
  }
}

// ── Run / cancel ──────────────────────────────────────────────────────────────
function startCompare() {
  if (!cmpPrompt.value.trim() || cmpSelectedModels.value.size === 0) return
  cmpRunning.value = true
  cmpResults.value = []
  cmpLog.value = []

  const params = new URLSearchParams({
    prompt:    cmpPrompt.value,
    model_ids: [...cmpSelectedModels.value].join(','),
    system:    cmpSystemPrompt.value,
  })

  const es = new EventSource(`/api/imitate/run?${params}`)
  cmpEventSource.value = es

  es.onmessage = (event: MessageEvent) => {
    try {
      const msg = JSON.parse(event.data)
      if (msg.type === 'start') {
        cmpLog.value.push(`Comparing ${msg.total_models} models…`)
      } else if (msg.type === 'model_start') {
        cmpLog.value.push(`→ ${msg.model}…`)
      } else if (msg.type === 'model_done') {
        const status = msg.error
          ? `✕ ${msg.error}`
          : `✓ ${(msg.elapsed_ms / 1000).toFixed(1)}s`
        cmpLog.value.push(`  ${msg.model}: ${status}`)
        cmpResults.value.push({
          model:      msg.model,
          response:   msg.response,
          elapsed_ms: msg.elapsed_ms,
          error:      msg.error ?? null,
        })
      } else if (msg.type === 'complete') {
        cmpRunning.value = false
        es.close()
      }
    } catch { /* ignore malformed frames */ }
  }

  es.onerror = () => {
    cmpLog.value.push('Connection error.')
    cmpRunning.value = false
    es.close()
    cmpEventSource.value = null
  }
}

function cancelCompare() {
  cmpEventSource.value?.close()
  cmpEventSource.value = null
  cmpRunning.value = false
  cmpLog.value.push('Cancelled.')
}

onMounted(() => {
  loadLlmTasks()
  loadLlmModels()
})
</script>

<style scoped>
.compare-tab {
  display: flex;
  flex-direction: column;
  gap: 1.75rem;
}

/* ── Source toggle ──────────────────────────────────────── */
.source-toggle {
  display: inline-flex;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  overflow: hidden;
  align-self: flex-start;
}

.source-btn {
  padding: 0.4rem 1rem;
  font-size: 0.83rem;
  font-family: var(--font-body, sans-serif);
  font-weight: 500;
  border: none;
  background: var(--color-surface, #fff);
  color: var(--color-text-secondary, #6b7a99);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.source-btn:not(:last-child) { border-right: 1px solid var(--color-border, #d0d7e8); }
.source-btn.active { background: var(--app-primary, #2A6080); color: #fff; }
.source-btn:not(.active):hover { background: var(--color-surface-raised, #e4ebf5); }

/* ── Voice prompt list ──────────────────────────────────── */
.style-prompt-list { flex-direction: column !important; flex-wrap: nowrap !important; padding-left: 0 !important; gap: 0.4rem !important; }

.style-prompt-row {
  flex-direction: column !important;
  align-items: flex-start !important;
  gap: 0.15rem !important;
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.35rem;
  background: var(--color-surface, #f4f7fc);
  cursor: pointer;
  transition: background 0.1s;
}
.style-prompt-row:hover { background: var(--color-surface-raised, #e4ebf5); }
.style-prompt-row:has(input:checked) {
  background: color-mix(in srgb, var(--app-primary, #2A6080) 10%, transparent);
  border-color: var(--app-primary, #2A6080);
}
.style-prompt-row input { display: none; }

.style-prompt-tag {
  font-family: var(--font-mono, monospace);
  font-size: 0.72rem;
  color: var(--app-primary, #2A6080);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.style-prompt-title {
  font-size: 0.83rem;
  color: var(--color-text, #1a2338);
  line-height: 1.4;
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

/* ── Run controls row ───────────────────────────────────── */
.run-controls {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

/* ── Run log ────────────────────────────────────────────── */
.run-log {
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  overflow: hidden;
  font-family: var(--font-mono, monospace);
  font-size: 0.78rem;
}

.log-lines {
  max-height: 160px;
  overflow-y: auto;
  padding: 0.5rem 0.75rem;
  background: var(--color-surface, #fff);
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.log-line { color: var(--color-text, #1a2338); line-height: 1.5; }

/* ── Chart title ────────────────────────────────────────── */
.chart-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--color-text, #1a2338);
  margin: 0;
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

.picker-cat-name { /* inherits from cat-header or section */ }

.picker-cat-section {
  font-weight: 600;
  font-size: 0.82rem;
  padding: 0.35rem 0;
  display: block;
  color: var(--color-text, #1a2338);
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

/* ── Prompt editor ──────────────────────────────────────── */
.prompt-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--color-text-secondary, #6b7a99);
  margin-top: 0.5rem;
}

.cmp-prompt-editor {
  width: 100%;
  font-family: var(--font-mono, monospace);
  font-size: 0.85rem;
  padding: 0.75rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.375rem;
  background: var(--color-surface, #f0f4fc);
  color: var(--color-text, #1a2338);
  resize: vertical;
  line-height: 1.5;
  box-sizing: border-box;
}
.cmp-prompt-editor:focus {
  outline: 2px solid var(--app-primary, #2A6080);
  outline-offset: -1px;
}

/* ── Results grid ───────────────────────────────────────── */
.cmp-results-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 1rem;
  margin-top: 0.5rem;
}

.cmp-result-card {
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  overflow: hidden;
  background: var(--color-surface, #f0f4fc);
  display: flex;
  flex-direction: column;
}

.cmp-result-card.cmp-error {
  border-color: #fca5a5;
}

.cmp-result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5rem 0.75rem;
  background: var(--color-surface-raised, #e4ebf5);
  border-bottom: 1px solid var(--color-border, #d0d7e8);
}

.cmp-model-name {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--color-text, #1a2338);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cmp-meta {
  font-size: 0.75rem;
  color: var(--color-text-secondary, #6b7a99);
  flex-shrink: 0;
  margin-left: 0.5rem;
}

.err-badge {
  background: #fee2e2;
  color: #991b1b;
  border-radius: 9999px;
  padding: 0.1rem 0.45rem;
  font-size: 0.7rem;
  font-weight: 600;
}

.cmp-response, .cmp-error-text {
  padding: 0.75rem;
  font-size: 0.82rem;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 300px;
  overflow-y: auto;
  margin: 0;
  flex: 1;
  color: var(--color-text, #1a2338);
}

.cmp-error-text { color: #b91c1c; }

@media (max-width: 600px) {
  .picker-model-list { padding-left: 0; }
  .picker-model-name { max-width: 14ch; }
}
</style>
