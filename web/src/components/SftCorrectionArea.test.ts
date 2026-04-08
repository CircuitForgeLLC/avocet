import { mount } from '@vue/test-utils'
import SftCorrectionArea from './SftCorrectionArea.vue'
import { describe, it, expect } from 'vitest'

describe('SftCorrectionArea', () => {
  it('renders a textarea', () => {
    const w = mount(SftCorrectionArea)
    expect(w.find('textarea').exists()).toBe(true)
  })

  it('submit button is disabled when textarea is empty', () => {
    const w = mount(SftCorrectionArea)
    const btn = w.find('[data-testid="submit-btn"]')
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('submit button is disabled when textarea is whitespace only', async () => {
    const w = mount(SftCorrectionArea)
    await w.find('textarea').setValue('   ')
    const btn = w.find('[data-testid="submit-btn"]')
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('submit button is enabled when textarea has content', async () => {
    const w = mount(SftCorrectionArea)
    await w.find('textarea').setValue('def add(a, b): return a + b')
    const btn = w.find('[data-testid="submit-btn"]')
    expect((btn.element as HTMLButtonElement).disabled).toBe(false)
  })

  it('clicking submit emits submit with trimmed text', async () => {
    const w = mount(SftCorrectionArea)
    await w.find('textarea').setValue('  def add(a, b): return a + b  ')
    await w.find('[data-testid="submit-btn"]').trigger('click')
    expect(w.emitted('submit')?.[0]).toEqual(['def add(a, b): return a + b'])
  })

  it('clicking cancel emits cancel', async () => {
    const w = mount(SftCorrectionArea)
    await w.find('[data-testid="cancel-btn"]').trigger('click')
    expect(w.emitted('cancel')).toBeTruthy()
  })

  it('Escape key emits cancel', async () => {
    const w = mount(SftCorrectionArea)
    await w.find('textarea').trigger('keydown', { key: 'Escape' })
    expect(w.emitted('cancel')).toBeTruthy()
  })

  it('Ctrl+Enter emits submit when text is non-empty', async () => {
    const w = mount(SftCorrectionArea)
    await w.find('textarea').setValue('correct answer')
    await w.find('textarea').trigger('keydown', { key: 'Enter', ctrlKey: true })
    expect(w.emitted('submit')?.[0]).toEqual(['correct answer'])
  })

  it('Ctrl+Enter does not emit submit when text is empty', async () => {
    const w = mount(SftCorrectionArea)
    await w.find('textarea').trigger('keydown', { key: 'Enter', ctrlKey: true })
    expect(w.emitted('submit')).toBeFalsy()
  })
})
