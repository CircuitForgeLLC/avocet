<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

interface CatalogEntry {
  path: string
  vram_mb: number
  description: string
  multi_gpu: boolean
}

interface ServiceProfile {
  catalog: Record<string, CatalogEntry>
  min_compute_cap: number
  max_mb: number
}

interface NodeProfile {
  services: Record<string, ServiceProfile>
}

const props = defineProps<{
  nodeId: string
  servicesCatalog: Record<string, { min_compute_cap: number; max_mb: number; catalog_size: number }>
}>()

const profile = ref<NodeProfile | null>(null)
const loading = ref(true)
const error = ref('')

let fetchAbort: AbortController | null = null

async function fetchProfile() {
  fetchAbort?.abort()
  fetchAbort = new AbortController()
  loading.value = true
  error.value = ''
  try {
    const r = await fetch(`/api/nodes-mgmt/nodes/${props.nodeId}/profile`, {
      signal: fetchAbort.signal,
    })
    if (r.status === 404) { profile.value = null; return }
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    profile.value = await r.json() as NodeProfile
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') return
    error.value = e instanceof Error ? e.message : 'Failed to load profile'
  } finally {
    loading.value = false
  }
}

onMounted(fetchProfile)
onUnmounted(() => { fetchAbort?.abort() })
</script>

<template>
  <section class="hf-panel">
    <h3 class="panel-title">Model Catalog</h3>
    <p class="hf-hint">
      To download a new HuggingFace model,
      <a href="#/fleet" class="hf-link">go to Fleet</a>.
      Models downloaded there are automatically registered in node catalogs.
    </p>

    <div aria-live="polite" aria-atomic="true" class="sr-announce">
      <span v-if="loading">Loading catalog...</span>
    </div>
    <div v-if="error" class="panel-error" role="alert">{{ error }}</div>
    <div v-else-if="!loading && !profile" class="panel-empty">No profile loaded for this node.</div>
    <div v-else-if="!loading && profile" class="catalog-body">
      <div
        v-for="(svcInfo, svcName) in profile.services"
        :key="String(svcName)"
        class="svc-section"
      >
        <h4 class="svc-name">{{ svcName }}</h4>
        <ul class="catalog-list" role="list">
          <li
            v-if="!Object.keys(svcInfo.catalog ?? {}).length"
            class="catalog-empty"
          >
            No models in catalog.
          </li>
          <li
            v-for="(entry, modelName) in (svcInfo.catalog ?? {})"
            :key="String(modelName)"
            class="catalog-item"
          >
            <span class="catalog-model">{{ modelName }}</span>
            <span class="catalog-vram">{{ entry.vram_mb }} MB</span>
            <span v-if="entry.description" class="catalog-desc">{{ entry.description }}</span>
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>

<style scoped>
.hf-panel {
  margin-top: 0.75rem;
  padding: 0.75rem;
  border: 1px solid var(--border, #333);
  border-radius: 6px;
}
.panel-title { margin: 0 0 0.5rem; font-size: 0.9rem; }
.hf-hint { font-size: 0.8rem; color: var(--text-secondary, #888); margin: 0 0 0.75rem; }
.hf-link { color: var(--color-primary, #4080ff); }
.svc-section { margin-bottom: 0.75rem; }
.svc-name {
  margin: 0 0 0.25rem;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-secondary, #888);
}
.catalog-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.2rem; }
.catalog-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.25rem 0.5rem;
  background: var(--bg-secondary, #111);
  border-radius: 4px;
  font-size: 0.8rem;
}
.catalog-model { font-family: monospace; flex: 1; }
.catalog-vram { color: var(--text-secondary, #888); white-space: nowrap; }
.catalog-desc { color: var(--text-secondary, #888); font-size: 0.75rem; flex: 2; }
.catalog-empty, .panel-empty { color: var(--text-secondary, #888); font-size: 0.875rem; }
.sr-announce { min-height: 1.2em; }
.panel-error { color: var(--color-error, #fc8181); font-size: 0.8rem; }
</style>
