import { onUnmounted, getCurrentInstance } from 'vue'

interface Label { name: string; key: string; emoji: string; color: string }

interface Options {
  labels: Label[]
  onLabel:   (name: string) => void
  onSkip:    () => void
  onDiscard: () => void
  onUndo:    () => void
  onHelp:    () => void
}

export function useLabelKeyboard(opts: Options) {
  const keyMap = new Map(opts.labels.map(l => [l.key.toLowerCase(), l.name]))

  function handler(e: KeyboardEvent) {
    if (e.target instanceof HTMLInputElement) return
    if (e.target instanceof HTMLTextAreaElement) return
    const k = e.key.toLowerCase()
    if (keyMap.has(k))  { opts.onLabel(keyMap.get(k)!); return }
    if (k === 'h')      { opts.onLabel('hired');         return }
    if (k === 's')      { opts.onSkip();                 return }
    if (k === 'd')      { opts.onDiscard();              return }
    if (k === 'u')      { opts.onUndo();                 return }
    if (k === '?')      { opts.onHelp();                 return }
  }

  // Add listener immediately (composable is called in setup, not in onMounted)
  window.addEventListener('keydown', handler)

  const cleanup = () => window.removeEventListener('keydown', handler)

  // In component context: auto-cleanup on unmount
  if (getCurrentInstance()) {
    onUnmounted(cleanup)
  }

  return { cleanup }
}
