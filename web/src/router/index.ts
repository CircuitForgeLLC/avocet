import { createRouter, createWebHashHistory } from 'vue-router'
import LabelView    from '../views/LabelView.vue'

// Views are lazy-loaded to keep initial bundle small
const FetchView     = () => import('../views/FetchView.vue')
const StatsView     = () => import('../views/StatsView.vue')
const BenchmarkView = () => import('../views/BenchmarkView.vue')
const SettingsView    = () => import('../views/SettingsView.vue')
const CorrectionsView = () => import('../views/CorrectionsView.vue')

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/',            component: LabelView,       meta: { title: 'Label' } },
    { path: '/fetch',       component: FetchView,       meta: { title: 'Fetch' } },
    { path: '/stats',       component: StatsView,       meta: { title: 'Stats' } },
    { path: '/benchmark',   component: BenchmarkView,   meta: { title: 'Benchmark' } },
    { path: '/corrections', component: CorrectionsView, meta: { title: 'Corrections' } },
    { path: '/settings',    component: SettingsView,    meta: { title: 'Settings' } },
  ],
})
