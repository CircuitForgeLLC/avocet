<script setup lang="ts">
import { ref, watch } from 'vue'
import type { CatalogEntryFull } from '../../types/nodes'

const props = defineProps<{
  svcName: string
  modelName?: string
  entry?: CatalogEntryFull
}>()
const emit = defineEmits<{
  save: [svcName: string, modelName: string, entry: CatalogEntryFull]
  cancel: []
}>()

const name = ref(props.modelName ?? '')
const path = ref(props.entry?.path ?? '')
const vramMb = ref(props.entry?.vram_mb ?? 0)
const description = ref(props.entry?.description ?? '')
const multiGpu = ref(props.entry?.multi_gpu ?? false)
const envPairs = ref<{ k: string; v: string }[]>(
  Object.entries(props.entry?.env ?? {}).map(([k, v]) => ({ k, v }))
)
const formError = ref('')

watch(() => props.entry, (e) => {
  name.value = props.modelName ?? ''
  path.value = e?.path ?? ''
  vramMb.value = e?.vram_mb ?? 0
  description.value = e?.description ?? ''
  multiGpu.value = e?.multi_gpu ?? false
  envPairs.value = Object.entries(e?.env ?? {}).map(([k, v]) => ({ k, v }))
})

function addEnvPair() {
  envPairs.value = [...envPairs.value, { k: '', v: '' }]
}
function removeEnvPair(i: number) {
  envPairs.value = envPairs.value.filter((_, idx) => idx !== i)
}

function submit() {
  formError.value = ''
  if (!name.value.trim()) { formError.value = 'Model name is required.'; return }
  if (!path.value.trim()) { formError.value = 'Path is required.'; return }
  if (!vramMb.value || vramMb.value < 0) { formError.value = 'vram_mb must be a positive number.'; return }

  const envObj: Record<string, string> = {}
  for (const { k, v } of envPairs.value) {
    if (k.trim()) envObj[k.trim()] = v
  }

  const entry: CatalogEntryFull = { path: path.value.trim(), vram_mb: vramMb.value }
  if (description.value.trim()) entry.description = description.value.trim()
  if (multiGpu.value) entry.multi_gpu = true
  if (Object.keys(envObj).length) entry.env = envObj

  emit('save', props.svcName, name.value.trim(), entry)
}
</script>

<template>
  <div class="modal-backdrop" role="dialog" aria-modal="true" :aria-label="`${modelName ? 'Edit' : 'Add'} catalog entry`">
    <div class="modal-box">
      <h3 class="modal-title">{{ modelName ? 'Edit' : 'Add' }} Catalog Entry — {{ svcName }}</h3>

      <div class="field-row">
        <label class="field-label" for="ce-name">Model name</label>
        <input id="ce-name" v-model="name" class="field-input" :readonly="!!modelName" placeholder="deepseek-r1-7b" />
      </div>
      <div class="field-row">
        <label class="field-label" for="ce-path">Path</label>
        <input id="ce-path" v-model="path" class="field-input" placeholder="/devl/Assets/LLM/cf-text/models/..." />
      </div>
      <div class="field-row">
        <label class="field-label" for="ce-vram">VRAM (MB)</label>
        <input id="ce-vram" v-model.number="vramMb" type="number" min="0" class="field-input field-input--sm" />
      </div>
      <div class="field-row">
        <label class="field-label" for="ce-desc">Description</label>
        <input id="ce-desc" v-model="description" class="field-input" placeholder="Short description" />
      </div>
      <div class="field-row field-row--check">
        <input id="ce-mgpu" v-model="multiGpu" type="checkbox" />
        <label for="ce-mgpu">Multi-GPU span</label>
      </div>

      <div class="env-section">
        <div class="env-header">
          <span class="field-label">Env vars</span>
          <button type="button" class="btn-link" @click="addEnvPair">+ Add</button>
        </div>
        <div v-for="(pair, i) in envPairs" :key="i" class="env-row">
          <input v-model="pair.k" class="field-input field-input--sm" placeholder="CF_TEXT_4BIT" />
          <span>=</span>
          <input v-model="pair.v" class="field-input field-input--sm" placeholder="1" />
          <button type="button" class="btn-icon" @click="removeEnvPair(i)" aria-label="Remove">✕</button>
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
  width: 100%; max-width: 500px;
  max-height: 90vh; overflow-y: auto;
  display: flex; flex-direction: column; gap: 0.75rem;
  color: var(--color-text);
}
.modal-title { margin: 0 0 0.25rem; font-size: 1rem; font-weight: 600; color: var(--color-text); }
.field-row { display: flex; align-items: center; gap: 0.5rem; }
.field-row--check { gap: 0.4rem; color: var(--color-text); }
.field-label { min-width: 8rem; font-size: 0.85rem; color: var(--color-text-muted); }
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
.env-section { display: flex; flex-direction: column; gap: 0.35rem; }
.env-header { display: flex; align-items: center; justify-content: space-between; }
.env-row { display: flex; align-items: center; gap: 0.4rem; }
.btn-link { background: none; border: none; color: var(--app-primary); cursor: pointer; font-size: 0.8rem; padding: 0; }
.btn-link:hover { color: var(--app-primary-hover); }
.btn-icon { background: none; border: none; color: var(--color-text-muted); cursor: pointer; padding: 0 0.2rem; font-size: 0.85rem; }
.btn-icon:hover { color: var(--color-error); }
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
