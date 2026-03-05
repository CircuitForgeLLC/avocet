import { mount } from '@vue/test-utils'
import LabelBucketGrid from './LabelBucketGrid.vue'
import { describe, it, expect } from 'vitest'

const labels = [
  { name: 'interview_scheduled', emoji: '🗓️', color: '#4CAF50', key: '1' },
  { name: 'offer_received',      emoji: '🎉', color: '#2196F3', key: '2' },
  { name: 'rejected',            emoji: '❌', color: '#F44336', key: '3' },
]

describe('LabelBucketGrid', () => {
  it('renders all labels', () => {
    const w = mount(LabelBucketGrid, { props: { labels, isBucketMode: false } })
    expect(w.findAll('[data-testid="label-btn"]')).toHaveLength(3)
  })

  it('emits label event on click', async () => {
    const w = mount(LabelBucketGrid, { props: { labels, isBucketMode: false } })
    await w.find('[data-testid="label-btn"]').trigger('click')
    expect(w.emitted('label')?.[0]).toEqual(['interview_scheduled'])
  })

  it('applies bucket-mode class when isBucketMode is true', () => {
    const w = mount(LabelBucketGrid, { props: { labels, isBucketMode: true } })
    expect(w.find('.label-grid').classes()).toContain('bucket-mode')
  })

  it('shows key hint and emoji', () => {
    const w = mount(LabelBucketGrid, { props: { labels, isBucketMode: false } })
    const btn = w.find('[data-testid="label-btn"]')
    expect(btn.text()).toContain('1')
    expect(btn.text()).toContain('🗓️')
  })

  it('marks button as drop-target when hoveredBucket matches label name', () => {
    const w = mount(LabelBucketGrid, {
      props: { labels, isBucketMode: true, hoveredBucket: 'interview_scheduled' },
    })
    const btns = w.findAll('[data-testid="label-btn"]')
    expect(btns[0].classes()).toContain('is-drop-target')
    expect(btns[1].classes()).not.toContain('is-drop-target')
  })

  it('no button marked as drop-target when hoveredBucket is null', () => {
    const w = mount(LabelBucketGrid, {
      props: { labels, isBucketMode: false, hoveredBucket: null },
    })
    w.findAll('[data-testid="label-btn"]').forEach(btn => {
      expect(btn.classes()).not.toContain('is-drop-target')
    })
  })
})
