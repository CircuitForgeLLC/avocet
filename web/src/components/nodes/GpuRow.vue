<script setup lang="ts">
import { ref, computed } from 'vue'
import ServiceBadge from './ServiceBadge.vue'
import type { GpuEntry, ServiceInfo } from '../../types/nodes'

const props = defineProps<{
  gpu: GpuEntry
  nodeId: string
  profileLoaded: boolean
  servicesCatalog: Record<string, ServiceInfo>
}>()

const emit = defineEmits<{ updated: [] }>()

const saving = ref(false)
const saveError = ref('')

const vramPct = computed(() => {
  if (!props.gpu.vram_total_mb) return 0
  return Math.round((props.gpu.vram_used_mb / props.gpu.vram_total_mb) * 100)
})

function serviceState(svcName: string): 'running' | 'stopped' | 'assigned-only' | 'available' | 'incompatible' | 'unknown' {
  const svc = props.servicesCatalog[svcName]
  if (!svc) return 'unknown'
  const cap = props.gpu.compute_cap ?? 0
  if (cap < svc.min_compute_cap) return 'incompatible'
  if (props.gpu.services_running.includes(svcName)) return 'running'
  if (props.gpu.services_assigned.includes(svcName)) return 'assigned-only'
  return 'available'
}

async function toggleService(svcName: string) {
  if (!props.profileLoaded || saving.value) return
  const current = [...props.gpu.services_assigned]
  const removing = current.includes(svcName)
  if (removing && !confirm(`Remove ${svcName} from GPU ${props.gpu.gpu_id}?`)) return
  const next = removing ? current.filter(s => s !== svcName) : [...current, svcName]

  saving.value = true
  saveError.value = ''
  try {
    const r = await fetch(
      `/api/nodes-mgmt/nodes/${props.nodeId}/gpu/${props.gpu.gpu_id}/services`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ services: next }),
      },
    )
    if (!r.ok) {
      const data = await r.json().catch(() => ({}))
      throw new Error((data as { detail?: string }).detail ?? `HTTP ${r.status}`)
    }
    const data = await r.json() as { ok: boolean; reloaded: boolean; warnings: string[] }
    if (data.warnings?.length) saveError.value = `Saved (warning: ${data.warnings.join(', ')})`
    emit('updated')
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : 'Failed to update services'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="gpu-row">
    <div class="gpu-info">
      <span class="gpu-label">GPU {{ gpu.gpu_id }}: {{ gpu.card }}</span>
      <span v-if="gpu.compute_cap != null" class="gpu-meta">sm{{ gpu.compute_cap }}</span>
      <span v-if="gpu.temp_c != null" class="gpu-meta">{{ gpu.temp_c }}°C</span>
      <span v-if="gpu.utilization_pct != null" class="gpu-meta">{{ gpu.utilization_pct }}%</span>
    </div>

    <div class="vram-wrap">
      <div
        class="vram-bar"
        role="progressbar"
        :aria-valuenow="gpu.vram_used_mb"
        aria-valuemin="0"
        :aria-valuemax="gpu.vram_total_mb"
        :aria-label="`VRAM: ${gpu.vram_used_mb} of ${gpu.vram_total_mb} MB used`"
      >
        <div class="vram-fill" :style="{ width: `${vramPct}%` }" />
      </div>
      <span class="vram-text">{{ gpu.vram_used_mb }} / {{ gpu.vram_total_mb }} MB ({{ vramPct }}%)</span>
    </div>

    <div v-if="profileLoaded" class="services-row" aria-label="Service assignments">
      <ServiceBadge
        v-for="(_, svcName) in servicesCatalog"
        :key="String(svcName)"
        :service-name="String(svcName)"
        :state="serviceState(String(svcName))"
        :assigned="gpu.services_assigned.includes(String(svcName))"
        :disabled="saving"
        @toggle="toggleService(String(svcName))"
      />
    </div>

    <div v-if="saveError" class="save-msg" role="alert">{{ saveError }}</div>
  </div>
</template>

<style scoped>
.gpu-row {
  padding: 0.5rem 0.75rem;
  border-radius: 4px;
  background: var(--bg-secondary, #111);
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.gpu-info { display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; font-size: 0.875rem; }
.gpu-label { font-weight: 500; }
.gpu-meta { color: var(--text-secondary, #888); font-size: 0.8rem; }
.vram-wrap { display: flex; align-items: center; gap: 0.5rem; }
.vram-bar {
  flex: 1;
  height: 8px;
  background: var(--bg-bar, #2a2a2a);
  border-radius: 4px;
  overflow: hidden;
}
.vram-fill { height: 100%; background: var(--color-primary, #4080ff); transition: width 0.3s; }
.vram-text { font-size: 0.75rem; color: var(--text-secondary, #888); white-space: nowrap; }
.services-row { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.save-msg { color: var(--color-warning, #ed8936); font-size: 0.8rem; }
</style>
