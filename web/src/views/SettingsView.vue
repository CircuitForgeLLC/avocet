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

onMounted(reload)
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
</style>
