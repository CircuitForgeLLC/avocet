<template>
  <div class="corrections-view">
    <header class="cv-header">
      <span class="queue-count">
        <template v-if="loading">Loading…</template>
        <template v-else-if="store.totalRemaining > 0">
          {{ store.totalRemaining }} remaining
        </template>
        <span v-else class="queue-empty-label">All caught up</span>
      </span>
      <div class="header-actions">
        <button @click="handleUndo" :disabled="!store.lastAction" class="btn-action">↩ Undo</button>
      </div>
    </header>

    <!-- States -->
    <div v-if="loading" class="skeleton-card" aria-label="Loading candidates" />

    <div v-else-if="apiError" class="error-display" role="alert">
      <p>Couldn't reach Avocet API.</p>
      <button @click="fetchBatch" class="btn-action">Retry</button>
    </div>

    <div v-else-if="!store.current" class="empty-state">
      <p>No candidates need review.</p>
      <p class="empty-hint">Import a benchmark run from the Settings tab to get started.</p>
    </div>

    <template v-else>
      <div class="card-wrapper">
        <SftCard
          :item="store.current"
          :correcting="correcting"
          @correct="startCorrection"
          @discard="handleDiscard"
          @flag="handleFlag"
          @submit-correction="handleCorrect"
          @cancel-correction="correcting = false"
        />
      </div>
    </template>

    <!-- Stats footer -->
    <footer v-if="stats" class="stats-footer">
      <span class="stat">✓ {{ stats.by_status?.approved ?? 0 }} approved</span>
      <span class="stat">✕ {{ stats.by_status?.discarded ?? 0 }} discarded</span>
      <span class="stat">⚑ {{ stats.by_status?.model_rejected ?? 0 }} flagged</span>
      <a
        v-if="(stats.export_ready ?? 0) > 0"
        :href="exportUrl"
        download
        class="btn-export"
      >
        ⬇ Export {{ stats.export_ready }} corrections
      </a>
    </footer>

    <!-- Undo toast (inline — UndoToast.vue uses label store's LastAction shape, not SFT's) -->
    <div v-if="store.lastAction" class="undo-toast">
      <span>Last: {{ store.lastAction.type }}</span>
      <button @click="handleUndo" class="btn-undo">↩ Undo</button>
      <button @click="store.clearLastAction()" class="btn-dismiss">✕</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useSftStore } from '../stores/sft'
import { useSftKeyboard } from '../composables/useSftKeyboard'
import SftCard from '../components/SftCard.vue'

const store      = useSftStore()
const loading    = ref(false)
const apiError   = ref(false)
const correcting = ref(false)
const stats      = ref<Record<string, any> | null>(null)
const exportUrl  = '/api/sft/export'

useSftKeyboard({
  onCorrect: () => { if (store.current && !correcting.value) correcting.value = true },
  onDiscard: () => { if (store.current && !correcting.value) handleDiscard() },
  onFlag:    () => { if (store.current && !correcting.value) handleFlag() },
  onEscape:  () => { correcting.value = false },
  onSubmit:  () => {},
  isEditing: () => correcting.value,
})

async function fetchBatch() {
  loading.value  = true
  apiError.value = false
  try {
    const res = await fetch('/api/sft/queue?per_page=20')
    if (!res.ok) throw new Error('API error')
    const data = await res.json()
    store.queue          = data.items
    store.totalRemaining = data.total
  } catch {
    apiError.value = true
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  try {
    const res = await fetch('/api/sft/stats')
    if (res.ok) stats.value = await res.json()
  } catch { /* ignore */ }
}

function startCorrection() {
  correcting.value = true
}

async function handleCorrect(text: string) {
  if (!store.current) return
  const item = store.current
  correcting.value = false
  try {
    const res = await fetch('/api/sft/submit', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ id: item.id, action: 'correct', corrected_response: text }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    store.removeCurrentFromQueue()
    store.setLastAction('correct', item)
    store.totalRemaining = Math.max(0, store.totalRemaining - 1)
    fetchStats()
    if (store.queue.length < 5) fetchBatch()
  } catch (err) {
    console.error('handleCorrect failed:', err)
  }
}

async function handleDiscard() {
  if (!store.current) return
  const item = store.current
  try {
    const res = await fetch('/api/sft/submit', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ id: item.id, action: 'discard' }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    store.removeCurrentFromQueue()
    store.setLastAction('discard', item)
    store.totalRemaining = Math.max(0, store.totalRemaining - 1)
    fetchStats()
    if (store.queue.length < 5) fetchBatch()
  } catch (err) {
    console.error('handleDiscard failed:', err)
  }
}

async function handleFlag() {
  if (!store.current) return
  const item = store.current
  try {
    const res = await fetch('/api/sft/submit', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ id: item.id, action: 'flag' }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    store.removeCurrentFromQueue()
    store.setLastAction('flag', item)
    store.totalRemaining = Math.max(0, store.totalRemaining - 1)
    fetchStats()
    if (store.queue.length < 5) fetchBatch()
  } catch (err) {
    console.error('handleFlag failed:', err)
  }
}

async function handleUndo() {
  if (!store.lastAction) return
  const action = store.lastAction
  const { item } = action
  try {
    const res = await fetch('/api/sft/undo', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ id: item.id }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    store.restoreItem(item)
    store.totalRemaining++
    store.clearLastAction()
    fetchStats()
  } catch (err) {
    // Backend did not restore — clear the undo UI without restoring queue state
    console.error('handleUndo failed:', err)
    store.clearLastAction()
  }
}

onMounted(() => {
  fetchBatch()
  fetchStats()
})
</script>

<style scoped>
.corrections-view {
  display: flex;
  flex-direction: column;
  min-height: 100dvh;
  padding: var(--space-4);
  gap: var(--space-4);
  max-width: 760px;
  margin: 0 auto;
}

.cv-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.queue-count {
  font-size: 1rem;
  font-weight: 600;
  color: var(--color-text);
}

.queue-empty-label { color: var(--color-text-muted); }

.btn-action {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-raised);
  cursor: pointer;
  font-size: 0.88rem;
}

.btn-action:disabled { opacity: 0.4; cursor: not-allowed; }

.skeleton-card {
  height: 320px;
  background: var(--color-surface-alt);
  border-radius: var(--radius-lg);
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

@media (prefers-reduced-motion: reduce) {
  .skeleton-card { animation: none; }
}

.error-display, .empty-state {
  text-align: center;
  padding: var(--space-12);
  color: var(--color-text-muted);
}

.empty-hint { font-size: 0.88rem; margin-top: var(--space-2); }

.stats-footer {
  display: flex;
  gap: var(--space-4);
  align-items: center;
  flex-wrap: wrap;
  padding: var(--space-3) 0;
  border-top: 1px solid var(--color-border-light);
  font-size: 0.85rem;
  color: var(--color-text-muted);
}

.btn-export {
  margin-left: auto;
  padding: var(--space-2) var(--space-3);
  background: var(--color-primary);
  color: var(--color-text-inverse, #fff);
  border-radius: var(--radius-md);
  text-decoration: none;
  font-size: 0.88rem;
}

.undo-toast {
  position: fixed;
  bottom: var(--space-6);
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  font-size: 0.9rem;
}

.btn-undo {
  background: var(--color-primary);
  color: var(--color-text-inverse, #fff);
  border: none;
  border-radius: var(--radius-sm);
  padding: var(--space-1) var(--space-3);
  cursor: pointer;
  font-size: 0.88rem;
}

.btn-dismiss {
  background: none;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  font-size: 1rem;
}
</style>
