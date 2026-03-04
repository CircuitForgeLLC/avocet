import { mount } from '@vue/test-utils'
import UndoToast from './UndoToast.vue'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Mock requestAnimationFrame for jsdom
beforeEach(() => {
  vi.stubGlobal('requestAnimationFrame', (fn: FrameRequestCallback) => {
    // Call with a fake timestamp to simulate one frame
    setTimeout(() => fn(16), 0)
    return 1
  })
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const labelAction = {
  type: 'label' as const,
  item: { id: 'abc', subject: 'Interview at Acme', body: '...', from: 'hr@acme.com', date: '2026-03-01', source: 'imap:test' },
  label: 'interview_scheduled',
}

const skipAction = {
  type: 'skip' as const,
  item: { id: 'xyz', subject: 'Cold Outreach', body: '...', from: 'recruiter@x.com', date: '2026-03-01', source: 'imap:test' },
}

const discardAction = {
  type: 'discard' as const,
  item: { id: 'def', subject: 'Spam Email', body: '...', from: 'spam@spam.com', date: '2026-03-01', source: 'imap:test' },
}

describe('UndoToast', () => {
  it('renders subject for a label action', () => {
    const w = mount(UndoToast, { props: { action: labelAction } })
    expect(w.text()).toContain('Interview at Acme')
    expect(w.text()).toContain('interview_scheduled')
  })

  it('renders subject for a skip action', () => {
    const w = mount(UndoToast, { props: { action: skipAction } })
    expect(w.text()).toContain('Cold Outreach')
    expect(w.text()).toContain('Skipped')
  })

  it('renders subject for a discard action', () => {
    const w = mount(UndoToast, { props: { action: discardAction } })
    expect(w.text()).toContain('Spam Email')
    expect(w.text()).toContain('Discarded')
  })

  it('has undo button', () => {
    const w = mount(UndoToast, { props: { action: labelAction } })
    expect(w.find('.undo-btn').exists()).toBe(true)
  })

  it('emits undo when button clicked', async () => {
    const w = mount(UndoToast, { props: { action: labelAction } })
    await w.find('.undo-btn').trigger('click')
    expect(w.emitted('undo')).toBeTruthy()
  })

  it('has timer bar element', () => {
    const w = mount(UndoToast, { props: { action: labelAction } })
    expect(w.find('.timer-bar').exists()).toBe(true)
  })

  it('has accessible role=status', () => {
    const w = mount(UndoToast, { props: { action: labelAction } })
    expect(w.find('[role="status"]').exists()).toBe(true)
  })
})
