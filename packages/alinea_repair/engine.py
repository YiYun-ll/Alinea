from __future__ import annotations

import copy
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from alinea_contracts.errors import AlineaError
from alinea_contracts.models import (
    DocumentSnapshot,
    ElementRef,
    ParagraphNode,
    RepairOperation,
    RepairPlan,
    SectionNode,
)
from lxml import etree

from alinea_repair._util import normalize_sha256, sha256_bytes, sha256_file
from alinea_repair.gates import run_integrity_gates
from alinea_repair.ooxml import (
    ensure_path,
    locate_snapshot_element,
    parse_xml,
    qname,
    require_supported_target_part,
    scan_high_risk,
    section_properties,
    selected_runs,
    serialize_xml,
    target_risks,
    verify_context_hashes,
    verify_para_id,
    verify_text_hash,
)
from alinea_repair.plan import compute_execution_key, compute_plan_digest
from alinea_repair.properties import PropertyPatch, encode_property, values_equal
from alinea_repair.refs import (
    find_fresh_ref,
    find_snapshot_node,
    normalize_part_uri,
    part_name,
)
from alinea_repair.result import RepairApplyResult


@dataclass
class _PreparedOperation:
    operation: RepairOperation
    patch: PropertyPatch
    part_name: str
    targets: list[etree._Element]


def _stale(message: str, **details: object) -> AlineaError:
    return AlineaError("STALE_REPAIR_PLAN", message, status_code=409, details=details)


def _load_base(path: Path) -> tuple[str, dict[str, bytes], list[zipfile.ZipInfo]]:
    try:
        base_sha256 = sha256_file(path)
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise AlineaError(
                    "UNSUPPORTED_FOR_AUTO_REPAIR",
                    "Duplicate ZIP entries are not accepted",
                    status_code=422,
                )
            bad_file = archive.testzip()
            if bad_file is not None:
                raise AlineaError(
                    "INVALID_DOCX_PACKAGE",
                    f"CRC validation failed for {bad_file}",
                    status_code=422,
                )
            parts: dict[str, bytes] = {}
            for info in infos:
                if info.is_dir():
                    continue
                if (
                    info.flag_bits & 0x1
                    or info.filename.startswith(("/", "\\"))
                    or "\\" in info.filename
                    or any(component in {"", ".", ".."} for component in Path(info.filename).parts)
                ):
                    raise AlineaError(
                        "UNSUPPORTED_FOR_AUTO_REPAIR",
                        f"Unsafe ZIP entry: {info.filename}",
                        status_code=422,
                    )
                parts[info.filename] = archive.read(info)
            return base_sha256, parts, infos
    except AlineaError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        raise AlineaError(
            "INVALID_DOCX_PACKAGE",
            f"The base DOCX cannot be read: {error}",
            status_code=422,
        ) from error


def _validate_approval_and_binding(
    plan: RepairPlan,
    snapshot: DocumentSnapshot,
    base_sha256: str,
    approved_actor: str | None,
) -> None:
    if plan.status not in {"APPROVED", "QUEUED", "RUNNING"} or plan.approved_at is None:
        raise AlineaError(
            "REPAIR_NOT_APPROVED",
            "Execution requires approved_at and status APPROVED, QUEUED or RUNNING",
            status_code=409,
        )
    if not plan.operations:
        raise AlineaError(
            "INVALID_REPAIR_SELECTION",
            "An empty repair plan cannot create a candidate revision",
            status_code=422,
        )
    if compute_plan_digest(plan) != plan.plan_digest:
        raise _stale("plan_digest does not match the approved plan content")
    if plan.base_revision_id != snapshot.revision_id:
        raise _stale("The plan base revision does not match the snapshot revision")
    try:
        snapshot_sha256 = normalize_sha256(snapshot.sha256, field="snapshot.sha256")
    except AlineaError as error:
        raise _stale(str(error)) from error
    if snapshot_sha256 != base_sha256:
        raise _stale(
            "The base DOCX SHA-256 differs from the snapshot",
            expected=snapshot_sha256,
            actual=base_sha256,
        )
    if [operation.issue_id for operation in plan.operations] != plan.selected_issue_ids:
        raise _stale("selected_issue_ids and operation issue order are inconsistent")
    if len({operation.operation_id for operation in plan.operations}) != len(plan.operations):
        raise _stale("Duplicate operation ids are not accepted")
    for operation in plan.operations:
        try:
            operation_base = normalize_sha256(
                operation.base_revision_sha256,
                field="operation.base_revision_sha256",
            )
        except AlineaError as error:
            raise _stale(str(error), operation_id=operation.operation_id) from error
        if operation_base != base_sha256:
            raise _stale(
                "An operation base SHA-256 is stale",
                operation_id=operation.operation_id,
            )
        if operation.rule_set_digest != plan.rule_set_digest:
            raise _stale(
                "An operation rule-set digest is stale",
                operation_id=operation.operation_id,
            )
        fresh = find_fresh_ref(snapshot, operation.target)
        if operation.target != fresh or fresh.revision_id != snapshot.revision_id:
            raise _stale(
                "An operation target differs from the fresh snapshot ElementRef",
                operation_id=operation.operation_id,
            )
    if approved_actor is not None:
        expected_key = compute_execution_key(plan.plan_digest, base_sha256, approved_actor)
        if plan.execution_key is not None and plan.execution_key != expected_key:
            raise _stale("The execution key does not match the approved actor and base")
    elif plan.execution_key is not None:
        raise AlineaError(
            "APPROVED_ACTOR_REQUIRED",
            "approved_actor is required to verify a plan carrying execution_key",
            status_code=409,
        )


def _verify_snapshot_parts(snapshot: DocumentSnapshot, parts: dict[str, bytes]) -> None:
    for descriptor in snapshot.parts:
        name = part_name(descriptor.part_uri)
        if name not in parts:
            raise _stale("A snapshot part is absent from the base package", part=name)
        actual = sha256_bytes(parts[name])
        try:
            expected = normalize_sha256(descriptor.sha256, field="PartDescriptor.sha256")
        except AlineaError as error:
            raise _stale(str(error), part=name) from error
        if actual != expected:
            raise _stale("A snapshot part hash is stale", part=name, actual=actual)


def _neighbor_refs(
    snapshot: DocumentSnapshot, ref: ElementRef
) -> tuple[ElementRef | None, ElementRef | None]:
    part = normalize_part_uri(ref.part_uri)
    if ref.kind == "paragraph":
        neighbors = [
            paragraph.element_ref
            for paragraph in snapshot.paragraphs
            if normalize_part_uri(paragraph.element_ref.part_uri) == part
        ]
        neighbors.sort(key=lambda item: item.paragraph_ordinal)
    else:
        neighbors = [
            section.element_ref
            for section in snapshot.sections
            if normalize_part_uri(section.element_ref.part_uri) == part
        ]
        neighbors.sort(key=lambda item: (item.section_ordinal is None, item.section_ordinal or 0))
    positions = [
        index
        for index, item in enumerate(neighbors)
        if item.paragraph_ordinal == ref.paragraph_ordinal
    ]
    if len(positions) != 1:
        raise _stale("The target is ambiguous in the snapshot context")
    index = positions[0]
    return (
        neighbors[index - 1] if index > 0 else None,
        neighbors[index + 1] if index + 1 < len(neighbors) else None,
    )


def _verify_neighbor_text(
    snapshot: DocumentSnapshot,
    ref: ElementRef,
    trees: dict[str, etree._ElementTree],
    parts: dict[str, bytes],
) -> None:
    before, after = _neighbor_refs(snapshot, ref)
    for expected, neighbor in (
        (ref.context_before_sha256, before),
        (ref.context_after_sha256, after),
    ):
        if expected is None:
            continue
        if neighbor is None:
            raise _stale("A target context neighbor is missing")
        if (
            neighbor.text_sha256.removeprefix("sha256:").casefold()
            != expected.removeprefix("sha256:").casefold()
        ):
            raise _stale("A target context hash differs from the neighbor anchor")
        name = part_name(neighbor.part_uri)
        if name not in trees:
            if name not in parts:
                raise _stale("A context part is missing", part=name)
            trees[name] = parse_xml(parts[name])
        node = find_snapshot_node(snapshot, neighbor)
        element = locate_snapshot_element(trees[name].getroot(), neighbor)
        verify_text_hash(element, neighbor, node)


def _resolved_value(node: ParagraphNode | SectionNode, prop: str) -> object:
    if not isinstance(node, (ParagraphNode, SectionNode)):
        raise _stale("The target has no effective property snapshot")
    resolved = node.effective.get(prop)
    if resolved is None or resolved.property != prop or resolved.status != "RESOLVED":
        raise _stale("The old effective property is not RESOLVED in the snapshot", property=prop)
    return resolved.value


def _verify_old_effective_value(
    operation: RepairOperation,
    node: ParagraphNode | SectionNode,
    run_indices: list[int] | None,
) -> None:
    if run_indices is None:
        actual = _resolved_value(node, operation.property)
        if not values_equal(operation.property, actual, operation.expected_before):
            raise _stale(
                "The old effective property value differs from expected_before",
                operation_id=operation.operation_id,
                property=operation.property,
                expected=operation.expected_before,
                actual=actual,
            )
        return
    if not isinstance(node, ParagraphNode):
        raise _stale("A run operation did not resolve to a paragraph snapshot")
    by_index = {run.index: run for run in node.runs}
    if len(by_index) != len(node.runs):
        raise _stale("Duplicate run indices in the snapshot")
    for index in run_indices:
        if index not in by_index:
            raise _stale("A selected run is missing from the snapshot", run_index=index)
        resolved = by_index[index].effective.get(operation.property)
        if (
            resolved is None
            or resolved.property != operation.property
            or resolved.status != "RESOLVED"
        ):
            raise _stale("A selected run has no RESOLVED old effective value", run_index=index)
        if not values_equal(operation.property, resolved.value, operation.expected_before):
            raise _stale(
                "A selected run old effective value differs from expected_before",
                operation_id=operation.operation_id,
                run_index=index,
                expected=operation.expected_before,
                actual=resolved.value,
            )


def _prepare_operations(
    plan: RepairPlan,
    snapshot: DocumentSnapshot,
    parts: dict[str, bytes],
) -> tuple[list[_PreparedOperation], dict[str, etree._ElementTree]]:
    prepared: list[_PreparedOperation] = []
    trees: dict[str, etree._ElementTree] = {}
    for operation in plan.operations:
        patch = encode_property(operation.property, operation.desired_after)
        if patch.strategy != operation.strategy:
            raise AlineaError(
                "UNSAFE_REPAIR_OPERATION",
                "The operation strategy does not match its property",
                status_code=422,
            )
        if set(operation.allowed_xml_changes) != set(patch.allowed_xml_changes) or len(
            operation.allowed_xml_changes
        ) != len(patch.allowed_xml_changes):
            raise AlineaError(
                "UNSAFE_REPAIR_OPERATION",
                "The operation XML whitelist does not match the property registry",
                status_code=422,
                details={"operation_id": operation.operation_id},
            )
        fresh = find_fresh_ref(snapshot, operation.target)
        name = require_supported_target_part(fresh.part_uri)
        if name not in parts:
            raise _stale("The target part is absent from the base package", part=name)
        if name not in trees:
            try:
                trees[name] = parse_xml(parts[name])
            except (etree.XMLSyntaxError, ValueError) as error:
                raise _stale("The target XML part cannot be parsed", part=name) from error
        node = find_snapshot_node(snapshot, fresh)
        target = locate_snapshot_element(trees[name].getroot(), fresh)
        verify_para_id(target, fresh)
        verify_text_hash(target, fresh, node)
        verify_context_hashes(snapshot, fresh)
        _verify_neighbor_text(snapshot, fresh, trees, parts)
        risks = target_risks(target)
        if risks:
            raise AlineaError(
                "UNSUPPORTED_FOR_AUTO_REPAIR",
                "The exact target contains a formula, field, text box or other complex content",
                status_code=422,
                details={"operation_id": operation.operation_id, "risks": risks},
            )
        run_indices: list[int] | None = None
        if patch.strategy == "DIRECT_RUN_PROPERTY":
            targets, run_indices = selected_runs(target, fresh)
            expected_impact = "EXACT_SELECTED_RUNS"
        elif patch.strategy == "DIRECT_PARAGRAPH_PROPERTY":
            targets = [target]
            expected_impact = "EXACT_SELECTED_PARAGRAPH"
        else:
            targets = [section_properties(target)]
            expected_impact = "EXACT_SELECTED_SECTION_WITH_REPACKAGING_RISK"
        if operation.impact_scope != expected_impact:
            raise AlineaError(
                "UNSAFE_REPAIR_OPERATION",
                "The operation impact scope is not the exact approved target",
                status_code=422,
                details={"operation_id": operation.operation_id},
            )
        _verify_old_effective_value(operation, node, run_indices)
        prepared.append(_PreparedOperation(operation, patch, name, targets))
    return prepared, trees


def _apply_operations(prepared: list[_PreparedOperation]) -> None:
    for item in prepared:
        for target in item.targets:
            for change in item.patch.changes:
                if not change.primary:
                    continue
                element = ensure_path(target, change.element_path, create=True)
                if element is None or change.value is None:
                    raise AlineaError(
                        "UNSAFE_REPAIR_OPERATION",
                        "A primary formatting path could not be created",
                        status_code=422,
                    )
                element.set(qname(change.attribute), change.value)
            for change in item.patch.changes:
                if change.primary:
                    continue
                element = ensure_path(target, change.element_path, create=False)
                if element is not None:
                    element.attrib.pop(qname(change.attribute), None)


def _write_candidate(
    base_path: Path,
    temporary_path: Path,
    infos: list[zipfile.ZipInfo],
    original_parts: dict[str, bytes],
    changed_parts: dict[str, bytes],
) -> None:
    with (
        zipfile.ZipFile(base_path, "r") as source,
        zipfile.ZipFile(temporary_path, "w", allowZip64=True) as destination,
    ):
        destination.comment = source.comment
        for info in infos:
            if info.is_dir():
                destination.writestr(copy.copy(info), b"")
                continue
            data = changed_parts.get(info.filename, original_parts[info.filename])
            destination.writestr(copy.copy(info), data)


def apply_approved_patch(
    base_path: str | Path,
    candidate_path: str | Path,
    snapshot: DocumentSnapshot,
    plan: RepairPlan,
    *,
    approved_actor: str | None = None,
) -> RepairApplyResult:
    base = Path(base_path)
    candidate = Path(candidate_path)
    if not base.is_file():
        raise AlineaError("INVALID_DOCX_PACKAGE", "base_path is not a file", status_code=422)
    if base.resolve() == candidate.resolve() or (candidate.exists() and base.samefile(candidate)):
        raise AlineaError(
            "IMMUTABLE_BASE_VIOLATION",
            "candidate_path must differ from base_path; the original DOCX is read-only",
            status_code=409,
        )
    base_sha256, parts, infos = _load_base(base)
    _validate_approval_and_binding(plan, snapshot, base_sha256, approved_actor)
    _verify_snapshot_parts(snapshot, parts)
    safety = scan_high_risk(parts)
    if safety.failures:
        raise AlineaError(
            "UNSUPPORTED_FOR_AUTO_REPAIR",
            "The package contains global high-risk features and cannot be auto-repaired",
            status_code=422,
            details={"failures": safety.failures[:100]},
        )
    prepared, trees = _prepare_operations(plan, snapshot, parts)
    _apply_operations(prepared)
    changed_parts: dict[str, bytes] = {}
    for name in sorted({item.part_name for item in prepared}):
        updated = serialize_xml(trees[name], parts[name])
        if updated != parts[name]:
            changed_parts[name] = updated

    candidate.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{candidate.name}.", suffix=".tmp", dir=candidate.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        _write_candidate(base, temporary, infos, parts, changed_parts)
        gates = run_integrity_gates(base, temporary, plan, snapshot)
        failed = [gate.gate for gate in gates if gate.status == "FAIL"]
        candidate_digest = sha256_file(temporary)
        execution_key = plan.execution_key
        if approved_actor is not None:
            execution_key = compute_execution_key(plan.plan_digest, base_sha256, approved_actor)
        if failed:
            return RepairApplyResult(
                plan_id=plan.plan_id,
                plan_digest=plan.plan_digest,
                status="BLOCKED",
                publishable=False,
                candidate_path=None,
                base_sha256=base_sha256,
                candidate_sha256=None,
                execution_key=execution_key,
                changed_parts=sorted(changed_parts),
                gates=gates,
            )
        os.replace(temporary, candidate)
        return RepairApplyResult(
            plan_id=plan.plan_id,
            plan_digest=plan.plan_digest,
            status="PATCHED",
            publishable=True,
            candidate_path=str(candidate),
            base_sha256=base_sha256,
            candidate_sha256=candidate_digest,
            execution_key=execution_key,
            changed_parts=sorted(changed_parts),
            gates=gates,
        )
    finally:
        if temporary.exists():
            temporary.unlink()
