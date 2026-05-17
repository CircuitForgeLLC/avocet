<script setup lang="ts">
import { ref } from 'vue'
import GpuRow from './GpuRow.vue'
import OllamaModelPanel from './OllamaModelPanel.vue'
import ProfileEditorPanel from './ProfileEditorPanel.vue'
import type { NodeSummary, FullProfile } from '../../types/nodes'

const props = defineProps<{ node: NodeSummary }>()
const emit = defineEmits<{ updated: [] }>()

const showOllama = ref(false)
const showEditor = ref(false)
const loadedProfile = ref<FullProfile | null>(null)
const profileLoading = ref(false)
const profileError = ref('')

async function openEditor() {
  if (showEditor.value) { showEditor.value = false; return }
  profileLoading.value = true
  profileError.value = ''
  try {
    const r = await fetch(`/api/nodes-mgmt/nodes/${props.node.node_id}/profile`)
    if (r.status === 404) {
      loadedProfile.value = null
    } else if (!r.ok) {
      throw new Error(`HTTP ${r.status}`)
    } else {
      loadedProfile.value = await r.json() as FullProfile
    }
    showEditor.value = true
  } catch (e) {
    profileError.value = e instanceof Error ? e.message : 'Failed to load profile'
  } finally {
    profileLoading.value = false
  }
}

function onProfileSaved() {
  showEditor.value = false
  emit('updated')
}
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
      <div class="node-actions">
        <button
          v-if="node.profile_loaded"
          class="btn-secondary btn-sm"
          @click="showOllama = !showOllama"
        >
          {{ showOllama ? 'Hide Ollama' : 'Ollama' }}
        </button>
        <button
          class="btn-secondary btn-sm"
          :disabled="profileLoading"
          @click="openEditor"
        >
          {{ profileLoading ? 'Loading…' : node.profile_loaded ? (showEditor ? 'Close Editor' : 'Edit Profile') : 'Create Profile' }}
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
    <div v-if="profileError" class="profile-load-error" role="alert">{{ profileError }}</div>
    <ProfileEditorPanel
      v-if="showEditor"
      :node-id="node.node_id"
      :initial-profile="loadedProfile"
      @saved="onProfileSaved"
      @close="showEditor = false"
    />
  </section>
</template>

<style scoped>
.node-card {
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 1rem;
  background: var(--color-surface-raised);
  color: var(--color-text);
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
.node-name { margin: 0; font-size: 1rem; font-weight: 600; color: var(--color-text); }
.node-agent { color: var(--color-text-muted); font-size: 0.8rem; font-family: var(--font-mono, monospace); }
.status-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.status-dot.online  { background: var(--color-success); }
.status-dot.offline { background: var(--color-warning); }
.node-actions { display: flex; gap: 0.5rem; flex-shrink: 0; }
.btn-secondary {
  background: transparent;
  border: 1px solid var(--color-border);
  color: var(--color-text);
  border-radius: 4px;
  padding: 0.3rem 0.65rem;
  cursor: pointer;
  font-size: 0.8rem;
}
.btn-secondary:hover { background: var(--color-surface-alt); }
.btn-secondary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-sm { font-size: 0.8rem; padding: 0.25rem 0.6rem; }
.no-profile {
  padding: 0.6rem 0.75rem;
  background: var(--color-surface-alt);
  border-radius: 4px;
  color: var(--color-text-muted);
  font-size: 0.875rem;
  margin-bottom: 0.5rem;
}
.gpu-list { display: flex; flex-direction: column; gap: 0.5rem; }
.profile-load-error { color: var(--color-error); font-size: 0.8rem; margin-top: 0.5rem; }
</style>
