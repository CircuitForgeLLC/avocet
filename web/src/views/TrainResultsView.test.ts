import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHashHistory } from 'vue-router'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import TrainResultsView from './TrainResultsView.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/fleet', component: { template: '<div />' } },
  ],
})

const sampleResult = {
  id: 'run-xyz',
  job_id: 'job-abc123',
  model_type: 'classifier',
  base_model: 'microsoft/deberta-v3-small',
  val_macro_f1: 0.847,
  val_accuracy: 0.891,
  sample_count: 1240,
  duration_seconds: 842,
  created_at: '2026-05-01T11:30:00Z',
}

function makeFetch(results: unknown[] = []) {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ results }),
    text: async () => '',
  })
}

beforeEach(() => {
  vi.stubGlobal('fetch', makeFetch([sampleResult]))
})

describe('TrainResultsView', () => {
  it('renders page title "Training Results"', async () => {
    const w = mount(TrainResultsView, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.find('h1.page-title').text()).toContain('Training Results')
  })

  it('shows empty notice when there are no results', async () => {
    vi.stubGlobal('fetch', makeFetch([]))
    const w = mount(TrainResultsView, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.find('.empty-notice').exists()).toBe(true)
  })

  it('renders results table when results exist', async () => {
    const w = mount(TrainResultsView, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.find('table.results-table').exists()).toBe(true)
  })

  it('shows base_model in table', async () => {
    const w = mount(TrainResultsView, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.text()).toContain('deberta-v3-small')
  })

  it('shows val_macro_f1 formatted as percentage', async () => {
    const w = mount(TrainResultsView, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.text()).toContain('84.7%')
  })

  it('shows val_accuracy formatted as percentage', async () => {
    const w = mount(TrainResultsView, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.text()).toContain('89.1%')
  })

  it('shows duration formatted as minutes and seconds', async () => {
    const w = mount(TrainResultsView, { global: { plugins: [router] } })
    await flushPromises()
    // 842 seconds = 14m 2s
    expect(w.text()).toContain('14m')
  })

  it('shows Register in Fleet button for classifier results', async () => {
    const w = mount(TrainResultsView, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.find('a.register-btn').exists()).toBe(true)
  })

  it('does NOT show Register in Fleet button for llm-sft results', async () => {
    vi.stubGlobal('fetch', makeFetch([{ ...sampleResult, model_type: 'llm-sft' }]))
    const w = mount(TrainResultsView, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.find('a.register-btn').exists()).toBe(false)
  })

  it('shows error notice when API fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, text: async () => '' }))
    const w = mount(TrainResultsView, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.find('.error-notice').exists()).toBe(true)
  })
})
