from __future__ import annotations

import hashlib
import posixpath
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote

from alinea_contracts.errors import AlineaError
from alinea_contracts.models import DocumentSnapshot, QualityGateResult, RepairPlan
from docx import Document
from lxml import etree

from alinea_repair._util import json_safe, normalize_sha256, sha256_file
from alinea_repair.ooxml import (
    CONTENT_TYPE_NS,
    PACKAGE_REL_NS,
    XML_PATH,
    append_xml_path,
    element_path,
    is_supported_target_part,
    locate_snapshot_element,
    parse_xml,
    qname,
    scan_high_risk,
    section_properties,
    selected_runs,
    target_risks,
    verify_context_hashes,
    verify_para_id,
    verify_text_hash,
)
from alinea_repair.plan import compute_plan_digest
from alinea_repair.properties import encode_property
from alinea_repair.refs import find_fresh_ref, find_snapshot_node, normalize_part_uri


@dataclass
class _ZipRead:
    parts: dict[str, bytes] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class _Whitelist:
    attributes: dict[tuple[XML_PATH, str], set[str]] = field(default_factory=dict)
    insertions: set[XML_PATH] = field(default_factory=set)


def _read_zip(path: str | Path) -> _ZipRead:
    result = _ZipRead()
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            counts = Counter(info.filename for info in infos)
            duplicates = sorted(name for name, count in counts.items() if count > 1)
            if duplicates:
                result.errors.append(f"duplicate ZIP entries: {duplicates[:20]}")
            bad_file = archive.testzip()
            if bad_file is not None:
                result.errors.append(f"CRC failure in {bad_file}")
            for info in infos:
                name = info.filename
                path_object = PurePosixPath(name)
                if (
                    not name
                    or name.startswith(("/", "\\"))
                    or "\\" in name
                    or any(component in {"", ".", ".."} for component in path_object.parts)
                ):
                    result.errors.append(f"unsafe ZIP entry name: {name!r}")
                    continue
                if info.flag_bits & 0x1:
                    result.errors.append(f"encrypted ZIP entry: {name}")
                    continue
                if info.is_dir():
                    continue
                try:
                    result.parts[name] = archive.read(info)
                except (OSError, RuntimeError, zipfile.BadZipFile) as error:
                    result.errors.append(f"cannot read {name}: {error}")
    except (OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as error:
        result.errors.append(f"cannot open ZIP: {error}")
    return result


def _result(gate: str, status: str, **details: Any) -> QualityGateResult:
    return QualityGateResult(gate=gate, status=status, details=json_safe(details))


def _relationship_base(name: str) -> str:
    if name == "_rels/.rels":
        return ""
    path = PurePosixPath(name)
    if path.parent.name != "_rels" or not path.name.endswith(".rels"):
        raise ValueError(f"invalid relationship part location: {name}")
    parent = str(path.parent.parent)
    return "" if parent == "." else parent


def _validate_opc(parts: dict[str, bytes]) -> list[str]:
    errors: list[str] = []
    required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
    missing = sorted(required - set(parts))
    if missing:
        return [f"missing required OPC part: {name}" for name in missing]
    try:
        content_types = parse_xml(parts["[Content_Types].xml"]).getroot()
        if content_types.tag != f"{{{CONTENT_TYPE_NS}}}Types":
            errors.append("[Content_Types].xml has an unexpected root element")
    except (etree.XMLSyntaxError, ValueError) as error:
        errors.append(f"cannot parse [Content_Types].xml: {error}")

    office_document_targets: list[str] = []
    for name, data in parts.items():
        if not name.endswith(".rels"):
            continue
        try:
            base = _relationship_base(name)
            root = parse_xml(data).getroot()
        except (etree.XMLSyntaxError, ValueError) as error:
            errors.append(f"cannot parse relationships {name}: {error}")
            continue
        if root.tag != f"{{{PACKAGE_REL_NS}}}Relationships":
            errors.append(f"unexpected relationship root in {name}")
            continue
        if name != "_rels/.rels":
            source_name = posixpath.join(base, PurePosixPath(name).name[:-5])
            if source_name not in parts:
                errors.append(f"relationship source is missing for {name}: {source_name}")
        ids: set[str] = set()
        for relationship in root:
            if relationship.tag != f"{{{PACKAGE_REL_NS}}}Relationship":
                errors.append(f"unexpected child in {name}: {relationship.tag}")
                continue
            rel_id = relationship.get("Id", "")
            if not rel_id or rel_id in ids:
                errors.append(f"missing or duplicate relationship Id in {name}: {rel_id!r}")
            ids.add(rel_id)
            target = relationship.get("Target", "")
            rel_type = relationship.get("Type", "")
            if not target or not rel_type:
                errors.append(f"relationship without Target or Type in {name}: {rel_id}")
                continue
            if relationship.get("TargetMode", "Internal").casefold() == "external":
                continue
            decoded_target = unquote(target.split("#", 1)[0])
            if decoded_target.startswith("/"):
                resolved = posixpath.normpath(decoded_target.lstrip("/"))
            else:
                resolved = posixpath.normpath(posixpath.join(base, decoded_target))
            if resolved.startswith("../") or resolved == ".." or resolved not in parts:
                errors.append(f"unresolved internal relationship {name} {rel_id}: {resolved}")
            if name == "_rels/.rels" and rel_type.rstrip("/").endswith("/officeDocument"):
                office_document_targets.append(resolved)
    if len(office_document_targets) != 1 or office_document_targets[0] != "word/document.xml":
        errors.append(
            "the package must have exactly one root officeDocument relationship to word/document.xml"
        )
    return errors


def _g1(path: str | Path, read: _ZipRead) -> QualityGateResult:
    errors = list(read.errors)
    if read.parts:
        errors.extend(_validate_opc(read.parts))
    if not errors:
        try:
            Document(str(path))
        except Exception as error:
            errors.append(f"python-docx reopen failed: {error}")
    return _result(
        "G1",
        "FAIL" if errors else "PASS",
        errors=errors[:100],
        reopened=not errors,
        part_count=len(read.parts),
    )


def _text_inventory(
    parts: dict[str, bytes],
) -> tuple[dict[str, list[tuple[str, str | None]]], list[str]]:
    inventory: dict[str, list[tuple[str, str | None]]] = {}
    errors: list[str] = []
    from alinea_repair.ooxml import iter_story_text

    for name, data in parts.items():
        if not name.casefold().endswith(".xml"):
            continue
        try:
            root = parse_xml(data).getroot()
        except (etree.XMLSyntaxError, ValueError) as error:
            errors.append(f"cannot parse text part {name}: {error}")
            continue
        inventory[name] = list(iter_story_text(root))
    return inventory, errors


def _g2(base: _ZipRead, candidate: _ZipRead) -> QualityGateResult:
    errors = [f"base: {item}" for item in base.errors] + [
        f"candidate: {item}" for item in candidate.errors
    ]
    if errors:
        return _result("G2", "FAIL", errors=errors[:100])
    base_text, base_errors = _text_inventory(base.parts)
    candidate_text, candidate_errors = _text_inventory(candidate.parts)
    errors = base_errors + candidate_errors
    mismatches: list[dict[str, Any]] = []
    for name in sorted(set(base_text) | set(candidate_text)):
        before = base_text.get(name)
        after = candidate_text.get(name)
        if before == after:
            continue
        first_difference: int | None = None
        if before is not None and after is not None:
            for index, (left, right) in enumerate(zip(before, after, strict=False)):
                if left != right:
                    first_difference = index
                    break
            if first_difference is None and len(before) != len(after):
                first_difference = min(len(before), len(after))
        mismatches.append(
            {
                "part": name,
                "before_count": None if before is None else len(before),
                "after_count": None if after is None else len(after),
                "first_difference": first_difference,
            }
        )
    return _result(
        "G2",
        "FAIL" if errors or mismatches else "PASS",
        errors=errors[:100],
        mismatches=mismatches[:100],
        compared_part_count=len(set(base_text) & set(candidate_text)),
    )


def _resource_inventory(parts: dict[str, bytes]) -> dict[str, dict[str, Any]]:
    resources: dict[str, dict[str, Any]] = {}
    for name, data in parts.items():
        folded = name.casefold()
        if folded.startswith(("word/media/", "word/embeddings/")) or folded.endswith(".rels"):
            resources[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return resources


def _g3(base: _ZipRead, candidate: _ZipRead) -> QualityGateResult:
    errors = [f"base: {item}" for item in base.errors] + [
        f"candidate: {item}" for item in candidate.errors
    ]
    if errors:
        return _result("G3", "FAIL", errors=errors[:100])
    before = _resource_inventory(base.parts)
    after = _resource_inventory(candidate.parts)
    changed = sorted(
        name
        for name in set(before) & set(after)
        if before[name]["sha256"] != after[name]["sha256"]
        or before[name]["size"] != after[name]["size"]
    )
    missing = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))
    failed = bool(changed or missing or added)
    return _result(
        "G3",
        "FAIL" if failed else "PASS",
        changed=changed[:100],
        missing=missing[:100],
        added=added[:100],
        resource_count=len(before),
    )


def _node_key(item: etree._Element) -> str:
    if isinstance(item.tag, str):
        return item.tag
    if isinstance(item, etree._Comment):
        return "!comment"
    if isinstance(item, etree._ProcessingInstruction):
        return "!processing-instruction"
    return "!non-element"


def _child_entries(
    parent: etree._Element, parent_path: XML_PATH
) -> tuple[list[XML_PATH], dict[XML_PATH, etree._Element]]:
    counts: Counter[str] = Counter()
    order: list[XML_PATH] = []
    children: dict[XML_PATH, etree._Element] = {}
    for child in parent:
        key = _node_key(child)
        counts[key] += 1
        path = (*parent_path, (key, counts[key]))
        order.append(path)
        children[path] = child
    return order, children


def _record(differences: list[dict[str, Any]], code: str, path: XML_PATH, **details: Any) -> None:
    differences.append(
        {"code": code, "path": "/".join(f"{tag}[{index}]" for tag, index in path), **details}
    )


def _validate_inserted_subtree(
    item: etree._Element,
    path: XML_PATH,
    whitelist: _Whitelist,
    differences: list[dict[str, Any]],
) -> None:
    if path not in whitelist.insertions:
        _record(differences, "UNAUTHORIZED_INSERTED_SUBTREE", path)
        return
    if (item.text and item.text.strip()) or (item.tail and item.tail.strip()):
        _record(differences, "INSERTED_TEXT_OR_TAIL", path)
    parent = item.getparent()
    inherited = {} if parent is None else parent.nsmap
    if any(item.nsmap.get(prefix) != uri for prefix, uri in inherited.items()) or any(
        prefix not in inherited for prefix in item.nsmap
    ):
        _record(differences, "INSERTED_NAMESPACE_DECLARATION", path)
    for attribute, after in item.attrib.items():
        if "set" not in whitelist.attributes.get((path, attribute), set()):
            _record(
                differences,
                "UNAUTHORIZED_INSERTED_ATTRIBUTE",
                path,
                attribute=attribute,
                after=after,
            )
    _, children = _child_entries(item, path)
    for child_path, child in children.items():
        _validate_inserted_subtree(child, child_path, whitelist, differences)


def _compare_element(
    before: etree._Element,
    after: etree._Element,
    path: XML_PATH,
    whitelist: _Whitelist,
    differences: list[dict[str, Any]],
) -> None:
    if before.tag != after.tag:
        _record(differences, "TAG_CHANGED", path, before=str(before.tag), after=str(after.tag))
        return
    if before.text != after.text:
        _record(differences, "TEXT_CHANGED", path, before=before.text, after=after.text)
    if before.tail != after.tail:
        _record(differences, "TAIL_CHANGED", path, before=before.tail, after=after.tail)
    if before.nsmap != after.nsmap:
        _record(differences, "NAMESPACE_MAP_CHANGED", path, before=before.nsmap, after=after.nsmap)
    for attribute in sorted(set(before.attrib) | set(after.attrib)):
        old_value = before.attrib.get(attribute)
        new_value = after.attrib.get(attribute)
        if old_value == new_value:
            continue
        direction = "set" if new_value is not None else "delete"
        if direction not in whitelist.attributes.get((path, attribute), set()):
            _record(
                differences,
                "UNAUTHORIZED_ATTRIBUTE_CHANGE",
                path,
                attribute=attribute,
                before=old_value,
                after=new_value,
            )
    before_order, before_children = _child_entries(before, path)
    after_order, after_children = _child_entries(after, path)
    before_keys = set(before_children)
    after_keys = set(after_children)
    allowed_added = {
        child_path for child_path in after_keys - before_keys if child_path in whitelist.insertions
    }
    for child_path in before_order:
        if child_path not in after_keys:
            _record(differences, "ELEMENT_REMOVED", child_path)
    for child_path in after_order:
        if child_path not in before_keys:
            if child_path in whitelist.insertions:
                _validate_inserted_subtree(
                    after_children[child_path], child_path, whitelist, differences
                )
            else:
                _record(differences, "ELEMENT_ADDED", child_path)
    if [item for item in after_order if item not in allowed_added] != before_order:
        _record(differences, "CHILD_ORDER_CHANGED", path)
    for child_path in before_order:
        if child_path in after_keys:
            _compare_element(
                before_children[child_path],
                after_children[child_path],
                child_path,
                whitelist,
                differences,
            )


def _compare_trees(
    before: etree._ElementTree, after: etree._ElementTree, whitelist: _Whitelist
) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    before_root = before.getroot()
    after_root = after.getroot()
    root_path = element_path(before_root)
    _compare_element(before_root, after_root, root_path, whitelist, differences)
    for direction in ("preceding", False):
        before_siblings = list(before_root.itersiblings(preceding=direction == "preceding"))
        after_siblings = list(after_root.itersiblings(preceding=direction == "preceding"))
        before_bytes = [etree.tostring(item) for item in before_siblings]
        after_bytes = [etree.tostring(item) for item in after_siblings]
        if before_bytes != after_bytes:
            _record(differences, "TOP_LEVEL_XML_NODES_CHANGED", root_path, direction=str(direction))
    return differences


def _build_whitelist(
    plan: RepairPlan,
    snapshot: DocumentSnapshot,
    base_parts: dict[str, bytes],
    base_sha256: str,
) -> tuple[_Whitelist, set[str], dict[str, etree._ElementTree]]:
    if compute_plan_digest(plan) != plan.plan_digest:
        raise AlineaError(
            "STALE_REPAIR_PLAN",
            "plan_digest does not bind the supplied operations",
            status_code=409,
        )
    if plan.base_revision_id != snapshot.revision_id:
        raise AlineaError(
            "STALE_REPAIR_PLAN",
            "The plan and snapshot base revisions differ",
            status_code=409,
        )
    snapshot_sha256 = normalize_sha256(snapshot.sha256, field="snapshot.sha256")
    if snapshot_sha256 != base_sha256:
        raise AlineaError(
            "STALE_REPAIR_PLAN",
            "The base file SHA-256 differs from the snapshot",
            status_code=409,
        )
    whitelist = _Whitelist()
    authorized_parts: set[str] = set()
    trees: dict[str, etree._ElementTree] = {}
    for operation in plan.operations:
        operation_base = normalize_sha256(
            operation.base_revision_sha256,
            field="operation.base_revision_sha256",
        )
        if operation_base != base_sha256 or operation.rule_set_digest != plan.rule_set_digest:
            raise AlineaError(
                "STALE_REPAIR_PLAN",
                "An operation base SHA-256 or rule-set digest is stale",
                status_code=409,
                details={"operation_id": operation.operation_id},
            )
        fresh = find_fresh_ref(snapshot, operation.target)
        if operation.target != fresh:
            raise AlineaError(
                "STALE_REPAIR_PLAN",
                "An operation target differs from the fresh snapshot ElementRef",
                status_code=409,
                details={"operation_id": operation.operation_id},
            )
        name = normalize_part_uri(fresh.part_uri)[1:]
        if not is_supported_target_part(name) or name not in base_parts:
            raise AlineaError(
                "UNSAFE_REPAIR_OPERATION",
                "G4 rejected a non-story or missing target part",
                status_code=422,
                details={"part": name},
            )
        if name not in trees:
            trees[name] = parse_xml(base_parts[name])
        node = find_snapshot_node(snapshot, fresh)
        target = locate_snapshot_element(trees[name].getroot(), fresh)
        verify_para_id(target, fresh)
        verify_text_hash(target, fresh, node)
        verify_context_hashes(snapshot, fresh)
        risks = target_risks(target)
        if risks:
            raise AlineaError(
                "UNSAFE_REPAIR_OPERATION",
                "G4 rejected a complex target",
                status_code=422,
                details={"operation_id": operation.operation_id, "risks": risks},
            )
        patch = encode_property(operation.property, operation.desired_after)
        if (
            patch.strategy != operation.strategy
            or set(operation.allowed_xml_changes) != set(patch.allowed_xml_changes)
            or len(operation.allowed_xml_changes) != len(patch.allowed_xml_changes)
        ):
            raise AlineaError(
                "UNSAFE_REPAIR_OPERATION",
                "An operation strategy or XML whitelist differs from the property registry",
                status_code=422,
                details={"operation_id": operation.operation_id},
            )
        if patch.strategy == "DIRECT_RUN_PROPERTY":
            runs, _ = selected_runs(target, fresh)
            bases = [element_path(run) for run in runs]
        elif patch.strategy == "DIRECT_PARAGRAPH_PROPERTY":
            bases = [element_path(target)]
        else:
            bases = [element_path(section_properties(target))]
        authorized_parts.add(name)
        for base in bases:
            for change in patch.changes:
                full_path = append_xml_path(base, change.element_path)
                attribute = qname(change.attribute)
                direction = "set" if change.primary else "delete"
                directions = whitelist.attributes.setdefault((full_path, attribute), set())
                if directions and direction not in directions:
                    raise AlineaError(
                        "UNSAFE_REPAIR_OPERATION",
                        "Conflicting operations require setting and deleting the same XML attribute",
                        status_code=422,
                        details={
                            "operation_id": operation.operation_id,
                            "attribute": change.whitelist_path,
                        },
                    )
                directions.add(direction)
                if change.primary:
                    for length in range(len(base) + 1, len(full_path) + 1):
                        whitelist.insertions.add(full_path[:length])
    return whitelist, authorized_parts, trees


def _g4(
    plan: RepairPlan,
    snapshot: DocumentSnapshot,
    base: _ZipRead,
    candidate: _ZipRead,
    base_sha256: str,
) -> QualityGateResult:
    errors = [f"base: {item}" for item in base.errors] + [
        f"candidate: {item}" for item in candidate.errors
    ]
    if errors:
        return _result("G4", "FAIL", errors=errors[:100])
    differences: list[dict[str, Any]] = []
    authorized_parts: set[str] = set()
    try:
        whitelist, authorized_parts, base_trees = _build_whitelist(
            plan, snapshot, base.parts, base_sha256
        )
    except (AlineaError, etree.XMLSyntaxError, ValueError) as error:
        return _result("G4", "FAIL", errors=[str(error)], authorized_parts=[])
    for name in sorted(set(base.parts) | set(candidate.parts)):
        if name not in base.parts:
            differences.append({"code": "PART_ADDED", "part": name})
            continue
        if name not in candidate.parts:
            differences.append({"code": "PART_REMOVED", "part": name})
            continue
        before_bytes = base.parts[name]
        after_bytes = candidate.parts[name]
        if name not in authorized_parts:
            if before_bytes != after_bytes:
                differences.append({"code": "UNAUTHORIZED_PART_BYTES_CHANGED", "part": name})
            continue
        if before_bytes == after_bytes:
            continue
        try:
            after_tree = parse_xml(after_bytes)
            part_differences = _compare_trees(base_trees[name], after_tree, whitelist)
        except (etree.XMLSyntaxError, ValueError) as error:
            differences.append(
                {"code": "AUTHORIZED_PART_XML_PARSE_ERROR", "part": name, "detail": str(error)}
            )
            continue
        for difference in part_differences:
            difference["part"] = name
        differences.extend(part_differences)
    return _result(
        "G4",
        "FAIL" if differences else "PASS",
        differences=differences[:100],
        difference_count=len(differences),
        authorized_parts=sorted(authorized_parts),
        operation_count=len(plan.operations),
    )


def run_integrity_gates(
    base_path: str | Path,
    candidate_path: str | Path,
    plan: RepairPlan,
    snapshot: DocumentSnapshot,
) -> list[QualityGateResult]:
    base = _read_zip(base_path)
    candidate = _read_zip(candidate_path)
    try:
        base_sha256 = sha256_file(base_path)
    except OSError:
        base_sha256 = ""
    safety = scan_high_risk(base.parts) if base.parts else None
    g0_errors = list(base.errors)
    if safety is not None:
        g0_errors.extend(str(item) for item in safety.failures)
    g0_status = "FAIL" if g0_errors else (safety.status if safety is not None else "FAIL")
    g0 = _result(
        "G0",
        g0_status,
        errors=g0_errors[:100],
        warnings=[] if safety is None else safety.warnings,
        scanned_part_count=len(base.parts),
    )
    return [
        g0,
        _g1(candidate_path, candidate),
        _g2(base, candidate),
        _g3(base, candidate),
        _g4(plan, snapshot, base, candidate, base_sha256),
    ]
