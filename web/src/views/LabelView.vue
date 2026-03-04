<template>
  <div class="label-view">
    <!-- Header bar -->
    <header class="lv-header">
      <span class="queue-count">
        <span v-if="loading" class="queue-status">Loading…</span>
        <template v-else-if="store.totalRemaining > 0">
          {{ store.totalRemaining }} remaining
        </template>
        <span v-else class="queue-status">Queue empty</span>
        <span v-if="onRoll"         class="badge badge-roll">🔥 On a roll!</span>
        <span v-if="speedRound"     class="badge badge-speed">⚡ Speed round!</span>
        <span v-if="fiftyDeep"      class="badge badge-fifty">🎯 Fifty deep!</span>
        <span v-if="centuryMark"    class="badge badge-century">💯 Century!</span>
        <span v-if="cleanSweep"     class="badge badge-sweep">🧹 Clean sweep!</span>
        <span v-if="midnightLabeler" class="badge badge-midnight">🦉 Midnight labeler!</span>
      </span>
      <div class="header-actions">
        <button @click="handleUndo"    :disabled="!store.lastAction" class="btn-action">↩ Undo</button>
        <button @click="handleSkip"    :disabled="!store.current"    class="btn-action">→ Skip</button>
        <button @click="handleDiscard" :disabled="!store.current"    class="btn-action btn-danger">✕ Discard</button>
      </div>
    </header>

    <!-- States -->
    <div v-if="loading" class="skeleton-card" aria-label="Loading email" />

    <div v-else-if="apiError" class="error-display" role="alert">
      <p>Couldn't reach Avocet API.</p>
      <button @click="fetchBatch" class="btn-action">Retry</button>
    </div>

    <div v-else-if="!store.current" class="empty-state">
      <p>Queue is empty — fetch more emails to continue.</p>
    </div>

    <!-- Card stack + label grid -->
    <template v-else>
      <div class="card-stack-wrapper">
        <EmailCardStack
          :item="store.current"
          :is-bucket-mode="isDragging"
          :dismiss-type="dismissType"
          @label="handleLabel"
          @skip="handleSkip"
          @discard="handleDiscard"
          @drag-start="isDragging = true"
          @drag-end="isDragging = false"
        />
      </div>

      <LabelBucketGrid
        :labels="labels"
        :is-bucket-mode="isDragging"
        @label="handleLabel"
      />
    </template>

    <!-- Undo toast -->
    <UndoToast
      v-if="store.lastAction"
      :action="store.lastAction"
      @undo="handleUndo"
      @expire="store.clearLastAction()"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useLabelStore } from '../stores/label'
import { useApiFetch } from '../composables/useApi'
import { useHaptics } from '../composables/useHaptics'
import { useMotion } from '../composables/useMotion'
import { useLabelKeyboard } from '../composables/useLabelKeyboard'
import { fireConfetti, useCursorTrail } from '../composables/useEasterEgg'
import EmailCardStack from '../components/EmailCardStack.vue'
import LabelBucketGrid from '../components/LabelBucketGrid.vue'
import UndoToast from '../components/UndoToast.vue'

const store   = useLabelStore()
const haptics = useHaptics()
const motion  = useMotion()   // only needed to pass to child — actual value used in App.vue

const loading    = ref(true)
const apiError   = ref(false)
const isDragging = ref(false)
const labels     = ref<any[]>([])
const dismissType = ref<'label' | 'skip' | 'discard' | null>(null)

// Easter egg state
const consecutiveLabeled = ref(0)
const recentLabels = ref<number[]>([])
const onRoll    = ref(false)
const speedRound = ref(false)
const fiftyDeep  = ref(false)

// New easter egg state
const centuryMark    = ref(false)
const cleanSweep     = ref(false)
const midnightLabeler = ref(false)
let midnightShownThisSession = false
let trailCleanup: (() => void) | null = null
let themeObserver: MutationObserver | null = null

function syncCursorTrail() {
  const isHacker = document.documentElement.dataset.theme === 'hacker'
  if (isHacker && !trailCleanup) {
    trailCleanup = useCursorTrail()
  } else if (!isHacker && trailCleanup) {
    trailCleanup()
    trailCleanup = null
  }
}

async function fetchBatch() {
  loading.value = true
  apiError.value = false
  const { data, error } = await useApiFetch<{ items: any[]; total: number }>('/api/queue?limit=10')
  loading.value = false
  if (error || !data) {
    apiError.value = true
    return
  }
  store.queue = data.items
  store.totalRemaining = data.total

  // Clean sweep — queue exhausted in this batch
  if (data.total === 0 && data.items.length === 0 && store.sessionLabeled > 0) {
    cleanSweep.value = true
    setTimeout(() => { cleanSweep.value = false }, 4000)
  }
}

function checkSpeedRound(): boolean {
  const now = Date.now()
  recentLabels.value = recentLabels.value.filter(t => now - t < 20000)
  recentLabels.value.push(now)
  return recentLabels.value.length >= 5
}

async function handleLabel(name: string) {
  const item = store.current
  if (!item) return

  // Optimistic update
  store.setLastAction('label', item, name)
  dismissType.value = 'label'

  if (motion.rich.value) {
    await new Promise(r => setTimeout(r, 350))
  }

  store.removeCurrentFromQueue()
  store.incrementLabeled()
  dismissType.value = null
  consecutiveLabeled.value++
  haptics.label()

  // Easter eggs
  if (consecutiveLabeled.value >= 10) {
    onRoll.value = true
    setTimeout(() => { onRoll.value = false }, 3000)
  }
  if (store.sessionLabeled === 50) {
    fiftyDeep.value = true
    setTimeout(() => { fiftyDeep.value = false }, 5000)
  }
  if (checkSpeedRound()) {
    onRoll.value = false
    speedRound.value = true
    setTimeout(() => { speedRound.value = false }, 2500)
  }

  // Hired confetti
  if (name === 'hired') {
    fireConfetti()
  }

  // Century mark
  if (store.sessionLabeled === 100) {
    centuryMark.value = true
    setTimeout(() => { centuryMark.value = false }, 4000)
  }

  // Midnight labeler — once per session
  if (!midnightShownThisSession) {
    const h = new Date().getHours()
    if (h >= 0 && h < 3) {
      midnightShownThisSession = true
      midnightLabeler.value = true
      setTimeout(() => { midnightLabeler.value = false }, 5000)
    }
  }

  await useApiFetch('/api/label', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: item.id, label: name }),
  })

  if (store.queue.length < 3) await fetchBatch()
}

async function handleSkip() {
  const item = store.current
  if (!item) return
  store.setLastAction('skip', item)
  dismissType.value = 'skip'
  if (motion.rich.value) await new Promise(r => setTimeout(r, 300))
  store.removeCurrentFromQueue()
  dismissType.value = null
  consecutiveLabeled.value = 0
  haptics.skip()
  await useApiFetch('/api/skip', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: item.id }),
  })
  if (store.queue.length < 3) await fetchBatch()
}

async function handleDiscard() {
  const item = store.current
  if (!item) return
  store.setLastAction('discard', item)
  dismissType.value = 'discard'
  if (motion.rich.value) await new Promise(r => setTimeout(r, 400))
  store.removeCurrentFromQueue()
  dismissType.value = null
  consecutiveLabeled.value = 0
  haptics.discard()
  await useApiFetch('/api/discard', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: item.id }),
  })
  if (store.queue.length < 3) await fetchBatch()
}

async function handleUndo() {
  const { data } = await useApiFetch<{ undone: { type: string; item: any } }>('/api/label/undo', { method: 'DELETE' })
  if (data?.undone?.item) {
    store.restoreItem(data.undone.item)
    store.clearLastAction()
    haptics.undo()
    if (data.undone.type === 'label') {
      // decrement session counter — sessionLabeled is direct state in a setup store
      if (store.sessionLabeled > 0) store.sessionLabeled--
    }
  }
}

useLabelKeyboard({
  labels: [],   // will be updated after labels load — keyboard not active until queue loads
  onLabel: handleLabel,
  onSkip: handleSkip,
  onDiscard: handleDiscard,
  onUndo: handleUndo,
  onHelp: () => { /* TODO: help overlay */ },
})

onMounted(async () => {
  const { data } = await useApiFetch<any[]>('/api/config/labels')
  if (data) labels.value = data
  await fetchBatch()

  // Cursor trail — activate immediately if already in hacker mode, then watch for changes
  syncCursorTrail()
  themeObserver = new MutationObserver(syncCursorTrail)
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
})

onUnmounted(() => {
  themeObserver?.disconnect()
  themeObserver = null
  if (trailCleanup) {
    trailCleanup()
    trailCleanup = null
  }
})
</script>

<style scoped>
.label-view {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  padding: 1rem;
  max-width: 640px;
  margin: 0 auto;
  min-height: 100dvh;
}

.queue-status {
  opacity: 0.6;
  font-style: italic;
}

.lv-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.queue-count {
  font-family: var(--font-mono, monospace);
  font-size: 0.9rem;
  color: var(--color-text-secondary, #6b7a99);
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.badge {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 700;
  font-family: var(--font-body, sans-serif);
  animation: badge-pop 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes badge-pop {
  from { transform: scale(0.6); opacity: 0; }
  to   { transform: scale(1);   opacity: 1; }
}

.badge-roll    { background: #ff6b35; color: #fff; }
.badge-speed   { background: #7c3aed; color: #fff; }
.badge-fifty   { background: var(--app-accent, #B8622A); color: var(--app-accent-text, #1a2338); }
.badge-century { background: #ffd700; color: #1a2338; }
.badge-sweep   { background: var(--app-primary, #2A6080); color: #fff; }
.badge-midnight { background: #1a1a2e; color: #7c9dcf; border: 1px solid #7c9dcf; }

.header-actions {
  display: flex;
  gap: 0.5rem;
}

.btn-action {
  padding: 0.4rem 0.8rem;
  border-radius: 0.375rem;
  border: 1px solid var(--color-border, #d0d7e8);
  background: var(--color-surface, #fff);
  color: var(--color-text, #1a2338);
  font-size: 0.85rem;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-action:hover:not(:disabled) {
  background: var(--app-primary-light, #E4F0F7);
}
.btn-action:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.btn-danger {
  border-color: var(--color-error, #ef4444);
  color: var(--color-error, #ef4444);
}

.skeleton-card {
  min-height: 200px;
  border-radius: var(--radius-card, 1rem);
  background: linear-gradient(
    90deg,
    var(--color-surface-raised, #f0f4fc) 25%,
    var(--color-surface, #e4ebf5) 50%,
    var(--color-surface-raised, #f0f4fc) 75%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
}

@keyframes shimmer {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.error-display, .empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
  padding: 3rem 1rem;
  color: var(--color-text-secondary, #6b7a99);
  text-align: center;
}

.card-stack-wrapper {
  flex: 1;
}
</style>
