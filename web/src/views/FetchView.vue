<template>
  <div class="fetch-view">
    <h1 class="page-title">📥 Fetch Emails</h1>

    <!-- No accounts -->
    <div v-if="!loading && accounts.length === 0" class="empty-notice">
      No accounts configured.
      <RouterLink to="/settings" class="link">Go to Settings →</RouterLink>
    </div>

    <template v-else>
      <!-- Account selection -->
      <section class="section">
        <h2 class="section-title">Accounts</h2>
        <label
          v-for="acc in accounts"
          :key="acc.name"
          class="account-check"
        >
          <input v-model="selectedAccounts" type="checkbox" :value="acc.name" />
          {{ acc.name || acc.username }}
        </label>
      </section>

      <!-- Standard fetch options -->
      <section class="section">
        <h2 class="section-title">Options</h2>

        <label class="field field-inline">
          <span class="field-label">Days back</span>
          <input v-model.number="daysBack" type="range" min="7" max="365" class="slider" />
          <span class="field-value">{{ daysBack }}</span>
        </label>

        <label class="field field-inline">
          <span class="field-label">Max per account</span>
          <input v-model.number="limitPerAccount" type="number" min="10" max="2000" class="field-num" />
        </label>
      </section>

      <!-- Fetch button -->
      <button
        class="btn-primary btn-fetch"
        :disabled="fetching || selectedAccounts.length === 0"
        @click="startFetch"
      >
        {{ fetching ? 'Fetching…' : '📥 Fetch from IMAP' }}
      </button>

      <!-- Progress bars -->
      <div v-if="progress.length > 0" class="progress-section">
        <div v-for="p in progress" :key="p.account" class="progress-row">
          <span class="progress-name">{{ p.account }}</span>
          <div class="progress-track">
            <div
              class="progress-fill"
              :class="{ done: p.done, error: p.error }"
              :style="{ width: `${p.pct}%` }"
            />
          </div>
          <span class="progress-label">{{ p.label }}</span>
        </div>

        <div v-if="completeMsg" class="complete-msg">{{ completeMsg }}</div>
      </div>

      <!-- Targeted fetch (collapsible) -->
      <details class="targeted-section">
        <summary class="targeted-summary">🎯 Targeted fetch (by date range + keyword)</summary>
        <div class="targeted-fields">
          <div class="field-row">
            <label class="field field-grow">
              <span>From</span>
              <input v-model="targetSince" type="date" />
            </label>
            <label class="field field-grow">
              <span>To</span>
              <input v-model="targetBefore" type="date" />
            </label>
          </div>
          <label class="field">
            <span>Search term (optional)</span>
            <input v-model="targetTerm" type="text" placeholder="e.g. interview" />
          </label>
          <label class="field">
            <span>Match field</span>
            <select v-model="targetField" class="field-select">
              <option value="either">Subject or From</option>
              <option value="subject">Subject only</option>
              <option value="from">From only</option>
              <option value="none">No filter (date range only)</option>
            </select>
          </label>
          <button class="btn-secondary" :disabled="fetching" @click="startTargetedFetch">
            🎯 Targeted fetch
          </button>
          <p class="targeted-note">
            Targeted fetch uses the same SSE stream — progress appears above.
          </p>
        </div>
      </details>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { useApiFetch, useApiSSE } from '../composables/useApi'

interface Account { name: string; username: string; days_back: number }

interface ProgressRow {
  account: string
  pct: number
  label: string
  done: boolean
  error: boolean
}

const accounts         = ref<Account[]>([])
const selectedAccounts = ref<string[]>([])
const daysBack         = ref(90)
const limitPerAccount  = ref(150)
const loading          = ref(true)
const fetching         = ref(false)
const progress         = ref<ProgressRow[]>([])
const completeMsg      = ref('')

// Targeted fetch
const targetSince  = ref('')
const targetBefore = ref('')
const targetTerm   = ref('')
const targetField  = ref('either')

async function loadConfig() {
  loading.value = true
  const { data } = await useApiFetch<{ accounts: Account[]; max_per_account: number }>('/api/config')
  loading.value = false
  if (data) {
    accounts.value         = data.accounts
    selectedAccounts.value = data.accounts.map(a => a.name)
    limitPerAccount.value  = data.max_per_account
  }
}

function initProgress() {
  progress.value = selectedAccounts.value.map(name => ({
    account: name, pct: 0, label: 'waiting…', done: false, error: false,
  }))
  completeMsg.value = ''
}

function startFetch() {
  if (fetching.value || selectedAccounts.value.length === 0) return
  fetching.value = true
  initProgress()

  const params = new URLSearchParams({
    accounts:  selectedAccounts.value.join(','),
    days_back: String(daysBack.value),
    limit:     String(limitPerAccount.value),
    mode:      'wide',
  })

  useApiSSE(
    `/api/fetch/stream?${params}`,
    (data) => handleEvent(data as Record<string, unknown>),
    () => { fetching.value = false },
    () => { fetching.value = false },
  )
}

function startTargetedFetch() {
  if (fetching.value || selectedAccounts.value.length === 0) return
  fetching.value = true
  initProgress()

  const params = new URLSearchParams({
    accounts:  selectedAccounts.value.join(','),
    days_back: String(daysBack.value),
    limit:     String(limitPerAccount.value),
    mode:      'targeted',
    since:     targetSince.value,
    before:    targetBefore.value,
    term:      targetTerm.value,
    field:     targetField.value,
  })

  useApiSSE(
    `/api/fetch/stream?${params}`,
    (data) => handleEvent(data as Record<string, unknown>),
    () => { fetching.value = false },
    () => { fetching.value = false },
  )
}

function handleEvent(data: Record<string, unknown>) {
  const type    = data.type as string
  const account = data.account as string | undefined

  const row = account ? progress.value.find(p => p.account === account) : null

  if (type === 'start' && row) {
    row.label = `0 / ${data.total_uids} found`
    row.pct   = 2  // show a sliver immediately
  } else if (type === 'progress' && row) {
    const total = (data.total_uids as number) || 1
    const fetched = (data.fetched as number) || 0
    row.pct   = Math.round((fetched / total) * 95)
    row.label = `${fetched} fetched…`
  } else if (type === 'done' && row) {
    row.pct   = 100
    row.done  = true
    row.label = `${data.added} added, ${data.skipped} skipped`
  } else if (type === 'error' && row) {
    row.error = true
    row.label = String(data.message || 'Error')
  } else if (type === 'complete') {
    completeMsg.value =
      `Done — ${data.total_added} new email(s) added · Queue: ${data.queue_size}`
  }
}

onMounted(loadConfig)
</script>

<style scoped>
.fetch-view {
  max-width: 640px;
  margin: 0 auto;
  padding: 1.5rem 1rem 4rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.page-title {
  font-family: var(--font-display, var(--font-body, sans-serif));
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--app-primary, #2A6080);
}

.section {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.section-title {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--color-text-secondary, #6b7a99);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding-bottom: 0.25rem;
  border-bottom: 1px solid var(--color-border, #d0d7e8);
}

.account-check {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.9rem;
  cursor: pointer;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.88rem;
}

.field-inline {
  flex-direction: row;
  align-items: center;
  gap: 0.75rem;
}

.field-label {
  min-width: 120px;
  color: var(--color-text-secondary, #6b7a99);
  font-size: 0.85rem;
}

.field-value {
  min-width: 32px;
  font-family: var(--font-mono, monospace);
  font-size: 0.85rem;
}

.slider {
  flex: 1;
  accent-color: var(--app-primary, #2A6080);
}

.field-num {
  width: 90px;
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.375rem;
  font-size: 0.9rem;
  background: var(--color-surface, #fff);
  color: var(--color-text, #1a2338);
}

.btn-primary {
  padding: 0.6rem 1.5rem;
  border-radius: 0.5rem;
  border: none;
  background: var(--app-primary, #2A6080);
  color: #fff;
  font-size: 1rem;
  font-family: var(--font-body, sans-serif);
  cursor: pointer;
  align-self: flex-start;
  transition: background 0.15s;
}

.btn-primary:hover:not(:disabled) { background: var(--app-primary-dark, #1d4d65); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-fetch { min-width: 200px; }

.progress-section {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.progress-row {
  display: grid;
  grid-template-columns: 10rem 1fr 8rem;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
}

.progress-name {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.progress-track {
  height: 12px;
  background: var(--color-surface-raised, #e4ebf5);
  border-radius: 99px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--app-primary, #2A6080);
  border-radius: 99px;
  transition: width 0.3s ease;
}

.progress-fill.done  { background: #4CAF50; }
.progress-fill.error { background: var(--color-error, #ef4444); }

.progress-label {
  font-size: 0.78rem;
  color: var(--color-text-secondary, #6b7a99);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.complete-msg {
  font-size: 0.9rem;
  font-weight: 600;
  color: #155724;
  background: #d4edda;
  padding: 0.5rem 0.75rem;
  border-radius: 0.375rem;
  margin-top: 0.5rem;
}

.targeted-section {
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  overflow: hidden;
}

.targeted-summary {
  padding: 0.6rem 0.75rem;
  background: var(--color-surface-raised, #e4ebf5);
  cursor: pointer;
  font-size: 0.88rem;
  font-weight: 600;
  user-select: none;
}

.targeted-fields {
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  background: var(--color-surface, #fff);
}

.field-row {
  display: flex;
  gap: 0.5rem;
}

.field-grow { flex: 1; }

.field select,
.field input[type="date"],
.field input[type="text"] {
  padding: 0.4rem 0.5rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.375rem;
  background: var(--color-surface, #fff);
  color: var(--color-text, #1a2338);
  font-size: 0.88rem;
}

.field-select { width: 100%; }

.btn-secondary {
  padding: 0.4rem 0.9rem;
  border-radius: 0.375rem;
  border: 1px solid var(--color-border, #d0d7e8);
  background: var(--color-surface, #fff);
  color: var(--color-text, #1a2338);
  font-size: 0.85rem;
  cursor: pointer;
  font-family: var(--font-body, sans-serif);
  align-self: flex-start;
  transition: background 0.15s;
}

.btn-secondary:hover { background: var(--color-surface-raised, #e4ebf5); }
.btn-secondary:disabled { opacity: 0.5; cursor: not-allowed; }

.targeted-note {
  font-size: 0.78rem;
  color: var(--color-text-secondary, #6b7a99);
}

.empty-notice {
  color: var(--color-text-secondary, #6b7a99);
  font-size: 0.9rem;
  padding: 1rem;
  border: 1px dashed var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
}

.link {
  color: var(--app-primary, #2A6080);
  text-decoration: underline;
}
</style>
