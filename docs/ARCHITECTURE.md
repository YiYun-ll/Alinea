# Architecture

## Trust and data flow

Browser → FastAPI → private storage/SQL database → background job → OOXML parser/inspector → LibreOffice renderer → pdfplumber locator → browser PDF.js. Repair follows a separate approved path: selected Issues → digest-bound RepairPlan → package patch → G0–G4 integrity gates → candidate reparse/reinspect/render → G5 report → published Revision.

The original source and all revisions use opaque project-scoped storage keys and are never mounted as public static files. The bearer token is returned only when a project is created and stored server-side as SHA-256.

## Modules

- `alinea_contracts`: versioned Pydantic contracts shared across API, workers and document engines.
- `alinea_docx`: safe ZIP/OPC reads, story-part ElementRef index, effective style resolver, Rule DSL and Inspector.
- `alinea_mapping`: isolated LibreOffice conversion, render profiles and explicit-confidence PDF location mappings.
- `alinea_repair`: plan digests, preconditions, part-level OOXML patches and independent integrity diff.
- `alinea_agent`: bounded Agents SDK extraction with tracing disabled and deterministic evidence validation.
- `apps/api`: scoped REST/SSE, SQL persistence, local/RQ task dispatch, reports and audit.
- `apps/web`: Vue/Pinia workspaces and PDF.js viewport-based overlays.

## Lifecycle and rendering caches

The API lifespan initializes the dispatcher, recovers unfinished local jobs and starts project-expiry maintenance. Local jobs are reclaimed through the database's atomic `QUEUED → RUNNING` update. RQ running jobs are not automatically duplicated after an API restart; they become retryable failures for manual result checking. Only queued jobs can be cancelled. A retry creates a distinct job with a deterministic `retry:{original_job_id}` idempotency key; repair execution resolves the approved plan from the persisted request and rechecks project ownership, base revision, ruleset and plan digest.

Render cache keys cover DOCX SHA-256, profile and exporter configuration. Renderer version and font hashes are cached by file metadata within a worker process. Cache hits return the same PDF bytes and regenerate revision-bound location mappings rather than reusing stale coordinates. Project cleanup removes private project files; it does not bypass job or revision authorization.

Published preview storage keys also include the actual PDF SHA-256. Repeated identical exports reuse immutable bytes; different output from the same renderer profile receives a separate key. Inspection overlays request their exact PDF fingerprint, and preview lookup excludes inspections without a stored PDF.

An explicit `create_app(settings)` configuration is installed for the application's lifespan so service storage, document limits, model calls and dispatcher use the same settings as the API. Shutdown waits for running local tasks and cancels pending executor futures, leaving their queued database records available for startup recovery, before restoring the previous runtime settings. The current API process continues to use one shared database and runtime configuration.

## Inspection reuse and evidence identity

An Inspection is the immutable evidence input of an approved RepairPlan, not a disposable preview to overwrite on every click. Creation first validates the idempotency request digest, then reuses a matching active Job or successful Inspection by project, revision, ruleset digest and inspector version. Successful records and their issues, previews and warnings are not rebound or cleared by a repeat request or a repeated retry. A successful after-inspection without an inspection Job receives a real completed `CACHED` Job and status URL without dispatching work.

Page-mapping capability is checked before reuse; a structural-only result cannot masquerade as a mapped result. Failed jobs retain the explicit retry path, while a cancelled unfinished Inspection can be deliberately resubmitted without erasing successful history. New writes use nested transactions, with the database unique constraint as a final guard; a known conflict is resolved only after ownership, digest and mapping validation. Same-project API creation is serialized locally, but this does not claim multi-process race testing.

The web workflow exposes four stages: rules, inspection, repair and results. Approval of a ruleset can be followed immediately by inspection, but repair-plan approval and execution remain separate explicit actions. Refreshing results is a read-only GET path, not a new inspection.

## Consistency invariants

Inspection binds revision SHA + ruleset digest + inspector version. Preview binds revision SHA + renderer/font profile. Location binds preview SHA. Repair binds base revision + inspection + ruleset + old values + approved plan digest. A revision change invalidates old coordinates and plans; it never silently rebinds them.

G1–G4 failure blocks publication. G5 distinguishes PASS, PARTIAL, BLOCKED and INDETERMINATE. Page-count changes alone are not integrity failures because valid formatting changes can reflow a document.
