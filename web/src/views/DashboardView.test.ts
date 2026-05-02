import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createWebHashHistory } from 'vue-router'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import DashboardView from './DashboardView.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/',               component: { template: '<div />' } },
    { path: '/eval/benchmark', component: { template: '<div />' } },
    { path: '/train/jobs',     component: { template: '<div />' } },
    { path: '/fleet',          component: { template: '<div />' } },
  ],
})

const baseDashboard = {
  labeled_since_last_eval: 0,
  last_eval_timestamp: null,
  last_eval_best_score: null,
  active_jobs: [],
  corrections_export_ready: 0,
  signals: { data_to_eval: false, eval_to_train: false, train_to_fleet: false },
}

function mockFetch(overrides: Partial<typeof baseDashboard> = {}) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ ...baseDashboard, ...overrides }),
    text: async () => '',
  }))
}

beforeEach(() => mockFetch())

describe('DashboardView', () => {
  it('renders page title', async () => {
    const w = mount(DashboardView, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.text()).toContain('Dashboard')
  })

  it('shows three stage cards: Data, Eval, Train', async () => {
    const w = mount(DashboardView, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.find('.stage-card[data-stage="data"]').exists()).toBe(true)
    expect(w.find('.stage-card[data-stage="eval"]').exists()).toBe(true)
    expect(w.find('.stage-card[data-stage="train"]').exists()).toBe(true)
  })

  it('shows labeled_since_last_eval count in Data card', async () => {
    mockFetch({ labeled_since_last_eval: 42 })
    const w = mount(DashboardView, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.find('.stage-card[data-stage="data"]').text()).toContain('42')
  })

  it('does NOT show Run Eval CTA when data_to_eval is false', async () => {
    mockFetch({ signals: { data_to_eval: false, eval_to_train: false, train_to_fleet: false } })
    const w = mount(DashboardView, { global: { plugins: [router] } })
    await flushPromises()
    const dataCard = w.find('.stage-card[data-stage="data"]')
    expect(dataCard.find('.cta-btn').exists()).toBe(false)
  })

  it('shows Run Eval CTA when data_to_eval is true', async () => {
    mockFetch({ signals: { data_to_eval: true, eval_to_train: false, train_to_fleet: false } })
    const w = mount(DashboardView, { global: { plugins: [router] } })
    await flushPromises()
    const dataCard = w.find('.stage-card[data-stage="data"]')
    expect(dataCard.find('.cta-btn').exists()).toBe(true)
    expect(dataCard.find('.cta-btn').text()).toContain('Run Eval')
  })

  it('shows Queue Finetune CTA when eval_to_train is true', async () => {
    mockFetch({ signals: { data_to_eval: false, eval_to_train: true, train_to_fleet: false } })
    const w = mount(DashboardView, { global: { plugins: [router] } })
    await flushPromises()
    const evalCard = w.find('.stage-card[data-stage="eval"]')
    expect(evalCard.find('.cta-btn').text()).toContain('Queue Finetune')
  })

  it('shows Register in Fleet CTA when train_to_fleet is true', async () => {
    mockFetch({ signals: { data_to_eval: false, eval_to_train: false, train_to_fleet: true } })
    const w = mount(DashboardView, { global: { plugins: [router] } })
    await flushPromises()
    const trainCard = w.find('.stage-card[data-stage="train"]')
    expect(trainCard.find('.cta-btn').text()).toContain('Register in Fleet')
  })

  it('shows active job status pills in Train card', async () => {
    mockFetch({ active_jobs: [{ id: 'j1', type: 'classifier', model_key: 'deberta-v3', status: 'running' }] })
    const w = mount(DashboardView, { global: { plugins: [router] } })
    await flushPromises()
    const trainCard = w.find('.stage-card[data-stage="train"]')
    expect(trainCard.find('.status-pill').exists()).toBe(true)
    expect(trainCard.text()).toContain('deberta-v3')
  })

  it('shows last eval score in Eval card when present', async () => {
    mockFetch({ last_eval_best_score: 0.821 })
    const w = mount(DashboardView, { global: { plugins: [router] } })
    await flushPromises()
    const evalCard = w.find('.stage-card[data-stage="eval"]')
    expect(evalCard.text()).toContain('82.1%')
  })

  it('shows error state when API call fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503, text: async () => '' }))
    const w = mount(DashboardView, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.find('.error-notice').exists()).toBe(true)
  })

  it('shows refresh button', async () => {
    const w = mount(DashboardView, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.find('.refresh-btn').exists()).toBe(true)
  })
})
