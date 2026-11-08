<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { packMedia, sized, useSamples, noteLoad, stallFor } from '../lib/media'
import { kindIcon } from '../lib/icons'
import MediaPoster from './MediaPoster.vue'

// A model as a circle: its first sample that loads (a video's first frame), else an image people made
// with it, else its icon on its own colours, which is also what shows while the picture loads.
const props = defineProps({ pack: { type: Object, required: true }, mature: Boolean, active: Boolean, size: { type: String, default: 'size-9' } })
const { list, fail } = useSamples(() => packMedia(props.pack, { mature: props.mature }), () => [props.pack], () => props.mature)
const media = computed(() => list.value[0] || null)
const url = computed(() => media.value && sized(media.value, { width: 128, still: true }))
const loaded = ref(false)
function onLoad() { loaded.value = true; noteLoad(url.value, true) }
function onError() {
  if (loaded.value || !media.value) return
  noteLoad(url.value, false)
  fail(media.value)
}
// Circles are small and few, so they load right away; one that hangs is given up like one that fails.
let timer
watch(url, (u) => {
  loaded.value = false
  clearTimeout(timer)
  if (u) timer = setTimeout(onError, stallFor(u))
}, { immediate: true })
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <span class="relative inline-flex shrink-0 overflow-hidden rounded-full bg-card ring-2 transition-shadow" :class="[size, active ? 'ring-primary-hover' : 'ring-panel']">
    <MediaPoster :seed="pack.id" :icon="kindIcon(pack)" small />
    <img v-if="url" :key="url" :src="url" alt="" decoding="async" referrerpolicy="no-referrer"
         class="absolute inset-0 size-full object-cover transition-opacity duration-300" :class="loaded ? 'opacity-100' : 'opacity-0'"
         @load="onLoad" @error="onError" />
  </span>
</template>
