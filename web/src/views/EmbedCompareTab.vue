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

    <!-- Results -->
    <section
      v-if="hasResults"
      class="card results-section"
      aria-labelledby="results-heading"
    >
      <h2 id="results-heading">Results</h2>

      <!-- Query pagination -->
      <div class="query-nav" role="navigation" aria-label="Query navigation">
        <button
          class="btn-secondary"
          aria-label="Previous query"
          :disabled="currentQueryIdx === 0"
          @click="currentQueryIdx--"
        >‹</button>
        <span class="query-counter">
          Query {{ currentQueryIdx + 1 }} of {{ uniqueQueries.length }}:
          <em>{{ uniqueQueries[currentQueryIdx] }}</em>
        </span>
        <button
          class="btn-secondary"
          aria-label="Next query"
          :disabled="currentQueryIdx >= uniqueQueries.length - 1"
          @click="currentQueryIdx++"
        >›</button>
      </div>

      <!-- Results table: one column per model -->
      <div class="table-wrap">
        <table class="results-table">
          <thead>
            <tr>
              <th scope="col" class="rank-col">#</th>
              <th
                v-for="model in selectedModels"
                :key="model"
                scope="col"
              >{{ model }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="rank in topK" :key="rank">
              <td class="rank-col muted">{{ rank }}</td>
              <td
                v-for="model in selectedModels"
                :key="model"
                class="hit-cell"
              >
                <template v-if="getHit(currentQueryIdx, model, rank - 1) as hit">
                  <div class="hit-text">{{ hit.text }}</div>
                  <!-- Visual score bar: decorative only -->
                  <div class="score-row">
                    <div class="score-bar-wrap" aria-hidden="true">
                      <div class="score-bar" :style="{ width: `${hit.score * 100}%` }" />
                    </div>
                    <span class="score-label">{{ hit.score.toFixed(3) }}</span>
                  </div>
                  <!-- Rating buttons -->
                  <div class="rating-row">
                    <button
                      class="rate-btn"
                      :class="{ active: getRating(currentQueryIdx, model, hit.chunk_idx) === 'relevant' }"
                      :aria-pressed="getRating(currentQueryIdx, model, hit.chunk_idx) === 'relevant'"
                      aria-label="Mark as relevant"
                      @click="rate(currentQueryIdx, model, hit, 'relevant')"
                    >
                      👍 Relevant
                    </button>
                    <button
                      class="rate-btn rate-btn-neg"
                      :class="{ active: getRating(currentQueryIdx, model, hit.chunk_idx) === 'not_relevant' }"
                      :aria-pressed="getRating(currentQueryIdx, model, hit.chunk_idx) === 'not_relevant'"
                      aria-label="Mark as not relevant"
                      @click="rate(currentQueryIdx, model, hit, 'not_relevant')"
                    >
                      👎 Not relevant
                    </button>
                  </div>
                </template>
                <span v-else class="muted">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- Export -->
    <section
      v-if="hasResults"
      class="card export-section"
      aria-labelledby="export-heading"
    >
      <h2 id="export-heading">Export Ratings</h2>
      <div class="export-row">
        <fieldset class="export-format-group">
          <legend>Format</legend>
          <label><input type="radio" v-model="exportFormat" value="csv" /> CSV</label>
          <label><input type="radio" v-model="exportFormat" value="json" /> JSON</label>
        </fieldset>
        <button class="btn-secondary" @click="exportRatings">Export</button>
      </div>
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

const currentQueryIdx  = ref(0)
const exportFormat     = ref<'csv' | 'json'>('csv')

type RatingMap = Record<string, Record<string, Record<number, 'relevant' | 'not_relevant'>>>
const ratings = ref<RatingMap>({})

const uniqueQueries = computed(() => {
  const seen = new Set<string>()
  const out: string[] = []
  for (const e of resultEvents.value) {
    if (!seen.has(e.query)) { seen.add(e.query); out.push(e.query) }
  }
  return out
})

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

function getHit(queryIdx: number, model: string, rank: number): HitResult | null {
  const query = uniqueQueries.value[queryIdx]
  if (!query) return null
  const ev = resultEvents.value.find(e => e.query === query && e.model === model)
  return ev?.hits[rank] ?? null
}

function getRating(queryIdx: number, model: string, chunkIdx: number): string | undefined {
  const query = uniqueQueries.value[queryIdx]
  return ratings.value[query]?.[model]?.[chunkIdx]
}

async function rate(
  queryIdx: number,
  model: string,
  hit: HitResult,
  rating: 'relevant' | 'not_relevant',
) {
  const query = uniqueQueries.value[queryIdx]
  // Optimistic update
  if (!ratings.value[query]) ratings.value[query] = {}
  if (!ratings.value[query][model]) ratings.value[query][model] = {}
  ratings.value[query][model][hit.chunk_idx] = rating

  try {
    await fetch('/api/embed-bench/rate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        model,
        chunk_text: hit.text,
        chunk_idx: hit.chunk_idx,
        rating,
      }),
    })
    liveMessage.value = `Rated chunk ${hit.chunk_idx + 1} as ${rating}.`
  } catch (err) {
    liveMessage.value = `Rating failed: ${err}`
  }
}

async function exportRatings() {
  const r = await fetch(`/api/embed-bench/export?format=${exportFormat.value}`)
  if (!r.ok) {
    liveMessage.value = `Export failed: HTTP ${r.status}`
    return
  }
  const blob = await r.blob()
  const disposition = r.headers.get('Content-Disposition') ?? ''
  const filenameMatch = disposition.match(/filename="([^"]+)"/)
  const filename = filenameMatch ? filenameMatch[1] : `embed_comparison.${exportFormat.value}`
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
  liveMessage.value = `Exported ${filename}.`
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

/* Results table */
.table-wrap { overflow-x: auto; }
.results-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}
.results-table thead th {
  position: sticky;
  top: 0;
  background: var(--color-surface-raised, #e4ebf5);
  border-bottom: 2px solid var(--color-border, #d0d7e8);
  padding: 0.5rem 0.75rem;
  text-align: left;
  font-weight: 700;
  white-space: nowrap;
  z-index: 1;
}
.results-table td {
  padding: 0.5rem 0.75rem;
  vertical-align: top;
  border-bottom: 1px solid var(--color-border, #d0d7e8);
}
.rank-col { width: 2rem; text-align: center; }

.hit-text { margin-bottom: 0.25rem; line-height: 1.4; }

.score-row { display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.25rem; }
.score-bar-wrap {
  flex: 1;
  height: 6px;
  background: var(--color-border, #d0d7e8);
  border-radius: 3px;
  overflow: hidden;
}
.score-bar {
  height: 100%;
  background: var(--app-primary, #2A6080);
  border-radius: 3px;
  transition: width 0.3s ease;
}
.score-label { font-size: 0.75rem; color: var(--color-text-muted, #4a5c7a); min-width: 3rem; text-align: right; }

.rating-row { display: flex; gap: 0.4rem; flex-wrap: wrap; }
.rate-btn {
  padding: 0.2rem 0.5rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: var(--radius-sm, 0.25rem);
  background: var(--color-surface, #f0f4fb);
  color: var(--color-text, #1a2338);
  font-size: 0.75rem;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.rate-btn.active {
  background: color-mix(in srgb, var(--app-primary, #2A6080) 20%, transparent);
  border-color: var(--app-primary, #2A6080);
  font-weight: 700;
}
.rate-btn-neg.active {
  background: color-mix(in srgb, var(--color-error, #c0392b) 15%, transparent);
  border-color: var(--color-error, #c0392b);
}

/* Query nav */
.query-nav {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
  flex-wrap: wrap;
}
.query-counter { font-size: 0.875rem; flex: 1; }

/* Export */
.export-row { display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; }
.export-format-group {
  border: none;
  padding: 0;
  display: flex;
  gap: 0.75rem;
}
.export-format-group legend {
  font-size: 0.85rem;
  font-weight: 600;
  margin-bottom: 0.25rem;
  float: left;
  margin-right: 0.5rem;
}
.export-format-group label { font-size: 0.875rem; display: flex; align-items: center; gap: 0.3rem; }

@media (max-width: 768px) {
  .results-table thead th,
  .results-table td { padding: 0.35rem 0.4rem; font-size: 0.8rem; }
  .query-nav { flex-direction: column; align-items: flex-start; }
}

@media (prefers-reduced-motion: reduce) {
  .score-bar { transition: none; }
}
</style>
