import { mount } from '@vue/test-utils'
import EmailCardStack from './EmailCardStack.vue'
import { describe, it, expect } from 'vitest'

const item = {
  id: 'abc',
  subject: 'Interview at Acme',
  body: 'We would like to schedule...',
  from: 'hr@acme.com',
  date: '2026-03-01',
  source: 'imap:test',
}

describe('EmailCardStack', () => {
  it('renders the email subject', () => {
    const w = mount(EmailCardStack, { props: { item, isBucketMode: false } })
    expect(w.text()).toContain('Interview at Acme')
  })

  it('renders shadow cards for depth effect', () => {
    const w = mount(EmailCardStack, { props: { item, isBucketMode: false } })
    expect(w.findAll('.card-shadow')).toHaveLength(2)
  })

  it('applies dismiss-label class when dismissType is label', () => {
    const w = mount(EmailCardStack, { props: { item, isBucketMode: false, dismissType: 'label' } })
    expect(w.find('.card-wrapper').classes()).toContain('dismiss-label')
  })

  it('applies dismiss-discard class when dismissType is discard', () => {
    const w = mount(EmailCardStack, { props: { item, isBucketMode: false, dismissType: 'discard' } })
    expect(w.find('.card-wrapper').classes()).toContain('dismiss-discard')
  })

  it('applies dismiss-skip class when dismissType is skip', () => {
    const w = mount(EmailCardStack, { props: { item, isBucketMode: false, dismissType: 'skip' } })
    expect(w.find('.card-wrapper').classes()).toContain('dismiss-skip')
  })

  it('no dismiss class when dismissType is null', () => {
    const w = mount(EmailCardStack, { props: { item, isBucketMode: false, dismissType: null } })
    const wrapperClasses = w.find('.card-wrapper').classes()
    expect(wrapperClasses).not.toContain('dismiss-label')
    expect(wrapperClasses).not.toContain('dismiss-discard')
    expect(wrapperClasses).not.toContain('dismiss-skip')
  })

  it('emits drag-start on dragstart event', async () => {
    const w = mount(EmailCardStack, { props: { item, isBucketMode: false } })
    await w.find('.card-stack').trigger('dragstart')
    expect(w.emitted('drag-start')).toBeTruthy()
  })

  it('emits drag-end on dragend event', async () => {
    const w = mount(EmailCardStack, { props: { item, isBucketMode: false } })
    await w.find('.card-stack').trigger('dragend')
    expect(w.emitted('drag-end')).toBeTruthy()
  })
})
