import { createRouter, createWebHashHistory } from 'vue-router'

// Lazy-loaded views
const DashboardView    = () => import('../views/DashboardView.vue')
const LabelView        = () => import('../views/LabelView.vue')
const FetchView        = () => import('../views/FetchView.vue')
const CorrectionsView  = () => import('../views/CorrectionsView.vue')
const ImitateView      = () => import('../views/ImitateView.vue')
const BenchmarkView    = () => import('../views/BenchmarkView.vue')
const CompareView      = () => import('../views/CompareView.vue')
const TrainJobsView    = () => import('../views/TrainJobsView.vue')
const TrainResultsView = () => import('../views/TrainResultsView.vue')
const ModelsView       = () => import('../views/ModelsView.vue')
const SettingsView     = () => import('../views/SettingsView.vue')
const NodeManagementView = () => import('../views/NodeManagementView.vue')

export const routes = [
  // ── Top-level ────────────────────────────────────────────
  { path: '/',         component: DashboardView, meta: { title: 'Dashboard' } },
  { path: '/fleet',    component: ModelsView,    meta: { title: 'Fleet'     } },
  { path: '/nodes',    component: NodeManagementView, meta: { title: 'Nodes' } },
  { path: '/settings', component: SettingsView,  meta: { title: 'Settings'  } },

  // ── Data domain ──────────────────────────────────────────
  { path: '/data/label',       component: LabelView,       meta: { title: 'Label'       } },
  { path: '/data/fetch',       component: FetchView,       meta: { title: 'Fetch'       } },
  { path: '/data/corrections', component: CorrectionsView, meta: { title: 'Corrections' } },
  { path: '/data/imitate',     component: ImitateView,     meta: { title: 'Imitate'     } },

  // ── Eval domain ──────────────────────────────────────────
  { path: '/eval/benchmark', component: BenchmarkView, meta: { title: 'Benchmark' } },
  { path: '/eval/compare',   component: CompareView,   meta: { title: 'Compare'   } },
  { path: '/eval/embed-compare', component: () => import('../views/EmbedCompareView.vue'), meta: { title: 'Embed Compare' } },

  // ── Train domain ─────────────────────────────────────────
  { path: '/train/jobs',    component: TrainJobsView,    meta: { title: 'Training Jobs'    } },
  { path: '/train/results', component: TrainResultsView, meta: { title: 'Training Results' } },

  // ── Backward-compat redirects ────────────────────────────
  { path: '/benchmark',   redirect: '/eval/benchmark'   },
  { path: '/models',      redirect: '/fleet'            },
  { path: '/stats',       redirect: '/'                 },
  { path: '/label',       redirect: '/data/label'       },
  { path: '/fetch',       redirect: '/data/fetch'       },
  { path: '/corrections', redirect: '/data/corrections' },
  { path: '/imitate',     redirect: '/data/imitate'     },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})
