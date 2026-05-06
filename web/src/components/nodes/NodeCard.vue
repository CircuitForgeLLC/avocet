<script setup lang="ts">
import { ref } from 'vue'
import GpuRow from './GpuRow.vue'
import OllamaModelPanel from './OllamaModelPanel.vue'
import HfNodeModelPanel from './HfNodeModelPanel.vue'
import type { NodeSummary } from '../../types/nodes'

const props = defineProps<{ node: NodeSummary }>()
const emit = defineEmits<{ updated: [] }>()

const showOllama = ref(false)
const showHf = ref(false)
</script>

<template>
  <section class="node-card" :class="{ offline: !node.online }">
    <header class="node-card-header">
      <div class="node-identity">
        <span
          class="status-dot"
          :class="node.online ? 'online' : 'offline'"
          :aria-label="node.online ? 'Online' : 'Offline'"
          role="img"
        />
        <h2 class="node-name">{{ node.node_id }}</h2>
        <span class="node-agent">{{ node.agent_url }}</span>
      </div>
      <div v-if="node.profile_loaded" class="node-actions">
        <button class="btn-secondary btn-sm" @click="showOllama = !showOllama">
          {{ showOllama ? 'Hide Ollama' : 'Ollama' }}
        </button>
        <button class="btn-secondary btn-sm" @click="showHf = !showHf">
          {{ showHf ? 'Hide Catalog' : 'Catalog' }}
        </button>
      </div>
    </header>

    <div v-if="!node.profile_loaded" class="no-profile" role="status">
      No profile configured for this node. GPU stats are visible; service assignment is disabled.
    </div>

    <div class="gpu-list">
      <GpuRow
        v-for="gpu in node.gpus"
        :key="gpu.gpu_id"
        :gpu="gpu"
        :node-id="node.node_id"
        :profile-loaded="node.profile_loaded"
        :services-catalog="node.services_catalog"
        @updated="emit('updated')"
      />
    </div>

    <OllamaModelPanel v-if="showOllama" :node-id="node.node_id" />
    <HfNodeModelPanel v-if="showHf" :node-id="node.node_id" />
  </section>
</template>

<style scoped>
.node-card {
  border: 1px solid var(--border, #333);
  border-radius: 8px;
  padding: 1rem;
  background: var(--bg-card, #1a1a1a);
}
.node-card.offline { opacity: 0.65; }
.node-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.node-identity { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.node-name { margin: 0; font-size: 1rem; font-weight: 600; }
.node-agent { color: var(--text-secondary, #888); font-size: 0.8rem; font-family: monospace; }
.status-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.status-dot.online  { background: var(--color-success, #48bb78); }
.status-dot.offline { background: var(--color-warning, #ed8936); }
.node-actions { display: flex; gap: 0.5rem; flex-shrink: 0; }
.no-profile {
  padding: 0.6rem 0.75rem;
  background: var(--bg-notice, #1e1e1e);
  border-radius: 4px;
  color: var(--text-secondary, #888);
  font-size: 0.875rem;
  margin-bottom: 0.5rem;
}
.gpu-list { display: flex; flex-direction: column; gap: 0.5rem; }
</style>
