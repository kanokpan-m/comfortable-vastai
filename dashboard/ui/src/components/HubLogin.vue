<script setup>
import { ref } from 'vue'
import { LockKeyhole } from '@lucide/vue'
import { hubApi } from '../lib/hub'
import { useApp } from '../stores/app'
import logoUrl from '../assets/logo.png'
import Btn from './ui/Btn.vue'

const app = useApp()
const pin = ref('')
const busy = ref(false)
const error = ref('')

async function signIn() {
  if (!pin.value) return
  busy.value = true
  error.value = ''
  try {
    await hubApi.post('login', { pin: pin.value })
    pin.value = ''
    await app.init()
  } catch (e) {
    error.value = e.message
    pin.value = ''
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="flex min-h-full w-full items-center justify-center px-4 py-10">
    <form class="w-full max-w-xs rounded-2xl border border-subtle bg-panel p-6 text-center" @submit.prevent="signIn">
      <img :src="logoUrl" alt="" class="mx-auto size-14 object-contain" />
      <h1 class="mt-3 text-lg font-semibold">Comfortable</h1>
      <p class="mt-1 text-sm text-fg2">Enter your PIN to manage your GPUs.</p>
      <label class="mt-5 flex items-center gap-2 rounded-lg border border-subtle bg-card px-3 focus-within:border-primary">
        <LockKeyhole class="size-4 text-muted" />
        <input
          v-model="pin" type="password" inputmode="numeric" pattern="[0-9]*" autocomplete="current-password" maxlength="12"
          aria-label="PIN" placeholder="PIN" autofocus
          class="h-11 min-w-0 flex-1 bg-transparent text-center text-lg tracking-[0.4em] outline-none placeholder:tracking-normal"
        />
      </label>
      <p v-if="error" class="mt-3 text-sm text-danger-hover" role="alert">{{ error }}</p>
      <Btn type="submit" variant="primary" size="lg" class="mt-5 w-full" :loading="busy" :disabled="!pin">Sign in</Btn>
      <p class="mt-4 text-[11px] leading-relaxed text-muted">The PIN was set on the PC running the hub
        (<span class="font-mono">comfortable_hub.py --set-pin</span>).</p>
    </form>
  </div>
</template>
