import { mount } from '@vue/test-utils'
import EmailCardStack from './EmailCardStack.vue'
import { describe, it, expect, vi } from 'vitest'

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

  // JSDOM doesn't implement setPointerCapture — mock it on the element.
  // Also use dispatchEvent(new PointerEvent) directly because @vue/test-utils
  // .trigger() tries to assign clientX on a MouseEvent (read-only in JSDOM).
  function mockPointerCapture(element: Element) {
    ;(element as any).setPointerCapture = vi.fn()
    ;(element as any).releasePointerCapture = vi.fn()
  }

  function fire(element: Element, type: string, init: PointerEventInit) {
    element.dispatchEvent(new PointerEvent(type, { bubbles: true, ...init }))
  }

  it('emits drag-start on pointerdown', async () => {
    const w = mount(EmailCardStack, { props: { item, isBucketMode: false } })
    const el = w.find('.card-wrapper').element
    mockPointerCapture(el)
    fire(el, 'pointerdown', { pointerId: 1, clientX: 200, clientY: 300 })
    await w.vm.$nextTick()
    expect(w.emitted('drag-start')).toBeTruthy()
  })

  it('emits drag-end on pointerup', async () => {
    const w = mount(EmailCardStack, { props: { item, isBucketMode: false } })
    const el = w.find('.card-wrapper').element
    mockPointerCapture(el)
    fire(el, 'pointerdown', { pointerId: 1, clientX: 200, clientY: 300 })
    fire(el, 'pointerup',   { pointerId: 1, clientX: 200, clientY: 300 })
    await w.vm.$nextTick()
    expect(w.emitted('drag-end')).toBeTruthy()
  })

  it('emits discard when released in left zone (x < 7% viewport)', async () => {
    const w = mount(EmailCardStack, { props: { item, isBucketMode: false } })
    const el = w.find('.card-wrapper').element
    mockPointerCapture(el)
    // JSDOM window.innerWidth defaults to 1024; 7% = 71.7px
    fire(el, 'pointerdown', { pointerId: 1, clientX: 512, clientY: 300 })
    fire(el, 'pointermove', { pointerId: 1, clientX: 30,  clientY: 300 })
    fire(el, 'pointerup',   { pointerId: 1, clientX: 30,  clientY: 300 })
    await w.vm.$nextTick()
    expect(w.emitted('discard')).toBeTruthy()
  })

  it('emits skip when released in right zone (x > 93% viewport)', async () => {
    const w = mount(EmailCardStack, { props: { item, isBucketMode: false } })
    const el = w.find('.card-wrapper').element
    mockPointerCapture(el)
    // JSDOM window.innerWidth defaults to 1024; 93% = 952px
    fire(el, 'pointerdown', { pointerId: 1, clientX: 512,  clientY: 300 })
    fire(el, 'pointermove', { pointerId: 1, clientX: 1000, clientY: 300 })
    fire(el, 'pointerup',   { pointerId: 1, clientX: 1000, clientY: 300 })
    await w.vm.$nextTick()
    expect(w.emitted('skip')).toBeTruthy()
  })

  it('does not emit action on pointerup without movement past zone', async () => {
    const w = mount(EmailCardStack, { props: { item, isBucketMode: false } })
    const el = w.find('.card-wrapper').element
    mockPointerCapture(el)
    fire(el, 'pointerdown', { pointerId: 1, clientX: 512, clientY: 300 })
    fire(el, 'pointerup',   { pointerId: 1, clientX: 512, clientY: 300 })
    await w.vm.$nextTick()
    expect(w.emitted('discard')).toBeFalsy()
    expect(w.emitted('skip')).toBeFalsy()
    expect(w.emitted('label')).toBeFalsy()
  })
})
