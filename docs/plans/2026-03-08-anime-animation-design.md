# Anime.js Animation Integration — Design

**Date:** 2026-03-08
**Status:** Approved
**Branch:** feat/vue-label-tab

## Problem

The current animation system mixes CSS keyframes, CSS transitions, and imperative inline-style bindings across three files. The seams between systems produce:

- Abrupt ball pickup (instant scale/borderRadius jump)
- No spring snap-back on release to no target
- Rigid CSS dismissals with no timing control
- Bucket grid and badge pop on basic `@keyframes`

## Decision

Integrate **Anime.js v4** as a single animation layer. Vue reactive state is unchanged; Anime.js owns all DOM motion imperatively.

## Architecture

One new composable, minimal changes to two existing files, CSS cleanup in two files.

```
web/src/composables/useCardAnimation.ts   ← NEW
web/src/components/EmailCardStack.vue     ← modify
web/src/views/LabelView.vue              ← modify
```

**Data flow:**
```
pointer events → Vue refs (isHeld, deltaX, deltaY, dismissType)
                     ↓  watched by
             useCardAnimation(cardEl, stackEl, isHeld, ...)
                     ↓  imperatively drives
                Anime.js → DOM transforms
```

`useCardAnimation` is a pure side-effect composable — returns nothing to the template. The `cardStyle` computed in `EmailCardStack.vue` is removed; Anime.js owns the element's transform directly.

## Animation Surfaces

### Pickup morph
```
animate(cardEl, { scale: 0.55, borderRadius: '50%', y: -80 }, { duration: 200, ease: spring(1, 80, 10) })
```
Replaces the instant CSS transform jump on `onPointerDown`.

### Drag tracking
Raw `cardEl.style.translate` update on `onPointerMove` — no animation, just position. Easing only at boundaries (pickup / release), not during active drag.

### Snap-back
```
animate(cardEl, { x: 0, y: 0, scale: 1, borderRadius: '1rem' }, { ease: spring(1, 80, 10) })
```
Fires on `onPointerUp` when no zone/bucket target was hit.

### Dismissals (replace CSS `@keyframes`)
- **fileAway** — `animate(cardEl, { y: '-120%', scale: 0.85, opacity: 0 }, { duration: 280, ease: 'out(3)' })`
- **crumple** — 2-step timeline: shrink + redden → `scale(0)` + rotate
- **slideUnder** — `animate(cardEl, { x: '110%', rotate: 5, opacity: 0 }, { duration: 260 })`

### Bucket grid rise
`animate(gridEl, { y: -8, opacity: 0.45 })` on `isHeld` → true; reversed on false. Spring easing.

### Badge pop
`animate(badgeEl, { scale: [0.6, 1], opacity: [0, 1] }, { ease: spring(1.5, 80, 8), duration: 300 })` triggered on badge mount via Vue's `onMounted` lifecycle hook in a `BadgePop` wrapper component or `v-enter-active` transition hook.

## Constraints

### Reduced motion
`useCardAnimation` checks `motion.rich.value` before firing any Anime.js call. If false, all animations are skipped — instant state changes only. Consistent with existing `useMotion` pattern.

### Bundle size
Anime.js v4 core ~17KB gzipped. Only `animate`, `spring`, and `createTimeline` are imported — Vite ESM tree-shaking keeps footprint minimal. The `draggable` module is not used.

### Tests
Existing `EmailCardStack.test.ts` tests emit behavior, not animation — they remain passing. Anime.js mocked at module level in Vitest via `vi.mock('animejs')` where needed.

### CSS cleanup
Remove from `EmailCardStack.vue` and `LabelView.vue`:
- `@keyframes fileAway`, `crumple`, `slideUnder`
- `@keyframes badge-pop`
- `.dismiss-label`, `.dismiss-skip`, `.dismiss-discard` classes (Anime.js fires on element refs directly)
- The `dismissClass` computed in `EmailCardStack.vue`

## Files Changed

| File | Change |
|------|--------|
| `web/package.json` | Add `animejs` dependency |
| `web/src/composables/useCardAnimation.ts` | New — all Anime.js animation logic |
| `web/src/components/EmailCardStack.vue` | Remove `cardStyle` computed + dismiss classes; call `useCardAnimation` |
| `web/src/views/LabelView.vue` | Badge pop + bucket grid rise via Anime.js |
| `web/src/assets/avocet.css` | Remove any global animation keyframes if present |
