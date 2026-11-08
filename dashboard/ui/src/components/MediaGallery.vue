<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Play, ChevronLeft, ChevronRight } from '@lucide/vue'
import { sized, isVideo, caption, useSamples, noteLoad, stallFor } from '../lib/media'
import MediaView from './MediaView.vue'
import MediaPoster from './MediaPoster.vue'

// Samples in a details panel: a big player (videos play with controls, so H3 audio can be turned on)
// and a strip to pick another one. Samples that don't load leave the strip; with none left, images
// people made with these models are fetched; with none of those either, the poster stays.
const props = defineProps({
  items: { type: Array, default: () => [] },
  packs: { type: Array, default: () => [] },
  mature: Boolean,
  icon: { type: [Object, Function], default: null },
  seed: { type: String, default: '' },
  label: { type: String, default: '' },
  eager: Boolean,   // add the models' Civitai galleries and generations right away, not only as a fallback
})
const { list, fail } = useSamples(() => props.items, () => props.packs, () => props.mature, { eager: () => props.eager })
// The shown sample is kept by URL, so one leaving the strip doesn't swap the picture being looked at.
const sel = ref('')
watch(() => props.items.map((m) => m.url).join(), () => { sel.value = '' })
const i = computed(() => Math.max(0, list.value.findIndex((m) => m.url === sel.value)))
const cur = computed(() => list.value[i.value] || null)
const step = (d) => { const n = list.value.length; if (n) sel.value = list.value[(i.value + d + n) % n].url }

// The strip's small pictures load at once; any still hanging after a while counts as failed, all
// together, so a dead host is noticed in one go rather than sample by sample.
const thumbs = new Map()
const thumbRef = (url) => (el) => { if (el) thumbs.set(url, el); else thumbs.delete(url) }
let stripTimer
watch(() => list.value.map((m) => m.url).join(), () => {
  clearTimeout(stripTimer)
  if (!list.value.length) return
  stripTimer = setTimeout(() => {
    for (const m of [...list.value]) {
      const el = thumbs.get(m.url)
      if (el && !el.complete) { noteLoad(el.src, false); fail(m) }
    }
  }, stallFor(sized(list.value[0], { width: 160, still: true })))
}, { immediate: true })
onBeforeUnmount(() => clearTimeout(stripTimer))
</script>

<template>
  <section aria-label="Samples" class="space-y-2">
    <div class="relative">
      <MediaView :item="cur" fit="contain" :width="960" :controls="isVideo(cur)" class="aspect-[16/10] w-full rounded-lg" :alt="cur ? `Sample from ${cur.pack_title}` : ''" @error="fail(cur)">
        <template #placeholder><MediaPoster :seed="seed" :icon="icon" :label="cur ? '' : label" /></template>
      </MediaView>
      <template v-if="list.length > 1">
        <button type="button" class="absolute left-2 top-1/2 -translate-y-1/2 rounded-full bg-black/55 p-1.5 text-white hover:bg-black/75" aria-label="Previous sample" @click="step(-1)"><ChevronLeft class="size-4" /></button>
        <button type="button" class="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-black/55 p-1.5 text-white hover:bg-black/75" aria-label="Next sample" @click="step(1)"><ChevronRight class="size-4" /></button>
      </template>
    </div>
    <p v-if="cur" class="flex justify-between gap-2 text-[11px] text-muted">
      <span class="truncate">Sample from {{ caption(cur) }}</span>
      <span class="shrink-0 tabular">{{ i + 1 }} / {{ list.length }}</span>
    </p>
    <div v-if="list.length > 1" class="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
      <button v-for="(m, k) in list" :key="m.url" type="button" :aria-label="`Sample ${k + 1}: ${m.pack_title}`" :aria-pressed="k === i"
              class="relative size-14 shrink-0 overflow-hidden rounded-md ring-2 transition-opacity" :class="k === i ? 'ring-primary-hover' : 'opacity-75 ring-transparent hover:opacity-100'" @click="sel = m.url">
        <MediaPoster :seed="m.pack_id || seed" :icon="icon" small />
        <img :ref="thumbRef(m.url)" :src="sized(m, { width: 160, still: true })" alt="" decoding="async" referrerpolicy="no-referrer" class="absolute inset-0 size-full object-cover"
             @load="noteLoad($event.target.src, true)" @error="noteLoad($event.target.src, false); fail(m)" />
        <span v-if="isVideo(m)" class="absolute bottom-0.5 right-0.5 flex size-4 items-center justify-center rounded-full bg-black/65 text-white"><Play class="size-2.5" /></span>
      </button>
    </div>
  </section>
</template>
