<script setup>
import { computed } from 'vue'

// Shown under every sample while it loads, and on its own when nothing loads, so there is always
// something to look at: a gradient in the model's own colours (from its id) with its icon.
const props = defineProps({ seed: { type: String, default: '' }, icon: { type: [Object, Function], default: null }, label: { type: String, default: '' }, small: Boolean })
const hue = computed(() => {
  let h = 7
  for (const ch of props.seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return h % 360
})
const style = computed(() => ({ background: `linear-gradient(135deg, hsl(${hue.value} 42% 26%), hsl(${(hue.value + 55) % 360} 50% 13%))` }))
</script>

<template>
  <div class="absolute inset-0 flex flex-col items-center justify-center gap-2 overflow-hidden" :style="style" aria-hidden="true">
    <component :is="icon" v-if="icon" class="text-white/75" :class="small ? 'size-1/2' : 'size-9'" />
    <span v-if="label && !small" class="line-clamp-2 max-w-[80%] text-center text-[11px] font-medium leading-snug text-white/80">{{ label }}</span>
  </div>
</template>
