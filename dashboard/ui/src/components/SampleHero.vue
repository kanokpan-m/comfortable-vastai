<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { isVideo, caption, useSamples } from '../lib/media'
import MediaView from './MediaView.vue'
import MediaPoster from './MediaPoster.vue'
import PackAvatar from './PackAvatar.vue'

// A starter's samples, rotating while the card is on screen, with its models as circles
// (the circle of the model the current sample comes from is ringed; click one to see its sample).
// Samples that don't load drop out; with none left, images people made with its models take over,
// and the poster underneath is what shows when nothing loads at all.
const props = defineProps({
  samples: { type: Array, default: () => [] },
  models: { type: Array, default: () => [] },
  mature: Boolean,
  icon: { type: [Object, Function], default: null },
  seed: { type: String, default: '' },
  maxModels: { type: Number, default: 5 },
})
const emit = defineEmits(['open'])
const { list, fail } = useSamples(() => props.samples, () => props.models, () => props.mature)
const i = ref(0)
const cur = computed(() => list.value[i.value] || list.value[0] || null)
const root = ref(null)
const visible = ref(false)
const hovered = ref(false)
const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
watch(() => props.samples.map((m) => m.url).join(), () => { i.value = 0 })
watch(() => list.value.length, (n) => { if (i.value >= n) i.value = 0 })

const next = () => { if (list.value.length > 1) i.value = (i.value + 1) % list.value.length }
// Stills change every 5 s; a video plays to its end first (at most 15 s). Paused while pointed at.
let timer
function schedule() {
  clearTimeout(timer)
  if (!visible.value || hovered.value || reduced || list.value.length < 2) return
  timer = setTimeout(next, isVideo(cur.value) ? 15000 : 5000)
}
watch([i, visible, hovered, () => list.value.length], schedule)
let io
onMounted(() => {
  if (typeof IntersectionObserver !== 'function') { visible.value = true; return }
  io = new IntersectionObserver(([e]) => { visible.value = e.isIntersecting }, { threshold: 0.4 })
  if (root.value) io.observe(root.value)
})
onBeforeUnmount(() => { io?.disconnect(); clearTimeout(timer) })

function showModel(p) {
  const k = list.value.findIndex((m) => m.pack_id === p.id)
  if (k >= 0) i.value = k
  else emit('open')
}
const shown = computed(() => props.models.slice(0, props.maxModels))
</script>

<template>
  <div ref="root" class="relative aspect-[16/10] overflow-hidden bg-card" @pointerenter="hovered = true" @pointerleave="hovered = false">
    <button type="button" class="absolute inset-0 block size-full" :aria-label="cur ? `Sample from ${cur.pack_title}: open details` : 'Open details'" @click="emit('open')">
      <MediaView :item="cur" fit="contain" :width="640" :loop="list.length < 2" class="size-full" :alt="cur ? `Sample from ${cur.pack_title}` : ''" @ended="next" @error="fail(cur)">
        <template #placeholder><MediaPoster :seed="seed" :icon="icon" /></template>
      </MediaView>
    </button>
    <slot />
    <div class="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between gap-2 bg-gradient-to-t from-black/75 via-black/35 to-transparent px-2.5 pb-2 pt-12">
      <div class="pointer-events-auto flex min-w-0 items-center">
        <div class="flex items-center -space-x-2">
          <button v-for="p in shown" :key="p.id" type="button" :title="p.title" :aria-label="`${p.title}: show its sample`"
                  class="relative rounded-full transition-transform hover:z-10 hover:scale-110 focus-visible:z-10" @click="showModel(p)">
            <PackAvatar :pack="p" :mature="mature" :active="cur?.pack_id === p.id" size="size-9" />
          </button>
          <span v-if="models.length > maxModels" class="relative flex size-9 items-center justify-center rounded-full bg-black/70 text-[11px] font-medium text-white ring-2 ring-panel">+{{ models.length - maxModels }}</span>
        </div>
        <span v-if="cur" class="ml-2 hidden min-w-0 truncate text-[11px] text-white/85 sm:block">{{ caption(cur) }}</span>
      </div>
      <div v-if="list.length > 1" class="pointer-events-auto flex shrink-0 items-center" role="tablist" aria-label="Samples">
        <button v-for="(m, k) in list.slice(0, 10)" :key="m.url" type="button" role="tab" :aria-selected="m === cur" :aria-label="`Sample ${k + 1} of ${list.length}`"
                class="flex size-4 items-center justify-center" @click="i = k">
          <span class="block size-1.5 rounded-full transition-colors" :class="m === cur ? 'bg-white' : 'bg-white/45'" />
        </button>
      </div>
    </div>
  </div>
</template>
