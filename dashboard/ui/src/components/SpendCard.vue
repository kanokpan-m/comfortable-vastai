<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Wallet } from '@lucide/vue'
import { api } from '../lib/api'
import { useApp } from '../stores/app'

// What renting has cost, recorded by every instance's dashboard (synced through MongoDB).
const app = useApp()
const days = ref(30)
const s = ref(null)
const load = async () => { try { s.value = await api.get('spend', { days: days.value }) } catch {} }
let timer
onMounted(() => { load(); timer = setInterval(load, 5 * 60 * 1000) })
onUnmounted(() => clearInterval(timer))
const usd = (x) => `$${(x || 0).toFixed(2)}`
const today = computed(() => s.value?.per_day?.find((d) => d.day === new Date().toLocaleDateString('sv')))
const here = computed(() => s.value?.instances?.find((i) => String(i.id) === String(app.system?.vast?.id)))
</script>

<template>
  <section class="rounded-xl border border-subtle bg-panel p-4">
    <header class="mb-3 flex flex-wrap items-center gap-2">
      <h2 class="flex items-center gap-2 font-medium"><Wallet class="size-4 text-fg2" /> Spending</h2>
      <div class="ml-auto flex rounded-md border border-subtle bg-card p-0.5" role="radiogroup" aria-label="Period">
        <button v-for="d in [7, 30, 90]" :key="d" role="radio" :aria-checked="days === d" class="h-6 rounded px-2 text-xs font-medium"
                :class="days === d ? 'bg-selected text-fg' : 'text-fg2 hover:text-fg'" @click="days = d; load()">{{ d }} days</button>
      </div>
    </header>
    <p v-if="!s" class="text-xs text-muted">Loading…</p>
    <template v-else>
      <dl class="mb-3 grid grid-cols-3 gap-3 text-xs">
        <div><dt class="text-muted">Last {{ days }} days</dt><dd class="text-lg font-medium text-fg tabular">{{ usd(s.total.all) }}</dd>
          <dd class="text-muted">{{ s.total.hours.toFixed(1) }} h · {{ usd(s.total.bandwidth) }} bandwidth</dd></div>
        <div><dt class="text-muted">Today</dt><dd class="text-lg font-medium text-fg tabular">{{ usd((today?.cost || 0) + (today?.bandwidth || 0)) }}</dd></div>
        <div><dt class="text-muted">This instance</dt><dd class="text-lg font-medium text-fg tabular">{{ usd((here?.cost || 0) + (here?.bandwidth || 0)) }}</dd>
          <dd v-if="here" class="text-muted">{{ here.hours.toFixed(1) }} h</dd></div>
      </dl>
      <div v-if="s.workflows.length" class="space-y-1 text-xs">
        <p class="text-muted">Per workflow (GPU-busy time)</p>
        <p v-for="w in s.workflows.slice(0, 6)" :key="w.workflow" class="flex gap-3">
          <span class="min-w-0 flex-1 truncate text-fg2">{{ w.workflow }}</span>
          <span class="text-muted tabular">{{ w.hours.toFixed(1) }} h</span>
          <span class="w-14 text-right text-fg tabular">{{ usd(w.cost) }}</span>
        </p>
      </div>
      <p class="mt-3 text-[11px] text-muted">GPU + disk at Vast's price while instances run, plus estimated bandwidth. Storage billed while stopped isn't included. <code>comfortable spend</code> shows the same on your computer.</p>
    </template>
  </section>
</template>
