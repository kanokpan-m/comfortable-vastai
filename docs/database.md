# Database (schema v3)

Comfortable keeps its data in one MongoDB database, `comfortable` (`COMFORTABLE_MONGO_DB` to
change it), shared by every instance, with a local SQLite copy on each instance
(`/workspace/.comfortable/comfortable.db`). Without `MONGO_URI` the SQLite copy is all there is.

## Collections

| Collection | Written by | One document per |
|---|---|---|
| `settings` | dashboard | setting: `{id: <key>, value}` (tokens, show_nsfw, concurrency, auto-stop, backup) |
| `library` | dashboard | saved model file |
| `bundles` | dashboard | named group of library items |
| `stars` | dashboard | starred gallery file `{id: <path>, at}` |
| `benchmarks` | dashboard | GPU benchmark result |
| `hosts` | dashboard | Vast machine's host-health verdict (the rent CLI skips poor hosts) |
| `catalog_categories` | `tools/catalog.py publish` | "Suggested by AI" category |
| `catalog_packs` | `tools/catalog.py publish` | suggested pack: every file one setup needs |
| `catalog_workflows` | `tools/catalog.py publish` | starter workflow, with its ComfyUI graph |
| `meta` | both | `{id: "schema", version: 3}`, `{id: "catalog", version, published_at, counts}` |

Every document has:

- `id`: unique in its collection (unique index `id_unique`)
- `v`: the schema version it was written with (3)
- `mtime`: epoch seconds of its last write (index `mtime`; drives incremental sync)

Extra indexes: `library.bundle_ids`, `library.category`, `library.origin`, `bundles.origin`,
`catalog_packs.categories`, `catalog_workflows.categories`.

### library

```
{id, name, url, source: civitai|hf|url,
 category,            ComfyUI folder; unet/clip are stored as diffusion_models/text_encoders
 filename,            may include a sub-folder the workflow expects: MiniMaxH3/model.safetensors
 aliases: [],         other file names workflows use for this model (picked in the Fixer)
 size, sha256, preview, preview_mature,
 trigger_words: [], base_model, type (Checkpoint, LORA, ...), nsfw, tags: [],
 page_url, civitai: {model_id, version_id, file_id}, hf: {repo, revision, path},
 bundle_ids: [], auto_install, notes,
 origin: manual | fixer | catalog:<pack id> | migrated,
 source_missing?, meta_checked_at?, created_at, updated_at}
```

### bundles

```
{id, name, icon, description, tags: [], auto_install,
 origin: user | catalog:<pack id> | catalog-workflow:<workflow id>, created_at, updated_at}
```

Membership lives on `library.bundle_ids` (multikey index), so a model can be in several bundles.
A bundle saved from a suggestion has the id `cat-<pack id>` (with the files of the packs it
requires), one saved from a starter workflow `wf-<workflow id>` (every file it needs), so saving
it again on another instance updates the same bundle.

### catalog_packs / catalog_workflows / catalog_categories

See [catalog/README.md](../catalog/README.md). The dashboard uses whichever is newer: the copy
in this database or the one shipped in `catalog/` with the installed version.

## Sync

Reads and writes only touch SQLite. A background thread:

1. pushes pending local writes (`bulk_write` of `ReplaceOne` upserts per collection). A delete is
   pushed as a tombstone `{id, deleted: true, mtime}`, so other instances drop the document too.
2. pulls documents whose `mtime` is past the last pull, minus 5 minutes for clock skew between
   instances, every 15 s or right after a write.
3. every 30 minutes (and at start) runs a full check: ids and mtimes only, then fetches the
   documents that differ and drops local copies the database no longer has. Tombstones older
   than 30 days are purged then.

A write made while a push is in flight keeps its pending row (pending rows carry a sequence
number), so nothing is lost when the same document changes twice in quick succession.

## Older layouts

v3 added `mtime`/`v` on every document, tombstones, indexes, normalised folders,
`type`/`nsfw`/`tags`/`origin` on library items and the catalog collections. Data in earlier
layouts was copied into this database once; the dashboard has no code for them. A local SQLite
copy written by a v2 dashboard is reshaped in place when v3 first opens it.
