import { ref } from 'vue'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock animejs before importing the composable
vi.mock('animejs', () => ({
  animate: vi.fn(),
  spring:  vi.fn(() => 'mock-spring'),
  utils:   { set: vi.fn() },
}))

import { useCardAnimation } from './useCardAnimation'
import { animate, utils } from 'animejs'

const mockAnimate = animate as ReturnType<typeof vi.fn>
const mockSet     = utils.set as ReturnType<typeof vi.fn>

function makeEl() {
  return document.createElement('div')
}

describe('useCardAnimation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('pickup() calls animate with ball shape', () => {
    const el = makeEl()
    const cardEl = ref<HTMLElement | null>(el)
    const motion = { rich: ref(true) }
    const { pickup } = useCardAnimation(cardEl, motion)
    pickup()
    expect(mockAnimate).toHaveBeenCalledWith(
      el,
      expect.objectContaining({ scale: 0.55, borderRadius: '50%' }),
    )
  })

  it('pickup() is a no-op when motion.rich is false', () => {
    const el = makeEl()
    const cardEl = ref<HTMLElement | null>(el)
    const motion = { rich: ref(false) }
    const { pickup } = useCardAnimation(cardEl, motion)
    pickup()
    expect(mockAnimate).not.toHaveBeenCalled()
  })

  it('setDragPosition() calls utils.set with translated coords', () => {
    const el = makeEl()
    const cardEl = ref<HTMLElement | null>(el)
    const motion = { rich: ref(true) }
    const { setDragPosition } = useCardAnimation(cardEl, motion)
    setDragPosition(50, 30)
    expect(mockSet).toHaveBeenCalledWith(el, expect.objectContaining({ x: 50, y: -50 }))
    // y = deltaY - 80 = 30 - 80 = -50
  })

  it('snapBack() calls animate returning to card shape', () => {
    const el = makeEl()
    const cardEl = ref<HTMLElement | null>(el)
    const motion = { rich: ref(true) }
    const { snapBack } = useCardAnimation(cardEl, motion)
    snapBack()
    expect(mockAnimate).toHaveBeenCalledWith(
      el,
      expect.objectContaining({ x: 0, y: 0, scale: 1 }),
    )
  })

  it('animateDismiss("label") calls animate', () => {
    const el = makeEl()
    const cardEl = ref<HTMLElement | null>(el)
    const motion = { rich: ref(true) }
    const { animateDismiss } = useCardAnimation(cardEl, motion)
    animateDismiss('label')
    expect(mockAnimate).toHaveBeenCalled()
  })

  it('animateDismiss("discard") calls animate', () => {
    const el = makeEl()
    const cardEl = ref<HTMLElement | null>(el)
    const motion = { rich: ref(true) }
    const { animateDismiss } = useCardAnimation(cardEl, motion)
    animateDismiss('discard')
    expect(mockAnimate).toHaveBeenCalled()
  })

  it('animateDismiss("skip") calls animate', () => {
    const el = makeEl()
    const cardEl = ref<HTMLElement | null>(el)
    const motion = { rich: ref(true) }
    const { animateDismiss } = useCardAnimation(cardEl, motion)
    animateDismiss('skip')
    expect(mockAnimate).toHaveBeenCalled()
  })

  it('animateDismiss is a no-op when motion.rich is false', () => {
    const el = makeEl()
    const cardEl = ref<HTMLElement | null>(el)
    const motion = { rich: ref(false) }
    const { animateDismiss } = useCardAnimation(cardEl, motion)
    animateDismiss('label')
    expect(mockAnimate).not.toHaveBeenCalled()
  })

  describe('updateAura', () => {
    it('sets red background for discard zone', () => {
      const el = makeEl()
      const cardEl = ref<HTMLElement | null>(el)
      const motion = { rich: ref(true) }
      const { updateAura } = useCardAnimation(cardEl, motion)
      updateAura('discard', null)
      expect(mockSet).toHaveBeenCalledWith(el, expect.objectContaining({ background: 'rgba(244, 67, 54, 0.25)' }))
    })

    it('sets orange background for skip zone', () => {
      const el = makeEl()
      const cardEl = ref<HTMLElement | null>(el)
      const motion = { rich: ref(true) }
      const { updateAura } = useCardAnimation(cardEl, motion)
      updateAura('skip', null)
      expect(mockSet).toHaveBeenCalledWith(el, expect.objectContaining({ background: 'rgba(255, 152,  0, 0.25)' }))
    })

    it('sets blue background for bucket hover', () => {
      const el = makeEl()
      const cardEl = ref<HTMLElement | null>(el)
      const motion = { rich: ref(true) }
      const { updateAura } = useCardAnimation(cardEl, motion)
      updateAura(null, 'interview_scheduled')
      expect(mockSet).toHaveBeenCalledWith(el, expect.objectContaining({ background: 'rgba(42,  96, 128, 0.20)' }))
    })

    it('sets transparent background when no zone/bucket', () => {
      const el = makeEl()
      const cardEl = ref<HTMLElement | null>(el)
      const motion = { rich: ref(true) }
      const { updateAura } = useCardAnimation(cardEl, motion)
      updateAura(null, null)
      expect(mockSet).toHaveBeenCalledWith(el, expect.objectContaining({ background: 'transparent' }))
    })
  })
})
