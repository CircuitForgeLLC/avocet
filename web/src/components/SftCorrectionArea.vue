<template>
  <div class="correction-area">
    <label class="correction-label" for="correction-textarea">
      Write the corrected response:
    </label>
    <textarea
      id="correction-textarea"
      ref="textareaEl"
      v-model="text"
      class="correction-textarea"
      aria-label="Write corrected response"
      aria-required="true"
      :aria-describedby="describedBy"
      placeholder="Write the response this model should have given..."
      rows="4"
      @keydown.escape="$emit('cancel')"
      @keydown.enter.ctrl.prevent="submitIfValid"
      @keydown.enter.meta.prevent="submitIfValid"
    />
    <div class="correction-actions">
      <button
        data-testid="submit-btn"
        class="btn-submit"
        :disabled="!isValid"
        @click="submitIfValid"
      >
        Submit correction
      </button>
      <button data-testid="cancel-btn" class="btn-cancel" @click="$emit('cancel')">
        Cancel
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

const props = withDefaults(defineProps<{ describedBy?: string }>(), { describedBy: undefined })

const emit = defineEmits<{ submit: [text: string]; cancel: [] }>()

const text       = ref('')
const textareaEl = ref<HTMLTextAreaElement | null>(null)
const isValid    = computed(() => text.value.trim().length > 0)

onMounted(() => textareaEl.value?.focus())

function submitIfValid() {
  if (isValid.value) emit('submit', text.value.trim())
}

function reset() {
  text.value = ''
}

defineExpose({ reset })
</script>

<style scoped>
.correction-area {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-alt, var(--color-surface));
  border-radius: 0 0 var(--radius-lg) var(--radius-lg);
}

.correction-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--color-text-muted);
}

.correction-textarea {
  width: 100%;
  min-height: 7rem;
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-raised);
  color: var(--color-text);
  font-family: var(--font-mono);
  font-size: 0.88rem;
  line-height: 1.5;
  resize: vertical;
}

.correction-textarea:focus {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

.correction-actions {
  display: flex;
  gap: var(--space-3);
  align-items: center;
}

.btn-submit {
  padding: var(--space-2) var(--space-4);
  background: var(--color-primary);
  color: var(--color-text-inverse, #fff);
  border: none;
  border-radius: var(--radius-md);
  font-size: 0.9rem;
  cursor: pointer;
}

.btn-submit:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.btn-submit:not(:disabled):hover {
  background: var(--color-primary-hover, var(--color-primary));
}

.btn-cancel {
  background: none;
  border: none;
  color: var(--color-text-muted);
  font-size: 0.9rem;
  cursor: pointer;
  text-decoration: underline;
  padding: 0;
}
</style>
