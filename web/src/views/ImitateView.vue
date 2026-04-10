<template>
  <div class="imitate-view">
    <header class="bench-header">
      <h1 class="page-title">🪞 Imitate</h1>
      <p class="page-subtitle">Pull real samples from CF product APIs and compare LLM responses</p>
    </header>

    <!-- ── Step 1: Product selection ──────────────────────────────── -->
    <section class="step-section">
      <h2 class="step-heading">1. Select Product</h2>
      <div v-if="productsLoading" class="picker-loading">Loading products…</div>
      <div v-else-if="products.length === 0" class="picker-empty">
        No products configured — add an <code>imitate:</code> section to
        <code>config/label_tool.yaml</code>.
      </div>
      <div v-else class="product-grid">
        <button
          v-for="p in products"
          :key="p.id"
          class="product-card"
          :class="{
            selected: selectedProduct?.id === p.id,
            offline: !p.online,
          }"
          :disabled="!p.online"
          :title="p.online ? p.description : `${p.name} is offline`"
          @click="selectProduct(p)"
        >
          <span class="product-icon">{{ p.icon }}</span>
          <span class="product-name">{{ p.name }}</span>
          <span class="product-status" :class="p.online ? 'status-on' : 'status-off'">
            {{ p.online ? 'online' : 'offline' }}
          </span>
        </button>
      </div>
    </section>

    <!-- ── Step 2: Sample + Prompt ────────────────────────────────── -->
    <section v-if="selectedProduct" class="step-section">
      <h2 class="step-heading">2. Sample &amp; Prompt</h2>
      <div class="sample-toolbar">
        <span class="sample-product-label">{{ selectedProduct.icon }} {{ selectedProduct.name }}</span>
        <button class="btn-refresh" :disabled="sampleLoading" @click="fetchSample">
          {{ sampleLoading ? '⏳ Fetching…' : '🔄 Refresh Sample' }}
        </button>
        <span v-if="sampleError" class="sample-error">{{ sampleError }}</span>
      </div>

      <div v-if="sampleLoading" class="picker-loading">Fetching sample from API…</div>

      <template v-else-if="rawSample">
        <!-- Fetched text preview -->
        <details class="sample-preview" open>
          <summary class="sample-preview-toggle">Raw sample text</summary>
          <pre class="sample-text">{{ rawSample.text }}</pre>
        </details>

        <!-- Prompt editor -->
        <label class="prompt-label" for="prompt-editor">Prompt sent to models</label>
        <textarea
          id="prompt-editor"
          class="prompt-editor"
          v-model="editedPrompt"
          rows="8"
        />
      </template>

      <div v-else-if="!sampleLoading && selectedProduct" class="picker-empty">
        Click "Refresh Sample" to fetch a real sample from {{ selectedProduct.name }}.
      </div>
    </section>

    <!-- ── Step 3: Models + Run ───────────────────────────────────── -->
    <section v-if="editedPrompt" class="step-section">
      <h2 class="step-heading">3. Models &amp; Run</h2>

      <!-- Ollama model picker -->
      <details class="model-picker" open>
        <summary class="picker-summary">
          <span class="picker-title">🤖 Ollama Models</span>
          <span class="picker-badge">{{ selectedModels.size }} / {{ ollamaModels.length }}</span>
        </summary>
        <div class="picker-body">
          <div v-if="modelsLoading" class="picker-loading">Loading models…</div>
          <div v-else-if="ollamaModels.length === 0" class="picker-empty">
            No ollama models in bench_models.yaml — add models with <code>service: ollama</code>.
          </div>
          <template v-else>
            <label class="picker-cat-header">
              <input
                type="checkbox"
                :checked="selectedModels.size === ollamaModels.length"
                :indeterminate="selectedModels.size > 0 && selectedModels.size < ollamaModels.length"
                @change="toggleAllModels(($event.target as HTMLInputElement).checked)"
              />
              <span class="picker-cat-name">All ollama models</span>
            </label>
            <div class="picker-model-list">
              <label v-for="m in ollamaModels" :key="m.id" class="picker-model-row">
                <input
                  type="checkbox"
                  :checked="selectedModels.has(m.id)"
                  @change="toggleModel(m.id, ($event.target as HTMLInputElement).checked)"
                />
                <span class="picker-model-name" :title="m.name">{{ m.name }}</span>
                <span class="picker-model-tags">
                  <span v-for="tag in m.tags.slice(0, 3)" :key="tag" class="tag">{{ tag }}</span>
                </span>
              </label>
            </div>
          </template>
        </div>
      </details>

      <!-- Temperature -->
      <div class="temp-row">
        <label for="temp-slider" class="temp-label">Temperature: <strong>{{ temperature.toFixed(1) }}</strong></label>
        <input
          id="temp-slider"
          type="range" min="0" max="1" step="0.1"
          :value="temperature"
          @input="temperature = parseFloat(($event.target as HTMLInputElement).value)"
          class="temp-slider"
        />
      </div>

      <!-- Run controls -->
      <div class="run-row">
        <button
          class="btn-run"
          :disabled="running || selectedModels.size === 0"
          @click="startRun"
        >
          {{ running ? '⏳ Running…' : '▶ Run' }}
        </button>
        <button v-if="running" class="btn-cancel" @click="cancelRun">✕ Cancel</button>
      </div>

      <!-- Progress log -->
      <div v-if="runLog.length > 0" class="run-log" aria-live="polite">
        <div v-for="(line, i) in runLog" :key="i" class="log-line">{{ line }}</div>
      </div>
    </section>

    <!-- ── Step 4: Results ────────────────────────────────────────── -->
    <section v-if="results.length > 0" class="step-section">
      <h2 class="step-heading">4. Results</h2>

      <div class="results-grid">
        <div
          v-for="r in results"
          :key="r.model"
          class="result-card"
          :class="{ 'result-error': !!r.error }"
        >
          <div class="result-header">
            <span class="result-model">{{ r.model }}</span>
            <span class="result-meta">
              <template v-if="r.error">
                <span class="result-err-badge">error</span>
              </template>
              <template v-else>
                {{ (r.elapsed_ms / 1000).toFixed(1) }}s
              </template>
            </span>
          </div>
          <pre v-if="r.error" class="result-error-text">{{ r.error }}</pre>
          <pre v-else class="result-response">{{ r.response }}</pre>
        </div>
      </div>

      <div class="corrections-row">
        <button
          class="btn-corrections"
          :disabled="pushingCorrections || !selectedProduct || successfulResults.length === 0"
          @click="pushCorrections"
        >
          {{ pushingCorrections ? '⏳ Pushing…' : `✍ Send ${successfulResults.length} to Corrections` }}
        </button>
        <span v-if="correctionsPushMsg" class="corrections-msg" :class="correctionsPushOk ? 'msg-ok' : 'msg-err'">
          {{ correctionsPushMsg }}
        </span>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

// ── Types ──────────────────────────────────────────────────────────────────────

interface Product {
  id: string
  name: string
  icon: string
  description: string
  base_url: string
  online: boolean
}

interface Sample {
  product_id: string
  sample_index: number
  text: string
  prompt: string
  raw_item: Record<string, unknown>
}

interface ModelEntry {
  id: string
  name: string
  service: string
  tags: string[]
  vram_estimate_mb: number
}

interface RunResult {
  model: string
  response: string
  elapsed_ms: number
  error: string | null
}

// ── State ──────────────────────────────────────────────────────────────────────

const productsLoading  = ref(false)
const products         = ref<Product[]>([])
const selectedProduct  = ref<Product | null>(null)

const sampleLoading    = ref(false)
const sampleError      = ref<string | null>(null)
const rawSample        = ref<Sample | null>(null)
const editedPrompt     = ref('')

const modelsLoading    = ref(false)
const allModels        = ref<ModelEntry[]>([])
const selectedModels   = ref<Set<string>>(new Set())

const temperature      = ref(0.7)

const running          = ref(false)
const eventSource      = ref<EventSource | null>(null)
const runLog           = ref<string[]>([])
const results          = ref<RunResult[]>([])

const pushingCorrections = ref(false)
const correctionsPushMsg = ref<string | null>(null)
const correctionsPushOk  = ref(false)

// ── Computed ───────────────────────────────────────────────────────────────────

const ollamaModels = computed(() =>
  allModels.value.filter(m => m.service === 'ollama')
)

const successfulResults = computed(() =>
  results.value.filter(r => !r.error && r.response.trim())
)

// ── Lifecycle ─────────────────────────────────────────────────────────────────

onMounted(async () => {
  await Promise.all([loadProducts(), loadModels()])
})

// ── Methods ────────────────────────────────────────────────────────────────────

async function loadProducts() {
  productsLoading.value = true
  try {
    const resp = await fetch('/api/imitate/products')
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    products.value = data.products ?? []
  } catch {
    products.value = []
  } finally {
    productsLoading.value = false
  }
}

async function loadModels() {
  modelsLoading.value = true
  try {
    const resp = await fetch('/api/cforch/models')
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    allModels.value = data.models ?? []
    // Select all ollama models by default
    for (const m of allModels.value) {
      if (m.service === 'ollama') selectedModels.value.add(m.id)
    }
  } catch {
    allModels.value = []
  } finally {
    modelsLoading.value = false
  }
}

async function selectProduct(p: Product) {
  selectedProduct.value = p
  rawSample.value = null
  editedPrompt.value = ''
  sampleError.value = null
  results.value = []
  runLog.value = []
  await fetchSample()
}

async function fetchSample() {
  if (!selectedProduct.value) return
  sampleLoading.value = true
  sampleError.value = null
  try {
    const resp = await fetch(`/api/imitate/products/${selectedProduct.value.id}/sample`)
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({ detail: 'Unknown error' }))
      throw new Error(body.detail ?? `HTTP ${resp.status}`)
    }
    const data: Sample = await resp.json()
    rawSample.value = data
    editedPrompt.value = data.prompt
  } catch (err: unknown) {
    sampleError.value = err instanceof Error ? err.message : String(err)
  } finally {
    sampleLoading.value = false
  }
}

function toggleModel(id: string, checked: boolean) {
  const next = new Set(selectedModels.value)
  checked ? next.add(id) : next.delete(id)
  selectedModels.value = next
}

function toggleAllModels(checked: boolean) {
  selectedModels.value = checked
    ? new Set(ollamaModels.value.map(m => m.id))
    : new Set()
}

function startRun() {
  if (running.value || !editedPrompt.value.trim() || selectedModels.value.size === 0) return

  running.value = true
  results.value = []
  runLog.value = []
  correctionsPushMsg.value = null

  const params = new URLSearchParams({
    prompt:     editedPrompt.value,
    model_ids:  [...selectedModels.value].join(','),
    temperature: temperature.value.toString(),
    product_id: selectedProduct.value?.id ?? '',
  })

  const es = new EventSource(`/api/imitate/run?${params}`)
  eventSource.value = es

  es.onmessage = (event: MessageEvent) => {
    try {
      const msg = JSON.parse(event.data)
      if (msg.type === 'start') {
        runLog.value.push(`Running ${msg.total_models} model(s)…`)
      } else if (msg.type === 'model_start') {
        runLog.value.push(`→ ${msg.model}…`)
      } else if (msg.type === 'model_done') {
        const status = msg.error
          ? `✕ error: ${msg.error}`
          : `✓ done (${(msg.elapsed_ms / 1000).toFixed(1)}s)`
        runLog.value.push(`  ${msg.model}: ${status}`)
        results.value.push({
          model:      msg.model,
          response:   msg.response,
          elapsed_ms: msg.elapsed_ms,
          error:      msg.error ?? null,
        })
      } else if (msg.type === 'complete') {
        runLog.value.push(`Complete. ${results.value.length} responses.`)
        running.value = false
        es.close()
      }
    } catch {
      // ignore malformed SSE frames
    }
  }

  es.onerror = () => {
    runLog.value.push('Connection error — run may be incomplete.')
    running.value = false
    es.close()
  }
}

function cancelRun() {
  eventSource.value?.close()
  eventSource.value = null
  running.value = false
  runLog.value.push('Cancelled.')
}

async function pushCorrections() {
  if (!selectedProduct.value || successfulResults.value.length === 0) return

  pushingCorrections.value = true
  correctionsPushMsg.value = null
  try {
    const resp = await fetch('/api/imitate/push-corrections', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        product_id: selectedProduct.value.id,
        prompt:     editedPrompt.value,
        results:    successfulResults.value,
      }),
    })
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({ detail: 'Unknown error' }))
      throw new Error(body.detail ?? `HTTP ${resp.status}`)
    }
    const data = await resp.json()
    correctionsPushMsg.value = `${data.pushed} record(s) added to Corrections queue.`
    correctionsPushOk.value = true
  } catch (err: unknown) {
    correctionsPushMsg.value = err instanceof Error ? err.message : String(err)
    correctionsPushOk.value = false
  } finally {
    pushingCorrections.value = false
  }
}
</script>

<style scoped>
.imitate-view {
  max-width: 1100px;
  margin: 0 auto;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.bench-header {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.page-title {
  font-size: 1.6rem;
  font-weight: 700;
  color: var(--color-text, #1a2338);
}

.page-subtitle {
  font-size: 0.9rem;
  color: var(--color-text-secondary, #6b7a99);
}

/* Steps */
.step-section {
  background: var(--color-surface-raised, #e4ebf5);
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.step-heading {
  font-size: 1rem;
  font-weight: 600;
  color: var(--color-text-secondary, #6b7a99);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid var(--color-border, #d0d7e8);
  padding-bottom: 0.5rem;
}

/* Product grid */
.product-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 0.75rem;
}

.product-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.35rem;
  padding: 1rem 0.75rem;
  border: 2px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  background: var(--color-surface, #f0f4fc);
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
  font-size: 0.9rem;
}

.product-card:hover:not(:disabled) {
  border-color: var(--app-primary, #2A6080);
  background: color-mix(in srgb, var(--app-primary, #2A6080) 6%, var(--color-surface, #f0f4fc));
}

.product-card.selected {
  border-color: var(--app-primary, #2A6080);
  background: color-mix(in srgb, var(--app-primary, #2A6080) 12%, var(--color-surface, #f0f4fc));
}

.product-card.offline {
  opacity: 0.45;
  cursor: not-allowed;
}

.product-icon {
  font-size: 2rem;
}

.product-name {
  font-weight: 600;
  color: var(--color-text, #1a2338);
}

.product-status {
  font-size: 0.72rem;
  padding: 0.1rem 0.45rem;
  border-radius: 9999px;
  font-weight: 600;
}

.status-on {
  background: #d1fae5;
  color: #065f46;
}

.status-off {
  background: #fee2e2;
  color: #991b1b;
}

/* Sample panel */
.sample-toolbar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.sample-product-label {
  font-weight: 600;
  color: var(--app-primary, #2A6080);
}

.sample-error {
  color: #b91c1c;
  font-size: 0.85rem;
}

.sample-preview {
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.375rem;
  overflow: hidden;
}

.sample-preview-toggle {
  padding: 0.5rem 0.75rem;
  cursor: pointer;
  font-size: 0.85rem;
  color: var(--color-text-secondary, #6b7a99);
  background: var(--color-surface, #f0f4fc);
  user-select: none;
}

.sample-text {
  padding: 0.75rem;
  font-size: 0.82rem;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 180px;
  overflow-y: auto;
  background: var(--color-bg, #f0f4fc);
  margin: 0;
  color: var(--color-text, #1a2338);
}

.prompt-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--color-text-secondary, #6b7a99);
}

.prompt-editor {
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
}

.prompt-editor:focus {
  outline: 2px solid var(--app-primary, #2A6080);
  outline-offset: -1px;
}

/* Model picker — reuse bench-view classes */
.model-picker {
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  overflow: hidden;
}

.picker-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  background: var(--color-surface, #f0f4fc);
  cursor: pointer;
  font-size: 0.95rem;
  font-weight: 600;
  user-select: none;
  list-style: none;
}

.picker-title { flex: 1; }

.picker-badge {
  font-size: 0.8rem;
  background: var(--app-primary, #2A6080);
  color: #fff;
  border-radius: 9999px;
  padding: 0.15rem 0.6rem;
}

.picker-body {
  padding: 0.75rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.picker-loading, .picker-empty {
  font-size: 0.85rem;
  color: var(--color-text-secondary, #6b7a99);
  padding: 0.5rem 0;
}

.picker-cat-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 600;
  font-size: 0.9rem;
  padding: 0.35rem 0;
  cursor: pointer;
}

.picker-model-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  padding-left: 1.25rem;
  padding-bottom: 0.5rem;
}

.picker-model-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
  cursor: pointer;
  padding: 0.2rem 0.5rem;
  border-radius: 0.25rem;
  min-width: 220px;
}

.picker-model-row:hover {
  background: color-mix(in srgb, var(--app-primary, #2A6080) 8%, transparent);
}

.picker-model-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.picker-model-tags {
  display: flex;
  gap: 0.2rem;
  flex-shrink: 0;
}

.tag {
  font-size: 0.68rem;
  background: var(--color-border, #d0d7e8);
  border-radius: 9999px;
  padding: 0.05rem 0.4rem;
  color: var(--color-text-secondary, #6b7a99);
  white-space: nowrap;
}

/* Temperature */
.temp-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.temp-label {
  font-size: 0.85rem;
  white-space: nowrap;
  min-width: 160px;
}

.temp-slider {
  flex: 1;
  accent-color: var(--app-primary, #2A6080);
}

/* Run controls */
.run-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.btn-run {
  background: var(--app-primary, #2A6080);
  color: #fff;
  border: none;
  border-radius: 0.375rem;
  padding: 0.55rem 1.25rem;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s;
}

.btn-run:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-cancel {
  background: transparent;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.375rem;
  padding: 0.5rem 0.9rem;
  font-size: 0.85rem;
  cursor: pointer;
  color: var(--color-text-secondary, #6b7a99);
}

.btn-refresh {
  background: transparent;
  border: 1px solid var(--app-primary, #2A6080);
  border-radius: 0.375rem;
  padding: 0.35rem 0.8rem;
  font-size: 0.85rem;
  color: var(--app-primary, #2A6080);
  cursor: pointer;
  transition: background 0.15s;
}

.btn-refresh:hover:not(:disabled) {
  background: color-mix(in srgb, var(--app-primary, #2A6080) 10%, transparent);
}

.btn-refresh:disabled { opacity: 0.5; cursor: not-allowed; }

/* Run log */
.run-log {
  background: var(--color-bg, #f0f4fc);
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.375rem;
  padding: 0.75rem;
  font-family: var(--font-mono, monospace);
  font-size: 0.8rem;
  max-height: 140px;
  overflow-y: auto;
}

.log-line {
  padding: 0.05rem 0;
  color: var(--color-text, #1a2338);
}

/* Results */
.results-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 1rem;
}

.result-card {
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  overflow: hidden;
  background: var(--color-surface, #f0f4fc);
  display: flex;
  flex-direction: column;
}

.result-card.result-error {
  border-color: #fca5a5;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5rem 0.75rem;
  background: var(--color-surface-raised, #e4ebf5);
  border-bottom: 1px solid var(--color-border, #d0d7e8);
}

.result-model {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--color-text, #1a2338);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.result-meta {
  font-size: 0.75rem;
  color: var(--color-text-secondary, #6b7a99);
  flex-shrink: 0;
  margin-left: 0.5rem;
}

.result-err-badge {
  background: #fee2e2;
  color: #991b1b;
  border-radius: 9999px;
  padding: 0.1rem 0.45rem;
  font-size: 0.7rem;
  font-weight: 600;
}

.result-response, .result-error-text {
  padding: 0.75rem;
  font-size: 0.82rem;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 280px;
  overflow-y: auto;
  margin: 0;
  flex: 1;
  color: var(--color-text, #1a2338);
}

.result-error-text {
  color: #b91c1c;
}

/* Corrections */
.corrections-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.btn-corrections {
  background: var(--color-accent-warm, #b45309);
  color: #fff;
  border: none;
  border-radius: 0.375rem;
  padding: 0.55rem 1.25rem;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s;
}

.btn-corrections:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.corrections-msg {
  font-size: 0.85rem;
}

.msg-ok { color: #065f46; }
.msg-err { color: #b91c1c; }
</style>
