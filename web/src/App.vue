<template>
  <div id="app" :class="{ 'rich-motion': motion.rich.value }">
    <AppSidebar />
    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterView } from 'vue-router'
import { useMotion } from './composables/useMotion'
import { useHackerMode } from './composables/useEasterEgg'
import AppSidebar from './components/AppSidebar.vue'

const motion = useMotion()
const { restore } = useHackerMode()

onMounted(() => {
  restore()  // re-apply hacker mode from localStorage on page load
})
</script>

<style>
/* Global reset + base */
*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: var(--font-body, sans-serif);
  background: var(--color-bg, #f0f4fc);
  color: var(--color-text, #1a2338);
  min-height: 100dvh;
}

#app {
  display: flex;
  min-height: 100dvh;
  overflow-x: hidden;
}

.app-main {
  flex: 1;
  min-width: 0;  /* prevent flex blowout */
  margin-left: var(--sidebar-width, 200px);
  transition: margin-left 250ms ease;
}
</style>
