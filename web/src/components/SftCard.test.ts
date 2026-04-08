import { mount } from '@vue/test-utils'
import SftCard from './SftCard.vue'
import type { SftQueueItem } from '../stores/sft'
import { describe, it, expect } from 'vitest'

const LOW_QUALITY_ITEM: SftQueueItem = {
  id: 'abc', source: 'cf-orch-benchmark', benchmark_run_id: 'run1',
  timestamp: '2026-04-07T10:00:00Z', status: 'needs_review',
  prompt_messages: [
    { role: 'system', content: 'You are a coding assistant.' },
    { role: 'user', content: 'Write a Python add function.' },
  ],
  model_response: 'def add(a, b): return a - b',
  corrected_response: null, quality_score: 0.2,
  failure_reason: 'pattern_match: 0/2 matched',
  task_id: 'code-fn', task_type: 'code', task_name: 'Code: Write a function',
  model_id: 'Qwen/Qwen2.5-3B', model_name: 'Qwen2.5-3B',
  node_id: 'heimdall', gpu_id: 0, tokens_per_sec: 38.4,
}

const MID_QUALITY_ITEM: SftQueueItem = { ...LOW_QUALITY_ITEM, id: 'mid', quality_score: 0.55 }
const HIGH_QUALITY_ITEM: SftQueueItem = { ...LOW_QUALITY_ITEM, id: 'hi', quality_score: 0.72 }

describe('SftCard', () => {
  it('renders model name chip', () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM } })
    expect(w.text()).toContain('Qwen2.5-3B')
  })

  it('renders task type chip', () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM } })
    expect(w.text()).toContain('code')
  })

  it('renders failure reason', () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM } })
    expect(w.text()).toContain('pattern_match: 0/2 matched')
  })

  it('renders model response', () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM } })
    expect(w.text()).toContain('def add(a, b): return a - b')
  })

  it('quality chip shows numeric value for low quality', () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM } })
    expect(w.text()).toContain('0.20')
  })

  it('quality chip has low-quality class when score < 0.4', () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM } })
    expect(w.find('[data-testid="quality-chip"]').classes()).toContain('quality-low')
  })

  it('quality chip has mid-quality class when score is 0.4 to <0.7', () => {
    const w = mount(SftCard, { props: { item: MID_QUALITY_ITEM } })
    expect(w.find('[data-testid="quality-chip"]').classes()).toContain('quality-mid')
  })

  it('quality chip has acceptable class when score >= 0.7', () => {
    const w = mount(SftCard, { props: { item: HIGH_QUALITY_ITEM } })
    expect(w.find('[data-testid="quality-chip"]').classes()).toContain('quality-ok')
  })

  it('clicking Correct button emits correct', async () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM } })
    await w.find('[data-testid="correct-btn"]').trigger('click')
    expect(w.emitted('correct')).toBeTruthy()
  })

  it('clicking Discard button emits discard', async () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM } })
    await w.find('[data-testid="discard-btn"]').trigger('click')
    expect(w.emitted('discard')).toBeTruthy()
  })

  it('clicking Flag Model button emits flag', async () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM } })
    await w.find('[data-testid="flag-btn"]').trigger('click')
    expect(w.emitted('flag')).toBeTruthy()
  })

  it('correction area hidden initially', () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM } })
    expect(w.find('[data-testid="correction-area"]').exists()).toBe(false)
  })

  it('correction area shown when correcting prop is true', () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM, correcting: true } })
    expect(w.find('[data-testid="correction-area"]').exists()).toBe(true)
  })

  it('renders nothing for failure reason when null', () => {
    const item = { ...LOW_QUALITY_ITEM, failure_reason: null }
    const w = mount(SftCard, { props: { item } })
    expect(w.find('.failure-reason').exists()).toBe(false)
  })
})
