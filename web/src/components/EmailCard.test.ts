import { mount } from '@vue/test-utils'
import EmailCard from './EmailCard.vue'
import { describe, it, expect } from 'vitest'

const item = {
  id: 'abc', subject: 'Interview Invitation',
  body: 'Hi there, we would like to schedule a phone screen with you. This will be a 30-minute call.',
  from: 'recruiter@acme.com', date: '2026-03-01', source: 'imap:test',
}

describe('EmailCard', () => {
  it('renders subject', () => {
    const w = mount(EmailCard, { props: { item } })
    expect(w.text()).toContain('Interview Invitation')
  })

  it('renders from and date', () => {
    const w = mount(EmailCard, { props: { item } })
    expect(w.text()).toContain('recruiter@acme.com')
    expect(w.text()).toContain('2026-03-01')
  })

  it('renders truncated body by default', () => {
    const w = mount(EmailCard, { props: { item } })
    expect(w.text()).toContain('Hi there')
  })

  it('emits expand on button click', async () => {
    const w = mount(EmailCard, { props: { item } })
    await w.find('[data-testid="expand-btn"]').trigger('click')
    expect(w.emitted('expand')).toBeTruthy()
  })

  it('shows collapse button when expanded', () => {
    const w = mount(EmailCard, { props: { item, expanded: true } })
    expect(w.find('[data-testid="collapse-btn"]').exists()).toBe(true)
    expect(w.find('[data-testid="expand-btn"]').exists()).toBe(false)
  })
})
