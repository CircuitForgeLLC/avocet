// src/stores/label.ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export interface QueueItem {
  id: string
  subject: string
  body: string
  from: string
  date: string
  source: string
}

export interface LastAction {
  type: 'label' | 'skip' | 'discard'
  item: QueueItem
  label?: string
}

export const useLabelStore = defineStore('label', () => {
  const queue          = ref<QueueItem[]>([])
  const totalRemaining = ref(0)
  const lastAction     = ref<LastAction | null>(null)
  const sessionLabeled = ref(0)   // for easter eggs

  const current = computed(() => queue.value[0] ?? null)

  function removeCurrentFromQueue() {
    queue.value.shift()
  }

  function setLastAction(type: LastAction['type'], item: QueueItem, label?: string) {
    lastAction.value = { type, item, label }
  }

  function clearLastAction() {
    lastAction.value = null
  }

  function restoreItem(item: QueueItem) {
    queue.value.unshift(item)
  }

  function incrementLabeled() {
    sessionLabeled.value++
  }

  return {
    queue, totalRemaining, lastAction, sessionLabeled, current,
    removeCurrentFromQueue, setLastAction, clearLastAction,
    restoreItem, incrementLabeled,
  }
})
