<script setup>
import { computed, onMounted, ref } from 'vue'
import { HardDrive, LoaderCircle, Download, Film, Music2, CircleAlert } from '@lucide/vue'
import { hubApi } from '../lib/hub'
import { bytes } from '../lib/format'
import Btn from '../components/ui/Btn.vue'
import Modal from '../components/ui/Modal.vue'

// Everything the hub copied from your instances to this PC (tools/comfortable_hub.py, Backup).
const data = ref(null)
const items = ref([])
const error = ref('')
const loading = ref(false)
async function load(more = false) {
  loading.value = true
  try {
    const r = await hubApi.get(`backups?offset=${more ? items.value.length : 0}&limit=60`)
    data.value = r
    items.value = more ? [...items.value, ...r.items] : r.items
    error.value = ''
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
onMounted(() => load())
const url = (it) => `hub/backups/file?path=${encodeURIComponent(it.path)}`
const kind = (it) => it.kind || (/\.(mp4|webm|mov)$/i.test(it.path) ? 'video' : /\.(mp3|wav|flac|ogg)$/i.test(it.path) ? 'audio' : 'image')
const open = ref(null)
const when = computed(() => (data.value?.last_sync ? new Date(data.value.last_sync * 1000).toLocaleTimeString() : 'not yet'))
</script>

<template>
  <div class="mx-auto max-w-5xl px-4 py-4 md:px-6">
    <header class="mb-4 flex items-start gap-3">
      <div class="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-primary-hover"><HardDrive class="size-5" /></div>
      <div class="min-w-0 flex-1">
        <h1 class="text-base font-semibold">Saved on your PC</h1>
        <p class="break-all text-xs text-fg2">Every new image, video and song from the connected GPU is copied to
          <span class="font-mono">{{ data?.dir || '…' }}</span> within about 20 s.</p>
        <p v-if="data" class="mt-1 text-xs text-muted">{{ data.total }} files · {{ bytes(data.bytes) }} · last check {{ when }}</p>
      </div>
    </header>
    <p v-if="error || data?.error" class="mb-3 flex items-start gap-2 rounded-lg bg-[color-mix(in_srgb,var(--warning)_12%,transparent)] px-3 py-2 text-xs text-warn">
      <CircleAlert class="mt-0.5 size-4 shrink-0" /> {{ error || data.error }}
    </p>
    <p v-if="!data && loading" class="flex items-center gap-2 py-6 text-sm text-fg2"><LoaderCircle class="size-4 animate-spin" /> Loading…</p>
    <p v-else-if="data && !items.length" class="rounded-xl border border-dashed border-subtle px-4 py-8 text-center text-sm text-fg2">Nothing saved yet. Generations appear here once a GPU is connected.</p>
    <ul class="grid grid-cols-3 gap-1.5 sm:grid-cols-4 lg:grid-cols-6">
      <li v-for="it in items" :key="it.path">
        <button class="relative block aspect-square w-full overflow-hidden rounded-lg bg-card" :aria-label="it.path" @click="open = it">
          <img v-if="kind(it) === 'image'" :src="url(it)" alt="" loading="lazy" class="size-full object-cover" />
          <span v-else class="flex size-full items-center justify-center text-fg2">
            <Film v-if="kind(it) === 'video'" class="size-7" /><Music2 v-else class="size-7" />
          </span>
        </button>
      </li>
    </ul>
    <div v-if="data && items.length < data.total" class="mt-4 flex justify-center">
      <Btn :loading="loading" @click="load(true)">Load more</Btn>
    </div>

    <Modal :open="!!open" :title="open ? open.path.split('/').pop() : ''" @update:open="(v) => !v && (open = null)">
      <template v-if="open">
        <img v-if="kind(open) === 'image'" :src="url(open)" alt="" class="w-full rounded-lg" />
        <video v-else-if="kind(open) === 'video'" :src="url(open)" controls playsinline class="w-full rounded-lg bg-black" />
        <audio v-else :src="url(open)" controls class="w-full" />
        <p class="mt-2 break-all text-[11px] text-muted">{{ open.path }} · {{ bytes(open.size) }}</p>
      </template>
      <template #footer>
        <Btn v-if="open" as="a" :href="url(open)" :download="open.path.split('/').pop()" variant="primary"><Download class="size-4" /> Save to phone</Btn>
      </template>
    </Modal>
  </div>
</template>
