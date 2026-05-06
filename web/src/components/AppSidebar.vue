<template>
  <!-- Mobile backdrop scrim -->
  <div
    v-if="isMobile && !stowed"
    class="sidebar-scrim"
    aria-hidden="true"
    @click="stow()"
  />

  <nav
    class="sidebar"
    :class="{ stowed, mobile: isMobile }"
    :style="{ '--sidebar-w': stowed ? '56px' : '200px' }"
    aria-label="App navigation"
  >
    <!-- Logo + stow toggle -->
    <div class="sidebar-header">
      <span v-if="!stowed" class="sidebar-logo">
        <span class="logo-icon">🐦</span>
        <span class="logo-name">Avocet</span>
      </span>
      <button
        class="stow-btn"
        :aria-label="stowed ? 'Expand navigation' : 'Collapse navigation'"
        @click="toggle()"
      >
        {{ stowed ? '›' : '‹' }}
      </button>
    </div>

    <!-- Nav -->
    <ul class="nav-list" role="list">
      <!-- Top-level links -->
      <li>
        <RouterLink
          to="/"
          class="nav-item"
          :title="stowed ? 'Dashboard' : ''"
          @click="isMobile && stow()"
        >
          <span class="nav-icon" aria-hidden="true">📊</span>
          <span v-if="!stowed" class="nav-label">Dashboard</span>
        </RouterLink>
      </li>
      <li>
        <RouterLink
          to="/fleet"
          class="nav-item"
          :title="stowed ? 'Fleet' : ''"
          @click="isMobile && stow()"
        >
          <span class="nav-icon" aria-hidden="true">⚡</span>
          <span v-if="!stowed" class="nav-label">Fleet</span>
        </RouterLink>
      </li>
      <li>
        <RouterLink
          to="/nodes"
          class="nav-item"
          :title="stowed ? 'Nodes' : ''"
          @click="isMobile && stow()"
        >
          <span class="nav-icon" aria-hidden="true">🖥️</span>
          <span v-if="!stowed" class="nav-label">Nodes</span>
        </RouterLink>
      </li>

      <!-- ① Data section -->
      <li>
        <div class="section-header" data-section="data" aria-hidden="true">
          <template v-if="!stowed">
            <span class="section-label">① Data</span>
            <span
              v-if="signals.data_to_eval"
              class="signal-badge"
              title="Enough new labels to run eval"
              aria-label="Eval recommended"
            />
          </template>
          <template v-else>
            <span class="section-icon">①</span>
            <span
              v-if="signals.data_to_eval"
              class="signal-badge signal-badge-stowed"
              title="Eval recommended"
              aria-label="Eval recommended"
            />
          </template>
        </div>
      </li>
      <li v-for="item in dataItems" :key="item.path">
        <RouterLink
          :to="item.path"
          class="nav-item nav-subitem"
          :title="stowed ? item.label : ''"
          @click="isMobile && stow()"
        >
          <span class="nav-icon" aria-hidden="true">{{ item.icon }}</span>
          <span v-if="!stowed" class="nav-label">{{ item.label }}</span>
        </RouterLink>
      </li>

      <!-- ② Eval section -->
      <li>
        <div class="section-header" data-section="eval" aria-hidden="true">
          <template v-if="!stowed">
            <span class="section-label">② Eval</span>
            <span
              v-if="signals.eval_to_train"
              class="signal-badge"
              title="Strong eval result — consider finetuning"
              aria-label="Finetune recommended"
            />
          </template>
          <template v-else>
            <span class="section-icon">②</span>
            <span
              v-if="signals.eval_to_train"
              class="signal-badge signal-badge-stowed"
              title="Finetune recommended"
              aria-label="Finetune recommended"
            />
          </template>
        </div>
      </li>
      <li v-for="item in evalItems" :key="item.path">
        <RouterLink
          :to="item.path"
          class="nav-item nav-subitem"
          :title="stowed ? item.label : ''"
          @click="isMobile && stow()"
        >
          <span class="nav-icon" aria-hidden="true">{{ item.icon }}</span>
          <span v-if="!stowed" class="nav-label">{{ item.label }}</span>
        </RouterLink>
      </li>

      <!-- ③ Train section -->
      <li>
        <div class="section-header" data-section="train" aria-hidden="true">
          <template v-if="!stowed">
            <span class="section-label">③ Train</span>
            <span
              v-if="signals.train_to_fleet"
              class="signal-badge"
              title="Trained model ready for fleet registration"
              aria-label="Fleet registration recommended"
            />
          </template>
          <template v-else>
            <span class="section-icon">③</span>
            <span
              v-if="signals.train_to_fleet"
              class="signal-badge signal-badge-stowed"
              title="Fleet registration recommended"
              aria-label="Fleet registration recommended"
            />
          </template>
        </div>
      </li>
      <li v-for="item in trainItems" :key="item.path">
        <RouterLink
          :to="item.path"
          class="nav-item nav-subitem"
          :title="stowed ? item.label : ''"
          @click="isMobile && stow()"
        >
          <span class="nav-icon" aria-hidden="true">{{ item.icon }}</span>
          <span v-if="!stowed" class="nav-label">{{ item.label }}</span>
        </RouterLink>
      </li>

      <!-- Divider + Settings -->
      <li class="nav-divider" aria-hidden="true" />
      <li>
        <RouterLink
          to="/settings"
          class="nav-item"
          :title="stowed ? 'Settings' : ''"
          @click="isMobile && stow()"
        >
          <span class="nav-icon" aria-hidden="true">⚙️</span>
          <span v-if="!stowed" class="nav-label">Settings</span>
        </RouterLink>
      </li>
    </ul>
  </nav>

  <!-- Mobile hamburger button — visible when sidebar is stowed on mobile -->
  <button
    v-if="isMobile && stowed"
    class="mobile-hamburger"
    aria-label="Open navigation"
    @click="toggle()"
  >
    ☰
  </button>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { RouterLink } from 'vue-router'

const LS_KEY = 'cf-avocet-nav-stowed'

interface NavItem {
  path: string
  icon: string
  label: string
}

interface DashboardSignals {
  data_to_eval: boolean
  eval_to_train: boolean
  train_to_fleet: boolean
}

const dataItems: NavItem[] = [
  { path: '/data/label',       icon: '🏷',  label: 'Label'       },
  { path: '/data/fetch',       icon: '📬',  label: 'Fetch'       },
  { path: '/data/corrections', icon: '✏️',  label: 'Corrections' },
  { path: '/data/imitate',     icon: '🪞',  label: 'Imitate'     },
]

const evalItems: NavItem[] = [
  { path: '/eval/benchmark', icon: '📊', label: 'Benchmark' },
  { path: '/eval/compare',   icon: '🔍', label: 'Compare'   },
]

const trainItems: NavItem[] = [
  { path: '/train/jobs',    icon: '🧠', label: 'Jobs'    },
  { path: '/train/results', icon: '📈', label: 'Results' },
]

const stowed   = ref(localStorage.getItem(LS_KEY) === 'true')
const winWidth = ref(window.innerWidth)
const isMobile = computed(() => winWidth.value < 640)

const signals = ref<DashboardSignals>({
  data_to_eval: false,
  eval_to_train: false,
  train_to_fleet: false,
})

async function loadSignals() {
  try {
    const res = await fetch('/api/dashboard')
    if (res.ok) {
      const data = await res.json() as { signals?: DashboardSignals }
      if (data.signals) {
        signals.value = {
          data_to_eval:   data.signals.data_to_eval   ?? false,
          eval_to_train:  data.signals.eval_to_train  ?? false,
          train_to_fleet: data.signals.train_to_fleet ?? false,
        }
      }
    }
  } catch {
    // Non-fatal: badges simply stay hidden if API is unreachable
  }
}

function toggle() {
  stowed.value = !stowed.value
  localStorage.setItem(LS_KEY, String(stowed.value))
  document.documentElement.style.setProperty('--sidebar-width', stowed.value ? '56px' : '200px')
}

function stow() {
  stowed.value = true
  localStorage.setItem(LS_KEY, 'true')
  document.documentElement.style.setProperty('--sidebar-width', '56px')
}

function onResize() { winWidth.value = window.innerWidth }

onMounted(() => {
  window.addEventListener('resize', onResize)
  document.documentElement.style.setProperty('--sidebar-width', stowed.value ? '56px' : '200px')
  if (isMobile.value && !localStorage.getItem(LS_KEY)) {
    stowed.value = true
    document.documentElement.style.setProperty('--sidebar-width', '56px')
  }
  loadSignals()
})

onUnmounted(() => window.removeEventListener('resize', onResize))
</script>

<style scoped>
.sidebar {
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  width: var(--sidebar-w, 200px);
  background: var(--color-surface-raised, #e4ebf5);
  border-right: 1px solid var(--color-border, #d0d7e8);
  display: flex;
  flex-direction: column;
  z-index: 200;
  transition: width 250ms ease;
  overflow: hidden;
}

.sidebar.stowed { width: 56px; }

.sidebar.mobile {
  box-shadow: 2px 0 16px rgba(0, 0, 0, 0.15);
}

.sidebar.mobile.stowed {
  transform: translateX(-100%);
  width: 200px;
  transition: transform 250ms ease, width 250ms ease;
}

.sidebar.mobile:not(.stowed) {
  transform: translateX(0);
  transition: transform 250ms ease;
}

.sidebar-scrim {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  z-index: 199;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 0.5rem 0.75rem 0.75rem;
  border-bottom: 1px solid var(--color-border, #d0d7e8);
  min-height: 52px;
}

.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  overflow: hidden;
  white-space: nowrap;
}

.logo-icon { font-size: 1.25rem; flex-shrink: 0; }

.logo-name {
  font-family: var(--font-display, var(--font-body, sans-serif));
  font-size: 1rem;
  font-weight: 700;
  color: var(--app-primary, #2A6080);
}

.stow-btn {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--color-text-secondary, #6b7a99);
  cursor: pointer;
  font-size: 1.1rem;
  border-radius: 0.25rem;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s;
}

.stow-btn:hover { background: var(--color-border, #d0d7e8); }

.nav-list {
  list-style: none;
  padding: 0.5rem 0;
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
}

/* ── Section headers ── */
.section-header {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.55rem 0.75rem 0.25rem;
  margin-top: 0.5rem;
  pointer-events: none;
  user-select: none;
}

.section-label {
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--color-text-muted, #4a5c7a);
  white-space: nowrap;
  flex: 1;
}

.section-icon {
  font-size: 0.75rem;
  color: var(--color-text-muted, #4a5c7a);
  width: 24px;
  text-align: center;
  flex-shrink: 0;
}

/* ── Signal badges ── */
.signal-badge {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-warning, #d4891a);
  flex-shrink: 0;
  display: inline-block;
}

.signal-badge-stowed {
  position: absolute;
  top: 4px;
  right: 4px;
}

/* Make the stowed section header container position:relative for the badge */
.sidebar.stowed .section-header {
  position: relative;
  justify-content: center;
  padding: 0.55rem 0 0.25rem;
}

/* ── Nav divider ── */
.nav-divider {
  height: 1px;
  background: var(--color-border, #d0d7e8);
  margin: 0.5rem 0.75rem;
}

/* ── Nav items ── */
.nav-item {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.65rem 0.75rem;
  color: var(--color-text, #1a2338);
  text-decoration: none;
  font-size: 0.9rem;
  white-space: nowrap;
  overflow: hidden;
  position: relative;
  transition: background 0.15s, color 0.15s;
}

.nav-item:hover {
  background: color-mix(in srgb, var(--app-primary, #2A6080) 10%, transparent);
}

.nav-item.router-link-active {
  background: color-mix(in srgb, var(--app-primary, #2A6080) 15%, transparent);
  color: var(--app-primary, #2A6080);
  font-weight: 600;
}

.nav-item.router-link-active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--app-primary, #2A6080);
  border-radius: 0 2px 2px 0;
}

/* Sub-items are indented slightly in expanded state */
.nav-subitem { padding-left: 1.1rem; font-size: 0.875rem; }

.nav-icon {
  font-size: 1.1rem;
  flex-shrink: 0;
  width: 24px;
  text-align: center;
}

.nav-label { overflow: hidden; text-overflow: ellipsis; }

/* Mobile hamburger */
.mobile-hamburger {
  position: fixed;
  top: 0.75rem;
  left: 0.75rem;
  z-index: 201;
  width: 36px;
  height: 36px;
  border: 1px solid var(--color-border, #d0d7e8);
  background: var(--color-surface-raised, #e4ebf5);
  border-radius: 0.375rem;
  cursor: pointer;
  font-size: 1rem;
  display: flex;
  align-items: center;
  justify-content: center;
}

@media (prefers-reduced-motion: reduce) {
  .sidebar,
  .sidebar.mobile,
  .sidebar.mobile.stowed {
    transition: none;
  }
}
</style>
