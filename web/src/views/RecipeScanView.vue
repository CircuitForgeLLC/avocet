<template>
  <div class="rsv">
    <!-- Header -->
    <header class="rsv-header">
      <h1 class="rsv-title">Recipe Scan Review</h1>
      <div class="rsv-stats" v-if="stats">
        <span class="stat-chip">{{ stats.by_status?.pending ?? 0 }} pending</span>
        <span class="stat-chip stat-chip--ok">{{ stats.by_status?.approved ?? 0 }} approved</span>
        <span class="stat-chip stat-chip--edited">{{ stats.by_status?.edited ?? 0 }} edited</span>
        <span class="stat-chip stat-chip--bad">{{ stats.by_status?.rejected ?? 0 }} rejected</span>
        <a
          v-if="(stats.export_ready ?? 0) > 0"
          :href="`${apiBase}/api/recipe-scan/export`"
          download
          class="btn-export"
        >
          ⬇ Export {{ stats.export_ready }} pairs
        </a>
      </div>
    </header>

    <!-- Loading -->
    <div v-if="loading" class="rsv-state" aria-label="Loading">
      <div class="skeleton-block" />
    </div>

    <!-- Error -->
    <div v-else-if="apiError" class="rsv-state rsv-error" role="alert">
      <p>{{ apiError }}</p>
      <button class="btn-action" @click="fetchNext">Retry</button>
    </div>

    <!-- Queue empty -->
    <div v-else-if="!item" class="rsv-state rsv-empty">
      <p>Queue is empty — all items reviewed.</p>
      <p class="rsv-hint">Import items from the Kiwi pipeline to continue.</p>
    </div>

    <!-- Review panel -->
    <div v-else class="rsv-workspace">
      <!-- Left: image -->
      <section class="rsv-image-panel" aria-label="Scan image">
        <div class="rsv-panel-label">
          <span class="modality-badge">{{ item.modality }}</span>
          <span class="source-badge">{{ item.source }}</span>
        </div>
        <div class="rsv-image-wrap">
          <img
            v-if="imageUrl"
            :src="imageUrl"
            :alt="`Recipe scan — ${item.source}`"
            class="rsv-image"
          />
          <div v-else class="rsv-image-placeholder">
            <span>Image not available</span>
            <code class="rsv-path">{{ item.image_path }}</code>
          </div>
        </div>
      </section>

      <!-- Right: JSON comparison -->
      <section class="rsv-json-panel" aria-label="Extraction review">

        <!-- Ground truth (read-only reference) -->
        <div class="rsv-json-block">
          <h2 class="rsv-json-label">Ground truth <span class="label-tag">reference</span></h2>
          <pre class="rsv-json rsv-json--ground-truth" tabindex="0" aria-label="Ground truth JSON">{{ prettyJson(item.ground_truth) }}</pre>
        </div>

        <!-- Extracted / editable -->
        <div class="rsv-json-block">
          <h2 class="rsv-json-label">
            Extracted
            <span class="label-tag label-tag--edit">edit before approving</span>
          </h2>
          <textarea
            v-model="draftJson"
            class="rsv-json rsv-json--edit"
            spellcheck="false"
            aria-label="Extracted JSON — edit to correct"
            :class="{ 'rsv-json--invalid': jsonError }"
          />
          <p v-if="jsonError" class="rsv-json-error" role="alert">{{ jsonError }}</p>
        </div>

        <!-- Actions -->
        <div class="rsv-actions" role="group" aria-label="Review actions">
          <button
            class="btn-approve"
            :disabled="acting"
            @click="handleApprove"
            title="Extracted JSON is accurate — approve as-is (A)"
          >
            ✓ Approve
          </button>
          <button
            class="btn-edit"
            :disabled="acting || !!jsonError"
            @click="handleEdit"
            title="Approve the edited JSON in the text area (E)"
          >
            ✎ Approve edited
          </button>
          <button
            class="btn-reject"
            :disabled="acting"
            @click="handleReject"
            title="Extraction too broken to use — reject (R)"
          >
            ✕ Reject
          </button>
        </div>

      </section>
    </div>

    <!-- Feedback toast -->
    <Transition name="toast">
      <div v-if="toast" class="rsv-toast" role="status" aria-live="polite">
        {{ toast }}
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'

const apiBase = window.location.origin

interface RecipeScanItem {
  id: string
  image_path: string
  modality: string
  source: string
  extracted: Record<string, unknown>
  ground_truth: Record<string, unknown>
  status: string
}

interface Stats {
  total: number
  by_status: Record<string, number>
  by_modality: Record<string, number>
  export_ready: number
}

const item    = ref<RecipeScanItem | null>(null)
const stats   = ref<Stats | null>(null)
const loading = ref(true)
const acting  = ref(false)
const apiError = ref('')
const draftJson = ref('')
const toast   = ref('')
let toastTimer: ReturnType<typeof setTimeout> | null = null

const jsonError = computed(() => {
  if (!draftJson.value.trim()) return ''
  try {
    JSON.parse(draftJson.value)
    return ''
  } catch (e) {
    return 'Invalid JSON — fix before approving'
  }
})

const imageUrl = computed(() => {
  if (!item.value) return ''
  const encoded = encodeURIComponent(item.value.image_path)
  return `${apiBase}/api/recipe-scan/image?path=${encoded}`
})

function prettyJson(obj: unknown): string {
  return JSON.stringify(obj, null, 2)
}

function showToast(msg: string) {
  toast.value = msg
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 2500)
}

async function fetchNext() {
  loading.value = true
  apiError.value = ''
  try {
    const r = await fetch(`${apiBase}/api/recipe-scan/next`)
    if (r.status === 404) {
      item.value = null
    } else if (!r.ok) {
      throw new Error(`API error ${r.status}`)
    } else {
      item.value = await r.json()
      draftJson.value = prettyJson(item.value!.extracted)
    }
  } catch (e) {
    apiError.value = e instanceof Error ? e.message : 'Could not reach API'
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  try {
    const r = await fetch(`${apiBase}/api/recipe-scan/stats`)
    if (r.ok) stats.value = await r.json()
  } catch { /* non-critical */ }
}

async function act(endpoint: string, body?: unknown) {
  if (!item.value || acting.value) return
  acting.value = true
  try {
    const r = await fetch(`${apiBase}/api/recipe-scan/items/${item.value.id}/${endpoint}`, {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    })
    if (!r.ok) throw new Error(`API error ${r.status}`)
  } catch (e) {
    showToast(e instanceof Error ? e.message : 'Action failed')
    acting.value = false
    return
  }
  acting.value = false
  await Promise.all([fetchNext(), fetchStats()])
}

async function handleApprove() {
  showToast('Approved')
  await act('approve')
}

async function handleEdit() {
  if (jsonError.value) return
  let corrected: unknown
  try {
    corrected = JSON.parse(draftJson.value)
  } catch {
    return
  }
  showToast('Saved edit')
  await act('edit', { corrected })
}

async function handleReject() {
  showToast('Rejected')
  await act('reject')
}

// Keyboard shortcuts: A = approve, E = edit+approve, R = reject
function handleKey(e: KeyboardEvent) {
  const tag = (e.target as HTMLElement)?.tagName?.toLowerCase()
  if (tag === 'textarea' || tag === 'input') return
  if (e.key === 'a' || e.key === 'A') handleApprove()
  if (e.key === 'e' || e.key === 'E') handleEdit()
  if (e.key === 'r' || e.key === 'R') handleReject()
}

watch(item, (newItem) => {
  if (newItem) draftJson.value = prettyJson(newItem.extracted)
})

onMounted(() => {
  fetchNext()
  fetchStats()
  window.addEventListener('keydown', handleKey)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKey)
  if (toastTimer) clearTimeout(toastTimer)
})
</script>

<style scoped>
.rsv {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: var(--space-md, 1rem);
  gap: var(--space-md, 1rem);
  box-sizing: border-box;
  overflow: hidden;
}

/* Header */
.rsv-header {
  display: flex;
  align-items: center;
  gap: var(--space-md, 1rem);
  flex-wrap: wrap;
}
.rsv-title {
  font-size: 1.1rem;
  font-weight: 600;
  margin: 0;
  color: var(--color-text, #fff);
}
.rsv-stats {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.stat-chip {
  font-size: 0.75rem;
  padding: 2px 8px;
  border-radius: 12px;
  background: var(--color-surface-alt, #2a2a2a);
  color: var(--color-text-muted, #aaa);
}
.stat-chip--ok      { background: #1a3a1a; color: #6fcf97; }
.stat-chip--edited  { background: #2a2a00; color: #f2c94c; }
.stat-chip--bad     { background: #3a1a1a; color: #eb5757; }
.btn-export {
  font-size: 0.8rem;
  padding: 4px 12px;
  border-radius: 6px;
  background: var(--color-accent, #4a9eff);
  color: #fff;
  text-decoration: none;
}

/* State panels */
.rsv-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  color: var(--color-text-muted, #aaa);
}
.rsv-error  { color: var(--color-danger, #eb5757); }
.rsv-empty  { font-size: 1rem; }
.rsv-hint   { font-size: 0.85rem; opacity: 0.7; margin: 0; }
.skeleton-block {
  width: 100%; height: 300px;
  border-radius: 8px;
  background: var(--color-surface-alt, #2a2a2a);
  animation: pulse 1.5s ease-in-out infinite;
}
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }

/* Workspace: two-column layout */
.rsv-workspace {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-md, 1rem);
  min-height: 0;
  overflow: hidden;
}
@media (max-width: 900px) {
  .rsv-workspace {
    grid-template-columns: 1fr;
    overflow-y: auto;
  }
}

/* Image panel */
.rsv-image-panel {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  min-height: 0;
}
.rsv-panel-label {
  display: flex;
  gap: 0.5rem;
}
.modality-badge, .source-badge {
  font-size: 0.72rem;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--color-surface-alt, #2a2a2a);
  color: var(--color-text-muted, #aaa);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.rsv-image-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-surface-alt, #111);
  border-radius: 8px;
  overflow: hidden;
  min-height: 200px;
}
.rsv-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}
.rsv-image-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  color: var(--color-text-muted, #666);
  font-size: 0.85rem;
  padding: 1rem;
  text-align: center;
}
.rsv-path {
  font-size: 0.7rem;
  word-break: break-all;
  opacity: 0.6;
}

/* JSON panel */
.rsv-json-panel {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  min-height: 0;
  overflow-y: auto;
}
.rsv-json-block {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  flex: 1;
  min-height: 0;
}
.rsv-json-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-text-muted, #aaa);
  margin: 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.label-tag {
  font-size: 0.68rem;
  font-weight: 400;
  padding: 1px 6px;
  border-radius: 8px;
  background: var(--color-surface-alt, #2a2a2a);
  color: var(--color-text-muted, #888);
}
.label-tag--edit {
  background: #2a2a00;
  color: #f2c94c;
}
.rsv-json {
  font-family: var(--font-mono, monospace);
  font-size: 0.75rem;
  line-height: 1.5;
  padding: 0.75rem;
  border-radius: 6px;
  min-height: 120px;
  flex: 1;
  overflow-y: auto;
  resize: vertical;
  white-space: pre;
}
.rsv-json--ground-truth {
  background: var(--color-surface-alt, #111);
  color: var(--color-text, #ccc);
  border: 1px solid var(--color-border, #333);
}
.rsv-json--edit {
  background: var(--color-surface, #1a1a1a);
  color: var(--color-text, #e0e0e0);
  border: 1px solid var(--color-border, #444);
  caret-color: var(--color-accent, #4a9eff);
  outline: none;
  transition: border-color 0.15s;
}
.rsv-json--edit:focus {
  border-color: var(--color-accent, #4a9eff);
}
.rsv-json--invalid {
  border-color: var(--color-danger, #eb5757) !important;
}
.rsv-json-error {
  font-size: 0.75rem;
  color: var(--color-danger, #eb5757);
  margin: 0;
}

/* Action buttons */
.rsv-actions {
  display: flex;
  gap: 0.5rem;
  padding-top: 0.25rem;
  flex-wrap: wrap;
}
.btn-approve, .btn-edit, .btn-reject {
  flex: 1;
  min-width: 80px;
  padding: 0.5rem 0.75rem;
  border: none;
  border-radius: 6px;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s;
}
.btn-approve, .btn-edit, .btn-reject {
  opacity: 1;
}
.btn-approve:disabled, .btn-edit:disabled, .btn-reject:disabled {
  opacity: 0.4;
  cursor: default;
}
.btn-approve { background: #1e6e1e; color: #6fcf97; }
.btn-approve:hover:not(:disabled) { background: #256325; }
.btn-edit    { background: #4a4a00; color: #f2c94c; }
.btn-edit:hover:not(:disabled)    { background: #606000; }
.btn-reject  { background: #6e1e1e; color: #eb8f8f; }
.btn-reject:hover:not(:disabled)  { background: #7a2222; }

/* Toast */
.rsv-toast {
  position: fixed;
  bottom: 1.5rem;
  left: 50%;
  transform: translateX(-50%);
  background: var(--color-surface, #222);
  color: var(--color-text, #fff);
  border: 1px solid var(--color-border, #444);
  border-radius: 8px;
  padding: 0.5rem 1.25rem;
  font-size: 0.85rem;
  box-shadow: 0 4px 20px rgba(0,0,0,0.4);
  pointer-events: none;
  z-index: 100;
}
.toast-enter-active, .toast-leave-active { transition: opacity 0.2s, transform 0.2s; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateX(-50%) translateY(8px); }
</style>
