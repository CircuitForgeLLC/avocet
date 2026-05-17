<script setup lang="ts">
import { ref, onMounted } from 'vue'
import NodeCard from '../components/nodes/NodeCard.vue'
import AssignmentsTab from './AssignmentsTab.vue'
import type { NodeSummary } from '../types/nodes'

type Tab = 'nodes' | 'assignments'

const activeTab = ref<Tab>('nodes')
const nodes = ref<NodeSummary[]>([])
const loading = ref(true)
const error = ref('')

async function fetchNodes() {
  loading.value = true
  error.value = ''
  try {
    const r = await fetch('/api/nodes-mgmt/nodes')
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    nodes.value = (await r.json()) as NodeSummary[]
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to load nodes'
  } finally {
    loading.value = false
  }
}

onMounted(fetchNodes)
</script>

<template>
  <main class="fleet-page">
    <header class="fleet-header">
      <h1 class="fleet-title">Fleet</h1>
    </header>

    <!-- Tab bar -->
    <nav class="tab-bar" role="tablist" aria-label="Fleet sections">
      <button
        id="tab-nodes"
        role="tab"
        :aria-selected="activeTab === 'nodes'"
        :class="['tab', { active: activeTab === 'nodes' }]"
        @click="activeTab = 'nodes'"
      >Nodes</button>
      <button
        id="tab-assignments"
        role="tab"
        :aria-selected="activeTab === 'assignments'"
        :class="['tab', { active: activeTab === 'assignments' }]"
        @click="activeTab = 'assignments'"
      >Assignments</button>
    </nav>

    <!-- Nodes tab -->
    <section
      v-if="activeTab === 'nodes'"
      role="tabpanel"
      aria-labelledby="tab-nodes"
      class="tab-panel"
    >
      <div class="nodes-toolbar">
        <button class="btn-secondary btn-sm" @click="fetchNodes" :disabled="loading">Refresh</button>
      </div>
      <div aria-live="polite" aria-atomic="true" class="sr-announce">
        <span v-if="loading">Loading nodes...</span>
      </div>
      <div v-if="error" class="nodes-status nodes-error" role="alert">{{ error }}</div>
      <div v-else-if="!loading && nodes.length === 0" class="nodes-status">
        No nodes found. Check <code>coordinator_url</code> in config.
      </div>
      <div v-else-if="!loading" class="nodes-grid">
        <NodeCard
          v-for="node in nodes"
          :key="node.node_id"
          :node="node"
          @updated="fetchNodes"
        />
      </div>
    </section>

    <!-- Assignments tab -->
    <section
      v-else-if="activeTab === 'assignments'"
      role="tabpanel"
      aria-labelledby="tab-assignments"
      class="tab-panel"
    >
      <AssignmentsTab />
    </section>
  </main>
</template>

<style scoped>
.fleet-page { padding: 1.5rem; }

.fleet-header {
  margin-bottom: 1rem;
}
.fleet-title {
  margin: 0;
  font-size: 1.5rem;
  color: var(--color-text);
}

/* ── Tab bar ── */
.tab-bar {
  display: flex;
  gap: 0;
  border-bottom: 2px solid var(--color-border);
  margin-bottom: 1.25rem;
}
.tab {
  padding: 0.55rem 1.1rem;
  font-size: 0.88rem;
  font-weight: 600;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  cursor: pointer;
  color: var(--color-text-muted);
  transition: color 0.15s, border-color 0.15s;
}
.tab:hover { color: var(--color-text); }
.tab.active {
  color: var(--app-primary);
  border-bottom-color: var(--app-primary);
}

/* ── Tab panel ── */
.tab-panel { min-height: 200px; }

/* ── Nodes toolbar ── */
.nodes-toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 1rem;
}

/* ── Nodes grid / status ── */
.nodes-grid { display: flex; flex-direction: column; gap: 1.5rem; }
.nodes-status {
  color: var(--color-text-muted);
  padding: 2rem;
  text-align: center;
}
.nodes-error { color: var(--color-error); }
.sr-announce { min-height: 1.2em; }

/* ── Shared button ── */
.btn-secondary {
  padding: 0.4rem 0.9rem;
  background: var(--color-surface-alt);
  border: 1px solid var(--color-border);
  border-radius: 0.4rem;
  font-size: 0.85rem;
  color: var(--color-text);
  cursor: pointer;
  transition: background 0.15s;
}
.btn-secondary:hover:not(:disabled) { background: var(--color-surface-raised); }
.btn-secondary:disabled { opacity: 0.5; cursor: default; }
.btn-sm { padding: 0.3rem 0.65rem; font-size: 0.8rem; }
</style>
