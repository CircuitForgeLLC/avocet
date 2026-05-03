import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import CompareView from './CompareView.vue'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ tasks: [], types: [], models: [] }),
    text: async () => '',
  }))
  vi.stubGlobal('EventSource', class {
    onmessage = null
    onerror = null
    close() {}
  })
})

describe('CompareView', () => {
  it('renders page title "Compare"', async () => {
    const w = mount(CompareView)
    await flushPromises()
    expect(w.find('h1.page-title').text()).toContain('Compare')
  })

  it('wraps CompareTab component', async () => {
    const w = mount(CompareView)
    await flushPromises()
    // CompareTab renders a .compare-tab root div
    expect(w.find('.compare-tab').exists()).toBe(true)
  })
})
