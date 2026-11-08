// Install state of catalog files, from the model scan and the live download queue.
import { computed } from 'vue'
import { pct } from './format'

// ComfyUI reads unet/ as diffusion_models/ and clip/ as text_encoders/.
const SAME = { unet: 'diffusion_models', clip: 'text_encoders' }
export const canon = (c) => SAME[c] || c
const base = (name) => (name || '').split('/').pop().toLowerCase()
const DONE = ['done', 'failed', 'cancelled']

export function useInstalled(app) {
  // Files by their path inside the folder: a starter looks for MiniMaxH3/x.safetensors, not any x.safetensors.
  const index = computed(() => {
    const idx = new Set()
    for (const [cat, files] of Object.entries(app.models || {})) {
      for (const f of files) idx.add(`${canon(cat)}/${f.name.toLowerCase()}`)
    }
    return idx
  })
  const fileInstalled = (f) => index.value.has(`${canon(f.category)}/${(f.filename || '').replace(/\\/g, '/').toLowerCase()}`)
  const taskFor = (f) => app.downloadList.find((t) => base(t.filename) === base(f.filename) && canon(t.category) === canon(f.category) && t.status !== 'cancelled')
  /** Download progress of a set of files: {active, value 0..100, failed: [tasks]}. */
  const progressOf = (files) => {
    const ts = (files || []).map(taskFor).filter(Boolean)
    return {
      active: ts.filter((t) => !DONE.includes(t.status)).length,
      value: pct(ts.reduce((s, t) => s + (t.done || 0), 0), ts.reduce((s, t) => s + (t.size || 0), 0)),
      failed: ts.filter((t) => t.status === 'failed'),
    }
  }
  return { fileInstalled, taskFor, progressOf }
}

export const MATURE_KEY = 'comfortable-show-mature-suggestions'
export function matureRevealed() {
  try { return sessionStorage.getItem(MATURE_KEY) === '1' } catch { return false }
}
export function revealMature(on) {
  try { sessionStorage.setItem(MATURE_KEY, on ? '1' : '0') } catch { /* private mode */ }
}
