<template>
  <div class="embed-compare-page">
    <!-- Step indicator (non-interactive) -->
    <ol class="step-indicator" aria-label="Setup progress">
      <li :class="{ complete: corpus.length > 0 }">Corpus</li>
      <li :class="{ complete: queries.length > 0 }">Queries</li>
      <li :class="{ complete: selectedModels.length > 0 }">Models</li>
      <li :class="{ complete: hasResults }">Run &amp; Rate</li>
    </ol>

    <!-- Persistent aria-live region — always in DOM, never v-if -->
    <div
      ref="liveRegion"
      class="sr-live"
      aria-live="polite"
      aria-atomic="true"
      v-text="liveMessage"
    />

    <!-- ① Corpus section -->
    <section class="card" aria-labelledby="corpus-heading">
      <h2 id="corpus-heading">① Corpus</h2>
      <div class="corpus-controls">
        <div class="field">
          <label for="corpus-paste">Paste chunks (one per line)</label>
          <textarea
            id="corpus-paste"
            v-model="rawCorpus"
            rows="6"
            placeholder="Paste one chunk per line, or use Import below..."
            @change="onCorpusPaste"
          />
        </div>
        <div class="import-row">
          <label for="imitate-product-select">Import from product</label>
          <select id="imitate-product-select" v-model="selectedProduct">
            <option value="">-- select product --</option>
            <option
              v-for="p in imitateProducts"
              :key="p.id"
              :value="p.id"
            >{{ p.name }}</option>
          </select>
          <button
            class="btn-secondary"
            :disabled="!selectedProduct || importing"
            @click="importCorpus"
          >
            {{ importing ? 'Importing…' : 'Import' }}
          </button>
          <span v-if="importError" class="error-text" role="alert">{{ importError }}</span>
        </div>
        <p v-if="corpus.length > 0" class="corpus-count">
          {{ corpus.length }} chunk{{ corpus.length === 1 ? '' : 's' }} loaded.
        </p>
      </div>
    </section>

    <!-- ② Queries section -->
    <section class="card" aria-labelledby="queries-heading">
      <h2 id="queries-heading">② Queries</h2>
      <div class="field">
        <label for="query-input">Enter queries (one per line)</label>
        <textarea
          id="query-input"
          v-model="rawQueries"
          rows="4"
          placeholder="One query per line..."
          @change="onQueriesChange"
        />
      </div>
      <p v-if="queries.length > 0" class="query-count">
        {{ queries.length }} quer{{ queries.length === 1 ? 'y' : 'ies' }}.
      </p>
    </section>

    <!-- ③ Model selection -->
    <section class="card" aria-labelledby="models-heading">
      <h2 id="models-heading">③ Models</h2>
      <p v-if="loadingModels" class="muted">Loading models from Ollama…</p>
      <p v-else-if="modelsError" class="error-text" role="alert">{{ modelsError }}</p>
      <ul v-else class="model-list" role="list">
        <li v-for="m in availableModels" :key="m.name">
          <label class="model-checkbox">
            <input
              type="checkbox"
              :value="m.name"
              v-model="selectedModels"
            />
            {{ m.name }}
            <span class="model-size muted" aria-label="model size">
              {{ formatBytes(m.size) }}
            </span>
          </label>
        </li>
      </ul>
      <p v-if="availableModels.length === 0 && !loadingModels && !modelsError" class="muted">
        No Ollama models found. Pull an embedding model first.
      </p>
    </section>

    <!-- ④ Run controls -->
    <section class="card run-controls" aria-labelledby="run-heading">
      <h2 id="run-heading">④ Run</h2>
      <div class="run-row">
        <div class="field-inline">
          <label for="top-k-input">Results per query</label>
          <input
            id="top-k-input"
            type="number"
            v-model.number="topK"
            min="1"
            max="20"
            style="width: 5rem"
          />
        </div>
        <button
          class="btn-primary"
          :disabled="!canRun || running"
          @click="startRun"
        >
          {{ running ? 'Running…' : 'Run' }}
        </button>
        <button
          v-if="running"
          class="btn-danger"
          aria-label="Cancel embedding run"
          @click="cancelRun"
        >
          Cancel
        </button>
      </div>
      <p v-if="!canRun && !running" class="muted">
        Fill corpus, at least one query, and select at least one model to run.
      </p>
    </section>

    <!-- Results (Task 8) -->
    <section
      v-if="hasResults"
      class="card results-section"
      aria-labelledby="results-heading"
    >
      <h2 id="results-heading">Results</h2>
      <!-- Populated in Task 8 -->
      <p class="muted">{{ resultEvents.length }} result events received.</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

// ── Types ─────────────────────────────────────────────────────────────────────

interface OllamaModel { name: string; size: number }
interface ImitateProduct { id: string; name: string }
interface HitResult { chunk_idx: number; text: string; score: number }
interface ResultEvent {
  type: 'result'
  query_idx: number
  query: string
  model: string
  hits: HitResult[]
}

// ── State ─────────────────────────────────────────────────────────────────────

const rawCorpus       = ref('')
const corpus          = ref<string[]>([])
const rawQueries      = ref('')
const queries         = ref<string[]>([])
const selectedModels  = ref<string[]>([])
const topK            = ref(5)
const availableModels = ref<OllamaModel[]>([])
const loadingModels   = ref(false)
const modelsError     = ref('')
const imitateProducts = ref<ImitateProduct[]>([])
const selectedProduct = ref('')
const importing       = ref(false)
const importError     = ref('')
const running         = ref(false)
const liveMessage     = ref('')
const resultEvents    = ref<ResultEvent[]>([])
const runController   = ref<AbortController | null>(null)

const hasResults = computed(() => resultEvents.value.length > 0)
const canRun = computed(
  () => corpus.value.length > 0 && queries.value.length > 0 && selectedModels.value.length > 0
)

// ── Corpus helpers ────────────────────────────────────────────────────────────

function onCorpusPaste() {
  const chunks = rawCorpus.value.split('\n').map(l => l.trim()).filter(Boolean)
  corpus.value = chunks
  if (chunks.length > 0) {
    liveMessage.value = `${chunks.length} chunk${chunks.length === 1 ? '' : 's'} loaded.`
  }
}

function onQueriesChange() {
  queries.value = rawQueries.value.split('\n').map(l => l.trim()).filter(Boolean)
}

async function importCorpus() {
  if (!selectedProduct.value) return
  importing.value = true
  importError.value = ''
  try {
    const r = await fetch(`/api/imitate/products/${selectedProduct.value}/sample-chunks`)
    if (!r.ok) {
      const text = await r.text()
      throw new Error(text || `HTTP ${r.status}`)
    }
    const data = await r.json() as { chunks?: string[] }
    const chunks = data.chunks ?? []
    corpus.value = chunks
    rawCorpus.value = chunks.join('\n')
    liveMessage.value = `${chunks.length} chunk${chunks.length === 1 ? '' : 's'} loaded from import.`
  } catch (err) {
    importError.value = String(err)
  } finally {
    importing.value = false
  }
}

// ── Model loading ─────────────────────────────────────────────────────────────

async function loadModels() {
  loadingModels.value = true
  modelsError.value = ''
  try {
    const r = await fetch('/api/embed-bench/models')
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const data = await r.json() as { models: OllamaModel[] }
    availableModels.value = data.models
  } catch (err) {
    modelsError.value = `Failed to load models: ${err}`
  } finally {
    loadingModels.value = false
  }
}

// ── Run ───────────────────────────────────────────────────────────────────────

async function startRun() {
  if (!canRun.value) return
  running.value = true
  resultEvents.value = []
  liveMessage.value = 'Starting embedding run…'
  runController.value = new AbortController()

  try {
    const resp = await fetch('/api/embed-bench/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        corpus: corpus.value,
        queries: queries.value,
        models: selectedModels.value,
        top_k: topK.value,
      }),
      signal: runController.value.signal,
    })

    const reader = resp.body!.getReader()
    const decoder = new TextDecoder()
    let buf = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() ?? ''
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const event = JSON.parse(line.slice(6))
        if (event.type === 'progress') {
          liveMessage.value = event.msg
        } else if (event.type === 'result') {
          resultEvents.value.push(event as ResultEvent)
        } else if (event.type === 'done') {
          liveMessage.value = 'Run complete.'
        } else if (event.type === 'error') {
          liveMessage.value = `Error: ${event.msg}`
        }
      }
    }
  } catch (err) {
    if ((err as Error).name !== 'AbortError') {
      liveMessage.value = `Run failed: ${err}`
    }
  } finally {
    running.value = false
    runController.value = null
  }
}

function cancelRun() {
  runController.value?.abort()
  liveMessage.value = 'Run cancelled.'
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (bytes < 1_000_000) return `${(bytes / 1000).toFixed(0)} KB`
  if (bytes < 1_000_000_000) return `${(bytes / 1_000_000).toFixed(0)} MB`
  return `${(bytes / 1_000_000_000).toFixed(1)} GB`
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────

onMounted(() => {
  loadModels()
})
</script>

<style scoped>
.embed-compare-page {
  padding: var(--space-4, 1.5rem);
  max-width: 1100px;
}

/* Step indicator */
.step-indicator {
  display: flex;
  gap: 0;
  list-style: none;
  margin: 0 0 var(--space-4, 1.5rem);
  padding: 0;
  border-bottom: 2px solid var(--color-border, #d0d7e8);
}
.step-indicator li {
  padding: 0.4rem 1rem;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-text-muted, #4a5c7a);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
}
.step-indicator li.complete {
  color: var(--app-primary, #2A6080);
  border-bottom-color: var(--app-primary, #2A6080);
}

/* Accessibility: screen-reader live region — visually hidden but always present */
.sr-live {
  position: absolute;
  width: 1px; height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

/* Cards */
.card {
  background: var(--color-surface-raised, #e4ebf5);
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: var(--radius-md, 0.5rem);
  padding: var(--space-4, 1.5rem);
  margin-bottom: var(--space-4, 1.5rem);
}
.card h2 {
  font-size: 1rem;
  font-weight: 700;
  margin: 0 0 var(--space-3, 1rem);
  color: var(--color-text, #1a2338);
}

.field { display: flex; flex-direction: column; gap: 0.3rem; margin-bottom: 0.75rem; }
.field label { font-size: 0.85rem; font-weight: 600; }
textarea, input[type="number"] {
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: var(--radius-sm, 0.25rem);
  padding: 0.5rem;
  font-size: 0.875rem;
  background: var(--color-surface, #f0f4fb);
  color: var(--color-text, #1a2338);
  resize: vertical;
}

.corpus-controls { display: flex; flex-direction: column; gap: 0.5rem; }
.import-row {
  display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center;
}
.import-row label { font-size: 0.85rem; font-weight: 600; }
.corpus-count, .query-count { font-size: 0.875rem; color: var(--app-primary, #2A6080); margin: 0; }

.model-list { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 0.5rem; }
.model-checkbox {
  display: flex; align-items: center; gap: 0.4rem;
  font-size: 0.875rem; cursor: pointer;
  padding: 0.3rem 0.6rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: var(--radius-sm, 0.25rem);
  background: var(--color-surface, #f0f4fb);
}
.model-size { font-size: 0.75rem; }

.run-row { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: flex-end; }
.field-inline { display: flex; align-items: center; gap: 0.4rem; }
.field-inline label { font-size: 0.85rem; font-weight: 600; white-space: nowrap; }

.btn-primary, .btn-secondary, .btn-danger {
  padding: 0.4rem 1rem;
  border-radius: var(--radius-sm, 0.25rem);
  border: 1px solid transparent;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-primary { background: var(--app-primary, #2A6080); color: #fff; }
.btn-primary:hover:not(:disabled) { filter: brightness(1.1); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { background: var(--color-surface, #f0f4fb); color: var(--color-text, #1a2338); border-color: var(--color-border, #d0d7e8); }
.btn-secondary:hover:not(:disabled) { background: var(--color-border, #d0d7e8); }
.btn-secondary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-danger { background: var(--color-error, #c0392b); color: #fff; }

.muted { color: var(--color-text-muted, #4a5c7a); font-size: 0.875rem; }
.error-text { color: var(--color-error, #c0392b); font-size: 0.875rem; }

@media (max-width: 768px) {
  .import-row { flex-direction: column; align-items: flex-start; }
  .run-row { flex-direction: column; }
  .model-list { flex-direction: column; }
}
</style>
