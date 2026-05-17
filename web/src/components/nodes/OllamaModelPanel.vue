<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

const props = defineProps<{ nodeId: string }>()

interface OllamaModel {
  name: string
  size: number
  modified_at: string
}

const models = ref<OllamaModel[]>([])
const loading = ref(true)
const loadError = ref('')
const pullName = ref('')
const pulling = ref(false)
const pullStatus = ref('')
const pullPct = ref(0)
const pullError = ref('')

// AbortController for the SSE pull stream
const abortCtrl = ref<AbortController | null>(null)

// AbortController for the one-shot fetchModels request
let fetchAbort: AbortController | null = null

async function fetchModels() {
  fetchAbort?.abort()
  fetchAbort = new AbortController()
  loading.value = true
  loadError.value = ''
  try {
    const r = await fetch(`/api/nodes-mgmt/nodes/${props.nodeId}/models/ollama`, {
      signal: fetchAbort.signal,
    })
    const data = await r.json() as { models?: OllamaModel[]; error?: string }
    if (data.error) { loadError.value = data.error; return }
    models.value = data.models ?? []
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') return
    loadError.value = e instanceof Error ? e.message : 'Failed to load models'
  } finally {
    loading.value = false
  }
}

async function doPull() {
  const name = pullName.value.trim()
  if (!name || pulling.value) return
  pulling.value = true
  pullStatus.value = 'Starting...'
  pullError.value = ''
  pullPct.value = 0

  const ctrl = new AbortController()
  abortCtrl.value = ctrl

  try {
    const resp = await fetch(`/api/nodes-mgmt/nodes/${props.nodeId}/models/ollama/pull`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
      signal: ctrl.signal,
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    if (!resp.body) throw new Error('No response body')

    const reader = resp.body.getReader()
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
        try {
          const evt = JSON.parse(line.slice(6)) as {
            status?: string; error?: string; total?: number; completed?: number
          }
          if (evt.error) {
            pullError.value = evt.error
            break
          }
          if (evt.status) pullStatus.value = evt.status
          if (evt.total && evt.completed) {
            pullPct.value = Math.round((evt.completed / evt.total) * 100)
          }
          if (evt.status === 'success') {
            pullStatus.value = 'Done!'
            pullName.value = ''
            break
          }
        } catch { /* skip malformed line */ }
      }
    }

    // Refresh model list after the stream closes (success or benign end)
    await fetchModels()
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') return
    pullError.value = e instanceof Error ? e.message : 'Pull failed'
  } finally {
    pulling.value = false
    abortCtrl.value = null
  }
}

async function deleteModel(name: string) {
  if (!confirm(`Delete model "${name}" from node ${props.nodeId}?`)) return
  try {
    const r = await fetch(
      `/api/nodes-mgmt/nodes/${props.nodeId}/models/ollama/${encodeURIComponent(name)}`,
      { method: 'DELETE' },
    )
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    await fetchModels()
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : 'Delete failed'
  }
}

function formatSize(bytes: number): string {
  return (bytes / 1e9).toFixed(1) + ' GB'
}

onMounted(fetchModels)
onUnmounted(() => {
  abortCtrl.value?.abort()
  fetchAbort?.abort()
})
</script>

<template>
  <section class="ollama-panel">
    <h3 class="panel-title">Ollama Models</h3>

    <form class="pull-form" @submit.prevent="doPull">
      <input
        v-model="pullName"
        type="text"
        placeholder="nomic-embed-text, llama3.2:3b, ..."
        :disabled="pulling"
        aria-label="Model name to pull from Ollama"
        class="pull-input"
      />
      <button type="submit" :disabled="pulling || !pullName.trim()" class="btn-primary btn-sm">
        {{ pulling ? 'Pulling...' : 'Pull' }}
      </button>
    </form>

    <div v-if="pulling || pullStatus" class="pull-progress" aria-live="polite">
      <div
        class="progress-bar"
        role="progressbar"
        :aria-valuenow="pullPct"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-label="`Pull progress: ${pullStatus}`"
      >
        <div class="progress-fill" :style="{ width: `${pullPct}%` }" />
      </div>
      <span class="progress-label">{{ pullStatus }}{{ pullPct > 0 ? ` (${pullPct}%)` : '' }}</span>
    </div>

    <div v-if="pullError" class="pull-error" role="alert">
      {{ pullError }}
      <span v-if="pullError.includes('permission denied')">
        — Remove the partial file on the node and retry.
      </span>
    </div>

    <div aria-live="polite" aria-atomic="true" class="sr-announce">
      <span v-if="loading">Loading...</span>
    </div>
    <div v-if="loadError" class="panel-error" role="alert">{{ loadError }}</div>
    <ul v-if="!loading && !loadError" class="model-list" role="list">
      <li v-if="!models.length" class="model-empty">No Ollama models installed on this node.</li>
      <li v-for="m in models" :key="m.name" class="model-item">
        <span class="model-name">{{ m.name }}</span>
        <span class="model-size">{{ formatSize(m.size) }}</span>
        <button
          class="btn-danger btn-xs"
          @click="deleteModel(m.name)"
          :aria-label="`Delete ${m.name}`"
        >
          Delete
        </button>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.ollama-panel {
  margin-top: 0.75rem;
  padding: 0.75rem;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  color: var(--color-text);
}
.panel-title { margin: 0 0 0.75rem; font-size: 0.9rem; color: var(--color-text); }
.pull-form { display: flex; gap: 0.5rem; margin-bottom: 0.5rem; }
.pull-input {
  flex: 1;
  padding: 0.3rem 0.5rem;
  background: var(--color-surface-alt);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  color: var(--color-text);
  font-size: 0.875rem;
}
.pull-progress { margin-bottom: 0.5rem; }
.progress-bar {
  height: 8px;
  background: var(--color-border);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 0.25rem;
}
.progress-fill { height: 100%; background: var(--app-primary); transition: width 0.2s; }
.progress-label { font-size: 0.75rem; color: var(--color-text-muted); }
.pull-error, .panel-error { color: var(--color-error); font-size: 0.8rem; margin-bottom: 0.5rem; }
.sr-announce { min-height: 1.2em; }
.panel-loading { color: var(--color-text-muted); font-size: 0.875rem; }
.model-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.3rem; }
.model-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.3rem 0.5rem;
  background: var(--color-surface-alt);
  border-radius: 4px;
  font-size: 0.875rem;
}
.model-name { flex: 1; font-family: var(--font-mono, monospace); }
.model-size { color: var(--color-text-muted); font-size: 0.8rem; }
.model-empty { color: var(--color-text-muted); font-size: 0.875rem; padding: 0.25rem 0; }
</style>
