# Implementation Plan

- [x] 1. Establish monorepo, contracts, persistence and reproducible runtimes. _Requirements: 1, 11, 12_
- [x] 2. Implement safe DOCX index, effective styles and style/security spikes. _Requirements: 1, 4_
- [x] 3. Implement sourced versioned rules, conflicts and eight-property inspection. _Requirements: 2, 3, 4_
- [x] 4. Implement approved package patches, integrity gates and idempotent revisions. _Requirements: 6, 7, 8, 9_
- [x] 5. Implement LibreOffice rendering, PDF mapping and ambiguity degradation. _Requirements: 5_
- [x] 6. Implement scoped API, jobs/SSE, Agent extraction and evidence reports. _Requirements: 2, 10, 11, 12_
- [x] 7. Implement Vue wizard, rule review, inspection workbench, repair/results/history. _Requirements: 2, 4, 5, 6, 10, 11_
- [x] 8. Run 30-fixture benchmark, golden E2E, security/fidelity checks and browser acceptance. _Requirements: 13_
- [x] 9. Deliver README, support matrix, SBOM, CI and Compose; mark unverified release items explicitly. _Requirements: 13_

## Iteration 2 — lifecycle, performance and commercial UI refinement

- [x] 10. Add scoped idempotent job retry, safe queued cancellation, startup recovery and RQ-compatible worker dispatch; verify repair retries retain the approved plan. _Requirements: 6, 8, 10, 11_
- [x] 11. Add expiry maintenance and metadata-aware renderer/font caches; preserve revision, preview and coordinate bindings. _Requirements: 1, 5, 11, 12_
- [x] 12. Refine the editorial homepage, native dialogs, progress, Toast, route/list transitions and mobile navigation; support system and persisted reduced-motion preferences with fallbacks. _Requirements: 2, 4, 5, 6, 10_
- [x] 13. Verify real failure/retry repair, document fidelity, downloads, 390px layouts, reduced motion, full backend/frontend suites and actual cache timings. _Requirements: 13_
- [x] 14. Update API, architecture, security and benchmark documentation; record current mypy debt and perform relevant secret/authorization review in `reports/iteration-2.md`. _Requirements: 11, 12, 13_

## Iteration 3 — simplified workflow and progressive commercial workspace

- [x] 15. Reuse active/successful inspections with mapping and idempotency validation; preserve successful evidence on repeated retries and batch job-event history queries. _Requirements: 2, 5, 6, 8, 10, 11, 12_
- [x] 16. Add four-stage workflow navigation, valid default presets, automatic naming and progressive disclosure for advanced settings, evidence and rendering details. _Requirements: 2, 4, 5, 6, 10, 11_
- [x] 17. Combine rules approval with inspection setup, add read-only refresh and failure recovery, summarize repairs and split results into conclusion/comparison/download views with natural transitions and reduced-motion support. _Requirements: 2, 4, 5, 6, 7, 10, 13_
- [x] 18. Verify real preset upload, desktop and 390px repair flows, actual downloads, immutable retry evidence and query counts; update API, architecture and `reports/iteration-3.md` with measured results and remaining limitations. _Requirements: 11, 12, 13_
