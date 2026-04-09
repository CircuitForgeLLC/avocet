import { describe, it, expect } from 'vitest'

describe('scaffold', () => {
  it('vitest works', () => {
    expect(1 + 1).toBe(2)
  })
})

describe('composable imports', () => {
  it('useApi imports', async () => {
    const { useApiFetch } = await import('./composables/useApi')
    expect(typeof useApiFetch).toBe('function')
  })

  it('useMotion imports', async () => {
    const { useMotion } = await import('./composables/useMotion')
    expect(typeof useMotion).toBe('function')
  })

  it('useHaptics imports', async () => {
    const { useHaptics } = await import('./composables/useHaptics')
    expect(typeof useHaptics).toBe('function')
  })

  it('useEasterEgg imports', async () => {
    const { useKonamiCode, useHackerMode } = await import('./composables/useEasterEgg')
    expect(typeof useKonamiCode).toBe('function')
    expect(typeof useHackerMode).toBe('function')
  })
})
