<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Download, Check, Package, Play, RotateCcw, FileJson, CircleAlert, LoaderCircle, KeyRound, Image as ImageIcon, Workflow } from '@lucide/vue'
import { api } from '../lib/api'
import { bytes } from '../lib/format'
import { go } from '../lib/route'
import { embedded, bridge } from '../lib/bridge'
import { useInstalled } from '../lib/catalog'
import { workflowSamples, workflowModels } from '../lib/media'
import { installStarter, openStarter, downloadStarter } from '../lib/starter'
import { useApp } from '../stores/app'
import Modal from './ui/Modal.vue'
import Btn from './ui/Btn.vue'
import Tag from './ui/Tag.vue'
import Bar from './ui/Bar.vue'
import MediaGallery from './MediaGallery.vue'
import PackAvatar from './PackAvatar.vue'

const open = defineModel('open', { type: Boolean })
// mature: 18+ samples may show (and lead)
const props = defineProps({ wf: { type: Object, default: null }, mature: Boolean })
const app = useApp()
const status = ref(null)
const installing = ref(false)
const installed = ref(null)     // result of the last install request
const restarting = ref(false)
let timer = null

const packs = computed(() => Object.fromEntries((app.catalog?.packs || []).map((p) => [p.id, p])))
const usedPacks = computed(() => (props.wf?.all_packs || props.wf?.packs || []).map((id) => packs.value[id]).filter(Boolean))
const samples = computed(() => workflowSamples(props.wf, packs.value, { mature: props.mature }))
const models = computed(() => workflowModels(props.wf, packs.value))
const { progressOf } = useInstalled(app)
const prog = computed(() => progressOf(status.value?.files || []))
const missingFiles = computed(() => (status.value?.files || []).filter((f) => !f.installed))
const missingNodes = computed(() => (status.value?.nodes || []).filter((n) => !n.installed))
const ready = computed(() => status.value?.ready)
const needsKey = computed(() => props.wf?.state?.needs_token && !app.settings.civitai_token)
const nodesQueued = computed(() => Object.values(installed.value?.node_packs || {}).some((v) => v === 'queued' || v === 'installed'))

async function refresh() {
  if (!props.wf) return
  try { status.value = await api.get(`catalog/workflows/${props.wf.id}/status`) } catch { /* ComfyUI restarting */ }
}
function poll() {
  clearInterval(timer)
  timer = setInterval(() => { if (open.value) refresh() }, 4000)
}
watch(open, (v) => { if (v) { status.value = null; installed.value = null; refresh(); poll() } else clearInterval(timer) })
onBeforeUnmount(() => clearInterval(timer))

async function install() {
  installing.value = true
  try { installed.value = await installStarter(app, props.wf); refresh() } catch (e) { app.toast(e.message, 'error') } finally { installing.value = false }
}
async function restart() {
  restarting.value = true
  try {
    await api.post('comfy/restart')
    app.toast('ComfyUI restarted: new nodes are loaded', 'success')
    installed.value = null
    if (embedded) setTimeout(() => bridge.reloadComfy(), 4000)
    else setTimeout(refresh, 8000)
  } catch (e) { app.toast(e.message, 'error') } finally { restarting.value = false }
}
</script>

<template>
  <Modal v-model:open="open" side="right" :title="wf?.title" :description="wf?.summary">
    <div v-if="wf" class="space-y-5">
      <MediaGallery :items="samples" :packs="models" :mature="mature" :icon="Workflow" :seed="wf.id" :label="wf.title" />
      <div class="flex flex-wrap gap-1.5">
        <Tag tone="primary">{{ wf.task_label || wf.task }}</Tag>
        <Tag v-if="wf.nsfw" tone="danger">18+</Tag>
        <Tag v-if="wf.for_you">Fits your library</Tag>
        <Tag v-for="i in wf.inputs || []" :key="i"><ImageIcon class="size-3" /> {{ i }}</Tag>
      </div>

      <section v-if="wf.steps?.length">
        <h3 class="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">How to use it</h3>
        <ol class="list-decimal space-y-1 pl-5 text-sm leading-relaxed marker:text-muted">
          <li v-for="(s, i) in wf.steps" :key="i">{{ s }}</li>
        </ol>
      </section>

      <p v-if="needsKey" class="flex items-start gap-2 rounded-lg bg-[color-mix(in_srgb,var(--warning)_12%,transparent)] px-3 py-2 text-xs text-warn">
        <KeyRound class="mt-0.5 size-3.5 shrink-0" /> <span>Some files are mature Civitai models, which need your Civitai API key: add it in <a href="#/settings" class="underline">Settings</a>.</span>
      </p>

      <section>
        <h3 class="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">Models</h3>
        <ul class="divide-y divide-stroke overflow-hidden rounded-lg border border-subtle">
          <li v-for="p in usedPacks" :key="p.id" class="flex items-center gap-3 px-3 py-2">
            <span class="relative shrink-0">
              <PackAvatar :pack="p" :mature="mature" size="size-9" />
              <span v-if="p.state.complete" class="absolute -bottom-0.5 -right-0.5 flex size-4 items-center justify-center rounded-full bg-ok text-panel ring-2 ring-panel" aria-label="Installed"><Check class="size-2.5" stroke-width="3" /></span>
            </span>
            <button class="min-w-0 flex-1 text-left" @click="open = false; go('suggested', { pack: p.id, cat: 'all' })">
              <p class="truncate text-sm hover:underline">{{ p.title }}</p>
              <p class="truncate text-[11px] text-muted">{{ p.files.length }} file(s) · {{ p.state.complete ? 'installed' : `${bytes(p.state.missing_bytes)} to download` }}</p>
            </button>
          </li>
        </ul>
        <div v-if="prog.active" class="mt-2">
          <div class="mb-1 flex justify-between text-xs text-fg2 tabular"><span>Downloading {{ prog.active }} file(s)</span><span>{{ Math.round(prog.value) }}%</span></div>
          <Bar :value="prog.value" label="Workflow download progress" />
        </div>
        <p v-for="t in prog.failed" :key="t.id" class="mt-1 text-[11px] text-danger-hover">{{ t.filename }}: {{ t.error }}</p>
      </section>

      <section v-if="status?.nodes?.length">
        <h3 class="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">Node packs</h3>
        <ul class="space-y-1 text-sm">
          <li v-for="n in status.nodes" :key="n.id" class="flex items-center gap-2">
            <component :is="n.installed ? Check : installed?.node_packs?.[n.id] === 'queued' ? LoaderCircle : Package" class="size-4" :class="[n.installed ? 'text-ok' : 'text-muted', !n.installed && installed?.node_packs?.[n.id] === 'queued' && 'animate-spin']" />
            <span class="flex-1">{{ n.title }}</span>
            <span v-if="installed?.node_packs?.[n.id] && !['queued', 'installed', 'already installed'].includes(installed.node_packs[n.id])" class="max-w-[50%] text-right text-[11px] text-danger-hover">{{ installed.node_packs[n.id] }}</span>
          </li>
        </ul>
        <p v-if="!status.manager" class="mt-1.5 flex items-center gap-1.5 text-[11px] text-warn"><CircleAlert class="size-3.5" /> ComfyUI-Manager isn't reachable{{ status.comfy ? '' : ' (is ComfyUI running?)' }}: node packs can't be checked or installed.</p>
      </section>
      <div v-if="nodesQueued && !missingNodes.length" class="flex flex-wrap items-center gap-2 rounded-lg bg-[color-mix(in_srgb,var(--warning)_12%,transparent)] px-3 py-2 text-xs text-warn">
        <CircleAlert class="size-4 shrink-0" /> New node packs are installed: restart ComfyUI to load them{{ embedded ? ' (this page reloads afterwards)' : '' }}.
        <Btn size="sm" class="ml-auto" :loading="restarting" @click="restart"><RotateCcw class="size-3.5" /> Restart ComfyUI</Btn>
      </div>
      <p v-if="ready" class="flex items-center gap-1.5 text-sm text-ok"><Check class="size-4" /> Everything is installed: open it and press Run.</p>
    </div>
    <template v-if="wf" #footer>
      <Btn variant="ghost" class="mr-auto" @click="downloadStarter(wf)"><FileJson class="size-4" /> .json</Btn>
      <Btn v-if="!ready" :variant="missingFiles.length || missingNodes.length ? 'secondary' : 'primary'" :loading="installing" :disabled="prog.active > 0" @click="install">
        <Download class="size-4" /> Install<span v-if="wf.state.missing_bytes" class="opacity-80">· {{ bytes(wf.state.missing_bytes) }}</span>
      </Btn>
      <Btn :variant="ready ? 'primary' : 'secondary'" @click="openStarter(app, wf)"><Play class="size-4" /> {{ ready ? 'Open in ComfyUI' : 'Open anyway' }}</Btn>
    </template>
  </Modal>
</template>
