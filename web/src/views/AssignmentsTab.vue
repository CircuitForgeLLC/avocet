<template>
  <div class="assignments-tab">

    <!-- ── Toast ───────────────────────────────────────────── -->
    <div v-if="toast" class="toast" :class="toast.type" role="status" aria-live="polite">
      {{ toast.message }}
    </div>

    <!-- ── Assignments section ─────────────────────────────── -->
    <div class="section-header">
      <h2 class="section-title">Task Assignments</h2>
      <button class="btn-primary btn-sm" @click="openNewAssignment">+ New Assignment</button>
    </div>

    <div class="filter-row">
      <label for="product-filter" class="filter-label">Product</label>
      <select id="product-filter" v-model="productFilter" class="filter-select">
        <option value="">All products</option>
        <option v-for="p in allProducts" :key="p" :value="p">{{ p }}</option>
      </select>
    </div>

    <div v-if="assignmentsLoading" class="empty-state">Loading assignments…</div>
    <div v-else-if="assignmentsError" class="error-notice" role="alert">{{ assignmentsError }}</div>
    <div v-else-if="filteredGroups.length === 0" class="empty-state">No assignments yet. Add one above.</div>
    <div v-else class="product-groups">
      <div v-for="group in filteredGroups" :key="group.product" class="product-group">
        <h3 class="product-name">{{ group.product.toUpperCase() }}</h3>
        <div class="assignment-list">
          <div v-for="a in group.assignments" :key="`${a.product}/${a.task}`" class="assignment-row">
            <div class="assignment-main">
              <span class="task-id">{{ a.task }}</span>
              <span
                class="model-name"
                :title="a.model_id"
              >{{ displayModelId(a) }}</span>
              <span v-if="a.vram_mb" class="chip chip-vram">{{ formatVram(a.vram_mb) }}</span>
              <span v-if="a.service_type" class="chip" :class="serviceChipClass(a.service_type)">{{ a.service_type }}</span>
            </div>

            <!-- Node deployment status -->
            <div v-if="deploymentMap[`${a.product}/${a.task}`]" class="node-statuses">
              <span
                v-for="ns in deploymentMap[`${a.product}/${a.task}`]"
                :key="ns.node_id"
                class="node-badge-wrap"
              >
                <span
                  class="node-badge"
                  :class="ns.status"
                  :title="`${ns.node_id}: ${ns.status}`"
                >
                  <span class="node-icon">{{ nodeIcon(ns.status) }}</span>
                  {{ ns.node_id }}
                </span>
                <button
                  v-if="ns.status === 'absent'"
                  class="btn-deploy"
                  :disabled="deploying.has(`${a.product}/${a.task}/${ns.node_id}`)"
                  :title="`Register ${a.model_id} in ${ns.node_id} catalog`"
                  @click="deployModel(a, ns.node_id)"
                >{{ deploying.has(`${a.product}/${a.task}/${ns.node_id}`) ? '…' : 'Register' }}</button>
              </span>
            </div>

            <div class="assignment-actions">
              <button
                v-if="editingKey !== `${a.product}/${a.task}`"
                class="btn-ghost btn-sm"
                @click="startEdit(a)"
              >Edit</button>
              <button
                class="btn-ghost btn-sm btn-danger"
                @click="deleteAssignment(a.product, a.task)"
              >Delete</button>
            </div>

            <!-- Inline edit form -->
            <div v-if="editingKey === `${a.product}/${a.task}`" class="inline-edit">
              <select v-model="editDraft.model_id" class="edit-select" aria-label="Model">
                <option value="" disabled>Select model…</option>
                <option v-for="m in registryModels" :key="m.model_id" :value="m.model_id">
                  {{ m.alias || truncate(m.model_id, 40) }}
                </option>
              </select>
              <input
                v-model="editDraft.description"
                type="text"
                class="edit-input"
                placeholder="Description (optional)"
              />
              <div class="inline-edit-btns">
                <button class="btn-primary btn-sm" :disabled="!editDraft.model_id" @click="saveEdit(a)">Save</button>
                <button class="btn-ghost btn-sm" @click="editingKey = null">Cancel</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Model Registry section ───────────────────────────── -->
    <div class="section-header section-header-mt">
      <h2 class="section-title">Model Registry</h2>
      <button class="btn-primary btn-sm" @click="showRegisterModal = true">Register Model</button>
    </div>

    <div v-if="registryLoading" class="empty-state">Loading model registry…</div>
    <div v-else-if="registryError" class="error-notice" role="alert">{{ registryError }}</div>
    <div v-else-if="registryModels.length === 0" class="empty-state">No models registered yet.</div>
    <div v-else class="registry-table-wrap">
      <table class="registry-table">
        <thead>
          <tr>
            <th>Alias</th>
            <th>Model ID</th>
            <th>VRAM</th>
            <th>Service</th>
            <th class="col-hf">HF Repo</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in registryModels" :key="m.model_id">
            <td>{{ m.alias || '—' }}</td>
            <td>
              <span class="truncated" :title="m.model_id">{{ truncate(m.model_id, 36) }}</span>
            </td>
            <td>{{ formatVram(m.vram_mb) }}</td>
            <td><span class="chip" :class="serviceChipClass(m.service_type)">{{ m.service_type }}</span></td>
            <td class="col-hf">
              <a
                v-if="m.hf_repo"
                :href="`https://huggingface.co/${m.hf_repo}`"
                target="_blank"
                rel="noopener noreferrer"
                class="hf-link"
              >{{ truncate(m.hf_repo, 30) }}</a>
              <span v-else class="text-muted">—</span>
            </td>
            <td>
              <button class="btn-ghost btn-sm btn-danger" @click="deleteModel(m.model_id)">Delete</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ── New Assignment modal ─────────────────────────────── -->
    <div v-if="showNewAssignmentModal" class="modal-backdrop" @click.self="showNewAssignmentModal = false">
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-new-assignment-title">
        <h3 id="modal-new-assignment-title" class="modal-title">New Assignment</h3>
        <label class="form-label">Product</label>
        <input
          v-model="newAssignment.product"
          list="product-list"
          class="form-input"
          placeholder="e.g. peregrine"
          autocomplete="off"
        />
        <datalist id="product-list">
          <option v-for="p in allProducts" :key="p" :value="p" />
        </datalist>

        <label class="form-label">Task ID</label>
        <input
          v-model="newAssignment.task"
          type="text"
          class="form-input"
          placeholder="e.g. cover_letter"
        />

        <label class="form-label">Model</label>
        <select v-model="newAssignment.model_id" class="form-select">
          <option value="" disabled>Select from registry…</option>
          <option v-for="m in registryModels" :key="m.model_id" :value="m.model_id">
            {{ m.alias || truncate(m.model_id, 50) }}
          </option>
        </select>

        <label class="form-label">Description <span class="optional">(optional)</span></label>
        <input
          v-model="newAssignment.description"
          type="text"
          class="form-input"
          placeholder="Human-readable note for operators"
        />

        <div class="modal-actions">
          <button
            class="btn-primary"
            :disabled="!newAssignment.product || !newAssignment.task || !newAssignment.model_id || saving"
            @click="saveNewAssignment"
          >{{ saving ? 'Saving…' : 'Save' }}</button>
          <button class="btn-ghost" @click="showNewAssignmentModal = false">Cancel</button>
        </div>
      </div>
    </div>

    <!-- ── Register Model modal ─────────────────────────────── -->
    <div v-if="showRegisterModal" class="modal-backdrop" @click.self="showRegisterModal = false">
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-register-title">
        <h3 id="modal-register-title" class="modal-title">Register Model</h3>

        <label class="form-label">Model ID <span class="hint">(HuggingFace slug, e.g. ibm-granite/granite-4.1-8b)</span></label>
        <input v-model="newModel.model_id" type="text" class="form-input" placeholder="org/model-name" />

        <label class="form-label">Alias <span class="optional">(optional, short name for assignments)</span></label>
        <input v-model="newModel.alias" type="text" class="form-input" placeholder="e.g. granite-8b" />

        <label class="form-label">Service type</label>
        <select v-model="newModel.service_type" class="form-select">
          <option value="" disabled>Select service…</option>
          <option value="cf-text">cf-text — Language Models</option>
          <option value="cf-stt">cf-stt — Speech Recognition</option>
          <option value="cf-tts">cf-tts — Text to Speech</option>
          <option value="cf-vision">cf-vision — Vision / VLM</option>
          <option value="cf-image">cf-image — Image Generation</option>
          <option value="cf-voice">cf-voice — Audio Classification</option>
          <option value="vllm">vllm — vLLM inference</option>
          <option value="ollama">ollama — Ollama inference</option>
        </select>

        <label class="form-label">VRAM required (MB)</label>
        <input v-model.number="newModel.vram_mb" type="number" min="0" class="form-input" placeholder="e.g. 16384" />

        <label class="form-label">HF Repo <span class="optional">(optional)</span></label>
        <input v-model="newModel.hf_repo" type="text" class="form-input" placeholder="org/repo-name" />

        <label class="form-label">Description <span class="optional">(optional)</span></label>
        <input v-model="newModel.description" type="text" class="form-input" placeholder="Human-readable note" />

        <div class="modal-actions">
          <button
            class="btn-primary"
            :disabled="!newModel.model_id || !newModel.service_type || !newModel.vram_mb || saving"
            @click="saveNewModel"
          >{{ saving ? 'Saving…' : 'Register' }}</button>
          <button class="btn-ghost" @click="showRegisterModal = false">Cancel</button>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

// ── Types ──────────────────────────────────────────────

interface AssignmentNode {
  node_id: string
  status: 'present' | 'absent' | 'vram_tight'
}

interface DeployingKey {
  nodeId: string
  assignmentKey: string
}

interface Assignment {
  product: string
  task: string
  model_id: string
  description: string
  alias?: string
  service_type?: string
  vram_mb?: number
  nodes?: AssignmentNode[]
}

interface RegistryModel {
  model_id: string
  alias: string
  service_type: string
  vram_mb: number
  hf_repo: string
  description: string
}

interface ProductGroup {
  product: string
  assignments: Assignment[]
}

interface Toast {
  message: string
  type: 'success' | 'error'
}

// ── State ──────────────────────────────────────────────

const assignments = ref<Assignment[]>([])
const assignmentsLoading = ref(false)
const assignmentsError = ref<string | null>(null)

const registryModels = ref<RegistryModel[]>([])
const registryLoading = ref(false)
const registryError = ref<string | null>(null)

const productFilter = ref('')
const editingKey = ref<string | null>(null)
const editDraft = ref({ model_id: '', description: '' })

const showNewAssignmentModal = ref(false)
const newAssignment = ref({ product: '', task: '', model_id: '', description: '' })

const showRegisterModal = ref(false)
const newModel = ref({ model_id: '', alias: '', service_type: '', vram_mb: 0, hf_repo: '', description: '' })

const saving = ref(false)
const toast = ref<Toast | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | null = null

const deploying = ref<Set<string>>(new Set())

// ── Derived ────────────────────────────────────────────

const allProducts = computed(() => {
  const seen = new Set<string>()
  for (const a of assignments.value) seen.add(a.product)
  return [...seen].sort()
})

const deploymentMap = computed(() => {
  const map: Record<string, AssignmentNode[]> = {}
  for (const a of assignments.value) {
    if (a.nodes) map[`${a.product}/${a.task}`] = a.nodes
  }
  return map
})

const filteredGroups = computed((): ProductGroup[] => {
  const filtered = productFilter.value
    ? assignments.value.filter(a => a.product === productFilter.value)
    : assignments.value

  const byProduct: Record<string, Assignment[]> = {}
  for (const a of filtered) {
    if (!byProduct[a.product]) byProduct[a.product] = []
    byProduct[a.product].push(a)
  }
  return Object.keys(byProduct)
    .sort()
    .map(product => ({ product, assignments: byProduct[product] }))
})

// ── Helpers ────────────────────────────────────────────

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max - 1) + '…' : s
}

function displayModelId(a: Assignment): string {
  if (a.alias) return a.alias
  const id = a.model_id
  // Show only the model name part (after /) and truncate long slugs
  const short = id.includes('/') ? id.split('/').slice(1).join('/') : id
  return truncate(short, 36)
}

function formatVram(mb: number | undefined): string {
  if (!mb) return ''
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`
  return `${mb} MB`
}

function serviceChipClass(service: string): string {
  return `chip-service-${service.replace(/[^a-z0-9]/g, '-')}`
}

function nodeIcon(status: string): string {
  if (status === 'present') return '✓'
  if (status === 'vram_tight') return '~'
  return '✗'
}

function showToast(message: string, type: 'success' | 'error' = 'success') {
  if (toastTimer) clearTimeout(toastTimer)
  toast.value = { message, type }
  toastTimer = setTimeout(() => { toast.value = null }, 3500)
}

function openNewAssignment() {
  newAssignment.value = { product: '', task: '', model_id: '', description: '' }
  showNewAssignmentModal.value = true
}

function startEdit(a: Assignment) {
  editingKey.value = `${a.product}/${a.task}`
  editDraft.value = { model_id: a.model_id, description: a.description }
}

// ── API ────────────────────────────────────────────────

async function loadAssignments() {
  assignmentsLoading.value = true
  assignmentsError.value = null
  try {
    // Fetch both list and deployment status in parallel
    const [listRes, statusRes] = await Promise.all([
      fetch('/api/cforch/assignments'),
      fetch('/api/cforch/assignments/deployment-status'),
    ])
    if (!listRes.ok) throw new Error(`HTTP ${listRes.status}`)
    const list: Assignment[] = (await listRes.json()).assignments ?? []

    // Merge deployment status into assignments if available
    if (statusRes.ok) {
      const statusList: Assignment[] = (await statusRes.json()).deployment_status ?? []
      const statusMap: Record<string, AssignmentNode[]> = {}
      for (const s of statusList) {
        statusMap[`${s.product}/${s.task}`] = s.nodes ?? []
      }
      for (const a of list) {
        a.nodes = statusMap[`${a.product}/${a.task}`] ?? []
        // Enrich with service_type/vram_mb from status payload
        const s = statusList.find(x => x.product === a.product && x.task === a.task)
        if (s) {
          a.service_type = s.service_type
          a.vram_mb = s.vram_mb
          a.alias = s.alias
        }
      }
    }
    assignments.value = list
  } catch (e) {
    assignmentsError.value = `Could not load assignments: ${e}`
  } finally {
    assignmentsLoading.value = false
  }
}

async function loadRegistry() {
  registryLoading.value = true
  registryError.value = null
  try {
    const res = await fetch('/api/cforch/model-registry')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    registryModels.value = (await res.json()).models ?? []
  } catch (e) {
    registryError.value = `Could not load model registry: ${e}`
  } finally {
    registryLoading.value = false
  }
}

async function saveNewAssignment() {
  saving.value = true
  try {
    const res = await fetch('/api/cforch/assignments', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newAssignment.value),
    })
    if (!res.ok) throw new Error(await res.text())
    showNewAssignmentModal.value = false
    showToast('Assignment saved')
    await loadAssignments()
  } catch (e) {
    showToast(`Save failed: ${e}`, 'error')
  } finally {
    saving.value = false
  }
}

async function saveEdit(a: Assignment) {
  saving.value = true
  try {
    const res = await fetch('/api/cforch/assignments', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        product: a.product,
        task: a.task,
        model_id: editDraft.value.model_id,
        description: editDraft.value.description,
      }),
    })
    if (!res.ok) throw new Error(await res.text())
    editingKey.value = null
    showToast('Assignment updated')
    await loadAssignments()
  } catch (e) {
    showToast(`Update failed: ${e}`, 'error')
  } finally {
    saving.value = false
  }
}

async function deleteAssignment(product: string, task: string) {
  if (!confirm(`Delete assignment ${product}.${task}?`)) return
  try {
    const res = await fetch(
      `/api/cforch/assignments/${encodeURIComponent(product)}/${encodeURIComponent(task)}`,
      { method: 'DELETE' },
    )
    if (!res.ok) throw new Error(await res.text())
    showToast('Assignment deleted')
    await loadAssignments()
  } catch (e) {
    showToast(`Delete failed: ${e}`, 'error')
  }
}

async function saveNewModel() {
  saving.value = true
  try {
    const res = await fetch('/api/cforch/model-registry', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newModel.value),
    })
    if (!res.ok) throw new Error(await res.text())
    showRegisterModal.value = false
    showToast('Model registered')
    await loadRegistry()
  } catch (e) {
    showToast(`Register failed: ${e}`, 'error')
  } finally {
    saving.value = false
  }
}

async function deleteModel(model_id: string) {
  if (!confirm(`Remove ${model_id} from the registry?`)) return
  try {
    const res = await fetch(
      `/api/cforch/model-registry/${encodeURIComponent(model_id)}`,
      { method: 'DELETE' },
    )
    if (!res.ok) throw new Error(await res.text())
    showToast('Model removed')
    await loadRegistry()
  } catch (e) {
    showToast(`Delete failed: ${e}`, 'error')
  }
}

async function deployModel(a: Assignment, nodeId: string) {
  const key = `${a.product}/${a.task}/${nodeId}`
  if (deploying.value.has(key)) return

  // Look up hf_repo from registry for cleaner path construction
  const regEntry = registryModels.value.find(m => m.model_id === a.model_id)
  const hf_repo = regEntry?.hf_repo ?? ''
  const service_type = a.service_type ?? regEntry?.service_type ?? ''
  const vram_mb = a.vram_mb ?? regEntry?.vram_mb ?? 0
  const description = regEntry?.alias ? `${regEntry.alias} (via assignments)` : ''

  if (!service_type) {
    showToast(`No service type for model ${a.model_id}`, 'error')
    return
  }

  deploying.value = new Set([...deploying.value, key])
  try {
    const res = await fetch(`/api/nodes-mgmt/nodes/${encodeURIComponent(nodeId)}/models/deploy`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_id: a.model_id, service_type, vram_mb, hf_repo, description }),
    })
    if (!res.ok) throw new Error(await res.text())
    const data = await res.json()
    showToast(`Registered ${a.model_id} on ${nodeId} at ${data.path}`)

    // Optimistic update: flip node to 'present' immediately so the Register button
    // disappears before the coordinator reload confirms. loadAssignments() reconciles
    // with real server state on the next round-trip.
    assignments.value = assignments.value.map(asgn => {
      if (asgn.product !== a.product || asgn.task !== a.task) return asgn
      return {
        ...asgn,
        nodes: (asgn.nodes ?? []).map(ns =>
          ns.node_id === nodeId ? { ...ns, status: 'present' as const } : ns
        ),
      }
    })

    await loadAssignments()
  } catch (e) {
    showToast(`Deploy failed: ${e}`, 'error')
  } finally {
    deploying.value = new Set([...deploying.value].filter(k => k !== key))
  }
}

onMounted(() => {
  loadAssignments()
  loadRegistry()
})
</script>

<style scoped>
.assignments-tab {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

/* ── Toast ── */
.toast {
  position: fixed;
  bottom: 1.5rem;
  right: 1.5rem;
  padding: 0.65rem 1.1rem;
  border-radius: 0.5rem;
  font-size: 0.88rem;
  font-weight: 500;
  z-index: 200;
  box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}
.toast.success {
  background: var(--color-success, #2a8050);
  color: #fff;
}
.toast.error {
  background: var(--color-danger, #b03030);
  color: #fff;
}

/* ── Section headers ── */
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}
.section-header-mt {
  margin-top: 1.5rem;
}
.section-title {
  font-size: 1rem;
  font-weight: 600;
  color: var(--app-primary, #2A6080);
  margin: 0;
}

/* ── Filter row ── */
.filter-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}
.filter-label {
  font-size: 0.85rem;
  color: var(--color-text-muted, #6b7a99);
}
.filter-select {
  padding: 0.3rem 0.6rem;
  font-size: 0.85rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.4rem;
  background: var(--color-surface, #fff);
  color: var(--color-text, #1a2030);
}

/* ── Product groups ── */
.product-groups {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.product-group {}
.product-name {
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--color-text-muted, #6b7a99);
  text-transform: uppercase;
  margin: 0 0 0.4rem;
}
.assignment-list {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

/* ── Assignment rows ── */
.assignment-row {
  background: var(--color-surface-raised, #f0f4fa);
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  padding: 0.65rem 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.assignment-main {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.task-id {
  font-family: var(--font-mono, monospace);
  font-size: 0.88rem;
  font-weight: 600;
  color: var(--color-text, #1a2030);
  min-width: 0;
}
.model-name {
  font-size: 0.85rem;
  color: var(--color-text-muted, #6b7a99);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 280px;
  cursor: default;
}
.assignment-actions {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
}

/* ── Node status badges ── */
.node-statuses {
  display: flex;
  gap: 0.35rem;
  flex-wrap: wrap;
}
.node-badge-wrap {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
}
.node-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  font-size: 0.78rem;
  padding: 0.15rem 0.5rem;
  border-radius: 0.35rem;
  font-weight: 500;
}
.node-badge.present {
  background: color-mix(in srgb, var(--color-success, #2a8050) 15%, transparent);
  color: var(--color-success, #2a8050);
  border: 1px solid color-mix(in srgb, var(--color-success, #2a8050) 30%, transparent);
}
.node-badge.absent {
  background: color-mix(in srgb, var(--color-danger, #b03030) 12%, transparent);
  color: var(--color-danger, #b03030);
  border: 1px solid color-mix(in srgb, var(--color-danger, #b03030) 25%, transparent);
}
.node-badge.vram_tight {
  background: color-mix(in srgb, #c08030 15%, transparent);
  color: #8a5500;
  border: 1px solid color-mix(in srgb, #c08030 30%, transparent);
}
.node-icon {
  font-size: 0.85em;
}
.btn-deploy {
  padding: 0.1rem 0.4rem;
  font-size: 0.72rem;
  font-weight: 600;
  background: color-mix(in srgb, var(--app-primary, #2A6080) 12%, transparent);
  color: var(--app-primary, #2A6080);
  border: 1px solid color-mix(in srgb, var(--app-primary, #2A6080) 30%, transparent);
  border-radius: 0.3rem;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s;
}
.btn-deploy:hover:not(:disabled) {
  background: color-mix(in srgb, var(--app-primary, #2A6080) 22%, transparent);
}
.btn-deploy:disabled { opacity: 0.5; cursor: default; }

/* ── Inline edit ── */
.inline-edit {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  padding-top: 0.35rem;
  border-top: 1px solid var(--color-border, #d0d7e8);
}
.edit-select,
.edit-input {
  flex: 1;
  min-width: 160px;
  padding: 0.35rem 0.55rem;
  font-size: 0.85rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.4rem;
  background: var(--color-surface, #fff);
  color: var(--color-text, #1a2030);
}
.inline-edit-btns {
  display: flex;
  gap: 0.35rem;
  align-items: center;
}

/* ── Registry table ── */
.registry-table-wrap {
  overflow-x: auto;
  border-radius: 0.5rem;
  border: 1px solid var(--color-border, #d0d7e8);
}
.registry-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.registry-table th {
  text-align: left;
  padding: 0.5rem 0.75rem;
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--color-text-muted, #6b7a99);
  background: var(--color-surface-raised, #f0f4fa);
  border-bottom: 1px solid var(--color-border, #d0d7e8);
  white-space: nowrap;
}
.registry-table td {
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--color-border, #d0d7e8);
  vertical-align: middle;
}
.registry-table tbody tr:last-child td {
  border-bottom: none;
}
.truncated {
  display: inline-block;
  max-width: 220px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
  cursor: default;
}
.hf-link {
  color: var(--app-primary, #2A6080);
  text-decoration: none;
  font-size: 0.82rem;
}
.hf-link:hover { text-decoration: underline; }
.text-muted { color: var(--color-text-muted, #6b7a99); }

/* ── Chips ── */
.chip {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 0.35rem;
  font-size: 0.75rem;
  font-weight: 600;
  white-space: nowrap;
}
.chip-vram {
  background: color-mix(in srgb, var(--app-primary, #2A6080) 12%, transparent);
  color: var(--app-primary, #2A6080);
  border: 1px solid color-mix(in srgb, var(--app-primary, #2A6080) 25%, transparent);
}
/* service chips — match ModelsView convention */
.chip-service-cf-text   { background: #e8f0fe; color: #1a5276; border: 1px solid #a9c4e8; }
.chip-service-cf-stt    { background: #eaf6ea; color: #1e6b3a; border: 1px solid #a2d9b1; }
.chip-service-cf-tts    { background: #fdf3e3; color: #7d4e00; border: 1px solid #e8c98a; }
.chip-service-cf-vision { background: #f3e8fd; color: #5b2d8e; border: 1px solid #c8a0e8; }
.chip-service-cf-image  { background: #fce8f0; color: #8e1a4f; border: 1px solid #e8a0c0; }
.chip-service-cf-voice  { background: #e8f8fc; color: #0a5c6e; border: 1px solid #88d0e0; }
.chip-service-vllm      { background: #f5ece0; color: #7a3800; border: 1px solid #d4a87a; }
.chip-service-ollama    { background: #eeeeee; color: #444;    border: 1px solid #ccc;    }

/* ── Buttons ── */
.btn-primary {
  padding: 0.45rem 1rem;
  background: var(--app-primary, #2A6080);
  color: #fff;
  border: none;
  border-radius: 0.4rem;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s;
}
.btn-primary:disabled { opacity: 0.5; cursor: default; }
.btn-primary:not(:disabled):hover { opacity: 0.88; }

.btn-ghost {
  padding: 0.35rem 0.75rem;
  background: transparent;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.4rem;
  font-size: 0.82rem;
  color: var(--color-text-muted, #6b7a99);
  cursor: pointer;
  transition: background 0.15s;
}
.btn-ghost:hover { background: var(--color-surface-raised, #e4ebf5); }
.btn-ghost.btn-danger { color: var(--color-danger, #b03030); border-color: color-mix(in srgb, var(--color-danger, #b03030) 30%, transparent); }
.btn-ghost.btn-danger:hover { background: color-mix(in srgb, var(--color-danger, #b03030) 10%, transparent); }

.btn-sm { padding: 0.3rem 0.65rem; font-size: 0.8rem; }

/* ── Empty / error states ── */
.empty-state {
  padding: 1.5rem;
  text-align: center;
  color: var(--color-text-muted, #6b7a99);
  font-size: 0.9rem;
  background: var(--color-surface-raised, #f0f4fa);
  border: 1px dashed var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
}
.error-notice {
  padding: 0.75rem 1rem;
  background: color-mix(in srgb, var(--color-danger, #b03030) 10%, transparent);
  color: var(--color-danger, #b03030);
  border: 1px solid color-mix(in srgb, var(--color-danger, #b03030) 25%, transparent);
  border-radius: 0.4rem;
  font-size: 0.87rem;
}

/* ── Modal ── */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 1rem;
}
.modal {
  background: var(--color-surface, #fff);
  border-radius: 0.65rem;
  padding: 1.5rem;
  width: 100%;
  max-width: 480px;
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  box-shadow: 0 8px 32px rgba(0,0,0,0.18);
  max-height: 90vh;
  overflow-y: auto;
}
.modal-title {
  font-size: 1rem;
  font-weight: 700;
  color: var(--app-primary, #2A6080);
  margin: 0 0 0.25rem;
}
.form-label {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--color-text-muted, #6b7a99);
}
.form-input,
.form-select {
  padding: 0.4rem 0.65rem;
  font-size: 0.88rem;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.4rem;
  background: var(--color-surface, #fff);
  color: var(--color-text, #1a2030);
  width: 100%;
  box-sizing: border-box;
}
.form-input:focus, .form-select:focus {
  outline: 2px solid var(--app-primary, #2A6080);
  outline-offset: 1px;
}
.modal-actions {
  display: flex;
  gap: 0.5rem;
  justify-content: flex-end;
  margin-top: 0.25rem;
}
.optional, .hint {
  font-weight: 400;
  color: var(--color-text-muted, #6b7a99);
  font-size: 0.78rem;
}

/* ── Responsive ── */
@media (max-width: 600px) {
  .assignment-main { flex-direction: column; align-items: flex-start; }
  .col-hf { display: none; }
  .model-name { max-width: 100%; }
  .modal { padding: 1rem; }
}
</style>
