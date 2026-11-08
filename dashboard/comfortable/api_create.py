"""Routes of the Create screen (create.py): starter forms, runs, uploads from the phone, job results."""
from aiohttp import web

from . import create
from .api import _body, ok

routes = web.RouteTableDef()


@routes.get("/api/create")
async def create_list(request):
    return ok({"workflows": create.available()})


@routes.post("/api/create/upload")
async def create_upload(request):
    reader = await request.multipart()
    field = await reader.next()
    while field is not None and field.name != "file":
        field = await reader.next()
    if field is None:
        raise ValueError("Send the file as multipart field 'file'")
    return ok(await create.upload(field))


@routes.get("/api/create/jobs")
async def create_jobs(request):
    ids = [i for i in (request.query.get("ids") or "").split(",") if i]
    return ok({"jobs": await create.jobs(ids[:50])})


@routes.get("/api/create/view")
async def create_view(request):
    kind, body = await create.view(dict(request.query))
    return web.Response(body=body, content_type=kind.split(";")[0], headers={"Cache-Control": "private, max-age=3600"})


@routes.post("/api/create/cancel")
async def create_cancel(request):
    b = await _body(request)
    return ok(await create.cancel(str(b.get("prompt_id") or "")))


@routes.get("/api/create/{id}")
async def create_form(request):
    return ok(create.form(request.match_info["id"], await create.object_info()))


@routes.post("/api/create/{id}/run")
async def create_run(request):
    b = await _body(request)
    return ok(await create.run(request.match_info["id"], b.get("values") or {}, b.get("loras") or [],
                               b.get("count") or 1, bool(b.get("fixed_seed"))))
