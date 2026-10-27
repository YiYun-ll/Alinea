# Alinea MVP Design

## Architecture

Vue 3/Pinia/PDF.js calls FastAPI. FastAPI owns scoped access and persistence; background workers own parsing, rendering, mapping and repair. SQLAlchemy uses SQLite locally and PostgreSQL in Compose. Local thread execution and RQ share task functions. Files live outside public static directories under opaque project/revision IDs.

## Document boundary

`alinea_docx` performs safe ZIP/OPC reads, story-part ElementRef indexing, property-level effective style resolution and deterministic issue generation. `alinea_repair` applies only approved run/paragraph/section OOXML patches. It never rebuilds paragraphs or saves a whole new Document. `alinea_mapping` renders through isolated LibreOffice profiles and maps normalized text anchors to pdfplumber geometry with explicit rejection states.

## Consistency

Inspections bind revision SHA, approved ruleset digest and inspector version. Previews bind revision SHA and renderer/font profile; locations bind preview SHA. Plans bind all inspection inputs and expected old values. Approval is a server record. Execution keys and project locks prevent duplicate versions. G1–G4 are hard publication gates; G5 reports PASS, PARTIAL, BLOCKED or INDETERMINATE.

## AI boundary

`alinea_agent` sends guideline fragments only to the configured OpenAI-compatible model through Agents SDK with tracing disabled. Output receives schema, property/type, source and conflict validation plus one bounded correction. The model receives no shell, filesystem or repair tool. Manual/preset rules need no model.

## Web and accessibility

The workbench uses three asymmetric regions: issue navigation, paginated paper preview, and evidence/action detail. PDF.js viewport is the only overlay coordinate transform. DOM text and overlay layers sit above canvas. Native controls, keyboard navigation, semantic tables and responsive container layouts are required. The approved PRD palette and Chinese font constraints govern styling.

## Verification

Unit tests cover security, inheritance, operators, patches, gates and coordinates. API integration tests exercise ownership, job idempotency and the full lifecycle. At least 30 synthetic/deidentified fixtures carry golden manifests. Playwright and Desktop browser checks exercise real uploads, repairs and downloads. Reports distinguish measured results from unverified release targets.
