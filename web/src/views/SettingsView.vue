<template>
  <div class="settings-view">
    <h1 class="page-title">⚙️ Settings</h1>

    <!-- IMAP Accounts -->
    <section class="section">
      <h2 class="section-title">IMAP Accounts</h2>

      <div v-if="accounts.length === 0" class="empty-notice">
        No accounts configured yet. Click <strong>➕ Add account</strong> to get started.
      </div>

      <details
        v-for="(acc, i) in accounts"
        :key="i"
        class="account-panel"
        open
      >
        <summary class="account-summary">
          {{ acc.name || acc.username || `Account ${i + 1}` }}
        </summary>

        <div class="account-fields">
          <label class="field">
            <span>Display name</span>
            <input v-model="acc.name" type="text" placeholder="e.g. Gmail Personal" />
          </label>

          <div class="field-row">
            <label class="field field-grow">
              <span>IMAP host</span>
              <input v-model="acc.host" type="text" placeholder="imap.gmail.com" />
            </label>
            <label class="field field-short">
              <span>Port</span>
              <input v-model.number="acc.port" type="number" min="1" max="65535" />
            </label>
            <label class="field field-check">
              <span>SSL</span>
              <input v-model="acc.use_ssl" type="checkbox" />
            </label>
          </div>

          <label class="field">
            <span>Username</span>
            <input v-model="acc.username" type="text" autocomplete="off" />
          </label>

          <label class="field">
            <span>Password</span>
            <div class="password-wrap">
              <input
                v-model="acc.password"
                :type="showPassword[i] ? 'text' : 'password'"
                autocomplete="new-password"
              />
              <button type="button" class="btn-icon" @click="togglePassword(i)">
                {{ showPassword[i] ? '🙈' : '👁' }}
              </button>
            </div>
          </label>

          <div class="field-row">
            <label class="field field-grow">
              <span>Folder</span>
              <input v-model="acc.folder" type="text" placeholder="INBOX" />
            </label>
            <label class="field field-short">
              <span>Days back</span>
              <input v-model.number="acc.days_back" type="number" min="1" max="3650" />
            </label>
          </div>

          <div class="account-actions">
            <button class="btn-secondary" @click="testAccount(i)">🔌 Test connection</button>
            <button class="btn-danger" @click="removeAccount(i)">🗑 Remove</button>
            <span
              v-if="testResults[i]"
              class="test-result"
              :class="testResults[i]?.ok ? 'result-ok' : 'result-err'"
            >
              {{ testResults[i]?.message }}
            </span>
          </div>
        </div>
      </details>

      <button class="btn-secondary btn-add" @click="addAccount">➕ Add account</button>
    </section>

    <!-- Global settings -->
    <section class="section">
      <h2 class="section-title">Global</h2>
      <label class="field field-inline">
        <span>Max emails per account per fetch</span>
        <input v-model.number="maxPerAccount" type="number" min="10" max="2000" class="field-num" />
      </label>
    </section>

    <!-- Display settings -->
    <section class="section">
      <h2 class="section-title">Display</h2>
      <label class="field field-inline">
        <input v-model="richMotion" type="checkbox" @change="onMotionChange" />
        <span>Rich animations &amp; haptic feedback</span>
      </label>
      <label class="field field-inline">
        <input v-model="keyHints" type="checkbox" @change="onKeyHintsChange" />
        <span>Show keyboard shortcut hints on label buttons</span>
      </label>
    </section>

    <!-- cf-orch SFT Integration section -->
    <section class="section">
      <h2 class="section-title">cf-orch Integration</h2>
      <p class="section-desc">
        Import SFT (supervised fine-tuning) candidates from cf-orch benchmark runs.
      </p>

      <div class="field-row">
        <label class="field field-grow">
          <span>bench_results_dir</span>
          <input
            id="bench-results-dir"
            v-model="benchResultsDir"
            type="text"
            placeholder="/path/to/circuitforge-orch/scripts/bench_results"
          />
        </label>
      </div>

      <div class="account-actions">
        <button class="btn-primary" @click="saveSftConfig">Save</button>
        <button class="btn-secondary" @click="scanRuns">Scan for runs</button>
        <span v-if="saveStatus" class="save-status">{{ saveStatus }}</span>
      </div>

      <table v-if="runs.length > 0" class="runs-table">
        <thead>
          <tr>
            <th>Timestamp</th>
            <th>Candidates</th>
            <th>Imported</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="run in runs" :key="run.run_id">
            <td>{{ run.timestamp }}</td>
            <td>{{ run.candidate_count }}</td>
            <td>{{ run.already_imported ? '✓' : '—' }}</td>
            <td>
              <button
                class="btn-import"
                :disabled="run.already_imported || importingRunId === run.run_id"
                @click="importRun(run.run_id)"
              >
                {{ importingRunId === run.run_id ? 'Importing…' : 'Import' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="importResult" class="import-result">
        Imported {{ importResult.imported }}, skipped {{ importResult.skipped }}.
      </div>
    </section>

    <!-- Save / Reload -->
    <div class="save-bar">
      <button class="btn-primary" :disabled="saving" @click="save">
        {{ saving ? 'Saving…' : '💾 Save' }}
      </button>
      <button class="btn-secondary" @click="reload">↩ Reload from disk</button>
      <span v-if="saveMsg" class="save-msg" :class="saveOk ? 'msg-ok' : 'msg-err'">
        {{ saveMsg }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useApiFetch } from '../composables/useApi'

interface Account {
  name: string; host: string; port: number; use_ssl: boolean
  username: string; password: string; folder: string; days_back: number
}

const accounts      = ref<Account[]>([])
const maxPerAccount = ref(500)
const showPassword  = ref<boolean[]>([])
const testResults   = ref<Array<{ ok: boolean; message: string } | null>>([])
const saving        = ref(false)
const saveMsg       = ref('')
const saveOk        = ref(true)
const richMotion    = ref(localStorage.getItem('cf-avocet-rich-motion') !== 'false')
const keyHints      = ref(localStorage.getItem('cf-avocet-key-hints') !== 'false')

// SFT integration state
const benchResultsDir = ref('')
const runs            = ref<Array<{ run_id: string; timestamp: string; candidate_count: number; already_imported: boolean }>>([])
const importingRunId  = ref<string | null>(null)
const importResult    = ref<{ imported: number; skipped: number } | null>(null)
const saveStatus      = ref('')

async function loadSftConfig() {
  try {
    const res = await fetch('/api/sft/config')
    if (res.ok) {
      const data = await res.json()
      benchResultsDir.value = data.bench_results_dir ?? ''
    }
  } catch {
    // non-fatal — leave field empty
  }
}

async function saveSftConfig() {
  saveStatus.value = 'Saving…'
  try {
    const res = await fetch('/api/sft/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bench_results_dir: benchResultsDir.value }),
    })
    saveStatus.value = res.ok ? 'Saved.' : 'Error saving.'
  } catch {
    saveStatus.value = 'Error saving.'
  }
  setTimeout(() => { saveStatus.value = '' }, 2000)
}

async function scanRuns() {
  try {
    const res = await fetch('/api/sft/runs')
    if (res.ok) runs.value = await res.json()
  } catch { /* ignore */ }
}

async function importRun(runId: string) {
  importingRunId.value = runId
  importResult.value = null
  try {
    const res = await fetch('/api/sft/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_id: runId }),
    })
    if (res.ok) {
      importResult.value = await res.json()
      scanRuns()  // refresh already_imported flags
    }
  } catch { /* ignore */ }
  importingRunId.value = null
}

async function reload() {
  const { data } = await useApiFetch<{ accounts: Account[]; max_per_account: number }>('/api/config')
  if (data) {
    accounts.value      = data.accounts
    maxPerAccount.value = data.max_per_account
    showPassword.value  = new Array(data.accounts.length).fill(false)
    testResults.value   = new Array(data.accounts.length).fill(null)
  }
}

async function save() {
  saving.value = true
  saveMsg.value = ''
  const { error } = await useApiFetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ accounts: accounts.value, max_per_account: maxPerAccount.value }),
  })
  saving.value = false
  if (error) {
    saveOk.value  = false
    saveMsg.value = '✗ Save failed'
  } else {
    saveOk.value  = true
    saveMsg.value = '✓ Saved'
    setTimeout(() => { saveMsg.value = '' }, 3000)
  }
}

async function testAccount(i: number) {
  testResults.value[i] = null
  const { data } = await useApiFetch<{ ok: boolean; message: string; count: number | null }>(
    '/api/accounts/test',
    { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account: accounts.value[i] }) },
  )
  if (data) {
    testResults.value[i] = { ok: data.ok, message: data.message }
    // Easter egg: > 5000 messages
    if (data.ok && data.count !== null && data.count > 5000) {
      setTimeout(() => {
        if (testResults.value[i]?.ok) {
          testResults.value[i] = { ok: true, message: `${data.message} That's a lot of email 📬` }
        }
      }, 800)
    }
  }
}

function addAccount() {
  accounts.value.push({
    name: '', host: 'imap.gmail.com', port: 993, use_ssl: true,
    username: '', password: '', folder: 'INBOX', days_back: 90,
  })
  showPassword.value.push(false)
  testResults.value.push(null)
}

function removeAccount(i: number) {
  accounts.value.splice(i, 1)
  showPassword.value.splice(i, 1)
  testResults.value.splice(i, 1)
}

function togglePassword(i: number) {
  showPassword.value[i] = !showPassword.value[i]
}

function onMotionChange() {
  localStorage.setItem('cf-avocet-rich-motion', String(richMotion.value))
}

function onKeyHintsChange() {
  localStorage.setItem('cf-avocet-key-hints', String(keyHints.value))
  document.documentElement.classList.toggle('hide-key-hints', !keyHints.value)
}

onMounted(() => {
  reload()
  loadSftConfig()
})
</script>

<style scoped>
.settings-view {
  max-width: 680px;
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
  color: var(--app-primary, #2A6080);
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
  border-bottom: 1px solid var(--color-border, #d0d7e8);
}

.account-panel {
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  overflow: hidden;
}

.account-summary {
  padding: 0.6rem 0.75rem;
  background: var(--color-surface-raised, #e4ebf5);
  cursor: pointer;
  font-weight: 600;
  font-size: 0.9rem;
  user-select: none;
}

.account-fields {
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  background: var(--color-surface, #fff);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  font-size: 0.85rem;
}

.field span:first-child {
  color: var(--color-text-secondary, #6b7a99);
  font-size: 0.78rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.field input[type="text"],
.field input[type="password"],
.field input[type="number"] {
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.375rem;
  background: var(--color-surface, #fff);
  color: var(--color-text, #1a2338);
  font-size: 0.9rem;
  font-family: var(--font-body, sans-serif);
}

.field-row {
  display: flex;
  gap: 0.5rem;
  align-items: flex-end;
}

.field-grow { flex: 1; }
.field-short { width: 80px; }
.field-check { width: 48px; align-items: center; }

.field-inline {
  flex-direction: row;
  align-items: center;
  gap: 0.5rem;
}

.field-num {
  width: 100px;
}

.password-wrap {
  display: flex;
  gap: 0.4rem;
}

.password-wrap input {
  flex: 1;
}

.btn-icon {
  border: 1px solid var(--color-border, #d0d7e8);
  background: transparent;
  border-radius: 0.375rem;
  padding: 0.3rem 0.5rem;
  cursor: pointer;
  font-size: 0.9rem;
}

.account-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  padding-top: 0.25rem;
}

.test-result {
  font-size: 0.8rem;
  padding: 0.2rem 0.5rem;
  border-radius: 0.25rem;
}

.result-ok  { background: #d4edda; color: #155724; }
.result-err { background: #f8d7da; color: #721c24; }

.btn-add { margin-top: 0.25rem; }

.btn-primary, .btn-secondary, .btn-danger {
  padding: 0.4rem 0.9rem;
  border-radius: 0.375rem;
  font-size: 0.85rem;
  cursor: pointer;
  border: 1px solid;
  font-family: var(--font-body, sans-serif);
  transition: background 0.15s, color 0.15s;
}

.btn-primary {
  border-color: var(--app-primary, #2A6080);
  background: var(--app-primary, #2A6080);
  color: #fff;
}

.btn-primary:hover:not(:disabled) {
  background: var(--app-primary-dark, #1d4d65);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  border-color: var(--color-border, #d0d7e8);
  background: var(--color-surface, #fff);
  color: var(--color-text, #1a2338);
}

.btn-secondary:hover {
  background: var(--color-surface-raised, #e4ebf5);
}

.btn-danger {
  border-color: var(--color-error, #ef4444);
  background: transparent;
  color: var(--color-error, #ef4444);
}

.btn-danger:hover {
  background: #fef2f2;
}

.save-bar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.save-msg {
  font-size: 0.85rem;
  padding: 0.2rem 0.6rem;
  border-radius: 0.25rem;
}

.msg-ok  { background: #d4edda; color: #155724; }
.msg-err { background: #f8d7da; color: #721c24; }

.empty-notice {
  color: var(--color-text-secondary, #6b7a99);
  font-size: 0.9rem;
  padding: 0.75rem;
  border: 1px dashed var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
}

.section-desc {
  color: var(--color-text-secondary, #6b7a99);
  font-size: 0.88rem;
  line-height: 1.5;
}

.field-input {
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.375rem;
  background: var(--color-surface, #fff);
  color: var(--color-text, #1a2338);
  font-size: 0.9rem;
  font-family: var(--font-body, sans-serif);
  width: 100%;
}

.runs-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: var(--space-3, 0.75rem);
  font-size: 0.88rem;
}

.runs-table th,
.runs-table td {
  padding: var(--space-2, 0.5rem) var(--space-3, 0.75rem);
  text-align: left;
  border-bottom: 1px solid var(--color-border, #d0d7e8);
}

.btn-import {
  padding: var(--space-1, 0.25rem) var(--space-3, 0.75rem);
  border: 1px solid var(--app-primary, #2A6080);
  border-radius: var(--radius-sm, 0.25rem);
  background: none;
  color: var(--app-primary, #2A6080);
  cursor: pointer;
  font-size: 0.85rem;
}

.btn-import:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.import-result {
  margin-top: var(--space-2, 0.5rem);
  font-size: 0.88rem;
  color: var(--color-text-secondary, #6b7a99);
}

.save-status {
  font-size: 0.85rem;
  color: var(--color-text-secondary, #6b7a99);
}
</style>
