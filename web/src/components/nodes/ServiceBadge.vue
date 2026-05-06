<script setup lang="ts">
type ServiceState =
  | 'running'
  | 'stopped'
  | 'assigned-only'
  | 'available'
  | 'incompatible'
  | 'vram-tight'
  | 'unknown'

const props = defineProps<{
  serviceName: string
  state: ServiceState
  assigned: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{ toggle: [] }>()

const STATE_LABELS: Record<string, string> = {
  running: 'Running',
  stopped: 'Stopped',
  'assigned-only': 'Assigned',
  available: 'Available',
  incompatible: 'Incompatible',
  'vram-tight': 'VRAM tight',
  unknown: 'Unknown',
}

const STATE_ICONS: Record<string, string> = {
  running: '▶',
  stopped: '⏹',
  'assigned-only': '📌',
  available: '○',
  incompatible: '✕',
  'vram-tight': '⚠',
  unknown: '?',
}

function handleToggle() {
  if (!props.disabled && props.state !== 'incompatible') emit('toggle')
}
</script>

<template>
  <button
    class="service-badge"
    :class="[`state-${state}`, { assigned, 'is-disabled': disabled || state === 'incompatible' }]"
    :aria-pressed="assigned"
    :aria-label="`${serviceName}: ${STATE_LABELS[state] ?? state}${assigned ? ' (assigned)' : ''}`"
    :disabled="disabled || state === 'incompatible'"
    @click="handleToggle"
  >
    <span class="badge-icon" aria-hidden="true">{{ STATE_ICONS[state] ?? '?' }}</span>
    <span class="badge-name">{{ serviceName }}</span>
    <span class="badge-state">{{ STATE_LABELS[state] ?? state }}</span>
  </button>
</template>

<style scoped>
.service-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  border: 1px solid var(--border, #333);
  background: var(--bg-badge, #1e1e1e);
  font-size: 0.75rem;
  cursor: pointer;
  transition: opacity 0.1s, border-color 0.1s;
}
.service-badge:hover:not(.is-disabled) { opacity: 0.8; }
.service-badge.is-disabled { cursor: not-allowed; opacity: 0.5; }
.service-badge.state-running  { border-color: var(--color-success, #48bb78); }
.service-badge.state-stopped  { border-color: var(--color-warning, #ed8936); }
.service-badge.state-assigned-only { border-color: var(--color-info, #4299e1); }
.service-badge.state-incompatible  { border-color: var(--color-error, #fc8181); }
.service-badge.state-vram-tight    { border-color: var(--color-warning, #ed8936); }
.badge-state { color: var(--text-secondary, #888); }
</style>
