<script setup>
import { computed, ref, watch } from 'vue'
import { Download, Check, BookmarkPlus, Copy, ExternalLink, Workflow, KeyRound, Package, HardDrive, Cpu, CircleAlert } from '@lucide/vue'
import { api } from '../lib/api'
import { bytes, pct } from '../lib/format'
import { go } from '../lib/route'
import { useApp } from '../stores/app'
import { useInstalled } from '../lib/catalog'
import Modal from './ui/Modal.vue'
import Btn from './ui/Btn.vue'
import Tag from './ui/Tag.vue'
import Bar from './ui/Bar.vue'
import Toggle from './ui/Toggle.vue'
import MediaGallery from './MediaGallery.vue'
import { packMedia } from '../lib/media'
import { kindIcon } from '../lib/icons'

const open = defineModel('open', { type: Boolean })
// mature: 18+ samples may show (and lead)
const props = defineProps({ pack: { type: Object, default: null }, mature: Boolean })
const samples = computed(() => packMedia(props.pack, { mature: props.mature }))
const app = useApp()
const autoInstall = ref(false)
watch(open, (v) => { if (v) autoInstall.value = false })

const packs = computed(() => Object.fromEntries((app.catalog?.packs || []).map((p) => [p.id, p])))
const requires = computed(() => (props.pack?.requires || []).map((id) => packs.value[id]).filter(Boolean))
const workflows = computed(() => (app.catalog?.workflows || []).filter((w) => (w.all_packs || w.packs || []).includes(props.pack?.id)))
const SETTINGS = [['steps', 'Steps'], ['cfg', 'CFG'], ['sampler', 'Sampler'], ['scheduler', 'Scheduler'], ['shift', 'Shift'],
  ['resolution', 'Resolution'], ['frames', 'Frames'], ['fps', 'FPS'], ['clip_skip', 'Clip skip'], ['strength', 'LoRA strength']]
const settings = computed(() => SETTINGS.map(([k, label]) => [label, props.pack?.settings?.[k]]).filter(([, v]) => v !== undefined && v !== null && v !== ''))
const { fileInstalled, taskFor, progressOf } = useInstalled(app)
const prog = computed(() => progressOf(props.pack?.files))
const needsKey = computed(() => props.pack?.state?.needs_token && !app.settings.civitai_token)

const installing = ref(false)
async function install() {
  installing.value = true
  try {
    if (!app.modelsLoaded) await app.loadModels()
    const r = await api.post(`catalog/packs/${props.pack.id}/install`)
    const nodes = Object.values(r.node_packs || {}).filter((v) => v === 'queued').length
    app.toast(r.queued ? `Downloading ${r.queued} file(s)${nodes ? `, installing ${nodes} node pack(s)` : ''}` : 'Everything is installed', r.queued ? 'info' : 'success',
      [...r.errors.map((e) => `${e.filename}: ${e.error}`), ...Object.entries(r.node_packs || {}).filter(([, v]) => !['queued', 'already installed', 'installed'].includes(v)).map(([k, v]) => `${k}: ${v}`)].join('; '))
    if (r.restart_needed) app.toast('Restart ComfyUI once the node packs are installed (Workflows or Fixer screen)', 'info')
  } catch (e) { app.toast(e.message, 'error') } finally { installing.value = false }
}
const saving = ref(false)
async function save() {
  saving.value = true
  try {
    const r = await api.post(`catalog/packs/${props.pack.id}/save`, { auto_install: autoInstall.value })
    app.toast(`Saved as bundle “${r.bundle.name}”`, 'success', `${r.added} new model(s) in your library, ${r.linked} already there.${autoInstall.value ? ' It installs on every new instance.' : ''}`)
    app.loadBundles(); app.loadLibrary(); app.refreshCatalog()
  } catch (e) { app.toast(e.message, 'error') } finally { saving.value = false }
}
const copy = (text) => navigator.clipboard?.writeText(text).then(() => app.toast('Copied', 'success'))
</script>

<template>
  <Modal v-model:open="open" side="right" :title="pack?.title" :description="[pack?.base_model, pack?.kind].filter(Boolean).join(' · ')">
    <div v-if="pack" class="space-y-5">
      <MediaGallery :items="samples" :packs="[pack]" :mature="mature" :icon="kindIcon(pack)" :seed="pack.id" :label="pack.title" />
      <div class="flex flex-wrap gap-1.5">
        <Tag v-if="pack.nsfw" tone="danger">18+</Tag>
        <Tag v-if="pack.for_you" tone="primary">Fits your library</Tag>
        <Tag v-for="c in pack.categories" :key="c">{{ (app.catalog?.categories || []).find((x) => x.id === c)?.title || c }}</Tag>
      </div>
      <p class="text-sm leading-relaxed">{{ pack.summary }}</p>
      <p v-if="pack.works_with" class="text-xs text-fg2"><span class="text-muted">Works with</span> {{ pack.works_with }}</p>
      <p v-if="pack.why" class="rounded-lg bg-primary-soft px-3 py-2 text-xs leading-relaxed text-fg"><span class="font-medium text-primary-hover">Why it's here · </span>{{ pack.why }}</p>

      <dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
        <dt class="flex items-center gap-1.5 text-fg2"><HardDrive class="size-3.5" /> Download</dt>
        <dd>{{ bytes(pack.state.total_bytes) }}<span v-if="pack.state.installed" class="text-muted"> · {{ bytes(pack.state.missing_bytes) }} still to get</span></dd>
        <template v-if="pack.vram_gb"><dt class="flex items-center gap-1.5 text-fg2"><Cpu class="size-3.5" /> VRAM</dt><dd>{{ pack.vram_gb }} GB or more</dd></template>
        <template v-for="[label, v] in settings" :key="label"><dt class="text-fg2">{{ label }}</dt><dd class="tabular">{{ v }}</dd></template>
      </dl>
      <p v-if="pack.settings?.notes" class="text-xs leading-relaxed text-fg2">{{ pack.settings.notes }}</p>

      <section v-if="pack.trigger_words?.length">
        <h3 class="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">Trigger words</h3>
        <div class="flex flex-wrap gap-1.5">
          <button v-for="w in pack.trigger_words" :key="w" class="flex h-7 items-center gap-1 rounded-md border border-subtle px-2 font-mono text-[11px] hover:border-border" :title="`Copy ${w}`" @click="copy(w)">{{ w }} <Copy class="size-3 text-muted" /></button>
        </div>
      </section>

      <p v-if="needsKey" class="flex items-start gap-2 rounded-lg bg-[color-mix(in_srgb,var(--warning)_12%,transparent)] px-3 py-2 text-xs text-warn">
        <KeyRound class="mt-0.5 size-3.5 shrink-0" /> <span>Civitai only gives mature files to signed-in users: add your Civitai API key in <a href="#/settings" class="underline">Settings</a> first.</span>
      </p>

      <section v-if="requires.length">
        <h3 class="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">Needs</h3>
        <ul class="space-y-1">
          <li v-for="r in requires" :key="r.id" class="flex items-center gap-2 text-xs">
            <component :is="r.state.complete ? Check : Package" class="size-3.5" :class="r.state.complete ? 'text-ok' : 'text-muted'" />
            <span class="flex-1">{{ r.title }}</span><span class="text-muted">{{ r.state.complete ? 'installed' : `${bytes(r.state.missing_bytes)}, installed with this` }}</span>
          </li>
        </ul>
      </section>

      <section>
        <h3 class="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">Files</h3>
        <ul class="divide-y divide-stroke overflow-hidden rounded-lg border border-subtle">
          <li v-for="f in pack.files" :key="f.url" class="px-3 py-2">
            <div class="flex items-center gap-2">
              <p class="min-w-0 flex-1 truncate font-mono text-[12px]" :title="f.filename">{{ f.filename }}</p>
              <Check v-if="fileInstalled(f)" class="size-3.5 shrink-0 text-ok" aria-label="Installed" />
              <Tag v-else-if="f.optional">optional</Tag>
            </div>
            <p class="mt-0.5 truncate text-[11px] text-muted">{{ app.categoryLabel(f.category) }} · {{ bytes(f.size) }}<template v-if="f.name"> · {{ f.name }}</template></p>
            <div v-if="taskFor(f) && !['done'].includes(taskFor(f).status)" class="mt-1.5"><Bar :value="pct(taskFor(f).done, taskFor(f).size)" :indeterminate="!taskFor(f).size" :tone="taskFor(f).status === 'failed' ? 'danger' : 'primary'" :label="`${f.filename} progress`" /></div>
            <p v-if="taskFor(f)?.status === 'failed'" class="mt-1 text-[11px] text-danger-hover">{{ taskFor(f).error }}</p>
          </li>
        </ul>
      </section>

      <section v-if="pack.node_packs?.length">
        <h3 class="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">Node packs</h3>
        <ul class="space-y-1 text-xs">
          <li v-for="n in pack.node_packs" :key="n.id" class="flex items-center gap-2"><Package class="size-3.5 text-muted" /> <span class="flex-1">{{ n.title || n.id }}</span>
            <a v-if="n.repository" :href="n.repository" target="_blank" rel="noopener" class="text-muted hover:text-fg" :aria-label="`${n.title || n.id} repository`"><ExternalLink class="size-3.5" /></a></li>
        </ul>
      </section>

      <section v-if="workflows.length">
        <h3 class="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">Starter workflows</h3>
        <div class="flex flex-wrap gap-1.5">
          <Btn v-for="w in workflows" :key="w.id" size="sm" @click="open = false; go('workflows', { open: w.id })"><Workflow class="size-3.5" /> {{ w.title }}</Btn>
        </div>
      </section>

      <section v-if="pack.links?.length">
        <h3 class="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">Links</h3>
        <ul class="space-y-1 text-xs">
          <li v-for="l in pack.links" :key="l.url"><a :href="l.url" target="_blank" rel="noopener" class="inline-flex items-center gap-1 text-primary-hover hover:underline">{{ l.title }} <ExternalLink class="size-3" /></a></li>
        </ul>
      </section>
      <p v-if="pack.state.bundle_id" class="flex items-center gap-1.5 text-xs text-ok"><Check class="size-3.5" /> Saved as a bundle in your library</p>
    </div>
    <template v-if="pack" #footer>
      <div v-if="prog.active" class="mr-auto w-40"><Bar :value="prog.value" label="Pack download progress" /><p class="mt-1 text-[11px] text-fg2">Downloading {{ prog.active }} file(s)</p></div>
      <div v-else-if="!pack.state.bundle_id" class="mr-auto"><Toggle v-model="autoInstall" label="Auto-install on new instances" /></div>
      <Btn :loading="saving" @click="save"><BookmarkPlus class="size-4" /> {{ pack.state.bundle_id ? 'Update bundle' : 'Save as bundle' }}</Btn>
      <Btn v-if="!pack.state.complete" variant="primary" :loading="installing" :disabled="prog.active > 0" @click="install">
        <Download class="size-4" /> Install <span class="opacity-80">· {{ bytes(pack.state.missing_bytes) }}</span>
      </Btn>
      <span v-else class="flex h-8 items-center gap-1.5 px-2 text-sm text-ok"><Check class="size-4" /> Installed</span>
    </template>
  </Modal>
</template>
