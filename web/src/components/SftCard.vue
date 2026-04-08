<template>
  <article class="sft-card">
    <!-- Chips row -->
    <div class="chips-row">
      <span class="chip chip-model">{{ item.model_name }}</span>
      <span class="chip chip-task">{{ item.task_type }}</span>
      <span class="chip chip-node">{{ item.node_id }} · GPU {{ item.gpu_id }}</span>
      <span class="chip chip-speed">{{ item.tokens_per_sec.toFixed(1) }} tok/s</span>
      <span
        class="chip quality-chip"
        :class="qualityClass"
        data-testid="quality-chip"
        :title="qualityLabel"
      >
        {{ item.quality_score.toFixed(2) }} · {{ qualityLabel }}
      </span>
    </div>

    <!-- Failure reason -->
    <p v-if="item.failure_reason" class="failure-reason">{{ item.failure_reason }}</p>

    <!-- Prompt (collapsible) -->
    <div class="prompt-section">
      <button
        class="prompt-toggle"
        :aria-expanded="promptExpanded"
        @click="promptExpanded = !promptExpanded"
      >
        {{ promptExpanded ? 'Hide prompt ↑' : 'Show full prompt ↓' }}
      </button>
      <div v-if="promptExpanded" class="prompt-messages">
        <div
          v-for="(msg, i) in item.prompt_messages"
          :key="i"
          class="prompt-message"
          :class="`role-${msg.role}`"
        >
          <span class="role-label">{{ msg.role }}</span>
          <pre class="message-content">{{ msg.content }}</pre>
        </div>
      </div>
    </div>

    <!-- Model response -->
    <div class="model-response-section">
      <p class="section-label">Model output (incorrect)</p>
      <pre class="model-response">{{ item.model_response }}</pre>
    </div>

    <!-- Action bar -->
    <div class="action-bar">
      <button
        data-testid="correct-btn"
        class="btn-correct"
        @click="$emit('correct')"
      >✓ Correct</button>
      <button
        data-testid="discard-btn"
        class="btn-discard"
        @click="$emit('discard')"
      >✕ Discard</button>
      <button
        data-testid="flag-btn"
        class="btn-flag"
        @click="$emit('flag')"
      >⚑ Flag Model</button>
    </div>

    <!-- Correction area (shown when correcting = true) -->
    <div v-if="correcting" data-testid="correction-area">
      <SftCorrectionArea
        ref="correctionAreaEl"
        :described-by="'sft-failure-' + item.id"
        @submit="$emit('submit-correction', $event)"
        @cancel="$emit('cancel-correction')"
      />
    </div>
  </article>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { SftQueueItem } from '../stores/sft'
import SftCorrectionArea from './SftCorrectionArea.vue'

const props = defineProps<{ item: SftQueueItem; correcting?: boolean }>()

const emit = defineEmits<{
  correct: []
  discard: []
  flag: []
  'submit-correction': [text: string]
  'cancel-correction': []
}>()

const promptExpanded   = ref(false)
const correctionAreaEl = ref<InstanceType<typeof SftCorrectionArea> | null>(null)

const qualityClass = computed(() => {
  const s = props.item.quality_score
  if (s < 0.4) return 'quality-low'
  if (s < 0.7) return 'quality-mid'
  return 'quality-ok'
})

const qualityLabel = computed(() => {
  const s = props.item.quality_score
  if (s < 0.4) return 'low quality'
  if (s < 0.7) return 'fair'
  return 'acceptable'
})

function resetCorrection() {
  correctionAreaEl.value?.reset()
}

defineExpose({ resetCorrection })
</script>

<style scoped>
.sft-card {
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.chips-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.chip {
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-full);
  font-size: 0.78rem;
  font-weight: 600;
  white-space: nowrap;
}

.chip-model   { background: var(--color-primary-light, #e8f2e7); color: var(--color-primary); }
.chip-task    { background: var(--color-surface-alt); color: var(--color-text-muted); }
.chip-node    { background: var(--color-surface-alt); color: var(--color-text-muted); }
.chip-speed   { background: var(--color-surface-alt); color: var(--color-text-muted); }

.quality-chip { color: #fff; }
.quality-low  { background: var(--color-error, #c0392b); }
.quality-mid  { background: var(--color-warning, #d4891a); }
.quality-ok   { background: var(--color-success, #3a7a32); }

.failure-reason {
  font-size: 0.82rem;
  color: var(--color-text-muted);
  font-style: italic;
}

.prompt-toggle {
  background: none;
  border: none;
  color: var(--color-accent);
  font-size: 0.85rem;
  cursor: pointer;
  padding: 0;
  text-decoration: underline;
}

.prompt-messages {
  margin-top: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.prompt-message {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.role-label {
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-muted);
}

.message-content {
  font-family: var(--font-mono);
  font-size: 0.82rem;
  white-space: pre-wrap;
  background: var(--color-surface-alt);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  max-height: 200px;
  overflow-y: auto;
}

.section-label {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--color-text-muted);
  margin-bottom: var(--space-1);
}

.model-response {
  font-family: var(--font-mono);
  font-size: 0.88rem;
  white-space: pre-wrap;
  background: color-mix(in srgb, var(--color-error, #c0392b) 8%, var(--color-surface-alt));
  border-left: 3px solid var(--color-error, #c0392b);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  max-height: 300px;
  overflow-y: auto;
}

.action-bar {
  display: flex;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.action-bar button {
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  font-size: 0.9rem;
  cursor: pointer;
  background: var(--color-surface-raised);
  color: var(--color-text);
}

.btn-correct { border-color: var(--color-success); color: var(--color-success); }
.btn-correct:hover { background: color-mix(in srgb, var(--color-success) 10%, transparent); }

.btn-discard { border-color: var(--color-error); color: var(--color-error); }
.btn-discard:hover { background: color-mix(in srgb, var(--color-error) 10%, transparent); }

.btn-flag { border-color: var(--color-warning); color: var(--color-warning); }
.btn-flag:hover { background: color-mix(in srgb, var(--color-warning) 10%, transparent); }
</style>
