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

    <!-- Nav items -->
    <ul class="nav-list" role="list">
      <li v-for="item in navItems" :key="item.path">
        <RouterLink
          :to="item.path"
          class="nav-item"
          :title="stowed ? item.label : ''"
          @click="isMobile && stow()"
        >
          <span class="nav-icon" aria-hidden="true">{{ item.icon }}</span>
          <span v-if="!stowed" class="nav-label">{{ item.label }}</span>
        </RouterLink>
      </li>
    </ul>
  </nav>

  <!-- Mobile hamburger button rendered outside the sidebar so it's visible when stowed -->
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

const navItems = [
  { path: '/',         icon: '🃏', label: 'Label'    },
  { path: '/fetch',    icon: '📥', label: 'Fetch'    },
  { path: '/stats',    icon: '📊', label: 'Stats'    },
  { path: '/settings', icon: '⚙️', label: 'Settings' },
]

const stowed    = ref(localStorage.getItem(LS_KEY) === 'true')
const winWidth  = ref(window.innerWidth)
const isMobile  = computed(() => winWidth.value < 640)

function toggle() {
  stowed.value = !stowed.value
  localStorage.setItem(LS_KEY, String(stowed.value))
  // Update CSS variable on :root so .app-main margin-left syncs
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
  // Apply persisted sidebar width to :root on mount
  document.documentElement.style.setProperty('--sidebar-width', stowed.value ? '56px' : '200px')
  // On mobile, default to stowed
  if (isMobile.value && !localStorage.getItem(LS_KEY)) {
    stowed.value = true
    document.documentElement.style.setProperty('--sidebar-width', '56px')
  }
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

.sidebar.stowed {
  width: 56px;
}

/* Mobile: slide in/out from left */
.sidebar.mobile {
  box-shadow: 2px 0 16px rgba(0, 0, 0, 0.15);
}

.sidebar.mobile.stowed {
  transform: translateX(-100%);
  width: 200px;   /* keep width so slide-in looks right */
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

.logo-icon {
  font-size: 1.25rem;
  flex-shrink: 0;
}

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

.stow-btn:hover {
  background: var(--color-border, #d0d7e8);
}

.nav-list {
  list-style: none;
  padding: 0.5rem 0;
  flex: 1;
}

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

.nav-icon {
  font-size: 1.1rem;
  flex-shrink: 0;
  width: 24px;
  text-align: center;
}

.nav-label {
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Mobile hamburger — visible when sidebar is stowed on mobile */
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
