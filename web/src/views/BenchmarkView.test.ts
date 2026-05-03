import { mount } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import BenchmarkView from './BenchmarkView.vue'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    // Return a shape that satisfies all child tab API calls:
    // - ClassifierTab expects { models: {}, ... } from /api/benchmark/results
    // - ClassifierTab expects ModelCategoriesResponse from /api/benchmark/models
    // - LlmEvalTab, StyleTab, CompareTab have their own calls but also use models/tasks
    json: async () => ({ models: {}, categories: {}, tasks: [], types: [], results: [] }),
    text: async () => '',
  }))
  vi.stubGlobal('EventSource', class {
    onmessage = null
    onerror = null
    close() {}
  })
})

describe('BenchmarkView', () => {
  it('renders page title "Benchmark"', () => {
    const w = mount(BenchmarkView)
    expect(w.text()).toContain('Benchmark')
  })

  it('has mode buttons: Classifier, LLM Eval, Writing Style', () => {
    const w = mount(BenchmarkView)
    const text = w.text()
    expect(text).toContain('Classifier')
    expect(text).toContain('LLM Eval')
    expect(text).toContain('Writing Style')
  })

  it('does NOT have a Compare mode button', () => {
    const w = mount(BenchmarkView)
    const buttons = w.findAll('.mode-btn')
    const labels = buttons.map(b => b.text())
    expect(labels.every(l => !l.includes('Compare'))).toBe(true)
  })

  it('shows Classifier tab by default', () => {
    const w = mount(BenchmarkView)
    // ClassifierTab has a .classifier-tab root
    expect(w.find('.classifier-tab').exists()).toBe(true)
  })
})
