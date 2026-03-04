import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import LabelView from './LabelView.vue'
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
})
