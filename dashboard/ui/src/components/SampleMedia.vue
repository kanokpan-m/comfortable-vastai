<script setup>
import { computed } from 'vue'
import { useSamples } from '../lib/media'
import MediaView from './MediaView.vue'
import MediaPoster from './MediaPoster.vue'

// The first sample that loads: the given ones in order, then images people generated with these
// packs' models, and the placeholder poster (always there underneath) when nothing loads.
const props = defineProps({
  items: { type: Array, default: () => [] },
  packs: { type: Array, default: () => [] },
  mature: Boolean,
  icon: { type: [Object, Function], default: null },
  seed: { type: String, default: '' },
  width: { type: Number, default: 450 },
  play: { type: String, default: 'visible' },
  fit: { type: String, default: 'cover' },
  alt: { type: String, default: '' },
})
const { list, fail } = useSamples(() => props.items, () => props.packs, () => props.mature)
const cur = computed(() => list.value[0] || null)
</script>

<template>
  <MediaView :item="cur" :width="width" :play="play" :fit="fit" :alt="alt" @error="fail(cur)">
    <template #placeholder><MediaPoster :seed="seed" :icon="icon" /></template>
    <slot />
  </MediaView>
</template>
