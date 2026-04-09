<template>
  <div class="models-view">
    <h1 class="page-title">🤗 Models</h1>

    <!-- ── 1. HF Lookup ───────────────────────────────── -->
    <section class="section">
      <h2 class="section-title">HuggingFace Lookup</h2>

      <div class="lookup-row">
        <input
          v-model="lookupInput"
          type="text"
          class="lookup-input"
          placeholder="org/model or huggingface.co/org/model"
          :disabled="lookupLoading"
          @keydown.enter="doLookup"
          aria-label="HuggingFace model ID"
        />
        <button
          class="btn-primary"
          :disabled="lookupLoading || !lookupInput.trim()"
          @click="doLookup"
        >
          {{ lookupLoading ? 'Looking up…' : 'Lookup' }}
        </button>
      </div>

      <div v-if="lookupError" class="error-notice" role="alert">
        {{ lookupError }}
      </div>

      <div v-if="lookupResult" class="preview-card">
        <div class="preview-header">
          <span class="preview-repo-id">{{ lookupResult.repo_id }}</span>
          <div class="badge-group">
            <span v-if="lookupResult.already_installed" class="badge badge-success">Installed</span>
            <span v-if="lookupResult.already_queued"    class="badge badge-info">In queue</span>
          </div>
        </div>

        <div class="preview-meta">
          <span v-if="lookupResult.pipeline_tag" class="chip chip-pipeline">
            {{ lookupResult.pipeline_tag }}
          </span>
          <span v-if="lookupResult.adapter_recommendation" class="chip chip-adapter">
            {{ lookupResult.adapter_recommendation }}
          </span>
          <span v-if="lookupResult.size != null" class="preview-size">
            {{ humanBytes(lookupResult.size) }}
          </span>
        </div>

        <p v-if="lookupResult.description" class="preview-desc">
          {{ lookupResult.description }}
        </p>

        <div v-if="lookupResult.warning" class="compat-warning" role="alert">
          <span class="compat-warning-icon">⚠️</span>
          <span>{{ lookupResult.warning }}</span>
        </div>

        <button
          class="btn-primary btn-add-queue"
          :class="{ 'btn-add-queue-warn': !lookupResult.compatible }"
          :disabled="lookupResult.already_installed || lookupResult.already_queued || addingToQueue"
          @click="addToQueue"
        >
          {{ addingToQueue ? 'Adding…' : lookupResult.compatible ? 'Add to queue' : 'Add anyway' }}
        </button>
      </div>
    </section>

    <!-- ── 2. Approval Queue ──────────────────────────── -->
    <section class="section">
      <h2 class="section-title">Approval Queue</h2>

      <div v-if="pendingModels.length === 0" class="empty-notice">
        No models waiting for approval.
      </div>

      <div v-for="model in pendingModels" :key="model.id" class="model-card">
        <div class="model-card-header">
          <span class="model-repo-id">{{ model.repo_id }}</span>
          <button
            class="btn-dismiss"
            :aria-label="`Dismiss ${model.repo_id}`"
            @click="dismissModel(model.id)"
          >
            ✕
          </button>
        </div>
        <div class="model-meta">
          <span v-if="model.pipeline_tag"         class="chip chip-pipeline">{{ model.pipeline_tag }}</span>
          <span v-if="model.adapter_recommendation" class="chip chip-adapter">{{ model.adapter_recommendation }}</span>
        </div>
        <div class="model-card-actions">
          <button class="btn-primary btn-sm" @click="approveModel(model.id)">
            Approve download
          </button>
        </div>
      </div>
    </section>

    <!-- ── 3. Active Downloads ────────────────────────── -->
    <section class="section">
      <h2 class="section-title">Active Downloads</h2>

      <div v-if="downloadingModels.length === 0" class="empty-notice">
        No active downloads.
      </div>

      <div v-for="model in downloadingModels" :key="model.id" class="model-card">
        <div class="model-card-header">
          <span class="model-repo-id">{{ model.repo_id }}</span>
          <span v-if="downloadErrors[model.id]" class="badge badge-error">Error</span>
        </div>
        <div class="model-meta">
          <span v-if="model.pipeline_tag" class="chip chip-pipeline">{{ model.pipeline_tag }}</span>
        </div>

        <div v-if="downloadErrors[model.id]" class="download-error" role="alert">
          {{ downloadErrors[model.id] }}
        </div>
        <div v-else class="progress-wrap" :aria-label="`Download progress for ${model.repo_id}`">
          <div
            class="progress-bar"
            :style="{ width: `${downloadProgress[model.id] ?? 0}%` }"
            role="progressbar"
            :aria-valuenow="downloadProgress[model.id] ?? 0"
            aria-valuemin="0"
            aria-valuemax="100"
          />
          <span class="progress-label">
            {{ downloadProgress[model.id] == null ? 'Preparing…' : `${downloadProgress[model.id]}%` }}
          </span>
        </div>
      </div>
    </section>

    <!-- ── 4. Installed Models ────────────────────────── -->
    <section class="section">
      <h2 class="section-title">Installed Models</h2>

      <div v-if="installedModels.length === 0" class="empty-notice">
        No models installed yet.
      </div>

      <div v-else class="installed-table-wrap">
        <table class="installed-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Adapter</th>
              <th>Size</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="model in installedModels" :key="model.name">
              <td class="td-name">{{ model.name }}</td>
              <td>
                <span
                  class="badge"
                  :class="model.type === 'finetuned' ? 'badge-accent' : 'badge-info'"
                >
                  {{ model.type }}
                </span>
              </td>
              <td>{{ model.adapter ?? '—' }}</td>
              <td>{{ humanBytes(model.size) }}</td>
              <td>
                <button
                  class="btn-danger btn-sm"
                  @click="deleteInstalled(model.name)"
                >
                  Delete
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'

// ── Type definitions ──────────────────────────────────

interface LookupResult {
  repo_id: string
  pipeline_tag: string | null
  adapter_recommendation: string | null
  compatible: boolean
  warning: string | null
  size: number | null
  description: string | null
  already_installed: boolean
  already_queued: boolean
}

interface QueuedModel {
  id: string
  repo_id: string
  status: 'pending' | 'downloading' | 'done' | 'error'
  pipeline_tag: string | null
  adapter_recommendation: string | null
}

interface InstalledModel {
  name: string
  type: 'finetuned' | 'downloaded'
  adapter: string | null
  size: number
}

interface SseProgressEvent {
  model_id: string
  pct: number | null
  status: 'progress' | 'done' | 'error'
  message?: string
}

// ── State ─────────────────────────────────────────────

const lookupInput   = ref('')
const lookupLoading = ref(false)
const lookupError   = ref<string | null>(null)
const lookupResult  = ref<LookupResult | null>(null)
const addingToQueue = ref(false)

const queuedModels    = ref<QueuedModel[]>([])
const installedModels = ref<InstalledModel[]>([])

const downloadProgress = ref<Record<string, number>>({})
const downloadErrors   = ref<Record<string, string>>({})

let pollInterval: ReturnType<typeof setInterval> | null = null
let sseSource: EventSource | null = null

// ── Derived ───────────────────────────────────────────

const pendingModels = computed(() =>
  queuedModels.value.filter(m => m.status === 'pending')
)

const downloadingModels = computed(() =>
  queuedModels.value.filter(m => m.status === 'downloading')
)

// ── Helpers ───────────────────────────────────────────

function humanBytes(bytes: number | null): string {
  if (bytes == null) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex++
  }
  return `${value.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`
}

function normalizeRepoId(raw: string): string {
  return raw.trim().replace(/^https?:\/\/huggingface\.co\//, '')
}

// ── API calls ─────────────────────────────────────────

async function doLookup() {
  const repoId = normalizeRepoId(lookupInput.value)
  if (!repoId) return

  lookupLoading.value = true
  lookupError.value   = null
  lookupResult.value  = null

  try {
    const res = await fetch(`/api/models/lookup?repo_id=${encodeURIComponent(repoId)}`)
    if (res.status === 404) {
      lookupError.value = 'Model not found on HuggingFace.'
      return
    }
    if (res.status === 502) {
      lookupError.value = 'HuggingFace unreachable. Check your connection and try again.'
      return
    }
    if (!res.ok) {
      lookupError.value = `Lookup failed (HTTP ${res.status}).`
      return
    }
    lookupResult.value = await res.json() as LookupResult
  } catch {
    lookupError.value = 'Network error. Is the Avocet API running?'
  } finally {
    lookupLoading.value = false
  }
}

async function addToQueue() {
  if (!lookupResult.value) return
  addingToQueue.value = true
  try {
    const res = await fetch('/api/models/queue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo_id: lookupResult.value.repo_id }),
    })
    if (res.ok) {
      lookupResult.value = { ...lookupResult.value, already_queued: true }
      await loadQueue()
    }
  } catch { /* ignore — already_queued badge won't flip, user can retry */ }
  finally {
    addingToQueue.value = false
  }
}

async function approveModel(id: string) {
  try {
    const res = await fetch(`/api/models/queue/${encodeURIComponent(id)}/approve`, { method: 'POST' })
    if (res.ok) {
      await loadQueue()
      startSse()
    }
  } catch { /* ignore */ }
}

async function dismissModel(id: string) {
  try {
    const res = await fetch(`/api/models/queue/${encodeURIComponent(id)}`, { method: 'DELETE' })
    if (res.ok) {
      queuedModels.value = queuedModels.value.filter(m => m.id !== id)
    }
  } catch { /* ignore */ }
}

async function deleteInstalled(name: string) {
  if (!window.confirm(`Delete installed model "${name}"? This cannot be undone.`)) return
  try {
    const res = await fetch(`/api/models/installed/${encodeURIComponent(name)}`, { method: 'DELETE' })
    if (res.ok) {
      installedModels.value = installedModels.value.filter(m => m.name !== name)
    }
  } catch { /* ignore */ }
}

async function loadQueue() {
  try {
    const res = await fetch('/api/models/queue')
    if (res.ok) queuedModels.value = await res.json() as QueuedModel[]
  } catch { /* non-fatal */ }
}

async function loadInstalled() {
  try {
    const res = await fetch('/api/models/installed')
    if (res.ok) installedModels.value = await res.json() as InstalledModel[]
  } catch { /* non-fatal */ }
}

// ── SSE for download progress ─────────────────────────

function startSse() {
  if (sseSource) return  // already connected

  sseSource = new EventSource('/api/models/download/stream')

  sseSource.addEventListener('message', (e: MessageEvent) => {
    let event: SseProgressEvent
    try {
      event = JSON.parse(e.data as string) as SseProgressEvent
    } catch {
      return
    }

    const { model_id, pct, status, message } = event

    if (status === 'progress' && pct != null) {
      downloadProgress.value = { ...downloadProgress.value, [model_id]: pct }
    } else if (status === 'done') {
      const updated = { ...downloadProgress.value }
      delete updated[model_id]
      downloadProgress.value = updated

      queuedModels.value = queuedModels.value.filter(m => m.id !== model_id)
      loadInstalled()
    } else if (status === 'error') {
      downloadErrors.value = {
        ...downloadErrors.value,
        [model_id]: message ?? 'Download failed.',
      }
    }
  })

  sseSource.onerror = () => {
    sseSource?.close()
    sseSource = null
  }
}

function stopSse() {
  sseSource?.close()
  sseSource = null
}

// ── Polling ───────────────────────────────────────────

function startPollingIfDownloading() {
  if (pollInterval) return
  pollInterval = setInterval(async () => {
    await loadQueue()
    if (downloadingModels.value.length === 0) {
      stopPolling()
    }
  }, 5000)
}

function stopPolling() {
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
}

// ── Lifecycle ─────────────────────────────────────────

onMounted(async () => {
  await Promise.all([loadQueue(), loadInstalled()])

  if (downloadingModels.value.length > 0) {
    startSse()
    startPollingIfDownloading()
  }
})

onUnmounted(() => {
  stopPolling()
  stopSse()
})
</script>

<style scoped>
.models-view {
  max-width: 760px;
  margin: 0 auto;
  padding: 1.5rem 1rem 4rem;
  display: flex;
  flex-direction: column;
  gap: 2rem;
}

.page-title {
  font-family: var(--font-display, var(--font-body, sans-serif));
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--color-primary, #2d5a27);
}

/* ── Sections ── */
.section {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.section-title {
  font-size: 1rem;
  font-weight: 600;
  color: var(--color-text, #1a2338);
  padding-bottom: 0.4rem;
  border-bottom: 1px solid var(--color-border, #a8b8d0);
}

/* ── Lookup row ── */
.lookup-row {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.lookup-input {
  flex: 1;
  min-width: 0;
  padding: 0.45rem 0.7rem;
  border: 1px solid var(--color-border, #a8b8d0);
  border-radius: var(--radius-md, 0.5rem);
  background: var(--color-surface-raised, #f5f7fc);
  color: var(--color-text, #1a2338);
  font-size: 0.9rem;
  font-family: var(--font-body, sans-serif);
}

.lookup-input:disabled {
  opacity: 0.6;
}

.lookup-input::placeholder {
  color: var(--color-text-muted, #4a5c7a);
}

/* ── Notices ── */
.error-notice {
  padding: 0.6rem 0.8rem;
  background: color-mix(in srgb, var(--color-error, #c0392b) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--color-error, #c0392b) 30%, transparent);
  border-radius: var(--radius-md, 0.5rem);
  color: var(--color-error, #c0392b);
  font-size: 0.88rem;
}

.empty-notice {
  color: var(--color-text-muted, #4a5c7a);
  font-size: 0.9rem;
  padding: 0.75rem;
  border: 1px dashed var(--color-border, #a8b8d0);
  border-radius: var(--radius-md, 0.5rem);
}

/* ── Preview card ── */
.preview-card {
  border: 1px solid var(--color-border, #a8b8d0);
  border-radius: var(--radius-lg, 1rem);
  background: var(--color-surface-raised, #f5f7fc);
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  box-shadow: var(--shadow-sm);
}

.preview-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.preview-repo-id {
  font-family: var(--font-mono, monospace);
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--color-text, #1a2338);
  word-break: break-all;
}

.preview-meta {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
  align-items: center;
}

.preview-size {
  font-size: 0.8rem;
  color: var(--color-text-muted, #4a5c7a);
  margin-left: 0.25rem;
}

.preview-desc {
  font-size: 0.875rem;
  color: var(--color-text-muted, #4a5c7a);
  line-height: 1.5;
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.compat-warning {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.6rem 0.75rem;
  border-radius: var(--radius-sm, 0.25rem);
  background: color-mix(in srgb, var(--color-warning, #f59e0b) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--color-warning, #f59e0b) 40%, transparent);
  font-size: 0.82rem;
  color: var(--color-text, #1a2338);
  line-height: 1.45;
}

.compat-warning-icon {
  flex-shrink: 0;
  line-height: 1.45;
}

.btn-add-queue {
  align-self: flex-start;
}

.btn-add-queue-warn {
  background: var(--color-surface-raised, #e4ebf5);
  color: var(--color-text-secondary, #6b7a99);
  border: 1px solid var(--color-border, #d0d7e8);
}

/* ── Model cards (queue + downloads) ── */
.model-card {
  border: 1px solid var(--color-border, #a8b8d0);
  border-radius: var(--radius-md, 0.5rem);
  background: var(--color-surface-raised, #f5f7fc);
  padding: 0.75rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  box-shadow: var(--shadow-sm);
}

.model-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.model-repo-id {
  font-family: var(--font-mono, monospace);
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--color-text, #1a2338);
  word-break: break-all;
}

.model-meta {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.model-card-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  padding-top: 0.25rem;
}

/* ── Progress bar ── */
.progress-wrap {
  position: relative;
  height: 1.5rem;
  background: var(--color-surface-alt, #dde4f0);
  border-radius: var(--radius-full, 9999px);
  overflow: hidden;
}

.progress-bar {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: var(--color-accent, #c4732a);
  border-radius: var(--radius-full, 9999px);
  transition: width 300ms ease;
}

.progress-label {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--color-text, #1a2338);
  pointer-events: none;
}

.download-error {
  font-size: 0.85rem;
  color: var(--color-error, #c0392b);
  padding: 0.4rem 0.5rem;
  background: color-mix(in srgb, var(--color-error, #c0392b) 10%, transparent);
  border-radius: var(--radius-sm, 0.25rem);
}

/* ── Installed table ── */
.installed-table-wrap {
  overflow-x: auto;
}

.installed-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}

.installed-table th {
  text-align: left;
  padding: 0.4rem 0.6rem;
  color: var(--color-text-muted, #4a5c7a);
  font-size: 0.78rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  border-bottom: 1px solid var(--color-border, #a8b8d0);
  white-space: nowrap;
}

.installed-table td {
  padding: 0.55rem 0.6rem;
  border-bottom: 1px solid var(--color-border-light, #ccd5e6);
  vertical-align: middle;
}

.td-name {
  font-family: var(--font-mono, monospace);
  font-size: 0.85rem;
  word-break: break-all;
}

/* ── Badges ── */
.badge-group {
  display: flex;
  gap: 0.35rem;
  flex-wrap: wrap;
  align-items: center;
}

.badge {
  display: inline-flex;
  align-items: center;
  padding: 0.15rem 0.55rem;
  border-radius: var(--radius-full, 9999px);
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  white-space: nowrap;
}

.badge-success {
  background: color-mix(in srgb, var(--color-success, #3a7a32) 15%, transparent);
  color: var(--color-success, #3a7a32);
}

.badge-info {
  background: color-mix(in srgb, var(--color-info, #1e6091) 15%, transparent);
  color: var(--color-info, #1e6091);
}

.badge-accent {
  background: color-mix(in srgb, var(--color-accent, #c4732a) 15%, transparent);
  color: var(--color-accent, #c4732a);
}

.badge-error {
  background: color-mix(in srgb, var(--color-error, #c0392b) 15%, transparent);
  color: var(--color-error, #c0392b);
}

/* ── Chips ── */
.chip {
  display: inline-flex;
  align-items: center;
  padding: 0.15rem 0.5rem;
  border-radius: var(--radius-full, 9999px);
  font-size: 0.75rem;
  font-weight: 600;
  background: var(--color-surface-alt, #dde4f0);
  white-space: nowrap;
}

.chip-pipeline {
  color: var(--color-primary, #2d5a27);
  background: color-mix(in srgb, var(--color-primary, #2d5a27) 12%, var(--color-surface-alt, #dde4f0));
}

.chip-adapter {
  color: var(--color-accent, #c4732a);
  background: color-mix(in srgb, var(--color-accent, #c4732a) 12%, var(--color-surface-alt, #dde4f0));
}

/* ── Buttons ── */
.btn-primary, .btn-danger {
  padding: 0.4rem 0.9rem;
  border-radius: var(--radius-md, 0.5rem);
  font-size: 0.85rem;
  cursor: pointer;
  border: 1px solid;
  font-family: var(--font-body, sans-serif);
  transition: background var(--transition, 200ms ease), color var(--transition, 200ms ease);
}

.btn-sm {
  padding: 0.25rem 0.65rem;
  font-size: 0.8rem;
}

.btn-primary {
  border-color: var(--color-primary, #2d5a27);
  background: var(--color-primary, #2d5a27);
  color: var(--color-text-inverse, #eaeff8);
}

.btn-primary:hover:not(:disabled) {
  background: var(--color-primary-hover, #234820);
  border-color: var(--color-primary-hover, #234820);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-danger {
  border-color: var(--color-error, #c0392b);
  background: transparent;
  color: var(--color-error, #c0392b);
}

.btn-danger:hover {
  background: color-mix(in srgb, var(--color-error, #c0392b) 10%, transparent);
}

.btn-dismiss {
  border: none;
  background: transparent;
  color: var(--color-text-muted, #4a5c7a);
  cursor: pointer;
  font-size: 0.9rem;
  padding: 0.15rem 0.4rem;
  border-radius: var(--radius-sm, 0.25rem);
  flex-shrink: 0;
  transition: color var(--transition, 200ms ease), background var(--transition, 200ms ease);
}

.btn-dismiss:hover {
  color: var(--color-error, #c0392b);
  background: color-mix(in srgb, var(--color-error, #c0392b) 10%, transparent);
}

/* ── Responsive ── */
@media (max-width: 480px) {
  .lookup-row {
    flex-direction: column;
  }

  .lookup-input {
    width: 100%;
  }

  .btn-primary:not(.btn-sm) {
    width: 100%;
  }

  .installed-table th:nth-child(3),
  .installed-table td:nth-child(3) {
    display: none;  /* hide Adapter column on very narrow screens */
  }
}
</style>
