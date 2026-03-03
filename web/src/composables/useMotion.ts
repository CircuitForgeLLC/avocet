import { computed, ref } from 'vue'

const STORAGE_KEY = 'cf-avocet-rich-motion'

// OS-level prefers-reduced-motion — checked once at module load
const OS_REDUCED = typeof window !== 'undefined'
  ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
  : false

// Reactive ref so toggling localStorage triggers re-reads in the same session
const _richOverride = ref(
  typeof window !== 'undefined'
    ? localStorage.getItem(STORAGE_KEY)
    : null
)

export function useMotion() {
  const rich = computed(() =>
    !OS_REDUCED && _richOverride.value !== 'false'
  )

  function setRich(enabled: boolean) {
    localStorage.setItem(STORAGE_KEY, enabled ? 'true' : 'false')
    _richOverride.value = enabled ? 'true' : 'false'
  }

  return { rich, setRich }
}
