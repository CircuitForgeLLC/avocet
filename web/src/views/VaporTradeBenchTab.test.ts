import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import VaporTradeBenchTab from './VaporTradeBenchTab.vue'

beforeEach(() => {
  global.fetch = vi.fn(async (url: string) => {
    if (url.includes('/results')) {
      return { ok: true, json: async () => [] } as Response
    }
    return { ok: true, json: async () => ({}) } as Response
  })
})

describe('VaporTradeBenchTab', () => {
  it('renders trigger buttons for cost and load runs', async () => {
    const wrapper = mount(VaporTradeBenchTab)
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('cost')
    expect(wrapper.text()).toContain('load')
  })

  it('shows an empty state when there are no past results', async () => {
    const wrapper = mount(VaporTradeBenchTab)
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(wrapper.text().toLowerCase()).toContain('no')
  })
})
