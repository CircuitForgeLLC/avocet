import { useLabelKeyboard } from './useLabelKeyboard'
import { describe, it, expect, vi, afterEach } from 'vitest'

const LABELS = [
  { name: 'interview_scheduled', key: '1', emoji: '🗓️', color: '#4CAF50' },
  { name: 'offer_received',      key: '2', emoji: '🎉', color: '#2196F3' },
  { name: 'rejected',            key: '3', emoji: '❌', color: '#F44336' },
]

describe('useLabelKeyboard', () => {
  const cleanups: (() => void)[] = []

  afterEach(() => {
    cleanups.forEach(fn => fn())
    cleanups.length = 0
  })

  it('calls onLabel when digit key pressed', () => {
    const onLabel = vi.fn()
    const { cleanup } = useLabelKeyboard({ labels: LABELS, onLabel, onSkip: vi.fn(), onDiscard: vi.fn(), onUndo: vi.fn(), onHelp: vi.fn() })
    cleanups.push(cleanup)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '1' }))
    expect(onLabel).toHaveBeenCalledWith('interview_scheduled')
  })

  it('calls onLabel for key 2', () => {
    const onLabel = vi.fn()
    const { cleanup } = useLabelKeyboard({ labels: LABELS, onLabel, onSkip: vi.fn(), onDiscard: vi.fn(), onUndo: vi.fn(), onHelp: vi.fn() })
    cleanups.push(cleanup)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '2' }))
    expect(onLabel).toHaveBeenCalledWith('offer_received')
  })

  it('calls onLabel("hired") when h pressed', () => {
    const onLabel = vi.fn()
    const { cleanup } = useLabelKeyboard({ labels: LABELS, onLabel, onSkip: vi.fn(), onDiscard: vi.fn(), onUndo: vi.fn(), onHelp: vi.fn() })
    cleanups.push(cleanup)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'h' }))
    expect(onLabel).toHaveBeenCalledWith('hired')
  })

  it('calls onSkip when s pressed', () => {
    const onSkip = vi.fn()
    const { cleanup } = useLabelKeyboard({ labels: LABELS, onLabel: vi.fn(), onSkip, onDiscard: vi.fn(), onUndo: vi.fn(), onHelp: vi.fn() })
    cleanups.push(cleanup)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 's' }))
    expect(onSkip).toHaveBeenCalled()
  })

  it('calls onDiscard when d pressed', () => {
    const onDiscard = vi.fn()
    const { cleanup } = useLabelKeyboard({ labels: LABELS, onLabel: vi.fn(), onSkip: vi.fn(), onDiscard, onUndo: vi.fn(), onHelp: vi.fn() })
    cleanups.push(cleanup)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'd' }))
    expect(onDiscard).toHaveBeenCalled()
  })

  it('calls onUndo when u pressed', () => {
    const onUndo = vi.fn()
    const { cleanup } = useLabelKeyboard({ labels: LABELS, onLabel: vi.fn(), onSkip: vi.fn(), onDiscard: vi.fn(), onUndo, onHelp: vi.fn() })
    cleanups.push(cleanup)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'u' }))
    expect(onUndo).toHaveBeenCalled()
  })

  it('calls onHelp when ? pressed', () => {
    const onHelp = vi.fn()
    const { cleanup } = useLabelKeyboard({ labels: LABELS, onLabel: vi.fn(), onSkip: vi.fn(), onDiscard: vi.fn(), onUndo: vi.fn(), onHelp })
    cleanups.push(cleanup)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '?' }))
    expect(onHelp).toHaveBeenCalled()
  })

  it('ignores keydown when target is an input', () => {
    const onLabel = vi.fn()
    const { cleanup } = useLabelKeyboard({ labels: LABELS, onLabel, onSkip: vi.fn(), onDiscard: vi.fn(), onUndo: vi.fn(), onHelp: vi.fn() })
    cleanups.push(cleanup)
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.dispatchEvent(new KeyboardEvent('keydown', { key: '1', bubbles: true }))
    expect(onLabel).not.toHaveBeenCalled()
    document.body.removeChild(input)
  })

  it('cleanup removes the listener', () => {
    const onLabel = vi.fn()
    const { cleanup } = useLabelKeyboard({ labels: LABELS, onLabel, onSkip: vi.fn(), onDiscard: vi.fn(), onUndo: vi.fn(), onHelp: vi.fn() })
    cleanup()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '1' }))
    expect(onLabel).not.toHaveBeenCalled()
  })
})
