// Talking to ComfyUI when the dashboard runs inside its sidebar (see comfyui_ext/web/comfortable.js).
import { ref } from 'vue'

export const embedded = new URLSearchParams(location.search).has('embed') && window.parent !== window

/** Where ComfyUI is for this browser: the same server when the dashboard is opened through
 *  ComfyUI's /comfortable/ proxy, else the public port Vast mapped to ComfyUI (same portal host). */
export function comfyUrl(comfyPort) {
  if (location.pathname.startsWith('/comfortable/')) return `${location.origin}/`
  return comfyPort ? `${location.protocol}//${location.hostname}:${comfyPort}/` : ''
}
export const parentWorkflow = ref(null)  // { workflow, name } of the workflow open in ComfyUI
export const parentPlan = ref(null)      // fix plan the extension computed when the workflow loaded

function send(type, extra = {}) {
  if (embedded) window.parent.postMessage({ type, ...extra }, location.origin)
}

if (embedded) {
  window.addEventListener('message', (e) => {
    if (e.origin !== location.origin) return
    if (e.data?.type === 'comfortable:workflow') parentWorkflow.value = { workflow: e.data.workflow, name: e.data.name }
    if (e.data?.type === 'comfortable:plan') parentPlan.value = e.data.plan
  })
}

export const bridge = {
  requestWorkflow: () => send('comfortable:get-workflow'),
  refreshModels: () => send('comfortable:refresh-models'),
  reanalyze: () => send('comfortable:reanalyze'),
  reloadComfy: () => send('comfortable:reload'),
  openWorkflow: (workflow, name) => send('comfortable:open-workflow', { workflow, name }),
}
