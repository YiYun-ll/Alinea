# Security and privacy

## Untrusted inputs

DOCX, guideline PDF/text and model output are untrusted. Upload checks cover size, ZIP entries, total uncompressed size, compression ratio, traversal, required OPC parts and malformed XML. XML parsers disable external entities and network access. External-resource relationships and high-risk objects are detected before conversion.

## Repair authorization

The model has no write tool. Execution requires a server-side approval record and revalidates base SHA, ruleset digest, inspection, text/context anchors and expected old values. Only exact run/paragraph/section formatting properties are patched. Text, media, relationships and unauthorized parts receive independent integrity checks. Successful Inspection evidence is not overwritten by repeated checks or retries; existing retry jobs return before any entity reset. Page-mapping capability must be proven before a result is reused.

## Access and retention

A random 32-byte project token grants one anonymous workspace. Only its SHA-256 is persisted. Every nested resource is checked against its project and expiry. Downloads use authenticated streams, not public paths. Projects default to a 24-hour TTL; a background task checks expiry every 15 minutes. Deletion removes original, derived and report files and invalidates old URLs. Job retry and cancellation use the same project-scoped authorization; retry does not bypass the original approval or create a second execution for repeated retry requests.

## Model disclosure

Only guideline text needed for extraction is sent to the configured provider. Full DOCX content is not sent by default. Agents SDK tracing is disabled. Logs and audit events record IDs, hashes, status and durations rather than full sensitive text. No real credential belongs in `.env.example`, frontend code, reports or CI.

## Rendering and deployment

LibreOffice uses isolated working/profile directories and timeouts. Public deployment requires a low-privilege container, resource limits and restricted renderer networking. Optional Gotenberg must be at least 8.34.0 and digest-pinned; it is not the default local renderer. Do not distribute restricted fonts.
