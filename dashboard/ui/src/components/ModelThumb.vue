<script setup>
import { computed, ref } from 'vue'
import { Box, Layers, Sparkles, Type, Image as ImageIcon, Wand2, Cpu, EyeOff, Package } from '@lucide/vue'
import { useApp } from '../stores/app'
import { isVideoUrl, isMature, ordered, catalogMatch, useSamples } from '../lib/media'
import MediaView from './MediaView.vue'
import MediaPoster from './MediaPoster.vue'

// The picture of any model record (library item, search result, download, Fixer candidate). Always
// shows something: its own preview, else the samples of the catalog pack for the same file, else
// (live, when those are missing or don't load) the model's Civitai gallery, videos included, and
// images people generated with it, else a poster in the model's colours with its folder's icon.
// Mature pictures are blurred unless "Show mature content" is on (or the user taps to reveal).
const props = defineProps({
  src: String,
  category: String,
  alt: { type: String, default: '' },
  mature: Boolean,
  item: { type: Object, default: null },     // where its Civitai version comes from
  play: { type: String, default: 'hover' },  // videos: 'hover', 'visible' or 'never'
  width: { type: Number, default: 450 },
  small: Boolean,
})
const app = useApp()
const allowed = computed(() => !!app.settings?.show_nsfw)
const revealed = ref(false)
const ICONS = { checkpoints: Box, diffusion_models: Cpu, loras: Layers, embeddings: Sparkles, text_encoders: Type, vae: ImageIcon, upscale_models: Wand2 }
const model = computed(() => ({
  id: props.item?.id || props.item?.url || props.src || props.alt,
  title: props.item?.name || props.alt,
  nsfw: !!(props.item?.nsfw || props.mature),
  civitai: props.item?.civitai, files: props.item?.files, url: props.item?.url, page_url: props.item?.page_url,
}))
const own = computed(() => (props.src ? [{ url: props.src, type: isVideoUrl(props.src) ? 'video' : 'image', nsfw_level: props.mature ? 4 : 1, pack_id: model.value.id, pack_title: model.value.title }] : []))
const items = computed(() => [...own.value, ...ordered(catalogMatch(props.item, app.catalog?.packs), { mature: allowed.value })])
const { list, fail } = useSamples(items, () => [model.value], allowed)
const cur = computed(() => list.value[0] || null)
const hidden = computed(() => !!cur.value && isMature(cur.value) && !allowed.value && !revealed.value)
</script>

<template>
  <MediaView :item="cur" :width="width" :play="hidden ? 'never' : play" :alt="alt" :blurred="hidden" @error="fail(cur)">
    <template #placeholder><MediaPoster :seed="String(model.id || category || '')" :icon="ICONS[category] || Package" :small="small" /></template>
    <button
      v-if="hidden && !small" type="button"
      class="absolute inset-0 m-auto flex h-7 w-fit items-center gap-1.5 rounded-full bg-black/60 px-3 text-xs text-white backdrop-blur hover:bg-black/75"
      @click.stop="revealed = true"
    >
      <EyeOff class="size-3.5" /> Mature · show
    </button>
    <slot />
  </MediaView>
</template>
