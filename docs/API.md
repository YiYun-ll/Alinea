# REST and SSE contract

All business routes are under `/api/v1`. JSON uses snake_case and timestamps are RFC3339 UTC. Project creation returns a scoped bearer token once; subsequent calls use `Authorization: Bearer <token>`. Nested revision/job/inspection/plan resources are rechecked against the token's project.

Errors have `{error:{code,message,request_id,retryable,details}}`. Long operations return 202 and a job/status URL. `Idempotency-Key` is required for inspections and repair execution. Unsafe stale input returns 409 rather than rebinding a plan.

## Main routes

| Method | Path | Purpose |
|---|---|---|
| POST | `/projects` | Create a 24-hour anonymous project |
| GET/DELETE | `/projects/{id}` | Read or delete a project and its derived files |
| POST | `/demo` | Create a real example DOCX/preset workspace |
| POST | `/projects/{id}/documents` | Multipart DOCX validation and immutable original |
| POST | `/projects/{id}/guidelines` | Preset/text JSON or text-PDF multipart |
| POST | `/projects/{id}/rules/extract` | Queue preset or bounded-Agent extraction |
| GET | `/projects/{id}/rules` | Latest RuleSet |
| GET/POST/PUT | `/projects/{id}/rulesets[/{ruleset}]` | Read/create/edit draft versions |
| PUT | `/projects/{id}/rules/{ruleset}/approve` | Approve an exact digest |
| POST | `/projects/{id}/inspections` | Create or reuse a revision/rule-compatible inspection with optional page mapping |
| GET | `/inspections/{id}` | Inspection, summary, issues and render metadata |
| GET | `/inspections/{id}/issues` | Paginated/filterable issues |
| GET | `/inspections/{id}/locations` | Preview-bound location mappings |
| POST | `/projects/{id}/repair-plans` | Create a selected-issue plan |
| GET | `/repair-plans/{id}` | Read plan and resulting revision |
| POST | `/repair-plans/{id}/approve` | Approve the exact plan digest |
| POST | `/repair-plans/{id}/execute` | Queue the unique approved execution |
| GET | `/jobs/{id}` | Authoritative job status, including `retryable` for failed jobs |
| POST | `/jobs/{id}/retry` | Create or return the idempotent retry of a safely retryable failure; 202 |
| POST | `/jobs/{id}/cancel` | Cancel a job only while it is still queued |
| GET | `/jobs/{id}/events` | SSE with `Last-Event-ID` recovery |
| GET | `/projects/{id}/jobs` | Project job history |
| GET | `/projects/{id}/audit-events` | Redacted audit events |
| GET | `/projects/{id}/revisions` | Immutable revision history |
| GET | `/revisions/{id}/preview` | Authenticated revision-specific PDF |
| GET | `/revisions/{id}/report[?format=markdown]` | JSON or Markdown verification report |
| GET | `/revisions/{id}/download` | Authorized original/published DOCX |
| GET | `/revisions/{id}/artifacts` | Real downloadable artifact links |

## Inspection reuse and job history

`POST /projects/{id}/inspections` creates or reuses an inspection and includes `reused` in the response. The existing `202 + job_id + inspection_id + status_url + events_url` fields remain. `reused=false` means a new InspectionRecord; `reused=true` means an existing record was reused, including an immediately completed `CACHED` Job for an after-inspection with no inspection Job. A 202 response can therefore already be SUCCEEDED; clients must read the returned status rather than wait blindly for execution.

The Idempotency-Key's request digest is always checked. A matching active job or successful Inspection is reused without rewriting its issues, summary, preview, warnings or any RepairPlan evidence. Mapping capability must be compatible with the request, otherwise a 409 is returned. Failed jobs retain the explicit retry path; cancelled unfinished work can be resubmitted safely. New records use nested transactions and the unique constraint as a fallback, with matching validation before any reuse. Repeating a completed retry returns the existing retry Job before any entity reset.

Project job history reads Jobs once and their events once more, grouped in memory. It preserves the single-Job response shape and avoids one event query per listed Job.

## SSE

Events use `id`, `event`, and JSON `data`. `job.queued`, `job.started`, `job.progress`, `job.completed`, `job.failed`, `job.cancelled`, and `job.recovered` are persisted. Reconnect with `Last-Event-ID`; if the event window is missed, the job status endpoint remains authoritative. Percentages are stage estimates, not a duration guarantee.

Retry is allowed only for a failed job whose failure event is explicitly retryable. Repeating a retry of the same original job returns the same retry job. Repair retries use the persisted plan ID from the original request, then revalidate ownership, approval, base revision and plan digest; a fresh job ID never rebinds a plan. Cancellation is safe only before the atomic claim starts execution. A running job cannot be cancelled through this endpoint.

At startup, local queued/running jobs are recovered and dispatched. In RQ mode, queued jobs are left to the external queue and previously running jobs become retryable `WORKER_RESTARTED` failures to avoid silent duplicate execution. Project expiry is checked every 15 minutes by API lifespan maintenance.
