"""API for the "Suggested by AI" catalog: packs, starter workflows, plan, install, save as bundle."""
import asyncio

from aiohttp import web

from . import catalog, manager, system
from .api import _body, _dl, _store, ok
from .downloads import ACTIVE
from .events import bus

routes = web.RouteTableDef()


@routes.get("/api/catalog")
async def catalog_overview(request):
    return ok(await asyncio.to_thread(catalog.overview, _store(request)))


def _picks(b):
    """The packs / workflows a plan or install body names: ids (any mix), packs, workflows."""
    as_list = lambda v: [v] if isinstance(v, str) else list(v or [])
    return {"ids": as_list(b.get("ids")), "packs": as_list(b.get("packs")), "workflows": as_list(b.get("workflows"))}


@routes.post("/api/catalog/plan")
async def catalog_plan(request):
    """Body: {ids?: [pack or workflow ids], packs?, workflows?, optional?: bool}. What installing them
    takes (files, sizes, what's on disk, node packs, disk / VRAM fit, warnings), downloading nothing."""
    b = await _body(request)
    active = [(t["category"], t["filename"]) for t in _dl(request).snapshot() if t["status"] in ACTIVE]
    result = await asyncio.to_thread(catalog.plan, _store(request), optional=bool(b.get("optional")), active=active, **_picks(b))
    gpus = await system.gpus()
    result["gpu"], result["fits_vram"] = None, None
    if gpus:
        vram = max(g["mem_total"] for g in gpus) / 2**30
        result["gpu"] = {"name": gpus[0]["name"], "vram_gb": round(vram, 1)}
        if result["vram_gb"]:
            result["fits_vram"] = vram + 0.5 >= result["vram_gb"]
            if not result["fits_vram"]:
                result["warnings"].append(f"Wants about {result['vram_gb']} GB of VRAM; this {gpus[0]['name']} has {vram:.0f} GB")
    return ok(result)


@routes.post("/api/catalog/install")
async def catalog_install(request):
    """Body: {ids?, packs?, workflows?, optional?, save_bundle?, auto_install?, to_comfy?, nodes? (default true)}.
    Queues every missing file and node pack in one call; returns the download tasks."""
    b = await _body(request)
    st = _store(request)
    result = await asyncio.to_thread(
        catalog.install, st, _dl(request), optional=bool(b.get("optional")), nodes=b.get("nodes", True) is not False,
        save_bundle=bool(b.get("save_bundle")), auto_install=bool(b.get("auto_install")), to_comfy=bool(b.get("to_comfy")),
        **_picks(b))
    if result.get("bundles"):
        bus.publish("bundles", {"changed": result["bundles"]})
        bus.publish("library", {"changed": []})
    return ok(result)


@routes.get("/api/catalog/progress")
async def catalog_progress(request):
    """?ids=<task id>,<task id> (default: running downloads and the last hour's). Download progress,
    the ComfyUI-Manager queue and the boot-time install (COMFORTABLE_INSTALL)."""
    ids = [i for i in (request.query.get("ids") or "").split(",") if i]
    result = await asyncio.to_thread(catalog.progress, _dl(request), ids or None)
    result["boot"] = dict(catalog.boot_state) or None
    return ok(result)


@routes.get("/api/catalog/nodes")
async def nodes_search(request):
    """?q=impact pack: node packs ComfyUI-Manager can install, with their state."""
    return ok(await asyncio.to_thread(catalog.search_nodes, request.query.get("q", ""), int(request.query.get("limit", 15))))


@routes.post("/api/catalog/nodes/install")
async def nodes_install(request):
    """Body: {ids: [Comfy Registry ids or GitHub URLs]}. Restart ComfyUI afterwards to load them."""
    b = await _body(request)
    ids = [str(i).strip() for i in b.get("ids") or [] if str(i).strip()]
    if not ids:
        raise ValueError("Name the node packs to install (registry ids or GitHub URLs)")
    results = await asyncio.to_thread(manager.install, ids)
    return ok({"node_packs": results, "restart_needed": any(v in ("queued", "installed") for v in results.values())})


@routes.post("/api/catalog/packs/{id}/install")
async def pack_install(request):
    """Body: {optional?: bool}. Queues the pack's files (and the packs it requires) and node packs."""
    b = await _body(request) if request.can_read_body else {}
    result = await asyncio.to_thread(catalog.install_packs, _store(request), _dl(request), [request.match_info["id"]],
                                     bool(b.get("optional")))
    return ok(result)


@routes.post("/api/catalog/packs/{id}/save")
async def pack_save(request):
    """Body: {auto_install?: bool}. Saves the pack's files to the library as a bundle."""
    b = await _body(request) if request.can_read_body else {}
    result = await asyncio.to_thread(catalog.save_pack, _store(request), request.match_info["id"], bool(b.get("auto_install")))
    bus.publish("bundles", {"changed": [result["bundle"]["id"]]})
    bus.publish("library", {"changed": []})
    return ok(result)


@routes.get("/api/catalog/workflows/{id}")
async def workflow_get(request):
    return ok(await asyncio.to_thread(catalog.workflow, _store(request), request.match_info["id"]))


@routes.get("/api/catalog/workflows/{id}/status")
async def workflow_status(request):
    return ok(await asyncio.to_thread(catalog.workflow_status, _store(request), request.match_info["id"]))


@routes.post("/api/catalog/workflows/{id}/install")
async def workflow_install(request):
    return ok(await asyncio.to_thread(catalog.install, _store(request), _dl(request), workflows=[request.match_info["id"]]))


@routes.post("/api/catalog/workflows/{id}/save")
async def workflow_save(request):
    """Body: {auto_install?: bool}. Saves every file the starter needs to the library as one bundle."""
    b = await _body(request) if request.can_read_body else {}
    result = await asyncio.to_thread(catalog.save_workflow, _store(request), request.match_info["id"], bool(b.get("auto_install")))
    bus.publish("bundles", {"changed": [result["bundle"]["id"]]})
    bus.publish("library", {"changed": []})
    return ok(result)


@routes.post("/api/catalog/workflows/{id}/comfy")
async def workflow_to_comfy(request):
    """Save the workflow into ComfyUI's workflows folder, so it opens from ComfyUI's Workflows sidebar."""
    return ok(await asyncio.to_thread(catalog.save_to_comfy, _store(request), request.match_info["id"]))
