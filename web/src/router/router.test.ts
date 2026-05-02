import { describe, it, expect } from 'vitest'
import { createRouter, createWebHashHistory } from 'vue-router'

// Import the raw routes array so we can test structure without mounting App
import { routes } from './index'

describe('router routes', () => {
  it('exports a routes array', () => {
    expect(Array.isArray(routes)).toBe(true)
  })

  it('has / pointing to DashboardView', () => {
    const root = routes.find(r => r.path === '/')
    expect(root).toBeDefined()
    // Component should be async (lazy) or have a name
    expect(root?.component).toBeDefined()
  })

  it('has /fleet route', () => {
    const r = routes.find(r => r.path === '/fleet')
    expect(r).toBeDefined()
  })

  it('has /data/label route', () => {
    const r = routes.find(r => r.path === '/data/label')
    expect(r).toBeDefined()
  })

  it('has /data/fetch route', () => {
    const r = routes.find(r => r.path === '/data/fetch')
    expect(r).toBeDefined()
  })

  it('has /data/corrections route', () => {
    const r = routes.find(r => r.path === '/data/corrections')
    expect(r).toBeDefined()
  })

  it('has /data/imitate route', () => {
    const r = routes.find(r => r.path === '/data/imitate')
    expect(r).toBeDefined()
  })

  it('has /eval/benchmark route', () => {
    const r = routes.find(r => r.path === '/eval/benchmark')
    expect(r).toBeDefined()
  })

  it('has /eval/compare route', () => {
    const r = routes.find(r => r.path === '/eval/compare')
    expect(r).toBeDefined()
  })

  it('has /train/jobs route', () => {
    const r = routes.find(r => r.path === '/train/jobs')
    expect(r).toBeDefined()
  })

  it('has /train/results route', () => {
    const r = routes.find(r => r.path === '/train/results')
    expect(r).toBeDefined()
  })

  it('has /settings route', () => {
    const r = routes.find(r => r.path === '/settings')
    expect(r).toBeDefined()
  })

  it('has backward-compat redirect from /benchmark to /eval/benchmark', () => {
    const r = routes.find(r => r.path === '/benchmark')
    expect(r).toBeDefined()
    expect((r as { redirect?: string }).redirect).toBe('/eval/benchmark')
  })

  it('has backward-compat redirect from /models to /fleet', () => {
    const r = routes.find(r => r.path === '/models')
    expect(r).toBeDefined()
    expect((r as { redirect?: string }).redirect).toBe('/fleet')
  })

  it('has backward-compat redirect from /stats to /', () => {
    const r = routes.find(r => r.path === '/stats')
    expect(r).toBeDefined()
    expect((r as { redirect?: string }).redirect).toBe('/')
  })

  it('can create a functional router instance', () => {
    const router = createRouter({
      history: createWebHashHistory(),
      routes,
    })
    expect(router).toBeDefined()
  })
})
