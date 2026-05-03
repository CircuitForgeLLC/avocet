<template>
  <div class="compare-view">
    <header class="compare-header">
      <h1 class="page-title">🔍 Compare</h1>
    </header>
    <CompareTab />
  </div>
</template>

<script setup lang="ts">
import CompareTab from './CompareTab.vue'
</script>

<style scoped>
.compare-view {
  max-width: 860px;
  margin: 0 auto;
  padding: 1.5rem 1rem 4rem;
  display: flex;
  flex-direction: column;
  gap: 1.75rem;
}

.compare-header {
  display: flex;
  align-items: center;
}

.page-title {
  font-family: var(--font-display, var(--font-body, sans-serif));
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--app-primary, #2A6080);
  margin: 0;
}
</style>
