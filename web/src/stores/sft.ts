// src/stores/sft.ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export interface SftQueueItem {
  id: string
  source: 'cf-orch-benchmark'
  benchmark_run_id: string
  timestamp: string
  status: 'needs_review' | 'approved' | 'discarded' | 'model_rejected'
  prompt_messages: { role: string; content: string }[]
  model_response: string
  corrected_response: string | null
  quality_score: number          // 0.0 to 1.0
  failure_reason: string | null
  task_id: string
  task_type: string
  task_name: string
  model_id: string
  model_name: string
  node_id: string
  gpu_id: number
  tokens_per_sec: number
}

export interface SftLastAction {
  type: 'correct' | 'discard' | 'flag'
  item: SftQueueItem
}

export const useSftStore = defineStore('sft', () => {
  const queue          = ref<SftQueueItem[]>([])
  const totalRemaining = ref(0)
  const lastAction     = ref<SftLastAction | null>(null)

  const current = computed(() => queue.value[0] ?? null)

  function removeCurrentFromQueue() {
    queue.value.shift()
  }

  function setLastAction(type: SftLastAction['type'], item: SftQueueItem) {
    lastAction.value = { type, item }
  }

  function clearLastAction() {
    lastAction.value = null
  }

  function restoreItem(item: SftQueueItem) {
    queue.value.unshift(item)
  }

  return {
    queue, totalRemaining, lastAction, current,
    removeCurrentFromQueue, setLastAction, clearLastAction, restoreItem,
  }
})
