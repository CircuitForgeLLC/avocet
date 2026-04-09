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
  failure_category: null,
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

  it('clicking Discard button then confirming emits discard', async () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM } })
    await w.find('[data-testid="discard-btn"]').trigger('click')
    await w.find('[data-testid="confirm-pending-btn"]').trigger('click')
    expect(w.emitted('discard')).toBeTruthy()
  })

  it('clicking Flag Model button then confirming emits flag', async () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM } })
    await w.find('[data-testid="flag-btn"]').trigger('click')
    await w.find('[data-testid="confirm-pending-btn"]').trigger('click')
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

  // ── Failure category chip-group ───────────────────────────────────
  it('failure category section hidden when not correcting and no pending action', () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM } })
    expect(w.find('[data-testid="failure-category-section"]').exists()).toBe(false)
  })

  it('failure category section shown when correcting prop is true', () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM, correcting: true } })
    expect(w.find('[data-testid="failure-category-section"]').exists()).toBe(true)
  })

  it('renders all six category chips when correcting', () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM, correcting: true } })
    const chips = w.findAll('.category-chip')
    expect(chips).toHaveLength(6)
  })

  it('clicking a category chip selects it (adds active class)', async () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM, correcting: true } })
    const chip = w.find('[data-testid="category-chip-wrong_answer"]')
    await chip.trigger('click')
    expect(chip.classes()).toContain('category-chip--active')
  })

  it('clicking the active chip again deselects it', async () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM, correcting: true } })
    const chip = w.find('[data-testid="category-chip-hallucination"]')
    await chip.trigger('click')
    expect(chip.classes()).toContain('category-chip--active')
    await chip.trigger('click')
    expect(chip.classes()).not.toContain('category-chip--active')
  })

  it('only one chip can be active at a time', async () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM, correcting: true } })
    await w.find('[data-testid="category-chip-wrong_answer"]').trigger('click')
    await w.find('[data-testid="category-chip-hallucination"]').trigger('click')
    const active = w.findAll('.category-chip--active')
    expect(active).toHaveLength(1)
    expect(active[0].attributes('data-testid')).toBe('category-chip-hallucination')
  })

  it('clicking Discard shows pending action row with category section', async () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM } })
    await w.find('[data-testid="discard-btn"]').trigger('click')
    expect(w.find('[data-testid="failure-category-section"]').exists()).toBe(true)
    expect(w.find('[data-testid="pending-action-row"]').exists()).toBe(true)
  })

  it('clicking Flag shows pending action row', async () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM } })
    await w.find('[data-testid="flag-btn"]').trigger('click')
    expect(w.find('[data-testid="pending-action-row"]').exists()).toBe(true)
  })

  it('confirming discard emits discard with null when no category selected', async () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM } })
    await w.find('[data-testid="discard-btn"]').trigger('click')
    await w.find('[data-testid="confirm-pending-btn"]').trigger('click')
    expect(w.emitted('discard')).toBeTruthy()
    expect(w.emitted('discard')![0]).toEqual([null])
  })

  it('confirming discard emits discard with selected category', async () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM } })
    await w.find('[data-testid="discard-btn"]').trigger('click')
    await w.find('[data-testid="category-chip-scoring_artifact"]').trigger('click')
    await w.find('[data-testid="confirm-pending-btn"]').trigger('click')
    expect(w.emitted('discard')![0]).toEqual(['scoring_artifact'])
  })

  it('cancelling pending action hides the pending row', async () => {
    const w = mount(SftCard, { props: { item: LOW_QUALITY_ITEM } })
    await w.find('[data-testid="discard-btn"]').trigger('click')
    await w.find('[data-testid="cancel-pending-btn"]').trigger('click')
    expect(w.find('[data-testid="pending-action-row"]').exists()).toBe(false)
  })
})
