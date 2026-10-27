# Benchmark method

The corpus contains 30 generated/deidentified cases: 5 normal, 8 single-property, 5 multi-property, 6 structural-edge and 6 high-risk inputs, plus a 10-page/10-error end-to-end example. Golden manifests record generator-known inputs, not unperformed human Microsoft Word verification.

- Precision = true confirmed issues / all confirmed issues, over supported and decidable rules.
- Recall = true confirmed issues / golden detectable issues.
- Location accuracy = correct high-confidence mappings / all high-confidence mappings; coverage is reported separately.
- Repair success = selected targets no longer violating after reinspection / executed selected targets.
- Fidelity = unexpected text/media changes across published candidates; the required count is zero.
- Protection = intentionally unsafe cases blocked / all unsafe test cases.

Reports must state OS, CPU, Python/Node/LibreOffice versions, font profile, sample scope, failures and elapsed times. UNKNOWN and skipped rules are excluded from precision denominators but disclosed separately. No value in this document is a measurement; see `reports/benchmark.md` for actual results. Iteration-two cache measurements use `scripts/benchmark_iteration2.py`, retain both empty-cache samples and verify cache-hit PDF hashes; see `reports/iteration-2.md`. For third-iteration workflow, inspection reuse and browser acceptance results, see `reports/iteration-3.md`.
