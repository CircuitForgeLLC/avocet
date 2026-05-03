<template>
  <div class="bench-view">
    <header class="bench-header">
      <h1 class="page-title">🏁 Benchmark</h1>
    </header>

    <!-- Mode toggle -->
    <div class="mode-toggle" role="group" aria-label="Benchmark mode">
      <button
        class="mode-btn"
        :class="{ active: benchMode === 'classifier' }"
        @click="benchMode = 'classifier'"
      >Classifier</button>
      <button
        class="mode-btn"
        :class="{ active: benchMode === 'llm' }"
        @click="benchMode = 'llm'"
      >🤖 LLM Eval</button>
      <button
        class="mode-btn"
        :class="{ active: benchMode === 'style' }"
        @click="benchMode = 'style'"
      >✍️ Writing Style</button>
      <button
        class="mode-btn"
        :class="{ active: benchMode === 'plans' }"
        @click="benchMode = 'plans'"
      >📐 Planning</button>
    </div>

    <ClassifierTab  v-if="benchMode === 'classifier'" />
    <LlmEvalTab     v-if="benchMode === 'llm'" />
    <StyleTab       v-if="benchMode === 'style'" />
    <PlansBenchTab  v-if="benchMode === 'plans'" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import ClassifierTab  from './ClassifierTab.vue'
import LlmEvalTab     from './LlmEvalTab.vue'
import StyleTab       from './StyleTab.vue'
import PlansBenchTab  from './PlansBenchTab.vue'

type BenchMode = 'classifier' | 'llm' | 'style' | 'plans'
const benchMode = ref<BenchMode>('classifier')
</script>

<style scoped>
.bench-view {
  max-width: 860px;
  margin: 0 auto;
  padding: 1.5rem 1rem 4rem;
  display: flex;
  flex-direction: column;
  gap: 1.75rem;
}

.bench-header {
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

/* ── Mode toggle (segmented control) ── */
.mode-toggle {
  display: inline-flex;
  border: 1px solid var(--color-border, #d0d7e8);
  border-radius: 0.5rem;
  overflow: hidden;
  align-self: flex-start;
}

.mode-btn {
  padding: 0.4rem 1.1rem;
  font-size: 0.85rem;
  font-family: var(--font-body, sans-serif);
  font-weight: 500;
  border: none;
  background: var(--color-surface, #fff);
  color: var(--color-text-secondary, #6b7a99);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.mode-btn:not(:last-child) {
  border-right: 1px solid var(--color-border, #d0d7e8);
}

.mode-btn.active {
  background: var(--app-primary, #2A6080);
  color: #fff;
}

.mode-btn:not(.active):hover {
  background: var(--color-surface-raised, #e4ebf5);
}

@media (max-width: 600px) {
  .mode-btn { padding: 0.4rem 0.65rem; font-size: 0.78rem; }
}
</style>
