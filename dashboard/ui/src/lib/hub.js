import { reactive } from 'vue'

// The hub (tools/comfortable_hub.py) runs on your PC or a small server: the phone signs in there with
// a PIN, rents and watches GPUs, and reaches the connected instance's dashboard through it (/api/...).
// On an instance (or inside ComfyUI) there is no hub and none of this shows.
export const hub = reactive({
  checked: false,
  on: false,
  authed: false,
  pinSet: true,
  state: null,   // instances, connected instance, the setup being watched
  catalog: null, // the catalog the hub ships with (for the start wizard)
})

async function request(method, path, body) {
  const res = await fetch(`hub/${path}`, {
    method,
    headers: method === 'GET' ? undefined : { 'Content-Type': 'application/json' },
    body: method === 'GET' ? undefined : JSON.stringify(body ?? {}),
  })
  const text = await res.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = null }
  if (res.status === 401 && data?.signin) window.dispatchEvent(new Event('comfortable:signin'))
  if (!res.ok) {
    const err = new Error(data?.error || `${res.status} ${res.statusText}`)
    err.data = data
    throw err
  }
  return data
}

export const hubApi = {
  get: (path) => request('GET', path),
  post: (path, body) => request('POST', path, body),
}

/** Is this page served by a hub? (An instance's dashboard answers hub/whoami with its web page.) */
export async function detectHub() {
  try {
    const res = await fetch('hub/whoami')
    const data = res.ok ? await res.json() : null
    if (data?.hub) Object.assign(hub, { on: true, authed: !!data.authed, pinSet: !!data.pin_set })
  } catch { /* not a hub */ }
  hub.checked = true
  return hub.on
}

export async function refreshHub(fresh = false) {
  hub.state = await hubApi.get(`state${fresh ? '?fresh=1' : ''}`)
  return hub.state
}

export async function loadHubCatalog() {
  if (!hub.catalog) hub.catalog = await hubApi.get('catalog')
  return hub.catalog
}

export const settingUp = (task) => !!task && ['starting', 'installing'].includes(task.state)
