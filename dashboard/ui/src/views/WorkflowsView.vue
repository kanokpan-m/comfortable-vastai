<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import {
  Workflow, Search, Play, Download, Check, LoaderCircle, Heart, EyeOff, CircleAlert, FileJson, Info,
  Type, PencilRuler, PersonStanding, Spline, ScanSearch, Palette, Smile, Paintbrush, Film, Clapperboard,
  LayoutDashboard, Rotate3d, Scissors, MessageSquareText, Images, MicVocal, Music, Box,
} from '@lucide/vue'
import { bytes } from '../lib/format'
import { route, go } from '../lib/route'
import { useInstalled, matureRevealed, revealMature } from '../lib/catalog'
import { workflowSamples, workflowModels } from '../lib/media'
import { installStarter, openStarter, downloadStarter } from '../lib/starter'
import { useApp } from '../stores/app'
import Btn from '../components/ui/Btn.vue'
import TextInput from '../components/ui/TextInput.vue'
import Tag from '../components/ui/Tag.vue'
import Bar from '../components/ui/Bar.vue'
import Menu from '../components/ui/Menu.vue'
import Empty from '../components/ui/Empty.vue'
import WorkflowDialog from '../components/WorkflowDialog.vue'
import SampleHero from '../components/SampleHero.vue'

const app = useApp()
const loading = ref(!app.catalog)
const error = ref('')
const q = ref('')
const task = computed(() => route.value.query.task || '')
onMounted(async () => {
  try { await Promise.all([app.loadCatalog(), app.modelsLoaded ? null : app.loadModels()]) } catch (e) { error.value = e.message } finally { loading.value = false }
  if (route.value.query.open) openWf(route.value.query.open)
})
watch(() => route.value.query.open, (id) => { if (id && app.catalog) openWf(id) })

const TASKS = {
  t2i: ['Text to image', Type], edit: ['Image edit', PencilRuler], pose: ['Pose swap', PersonStanding], controlnet: ['ControlNet', Spline],
  upscale: ['Upscale', ScanSearch], style: ['Styles & artists', Palette], detail: ['Face & detail', Smile], inpaint: ['Inpaint', Paintbrush],
  layout: ['Layout', LayoutDashboard], angles: ['New angles', Rotate3d], cutout: ['Remove background', Scissors],
  caption: ['Image to prompt', MessageSquareText],
  i2v: ['Image to video', Film], t2v: ['Text to video', Clapperboard], flf2v: ['First & last frame', Images],
  lipsync: ['Lip sync', MicVocal], video: ['Video', Film], audio: ['Music', Music], '3d': ['3D model', Box],
}
const label = (t) => TASKS[t]?.[0] || t
const icon = (t) => TASKS[t]?.[1] || Workflow

const revealed = ref(matureRevealed())
const showMature = computed(() => !!app.settings.show_nsfw || revealed.value)
const reveal = () => { revealed.value = true; revealMature(true) }
const all = computed(() => (app.catalog?.workflows || []).map((w) => ({ ...w, task_label: label(w.task) })))
const visible = computed(() => all.value.filter((w) => showMature.value || !w.nsfw))
const hiddenMature = computed(() => (showMature.value ? 0 : all.value.filter((w) => w.nsfw).length))
const tasks = computed(() => [...new Set(visible.value.map((w) => w.task))].sort((a, b) => Object.keys(TASKS).indexOf(a) - Object.keys(TASKS).indexOf(b)))
const list = computed(() => {
  const terms = q.value.toLowerCase().split(/\s+/).filter(Boolean)
  return visible.value.filter((w) => (!task.value || w.task === task.value) &&
    terms.every((t) => `${w.title} ${w.summary} ${w.task_label} ${(w.categories || []).join(' ')}`.toLowerCase().includes(t)))
})
const packs = computed(() => Object.fromEntries((app.catalog?.packs || []).map((p) => [p.id, p])))
// What each starter makes (its models' samples, 18+ first when mature content is on) and its models.
const media = computed(() => Object.fromEntries(list.value.map((w) => [w.id, {
  samples: workflowSamples(w, packs.value, { mature: showMature.value }).slice(0, 8),
  models: workflowModels(w, packs.value),
}])))
const { progressOf } = useInstalled(app)
const filesOf = (w) => (w.all_packs || []).flatMap((id) => (packs.value[id]?.files || []).filter((f) => !f.optional))

const dialog = ref({ open: false, id: '' })
const selected = computed(() => all.value.find((w) => w.id === dialog.value.id) || null)
function openWf(id) { dialog.value = { open: true, id } }
watch(() => dialog.value.open, (v) => { if (!v && route.value.query.open) go('workflows', { task: task.value }) })

const busy = ref('')
async function install(w) {
  busy.value = w.id
  try { await installStarter(app, w) } catch (e) { app.toast(e.message, 'error') } finally { busy.value = '' }
}
const menu = (w) => [
  { label: 'Details', icon: Info, onSelect: () => openWf(w.id) },
  { label: 'Open in ComfyUI', icon: Play, onSelect: () => openStarter(app, w) },
  { label: 'Download .json', icon: FileJson, onSelect: () => downloadStarter(w).catch((e) => app.toast(e.message, 'error')) },
]
</script>

<template>
  <div class="mx-auto max-w-[1400px] px-4 py-4 md:px-6">
    <div class="mb-4 flex flex-wrap items-center gap-3">
      <div class="flex min-w-0 flex-1 items-center gap-3">
        <span class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary-soft"><Workflow class="size-5 text-primary-hover" /></span>
        <div class="min-w-0">
          <p class="text-sm font-medium">Starter workflows</p>
          <p class="text-xs text-fg2">Installs every model and node pack a workflow needs, then opens it in ComfyUI with the right model picked in every node.</p>
        </div>
      </div>
      <TextInput v-model="q" class="w-full sm:w-64" :icon="Search" placeholder="Search workflows" aria-label="Search workflows" />
    </div>

    <div class="-mx-4 mb-4 flex gap-1.5 overflow-x-auto px-4 pb-1" role="tablist" aria-label="Task">
      <button role="tab" :aria-selected="!task" class="h-7 shrink-0 rounded-full border px-3 text-xs" :class="!task ? 'border-primary bg-primary-soft text-fg' : 'border-subtle text-fg2 hover:text-fg'" @click="go('workflows')">All · {{ visible.length }}</button>
      <button v-for="t in tasks" :key="t" role="tab" :aria-selected="task === t" class="flex h-7 shrink-0 items-center gap-1.5 rounded-full border px-3 text-xs"
              :class="task === t ? 'border-primary bg-primary-soft text-fg' : 'border-subtle text-fg2 hover:text-fg'" @click="go('workflows', { task: t })">
        <component :is="icon(t)" class="size-3.5" /> {{ label(t) }}
      </button>
    </div>
    <div v-if="hiddenMature > 0" class="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-subtle bg-panel px-3 py-2 text-xs text-fg2">
      <EyeOff class="size-3.5" /> {{ hiddenMature }} mature (18+) workflows are hidden because “Show mature content” is off in Settings.
      <Btn size="sm" variant="link" @click="reveal">Show them for this session</Btn>
    </div>

    <div v-if="loading" class="flex items-center gap-2 py-10 text-sm text-fg2"><LoaderCircle class="size-4 animate-spin" /> Loading workflows…</div>
    <p v-else-if="error" class="flex items-center gap-2 rounded-md bg-[color-mix(in_srgb,var(--destructive-hover)_14%,transparent)] px-3 py-2 text-sm text-danger-hover"><CircleAlert class="size-4" /> {{ error }}</p>
    <Empty v-else-if="!list.length" :icon="Workflow" title="No workflows here" text="Try another task or search." />

    <ul v-else class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <li v-for="w in list" :key="w.id" class="flex flex-col overflow-hidden rounded-xl border border-subtle bg-panel transition-colors hover:border-border">
        <SampleHero :samples="media[w.id].samples" :models="media[w.id].models" :mature="showMature" :icon="icon(w.task)" :seed="w.id" @open="openWf(w.id)">
          <div class="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between gap-1 p-2">
            <span class="flex flex-wrap gap-1">
              <Tag class="bg-black/60 text-white backdrop-blur"><component :is="icon(w.task)" class="size-3" /> {{ w.task_label }}</Tag>
              <Tag v-if="w.nsfw" class="bg-black/60 text-danger-hover backdrop-blur">18+</Tag>
            </span>
            <span v-if="w.for_you" class="flex h-5 items-center gap-1 rounded bg-black/60 px-1.5 text-[11px] text-primary-hover backdrop-blur" title="Uses a base model in your library"><Heart class="size-3" /> for you</span>
          </div>
        </SampleHero>
        <div class="flex flex-1 flex-col p-3.5">
        <div class="flex items-start gap-2">
          <button class="min-w-0 flex-1 text-left" @click="openWf(w.id)">
            <p class="font-medium leading-snug hover:underline">{{ w.title }}</p>
            <p class="mt-1 line-clamp-2 text-xs leading-relaxed text-fg2">{{ w.summary }}</p>
          </button>
          <Menu :label="`${w.title} actions`" :items="menu(w)" />
        </div>
        <div class="mt-auto pt-3">
          <template v-if="progressOf(filesOf(w)).active">
            <div class="mb-1 flex justify-between text-[11px] text-fg2 tabular"><span class="flex items-center gap-1"><LoaderCircle class="size-3 animate-spin" /> Downloading models</span><span>{{ Math.round(progressOf(filesOf(w)).value) }}%</span></div>
            <Bar :value="progressOf(filesOf(w)).value" :label="`Installing ${w.title}`" />
          </template>
          <div v-else class="flex flex-wrap items-center gap-2">
            <span v-if="w.state.complete" class="flex items-center gap-1 text-xs text-ok"><Check class="size-3.5" /> Models installed</span>
            <span v-else class="text-xs text-fg2">{{ bytes(w.state.missing_bytes) }} to download</span>
            <div class="ml-auto flex gap-1.5">
              <Btn v-if="!w.state.complete" size="sm" :loading="busy === w.id" @click="install(w)"><Download class="size-3.5" /> Install</Btn>
              <Btn size="sm" :variant="w.state.complete ? 'primary' : 'ghost'" @click="w.state.complete ? openStarter(app, w) : openWf(w.id)">
                <Play class="size-3.5" /> {{ w.state.complete ? 'Open in ComfyUI' : 'Details' }}
              </Btn>
            </div>
          </div>
        </div>
        </div>
      </li>
    </ul>
    <WorkflowDialog v-model:open="dialog.open" :wf="selected" :mature="showMature" />
  </div>
</template>
