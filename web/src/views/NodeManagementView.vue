<script setup lang="ts">
import { ref, onMounted } from 'vue'
import NodeCard from '../components/nodes/NodeCard.vue'

interface GpuEntry {
  gpu_id: number
  card: string
  vram_total_mb: number
  vram_used_mb: number
  vram_free_mb: number
  temp_c: number | null
  utilization_pct: number | null
  compute_cap: number | null
  services_assigned: string[]
  services_running: string[]
}

interface ServiceInfo {
  min_compute_cap: number
  max_mb: number
  catalog_size: number
}

interface NodeSummary {
  node_id: string
  online: boolean
  agent_url: string
  gpus: GpuEntry[]
  profile_loaded: boolean
  services_catalog: Record<string, ServiceInfo>
}

const nodes = ref<NodeSummary[]>([])
const loading = ref(true)
const error = ref('')

async function fetchNodes() {
  loading.value = true
  error.value = ''
  try {
    const r = await fetch('/api/nodes-mgmt/nodes')
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    nodes.value = await r.json()
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

    <div v-if="loading" class="nodes-status" aria-live="polite">Loading nodes...</div>
    <div v-else-if="error" class="nodes-status nodes-error" role="alert">{{ error }}</div>
    <div v-else-if="nodes.length === 0" class="nodes-status">
      No nodes found. Check <code>coordinator_url</code> in config.
    </div>
    <div v-else class="nodes-grid">
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
</style>
