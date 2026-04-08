// src/composables/useSftKeyboard.ts
import { onUnmounted, getCurrentInstance } from 'vue'

interface Options {
  onCorrect:  () => void
  onDiscard:  () => void
  onFlag:     () => void
  onEscape:   () => void
  onSubmit:   () => void
  isEditing:  () => boolean   // returns true when correction area is open
}

export function useSftKeyboard(opts: Options) {
  function handler(e: KeyboardEvent) {
    // Never intercept keys when focus is in an input (correction textarea handles its own keys)
    if (e.target instanceof HTMLInputElement) return

    // When correction area is open, only handle Escape (textarea handles Ctrl+Enter itself)
    if (e.target instanceof HTMLTextAreaElement) return

    const k = e.key.toLowerCase()

    if (opts.isEditing()) {
      if (k === 'escape') opts.onEscape()
      return
    }

    if (k === 'c') { opts.onCorrect();  return }
    if (k === 'd') { opts.onDiscard();  return }
    if (k === 'f') { opts.onFlag();     return }
    if (k === 'escape') { opts.onEscape(); return }
  }

  window.addEventListener('keydown', handler)
  const cleanup = () => window.removeEventListener('keydown', handler)

  if (getCurrentInstance()) {
    onUnmounted(cleanup)
  }

  return { cleanup }
}
