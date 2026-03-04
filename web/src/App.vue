<template>
  <div id="app" :class="{ 'rich-motion': motion.rich.value }">
    <LabelView />
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useMotion } from './composables/useMotion'
import { useHackerMode } from './composables/useEasterEgg'
import LabelView from './views/LabelView.vue'

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
  min-height: 100dvh;
}
</style>
