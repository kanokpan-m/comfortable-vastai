// Installing and opening starter workflows (Workflows screen).
import { api } from './api'
import { bridge, comfyUrl, embedded } from './bridge'

export async function installStarter(app, wf) {
  const r = await api.post(`catalog/workflows/${wf.id}/install`)
  const nodes = Object.entries(r.node_packs || {})
  const queuedNodes = nodes.filter(([, v]) => v === 'queued').length
  const problems = [...r.errors.map((e) => `${e.filename}: ${e.error}`),
    ...nodes.filter(([, v]) => !['queued', 'installed', 'already installed'].includes(v)).map(([k, v]) => `${k}: ${v}`)]
  const parts = [r.queued && `${r.queued} download(s)`, queuedNodes && `${queuedNodes} node pack(s)`].filter(Boolean)
  app.toast(parts.length ? `Installing ${parts.join(' and ')} for ${wf.title}` : `${wf.title}: everything is installed`, problems.length ? 'error' : parts.length ? 'info' : 'success', problems.join('; '))
  return r
}

/** Open a starter workflow in ComfyUI: inside ComfyUI's sidebar directly, else in a ComfyUI tab
 *  (it is also saved to ComfyUI's Workflows → Comfortable folder). Falls back to a .json download. */
export async function openStarter(app, wf) {
  const href = embedded ? '' : comfyUrl(app.boot.comfy_port)
  // Open the tab now, inside the click, so pop-up blockers allow it; point it at ComfyUI once saved.
  const tab = href ? window.open('about:blank', '_blank') : null
  try {
    const full = await api.get(`catalog/workflows/${wf.id}`)
    if (embedded) {
      bridge.openWorkflow(full.graph, full.title)
      return
    }
    let saved = ''
    try { saved = (await api.post(`catalog/workflows/${wf.id}/comfy`)).path } catch { /* ComfyUI is offline */ }
    if (tab) {
      tab.opener = null
      tab.location = `${href}?comfortable_open=${encodeURIComponent(wf.id)}`
      app.toast(`Opening ${full.title} in ComfyUI`, 'success', saved ? `Also saved in ComfyUI: Workflows → ${saved}` : '')
    } else if (saved) {
      app.toast(`Saved to ComfyUI: Workflows → ${saved}`, 'success', 'Open ComfyUI and pick it in the Workflows sidebar.')
    } else {
      downloadJson(full)
      app.toast('ComfyUI is not reachable: downloaded the workflow instead', 'info', 'Drop the .json onto ComfyUI to open it.')
    }
  } catch (e) {
    tab?.close()
    app.toast(e.message, 'error')
  }
}

export async function downloadStarter(wf) {
  downloadJson(await api.get(`catalog/workflows/${wf.id}`))
}

function downloadJson(full) {
  const blob = new Blob([JSON.stringify(full.graph, null, 1)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `${full.title.replace(/[\\/:*?"<>|]+/g, ' ').trim()}.json`
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(a.href), 2000)
}
