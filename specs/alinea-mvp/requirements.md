# Alinea MVP Requirements

## Scope

Alinea v0.2-mvp is a local, single-user web workspace for verifiable DOCX formatting inspection and approved repair. The original DOCX is immutable. AI interprets guidelines only; deterministic code inspects and patches document copies. P1/P2 collaboration, billing, OCR, online editing, and complex-object repair are excluded.

## Acceptance criteria

1. When a user uploads a DOCX, the system shall validate its size, ZIP/OPC structure and input risks before parsing or rendering, and shall store the original immutably.
2. When a user supplies a preset, guideline text or text PDF, the system shall produce sourced editable draft rules; when AI is unavailable, preset/manual flows shall remain usable.
3. When rules conflict or lack required evidence, the system shall require explicit resolution and shall not approve automatic repair silently.
4. When approved rules are inspected, the system shall report supported font, size, bold, alignment, line spacing, indentation, paragraph spacing and section/page deviations with provenance or UNKNOWN.
5. When a PDF preview exists, the system shall bind issue overlays to that exact revision and preview SHA; ambiguous or unavailable locations shall not produce guessed rectangles.
6. When a user selects issues, the system shall create a digest-bound plan showing before/after values and impact, and shall require separate approval before execution.
7. When a repair executes, the system shall revalidate base revision, ruleset digest, anchors and old values, and shall modify only whitelisted formatting in a new DOCX copy.
8. When a candidate is produced, the system shall run package, full-text, media/relationship, XML-whitelist and reinspection gates before assigning a verification status.
9. When any hard integrity gate fails, the system shall not publish the candidate as a verified revision or alter the original.
10. When a revision is ready, the user shall be able to download the DOCX, preview PDF and JSON/Markdown evidence report, including unresolved and skipped checks.
11. When jobs execute, the system shall persist status, progress, errors and audit events, enforce idempotency and permit status recovery after reconnection.
12. When a project/resource is accessed, the system shall verify its scoped token and expiry; deletion shall invalidate prior resource URLs and remove derived files.
13. When the product is accepted, real browser and API flows shall pass and quantitative results shall cite actual fixtures, versions and failures rather than targets presented as measurements.
