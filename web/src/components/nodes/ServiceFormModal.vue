<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import type { ServiceDefinition } from '../../types/nodes'

const props = defineProps<{
  serviceName?: string
  definition?: ServiceDefinition
}>()
const emit = defineEmits<{
  save: [name: string, def: ServiceDefinition]
  cancel: []
}>()

const name = ref(props.serviceName ?? '')
const maxMb = ref(props.definition?.max_mb ?? 0)
const priority = ref(props.definition?.priority ?? 1)
const minCap = ref(props.definition?.min_compute_cap ?? 0)
const prefCap = ref<number | ''>(props.definition?.preferred_compute_cap ?? '')
const shared = ref(props.definition?.shared ?? false)
const maxConcurrent = ref<number | ''>(props.definition?.max_concurrent ?? '')
const idleStop = ref<number | ''>(props.definition?.idle_stop_after_s ?? '')
const alwaysOn = ref(props.definition?.always_on ?? false)
const modelBasePath = ref(props.definition?.model_base_path ?? '')
const hasManaged = ref(!!props.definition?.managed)
const managedJson = ref(
  props.definition?.managed ? JSON.stringify(props.definition.managed, null, 2) : ''
)
const formError = ref('')

watch(() => props.definition, (d) => {
  name.value = props.serviceName ?? ''
  maxMb.value = d?.max_mb ?? 0
  priority.value = d?.priority ?? 1
  minCap.value = d?.min_compute_cap ?? 0
  prefCap.value = d?.preferred_compute_cap ?? ''
  shared.value = d?.shared ?? false
  maxConcurrent.value = d?.max_concurrent ?? ''
  idleStop.value = d?.idle_stop_after_s ?? ''
  alwaysOn.value = d?.always_on ?? false
  modelBasePath.value = d?.model_base_path ?? ''
  hasManaged.value = !!d?.managed
  managedJson.value = d?.managed ? JSON.stringify(d.managed, null, 2) : ''
})

const managedJsonError = computed(() => {
  if (!hasManaged.value || !managedJson.value.trim()) return ''
  try { JSON.parse(managedJson.value); return '' }
  catch { return 'Invalid JSON' }
})

function submit() {
  formError.value = ''
  if (!name.value.trim()) { formError.value = 'Service name is required.'; return }
  if (!maxMb.value || maxMb.value <= 0) { formError.value = 'max_mb must be > 0.'; return }
  if (managedJsonError.value) { formError.value = 'Fix the managed JSON before saving.'; return }

  const def: ServiceDefinition = { max_mb: maxMb.value, priority: priority.value }
  if (minCap.value) def.min_compute_cap = minCap.value
  if (prefCap.value !== '') def.preferred_compute_cap = Number(prefCap.value)
  if (shared.value) def.shared = true
  if (maxConcurrent.value !== '') def.max_concurrent = Number(maxConcurrent.value)
  if (idleStop.value !== '') def.idle_stop_after_s = Number(idleStop.value)
  if (alwaysOn.value) def.always_on = true
  if (modelBasePath.value.trim()) def.model_base_path = modelBasePath.value.trim()
  if (hasManaged.value && managedJson.value.trim()) {
    def.managed = JSON.parse(managedJson.value)
  }
  // Preserve existing catalog when editing
  if (props.definition?.catalog) def.catalog = props.definition.catalog

  emit('save', name.value.trim(), def)
}
</script>

<template>
  <div class="modal-backdrop" role="dialog" aria-modal="true" :aria-label="`${serviceName ? 'Edit' : 'Add'} service`">
    <div class="modal-box">
      <h3 class="modal-title">{{ serviceName ? 'Edit' : 'Add' }} Service</h3>

      <div class="field-row">
        <label class="field-label" for="sf-name">Service name</label>
        <input id="sf-name" v-model="name" class="field-input" :readonly="!!serviceName" placeholder="cf-text" />
      </div>

      <div class="field-row">
        <label class="field-label" for="sf-maxmb">max_mb</label>
        <input id="sf-maxmb" v-model.number="maxMb" type="number" min="0" class="field-input field-input--sm" />
        <span class="field-hint">VRAM ceiling</span>
      </div>

      <div class="field-row">
        <label class="field-label" for="sf-prio">priority</label>
        <input id="sf-prio" v-model.number="priority" type="number" min="1" max="10" class="field-input field-input--sm" />
        <span class="field-hint">1 = highest</span>
      </div>

      <div class="field-row">
        <label class="field-label" for="sf-mincap">min_compute_cap</label>
        <input id="sf-mincap" v-model.number="minCap" type="number" step="0.1" min="0" class="field-input field-input--sm" placeholder="0.0" />
      </div>

      <div class="field-row">
        <label class="field-label" for="sf-prefcap">preferred_cap</label>
        <input id="sf-prefcap" v-model="prefCap" type="number" step="0.1" min="0" class="field-input field-input--sm" placeholder="optional" />
      </div>

      <div class="field-row field-row--check">
        <input id="sf-shared" v-model="shared" type="checkbox" />
        <label for="sf-shared">shared (multiple concurrent users)</label>
      </div>

      <div class="field-row">
        <label class="field-label" for="sf-maxcon">max_concurrent</label>
        <input id="sf-maxcon" v-model="maxConcurrent" type="number" min="1" class="field-input field-input--sm" placeholder="optional" />
      </div>

      <div class="field-row">
        <label class="field-label" for="sf-idle">idle_stop_after_s</label>
        <input id="sf-idle" v-model="idleStop" type="number" min="0" class="field-input field-input--sm" placeholder="optional" />
        <span class="field-hint">seconds</span>
      </div>

      <div class="field-row field-row--check">
        <input id="sf-always" v-model="alwaysOn" type="checkbox" />
        <label for="sf-always">always_on (never evict)</label>
      </div>

      <div class="field-row">
        <label class="field-label" for="sf-base">model_base_path</label>
        <input id="sf-base" v-model="modelBasePath" class="field-input" placeholder="/devl/Assets/LLM/cf-text/models (optional)" />
      </div>

      <div class="managed-section">
        <div class="field-row field-row--check">
          <input id="sf-has-managed" v-model="hasManaged" type="checkbox" />
          <label for="sf-has-managed">Has managed process config</label>
        </div>
        <div v-if="hasManaged" class="managed-body">
          <label class="field-label" for="sf-managed">managed (JSON)</label>
          <textarea
            id="sf-managed"
            v-model="managedJson"
            class="field-textarea"
            rows="6"
            spellcheck="false"
            placeholder='{"type": "process", "exec_path": "...", "args_template": "...", "port": 8008, "host_port": 8008}'
          />
          <span v-if="managedJsonError" class="json-error" role="alert">{{ managedJsonError }}</span>
        </div>
      </div>

      <div v-if="formError" class="form-error" role="alert">{{ formError }}</div>

      <div class="modal-actions">
        <button class="btn-secondary" @click="emit('cancel')">Cancel</button>
        <button class="btn-primary" @click="submit">Save</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-backdrop {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center;
  z-index: 200;
}
.modal-box {
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 1.5rem;
  width: 100%; max-width: 540px;
  max-height: 90vh; overflow-y: auto;
  display: flex; flex-direction: column; gap: 0.65rem;
  color: var(--color-text);
}
.modal-title { margin: 0 0 0.25rem; font-size: 1rem; font-weight: 600; color: var(--color-text); }
.field-row { display: flex; align-items: center; gap: 0.5rem; }
.field-row--check { gap: 0.4rem; font-size: 0.875rem; color: var(--color-text); }
.field-label { min-width: 9rem; font-size: 0.85rem; color: var(--color-text-muted); flex-shrink: 0; }
.field-hint { font-size: 0.75rem; color: var(--color-text-muted); }
.field-input {
  flex: 1;
  background: var(--color-surface-alt);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  padding: 0.3rem 0.5rem;
  color: var(--color-text);
  font-size: 0.85rem;
}
.field-input--sm { flex: 0 0 8rem; }
.managed-section { display: flex; flex-direction: column; gap: 0.4rem; border-top: 1px solid var(--color-border); padding-top: 0.5rem; }
.managed-body { display: flex; flex-direction: column; gap: 0.3rem; }
.field-textarea {
  width: 100%;
  background: var(--color-surface-alt);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  padding: 0.4rem 0.5rem;
  color: var(--color-text);
  font-size: 0.8rem;
  font-family: var(--font-mono, monospace);
  resize: vertical;
  box-sizing: border-box;
}
.json-error { color: var(--color-error); font-size: 0.78rem; }
.form-error { color: var(--color-error); font-size: 0.8rem; }
.modal-actions { display: flex; justify-content: flex-end; gap: 0.5rem; margin-top: 0.25rem; }
.btn-primary {
  background: var(--app-primary);
  color: var(--color-text-inverse);
  border: none;
  border-radius: 4px;
  padding: 0.4rem 1rem;
  cursor: pointer;
  font-size: 0.875rem;
}
.btn-primary:hover { background: var(--app-primary-hover); }
.btn-secondary {
  background: transparent;
  border: 1px solid var(--color-border);
  color: var(--color-text);
  border-radius: 4px;
  padding: 0.4rem 0.75rem;
  cursor: pointer;
  font-size: 0.875rem;
}
.btn-secondary:hover { background: var(--color-surface-alt); }
</style>
