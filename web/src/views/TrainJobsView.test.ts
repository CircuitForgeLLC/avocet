import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import TrainJobsView from './TrainJobsView.vue'

const sampleJob = {
  id: 'job-abc123',
  type: 'classifier',
  model_key: 'deberta-v3-small',
  status: 'queued',
  created_at: '2026-05-01T10:00:00Z',
  config: null,
}

function makeFetch(jobs: unknown[] = []) {
  return vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
    if ((opts?.method ?? 'GET') === 'POST') {
      return Promise.resolve({
        ok: true,
        json: async () => ({ ...sampleJob, id: 'new-job', status: 'queued' }),
        text: async () => '',
      })
    }
    if ((opts?.method ?? 'GET') === 'DELETE') {
      return Promise.resolve({ ok: true, json: async () => ({}), text: async () => '' })
    }
    // GET
    return Promise.resolve({
      ok: true,
      json: async () => ({ jobs }),
      text: async () => '',
    })
  })
}

class MockEventSource {
  onmessage: ((e: MessageEvent) => void) | null = null
  onerror: ((e: Event) => void) | null = null
  private _url: string
  constructor(url: string) { this._url = url }
  close() {}
}

beforeEach(() => {
  vi.stubGlobal('fetch', makeFetch([sampleJob]))
  vi.stubGlobal('EventSource', MockEventSource)
})

describe('TrainJobsView', () => {
  it('renders page title "Training Jobs"', async () => {
    const w = mount(TrainJobsView)
    await flushPromises()
    expect(w.find('h1.page-title').text()).toContain('Training Jobs')
  })

  it('renders the new job form with type selector and model key input', async () => {
    const w = mount(TrainJobsView)
    await flushPromises()
    expect(w.find('select.job-type-select').exists()).toBe(true)
    expect(w.find('input.model-key-input').exists()).toBe(true)
    expect(w.find('button.submit-job-btn').exists()).toBe(true)
  })

  it('type selector has classifier and llm-sft options', async () => {
    const w = mount(TrainJobsView)
    await flushPromises()
    const options = w.findAll('select.job-type-select option')
    const values = options.map(o => o.attributes('value') ?? o.element.textContent)
    expect(values).toContain('classifier')
    expect(values).toContain('llm-sft')
  })

  it('submit button is disabled when model key is empty', async () => {
    const w = mount(TrainJobsView)
    await flushPromises()
    const btn = w.find('button.submit-job-btn')
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('submit button is enabled when model key is entered', async () => {
    const w = mount(TrainJobsView)
    await flushPromises()
    await w.find('input.model-key-input').setValue('deberta-v3-small')
    const btn = w.find('button.submit-job-btn')
    expect((btn.element as HTMLButtonElement).disabled).toBe(false)
  })

  it('shows job table with existing jobs', async () => {
    const w = mount(TrainJobsView)
    await flushPromises()
    expect(w.find('table.jobs-table').exists()).toBe(true)
    expect(w.text()).toContain('deberta-v3-small')
  })

  it('shows status pill for each job', async () => {
    const w = mount(TrainJobsView)
    await flushPromises()
    expect(w.find('.status-pill').exists()).toBe(true)
    expect(w.find('.status-queued').exists()).toBe(true)
  })

  it('shows cancel button for queued/running jobs', async () => {
    const w = mount(TrainJobsView)
    await flushPromises()
    expect(w.find('button.cancel-btn').exists()).toBe(true)
  })

  it('submitting new job calls POST /api/train/jobs and refreshes', async () => {
    const fetchMock = makeFetch([])
    vi.stubGlobal('fetch', fetchMock)
    const w = mount(TrainJobsView)
    await flushPromises()
    await w.find('input.model-key-input').setValue('my-model')
    await w.find('button.submit-job-btn').trigger('click')
    await flushPromises()
    const calls = (fetchMock as ReturnType<typeof vi.fn>).mock.calls as [string, RequestInit?][]
    const postCall = calls.find(([, opts]) => (opts?.method ?? 'GET') === 'POST')
    expect(postCall).toBeDefined()
    expect(postCall![0]).toContain('/api/train/jobs')
  })

  it('shows View Log button for running jobs', async () => {
    vi.stubGlobal('fetch', makeFetch([{ ...sampleJob, status: 'running' }]))
    const w = mount(TrainJobsView)
    await flushPromises()
    expect(w.find('button.view-log-btn').exists()).toBe(true)
  })
})
