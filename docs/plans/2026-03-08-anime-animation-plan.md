# Anime.js Animation Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the current mixed CSS keyframes / inline-style animation system with Anime.js v4 for all card motion — pickup morph, drag tracking, spring snap-back, dismissals, bucket grid rise, and badge pop.

**Architecture:** A new `useCardAnimation` composable owns all Anime.js calls imperatively against DOM refs. Vue reactive state (`isHeld`, `deltaX`, `deltaY`, `dismissType`) is unchanged. `cardStyle` computed and `dismissClass` computed are deleted; Anime.js writes to the element directly.

**Tech Stack:** Anime.js v4 (`animejs`), Vue 3 Composition API, `@vue/test-utils` + Vitest for tests.

---

## Task 1: Install Anime.js

**Files:**
- Modify: `web/package.json`

**Step 1: Install the package**

```bash
cd /Library/Development/CircuitForge/avocet/web
npm install animejs
```

**Step 2: Verify the import resolves**

Create a throwaway check — open `web/src/main.ts` briefly and confirm:
```ts
import { animate, spring } from 'animejs'
```
resolves without error in the editor (TypeScript types ship with animejs v4).
Remove the import immediately after verifying — do not commit it.

**Step 3: Commit**

```bash
cd /Library/Development/CircuitForge/avocet/web
git add package.json package-lock.json
git commit -m "feat(avocet): add animejs v4 dependency"
```

---

## Task 2: Create `useCardAnimation` composable

**Files:**
- Create: `web/src/composables/useCardAnimation.ts`
- Create: `web/src/composables/useCardAnimation.test.ts`

**Background — Anime.js v4 transform model:**
Anime.js v4 tracks `x`, `y`, `scale`, `rotate`, etc. as separate transform components internally.
Use `utils.set(el, props)` for instant (no-animation) property updates — this keeps the internal cache consistent.
Never mix direct `el.style.transform = "..."` with Anime.js on the same element, or the cache desyncs.

**Step 1: Write the failing tests**

`web/src/composables/useCardAnimation.test.ts`:
```ts
import { ref, nextTick } from 'vue'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock animejs before importing the composable
vi.mock('animejs', () => ({
  animate: vi.fn(),
  spring:  vi.fn(() => 'mock-spring'),
  utils:   { set: vi.fn() },
}))

import { useCardAnimation } from './useCardAnimation'
import { animate, utils } from 'animejs'

const mockAnimate = animate as ReturnType<typeof vi.fn>
const mockSet     = utils.set as ReturnType<typeof vi.fn>

function makeEl() {
  return document.createElement('div')
}

describe('useCardAnimation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('pickup() calls animate with ball shape', () => {
    const el = makeEl()
    const cardEl = ref<HTMLElement | null>(el)
    const motion = { rich: ref(true) }
    const { pickup } = useCardAnimation(cardEl, motion)
    pickup()
    expect(mockAnimate).toHaveBeenCalledWith(
      el,
      expect.objectContaining({ scale: 0.55, borderRadius: '50%' }),
      expect.anything(),
    )
  })

  it('pickup() is a no-op when motion.rich is false', () => {
    const el = makeEl()
    const cardEl = ref<HTMLElement | null>(el)
    const motion = { rich: ref(false) }
    const { pickup } = useCardAnimation(cardEl, motion)
    pickup()
    expect(mockAnimate).not.toHaveBeenCalled()
  })

  it('setDragPosition() calls utils.set with translated coords', () => {
    const el = makeEl()
    const cardEl = ref<HTMLElement | null>(el)
    const motion = { rich: ref(true) }
    const { setDragPosition } = useCardAnimation(cardEl, motion)
    setDragPosition(50, 30)
    expect(mockSet).toHaveBeenCalledWith(el, expect.objectContaining({ x: 50, y: -50 }))
    // y = deltaY - 80 = 30 - 80 = -50
  })

  it('snapBack() calls animate returning to card shape', () => {
    const el = makeEl()
    const cardEl = ref<HTMLElement | null>(el)
    const motion = { rich: ref(true) }
    const { snapBack } = useCardAnimation(cardEl, motion)
    snapBack()
    expect(mockAnimate).toHaveBeenCalledWith(
      el,
      expect.objectContaining({ x: 0, y: 0, scale: 1 }),
      expect.anything(),
    )
  })

  it('animateDismiss("label") calls animate', () => {
    const el = makeEl()
    const cardEl = ref<HTMLElement | null>(el)
    const motion = { rich: ref(true) }
    const { animateDismiss } = useCardAnimation(cardEl, motion)
    animateDismiss('label')
    expect(mockAnimate).toHaveBeenCalled()
  })

  it('animateDismiss("discard") calls animate', () => {
    const el = makeEl()
    const cardEl = ref<HTMLElement | null>(el)
    const motion = { rich: ref(true) }
    const { animateDismiss } = useCardAnimation(cardEl, motion)
    animateDismiss('discard')
    expect(mockAnimate).toHaveBeenCalled()
  })

  it('animateDismiss("skip") calls animate', () => {
    const el = makeEl()
    const cardEl = ref<HTMLElement | null>(el)
    const motion = { rich: ref(true) }
    const { animateDismiss } = useCardAnimation(cardEl, motion)
    animateDismiss('skip')
    expect(mockAnimate).toHaveBeenCalled()
  })

  it('animateDismiss is a no-op when motion.rich is false', () => {
    const el = makeEl()
    const cardEl = ref<HTMLElement | null>(el)
    const motion = { rich: ref(false) }
    const { animateDismiss } = useCardAnimation(cardEl, motion)
    animateDismiss('label')
    expect(mockAnimate).not.toHaveBeenCalled()
  })
})
```

**Step 2: Run tests to confirm they fail**

```bash
cd /Library/Development/CircuitForge/avocet/web
npm test -- useCardAnimation
```

Expected: FAIL — "Cannot find module './useCardAnimation'"

**Step 3: Implement the composable**

`web/src/composables/useCardAnimation.ts`:
```ts
import { type Ref } from 'vue'
import { animate, spring, utils } from 'animejs'

const BALL_SCALE        = 0.55
const BALL_RADIUS       = '50%'
const CARD_RADIUS       = '1rem'
const PICKUP_Y_OFFSET   = 80      // px above finger
const PICKUP_DURATION   = 200
// NOTE: animejs v4 — spring() takes an object, not positional args
const SNAP_SPRING       = spring({ mass: 1, stiffness: 80, damping: 10 })

interface Motion { rich: Ref<boolean> }

export function useCardAnimation(
  cardEl: Ref<HTMLElement | null>,
  motion: Motion,
) {
  function pickup() {
    if (!motion.rich.value || !cardEl.value) return
    // NOTE: animejs v4 — animate() is 2-arg; timing options merge into the params object
    animate(cardEl.value, {
      scale:        BALL_SCALE,
      borderRadius: BALL_RADIUS,
      y:            -PICKUP_Y_OFFSET,
      duration:     PICKUP_DURATION,
      ease:         SNAP_SPRING,
    })
  }

  function setDragPosition(dx: number, dy: number) {
    if (!cardEl.value) return
    utils.set(cardEl.value, { x: dx, y: dy - PICKUP_Y_OFFSET })
  }

  function snapBack() {
    if (!motion.rich.value || !cardEl.value) return
    // No duration — spring physics determines settling time
    animate(cardEl.value, {
      x:            0,
      y:            0,
      scale:        1,
      borderRadius: CARD_RADIUS,
      ease:         SNAP_SPRING,
    })
  }

  function animateDismiss(type: 'label' | 'skip' | 'discard') {
    if (!motion.rich.value || !cardEl.value) return
    const el = cardEl.value
    if (type === 'label') {
      animate(el, { y: '-120%', scale: 0.85, opacity: 0, duration: 280, ease: 'out(3)' })
    } else if (type === 'discard') {
      // Two-step: crumple then shrink (keyframes array in params object)
      animate(el, { keyframes: [
        { scale: 0.95, rotate: 2,  filter: 'brightness(0.6) sepia(1) hue-rotate(-20deg)', duration: 140 },
        { scale: 0,    rotate: 8,  opacity: 0,                                             duration: 210 },
      ])
    } else if (type === 'skip') {
      animate(el, { x: '110%', rotate: 5, opacity: 0 }, { duration: 260, ease: 'out(2)' })
    }
  }

  return { pickup, setDragPosition, snapBack, animateDismiss }
}
```

**Step 4: Run tests — expect pass**

```bash
npm test -- useCardAnimation
```

Expected: All 8 tests PASS.

**Step 5: Commit**

```bash
git add web/src/composables/useCardAnimation.ts web/src/composables/useCardAnimation.test.ts
git commit -m "feat(avocet): add useCardAnimation composable with Anime.js"
```

---

## Task 3: Wire `useCardAnimation` into `EmailCardStack.vue`

**Files:**
- Modify: `web/src/components/EmailCardStack.vue`
- Modify: `web/src/components/EmailCardStack.test.ts`

**What changes:**
- Remove `cardStyle` computed and `:style="cardStyle"` binding
- Remove `dismissClass` computed and `:class="[dismissClass, ...]"` binding (keep `is-held`)
- Remove `deltaX`, `deltaY` reactive refs (position now owned by Anime.js)
- Call `pickup()` in `onPointerDown`, `setDragPosition()` in `onPointerMove`, `snapBack()` in `onPointerUp` (no-target path)
- Watch `props.dismissType` and call `animateDismiss()`
- Remove CSS `@keyframes fileAway`, `crumple`, `slideUnder` and their `.dismiss-*` rule blocks from `<style>`

**Step 1: Update the tests that check dismiss classes**

In `EmailCardStack.test.ts`, the 5 tests checking `.dismiss-label`, `.dismiss-discard`, `.dismiss-skip` classes are testing implementation (CSS class name), not behavior. Replace them with a single test that verifies `animateDismiss` is called:

```ts
// Add at the top of the file (after existing imports):
vi.mock('../composables/useCardAnimation', () => ({
  useCardAnimation: vi.fn(() => ({
    pickup:          vi.fn(),
    setDragPosition: vi.fn(),
    snapBack:        vi.fn(),
    animateDismiss:  vi.fn(),
  })),
}))

import { useCardAnimation } from '../composables/useCardAnimation'
```

Replace the five `dismissType` class tests (lines 25–46) with:

```ts
it('calls animateDismiss with type when dismissType prop changes', async () => {
  const w = mount(EmailCardStack, { props: { item, isBucketMode: false, dismissType: null } })
  const { animateDismiss } = (useCardAnimation as ReturnType<typeof vi.fn>).mock.results[0].value
  await w.setProps({ dismissType: 'label' })
  await nextTick()
  expect(animateDismiss).toHaveBeenCalledWith('label')
})
```

Add `nextTick` import to the test file header if not already present:
```ts
import { nextTick } from 'vue'
```

**Step 2: Run tests to confirm the replaced tests fail**

```bash
npm test -- EmailCardStack
```

Expected: FAIL — `animateDismiss` not called (not yet wired in component)

**Step 3: Modify `EmailCardStack.vue`**

Script section changes:

```ts
// Remove:
//   import { ref, computed } from 'vue'  →  change to:
import { ref, watch } from 'vue'

// Add import:
import { useCardAnimation } from '../composables/useCardAnimation'

// Remove these refs:
//   const deltaX = ref(0)
//   const deltaY = ref(0)

// Add after const motion = useMotion():
const { pickup, setDragPosition, snapBack, animateDismiss } = useCardAnimation(cardEl, motion)

// Add watcher:
watch(() => props.dismissType, (type) => {
  if (type) animateDismiss(type)
})

// Remove dismissClass computed entirely.

// In onPointerDown — add after isHeld.value = true:
pickup()

// In onPointerMove — replace deltaX/deltaY assignments with:
const dx = e.clientX - pickupX.value
const dy = e.clientY - pickupY.value
setDragPosition(dx, dy)
// (keep the zone/bucket detection that uses e.clientX/e.clientY — those stay the same)

// In onPointerUp — in the snap-back else branch, replace:
//   deltaX.value = 0
//   deltaY.value = 0
// with:
snapBack()
```

Template changes — on the `.card-wrapper` div:
```html
<!-- Remove: :class="[dismissClass, { 'is-held': isHeld }]" -->
<!-- Replace with: -->
:class="{ 'is-held': isHeld }"
<!-- Remove: :style="cardStyle" -->
```

CSS changes in `<style scoped>` — delete these entire blocks:
```
@keyframes fileAway { ... }
@keyframes crumple { ... }
@keyframes slideUnder { ... }
.card-wrapper.dismiss-label { ... }
.card-wrapper.dismiss-discard { ... }
.card-wrapper.dismiss-skip { ... }
```

Also delete `--card-dismiss` and `--card-skip` CSS var usages if present.

**Step 4: Run all tests**

```bash
npm test
```

Expected: All pass (both `useCardAnimation.test.ts` and `EmailCardStack.test.ts`).

**Step 5: Commit**

```bash
git add web/src/components/EmailCardStack.vue web/src/components/EmailCardStack.test.ts
git commit -m "feat(avocet): wire Anime.js card animation into EmailCardStack"
```

---

## Task 4: Bucket grid rise animation

**Files:**
- Modify: `web/src/views/LabelView.vue`

**What changes:**
Replace the CSS class-toggle animation on `.bucket-grid-footer.grid-active` with an Anime.js watch in `LabelView.vue`. The `position: sticky → fixed` switch stays as a CSS class (can't animate position), but `translateY` and `opacity` move to Anime.js.

**Step 1: Add gridEl ref and import animate**

In `LabelView.vue` `<script setup>`:
```ts
// Add to imports:
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { animate, spring } from 'animejs'

// Add ref:
const gridEl = ref<HTMLElement | null>(null)
```

**Step 2: Add watcher for isHeld**

```ts
watch(isHeld, (held) => {
  if (!motion.rich.value || !gridEl.value) return
  // animejs v4: 2-arg animate, spring() takes object
  animate(gridEl.value,
    held
      ? { y: -8, opacity: 0.45, ease: spring({ mass: 1, stiffness: 80, damping: 10 }), duration: 250 }
      : { y:  0, opacity: 1,    ease: spring({ mass: 1, stiffness: 80, damping: 10 }), duration: 250 }
  )
})
```

**Step 3: Wire ref in template**

On the `.bucket-grid-footer` div:
```html
<div ref="gridEl" class="bucket-grid-footer" :class="{ 'grid-active': isHeld }">
```

**Step 4: Remove CSS transition from `.bucket-grid-footer`**

In `LabelView.vue <style scoped>`, delete the `transition:` line from `.bucket-grid-footer`:
```css
/* DELETE this line: */
transition: transform 250ms cubic-bezier(0.34, 1.56, 0.64, 1),
            opacity 200ms ease,
            background 200ms ease;
```
Keep the `transform: translateY(-8px)` and `opacity: 0.45` on `.bucket-grid-footer.grid-active` as fallback for reduced-motion users (no-JS fallback too).

Actually — keep `.grid-active` rules as-is for the no-motion path. The Anime.js `watch` guard (`if (!motion.rich.value)`) means reduced-motion users never hit Anime.js; the CSS class handles them.

**Step 5: Run tests**

```bash
npm test
```

Expected: All pass (LabelView has no dedicated tests, but full suite should be green).

**Step 6: Commit**

```bash
git add web/src/views/LabelView.vue
git commit -m "feat(avocet): animate bucket grid rise with Anime.js spring"
```

---

## Task 5: Badge pop animation

**Files:**
- Modify: `web/src/views/LabelView.vue`

**What changes:**
Replace `@keyframes badge-pop` (scale + opacity keyframe) with a Vue `<Transition>` `@enter` hook that calls `animate()`. Badges already appear/disappear via `v-if`, so they have natural mount/unmount lifecycle.

**Step 1: Wrap each badge in a `<Transition>`**

In `LabelView.vue` template, each badge `<span v-if="...">` gets wrapped:

```html
<Transition @enter="onBadgeEnter" :css="false">
  <span v-if="onRoll" class="badge badge-roll">🔥 On a roll!</span>
</Transition>
<Transition @enter="onBadgeEnter" :css="false">
  <span v-if="speedRound" class="badge badge-speed">⚡ Speed round!</span>
</Transition>
<!-- repeat for all 6 badges -->
```

`:css="false"` tells Vue not to apply any CSS transition classes — Anime.js owns the enter animation entirely.

**Step 2: Add `onBadgeEnter` hook**

```ts
function onBadgeEnter(el: Element, done: () => void) {
  if (!motion.rich.value) { done(); return }
  animate(el as HTMLElement,
    { scale: [0.6, 1], opacity: [0, 1] },
    { ease: spring(1.5, 80, 8), duration: 300, onComplete: done }
  )
}
```

**Step 3: Remove `@keyframes badge-pop` from CSS**

In `LabelView.vue <style scoped>`:
```css
/* DELETE: */
@keyframes badge-pop {
  from { transform: scale(0.6); opacity: 0; }
  to   { transform: scale(1);   opacity: 1; }
}

/* DELETE animation line from .badge: */
animation: badge-pop 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
```

**Step 4: Run tests**

```bash
npm test
```

Expected: All pass.

**Step 5: Commit**

```bash
git add web/src/views/LabelView.vue
git commit -m "feat(avocet): badge pop via Anime.js spring transition hook"
```

---

## Task 6: Build and smoke test

**Step 1: Build the SPA**

```bash
cd /Library/Development/CircuitForge/avocet
./manage.sh start-api
```

(This builds Vue + starts FastAPI on port 8503.)

**Step 2: Open the app**

```bash
./manage.sh open-api
```

**Step 3: Manual smoke test checklist**

- [ ] Pick up a card — ball morph is smooth (not instant jump)
- [ ] Drag ball around — follows finger with no lag
- [ ] Release in center — springs back to card with bounce
- [ ] Release in left zone — discard fires (card crumples)
- [ ] Release in right zone — skip fires (card slides right)
- [ ] Release on a bucket — label fires (card files up)
- [ ] Fling left fast — discard fires
- [ ] Bucket grid rises smoothly on pickup, falls on release
- [ ] Badge (label 10 in a row for 🔥) pops in with spring
- [ ] Reduced motion: toggle in system settings → no animations, instant behavior
- [ ] Keyboard labels (1–9) still work (pointer events unchanged)

**Step 4: Final commit if all green**

```bash
git add -A
git commit -m "feat(avocet): complete Anime.js animation integration"
```
