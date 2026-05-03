<template>
  <div class="train-jobs-view">
    <header class="view-header">
      <h1 class="page-title">🧠 Training Jobs</h1>
    </header>

    <!-- New Job form -->
    <section class="section">
      <h2 class="section-title">New Job</h2>
      <form class="new-job-form" @submit.prevent="submitJob">
        <div class="form-row">
          <label class="form-label" for="job-type">Type</label>
          <select
            id="job-type"
            v-model="form.type"
            class="job-type-select form-control"
          >
            <option value="classifier">classifier</option>
            <option value="llm-sft">llm-sft</option>
          </select>
        </div>

        <div class="form-row">
          <label class="form-label" for="model-key">Model key</label>
          <input
            id="model-key"
            v-model.trim="form.model_key"
            type="text"
            class="model-key-input form-control"
            placeholder="e.g. microsoft/deberta-v3-small"
            autocomplete="off"
          />
        </div>

        <div class="form-row">
          <label class="form-label" for="job-config">Config JSON <span class="form-hint">(optional)</span></label>
          <textarea
            id="job-config"
            v-model="form.config_raw"
            class="config-textarea form-control"
            rows="4"
            placeholder='{"learning_rate": 2e-5}'
          />
        </div>

        <div v-if="submitError" class="error-notice" role="alert">{{ submitError }}</div>

        <button
          type="submit"
          class="submit-job-btn btn-primary"
          :disabled="submitting || !form.model_key"
          @click.prevent="submitJob"
        >
          {{ submitting ? 'Queuing…' : 'Queue Job' }}
        </button>
      </form>
    </section>

    <!-- Job queue table -->
    <section class="section">
      <h2 class="section-title">Job Queue</h2>

      <div v-if="loadError" class="error-notice" role="alert">
        {{ loadError }}
        <button class="btn-retry" @click="loadJobs">Retry</button>
      </div>

      <div v-else-if="jobs.length === 0" class="empty-notice">
        No training jobs yet.
      </div>

      <div v-else class="jobs-table-wrap">
        <table class="jobs-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Type</th>
              <th>Model</th>
              <th>Status</th>
              <th>Created</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="job in jobs" :key="job.id">
              <td class="td-id" :title="job.id">{{ job.id.slice(0, 8) }}</td>
              <td>
                <span class="type-chip">{{ job.type }}</span>
              </td>
              <td class="td-model">{{ job.model_key }}</td>
              <td>
                <span class="status-pill" :class="`status-${job.status}`">{{ job.status }}</span>
              </td>
              <td class="td-date">{{ formatDate(job.created_at) }}</td>
              <td class="td-actions">
                <button
                  v-if="job.status === 'running'"
                  class="view-log-btn btn-sm"
                  @click="openLog(job.id)"
                >
                  View Log
                </button>
                <button
                  v-if="job.status === 'queued' || job.status === 'running'"
                  class="cancel-btn btn-sm btn-danger-sm"
                  :disabled="cancellingId === job.id"
                  @click="cancelJob(job.id)"
                >
                  {{ cancellingId === job.id ? '…' : 'Cancel' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="cancelError" class="error-notice" role="alert">{{ cancelError }}</div>
    </section>

    <!-- Log panel (SSE) -->
    <section v-if="logJobId" class="section log-section">
      <div class="log-header">
        <h2 class="section-title">Log — {{ logJobId.slice(0, 8) }}</h2>
        <button class="btn-close-log" @click="closeLog">✕ Close</button>
      </div>
      <div class="log-panel" ref="logPanelEl">
        <div
          v-for="(line, i) in logLines"
          :key="i"
          class="log-line"
        >{{ line }}</div>
        <div v-if="logLines.length === 0" class="log-line log-muted">Connecting…</div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onUnmounted } from 'vue'
import { useApiSSE } from '../composables/useApi'

interface TrainJob {
  id: string
  type: 'classifier' | 'llm-sft'
  model_key: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  created_at: string
  config: Record<string, unknown> | null
}

const jobs        = ref<TrainJob[]>([])
const loadError   = ref<string | null>(null)
const submitError = ref<string | null>(null)
const submitting  = ref(false)
const cancellingId = ref<string | null>(null)
const cancelError  = ref<string | null>(null)

const form = ref({
  type: 'classifier' as 'classifier' | 'llm-sft',
  model_key: '',
  config_raw: '',
})

// ── Log panel state ──
const logJobId   = ref<string | null>(null)
const logLines   = ref<string[]>([])
const logPanelEl = ref<HTMLElement | null>(null)
let   closeSSE: (() => void) | null = null

// ── Data loading ──

async function loadJobs() {
  loadError.value = null
  try {
    const res = await fetch('/api/train/jobs')
    if (!res.ok) { loadError.value = `Failed to load jobs (HTTP ${res.status}).`; return }
    const data = await res.json() as { jobs: TrainJob[] }
    jobs.value = data.jobs ?? []
  } catch {
    loadError.value = 'Network error loading jobs.'
  }
}

// ── Submit ──

async function submitJob() {
  if (!form.value.model_key) return
  submitError.value = null
  submitting.value = true

  let config: Record<string, unknown> | null = null
  if (form.value.config_raw.trim()) {
    try {
      config = JSON.parse(form.value.config_raw) as Record<string, unknown>
    } catch {
      submitError.value = 'Config JSON is not valid. Fix it before submitting.'
      submitting.value = false
      return
    }
  }

  try {
    const res = await fetch('/api/train/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type:      form.value.type,
        model_key: form.value.model_key,
        config_json: config,
      }),
    })
    if (!res.ok) {
      const detail = await res.text().catch(() => '')
      submitError.value = `Failed to queue job (HTTP ${res.status})${detail ? `: ${detail}` : '.'}`
      return
    }
    const newJob = await res.json() as TrainJob
    jobs.value = [newJob, ...jobs.value]
    form.value = { type: 'classifier', model_key: '', config_raw: '' }
  } catch {
    submitError.value = 'Network error submitting job.'
  } finally {
    submitting.value = false
  }
}

// ── Cancel ──

async function cancelJob(id: string) {
  cancellingId.value = id
  cancelError.value = null
  try {
    const res = await fetch(`/api/train/jobs/${encodeURIComponent(id)}/cancel`, { method: 'DELETE' })
    if (res.ok) {
      jobs.value = jobs.value.map(j =>
        j.id === id ? { ...j, status: 'cancelled' as const } : j
      )
    } else {
      cancelError.value = `Failed to cancel job (HTTP ${res.status}).`
    }
  } catch {
    cancelError.value = 'Network error cancelling job.'
  } finally {
    cancellingId.value = null
  }
}

// ── Log SSE ──

function openLog(id: string) {
  closeLog()
  logJobId.value = id
  logLines.value = []

  closeSSE = useApiSSE(
    `/api/train/jobs/${encodeURIComponent(id)}/run`,
    (data) => {
      if (data.type === 'log' || data.type === 'progress' || data.type === 'error') {
        logLines.value = [...logLines.value, String(data.message ?? '')]
        nextTick(() => {
          if (logPanelEl.value) {
            logPanelEl.value.scrollTop = logPanelEl.value.scrollHeight
          }
        })
      }
      if (data.type === 'error') {
        logLines.value = [...logLines.value, '--- stream ended with error ---']
        nextTick(() => {
          if (logPanelEl.value) {
            logPanelEl.value.scrollTop = logPanelEl.value.scrollHeight
          }
        })
      }
    },
    () => {
      logLines.value = [...logLines.value, '--- stream complete ---']
    },
    () => {
      logLines.value = [...logLines.value, '--- connection lost ---']
    },
  )
}

function closeLog() {
  closeSSE?.()
  closeSSE = null
  logJobId.value = null
  logLines.value = []
}

// ── Helpers ──

function formatDate(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })
}

// ── Lifecycle ──

loadJobs()

onUnmounted(() => {
  closeSSE?.()
})
</script>

<style scoped>
.train-jobs-view {
  max-width: 860px;
  margin: 0 auto;
  padding: 1.5rem 1rem 4rem;
  display: flex;
  flex-direction: column;
  gap: 2rem;
}

.view-header { display: flex; align-items: center; }

.page-title {
  font-family: var(--font-display, var(--font-body, sans-serif));
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--app-primary, #2A6080);
  margin: 0;
}

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
  margin: 0;
}

.new-job-form {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  max-width: 480px;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.form-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--color-text-muted, #4a5c7a);
}

.form-hint {
  font-weight: 400;
  font-size: 0.78rem;
}

.form-control {
  padding: 0.45rem 0.65rem;
  border: 1px solid var(--color-border, #a8b8d0);
  border-radius: var(--radius-md, 0.5rem);
  background: var(--color-surface-raised, #f5f7fc);
  color: var(--color-text, #1a2338);
  font-size: 0.9rem;
  font-family: var(--font-body, sans-serif);
}

.form-control:focus {
  outline: 2px solid var(--app-primary, #2A6080);
  outline-offset: -1px;
}

.config-textarea {
  resize: vertical;
  font-family: var(--font-mono, monospace);
  font-size: 0.82rem;
}

.btn-primary {
  padding: 0.4rem 0.9rem;
  border-radius: var(--radius-md, 0.5rem);
  border: 1px solid var(--app-primary, #2A6080);
  background: var(--app-primary, #2A6080);
  color: #fff;
  font-size: 0.88rem;
  font-family: var(--font-body, sans-serif);
  cursor: pointer;
  align-self: flex-start;
  transition: opacity 0.15s;
}

.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary:not(:disabled):hover { opacity: 0.85; }

.btn-sm {
  padding: 0.2rem 0.55rem;
  font-size: 0.78rem;
  border-radius: 0.3rem;
  cursor: pointer;
  font-family: var(--font-body, sans-serif);
  border: 1px solid;
  transition: background 0.1s;
}

.view-log-btn {
  border-color: var(--color-info, #1e6091);
  background: transparent;
  color: var(--color-info, #1e6091);
}

.view-log-btn:hover {
  background: color-mix(in srgb, var(--color-info, #1e6091) 10%, transparent);
}

.btn-danger-sm {
  border-color: var(--color-error, #c0392b);
  background: transparent;
  color: var(--color-error, #c0392b);
}

.btn-danger-sm:hover:not(:disabled) {
  background: color-mix(in srgb, var(--color-error, #c0392b) 10%, transparent);
}

.btn-danger-sm:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-retry {
  margin-left: 0.5rem;
  padding: 0.2rem 0.55rem;
  border-radius: 0.25rem;
  border: 1px solid var(--color-error, #c0392b);
  background: transparent;
  color: var(--color-error, #c0392b);
  cursor: pointer;
  font-size: 0.82rem;
}

.error-notice {
  padding: 0.6rem 0.8rem;
  background: color-mix(in srgb, var(--color-error, #c0392b) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--color-error, #c0392b) 30%, transparent);
  border-radius: var(--radius-md, 0.5rem);
  color: var(--color-error, #c0392b);
  font-size: 0.88rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.empty-notice {
  color: var(--color-text-muted, #4a5c7a);
  font-size: 0.9rem;
  padding: 0.75rem;
  border: 1px dashed var(--color-border, #a8b8d0);
  border-radius: var(--radius-md, 0.5rem);
}

.jobs-table-wrap { overflow-x: auto; }

.jobs-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}

.jobs-table th {
  text-align: left;
  padding: 0.4rem 0.6rem;
  background: var(--color-surface-raised, #f5f7fc);
  color: var(--color-text-muted, #4a5c7a);
  font-size: 0.78rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  border-bottom: 1px solid var(--color-border, #a8b8d0);
  white-space: nowrap;
}

.jobs-table td {
  padding: 0.5rem 0.6rem;
  border-bottom: 1px solid var(--color-border-light, #ccd5e6);
  vertical-align: middle;
}

.td-id {
  font-family: var(--font-mono, monospace);
  font-size: 0.78rem;
  color: var(--color-text-muted, #4a5c7a);
}

.td-model {
  font-family: var(--font-mono, monospace);
  font-size: 0.82rem;
  word-break: break-all;
}

.td-date {
  font-size: 0.8rem;
  color: var(--color-text-muted, #4a5c7a);
  white-space: nowrap;
}

.td-actions {
  display: flex;
  gap: 0.35rem;
  align-items: center;
  flex-wrap: wrap;
}

.status-pill {
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.15rem 0.45rem;
  border-radius: var(--radius-full, 9999px);
  white-space: nowrap;
}

.status-queued    { background: var(--color-surface-alt, #dde4f0); color: var(--color-text-muted, #4a5c7a); }
.status-running   { background: color-mix(in srgb, var(--color-info, #1e6091) 15%, transparent); color: var(--color-info, #1e6091); }
.status-completed { background: color-mix(in srgb, var(--color-success, #3a7a32) 15%, transparent); color: var(--color-success, #3a7a32); }
.status-failed    { background: color-mix(in srgb, var(--color-error, #c0392b) 15%, transparent); color: var(--color-error, #c0392b); }
.status-cancelled { background: color-mix(in srgb, var(--color-warning, #d4891a) 15%, transparent); color: var(--color-warning, #d4891a); }

.type-chip {
  font-size: 0.72rem;
  font-family: var(--font-mono, monospace);
  padding: 0.1rem 0.4rem;
  border-radius: 0.25rem;
  background: var(--color-surface-alt, #dde4f0);
  color: var(--color-text, #1a2338);
}

.log-section { gap: 0.5rem; }

.log-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.btn-close-log {
  background: transparent;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.25rem;
  cursor: pointer;
  font-size: 0.8rem;
  padding: 0.2rem 0.5rem;
  color: var(--color-text-muted, #4a5c7a);
  transition: background 0.1s;
}

.btn-close-log:hover { background: var(--color-surface-raised, #e4ebf5); }

.log-panel {
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  max-height: 320px;
  overflow-y: auto;
  padding: 0.5rem 0.75rem;
  background: var(--color-surface, #f0f4fc);
  font-family: var(--font-mono, monospace);
  font-size: 0.78rem;
}

.log-line {
  color: var(--color-text, #1a2338);
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}

.log-muted { color: var(--color-text-muted, #4a5c7a); }

@media (max-width: 560px) {
  .jobs-table th:nth-child(4),
  .jobs-table td:nth-child(4),
  .jobs-table th:nth-child(5),
  .jobs-table td:nth-child(5) {
    display: none;
  }
}
</style>
