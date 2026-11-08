// Sample media of catalog packs and starters: each model's Civitai gallery (images and videos) and
// the thumbnails of ComfyUI's official templates (animated WebP for video templates). When none of
// them loads, images people generated with the model are fetched live from Civitai instead.
import { computed, reactive, ref, toValue, watch } from 'vue'

const MATURE = 4 // Civitai nsfwLevel: 1 PG, 2 PG-13, 4 R, 8 X, 16 XXX
const VIDEO_TASKS = ['i2v', 't2v', 'flf2v', 'lipsync', 'video']
export const isMature = (m) => (m?.nsfw_level || 1) >= MATURE
export const isVideo = (m) => m?.type === 'video'
export const isMoving = (m) => isVideo(m) || !!m?.animated
export const isVideoUrl = (url) => /\.(mp4|webm|mov|m4v)(\?|$)/i.test(url || '')

const CIVITAI = /^(https:\/\/image\.civitai\.com\/[^/]+\/[^/]+\/)([^/]+)\/([^/.]+)(\.[a-z0-9]+)?$/i
/** A smaller copy from Civitai's CDN: an image `width` wide, a video's first frame (`still`), or a
 *  smaller video. A URL that already asks for a first frame (`transcode=true,anim=false`, what the
 *  dashboard stores for video-only models) keeps asking for it. Other URLs come back unchanged. */
export function sized(m, { width = 450, still = false } = {}) {
  const url = m?.url || ''
  const hit = url.match(CIVITAI)
  if (!hit) return url
  const [, base, params, name, ext] = hit
  if (isVideo(m)) return still ? `${base}transcode=true,anim=false,width=${width}/${name}.jpeg` : `${base}transcode=true,width=${width}/${name}.mp4`
  const keep = params.split(',').filter((p) => /^(transcode|anim)=/.test(p))
  return `${base}${[...keep, `width=${width}`].join(',')}/${name}${ext || '.jpeg'}`
}

/** Media in the order to show it. With mature content allowed its samples come first, otherwise they
 *  are left out; `moving` puts videos and animations ahead of stills; `mix` takes one sample per
 *  model in turn, so a checkpoint + LoRA starter shows both. Same URL twice is dropped. */
export function ordered(items, { mature = false, moving = false, mix = false } = {}) {
  const seen = new Set()
  const list = (items || []).filter((m) => m?.url && (mature || !isMature(m)) && !seen.has(m.url) && seen.add(m.url))
  const rank = (m) => (mature && isMature(m) ? 0 : 2) + (moving && isMoving(m) ? 0 : 1)
  const sorted = list.map((m, i) => ({ m, i })).sort((a, b) => rank(a.m) - rank(b.m) || a.i - b.i).map(({ m }) => m)
  if (!mix) return sorted
  const out = []
  for (let i = 0; i < sorted.length;) {
    let j = i
    while (j < sorted.length && rank(sorted[j]) === rank(sorted[i])) j++
    const queues = new Map()
    for (const m of sorted.slice(i, j)) {
      const q = queues.get(m.pack_id || '') || []
      q.push(m)
      queues.set(m.pack_id || '', q)
    }
    const qs = [...queues.values()]
    while (qs.some((q) => q.length)) for (const q of qs) if (q.length) out.push(q.shift())
    i = j
  }
  return out
}

/** A pack's samples tagged with where they come from (older catalogs only have `preview`). */
function tagged(pack) {
  if (!pack) return []
  const items = pack.previews?.length ? pack.previews
    : pack.preview?.url ? [{ url: pack.preview.url, type: 'image', nsfw_level: pack.preview.nsfw_level || 1 }] : []
  return items.map((m) => ({ ...m, pack_id: pack.id, pack_title: pack.title }))
}

export const packMedia = (pack, { mature = false } = {}) => ordered(tagged(pack), { mature })

/** Caption of a sample: the model it comes from, "official template" for ComfyUI's own thumbnails,
 *  "made with it" for images people generated with the model. */
export const caption = (m) => [m?.pack_title, m?.source === 'template' && m?.pack_id ? 'official template' : '',
  m?.source === 'generation' ? 'made with it' : '', isMature(m) ? '18+' : ''].filter(Boolean).join(' · ')

/** What a starter makes: its models' samples (they lead for 18+ starters, whose official template
 *  thumbnail is a safe one) and the official template's thumbnail (credited to the model it shows). */
export function workflowSamples(wf, packsById, { mature = false } = {}) {
  if (!wf) return []
  const owner = (url) => (wf.packs || []).map((id) => packsById[id]).find((p) => p?.previews?.some((m) => m.url === url))
  const own = (wf.previews || []).map((m) => {
    const p = owner(m.url)
    return { ...m, pack_id: p?.id || '', pack_title: p?.title || 'Official ComfyUI template' }
  })
  const fromPacks = (wf.packs || []).flatMap((id) => tagged(packsById[id]))
  const moving = VIDEO_TASKS.includes(wf.task) || own.some(isMoving)
  return ordered(wf.nsfw ? [...fromPacks, ...own] : [...own, ...fromPacks], { mature, moving, mix: true })
}

/** The models a starter uses, as shown in its circles (shared text encoders / VAEs left out). */
export function workflowModels(wf, packsById) {
  const ids = [...new Set([...(wf?.packs || []), ...(wf?.all_packs || [])])]
  return ids.map((id) => packsById[id]).filter((p) => p && !p.component)
}

/** Samples of a catalog pack for the same file as `item` (a library item, search result or download),
 *  matched by Civitai version or by file name. */
export function catalogMatch(item, packs) {
  if (!item || !packs?.length) return []
  const vid = String(versionOf(item) || '')
  const name = (item.filename || '').split('/').pop().toLowerCase()
  const pack = packs.find((p) => !p.component && (p.files || []).some((f) =>
    (vid && String(f.civitai?.version_id || '') === vid) || (name && (f.filename || '').split('/').pop().toLowerCase() === name)))
  return tagged(pack)
}

// ---- Fallback: a model's Civitai gallery, and images people generated with it ---------------------
// Both from Civitai's public API (it allows browser requests). A prompt that could read as young rules
// a picture out; mature pictures, PG-13 generations and every picture of an 18+ model need a known
// prompt. Civitai's minor / real-person flags always rule one out. tools/catalog.py applies the same
// screen to the catalog's samples (YOUTHFUL: keep the two in step).
const LEVELS = { None: 1, Soft: 2, Mature: 4, X: 8 }
const YOUTHFUL = /\b(loli\w*|shota\w*|child\w*|kids?|toddler|underage|minor|preteen|teen\w*|baby|infant|young(?:er|est)?|youthful|little|tiny|petite|flat[ -]?chest\w*|small (?:breasts?|body|chest)|school\w*|student|uniform|chibi|cute girl|innocent|kawaii|aged? down|age[ -]?regression)\b/i
const fetched = new Map()
const levelOf = (im) => (typeof im.nsfwLevel === 'number' ? im.nsfwLevel : (LEVELS[im.nsfwLevel] ?? 99))

/** The Civitai model version of a pack, library item, search result or download, if any. */
export function versionOf(x) {
  const direct = x?.civitai?.version_id || (x?.files || []).map((f) => f.civitai?.version_id).find(Boolean)
  if (direct) return direct
  for (const url of [x?.url, x?.page_url, x?.page]) {
    const m = String(url || '').match(/civitai\.(?:com|red)\/(?:api\/download\/models\/(\d+)|models\/\d+[^?#]*\?(?:[^#]*&)?modelVersionId=(\d+))/)
    if (m) return m[1] || m[2]
  }
  return null
}

function screened(model, im, maxLevel, promptFor) {
  const level = levelOf(im)
  if (!im.url || im.minor || im.poi || level > maxLevel || level >= 32) return false
  const prompt = String(im.meta?.prompt || '').trim()
  if (prompt) return !YOUTHFUL.test(prompt)
  return !(level >= promptFor || model?.nsfw)
}
const asMedia = (model, im, source) => ({
  url: im.url, type: im.type === 'video' ? 'video' : 'image', width: im.width || 0, height: im.height || 0,
  nsfw_level: levelOf(im), source, pack_id: model.id, pack_title: model.title || model.name || '',
})
function cached(key, load) {
  if (!fetched.has(key)) fetched.set(key, load().catch(() => []))
  return fetched.get(key)
}

/** The pictures and clips the creator published with the model version (videos included). */
export function showcaseFor(model, { mature = false } = {}) {
  const vid = versionOf(model)
  if (!vid) return Promise.resolve([])
  return cached(`show:${vid}:${mature ? 1 : 0}`, () => fetch(`https://civitai.com/api/v1/model-versions/${vid}`, { credentials: 'omit', referrerPolicy: 'no-referrer' })
    .then((r) => (r.ok ? r.json() : { images: [] }))
    .then((d) => (d.images || []).filter((im) => screened(model, im, mature ? 16 : 2, MATURE)).slice(0, 8).map((im) => asMedia(model, im, 'gallery'))))
}

/** Images people generated with the model version (Civitai's public feed: safe ones only). */
export function generationsFor(model, { mature = false } = {}) {
  const vid = versionOf(model)
  if (!vid) return Promise.resolve([])
  const q = new URLSearchParams({ modelVersionId: vid, limit: '30', sort: 'Most Reactions', period: 'AllTime', nsfw: mature ? 'Soft' : 'None' })
  return cached(`gen:${vid}:${mature ? 1 : 0}`, () => fetch(`https://civitai.com/api/v1/images?${q}`, { credentials: 'omit', referrerPolicy: 'no-referrer' })
    .then((r) => (r.ok ? r.json() : { items: [] }))
    .then((d) => (d.items || []).filter((im) => screened(model, im, mature ? 2 : 1, 2)).slice(0, 8).map((im) => asMedia(model, im, 'generation'))))
}

// A host that keeps failing (blocked, down or hanging) with nothing loaded from it yet is skipped for
// every other sample at once, so cards reach a working fallback quickly instead of waiting out each
// dead link in turn. One missing file on a host that works doesn't count against it.
// A picture that neither loads nor fails this long on screen counts as failed: 10 s on a host nothing
// has loaded from yet, 25 s on one that works (a slow connection, not a dead link).
const STALL_MS = 10000
const SLOW_MS = 25000
const hosts = reactive({})
const hostOf = (url) => { try { return new URL(url).host } catch { return '' } }
export const stallFor = (url) => ((hosts[hostOf(url)]?.ok || 0) > 0 ? SLOW_MS : STALL_MS)
export function noteLoad(url, ok) {
  const h = hostOf(url)
  if (!h) return
  const s = hosts[h] || (hosts[h] = { ok: 0, bad: 0 })
  if (ok) s.ok++
  else s.bad++
}
const hostDead = (url) => { const s = hosts[hostOf(url)]; return !!s && s.ok === 0 && s.bad >= 2 }

/** Samples with a fallback chain, so there is always something to show: the given samples in order,
 *  skipping any that fail to load (and any on a host that is down); once none is left (or there were
 *  none), the models' Civitai galleries (videos too) and images people generated with them; once
 *  those are gone too, the list is empty and the caller shows its placeholder. `models` are catalog
 *  packs or anything with a Civitai version (library items, search results, downloads). With
 *  `eager` the galleries are added right away, for a details panel that lists them all.
 *  Arguments may be refs or getters. */
export function useSamples(items, models, mature, { eager = false } = {}) {
  const broken = ref(new Set())
  const extra = ref([])
  const asked = ref('')
  const list = computed(() => {
    const seen = new Set()
    return [...(toValue(items) || []), ...extra.value].filter((m) => m?.url && !broken.value.has(m.url) && !hostDead(m.url) && !seen.has(m.url) && seen.add(m.url))
  })
  const fail = (m) => { if (m?.url && !broken.value.has(m.url)) broken.value = new Set([...broken.value, m.url]) }
  const key = computed(() => `${(toValue(models) || []).map((p) => `${p?.id}@${versionOf(p) || ''}`).join()}:${toValue(mature) ? 1 : 0}`)
  watch(key, () => { extra.value = []; asked.value = '' }, { flush: 'sync' })
  watch([() => list.value.length, key], async ([n, k]) => {
    if ((n && !toValue(eager)) || asked.value === k) return
    asked.value = k
    const mat = !!toValue(mature)
    const ms = (toValue(models) || []).filter((p) => versionOf(p))
    const got = (await Promise.all(ms.map(async (p) => [...await showcaseFor(p, { mature: mat }), ...await generationsFor(p, { mature: mat })]))).flat()
    if (asked.value === k) extra.value = ordered(got, { mature: mat, moving: false })
  }, { immediate: true })
  return { list, fail }
}
