<script setup lang="ts">
import { ref, onMounted } from 'vue'
import NodeCard from '../components/nodes/NodeCard.vue'
import type { NodeSummary } from '../types/nodes'

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
  <main class="nodes-page">
    <header class="nodes-header">
      <h1>Nodes</h1>
      <button class="btn-secondary" @click="fetchNodes" :disabled="loading">Refresh</button>
    </header>

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
  </main>
</template>

<style scoped>
.nodes-page { padding: 1.5rem; }
.nodes-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.5rem;
}
.nodes-header h1 { margin: 0; font-size: 1.5rem; }
.nodes-grid { display: flex; flex-direction: column; gap: 1.5rem; }
.nodes-status {
  color: var(--text-secondary, #888);
  padding: 2rem;
  text-align: center;
}
.nodes-error { color: var(--color-error, #fc8181); }
.sr-announce { min-height: 1.2em; }
</style>
