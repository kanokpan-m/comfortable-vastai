<script setup>
import { computed, onMounted, ref } from 'vue'
import { Sparkles, Search, Download, Check, LoaderCircle, BookmarkPlus, Info, ExternalLink, EyeOff, Heart, Workflow, CircleAlert, Copy } from '@lucide/vue'
import { api } from '../lib/api'
import { bytes } from '../lib/format'
import { route, go } from '../lib/route'
import { useInstalled, matureRevealed, revealMature } from '../lib/catalog'
import { useApp } from '../stores/app'
import Btn from '../components/ui/Btn.vue'
import TextInput from '../components/ui/TextInput.vue'
import Tag from '../components/ui/Tag.vue'
import Bar from '../components/ui/Bar.vue'
import Menu from '../components/ui/Menu.vue'
import Empty from '../components/ui/Empty.vue'
import SampleMedia from '../components/SampleMedia.vue'
import PackDialog from '../components/PackDialog.vue'
import { packMedia } from '../lib/media'
import { kindIcon } from '../lib/icons'

const app = useApp()
const loading = ref(!app.catalog)
const error = ref('')
const q = ref(route.value.query.q || '')
// No category picked yet: "For you" when the library says what you use, else everything.
const cat = computed(() => {
  const c = route.value.query.cat
  if (c === 'all') return ''
  if (c) return c
  return (app.catalog?.packs || []).some((p) => p.for_you) ? 'for-you' : ''
})
onMounted(async () => {
  try { await Promise.all([app.loadCatalog(), app.modelsLoaded ? null : app.loadModels()]) } catch (e) { error.value = e.message } finally { loading.value = false }
  if (route.value.query.pack) openPack(route.value.query.pack)
})

// Mature suggestions follow "Show mature content" in Settings; with it off they can be revealed for this session.
const revealed = ref(matureRevealed())
const showMature = computed(() => !!app.settings.show_nsfw || revealed.value)
const reveal = () => { revealed.value = true; revealMature(true) }

const categories = computed(() => (app.catalog?.categories || []).filter((c) => showMature.value || !c.mature))
const groups = computed(() => {
  const out = []
  for (const c of categories.value) {
    const g = out.find((x) => x.name === (c.group || 'More'))
    g ? g.items.push(c) : out.push({ name: c.group || 'More', items: [c] })
  }
  return out
})
// Components (shared text encoders / VAEs) only show under a pack's "Needs".
const listed = computed(() => (app.catalog?.packs || []).filter((p) => !p.component))
const visible = computed(() => listed.value.filter((p) => showMature.value || !p.nsfw))
const hiddenMature = computed(() => (showMature.value ? 0 : listed.value.filter((p) => p.nsfw).length))
const copyTag = (t) => navigator.clipboard?.writeText(t).then(() => app.toast(`Copied ${t}`, 'success'))
const packs = computed(() => {
  const terms = q.value.toLowerCase().split(/\s+/).filter(Boolean)
  return visible.value.filter((p) =>
    (!cat.value || (cat.value === 'for-you' ? p.for_you : (p.categories || []).includes(cat.value))) &&
    terms.every((t) => `${p.title} ${p.base_model} ${p.summary} ${p.why} ${(p.trigger_words || []).join(' ')} ${(p.categories || []).join(' ')}`.toLowerCase().includes(t)))
})
const counts = computed(() => {
  const c = { all: visible.value.length, 'for-you': visible.value.filter((p) => p.for_you).length }
  for (const p of visible.value) for (const id of p.categories || []) c[id] = (c[id] || 0) + 1
  return c
})
const currentCat = computed(() => categories.value.find((c) => c.id === cat.value))
// Artist names some base models know without a LoRA, one group per base, each with how to write them.
const TAG_HINT = 'already know these artists. Click to copy a tag into your prompt; mix 2-3, weight them like'
const tagGroups = computed(() => {
  const groups = {}
  for (const t of currentCat.value?.prompt_tags || []) (groups[t.base || 'Illustrious'] ||= []).push(t)
  return Object.entries(groups).map(([base, tags]) => ({
    base, tags, hint: currentCat.value?.prompt_hints?.[base] || '',
    who: base === 'Illustrious' ? 'Illustrious and NoobAI' : base,
  }))
})
const setCat = (id) => go('suggested', { cat: id || 'all' })

const { progressOf } = useInstalled(app)
const kindLabel = (p) => (p.files?.length > 1 ? `Pack · ${p.files.length} files` : ({ lora: 'LoRA', checkpoint: 'Checkpoint', base: 'Base model', tool: 'Tool', video: 'Video model', upscaler: 'Upscaler', controlnet: 'ControlNet' }[p.kind] || 'Model'))
// Card picture: the pack's first sample that loads (18+ ones first when mature content is on), then
// images people made with it, then its poster; videos play on hover.
const samples = computed(() => Object.fromEntries(packs.value.map((p) => [p.id, packMedia(p, { mature: showMature.value })])))
const workflowsFor = (p) => (app.catalog?.workflows || []).filter((w) => (w.all_packs || w.packs || []).includes(p.id))

const dialog = ref({ open: false, id: '' })
const selected = computed(() => (app.catalog?.packs || []).find((p) => p.id === dialog.value.id) || null)
function openPack(id) { dialog.value = { open: true, id } }

const busy = ref('')
async function install(p) {
  busy.value = p.id
  try {
    const r = await api.post(`catalog/packs/${p.id}/install`)
    app.toast(r.queued ? `Downloading ${r.queued} file(s) for ${p.title}` : `${p.title} is installed`, r.queued ? 'info' : 'success',
      r.errors.map((e) => `${e.filename}: ${e.error}`).join('; '))
  } catch (e) { app.toast(e.message, 'error') } finally { busy.value = '' }
}
async function save(p) {
  try {
    const r = await api.post(`catalog/packs/${p.id}/save`)
    app.toast(`Saved as bundle “${r.bundle.name}”`, 'success', `${r.added} new model(s) in your library, ${r.linked} already there.`)
    app.loadBundles(); app.loadLibrary(); app.refreshCatalog()
  } catch (e) { app.toast(e.message, 'error') }
}
const menu = (p) => [
  { label: 'Details', icon: Info, onSelect: () => openPack(p.id) },
  { label: p.state.bundle_id ? 'Update bundle' : 'Save as bundle', icon: BookmarkPlus, onSelect: () => save(p) },
  ...workflowsFor(p).slice(0, 3).map((w) => ({ label: `Workflow: ${w.title}`, icon: Workflow, onSelect: () => go('workflows', { open: w.id }) })),
  p.links?.[0] && { label: 'Open model page', icon: ExternalLink, onSelect: () => window.open(p.links[0].url, '_blank', 'noopener') },
].filter(Boolean)
const FAMILY = { krea2: 'Krea 2', qwen: 'Qwen-Image', 'qwen-edit': 'Qwen-Image-Edit', illustrious: 'Illustrious / NoobAI', 'minimax-h3': 'MiniMax H3', wan22: 'Wan 2.2', zimage: 'Z-Image', flux1: 'FLUX.1', flux2: 'FLUX.2', pony: 'Pony', sdxl: 'SDXL', chroma: 'Chroma' }
const families = computed(() => (app.catalog?.library_families || []).map((f) => FAMILY[f] || f))
</script>

<template>
  <div class="mx-auto max-w-[1600px] px-4 py-4 md:px-6">
    <!-- Intro -->
    <div class="mb-4 flex flex-wrap items-center gap-3">
      <div class="flex min-w-0 flex-1 items-center gap-3">
        <span class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary-soft"><Sparkles class="size-5 text-primary-hover" /></span>
        <div class="min-w-0">
          <p class="text-sm font-medium">Picked from Civitai and Hugging Face research</p>
          <p class="truncate text-xs text-fg2">
            One click installs every file a setup needs.<template v-if="families.length"> Ranked for what's in your library: {{ families.slice(0, 3).join(', ') }}.</template>
            <span v-if="app.catalog?.version" class="text-muted"> · catalog {{ app.catalog.version }}{{ app.catalog.source === 'database' ? ' (shared)' : '' }}</span>
          </p>
        </div>
      </div>
      <TextInput v-model="q" class="w-full sm:w-72" :icon="Search" placeholder="Search suggestions, trigger words…" aria-label="Search suggestions" />
    </div>

    <!-- Categories -->
    <div class="-mx-4 mb-4 flex items-center gap-1.5 overflow-x-auto px-4 pb-1" role="tablist" aria-label="Categories">
      <button v-if="counts['for-you']" role="tab" :aria-selected="cat === 'for-you'" class="flex h-7 shrink-0 items-center gap-1.5 rounded-full border px-3 text-xs"
              :class="cat === 'for-you' ? 'border-primary bg-primary-soft text-fg' : 'border-subtle text-fg2 hover:text-fg'" @click="setCat('for-you')">
        <Heart class="size-3" /> For you <span class="text-muted tabular">{{ counts['for-you'] }}</span>
      </button>
      <button role="tab" :aria-selected="!cat" class="h-7 shrink-0 rounded-full border px-3 text-xs" :class="!cat ? 'border-primary bg-primary-soft text-fg' : 'border-subtle text-fg2 hover:text-fg'" @click="setCat('')">
        All <span class="text-muted tabular">{{ counts.all }}</span>
      </button>
      <template v-for="g in groups" :key="g.name">
        <span class="ml-2 shrink-0 text-[10px] font-medium uppercase tracking-wide text-muted">{{ g.name }}</span>
        <button v-for="c in g.items" :key="c.id" role="tab" :aria-selected="cat === c.id" class="flex h-7 shrink-0 items-center gap-1.5 rounded-full border px-3 text-xs"
                :class="cat === c.id ? 'border-primary bg-primary-soft text-fg' : 'border-subtle text-fg2 hover:text-fg'" :title="c.description" @click="setCat(c.id)">
          <span>{{ c.icon }}</span>{{ c.title }} <span class="text-muted tabular">{{ counts[c.id] || 0 }}</span>
        </button>
      </template>
    </div>

    <p v-if="currentCat?.description" class="-mt-2 mb-4 text-xs text-fg2">{{ currentCat.description }}</p>
    <section v-for="g in tagGroups" :key="g.base" class="mb-4 rounded-xl border border-subtle bg-panel p-3">
      <p class="mb-2 text-xs text-fg2">
        <span class="font-medium text-fg">No download needed:</span> {{ g.who }}
        <template v-if="g.hint">{{ g.hint }}</template>
        <template v-else>{{ TAG_HINT }} <span class="font-mono">(wlop:0.8)</span>.</template>
      </p>
      <div class="flex flex-wrap gap-1.5">
        <button v-for="t in g.tags" :key="t.tag" class="flex h-7 items-center gap-1.5 rounded-md border border-subtle px-2 text-[11px] hover:border-border" :title="t.look" @click="copyTag(t.tag)">
          <span class="font-mono">{{ t.tag }}</span><Copy class="size-3 text-muted" />
        </button>
      </div>
    </section>
    <div v-if="hiddenMature > 0" class="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-subtle bg-panel px-3 py-2 text-xs text-fg2">
      <EyeOff class="size-3.5" /> {{ hiddenMature }} mature (18+) suggestions are hidden because “Show mature content” is off in Settings.
      <Btn size="sm" variant="link" @click="reveal">Show them for this session</Btn>
    </div>

    <div v-if="loading" class="flex items-center gap-2 py-10 text-sm text-fg2"><LoaderCircle class="size-4 animate-spin" /> Loading suggestions…</div>
    <p v-else-if="error" class="flex items-center gap-2 rounded-md bg-[color-mix(in_srgb,var(--destructive-hover)_14%,transparent)] px-3 py-2 text-sm text-danger-hover"><CircleAlert class="size-4" /> {{ error }}</p>
    <Empty v-else-if="!packs.length" :icon="Sparkles" title="Nothing here" text="Try another category or search." />

    <ul v-else class="grid grid-cols-2 gap-2 sm:grid-cols-[repeat(auto-fill,minmax(200px,1fr))] sm:gap-3">
      <li v-for="p in packs" :key="p.id" class="group flex flex-col overflow-hidden rounded-xl border border-subtle bg-panel transition-colors hover:border-border">
        <button class="relative block text-left" :aria-label="`Details for ${p.title}`" @click="openPack(p.id)">
          <SampleMedia :items="samples[p.id]" :packs="[p]" :mature="showMature" :icon="kindIcon(p)" :seed="p.id" play="hover" :alt="p.title" class="aspect-[4/5] w-full">
            <div class="absolute inset-x-0 top-0 flex justify-between gap-1 p-2">
              <span class="flex flex-wrap gap-1">
                <Tag class="bg-black/60 text-white backdrop-blur">{{ kindLabel(p) }}</Tag>
                <Tag v-if="p.nsfw" class="bg-black/60 text-danger-hover backdrop-blur">18+</Tag>
              </span>
              <span v-if="p.for_you" class="flex h-5 items-center gap-1 rounded bg-black/60 px-1.5 text-[11px] text-primary-hover backdrop-blur" title="Fits a base model in your library"><Heart class="size-3" /> for you</span>
            </div>
          </SampleMedia>
        </button>
        <div class="flex flex-1 flex-col gap-2 p-2.5">
          <div class="min-w-0">
            <p class="line-clamp-2 text-[13px] font-medium leading-snug" :title="p.title">{{ p.title }}</p>
            <p class="mt-0.5 truncate text-[11px] text-muted">{{ p.base_model || '—' }} · {{ bytes(p.state.total_bytes, 0) }}<template v-if="p.vram_gb"> · {{ p.vram_gb }} GB VRAM</template></p>
            <p v-if="p.why" class="mt-1 line-clamp-2 text-[11px] leading-snug text-fg2">{{ p.why }}</p>
          </div>
          <div class="mt-auto">
            <template v-if="progressOf(p.files).active">
              <div class="mb-1 flex justify-between text-[11px] text-fg2 tabular"><span class="flex items-center gap-1"><LoaderCircle class="size-3 animate-spin" /> Downloading</span><span>{{ Math.round(progressOf(p.files).value) }}%</span></div>
              <Bar :value="progressOf(p.files).value" :label="`Downloading ${p.title}`" />
            </template>
            <div v-else class="flex items-center gap-1">
              <span v-if="p.state.complete" class="flex h-7 flex-1 items-center gap-1 text-xs text-ok"><Check class="size-3.5" /> Installed</span>
              <Btn v-else size="sm" class="flex-1" :loading="busy === p.id" @click="install(p)"><Download class="size-3.5" /> Install <span class="text-muted">{{ bytes(p.state.missing_bytes, 0) }}</span></Btn>
              <Menu :label="`${p.title} actions`" :items="menu(p)" />
            </div>
          </div>
        </div>
      </li>
    </ul>
    <PackDialog v-model:open="dialog.open" :pack="selected" :mature="showMature" />
  </div>
</template>
