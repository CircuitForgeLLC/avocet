import { useMotion } from './useMotion'

export function useHaptics() {
  const { rich } = useMotion()

  function vibrate(pattern: number | number[]) {
    if (rich.value && typeof navigator !== 'undefined' && 'vibrate' in navigator) {
      navigator.vibrate(pattern)
    }
  }

  return {
    label:   () => vibrate(40),
    discard: () => vibrate([40, 30, 40]),
    skip:    () => vibrate(15),
    undo:    () => vibrate([20, 20, 60]),
  }
}
