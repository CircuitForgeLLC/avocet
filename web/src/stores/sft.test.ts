import { setActivePinia, createPinia } from 'pinia'
import { useSftStore } from './sft'
import type { SftQueueItem } from './sft'
import { beforeEach, describe, it, expect } from 'vitest'

const MOCK_ITEM: SftQueueItem = {
  id: 'abc',
  source: 'cf-orch-benchmark',
  benchmark_run_id: 'run1',
  timestamp: '2026-04-07T10:00:00Z',
  status: 'needs_review',
  prompt_messages: [
    { role: 'system', content: 'You are a coding assistant.' },
    { role: 'user', content: 'Write a Python add function.' },
  ],
  model_response: 'def add(a, b): return a - b',
  corrected_response: null,
  quality_score: 0.2,
  failure_reason: 'pattern_match: 0/2 matched',
  task_id: 'code-fn',
  task_type: 'code',
  task_name: 'Code: Write a Python function',
  model_id: 'Qwen/Qwen2.5-3B',
  model_name: 'Qwen2.5-3B',
  node_id: 'heimdall',
  gpu_id: 0,
  tokens_per_sec: 38.4,
}

describe('useSftStore', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('starts with empty queue', () => {
    const store = useSftStore()
    expect(store.queue).toEqual([])
    expect(store.current).toBeNull()
  })

  it('current returns first item', () => {
    const store = useSftStore()
    store.queue = [MOCK_ITEM]
    expect(store.current?.id).toBe('abc')
  })

  it('removeCurrentFromQueue removes first item', () => {
    const store = useSftStore()
    const second = { ...MOCK_ITEM, id: 'def' }
    store.queue = [MOCK_ITEM, second]
    store.removeCurrentFromQueue()
    expect(store.queue[0].id).toBe('def')
  })

  it('restoreItem adds to front of queue', () => {
    const store = useSftStore()
    const second = { ...MOCK_ITEM, id: 'def' }
    store.queue = [second]
    store.restoreItem(MOCK_ITEM)
    expect(store.queue[0].id).toBe('abc')
    expect(store.queue[1].id).toBe('def')
  })

  it('setLastAction records the action', () => {
    const store = useSftStore()
    store.setLastAction('discard', MOCK_ITEM)
    expect(store.lastAction?.type).toBe('discard')
    expect(store.lastAction?.item.id).toBe('abc')
  })

  it('clearLastAction nulls lastAction', () => {
    const store = useSftStore()
    store.setLastAction('flag', MOCK_ITEM)
    store.clearLastAction()
    expect(store.lastAction).toBeNull()
  })
})
