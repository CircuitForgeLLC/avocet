import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHashHistory } from 'vue-router'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import AppSidebar from './AppSidebar.vue'

// Minimal router so RouterLink renders without warnings
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/',                  component: { template: '<div />' } },
    { path: '/fleet',             component: { template: '<div />' } },
    { path: '/data/label',        component: { template: '<div />' } },
    { path: '/data/fetch',        component: { template: '<div />' } },
    { path: '/data/corrections',  component: { template: '<div />' } },
    { path: '/data/imitate',      component: { template: '<div />' } },
    { path: '/eval/benchmark',    component: { template: '<div />' } },
    { path: '/eval/compare',      component: { template: '<div />' } },
    { path: '/train/jobs',        component: { template: '<div />' } },
    { path: '/train/results',     component: { template: '<div />' } },
    { path: '/settings',          component: { template: '<div />' } },
  ],
})

function makeFetch(signals: Record<string, boolean> = {}) {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      labeled_since_last_eval: 0,
      last_eval_timestamp: null,
      last_eval_best_score: null,
      active_jobs: [],
      corrections_export_ready: 0,
      signals,
    }),
    text: async () => '',
  })
}

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('fetch', makeFetch())
})

describe('AppSidebar structure', () => {
  it('renders section headers for Data, Eval, Train', async () => {
    const w = mount(AppSidebar, { global: { plugins: [router] } })
    await flushPromises()
    const text = w.text()
    expect(text).toContain('Data')
    expect(text).toContain('Eval')
    expect(text).toContain('Train')
  })

  it('renders all sub-links', async () => {
    const w = mount(AppSidebar, { global: { plugins: [router] } })
    await flushPromises()
    const anchors = w.findAll('a')
    const hrefs = anchors.map(a => a.attributes('href') ?? '')
    expect(hrefs.some(h => h.includes('/data/label'))).toBe(true)
    expect(hrefs.some(h => h.includes('/data/fetch'))).toBe(true)
    expect(hrefs.some(h => h.includes('/data/corrections'))).toBe(true)
    expect(hrefs.some(h => h.includes('/data/imitate'))).toBe(true)
    expect(hrefs.some(h => h.includes('/eval/benchmark'))).toBe(true)
    expect(hrefs.some(h => h.includes('/eval/compare'))).toBe(true)
    expect(hrefs.some(h => h.includes('/train/jobs'))).toBe(true)
    expect(hrefs.some(h => h.includes('/train/results'))).toBe(true)
    expect(hrefs.some(h => h.includes('/fleet'))).toBe(true)
    expect(hrefs.some(h => h.includes('/settings'))).toBe(true)
  })

  it('does NOT render the old /benchmark or /models links', async () => {
    const w = mount(AppSidebar, { global: { plugins: [router] } })
    await flushPromises()
    const anchors = w.findAll('a')
    const hrefs = anchors.map(a => a.attributes('href') ?? '')
    // Old paths must not appear as direct links (they're only redirects)
    expect(hrefs.every(h => !h.endsWith('/#/benchmark'))).toBe(true)
    expect(hrefs.every(h => !h.endsWith('/#/models'))).toBe(true)
    expect(hrefs.every(h => !h.endsWith('/#/stats'))).toBe(true)
  })

  it('shows no signal badges when all signals are false', async () => {
    vi.stubGlobal('fetch', makeFetch({ data_to_eval: false, eval_to_train: false, train_to_fleet: false }))
    const w = mount(AppSidebar, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.findAll('.signal-badge').length).toBe(0)
  })

  it('shows signal badge on Data section when data_to_eval is true', async () => {
    vi.stubGlobal('fetch', makeFetch({ data_to_eval: true, eval_to_train: false, train_to_fleet: false }))
    const w = mount(AppSidebar, { global: { plugins: [router] } })
    await flushPromises()
    const badges = w.findAll('.signal-badge')
    expect(badges.length).toBe(1)
    // It should be inside the Data section header
    const dataHeader = w.find('[data-section="data"]')
    expect(dataHeader.find('.signal-badge').exists()).toBe(true)
  })

  it('shows signal badge on Eval section when eval_to_train is true', async () => {
    vi.stubGlobal('fetch', makeFetch({ data_to_eval: false, eval_to_train: true, train_to_fleet: false }))
    const w = mount(AppSidebar, { global: { plugins: [router] } })
    await flushPromises()
    const evalHeader = w.find('[data-section="eval"]')
    expect(evalHeader.find('.signal-badge').exists()).toBe(true)
  })

  it('shows signal badge on Train section when train_to_fleet is true', async () => {
    vi.stubGlobal('fetch', makeFetch({ data_to_eval: false, eval_to_train: false, train_to_fleet: true }))
    const w = mount(AppSidebar, { global: { plugins: [router] } })
    await flushPromises()
    const trainHeader = w.find('[data-section="train"]')
    expect(trainHeader.find('.signal-badge').exists()).toBe(true)
  })

  it('stow toggle still works', async () => {
    const w = mount(AppSidebar, { global: { plugins: [router] } })
    await flushPromises()
    const nav = w.find('nav')
    expect(nav.classes()).not.toContain('stowed')
    await w.find('.stow-btn').trigger('click')
    expect(nav.classes()).toContain('stowed')
  })
})
