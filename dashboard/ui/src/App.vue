<script setup>
import { computed, defineAsyncComponent, onMounted } from 'vue'
import { onKeyStroke } from '@vueuse/core'
import { BookMarked, Sparkles, Workflow, Compass, Wand2, Download, Images, Activity, Settings, WifiOff, CircleAlert, Clock, ArrowUpCircle, Rocket, WandSparkles, HardDrive } from '@lucide/vue'
import { api } from './lib/api'
import { useApp } from './stores/app'
import { route, go } from './lib/route'
import { embedded } from './lib/bridge'
import { hub, settingUp } from './lib/hub'
import HubLogin from './components/HubLogin.vue'
import logoUrl from './assets/logo.png'
import StatusBar from './components/StatusBar.vue'
import ViewState from './components/ViewState.vue'
import CommandPalette from './components/CommandPalette.vue'
import Toasts from './components/ui/Toasts.vue'
import Btn from './components/ui/Btn.vue'

const app = useApp()
onMounted(() => app.init())
// The hub's sign-in ran out (or the PIN changed): ask for it again.
window.addEventListener('comfortable:signin', () => { app.hubLogin = true })
onKeyStroke((e) => (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k', (e) => { e.preventDefault(); app.paletteOpen = !app.paletteOpen })

// Each screen is its own chunk; show a spinner while it loads and a reload prompt if it can't.
const lazy = (loader) => defineAsyncComponent({ loader, loadingComponent: ViewState, errorComponent: ViewState, delay: 150, timeout: 30000 })
const views = {
  start: lazy(() => import('./views/StartView.vue')),
  create: lazy(() => import('./views/CreateView.vue')),
  saved: lazy(() => import('./views/SavedView.vue')),
  library: lazy(() => import('./views/LibraryView.vue')),
  suggested: lazy(() => import('./views/SuggestedView.vue')),
  workflows: lazy(() => import('./views/WorkflowsView.vue')),
  discover: lazy(() => import('./views/DiscoverView.vue')),
  fix: lazy(() => import('./views/FixView.vue')),
  downloads: lazy(() => import('./views/DownloadsView.vue')),
  gallery: lazy(() => import('./views/GalleryView.vue')),
  monitor: lazy(() => import('./views/MonitorView.vue')),
  settings: lazy(() => import('./views/SettingsView.vue')),
}
const pages = computed(() => [
  { id: 'create', label: 'Create', icon: WandSparkles },
  { id: 'library', label: 'Library', icon: BookMarked },
  { id: 'suggested', label: 'Suggested', icon: Sparkles },
  { id: 'workflows', label: 'Workflows', icon: Workflow },
  { id: 'discover', label: 'Discover', icon: Compass },
  { id: 'fix', label: 'Fixer', icon: Wand2 },
  { id: 'downloads', label: 'Downloads', icon: Download, count: app.activeDownloads.length },
  { id: 'gallery', label: 'Gallery', icon: Images, dot: app.galleryTick > 0 && route.value.view !== 'gallery' },
  { id: 'monitor', label: 'Monitor', icon: Activity, dot: app.health?.score === 'poor' },
  { id: 'settings', label: 'Settings', icon: Settings, dot: !!app.update?.available },
])
// Through a hub the Start screen (GPU sessions) comes first; it's all there is until a GPU is connected.
const nav = computed(() => {
  if (!hub.on) return pages.value
  const start = { id: 'start', label: 'Start', icon: Rocket, dot: settingUp(hub.state?.task) }
  const saved = { id: 'saved', label: 'Saved', icon: HardDrive }
  return app.hubOnly ? [start, saved] : [start, ...pages.value.slice(0, 1), saved, ...pages.value.slice(1)]
})
const current = computed(() => (app.hubOnly && !['start', 'saved'].includes(route.value.view) ? 'start' : route.value.view))
const stopsIn = computed(() => Math.max(1, Math.round((app.autostop?.stops_in || 0) / 60)))
const snooze = () => api.post('autostop/snooze').then((s) => (app.autostop = s)).catch((e) => app.toast(e.message, 'error'))
</script>

<template>
  <HubLogin v-if="app.hubLogin" class="h-full overflow-y-auto" />
  <div v-else class="flex h-full" :class="embedded && 'embedded'">
    <!-- Desktop sidebar, styled like ComfyUI's side toolbar -->
    <nav v-if="!embedded" class="hidden w-[72px] shrink-0 flex-col items-center gap-1 border-r border-stroke bg-panel py-3 md:flex" aria-label="Main">
      <button class="mb-3 flex size-11 items-center justify-center rounded-lg transition-transform hover:scale-105" title="Comfortable · Ctrl+K for commands" aria-label="Comfortable: open the command palette" @click="app.paletteOpen = true">
        <img :src="logoUrl" alt="" class="size-11 object-contain" />
      </button>
      <a
        v-for="n in nav" :key="n.id" :href="`#/${n.id}`"
        class="relative flex w-14 flex-col items-center gap-1 rounded-lg py-2 text-[10px] font-medium transition-colors"
        :class="current === n.id ? 'bg-hover text-fg' : 'text-fg2 hover:bg-hover hover:text-fg'"
        :aria-current="current === n.id ? 'page' : undefined"
      >
        <component :is="n.icon" class="size-5" />
        {{ n.label }}
        <span v-if="n.count" class="absolute right-1.5 top-1 min-w-4 rounded-full bg-primary px-1 text-center text-[10px] leading-4 text-white tabular">{{ n.count }}</span>
        <span v-else-if="n.dot" class="absolute right-3 top-1.5 size-2 rounded-full bg-primary-hover" />
      </a>
    </nav>

    <div class="flex min-w-0 flex-1 flex-col">
      <StatusBar v-if="!app.hubOnly" />
      <!-- Auto-stop warning -->
      <!-- Inside ComfyUI the extension shows this banner itself. -->
      <div v-if="!embedded && (app.autostop?.warned || app.autostop?.stopping)" class="flex flex-wrap items-center gap-2 border-b border-stroke bg-[color-mix(in_srgb,var(--warning)_14%,transparent)] px-4 py-2 text-xs text-warn" role="alert">
        <Clock class="size-4" />
        <span class="flex-1">{{ app.autostop.stopping ? 'Instance is idle and stopping now…' : `Instance idle: it will stop in about ${stopsIn} min to save money.` }}</span>
        <Btn v-if="!app.autostop.stopping" size="sm" variant="primary" @click="snooze">Keep running</Btn>
      </div>
      <!-- Update available -->
      <div v-else-if="app.update?.available && route.view !== 'settings'" class="flex items-center gap-2 border-b border-stroke bg-primary-soft px-4 py-1.5 text-xs">
        <ArrowUpCircle class="size-4 text-primary-hover" />
        <span class="min-w-0 flex-1 truncate">Comfortable update available: {{ app.update.latest?.message }}</span>
        <Btn size="sm" variant="link" @click="go('settings', { section: 'update' })">Review</Btn>
      </div>
      <div v-if="!app.connected && app.ready && !app.hubOnly" class="flex items-center gap-2 border-b border-stroke bg-[color-mix(in_srgb,var(--warning)_12%,transparent)] px-4 py-1.5 text-xs text-warn">
        <WifiOff class="size-3.5" /> Live updates disconnected, reconnecting…
      </div>
      <main class="min-h-0 flex-1 overflow-y-auto pb-20" :class="!embedded && 'md:pb-0'">
        <div v-if="app.bootError" class="mx-auto mt-16 max-w-md px-4">
          <div class="flex items-start gap-3 rounded-xl border border-subtle bg-panel p-5">
            <CircleAlert class="mt-0.5 size-5 shrink-0 text-danger-hover" />
            <div>
              <p class="font-medium">Can't reach the Comfortable backend</p>
              <p class="mt-1 text-sm text-fg2">{{ app.bootError }}</p>
            </div>
          </div>
        </div>
        <component :is="views[current]" v-else-if="app.ready" :key="current" />
        <ViewState v-else />
      </main>
    </div>

    <!-- Phone (and ComfyUI sidebar) tab bar -->
    <nav class="fixed inset-x-0 bottom-0 z-30 flex border-t border-stroke bg-panel pb-[env(safe-area-inset-bottom)]" :class="!embedded && 'md:hidden'" aria-label="Main">
      <a
        v-for="n in nav" :key="n.id" :href="`#/${n.id}`"
        class="relative flex min-w-0 flex-1 flex-col items-center gap-0.5 py-2 text-[10px]"
        :class="current === n.id ? 'text-fg' : 'text-muted'"
        :aria-current="current === n.id ? 'page' : undefined"
        :aria-label="n.label" :title="n.label"
      >
        <component :is="n.icon" class="size-5" />
        <span class="hidden truncate min-[480px]:block">{{ n.label }}</span>
        <span v-if="n.count" class="absolute right-[calc(50%-18px)] top-1 min-w-4 rounded-full bg-primary px-1 text-center text-[10px] leading-4 text-white tabular">{{ n.count }}</span>
        <span v-else-if="n.dot" class="absolute right-[calc(50%-14px)] top-1.5 size-2 rounded-full bg-primary-hover" />
      </a>
    </nav>
    <CommandPalette />
    <Toasts />
  </div>
</template>
