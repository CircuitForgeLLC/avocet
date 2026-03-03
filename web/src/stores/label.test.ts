// src/stores/label.test.ts
import { setActivePinia, createPinia } from 'pinia'
import { useLabelStore } from './label'
import { beforeEach, describe, it, expect } from 'vitest'

const MOCK_ITEM = {
  id: 'abc', subject: 'Test', body: 'Body', from: 'a@b.com',
  date: '2026-03-01', source: 'imap:test',
}

describe('label store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('starts with empty queue', () => {
    const store = useLabelStore()
    expect(store.queue).toEqual([])
    expect(store.current).toBeNull()
  })

  it('current returns first item', () => {
    const store = useLabelStore()
    store.queue = [MOCK_ITEM]
    expect(store.current).toEqual(MOCK_ITEM)
  })

  it('removeCurrentFromQueue removes first item', () => {
    const store = useLabelStore()
    store.queue = [MOCK_ITEM, { ...MOCK_ITEM, id: 'def' }]
    store.removeCurrentFromQueue()
    expect(store.queue[0].id).toBe('def')
  })

  it('tracks lastAction', () => {
    const store = useLabelStore()
    store.queue = [MOCK_ITEM]
    store.setLastAction('label', MOCK_ITEM, 'interview_scheduled')
    expect(store.lastAction?.type).toBe('label')
    expect(store.lastAction?.label).toBe('interview_scheduled')
  })

  it('incrementLabeled increases sessionLabeled', () => {
    const store = useLabelStore()
    store.incrementLabeled()
    store.incrementLabeled()
    expect(store.sessionLabeled).toBe(2)
  })

  it('restoreItem adds to front of queue', () => {
    const store = useLabelStore()
    store.queue = [{ ...MOCK_ITEM, id: 'def' }]
    store.restoreItem(MOCK_ITEM)
    expect(store.queue[0].id).toBe('abc')
    expect(store.queue[1].id).toBe('def')
  })

  it('clearLastAction nulls lastAction', () => {
    const store = useLabelStore()
    store.setLastAction('skip', MOCK_ITEM)
    store.clearLastAction()
    expect(store.lastAction).toBeNull()
  })
})
