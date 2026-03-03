import { onMounted, onUnmounted } from 'vue'

const KONAMI = ['ArrowUp','ArrowUp','ArrowDown','ArrowDown','ArrowLeft','ArrowRight','ArrowLeft','ArrowRight','b','a']

export function useKonamiCode(onActivate: () => void) {
  let pos = 0

  function handler(e: KeyboardEvent) {
    if (e.key === KONAMI[pos]) {
      pos++
      if (pos === KONAMI.length) {
        pos = 0
        onActivate()
      }
    } else {
      pos = 0
    }
  }

  onMounted(()   => window.addEventListener('keydown', handler))
  onUnmounted(() => window.removeEventListener('keydown', handler))
}

export function useHackerMode() {
  function toggle() {
    const root = document.documentElement
    if (root.dataset.theme === 'hacker') {
      delete root.dataset.theme
      localStorage.removeItem('cf-hacker-mode')
    } else {
      root.dataset.theme = 'hacker'
      localStorage.setItem('cf-hacker-mode', 'true')
    }
  }

  function restore() {
    if (localStorage.getItem('cf-hacker-mode') === 'true') {
      document.documentElement.dataset.theme = 'hacker'
    }
  }

  return { toggle, restore }
}
