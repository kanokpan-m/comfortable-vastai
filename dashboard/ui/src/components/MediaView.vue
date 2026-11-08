<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Play } from '@lucide/vue'
import { sized, isVideo, noteLoad, stallFor } from '../lib/media'

// One sample: an image, an animated WebP or a video (a still first; the video loads once on screen
// or hovered). The `placeholder` slot stays visible underneath until the picture has loaded.
// `error` means nothing of this sample can be shown: the caller moves on to another one.
const props = defineProps({
  item: { type: Object, default: null },
  width: { type: Number, default: 450 },      // size asked from Civitai's CDN
  play: { type: String, default: 'visible' }, // videos: 'visible' (on screen), 'hover' or 'never'
  fit: { type: String, default: 'cover' },    // 'contain': the whole sample over a blurred copy of it
  controls: Boolean,
  loop: { type: Boolean, default: true },
  alt: { type: String, default: '' },
  blurred: Boolean,                           // a mature picture not revealed yet
})
const emit = defineEmits(['ended', 'error'])
const root = ref(null)
const video = ref(null)
const visible = ref(false)
const hovered = ref(false)
const armed = ref(false)       // the video file is only fetched once it is on screen (or hovered)
const stillOk = ref(false)     // the picture (a video's first frame) has loaded
const stillBad = ref(false)
const videoOk = ref(false)     // the video has a frame to show
const videoAlive = ref(false)  // the video answered (metadata at least)
const videoBad = ref(false)
const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

const vid = computed(() => isVideo(props.item))
const src = computed(() => sized(props.item, { width: props.width }))
const still = computed(() => (vid.value ? sized(props.item, { width: props.width, still: true }) : src.value))
const playing = computed(() => vid.value && !reduced && !videoBad.value &&
  (props.play === 'visible' ? visible.value : props.play === 'hover' ? hovered.value : false))
const showVideo = computed(() => vid.value && !videoBad.value && (armed.value || props.controls))

const arm = () => { if (visible.value && (props.play !== 'hover' || hovered.value)) armed.value = true }
watch(() => props.item?.url, () => { stillOk.value = stillBad.value = videoOk.value = videoAlive.value = videoBad.value = armed.value = false; arm() })
watch([visible, hovered], arm)
watch([playing, video, armed], ([on, el]) => {
  if (!el) return
  if (on && armed.value) el.play().catch(() => { /* not allowed yet, the still stays */ })
  else el.pause()
}, { flush: 'post' })

// A video whose first frame won't load may still play (on screen or in a player), so it gets a try;
// anything else that fails is given up.
function onStillLoad() {
  stillOk.value = true
  noteLoad(still.value, true)
}
function onStillError() {
  if (stillBad.value || stillOk.value) return
  stillBad.value = true
  noteLoad(still.value, false)
  if (vid.value && !videoBad.value && (props.controls || props.play === 'visible')) armed.value = true
  else emit('error')
}
function onVideoError() {
  if (videoBad.value) return
  videoBad.value = true
  if (!stillOk.value) emit('error')
}

// Hung requests never fire `error`: give up on them after a while (only counted while on screen,
// where the browser is actually loading them).
let stillTimer, videoTimer
watch([() => props.item?.url, visible, stillOk, stillBad], () => {
  clearTimeout(stillTimer)
  if (props.item && visible.value && !stillOk.value && !stillBad.value) stillTimer = setTimeout(onStillError, stallFor(still.value))
}, { immediate: true })
watch([showVideo, visible, videoAlive, videoBad, stillOk], () => {
  clearTimeout(videoTimer)
  if (showVideo.value && visible.value && !videoAlive.value && !videoBad.value && !stillOk.value) videoTimer = setTimeout(onVideoError, stallFor(src.value))
})
onBeforeUnmount(() => { clearTimeout(stillTimer); clearTimeout(videoTimer) })

let io
onMounted(() => {
  if (typeof IntersectionObserver !== 'function') { visible.value = true; return }
  io = new IntersectionObserver(([e]) => { visible.value = e.isIntersecting }, { threshold: 0.3 })
  if (root.value) io.observe(root.value)
})
onBeforeUnmount(() => io?.disconnect())
const fitClass = computed(() => [props.fit === 'contain' ? 'object-contain' : 'object-cover', props.blurred && 'scale-110 blur-2xl'])
</script>

<template>
  <div ref="root" class="relative overflow-hidden bg-card" @pointerenter="hovered = true" @pointerleave="hovered = false">
    <slot name="placeholder" />
    <template v-if="item">
      <img v-if="fit === 'contain' && stillOk" :src="still" alt="" aria-hidden="true" referrerpolicy="no-referrer"
           class="absolute inset-0 size-full scale-110 object-cover opacity-45 blur-2xl" />
      <img v-if="!stillBad" :key="item.url" :src="still" :alt="alt" loading="lazy" decoding="async" referrerpolicy="no-referrer"
           class="absolute inset-0 size-full transition-opacity duration-300" :class="[fitClass, stillOk ? 'opacity-100' : 'opacity-0']"
           @load="onStillLoad" @error="onStillError" />
      <video
        v-if="showVideo" ref="video" :key="`v:${item.url}`" :src="src" :poster="stillOk ? still : undefined" muted playsinline :loop="loop" :controls="controls"
        :preload="controls ? 'metadata' : 'auto'" :aria-label="alt" class="absolute inset-0 size-full transition-opacity duration-300"
        :class="[fitClass, videoOk || controls ? 'opacity-100' : 'opacity-0']"
        @loadedmetadata="videoAlive = true" @loadeddata="videoOk = videoAlive = true" @playing="videoOk = videoAlive = true" @ended="emit('ended')" @error="onVideoError"
      />
      <span v-if="vid && stillOk && !playing && !controls" class="pointer-events-none absolute bottom-2 right-2 flex size-6 items-center justify-center rounded-full bg-black/60 text-white">
        <Play class="size-3" aria-hidden="true" />
      </span>
    </template>
    <slot />
  </div>
</template>
