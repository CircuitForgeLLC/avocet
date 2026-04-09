import { mount } from '@vue/test-utils'
import EmailCardStack from './EmailCardStack.vue'
import { describe, it, expect, vi } from 'vitest'

vi.mock('../composables/useCardAnimation', () => ({
  useCardAnimation: vi.fn(() => ({
    pickup:          vi.fn(),
    setDragPosition: vi.fn(),
    snapBack:        vi.fn(),
    animateDismiss:  vi.fn(),
    updateAura:      vi.fn(),
    reset:           vi.fn(),
  })),
}))

import { useCardAnimation } from '../composables/useCardAnimation'
import { nextTick } from 'vue'

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

  it('calls animateDismiss with type when dismissType prop changes', async () => {
    ;(useCardAnimation as ReturnType<typeof vi.fn>).mockClear()
    const w = mount(EmailCardStack, { props: { item, isBucketMode: false, dismissType: null } })
    const { animateDismiss } = (useCardAnimation as ReturnType<typeof vi.fn>).mock.results[0].value
    await w.setProps({ dismissType: 'label' })
    await nextTick()
    expect(animateDismiss).toHaveBeenCalledWith('label')
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

  // Fling tests — mock performance.now() to control timestamps between events
  it('emits discard on fast leftward fling (option B: speed + alignment)', async () => {
    let mockTime = 0
    vi.spyOn(performance, 'now').mockImplementation(() => mockTime)
    const w = mount(EmailCardStack, { props: { item, isBucketMode: false } })
    const el = w.find('.card-wrapper').element
    mockPointerCapture(el)
    mockTime = 0;  fire(el, 'pointerdown', { pointerId: 1, clientX: 512, clientY: 300 })
    mockTime = 30; fire(el, 'pointermove', { pointerId: 1, clientX: 400, clientY: 310 })
    mockTime = 50; fire(el, 'pointermove', { pointerId: 1, clientX: 288, clientY: 320 })
    // vx = (288-400)/(50-30)*1000 = -5600 px/s, vy ≈ 500 px/s
    // speed ≈ 5622 px/s > 600, alignment = 5600/5622 ≈ 0.996 > 0.707 ✓
    fire(el, 'pointerup', { pointerId: 1, clientX: 288, clientY: 320 })
    await w.vm.$nextTick()
    expect(w.emitted('discard')).toBeTruthy()
    vi.restoreAllMocks()
  })

  it('emits skip on fast rightward fling', async () => {
    let mockTime = 0
    vi.spyOn(performance, 'now').mockImplementation(() => mockTime)
    const w = mount(EmailCardStack, { props: { item, isBucketMode: false } })
    const el = w.find('.card-wrapper').element
    mockPointerCapture(el)
    mockTime = 0;  fire(el, 'pointerdown', { pointerId: 1, clientX: 512, clientY: 300 })
    mockTime = 30; fire(el, 'pointermove', { pointerId: 1, clientX: 624, clientY: 310 })
    mockTime = 50; fire(el, 'pointermove', { pointerId: 1, clientX: 736, clientY: 320 })
    // vx = (736-624)/(50-30)*1000 = 5600 px/s — mirror of discard case
    fire(el, 'pointerup', { pointerId: 1, clientX: 736, clientY: 320 })
    await w.vm.$nextTick()
    expect(w.emitted('skip')).toBeTruthy()
    vi.restoreAllMocks()
  })

  it('does not fling on diagonal swipe (alignment < 0.707)', async () => {
    let mockTime = 0
    vi.spyOn(performance, 'now').mockImplementation(() => mockTime)
    const w = mount(EmailCardStack, { props: { item, isBucketMode: false } })
    const el = w.find('.card-wrapper').element
    mockPointerCapture(el)
    mockTime = 0;  fire(el, 'pointerdown', { pointerId: 1, clientX: 512, clientY: 300 })
    mockTime = 30; fire(el, 'pointermove', { pointerId: 1, clientX: 400, clientY: 150 })
    mockTime = 50; fire(el, 'pointermove', { pointerId: 1, clientX: 288, clientY:   0 })
    // vx = -5600 px/s, vy = -7500 px/s, speed ≈ 9356 px/s
    // alignment = 5600/9356 ≈ 0.598 < 0.707 — too diagonal ✓
    fire(el, 'pointerup', { pointerId: 1, clientX: 288, clientY: 0 })
    await w.vm.$nextTick()
    expect(w.emitted('discard')).toBeFalsy()
    expect(w.emitted('skip')).toBeFalsy()
    vi.restoreAllMocks()
  })

  it('does not fling on slow movement (speed < threshold)', async () => {
    let mockTime = 0
    vi.spyOn(performance, 'now').mockImplementation(() => mockTime)
    const w = mount(EmailCardStack, { props: { item, isBucketMode: false } })
    const el = w.find('.card-wrapper').element
    mockPointerCapture(el)
    mockTime = 0;   fire(el, 'pointerdown', { pointerId: 1, clientX: 512, clientY: 300 })
    mockTime = 100; fire(el, 'pointermove', { pointerId: 1, clientX: 480, clientY: 300 })
    mockTime = 200; fire(el, 'pointermove', { pointerId: 1, clientX: 450, clientY: 300 })
    // vx = (450-480)/(200-100)*1000 = -300 px/s < 600 threshold
    fire(el, 'pointerup', { pointerId: 1, clientX: 450, clientY: 300 })
    await w.vm.$nextTick()
    expect(w.emitted('discard')).toBeFalsy()
    expect(w.emitted('skip')).toBeFalsy()
    vi.restoreAllMocks()
  })
})
