<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { FullProfile, ServiceDefinition, CatalogEntryFull } from '../../types/nodes'
import ServiceFormModal from './ServiceFormModal.vue'
import CatalogEntryFormModal from './CatalogEntryFormModal.vue'

const props = defineProps<{
  nodeId: string
  initialProfile: FullProfile | null
}>()
const emit = defineEmits<{ saved: []; close: [] }>()

// Deep-clone initial profile so edits don't mutate the parent's data
const profile = ref<FullProfile>(
  props.initialProfile
    ? JSON.parse(JSON.stringify(props.initialProfile))
    : { services: {}, nodes: {} }
)

const saving = ref(false)
const generating = ref(false)
const opError = ref('')
const expandedSvcs = ref<Set<string>>(new Set())

// Service modal
const showSvcModal = ref(false)
const editingSvcName = ref<string | undefined>()
const editingSvcDef = ref<ServiceDefinition | undefined>()

// Catalog modal
const showCatalogModal = ref(false)
const catalogTargetSvc = ref('')
const editingModelName = ref<string | undefined>()
const editingEntry = ref<CatalogEntryFull | undefined>()

// ── Generate nodes section from coordinator ────────────────────────────────────

async function generate() {
  generating.value = true
  opError.value = ''
  try {
    const r = await fetch(`/api/nodes-mgmt/nodes/${props.nodeId}/profile/generate`, { method: 'POST' })
    if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error((d as {detail?: string}).detail ?? `HTTP ${r.status}`) }
    const generated = await r.json() as FullProfile
    // Merge: keep current services edits, replace nodes section
    profile.value = { ...generated, services: profile.value.services }
  } catch (e) {
    opError.value = e instanceof Error ? e.message : 'Generate failed'
  } finally {
    generating.value = false
  }
}

// ── Save full profile ──────────────────────────────────────────────────────────

async function save() {
  saving.value = true
  opError.value = ''
  try {
    const r = await fetch(`/api/nodes-mgmt/nodes/${props.nodeId}/profile`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile: profile.value }),
    })
    if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error((d as {detail?: string}).detail ?? `HTTP ${r.status}`) }
    emit('saved')
  } catch (e) {
    opError.value = e instanceof Error ? e.message : 'Save failed'
  } finally {
    saving.value = false
  }
}

// ── Service CRUD ───────────────────────────────────────────────────────────────

function openAddService() {
  editingSvcName.value = undefined
  editingSvcDef.value = undefined
  showSvcModal.value = true
}

function openEditService(name: string) {
  editingSvcName.value = name
  editingSvcDef.value = JSON.parse(JSON.stringify(profile.value.services[name]))
  showSvcModal.value = true
}

function onServiceSaved(name: string, def: ServiceDefinition) {
  profile.value = { ...profile.value, services: { ...profile.value.services, [name]: def } }
  expandedSvcs.value = new Set([...expandedSvcs.value, name])
  showSvcModal.value = false
}

function deleteService(name: string) {
  if (!confirm(`Remove service "${name}" from this profile?`)) return
  const svcs = { ...profile.value.services }
  delete svcs[name]
  profile.value = { ...profile.value, services: svcs }
  expandedSvcs.value = new Set([...expandedSvcs.value].filter(s => s !== name))
}

function toggleSvc(name: string) {
  const s = new Set(expandedSvcs.value)
  s.has(name) ? s.delete(name) : s.add(name)
  expandedSvcs.value = s
}

// ── Catalog CRUD ───────────────────────────────────────────────────────────────

function openAddCatalogEntry(svcName: string) {
  catalogTargetSvc.value = svcName
  editingModelName.value = undefined
  editingEntry.value = undefined
  showCatalogModal.value = true
}

function openEditCatalogEntry(svcName: string, modelName: string) {
  catalogTargetSvc.value = svcName
  editingModelName.value = modelName
  editingEntry.value = JSON.parse(JSON.stringify(profile.value.services[svcName].catalog![modelName]))
  showCatalogModal.value = true
}

function onCatalogEntrySaved(svcName: string, modelName: string, entry: CatalogEntryFull) {
  const svcs = { ...profile.value.services }
  const svc = { ...svcs[svcName], catalog: { ...(svcs[svcName].catalog ?? {}), [modelName]: entry } }
  svcs[svcName] = svc
  profile.value = { ...profile.value, services: svcs }
  showCatalogModal.value = false
}

function deleteCatalogEntry(svcName: string, modelName: string) {
  if (!confirm(`Remove model "${modelName}" from ${svcName} catalog?`)) return
  const svcs = { ...profile.value.services }
  const catalog = { ...(svcs[svcName].catalog ?? {}) }
  delete catalog[modelName]
  svcs[svcName] = { ...svcs[svcName], catalog }
  profile.value = { ...profile.value, services: svcs }
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function gpuList() {
  return (profile.value.nodes[props.nodeId]?.gpus ?? [])
}

function serviceCount() {
  return Object.keys(profile.value.services).length
}

// ── Ollama model suggestions ───────────────────────────────────────────────────

interface OllamaModel { name: string; size: number }
const ollamaModels = ref<OllamaModel[]>([])
const ollamaLoading = ref(false)

onMounted(async () => {
  ollamaLoading.value = true
  try {
    const r = await fetch(`/api/nodes-mgmt/nodes/${props.nodeId}/models/ollama`)
    if (r.ok) {
      const d = await r.json() as { models?: OllamaModel[] }
      ollamaModels.value = d.models ?? []
    }
  } catch { /* Ollama offline — silently skip */ }
  finally { ollamaLoading.value = false }
})

function ollamaNotInCatalog(svcName: string): OllamaModel[] {
  const catalog = profile.value.services[svcName]?.catalog ?? {}
  return ollamaModels.value.filter(m => !(m.name in catalog))
}

function openAddFromOllama(svcName: string, modelName: string) {
  catalogTargetSvc.value = svcName
  editingModelName.value = modelName
  editingEntry.value = {
    path: profile.value.services[svcName]?.model_base_path
      ? `${profile.value.services[svcName].model_base_path}/${modelName}`
      : '',
    vram_mb: 0,
  }
  showCatalogModal.value = true
}

function formatMb(bytes: number): string {
  return bytes >= 1_000_000_000
    ? `${(bytes / 1_073_741_824).toFixed(1)} GB`
    : `${Math.round(bytes / 1_048_576)} MB`
}

// ── Pull model onto node ───────────────────────────────────────────────────────

const pullName = ref('')
const pulling = ref(false)
const pullStatus = ref('')
const pullPct = ref(0)
const pullError = ref('')
let pullAbort: AbortController | null = null

async function doPull() {
  const name = pullName.value.trim()
  if (!name || pulling.value) return
  pulling.value = true
  pullStatus.value = 'Starting…'
  pullError.value = ''
  pullPct.value = 0
  pullAbort?.abort()
  pullAbort = new AbortController()

  try {
    const resp = await fetch(`/api/nodes-mgmt/nodes/${props.nodeId}/models/ollama/pull`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
      signal: pullAbort.signal,
    })
    if (!resp.ok || !resp.body) {
      pullError.value = `HTTP ${resp.status}`
      return
    }
    const reader = resp.body.getReader()
    const dec = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() ?? ''
      for (const line of lines) {
        if (!line.startsWith('data:')) continue
        try {
          const d = JSON.parse(line.slice(5)) as {
            status?: string; completed?: number; total?: number; error?: string; done?: boolean
          }
          if (d.error) { pullError.value = d.error; return }
          pullStatus.value = d.status ?? ''
          if (d.total && d.total > 0) pullPct.value = Math.round((d.completed ?? 0) / d.total * 100)
          if (d.done) {
            pullName.value = ''
            pullPct.value = 100
            // Refresh Ollama model list so new model appears in suggest chips
            const r = await fetch(`/api/nodes-mgmt/nodes/${props.nodeId}/models/ollama`)
            if (r.ok) { const d2 = await r.json() as { models?: OllamaModel[] }; ollamaModels.value = d2.models ?? [] }
          }
        } catch { /* skip malformed SSE line */ }
      }
    }
  } catch (e) {
    if (e instanceof Error && e.name !== 'AbortError') pullError.value = e.message
  } finally {
    pulling.value = false
    if (pullPct.value === 100) setTimeout(() => { pullStatus.value = ''; pullPct.value = 0 }, 2000)
  }
}
</script>

<template>
  <section class="pep" aria-label="Profile editor">
    <!-- Header -->
    <div class="pep-header">
      <div class="pep-title-row">
        <h3 class="pep-title">Profile — {{ nodeId }}</h3>
        <span class="pep-svc-count">{{ serviceCount() }} service{{ serviceCount() === 1 ? '' : 's' }}</span>
      </div>
      <div class="pep-actions">
        <button class="btn-secondary btn-sm" :disabled="generating" @click="generate">
          {{ generating ? 'Refreshing…' : 'Refresh Hardware' }}
        </button>
        <button class="btn-primary btn-sm" :disabled="saving" @click="save">
          {{ saving ? 'Saving…' : 'Save Profile' }}
        </button>
        <button class="btn-icon-lg" aria-label="Close editor" @click="emit('close')">✕</button>
      </div>
    </div>

    <div v-if="opError" class="pep-error" role="alert">{{ opError }}</div>

    <!-- Meta fields -->
    <div class="pep-meta">
      <label class="meta-label" for="pep-vram">vram_total_mb</label>
      <input id="pep-vram" v-model.number="profile.vram_total_mb" type="number" min="0" class="meta-input" />
      <label class="meta-label" for="pep-evict">eviction_timeout_s</label>
      <input id="pep-evict" v-model.number="profile.eviction_timeout_s" type="number" min="0" step="0.5" class="meta-input" />
    </div>

    <!-- Hardware summary -->
    <div v-if="gpuList().length" class="hw-section">
      <span class="hw-label">Hardware</span>
      <span v-for="g in gpuList()" :key="g.id" class="hw-gpu">
        GPU {{ g.id }}: {{ g.card || 'unknown' }} · {{ g.vram_mb }} MB · sm{{ g.compute_cap ?? '?' }}
      </span>
      <span v-if="!gpuList().length" class="hw-none">No hardware data — click Refresh Hardware.</span>
    </div>
    <div v-else class="hw-section">
      <span class="hw-none">No hardware data — click Refresh Hardware to seed from coordinator.</span>
    </div>

    <!-- Services -->
    <div class="svcs-header">
      <span class="svcs-title">Services</span>
      <button class="btn-secondary btn-sm" @click="openAddService">+ Add Service</button>
    </div>

    <div v-if="serviceCount() === 0" class="svcs-empty">
      No services defined. Add a service to configure what can run on this node.
    </div>

    <ul class="svcs-list" role="list">
      <li
        v-for="(def, svcName) in profile.services"
        :key="String(svcName)"
        class="svc-item"
      >
        <!-- Service row header -->
        <div class="svc-row">
          <button
            class="svc-toggle"
            :aria-expanded="expandedSvcs.has(String(svcName))"
            @click="toggleSvc(String(svcName))"
          >
            <span class="svc-arrow">{{ expandedSvcs.has(String(svcName)) ? '▾' : '▸' }}</span>
            <span class="svc-name">{{ svcName }}</span>
          </button>
          <span class="svc-badges">
            <span class="badge">{{ def.max_mb }} MB</span>
            <span class="badge">p{{ def.priority }}</span>
            <span v-if="def.shared" class="badge badge--blue">shared</span>
            <span v-if="def.managed" class="badge badge--dim">managed</span>
            <span v-if="def.catalog" class="badge badge--dim">{{ Object.keys(def.catalog).length }} models</span>
          </span>
          <div class="svc-btns">
            <button class="btn-secondary btn-xs" @click="openEditService(String(svcName))">Edit</button>
            <button class="btn-danger btn-xs" @click="deleteService(String(svcName))">Delete</button>
          </div>
        </div>

        <!-- Expanded catalog -->
        <div v-if="expandedSvcs.has(String(svcName))" class="svc-detail">
          <div class="svc-detail-meta">
            <span v-if="def.min_compute_cap">min sm{{ def.min_compute_cap }}</span>
            <span v-if="def.max_concurrent">max_concurrent: {{ def.max_concurrent }}</span>
            <span v-if="def.idle_stop_after_s">idle_stop: {{ def.idle_stop_after_s }}s</span>
            <span v-if="def.always_on" class="badge badge--blue">always_on</span>
          </div>

          <!-- Ollama model suggestions + pull -->
          <div class="ollama-suggest">
            <div class="suggest-row">
              <span class="suggest-label">On node (Ollama):</span>
              <span v-if="ollamaLoading" class="suggest-loading">loading…</span>
              <template v-else-if="ollamaNotInCatalog(String(svcName)).length">
                <button
                  v-for="m in ollamaNotInCatalog(String(svcName))"
                  :key="m.name"
                  class="suggest-chip"
                  :title="`Add ${m.name} (${formatMb(m.size)}) to this service catalog`"
                  @click="openAddFromOllama(String(svcName), m.name)"
                >
                  + {{ m.name }} <span class="chip-size">{{ formatMb(m.size) }}</span>
                </button>
              </template>
              <span v-else-if="!ollamaLoading" class="suggest-none">All Ollama models already in catalog.</span>
            </div>

            <!-- Pull model onto this node -->
            <div class="pull-row">
              <input
                v-model="pullName"
                class="pull-input"
                placeholder="Pull model on node (e.g. llama3:8b)"
                :disabled="pulling"
                @keyup.enter="doPull"
              />
              <button class="btn-pull" :disabled="pulling || !pullName.trim()" @click="doPull">
                {{ pulling ? 'Pulling…' : 'Pull' }}
              </button>
            </div>
            <div v-if="pulling || pullPct > 0" class="pull-progress">
              <div class="pull-bar"><div class="pull-fill" :style="{ width: pullPct + '%' }" /></div>
              <span class="pull-status">{{ pullStatus }}</span>
            </div>
            <div v-if="pullError" class="pull-err" role="alert">{{ pullError }}</div>
          </div>

          <div class="catalog-header">
            <span class="catalog-title">Catalog</span>
            <button class="btn-link" @click="openAddCatalogEntry(String(svcName))">+ Add Model</button>
          </div>

          <div v-if="!def.catalog || !Object.keys(def.catalog).length" class="catalog-empty">
            No catalog entries. Only services like cf-text need a catalog.
          </div>
          <ul v-else class="catalog-list" role="list">
            <li
              v-for="(entry, modelName) in def.catalog"
              :key="String(modelName)"
              class="catalog-item"
            >
              <span class="catalog-model">{{ modelName }}</span>
              <span class="catalog-vram">{{ entry.vram_mb }} MB</span>
              <span v-if="entry.multi_gpu" class="badge badge--dim">multi-gpu</span>
              <span v-if="entry.description" class="catalog-desc">{{ entry.description }}</span>
              <div class="catalog-btns">
                <button class="btn-secondary btn-xs" @click="openEditCatalogEntry(String(svcName), String(modelName))">Edit</button>
                <button class="btn-danger btn-xs" @click="deleteCatalogEntry(String(svcName), String(modelName))">✕</button>
              </div>
            </li>
          </ul>
        </div>
      </li>
    </ul>
  </section>

  <!-- Service form modal -->
  <ServiceFormModal
    v-if="showSvcModal"
    :service-name="editingSvcName"
    :definition="editingSvcDef"
    @save="onServiceSaved"
    @cancel="showSvcModal = false"
  />

  <!-- Catalog entry form modal -->
  <CatalogEntryFormModal
    v-if="showCatalogModal"
    :svc-name="catalogTargetSvc"
    :model-name="editingModelName"
    :entry="editingEntry"
    @save="onCatalogEntrySaved"
    @cancel="showCatalogModal = false"
  />
</template>

<style scoped>
.pep {
  margin-top: 0.75rem;
  padding: 1rem;
  border: 1px solid var(--color-primary);
  border-radius: 6px;
  background: var(--color-surface-raised);
  color: var(--color-text);
}
.pep-header {
  display: flex; align-items: center; justify-content: space-between; gap: 0.5rem;
  margin-bottom: 0.75rem; flex-wrap: wrap;
}
.pep-title-row { display: flex; align-items: baseline; gap: 0.5rem; }
.pep-title { margin: 0; font-size: 0.95rem; font-weight: 600; color: var(--color-text); }
.pep-svc-count { font-size: 0.75rem; color: var(--color-text-muted); }
.pep-actions { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }
.pep-error { color: var(--color-error); font-size: 0.8rem; margin-bottom: 0.5rem; }
.pep-meta {
  display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;
  padding: 0.5rem; background: var(--color-surface-alt); border-radius: 4px; margin-bottom: 0.75rem;
}
.meta-label { font-size: 0.8rem; color: var(--color-text-muted); }
.meta-input {
  width: 7rem; background: var(--color-surface); border: 1px solid var(--color-border);
  border-radius: 4px; padding: 0.2rem 0.4rem; color: var(--color-text); font-size: 0.8rem;
}
.hw-section {
  display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem;
  font-size: 0.8rem; color: var(--color-text-muted);
  padding: 0.4rem 0.5rem; border-radius: 4px; background: var(--color-surface-alt);
  margin-bottom: 0.75rem;
}
.hw-label { font-weight: 600; color: var(--color-text); }
.hw-gpu { font-family: monospace; color: var(--color-text); }
.hw-none { font-style: italic; }
.svcs-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 0.5rem;
}
.svcs-title { font-size: 0.85rem; font-weight: 600; color: var(--color-text); }
.svcs-empty { color: var(--color-text-muted); font-size: 0.85rem; padding: 0.5rem 0; }
.svcs-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.4rem; }
.svc-item { border: 1px solid var(--color-border); border-radius: 4px; overflow: hidden; }
.svc-row {
  display: flex; align-items: center; gap: 0.5rem; padding: 0.4rem 0.5rem;
  background: var(--color-surface-alt); flex-wrap: wrap;
}
.svc-toggle {
  display: flex; align-items: center; gap: 0.35rem;
  background: none; border: none; cursor: pointer; color: var(--color-text); padding: 0; flex: 1; min-width: 0;
}
.svc-arrow { font-size: 0.7rem; color: var(--color-text-muted); }
.svc-name { font-size: 0.875rem; font-weight: 500; font-family: monospace; }
.svc-badges { display: flex; gap: 0.3rem; flex-wrap: wrap; }
.svc-btns { display: flex; gap: 0.3rem; margin-left: auto; }
.svc-detail { padding: 0.5rem 0.75rem; display: flex; flex-direction: column; gap: 0.5rem; background: var(--color-surface-raised); }
.svc-detail-meta {
  display: flex; gap: 0.5rem; flex-wrap: wrap;
  font-size: 0.78rem; color: var(--color-text-muted);
}
.ollama-suggest {
  display: flex; flex-direction: column; gap: 0.35rem;
  padding: 0.4rem 0.5rem;
  background: var(--color-primary-light);
  border: 1px solid var(--color-border-light);
  border-radius: 4px;
  font-size: 0.78rem;
}
.suggest-row { display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem; }
.suggest-label { color: var(--color-text-muted); font-weight: 500; white-space: nowrap; }
.suggest-loading { color: var(--color-text-muted); font-style: italic; }
.suggest-none { color: var(--color-text-muted); font-style: italic; }
.suggest-chip {
  display: inline-flex; align-items: center; gap: 0.25rem;
  padding: 0.15rem 0.45rem;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: 3px;
  color: var(--color-text);
  cursor: pointer;
  font-size: 0.78rem;
  transition: border-color 0.15s, background 0.15s;
}
.suggest-chip:hover { border-color: var(--app-primary); background: var(--color-surface-alt); }
.chip-size { color: var(--color-text-muted); font-size: 0.72rem; }
.pull-row { display: flex; gap: 0.4rem; align-items: center; }
.pull-input {
  flex: 1;
  padding: 0.25rem 0.5rem;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  color: var(--color-text);
  font-size: 0.78rem;
  font-family: var(--font-mono, monospace);
}
.pull-input:disabled { opacity: 0.5; }
.btn-pull {
  padding: 0.25rem 0.6rem;
  background: var(--app-primary);
  color: var(--color-text-inverse);
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.78rem;
  white-space: nowrap;
}
.btn-pull:hover:not(:disabled) { background: var(--app-primary-hover); }
.btn-pull:disabled { opacity: 0.5; cursor: not-allowed; }
.pull-progress { display: flex; align-items: center; gap: 0.4rem; }
.pull-bar {
  flex: 1; height: 6px;
  background: var(--color-border);
  border-radius: 3px; overflow: hidden;
}
.pull-fill { height: 100%; background: var(--app-primary); transition: width 0.2s; }
.pull-status { color: var(--color-text-muted); font-size: 0.72rem; white-space: nowrap; max-width: 14rem; overflow: hidden; text-overflow: ellipsis; }
.pull-err { color: var(--color-error); font-size: 0.75rem; }
.catalog-header { display: flex; align-items: center; justify-content: space-between; }
.catalog-title { font-size: 0.8rem; font-weight: 600; color: var(--color-text-muted); text-transform: uppercase; letter-spacing: 0.05em; }
.catalog-empty { font-size: 0.8rem; color: var(--color-text-muted); font-style: italic; }
.catalog-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.25rem; }
.catalog-item {
  display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap;
  padding: 0.25rem 0.5rem; background: var(--color-surface-alt); border-radius: 3px; font-size: 0.8rem;
  color: var(--color-text);
}
.catalog-model { font-family: monospace; flex: 1; min-width: 12rem; }
.catalog-vram { color: var(--color-text-muted); white-space: nowrap; }
.catalog-desc { color: var(--color-text-muted); flex: 2; font-size: 0.75rem; }
.catalog-btns { display: flex; gap: 0.25rem; margin-left: auto; }
.badge {
  padding: 0.1rem 0.4rem; border-radius: 3px; font-size: 0.72rem;
  background: var(--color-surface); border: 1px solid var(--color-border); color: var(--color-text);
}
.badge--blue { border-color: var(--color-primary); color: var(--color-primary); background: var(--color-primary-light); }
.badge--dim { opacity: 0.75; }
.btn-link { background: none; border: none; color: var(--color-accent); cursor: pointer; font-size: 0.8rem; padding: 0; }
.btn-link:hover { color: var(--color-accent-hover); }
.btn-primary {
  background: var(--color-primary); color: var(--color-text-inverse); border: none;
  border-radius: 4px; cursor: pointer; font-size: 0.8rem;
}
.btn-primary:hover { background: var(--color-primary-hover); }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-secondary {
  background: transparent; border: 1px solid var(--color-border); color: var(--color-text);
  border-radius: 4px; cursor: pointer; font-size: 0.8rem;
}
.btn-secondary:hover { background: var(--color-surface-alt); }
.btn-secondary:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-danger {
  background: transparent; border: 1px solid var(--color-error); color: var(--color-error);
  border-radius: 4px; cursor: pointer; font-size: 0.8rem;
}
.btn-danger:hover { background: var(--color-surface-alt); }
.btn-sm { padding: 0.3rem 0.6rem; }
.btn-xs { padding: 0.15rem 0.4rem; }
.btn-icon-lg { background: none; border: none; color: var(--color-text-muted); cursor: pointer; font-size: 1rem; padding: 0.2rem 0.3rem; }
.btn-icon-lg:hover { color: var(--color-text); }
</style>
