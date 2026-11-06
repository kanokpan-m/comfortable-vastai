// Talking to ComfyUI when the dashboard runs inside its sidebar (see comfyui_ext/web/comfortable.js).
import { ref } from 'vue'

export const embedded = new URLSearchParams(location.search).has('embed') && window.parent !== window
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
}
