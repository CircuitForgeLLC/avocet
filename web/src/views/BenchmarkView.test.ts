import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import BenchmarkView from './BenchmarkView.vue'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
    // LlmEvalTab calls /api/cforch/models and expects { models: CfOrchModel[] }
    if (url.includes('/api/cforch/models')) {
      return Promise.resolve({
        ok: true,
        json: async () => ({ models: [] }),
        text: async () => '',
      })
    }
    // Default: satisfies ClassifierTab (/api/benchmark/results, /api/benchmark/models,
    // /api/finetune/status), StyleTab (/api/style/models, /api/style/results),
    // and any other tab that tolerates empty arrays/objects.
    return Promise.resolve({
      ok: true,
      json: async () => ({ models: {}, categories: {}, tasks: [], types: [], results: [] }),
      text: async () => '',
    })
  }))
  vi.stubGlobal('EventSource', class {
    onmessage = null
    onerror = null
    close() {}
  })
})

describe('BenchmarkView', () => {
  it('renders page title "Benchmark"', async () => {
    const w = mount(BenchmarkView)
    await flushPromises()
    expect(w.text()).toContain('Benchmark')
  })

  it('has mode buttons: Classifier, LLM Eval, Writing Style', async () => {
    const w = mount(BenchmarkView)
    await flushPromises()
    const text = w.text()
    expect(text).toContain('Classifier')
    expect(text).toContain('LLM Eval')
    expect(text).toContain('Writing Style')
  })

  it('does NOT have a Compare mode button', async () => {
    const w = mount(BenchmarkView)
    await flushPromises()
    const buttons = w.findAll('.mode-btn')
    const labels = buttons.map(b => b.text())
    expect(labels.every(l => !l.includes('Compare'))).toBe(true)
  })

  it('shows Classifier tab by default', async () => {
    const w = mount(BenchmarkView)
    await flushPromises()
    // ClassifierTab has a .classifier-tab root
    expect(w.find('.classifier-tab').exists()).toBe(true)
  })

  it('switches to LlmEvalTab when LLM Eval clicked', async () => {
    const w = mount(BenchmarkView)
    await flushPromises()
    const llmBtn = w.findAll('.mode-btn').find(b => b.text().includes('LLM Eval'))!
    await llmBtn.trigger('click')
    await flushPromises()
    expect(w.find('.llm-eval-tab').exists()).toBe(true)
    expect(w.find('.classifier-tab').exists()).toBe(false)
    expect(llmBtn.classes()).toContain('active')
  })

  it('switches to StyleTab when Writing Style clicked', async () => {
    const w = mount(BenchmarkView)
    await flushPromises()
    const styleBtn = w.findAll('.mode-btn').find(b => b.text().includes('Writing Style'))!
    await styleBtn.trigger('click')
    await flushPromises()
    expect(w.find('.style-tab').exists()).toBe(true)
    expect(w.find('.classifier-tab').exists()).toBe(false)
  })
})
