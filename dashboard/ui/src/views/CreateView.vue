<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import {
  WandSparkles, ImagePlus, X, Plus, ChevronDown, ChevronLeft, LoaderCircle, Square, RotateCcw, Download, Layers,
  SlidersHorizontal, CircleAlert, Check, Music2, Box, Shuffle, ArrowUpFromLine,
} from '@lucide/vue'
import { api } from '../lib/api'
import { route, go } from '../lib/route'
import { useApp } from '../stores/app'
import { useInstalled, matureRevealed } from '../lib/catalog'
import { workflowSamples } from '../lib/media'
import Btn from '../components/ui/Btn.vue'
import Tag from '../components/ui/Tag.vue'
import Bar from '../components/ui/Bar.vue'
import Toggle from '../components/ui/Toggle.vue'
import Modal from '../components/ui/Modal.vue'
import SampleMedia from '../components/SampleMedia.vue'

const app = useApp()
const { fileInstalled } = useInstalled(app)
const wid = computed(() => route.value.query.w || '')

// ---- which starters can be run from here -------------------------------------------------------------------
const ids = ref([])
const listError = ref('')
onMounted(async () => {
  try {
    const [r] = await Promise.all([api.get('create'), app.catalog ? null : app.loadCatalog(), app.modelsLoaded ? null : app.loadModels()])
    ids.value = r.workflows
  } catch (e) {
    listError.value = e.message
  }
})
const packsById = computed(() => Object.fromEntries((app.catalog?.packs || []).map((p) => [p.id, p])))
const installed = (w) => (w.all_packs || w.packs || []).every((id) => (packsById.value[id]?.files || []).every((f) => f.optional || fileInstalled(f)))
const mature = computed(() => !!app.settings?.show_nsfw || matureRevealed())
const starters = computed(() => (app.catalog?.workflows || [])
  .filter((w) => ids.value.includes(w.id) && (mature.value || !w.nsfw))
  .map((w) => ({ ...w, ready: installed(w) }))
  .sort((a, b) => Number(b.ready) - Number(a.ready)))
const current = computed(() => (app.catalog?.workflows || []).find((w) => w.id === wid.value) || null)

// ---- the form ---------------------------------------------------------------------------------------------
const form = ref(null)
const formError = ref('')
const values = reactive({})
const previews = reactive({})
const randomSeed = ref(true)
const count = ref(1)
const loras = ref([])
const open = reactive({ models: false, advanced: false, negative: false })
async function loadForm(id) {
  form.value = null
  formError.value = ''
  for (const k of Object.keys(values)) delete values[k]
  loras.value = []
  if (!id) return
  try {
    form.value = await api.get(`create/${id}`)
    for (const f of form.value.fields) values[f.key] = f.value
  } catch (e) {
    formError.value = e.message
  }
}
watch(wid, loadForm, { immediate: true })
// Templates name their knobs like code (unet_name, turbo_mode): say them in words.
const NAMES = { unet_name: 'Model', ckpt_name: 'Checkpoint', clip_name: 'Text encoder', vae_name: 'VAE', lora_name: 'LoRA', model_name: 'Model file' }
const nice = (label) => {
  const raw = String(label || '')
  if (NAMES[raw]) return NAMES[raw]
  const t = raw.replace(/_/g, ' ').replace(/\s+/g, ' ').trim()
  return t ? t[0].toUpperCase() + t.slice(1) : raw
}
const fields = computed(() => (form.value?.fields || []).map((f) => ({ ...f, label: nice(f.label) })))
// One seed switch for the whole run (a workflow can have several samplers, each with a seed).
const seedField = computed(() => fields.value.find((f) => f.role === 'seed') || null)
const main = computed(() => fields.value.filter((f) => f.group === 'main' && f.role !== 'negative' && f.role !== 'seed'))
const negatives = computed(() => fields.value.filter((f) => f.group === 'main' && f.role === 'negative'))
const models = computed(() => fields.value.filter((f) => f.group === 'model'))
const advanced = computed(() => {
  const groups = {}
  for (const f of fields.value.filter((x) => x.group === 'advanced')) (groups[f.title] ||= []).push(f)
  return Object.entries(groups)
})
const hasSeed = computed(() => !!seedField.value)

// ---- pictures, audio, video from the phone ---------------------------------------------------------------------
const uploading = ref('')
const accept = { image: 'image/*', audio: 'audio/*', video: 'video/*' }
async function uploadFile(f, file) {
  if (!file) return
  uploading.value = f.key
  try {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch('api/create/upload', { method: 'POST', body: fd })
    const data = await res.json()
    if (!res.ok) throw new Error(data.error || res.statusText)
    values[f.key] = data.value
    previews[f.key] = URL.createObjectURL(file)
  } catch (e) {
    app.toast(`Upload failed: ${e.message}`, 'error')
  } finally {
    uploading.value = ''
  }
}
const inputUrl = (v) => api.url('create/view', { filename: String(v).split('/').pop(), subfolder: String(v).split('/').slice(0, -1).join('/'), type: 'input' })

// ---- LoRAs added here -----------------------------------------------------------------------------------------------
const libraryByFile = computed(() => Object.fromEntries((app.library || []).map((i) => [String(i.filename || '').split('/').pop(), i])))
const loraFiles = computed(() => (app.models?.loras || []).map((m) => {
  const lib = libraryByFile.value[m.name.split('/').pop()]
  return { name: m.name, base: lib?.base_model || '', words: lib?.trigger_words || [], title: lib?.name || m.name }
}))
const picker = ref({ open: false, q: '' })
const pickList = computed(() => {
  const q = picker.value.q.toLowerCase()
  return loraFiles.value.filter((l) => !loras.value.some((x) => x.name === l.name) && `${l.title} ${l.base} ${l.name}`.toLowerCase().includes(q))
})
function addLora(l) {
  loras.value.push({ name: l.name, strength: 0.8, title: l.title, words: l.words })
  const p = main.value.find((f) => f.role === 'prompt')
  if (p && l.words?.length) {
    const missing = l.words.filter((w) => !String(values[p.key] || '').includes(w))
    if (missing.length) values[p.key] = `${missing.join(', ')}, ${values[p.key] || ''}`
  }
  picker.value.open = false
}

// ---- running ----------------------------------------------------------------------------------------------------
const JOBS_KEY = 'comfortable-create-jobs'
const jobs = ref((() => { try { return JSON.parse(sessionStorage.getItem(JOBS_KEY) || '[]') } catch { return [] } })())
const save = () => { try { sessionStorage.setItem(JOBS_KEY, JSON.stringify(jobs.value.slice(0, 40))) } catch { /* private mode */ } }
const OPEN = ['queued', 'running', 'unknown', 'sent']
let timer = null
async function poll() {
  clearTimeout(timer)
  const waiting = jobs.value.filter((j) => OPEN.includes(j.state) && Date.now() - j.at < 6 * 3600e3)
  if (!waiting.length) return
  try {
    const r = await api.get('create/jobs', { ids: waiting.map((j) => j.id).join(',') })
    for (const s of r.jobs) Object.assign(jobs.value.find((j) => j.id === s.id) || {}, s)
    save()
  } catch { /* the instance may be busy loading a model; try again */ }
  timer = setTimeout(poll, 2000)
}
onMounted(poll)
onUnmounted(() => clearTimeout(timer))
const running = ref(false)
async function generate() {
  if (!form.value) return
  running.value = true
  try {
    const changed = {}
    for (const f of fields.value) if (values[f.key] !== f.value) changed[f.key] = values[f.key]
    const r = await api.post(`create/${wid.value}/run`, {
      values: changed, count: count.value, fixed_seed: !randomSeed.value,
      loras: loras.value.map((l) => ({ name: l.name, strength: Number(l.strength) })),
    })
    for (const id of r.prompt_ids) jobs.value.unshift({ id, workflow: wid.value, title: current.value?.title || wid.value, state: 'sent', files: [], at: Date.now() })
    save()
    poll()
  } catch (e) {
    app.toast('Not started', 'error', e.message)
  } finally {
    running.value = false
  }
}
async function cancel(j) {
  await api.post('create/cancel', { prompt_id: j.id }).catch((e) => app.toast(e.message, 'error'))
  j.state = 'cancelled'
  save()
}
const shown = computed(() => jobs.value.filter((j) => !wid.value || j.workflow === wid.value).slice(0, 20))
const progress = computed(() => {
  const p = app.comfy?.progress
  return p?.max ? (100 * p.value) / p.max : 0
})
const viewUrl = (f) => api.url('create/view', f.view)
const kindOf = (f) => (/\.(mp4|webm|mov|mkv)$/i.test(f.filename) ? 'video' : /\.(mp3|wav|flac|ogg|m4a|opus)$/i.test(f.filename) ? 'audio'
  : /\.(glb|gltf|obj|ply|fbx|stl)$/i.test(f.filename) ? '3d' : 'image')

// The full-size result, and using it as the next run's picture.
const lightbox = ref(null)
const imageField = computed(() => main.value.find((f) => f.kind === 'media' && f.media === 'image'))
async function useAsInput(file) {
  const f = imageField.value
  if (!f) return
  const blob = await (await fetch(viewUrl(file))).blob()
  await uploadFile(f, new File([blob], file.filename, { type: blob.type }))
  lightbox.value = null
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
</script>

<template>
  <div class="mx-auto max-w-3xl px-4 py-4 md:px-6">
    <!-- Pick a starter -------------------------------------------------------------------------------------- -->
    <template v-if="!wid">
      <header class="mb-4 flex items-center gap-3">
        <div class="flex size-10 items-center justify-center rounded-xl bg-primary-soft text-primary-hover"><WandSparkles class="size-5" /></div>
        <div class="min-w-0">
          <h1 class="text-base font-semibold">Create</h1>
          <p class="text-xs text-fg2">Pick a starter, type what you want, press Generate.</p>
        </div>
      </header>
      <p v-if="listError" class="text-sm text-danger-hover">{{ listError }}</p>
      <p v-else-if="!app.catalog" class="flex items-center gap-2 py-6 text-sm text-fg2"><LoaderCircle class="size-4 animate-spin" /> Loading…</p>
      <ul v-else class="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <li v-for="w in starters" :key="w.id">
          <button class="flex w-full flex-col overflow-hidden rounded-xl border border-subtle bg-panel text-left hover:border-border" @click="go('create', { w: w.id })">
            <SampleMedia :items="workflowSamples(w, packsById, { mature }).slice(0, 4)" :packs="(w.packs || []).map((id) => packsById[id]).filter(Boolean)"
                         :mature="mature" :seed="w.id" :width="320" play="never" class="aspect-[4/3] w-full" />
            <span class="p-2">
              <span class="line-clamp-2 text-xs font-medium">{{ w.title }}</span>
              <Tag v-if="w.ready" tone="ok" class="mt-1"><Check class="size-3" /> ready</Tag>
              <Tag v-else class="mt-1">install first</Tag>
            </span>
          </button>
        </li>
      </ul>
    </template>

    <!-- The form --------------------------------------------------------------------------------------------------- -->
    <template v-else>
      <header class="mb-3 flex items-center gap-2">
        <Btn variant="ghost" size="icon" aria-label="Other starters" @click="go('create')"><ChevronLeft class="size-5" /></Btn>
        <div class="min-w-0 flex-1">
          <h1 class="truncate text-base font-semibold">{{ current?.title || wid }}</h1>
          <p v-if="current && !installed(current)" class="text-xs text-warn">Some of its models aren't installed yet.
            <a class="underline" :href="`#/workflows?open=${wid}`">Install them</a></p>
        </div>
      </header>
      <p v-if="formError" class="flex items-start gap-2 rounded-lg bg-[color-mix(in_srgb,var(--destructive-hover)_14%,transparent)] px-3 py-2 text-sm text-danger-hover"><CircleAlert class="mt-0.5 size-4 shrink-0" /> {{ formError }}</p>
      <p v-else-if="!form" class="flex items-center gap-2 py-6 text-sm text-fg2"><LoaderCircle class="size-4 animate-spin" /> Loading…</p>

      <div v-else class="space-y-4 pb-40">
        <!-- Main fields -->
        <section class="space-y-3">
          <template v-for="f in main" :key="f.key">
            <!-- picture / audio / video -->
            <div v-if="f.kind === 'media'">
              <p class="mb-1 text-xs font-medium text-fg2">{{ f.label }}</p>
              <label class="relative flex min-h-28 cursor-pointer items-center justify-center overflow-hidden rounded-xl border border-dashed border-subtle bg-card hover:border-border">
                <img v-if="f.media === 'image' && (previews[f.key] || values[f.key])" :src="previews[f.key] || inputUrl(values[f.key])" alt="" class="max-h-64 w-full object-contain" />
                <span v-else class="flex flex-col items-center gap-1 py-6 text-xs text-fg2">
                  <ImagePlus v-if="f.media === 'image'" class="size-6" /><Music2 v-else-if="f.media === 'audio'" class="size-6" /><ArrowUpFromLine v-else class="size-6" />
                  {{ values[f.key] ? String(values[f.key]).split('/').pop() : `Choose ${f.media === 'audio' ? 'an audio file' : f.media === 'video' ? 'a video' : 'a picture'}` }}
                </span>
                <span v-if="uploading === f.key" class="absolute inset-0 flex items-center justify-center bg-overlay"><LoaderCircle class="size-6 animate-spin" /></span>
                <input type="file" class="sr-only" :accept="accept[f.media]" @change="uploadFile(f, $event.target.files[0])" />
              </label>
            </div>
            <!-- prompt -->
            <label v-else-if="f.kind === 'text' && f.multiline" class="block">
              <span class="mb-1 block text-xs font-medium text-fg2">{{ f.label }}</span>
              <textarea v-model="values[f.key]" rows="4" class="w-full rounded-xl border border-subtle bg-card px-3 py-2 text-sm outline-none focus:border-primary" />
            </label>
            <Toggle v-else-if="f.kind === 'bool'" v-model="values[f.key]" :label="f.label" />
            <label v-else class="flex items-center justify-between gap-3 text-sm">
              <span class="min-w-0 truncate text-fg2">{{ f.label }}</span>
              <select v-if="f.kind === 'combo'" v-model="values[f.key]" class="h-8 max-w-[60%] rounded-md border border-subtle bg-card px-2 text-sm">
                <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
              </select>
              <input v-else-if="f.kind === 'int' || f.kind === 'float'" v-model.number="values[f.key]" type="number" :min="f.min" :max="f.max" :step="f.step || (f.kind === 'int' ? 1 : 0.05)"
                     class="h-8 w-28 rounded-md border border-subtle bg-card px-2 text-right text-sm" />
              <input v-else v-model="values[f.key]" class="h-8 w-1/2 rounded-md border border-subtle bg-card px-2 text-sm" />
            </label>
          </template>
          <div v-if="seedField" class="flex flex-wrap items-center gap-3">
            <Toggle v-model="randomSeed" label="New seed each run" class="flex-1" />
            <input v-if="!randomSeed" v-model.number="values[seedField.key]" type="number" class="h-8 w-40 rounded-md border border-subtle bg-card px-2 text-sm" aria-label="Seed" />
          </div>
          <details v-if="negatives.length" class="rounded-xl border border-subtle bg-panel px-3 py-2" :open="open.negative">
            <summary class="cursor-pointer text-xs font-medium text-fg2">Negative prompt</summary>
            <textarea v-for="f in negatives" :key="f.key" v-model="values[f.key]" rows="3" class="mt-2 w-full rounded-lg border border-subtle bg-card px-3 py-2 text-sm outline-none focus:border-primary" />
          </details>
        </section>

        <!-- LoRAs and models -->
        <section class="rounded-xl border border-subtle bg-panel">
          <button class="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm font-medium" @click="open.models = !open.models">
            <Layers class="size-4 text-fg2" /> <span class="flex-1">LoRAs and models</span>
            <Tag v-if="loras.length" tone="primary">{{ loras.length }} added</Tag>
            <ChevronDown class="size-4 transition-transform" :class="open.models && 'rotate-180'" />
          </button>
          <div v-if="open.models" class="space-y-3 border-t border-stroke px-3 py-3">
            <div v-for="(l, i) in loras" :key="l.name" class="rounded-lg bg-card p-2">
              <div class="flex items-center gap-2 text-sm">
                <span class="min-w-0 flex-1 truncate">{{ l.title }}</span>
                <Btn variant="ghost" size="icon-sm" :aria-label="`Remove ${l.title}`" @click="loras.splice(i, 1)"><X class="size-4" /></Btn>
              </div>
              <label class="mt-1 flex items-center gap-2 text-xs text-fg2">Strength
                <input v-model.number="l.strength" type="range" min="0" max="1.5" step="0.05" class="flex-1" />
                <span class="w-9 text-right tabular">{{ Number(l.strength).toFixed(2) }}</span>
              </label>
            </div>
            <Btn size="sm" :disabled="!form.lora_points" @click="picker.open = true"><Plus class="size-4" /> Add a LoRA</Btn>
            <p v-if="!form.lora_points" class="text-xs text-muted">This workflow has no model loader to add a LoRA after.</p>
            <label v-for="f in models" :key="f.key" class="flex items-center justify-between gap-3 text-sm">
              <span class="min-w-0 truncate text-fg2">{{ f.label }}</span>
              <select v-if="f.kind === 'combo'" v-model="values[f.key]" class="h-8 max-w-[60%] rounded-md border border-subtle bg-card px-2 text-xs">
                <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
              </select>
              <input v-else v-model.number="values[f.key]" type="number" step="0.05" class="h-8 w-24 rounded-md border border-subtle bg-card px-2 text-right text-sm" />
            </label>
          </div>
        </section>

        <!-- Everything else -->
        <section class="rounded-xl border border-subtle bg-panel">
          <button class="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm font-medium" @click="open.advanced = !open.advanced">
            <SlidersHorizontal class="size-4 text-fg2" /> <span class="flex-1">All settings</span>
            <ChevronDown class="size-4 transition-transform" :class="open.advanced && 'rotate-180'" />
          </button>
          <div v-if="open.advanced" class="space-y-4 border-t border-stroke px-3 py-3">
            <div v-for="[title, group] in advanced" :key="title">
              <p class="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted">{{ title }}</p>
              <div class="space-y-1.5">
                <template v-for="f in group" :key="f.key">
                  <Toggle v-if="f.kind === 'bool'" v-model="values[f.key]" :label="f.label" />
                  <label v-else-if="f.kind === 'text' && f.multiline" class="block text-xs text-fg2">{{ f.label }}
                    <textarea v-model="values[f.key]" rows="2" class="mt-1 w-full rounded-lg border border-subtle bg-card px-2 py-1.5 text-sm" />
                  </label>
                  <label v-else class="flex items-center justify-between gap-3 text-sm">
                    <span class="min-w-0 truncate text-fg2">{{ f.label }}</span>
                    <select v-if="f.kind === 'combo'" v-model="values[f.key]" class="h-8 max-w-[60%] rounded-md border border-subtle bg-card px-2 text-xs">
                      <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
                    </select>
                    <input v-else-if="f.kind === 'int' || f.kind === 'float'" v-model.number="values[f.key]" type="number" :min="f.min" :max="f.max" :step="f.step || (f.kind === 'int' ? 1 : 0.01)"
                           class="h-8 w-28 rounded-md border border-subtle bg-card px-2 text-right text-sm" />
                    <input v-else v-model="values[f.key]" class="h-8 w-1/2 rounded-md border border-subtle bg-card px-2 text-sm" />
                  </label>
                </template>
              </div>
            </div>
          </div>
        </section>

        <!-- Results -->
        <section v-if="shown.length">
          <h2 class="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Results</h2>
          <ul class="space-y-3">
            <li v-for="j in shown" :key="j.id" class="rounded-xl border border-subtle bg-panel p-2">
              <div class="flex items-center gap-2 text-xs">
                <Tag :tone="j.state === 'done' ? 'ok' : j.state === 'failed' ? 'danger' : 'primary'">
                  <LoaderCircle v-if="OPEN.includes(j.state)" class="size-3 animate-spin" />{{ j.state === 'sent' ? 'queued' : j.state }}
                </Tag>
                <span class="min-w-0 flex-1 truncate text-fg2">{{ new Date(j.at).toLocaleTimeString() }}</span>
                <Btn v-if="OPEN.includes(j.state)" size="sm" variant="ghost" @click="cancel(j)"><Square class="size-3.5" /> Cancel</Btn>
              </div>
              <Bar v-if="j.state === 'running' || app.comfy?.running === j.id" :value="progress" :indeterminate="!progress" class="mt-2" label="Progress" />
              <p v-if="j.error" class="mt-2 break-words text-xs text-danger-hover">{{ j.error }}</p>
              <div v-if="j.files?.length" class="mt-2 grid grid-cols-2 gap-2">
                <template v-for="f in j.files" :key="f.filename">
                  <button v-if="kindOf(f) === 'image'" class="overflow-hidden rounded-lg bg-card" @click="lightbox = f">
                    <img :src="viewUrl(f)" :alt="f.filename" loading="lazy" class="aspect-square w-full object-contain" />
                  </button>
                  <video v-else-if="kindOf(f) === 'video'" :src="viewUrl(f)" controls playsinline loop class="col-span-2 w-full rounded-lg bg-black" />
                  <audio v-else-if="kindOf(f) === 'audio'" :src="viewUrl(f)" controls class="col-span-2 w-full" />
                  <a v-else :href="viewUrl(f)" :download="f.filename" class="col-span-2 flex items-center gap-2 rounded-lg bg-card px-3 py-2 text-sm"><Box class="size-4" /> {{ f.filename }}</a>
                </template>
              </div>
            </li>
          </ul>
        </section>
      </div>

      <!-- Generate, pinned above the tab bar -->
      <div v-if="form" class="fixed inset-x-0 bottom-[calc(56px+env(safe-area-inset-bottom))] z-20 border-t border-stroke bg-panel px-4 py-3 md:bottom-0 md:left-[72px]">
        <div class="mx-auto flex max-w-3xl items-center gap-3">
          <label class="flex items-center gap-1.5 text-xs text-fg2">How many
            <select v-model.number="count" class="h-9 rounded-md border border-subtle bg-card px-2 text-sm text-fg">
              <option v-for="n in [1, 2, 3, 4]" :key="n" :value="n">{{ n }}</option>
            </select>
          </label>
          <Btn variant="primary" size="lg" class="flex-1" :loading="running" @click="generate">
            <Shuffle v-if="randomSeed && hasSeed" class="size-4" /><RotateCcw v-else class="size-4" /> Generate
          </Btn>
        </div>
      </div>
    </template>

    <!-- LoRA picker -->
    <Modal v-model:open="picker.open" title="Add a LoRA" description="LoRAs installed on this instance. More in Suggested.">
      <input v-model="picker.q" placeholder="Search" class="mb-3 h-9 w-full rounded-md border border-subtle bg-card px-3 text-sm" />
      <p v-if="!pickList.length" class="py-4 text-center text-sm text-fg2">No LoRA installed{{ picker.q ? ' matches' : '' }}.
        <a class="text-primary underline" href="#/suggested">Find some in Suggested</a></p>
      <ul class="max-h-[50dvh] space-y-1 overflow-y-auto">
        <li v-for="l in pickList" :key="l.name">
          <button class="flex w-full flex-col rounded-lg px-2 py-2 text-left hover:bg-hover" @click="addLora(l)">
            <span class="truncate text-sm">{{ l.title }}</span>
            <span class="truncate text-[11px] text-muted">{{ l.base || 'base unknown' }} · {{ l.name }}</span>
          </button>
        </li>
      </ul>
    </Modal>

    <!-- A result, full size -->
    <Modal :open="!!lightbox" title="Result" @update:open="(v) => !v && (lightbox = null)">
      <img v-if="lightbox" :src="viewUrl(lightbox)" :alt="lightbox.filename" class="w-full rounded-lg" />
      <template #footer>
        <Btn v-if="imageField" variant="ghost" @click="useAsInput(lightbox)"><ImagePlus class="size-4" /> Use as input</Btn>
        <Btn v-if="lightbox" as="a" :href="viewUrl(lightbox)" :download="lightbox.filename" variant="primary"><Download class="size-4" /> Save</Btn>
      </template>
    </Modal>
  </div>
</template>
