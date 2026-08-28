<!-- Structural sibling to PlansBenchTab.vue -- same run-trigger +
     EventSource-streamed-progress + results-list/detail shape, pointed
     at /api/vaportrade-bench instead of /api/plans-bench. -->
<template>
  <div class="vt-bench-tab">
    <p class="vt-intro">
      Triggers VaporTrade's own <code>bench/</code> harness (cost benchmark or a Locust load-test
      sweep) and streams its progress here. These numbers are raw input for a future pricing
      decision, not a recommendation.
    </p>

    <!-- ── Run controls ─────────────────────────────────────────────────── -->
    <div class="run-bar">
      <button
        class="btn-run"
        :disabled="running"
        @click="runCost"
      >{{ running && activeKind === 'cost' ? '⏳ Running cost…' : '▶ Run cost benchmark' }}</button>

      <label class="option-row">
        <span class="option-label">load-test users</span>
        <input
          v-model.number="loadUsers"
          type="number"
          min="1"
          max="1000"
          class="option-number"
          :disabled="running"
        />
      </label>

      <label class="option-row">
        <span class="option-label">label</span>
        <select v-model="loadLabel" class="option-select" :disabled="running">
          <option value="single">single-node</option>
          <option value="fleet">fleet</option>
        </select>
      </label>

      <button
        class="btn-run"
        :disabled="running"
        @click="runLoad"
      >{{ running && activeKind === 'load' ? '⏳ Running load…' : '▶ Run load test' }}</button>

      <button v-if="running" class="btn-cancel" @click="cancel">✕ Cancel</button>
    </div>

    <!-- ── Progress log ─────────────────────────────────────────────────── -->
    <div v-if="progressLines.length" class="run-log">
      <div class="run-log-header">
        <span class="run-log-title">Run log</span>
        <button class="btn-log-action" @click="progressLines = []">Clear</button>
      </div>
      <pre class="run-log-body" ref="logEl">{{ progressLines.join('\n') }}</pre>
    </div>

    <!-- ── Past results ─────────────────────────────────────────────────── -->
    <div class="results-section">
      <h2 class="results-title">Past results</h2>
      <p v-if="!results.length" class="run-hint">No runs yet — trigger a cost or load run above.</p>
      <ul v-else class="results-list">
        <li v-for="r in results" :key="r.run_id" class="results-list-item">
          <a href="#" class="results-link" @click.prevent="openResult(r.run_id)">{{ r.filename }}</a>
        </li>
      </ul>
      <pre v-if="selectedContent" class="detail-response">{{ selectedContent }}</pre>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'

interface PastResult { run_id: string; filename: string }

const running         = ref(false)
const activeKind       = ref<'cost' | 'load' | null>(null)
const progressLines    = ref<string[]>([])
const results          = ref<PastResult[]>([])
const selectedContent  = ref('')
const loadUsers        = ref(10)
const loadLabel        = ref<'single' | 'fleet'>('single')
const logEl            = ref<HTMLPreElement | null>(null)

let es: EventSource | null = null

async function loadResults() {
  try {
    const r = await fetch('/api/vaportrade-bench/results')
    if (!r.ok) return
    results.value = await r.json()
  } catch {
    // non-critical
  }
}

async function openResult(runId: string) {
  try {
    const r = await fetch(`/api/vaportrade-bench/results/${runId}`)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const data = await r.json()
    selectedContent.value = data.content ?? ''
  } catch (e: unknown) {
    progressLines.value.push(`Error loading result: ${e instanceof Error ? e.message : String(e)}`)
  }
}

function startRun(kind: 'cost' | 'load', params: string) {
  if (running.value) return
  running.value = true
  activeKind.value = kind
  progressLines.value = []
  selectedContent.value = ''

  es = new EventSource(`/api/vaportrade-bench/run?${params}`)
  es.onmessage = async (ev) => {
    const data = JSON.parse(ev.data)
    if (data.type === 'progress') {
      progressLines.value.push(data.message)
      await nextTick()
      if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
    } else if (data.type === 'complete') {
      running.value = false
      activeKind.value = null
      es?.close()
      loadResults()
    } else if (data.type === 'error') {
      progressLines.value.push(`ERROR: ${data.message}`)
      running.value = false
      activeKind.value = null
      es?.close()
    }
  }
  es.onerror = () => {
    progressLines.value.push('Connection error — run may have ended unexpectedly.')
    running.value = false
    activeKind.value = null
    es?.close()
  }
}

function runCost() {
  startRun('cost', 'kind=cost')
}

function runLoad() {
  startRun('load', `kind=load&users=${loadUsers.value}&label=${loadLabel.value}`)
}

async function cancel() {
  try {
    await fetch('/api/vaportrade-bench/cancel', { method: 'POST' })
  } catch {
    // ignore
  } finally {
    running.value = false
    activeKind.value = null
    es?.close()
  }
}

onMounted(loadResults)
</script>

<style scoped>
.vt-bench-tab {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.vt-intro {
  font-size: 0.85rem;
  color: var(--color-text-secondary, #6b7a99);
  margin: 0;
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

.option-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
}
.option-label {
  font-weight: 500;
  color: var(--color-text, #1a2540);
}
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
.option-select {
  padding: 0.3rem 0.5rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.3rem;
  font-size: 0.85rem;
  background: var(--color-surface, #fff);
  color: var(--color-text, #1a2540);
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
.btn-log-action {
  background: none;
  border: none;
  font-size: 0.78rem;
  color: var(--color-muted, #8a98b4);
  cursor: pointer;
  padding: 0;
}
.btn-log-action:hover { color: var(--color-text, #1a2540) }
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

/* ── Results section ─────────────────────────────────────────────────── */
.results-section { display: flex; flex-direction: column; gap: 0.6rem }

.results-title {
  font-size: 1rem;
  font-weight: 700;
  color: var(--app-primary, #2A6080);
  margin: 0;
}

.results-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.results-list-item { font-size: 0.85rem }
.results-link {
  color: var(--app-primary, #2A6080);
  text-decoration: none;
}
.results-link:hover { text-decoration: underline }

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

@media (max-width: 600px) {
  .run-bar { flex-direction: column; align-items: stretch }
  .option-row { justify-content: space-between }
}
</style>
