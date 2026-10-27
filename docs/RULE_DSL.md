# Rule DSL v1

A rule is atomic: one selector, one property, one comparison and one evidence source. Multiple formatting requirements must be separate rules.

```json
{
  "rule_id": "body_size",
  "selector": "body",
  "property": "font.size_pt",
  "operator": "eq",
  "expected": 12,
  "tolerance": 0.1,
  "enabled": true,
  "severity": "ERROR",
  "fix_policy": "AUTO_WITH_APPROVAL",
  "source": {"source_type": "user_text", "reference": "guide_1", "quote": "正文 12 pt"}
}
```

Selectors are `body`, `heading_1`, `heading_2`, `heading_3`, `caption`, `table_text`, and `section`. Operators are `eq`, `in`, and `between`.

Properties cover `font.eastAsia`, `font.ascii`, `font.size_pt`, `font.bold`, paragraph alignment, first-line/left/right indentation, typed line spacing, space before/after, section margins and page dimensions. Line spacing distinguishes `MULTIPLE`, `EXACT`, and `AT_LEAST`; character indentation is not silently converted to points.

Pydantic validation enforces property/type/unit consistency and finite tolerances. Enabled rules require source reference and quote. Conflicting overlapping rules require explicit user resolution. Approval freezes a digest; subsequent edits create a new draft version.

Detection status, location status and repair eligibility are independent. UNKNOWN never counts as a confirmed violation or as a pass.
