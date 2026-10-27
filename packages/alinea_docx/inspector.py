from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from alinea_contracts.errors import AlineaError
from alinea_contracts.models import (
    DocumentSnapshot,
    ElementRef,
    FormatRule,
    InspectionResult,
    InspectionSummary,
    Issue,
    LocationMapping,
    ParagraphNode,
    RepairEligibility,
    ResolvedProperty,
    RuleSet,
    RunNode,
    RunRange,
    SectionNode,
    ValueEvidence,
)

from alinea_docx.rules import (
    _coerce_actual_value,
    _evidence_unit,
    _matches,
    compute_ruleset_digest,
    validate_rule,
)

DEFAULT_INSPECTOR_VERSION = "1.0.0"


@dataclass(frozen=True)
class _Target:
    element_ref: ElementRef
    effective: Mapping[str, ResolvedProperty]
    unsupported_features: tuple[str, ...]
    excerpt: str


def _is_excluded(rule: FormatRule, paragraph: ParagraphNode, run: RunNode | None = None) -> bool:
    if not rule.exclusions:
        return False
    candidates = {paragraph.semantic_role}
    if paragraph.p_style_id:
        candidates.add(paragraph.p_style_id)
    if paragraph.inside_table:
        candidates.update({"inside_table", "table"})
    if run is not None and run.character_style_id:
        candidates.add(run.character_style_id)
    features = paragraph.unsupported_features + (run.unsupported_features if run else [])
    candidates.update(features)
    folded = {candidate.casefold() for candidate in candidates}
    return any(exclusion.casefold() in folded for exclusion in rule.exclusions)


def _contains_east_asian_script(text: str) -> bool:
    return any(
        not character.isspace() and unicodedata.east_asian_width(character) in {"W", "F"}
        for character in text
    )


def _contains_ascii_script(text: str) -> bool:
    return any(character.isascii() and character.isalnum() for character in text)


def _run_matches_script(property_name: str, text: str) -> bool:
    if property_name == "font.eastAsia":
        return _contains_east_asian_script(text)
    if property_name == "font.ascii":
        return _contains_ascii_script(text)
    return True


def _run_element_ref(paragraph: ParagraphNode, run: RunNode) -> ElementRef:
    return paragraph.element_ref.model_copy(
        update={"run_range": RunRange(start=run.index, end=run.index + 1)}
    )


def _paragraph_targets(paragraph: ParagraphNode, rule: FormatRule) -> Iterator[_Target]:
    if paragraph.semantic_role != rule.selector or _is_excluded(rule, paragraph):
        return
    if not rule.property.startswith("font."):
        yield _Target(
            element_ref=paragraph.element_ref,
            effective=paragraph.effective,
            unsupported_features=tuple(paragraph.unsupported_features),
            excerpt=paragraph.text[:80],
        )
        return
    for run in paragraph.runs:
        if not run.text.strip() or _is_excluded(rule, paragraph, run):
            continue
        if not _run_matches_script(rule.property, run.text):
            continue
        yield _Target(
            element_ref=_run_element_ref(paragraph, run),
            effective=run.effective,
            unsupported_features=tuple(paragraph.unsupported_features + run.unsupported_features),
            excerpt=run.text[:80] or paragraph.text[:80],
        )


def _section_targets(section: SectionNode) -> _Target:
    return _Target(
        element_ref=section.element_ref,
        effective=section.effective,
        unsupported_features=(),
        excerpt="",
    )


def _select_targets(snapshot: DocumentSnapshot, rule: FormatRule) -> Iterator[_Target]:
    if rule.selector == "section":
        for section in snapshot.sections:
            yield _section_targets(section)
        return
    for paragraph in snapshot.paragraphs:
        yield from _paragraph_targets(paragraph, rule)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _issue_identity(
    inspection_id: str, revision_id: str, rule: FormatRule, target: _Target
) -> tuple[str, str]:
    fingerprint_payload = {
        "revision_id": revision_id,
        "rule_id": rule.rule_id,
        "property": rule.property,
        "element_ref": target.element_ref.model_dump(mode="json", exclude_none=True),
    }
    fingerprint = hashlib.sha256(_canonical_json(fingerprint_payload).encode("utf-8")).hexdigest()
    issue_id = "iss_" + hashlib.sha256(f"{inspection_id}:{fingerprint}".encode()).hexdigest()[:24]
    return fingerprint, issue_id


def _expected_evidence(rule: FormatRule) -> ValueEvidence:
    sample = rule.expected[0] if rule.operator in {"in", "between"} else rule.expected
    return ValueEvidence(
        value=rule.expected,
        unit=_evidence_unit(rule.property, sample),
        origin="RULE",
    )


def _repair_eligibility(
    rule: FormatRule,
    target: _Target,
    document_features: list[str],
    *,
    unknown: bool,
    unknown_reason: str | None = None,
) -> RepairEligibility:
    if unknown:
        return RepairEligibility(
            eligibility="UNSUPPORTED",
            reason=unknown_reason or "A resolved effective value is required for repair",
        )
    if rule.fix_policy == "UNSUPPORTED":
        return RepairEligibility(
            eligibility="UNSUPPORTED", reason="The rule disables repair for this property"
        )
    risk_features = sorted(set(document_features + list(target.unsupported_features)))
    if risk_features:
        return RepairEligibility(
            eligibility="NEEDS_REVIEW",
            reason="Unsupported features prevent automatic repair: " + ", ".join(risk_features),
        )
    if rule.fix_policy == "MANUAL_ONLY":
        return RepairEligibility(
            eligibility="NEEDS_REVIEW", reason="The rule requires manual repair"
        )
    if rule.property == "paragraph.first_line_indent_chars":
        return RepairEligibility(
            eligibility="NEEDS_REVIEW",
            reason="Character-based indentation requires layout-aware review",
        )
    if rule.property in {"section.page_width_mm", "section.page_height_mm"}:
        return RepairEligibility(
            eligibility="NEEDS_REVIEW", reason="Page size changes can reflow the whole section"
        )
    return RepairEligibility(
        eligibility="SAFE_SINGLE_TARGET", reason="A single supported formatting target is resolved"
    )


def _unknown_reason(resolution: ResolvedProperty, error: Exception | None = None) -> str:
    if error is not None:
        return f"Resolved value is not comparable: {error}"
    if resolution.reason:
        return resolution.reason
    return f"Effective property status is {resolution.status}"


def _make_issue(
    snapshot: DocumentSnapshot,
    inspection_id: str,
    rule: FormatRule,
    target: _Target,
    resolution: ResolvedProperty,
) -> Issue | None:
    unknown = resolution.status != "RESOLVED"
    actual_value: Any = resolution.value
    error: Exception | None = None
    if not unknown:
        try:
            actual_value = _coerce_actual_value(rule, resolution.value)
        except (TypeError, ValueError, OverflowError) as exc:
            unknown = True
            error = exc
    if not unknown and _matches(rule, actual_value):
        return None

    fingerprint, issue_id = _issue_identity(inspection_id, snapshot.revision_id, rule, target)
    reason = _unknown_reason(resolution, error) if unknown else None
    if unknown:
        actual = ValueEvidence(
            value=resolution.value,
            unit=_evidence_unit(rule.property, resolution.value),
            origin=resolution.origin,
            raw_ooxml_value=resolution.raw_ooxml_value,
            reason=reason,
        )
    else:
        actual = ValueEvidence(
            value=actual_value,
            unit=_evidence_unit(rule.property, actual_value),
            origin=resolution.origin,
            raw_ooxml_value=resolution.raw_ooxml_value,
            reason=resolution.reason,
        )
    global_blockers = list(snapshot.package_inventory.get("repair_blockers", []))
    global_blockers.extend(
        feature
        for feature in snapshot.unsupported_features
        if feature.casefold()
        in {
            "tracked_changes",
            "track_changes",
            "ole_object",
            "active_x",
            "document_protection",
            "write_protection",
            "alt_chunk",
            "macro",
            "digital_signature",
            "encrypted",
        }
    )
    repair = _repair_eligibility(
        rule,
        target,
        global_blockers,
        unknown=unknown,
        unknown_reason=reason,
    )
    location = LocationMapping(
        issue_id=issue_id,
        revision_id=snapshot.revision_id,
        renderer_profile_id=snapshot.renderer_profile_id,
        status="PENDING",
        anchor_excerpt=target.excerpt,
    )
    return Issue(
        issue_id=issue_id,
        inspection_id=inspection_id,
        revision_id=snapshot.revision_id,
        rule_id=rule.rule_id,
        element_ref=target.element_ref,
        property=rule.property,
        actual=actual,
        expected=_expected_evidence(rule),
        detection_status="UNKNOWN" if unknown else "CONFIRMED_VIOLATION",
        severity=rule.severity,
        repair=repair,
        location=location,
        source=rule.source,
        fingerprint=fingerprint,
    )


def _default_inspection_id(
    snapshot: DocumentSnapshot, ruleset_digest: str, inspector_version: str
) -> str:
    identity = _canonical_json(
        {
            "revision_id": snapshot.revision_id,
            "revision_sha256": snapshot.sha256,
            "rule_set_digest": ruleset_digest,
            "inspector_version": inspector_version,
        }
    )
    return "ins_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _deduplicate(issues: list[Issue]) -> list[Issue]:
    deduplicated: dict[str, Issue] = {}
    detection_rank = {"UNKNOWN": 0, "POSSIBLE_VIOLATION": 1, "CONFIRMED_VIOLATION": 2}
    for issue in issues:
        existing = deduplicated.get(issue.issue_id)
        if (
            existing is None
            or detection_rank[issue.detection_status] > detection_rank[existing.detection_status]
        ):
            deduplicated[issue.issue_id] = issue
    severity_rank = {"ERROR": 0, "WARNING": 1, "INFO": 2}
    return sorted(
        deduplicated.values(),
        key=lambda issue: (
            severity_rank[issue.severity],
            issue.rule_id,
            issue.element_ref.paragraph_ordinal,
            issue.element_ref.run_range.start if issue.element_ref.run_range else -1,
            issue.property,
            issue.fingerprint,
        ),
    )


def inspect_document(
    snapshot: DocumentSnapshot | Mapping[str, Any],
    ruleset: RuleSet | Mapping[str, Any],
    inspection_id: str | None = None,
    inspector_version: str = DEFAULT_INSPECTOR_VERSION,
) -> InspectionResult:
    document = (
        DocumentSnapshot.model_validate(snapshot) if isinstance(snapshot, Mapping) else snapshot
    )
    if isinstance(ruleset, Mapping):
        raw_ruleset = dict(ruleset)
        if "rules" in raw_ruleset:
            raw_ruleset["rules"] = [
                validate_rule(rule).model_dump(mode="python") for rule in raw_ruleset["rules"]
            ]
        rule_set = RuleSet.model_validate(raw_ruleset)
    else:
        rule_set = ruleset
    if rule_set.status != "APPROVED":
        raise AlineaError("RULESET_NOT_APPROVED", "FormatInspector requires an APPROVED RuleSet")
    validated_rules = [validate_rule(rule) for rule in rule_set.rules]
    ruleset_digest = rule_set.digest or compute_ruleset_digest(validated_rules)
    resolved_inspection_id = inspection_id or _default_inspection_id(
        document, ruleset_digest, inspector_version
    )

    issues: list[Issue] = []
    evaluated_rules = 0
    skipped_rules = 0
    for rule in validated_rules:
        if not rule.enabled:
            skipped_rules += 1
            continue
        targets = list(_select_targets(document, rule))
        if not targets:
            skipped_rules += 1
            continue
        evaluated_rules += 1
        for target in targets:
            resolution = target.effective.get(rule.property)
            if resolution is None:
                resolution = ResolvedProperty(
                    property=rule.property,
                    status="UNRESOLVED",
                    origin="UNKNOWN",
                    reason="Effective property is absent from the input snapshot",
                )
            issue = _make_issue(document, resolved_inspection_id, rule, target, resolution)
            if issue is not None:
                issues.append(issue)

    unique_issues = _deduplicate(issues)
    summary = InspectionSummary(
        violations=sum(issue.detection_status == "CONFIRMED_VIOLATION" for issue in unique_issues),
        unverifiable=sum(issue.detection_status == "UNKNOWN" for issue in unique_issues),
        fixable=sum(
            issue.detection_status == "CONFIRMED_VIOLATION"
            and issue.repair.eligibility == "SAFE_SINGLE_TARGET"
            for issue in unique_issues
        ),
        evaluated_rules=evaluated_rules,
        skipped_rules=skipped_rules,
    )
    return InspectionResult(
        inspection_id=resolved_inspection_id,
        revision_id=document.revision_id,
        rule_set_id=rule_set.rule_set_id,
        rule_set_digest=ruleset_digest,
        inspector_version=inspector_version,
        status="SUCCEEDED",
        issues=unique_issues,
        summary=summary,
        created_at=datetime.now(UTC),
    )


__all__ = ["DEFAULT_INSPECTOR_VERSION", "inspect_document"]
