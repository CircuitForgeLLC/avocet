import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import LabelView from './LabelView.vue'
import EmailCardStack from '../components/EmailCardStack.vue'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock fetch globally
beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ items: [], total: 0 }),
    text: async () => '',
  }))
})

describe('LabelView', () => {
  it('shows loading state initially', () => {
    const w = mount(LabelView, {
      global: { plugins: [createPinia()] },
    })
    // Should show skeleton while loading
    expect(w.find('.skeleton-card').exists()).toBe(true)
  })

  it('shows empty state when queue is empty after load', async () => {
    const w = mount(LabelView, {
      global: { plugins: [createPinia()] },
    })
    // Let all promises resolve
    await new Promise(r => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.find('.empty-state').exists()).toBe(true)
  })

  it('renders header with action buttons', async () => {
    const w = mount(LabelView, {
      global: { plugins: [createPinia()] },
    })
    await new Promise(r => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.find('.lv-header').exists()).toBe(true)
    expect(w.text()).toContain('Undo')
    expect(w.text()).toContain('Skip')
    expect(w.text()).toContain('Discard')
  })

  const queueItem = {
    id: 'test-1', subject: 'Test Email', body: 'Test body',
    from: 'test@test.com', date: '2026-03-05', source: 'test',
  }

  // Return queue items for /api/queue, empty array for /api/config/labels
  function mockFetchWithQueue() {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) =>
      Promise.resolve({
        ok: true,
        json: async () => (url as string).includes('/api/queue')
          ? { items: [queueItem], total: 1 }
          : [],
        text: async () => '',
      })
    ))
  }

  it('renders toss zone overlays when isHeld is true (after drag-start)', async () => {
    mockFetchWithQueue()
    const w = mount(LabelView, { global: { plugins: [createPinia()] } })
    await new Promise(r => setTimeout(r, 0))
    await w.vm.$nextTick()
    // Zone overlays should not exist before drag
    expect(w.find('.toss-zone-left').exists()).toBe(false)
    // Emit drag-start from EmailCardStack child
    const cardStack = w.findComponent(EmailCardStack)
    cardStack.vm.$emit('drag-start')
    await w.vm.$nextTick()
    expect(w.find('.toss-zone-left').exists()).toBe(true)
    expect(w.find('.toss-zone-right').exists()).toBe(true)
  })

  it('bucket-grid-footer has grid-active class while card is held', async () => {
    mockFetchWithQueue()
    const w = mount(LabelView, { global: { plugins: [createPinia()] } })
    await new Promise(r => setTimeout(r, 0))
    await w.vm.$nextTick()
    expect(w.find('.bucket-grid-footer').classes()).not.toContain('grid-active')
    const cardStack = w.findComponent(EmailCardStack)
    cardStack.vm.$emit('drag-start')
    await w.vm.$nextTick()
    expect(w.find('.bucket-grid-footer').classes()).toContain('grid-active')
  })
})
