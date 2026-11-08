<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  Rocket, Play, Square, Trash2, Link2, Check, CircleAlert, ChevronLeft, Search, Clock, Download, Cpu, MapPin,
  Gauge, EyeOff, LoaderCircle, Plus, Wallet, HardDrive,
} from '@lucide/vue'
import { hub, hubApi, refreshHub, loadHubCatalog, settingUp } from '../lib/hub'
import { matureRevealed, revealMature } from '../lib/catalog'
import { workflowSamples } from '../lib/media'
import { go } from '../lib/route'
import { useApp } from '../stores/app'
import Btn from '../components/ui/Btn.vue'
import Tag from '../components/ui/Tag.vue'
import Bar from '../components/ui/Bar.vue'
import Modal from '../components/ui/Modal.vue'
import SampleMedia from '../components/SampleMedia.vue'

const app = useApp()
const usd = (n, d = 3) => `$${Number(n || 0).toFixed(d)}`
const hours = (h) => (h < 1 ? `${Math.max(1, Math.round(h * 60))} min` : `${h.toFixed(1)} h`)

// ---- live state: instances and the setup being watched --------------------------------------------------
let timer = null
const loadError = ref('')
async function poll() {
  clearTimeout(timer)
  try {
    await refreshHub()
    loadError.value = ''
  } catch (e) {
    loadError.value = e.message
  }
  timer = setTimeout(poll, settingUp(hub.state?.task) ? 3000 : 15000)
}
onMounted(poll)
onUnmounted(() => clearTimeout(timer))
const task = computed(() => hub.state?.task || null)
const instances = computed(() => hub.state?.instances || [])
const connectedId = computed(() => hub.state?.connected?.instance_id)
// A GPU just got connected (setup ready, or Connect): load the whole dashboard through it.
watch(() => hub.state?.connected?.label, (now, before) => { if (now && now !== before && app.hubOnly) app.reinit() })

const STEPS = [['starting', 'Renting and starting'], ['installing', 'Host check and models'], ['ready', 'Ready']]
const stepIndex = computed(() => ({ starting: 0, installing: 1, ready: 2 }[task.value?.state] ?? -1))
const installPct = computed(() => {
  const i = task.value?.install
  return i?.total_gb ? (100 * i.done_gb) / i.total_gb : 0
})

// ---- confirmations: rent, stop, start, destroy -----------------------------------------------------------
const confirm = ref({ open: false, kind: '', title: '', text: '', danger: false, run: null, busy: false, error: '' })
function ask(kind, title, text, run, danger = false) {
  confirm.value = { open: true, kind, title, text, danger, run, busy: false, error: '' }
}
async function doConfirm() {
  confirm.value.busy = true
  confirm.value.error = ''
  try {
    await confirm.value.run()
    confirm.value.open = false
  } catch (e) {
    confirm.value.error = e.message
  } finally {
    confirm.value.busy = false
  }
}
function instanceAction(inst, action) {
  const name = `${inst.gpu} (instance ${inst.id}, ${usd(inst.price_per_hour)}/h)`
  const texts = {
    stop: `Stop ${name}? The GPU stops billing; its disk (models, outputs) is still billed, and the GPU may be taken by someone else meanwhile.`,
    start: `Start ${name} again? Billing resumes at about ${usd(inst.price_per_hour)}/h.`,
    destroy: `Destroy ${name}? This deletes its disk (models and outputs) for good and stops all billing.`,
  }
  ask(action, `${action[0].toUpperCase()}${action.slice(1)} instance`, texts[action], async () => {
    await hubApi.post(`instances/${inst.id}`, { action, confirm: true })
    await refreshHub(true)
    poll()
  }, action === 'destroy')
}
const connecting = ref(0)
async function connectTo(inst) {
  connecting.value = inst.id
  try {
    await hubApi.post(`instances/${inst.id}`, { action: 'connect' })
    await refreshHub()
  } catch (e) {
    app.toast(e.message, 'error')
  } finally {
    connecting.value = 0
  }
}
async function dismiss() {
  await hubApi.post('task/dismiss').catch(() => {})
  await refreshHub()
}

// ---- the wizard: what -> which workflows -> options -> offers -------------------------------------------------
const step = ref(0) // 0 = sessions, 1 = what, 2 = workflows, 3 = GPUs
const revealed = ref(matureRevealed())
const showMature = computed(() => !!app.settings?.show_nsfw || revealed.value)
const cat = ref(null)
const catError = ref('')
async function startWizard() {
  step.value = 1
  if (!cat.value) {
    try { cat.value = await loadHubCatalog() } catch (e) { catError.value = e.message }
  }
}
const packsById = computed(() => Object.fromEntries((cat.value?.packs || []).map((p) => [p.id, p])))
const kinds = computed(() => {
  const wfs = cat.value?.workflows || []
  return (cat.value?.categories || [])
    .filter((c) => showMature.value || !c.mature)
    .map((c) => ({ ...c, count: wfs.filter((w) => (w.categories || []).includes(c.id) && (showMature.value || !w.nsfw)).length }))
    .filter((c) => c.count > 0)
})
const hiddenMature = computed(() => (showMature.value ? 0 : (cat.value?.categories || []).filter((c) => c.mature).length))
const kind = ref('')
const picked = ref([])
const list = computed(() => (cat.value?.workflows || [])
  .filter((w) => (w.categories || []).includes(kind.value) && (showMature.value || !w.nsfw)))
const pickedWfs = computed(() => (cat.value?.workflows || []).filter((w) => picked.value.includes(w.id)))
const totals = computed(() => ({
  gb: pickedWfs.value.reduce((s, w) => s + (w.download_gb || 0), 0),
  vram: Math.max(0, ...pickedWfs.value.map((w) => w.vram_gb || 0)),
  key: pickedWfs.value.some((w) => w.needs_civitai_key),
}))
function chooseKind(id) {
  kind.value = id
  step.value = 2
}
function toggle(id) {
  picked.value = picked.value.includes(id) ? picked.value.filter((x) => x !== id) : [...picked.value, id]
}
const samples = (w) => workflowSamples(w, packsById.value, { mature: showMature.value }).slice(0, 6)
const modelsOf = (w) => (w.packs || []).map((id) => packsById.value[id]).filter(Boolean)

const opts = ref({ hours: 3, autostop: 30, maxPrice: '', rank: 'value' })
const offers = ref(null)
const searching = ref(false)
const offerError = ref('')
async function findGpus() {
  step.value = 3
  searching.value = true
  offerError.value = ''
  offers.value = null
  try {
    offers.value = await hubApi.post('offers', {
      setups: picked.value, hours: opts.value.hours, rank: opts.value.rank,
      max_price: opts.value.maxPrice ? Number(opts.value.maxPrice) : undefined,
    })
  } catch (e) {
    offerError.value = e.message
  } finally {
    searching.value = false
  }
}
function rentAsk(o) {
  const what = pickedWfs.value.map((w) => w.title).join(', ') || 'nothing extra'
  const stop = opts.value.autostop ? ` It stops by itself after ${opts.value.autostop} min with nothing running.` : ''
  ask('rent', 'Rent this GPU', `Rent ${o.gpu} ${o.vram_gb} GB in ${o.where || 'an unknown place'} for about ${usd(o.cost_per_hour)}/h? `
    + `It sets up ${what} (${totals.value.gb.toFixed(1)} GB), ready in about ${o.ready_minutes} min.${stop}`, async () => {
    try {
      await hubApi.post('rent', { offer_id: o.id, cost_per_hour: o.cost_per_hour, confirm: true, autostop_minutes: opts.value.autostop || null })
    } catch (e) {
      if (e.data?.refresh) findGpus()
      throw e
    }
    step.value = 0
    picked.value = []
    await refreshHub(true)
    poll()
  })
}
const back = () => { step.value = Math.max(0, step.value - 1) }
</script>

<template>
  <div class="mx-auto max-w-3xl px-4 py-4 md:px-6">
    <!-- 0: sessions ------------------------------------------------------------------------------------- -->
    <template v-if="step === 0">
      <header class="mb-4 flex items-center gap-3">
        <div class="flex size-10 items-center justify-center rounded-xl bg-primary-soft text-primary-hover"><Rocket class="size-5" /></div>
        <div class="min-w-0 flex-1">
          <h1 class="text-base font-semibold">GPU sessions</h1>
          <p class="text-xs text-fg2">Rent a GPU set up for what you want to make, then create from here.</p>
        </div>
      </header>
      <p v-if="loadError || hub.state?.vast_error" class="mb-3 flex items-start gap-2 rounded-lg bg-[color-mix(in_srgb,var(--destructive-hover)_14%,transparent)] px-3 py-2 text-sm text-danger-hover">
        <CircleAlert class="mt-0.5 size-4 shrink-0" /> {{ loadError || hub.state.vast_error }}
      </p>

      <!-- The setup being watched -->
      <section v-if="task" class="mb-4 rounded-xl border border-subtle bg-panel p-4" aria-live="polite">
        <div class="flex items-start gap-3">
          <div class="min-w-0 flex-1">
            <p class="font-medium">{{ task.gpu || `Instance ${task.instance_id}` }}
              <span v-if="task.price_per_hour" class="text-fg2">· {{ usd(task.price_per_hour) }}/h</span></p>
            <p class="mt-0.5 text-sm" :class="task.state === 'failed' ? 'text-danger-hover' : 'text-fg2'">{{ task.phase }}</p>
          </div>
          <Tag :tone="task.state === 'ready' ? 'ok' : task.state === 'failed' ? 'danger' : 'primary'">
            <LoaderCircle v-if="settingUp(task)" class="size-3 animate-spin" />{{ task.state }}
          </Tag>
        </div>
        <ol v-if="task.state !== 'failed' && task.state !== 'cancelled'" class="mt-3 flex gap-2 text-[11px]">
          <li v-for="([id, label], i) in STEPS" :key="id" class="flex flex-1 items-center gap-1.5" :class="i <= stepIndex ? 'text-fg' : 'text-muted'">
            <span class="flex size-4 shrink-0 items-center justify-center rounded-full" :class="i < stepIndex || task.state === 'ready' ? 'bg-ok text-white' : i === stepIndex ? 'bg-primary text-white' : 'bg-hover'">
              <Check v-if="i < stepIndex || task.state === 'ready'" class="size-3" />
            </span>{{ label }}
          </li>
        </ol>
        <div v-if="task.state === 'installing' && task.install?.total_gb" class="mt-3">
          <Bar :value="installPct" label="Model downloads" />
          <p class="mt-1 text-xs text-fg2">{{ task.install.done_gb.toFixed(1) }} / {{ task.install.total_gb.toFixed(1) }} GB
            · {{ task.install.speed_mb_s }} MB/s<span v-if="task.install.eta_seconds"> · about {{ Math.max(1, Math.round(task.install.eta_seconds / 60)) }} min left</span></p>
        </div>
        <Bar v-else-if="settingUp(task)" indeterminate class="mt-3" label="Setting up" />
        <p v-if="task.host_advice || task.advice" class="mt-3 rounded-lg bg-[color-mix(in_srgb,var(--warning)_12%,transparent)] px-3 py-2 text-xs text-warn">{{ task.host_advice || task.advice }}</p>
        <p v-if="task.install?.failed?.length" class="mt-2 text-xs text-danger-hover">Failed downloads: {{ task.install.failed.join(', ') }}
          (a Civitai file usually needs your Civitai API key in Settings)</p>
        <div class="mt-3 flex flex-wrap gap-2">
          <template v-if="task.state === 'ready'">
            <Btn variant="primary" @click="go('create', { w: task.setups?.[0] })"><Play class="size-4" /> Start creating</Btn>
            <Btn variant="ghost" @click="dismiss">Dismiss</Btn>
          </template>
          <Btn v-else-if="!settingUp(task)" variant="ghost" @click="dismiss">Dismiss</Btn>
        </div>
      </section>

      <!-- Instances -->
      <section class="mb-4">
        <h2 class="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Your instances</h2>
        <p v-if="!hub.state" class="flex items-center gap-2 py-6 text-sm text-fg2"><LoaderCircle class="size-4 animate-spin" /> Looking at your Vast account…</p>
        <p v-else-if="!instances.length" class="rounded-xl border border-dashed border-subtle px-4 py-6 text-center text-sm text-fg2">No GPU rented right now.</p>
        <ul v-else class="space-y-2">
          <li v-for="i in instances" :key="i.id" class="rounded-xl border border-subtle bg-panel p-3">
            <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
              <p class="min-w-0 flex-1 font-medium">{{ i.gpu }} <span class="text-xs text-muted">#{{ i.id }}</span></p>
              <Tag :tone="i.status === 'running' ? 'ok' : 'neutral'">{{ i.status || 'loading' }}</Tag>
              <Tag v-if="connectedId === i.id" tone="primary"><Link2 class="size-3" /> connected</Tag>
            </div>
            <p class="mt-1 flex flex-wrap gap-x-3 text-xs text-fg2">
              <span>{{ usd(i.price_per_hour) }}/h</span>
              <span v-if="i.uptime_hours != null"><Clock class="inline size-3" /> {{ hours(i.uptime_hours) }}</span>
              <span v-if="i.spent != null"><Wallet class="inline size-3" /> {{ usd(i.spent, 2) }} so far</span>
            </p>
            <div class="mt-2 flex flex-wrap gap-2">
              <Btn v-if="i.status === 'running' && connectedId !== i.id" size="sm" :loading="connecting === i.id" @click="connectTo(i)"><Link2 class="size-3.5" /> Connect</Btn>
              <Btn v-if="connectedId === i.id" size="sm" variant="primary" @click="go('create')"><Play class="size-3.5" /> Create</Btn>
              <Btn v-if="i.status === 'running'" size="sm" variant="ghost" @click="instanceAction(i, 'stop')"><Square class="size-3.5" /> Stop</Btn>
              <Btn v-else-if="i.status === 'exited' || i.status === 'stopped'" size="sm" variant="ghost" @click="instanceAction(i, 'start')"><Play class="size-3.5" /> Start</Btn>
              <Btn size="sm" variant="ghost" class="text-danger-hover" @click="instanceAction(i, 'destroy')"><Trash2 class="size-3.5" /> Destroy</Btn>
            </div>
          </li>
        </ul>
      </section>

      <Btn variant="primary" size="lg" class="w-full" :disabled="settingUp(task)" @click="startWizard"><Plus class="size-4" /> New GPU session</Btn>

      <!-- Everything made on the GPUs, copied to this PC -->
      <button v-if="hub.state?.backup" class="mt-4 flex w-full items-center gap-3 rounded-xl border border-subtle bg-panel p-3 text-left hover:border-border" @click="go('saved')">
        <HardDrive class="size-5 shrink-0 text-fg2" />
        <span class="min-w-0 flex-1">
          <span class="block text-sm font-medium">Saved on your PC</span>
          <span class="block truncate text-xs text-fg2">{{ hub.state.backup.count }} files<template v-if="hub.state.backup.copying"> · copying {{ hub.state.backup.copying.split('/').pop() }}</template>
            <template v-else-if="hub.state.backup.error"> · {{ hub.state.backup.error }}</template></span>
        </span>
      </button>
    </template>

    <!-- 1: what to make ------------------------------------------------------------------------------------------ -->
    <template v-else-if="step === 1">
      <header class="mb-4 flex items-center gap-2">
        <Btn variant="ghost" size="icon" aria-label="Back" @click="back"><ChevronLeft class="size-5" /></Btn>
        <h1 class="text-base font-semibold">What do you want to make?</h1>
      </header>
      <p v-if="catError" class="text-sm text-danger-hover">{{ catError }}</p>
      <p v-else-if="!cat" class="flex items-center gap-2 py-6 text-sm text-fg2"><LoaderCircle class="size-4 animate-spin" /> Loading…</p>
      <template v-else>
        <div class="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <button v-for="c in kinds" :key="c.id" class="flex flex-col items-start gap-1 rounded-xl border border-subtle bg-panel p-3 text-left hover:border-border" @click="chooseKind(c.id)">
            <span class="text-xl" aria-hidden="true">{{ c.icon }}</span>
            <span class="text-sm font-medium">{{ c.title }}</span>
            <span class="text-[11px] text-muted">{{ c.count }} workflow{{ c.count === 1 ? '' : 's' }}</span>
          </button>
        </div>
        <p v-if="hiddenMature" class="mt-3 flex flex-wrap items-center gap-2 text-xs text-fg2">
          <EyeOff class="size-3.5" /> Mature (18+) workflows are hidden.
          <Btn size="sm" variant="link" @click="revealed = true; revealMature(true)">Show them for this session</Btn>
        </p>
      </template>
    </template>

    <!-- 2: which workflows + options --------------------------------------------------------------------------------- -->
    <template v-else-if="step === 2">
      <header class="mb-3 flex items-center gap-2">
        <Btn variant="ghost" size="icon" aria-label="Back" @click="back"><ChevronLeft class="size-5" /></Btn>
        <div class="min-w-0">
          <h1 class="text-base font-semibold">Pick workflows</h1>
          <p class="text-xs text-fg2">Every model they need is downloaded while the GPU starts. Pick more than one if you like.</p>
        </div>
      </header>
      <ul class="space-y-2 pb-44">
        <li v-for="w in list" :key="w.id">
          <button class="flex w-full gap-3 rounded-xl border bg-panel p-2 text-left transition-colors" :class="picked.includes(w.id) ? 'border-primary' : 'border-subtle hover:border-border'"
                  :aria-pressed="picked.includes(w.id)" @click="toggle(w.id)">
            <SampleMedia :items="samples(w)" :packs="modelsOf(w)" :mature="showMature" :seed="w.id" :width="240" play="never" class="size-20 shrink-0 overflow-hidden rounded-lg sm:size-24" />
            <span class="min-w-0 flex-1">
              <span class="flex items-start gap-2">
                <span class="min-w-0 flex-1 text-sm font-medium">{{ w.title }}</span>
                <span class="flex size-5 shrink-0 items-center justify-center rounded-full border" :class="picked.includes(w.id) ? 'border-primary bg-primary text-white' : 'border-subtle'">
                  <Check v-if="picked.includes(w.id)" class="size-3" />
                </span>
              </span>
              <span class="mt-0.5 line-clamp-2 block text-xs text-fg2">{{ w.summary }}</span>
              <span class="mt-1 flex flex-wrap gap-1">
                <Tag><Download class="size-3" />{{ w.download_gb.toFixed(1) }} GB</Tag>
                <Tag v-if="w.vram_gb"><Cpu class="size-3" />{{ w.vram_gb }} GB VRAM</Tag>
                <Tag v-if="w.nsfw" tone="danger">18+</Tag>
              </span>
            </span>
          </button>
        </li>
      </ul>
      <!-- Options and next, pinned above the tab bar -->
      <div class="fixed inset-x-0 bottom-[calc(56px+env(safe-area-inset-bottom))] z-20 border-t border-stroke bg-panel px-4 py-3 md:bottom-0 md:left-[72px]">
        <div class="mx-auto max-w-3xl">
          <div class="mb-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-fg2">
            <label class="flex items-center gap-1.5">Hours
              <select v-model.number="opts.hours" class="h-7 rounded-md border border-subtle bg-card px-1.5 text-fg">
                <option v-for="h in [1, 2, 3, 5, 8]" :key="h" :value="h">{{ h }}</option>
              </select>
            </label>
            <label class="flex items-center gap-1.5">Stop when idle
              <select v-model.number="opts.autostop" class="h-7 rounded-md border border-subtle bg-card px-1.5 text-fg">
                <option :value="15">15 min</option><option :value="30">30 min</option><option :value="60">1 h</option><option :value="0">never</option>
              </select>
            </label>
            <label class="flex items-center gap-1.5">Max $/h
              <input v-model="opts.maxPrice" inputmode="decimal" placeholder="any" class="h-7 w-16 rounded-md border border-subtle bg-card px-1.5 text-fg" />
            </label>
            <label class="flex items-center gap-1.5">Pick by
              <select v-model="opts.rank" class="h-7 rounded-md border border-subtle bg-card px-1.5 text-fg">
                <option value="value">best value</option><option value="speed">fastest</option>
              </select>
            </label>
          </div>
          <div class="flex items-center gap-3">
            <p class="min-w-0 flex-1 text-xs text-fg2">
              <template v-if="picked.length">{{ picked.length }} picked · {{ totals.gb.toFixed(1) }} GB<span v-if="totals.vram"> · {{ totals.vram }} GB VRAM</span>
                <span v-if="totals.key" class="block text-warn">Needs your Civitai API key (Settings) for some files</span></template>
              <template v-else>Pick at least one workflow</template>
            </p>
            <Btn variant="primary" :disabled="!picked.length" @click="findGpus"><Search class="size-4" /> Find GPUs</Btn>
          </div>
        </div>
      </div>
    </template>

    <!-- 3: GPU offers -------------------------------------------------------------------------------------------------- -->
    <template v-else-if="step === 3">
      <header class="mb-3 flex items-center gap-2">
        <Btn variant="ghost" size="icon" aria-label="Back" @click="step = 2"><ChevronLeft class="size-5" /></Btn>
        <div class="min-w-0 flex-1">
          <h1 class="text-base font-semibold">Best GPUs right now</h1>
          <p class="text-xs text-fg2">Real cost per hour (GPU, disk and the host's download fee spread over {{ opts.hours }} h), speed from your benchmarks.</p>
        </div>
        <Btn variant="ghost" size="icon" aria-label="Search again" :disabled="searching" @click="findGpus"><Search class="size-4" /></Btn>
      </header>
      <p v-if="searching" class="flex items-center gap-2 py-8 text-sm text-fg2"><LoaderCircle class="size-4 animate-spin" /> Checking offers on Vast…</p>
      <p v-else-if="offerError" class="rounded-lg bg-[color-mix(in_srgb,var(--destructive-hover)_14%,transparent)] px-3 py-2 text-sm text-danger-hover">{{ offerError }}</p>
      <template v-else-if="offers">
        <p v-if="!offers.offers?.length" class="py-6 text-sm text-fg2">{{ offers.hint || 'No offer matches right now.' }}</p>
        <ul class="space-y-2">
          <li v-for="(o, n) in offers.offers" :key="o.id" class="rounded-xl border border-subtle bg-panel p-3">
            <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
              <p class="min-w-0 flex-1 font-medium">{{ o.gpu }} <span class="text-fg2">{{ o.vram_gb }} GB</span>
                <Tag v-if="n === 0" tone="primary" class="ml-1">best pick</Tag></p>
              <p class="text-base font-semibold tabular">{{ usd(o.cost_per_hour) }}<span class="text-xs font-normal text-fg2">/h</span></p>
            </div>
            <p class="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-fg2">
              <span v-if="o.where"><MapPin class="inline size-3" /> {{ o.where }}</span>
              <span><Clock class="inline size-3" /> ready in ~{{ o.ready_minutes }} min</span>
              <span><Gauge class="inline size-3" /> {{ o.images_per_hour }} img/h{{ o.speed_measured ? '' : ' (est.)' }}</span>
              <span v-if="o.host_perf && o.host_perf < 0.95" class="text-warn">host {{ Math.round(o.host_perf * 100) }}%</span>
            </p>
            <Btn variant="primary" class="mt-2 w-full sm:w-auto" @click="rentAsk(o)">Rent for {{ usd(o.cost_per_hour) }}/h</Btn>
          </li>
        </ul>
        <p v-if="offers.hidden" class="mt-3 text-[11px] text-muted">Left out: {{ Object.entries(offers.hidden).filter(([, n]) => n).map(([k, n]) => `${n} ${k}`).join(', ') }} (slow, failed host checks, expensive bandwidth…)</p>
      </template>
    </template>

    <Modal v-model:open="confirm.open" :title="confirm.title">
      <div class="space-y-3 text-sm">
        <p>{{ confirm.text }}</p>
        <p v-if="confirm.error" class="text-danger-hover" role="alert">{{ confirm.error }}</p>
      </div>
      <template #footer>
        <Btn variant="ghost" @click="confirm.open = false">Cancel</Btn>
        <Btn :variant="confirm.danger ? 'danger' : 'primary'" :loading="confirm.busy" @click="doConfirm">
          {{ confirm.kind === 'rent' ? 'Rent' : confirm.kind[0]?.toUpperCase() + confirm.kind.slice(1) }}
        </Btn>
      </template>
    </Modal>
  </div>
</template>
