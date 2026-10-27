from __future__ import annotations

import posixpath
import re

from alinea_contracts.errors import AlineaError
from alinea_contracts.models import DocumentSnapshot, ElementRef, ParagraphNode, SectionNode

_PART_COMPONENT_RE = re.compile(r"^[^/\\]+$")


def normalize_part_uri(part_uri: str) -> str:
    if not isinstance(part_uri, str) or not part_uri.strip():
        raise AlineaError("INVALID_ELEMENT_REF", "part_uri must be non-empty", status_code=422)
    value = part_uri.strip().replace("\\", "/")
    if value.startswith("/"):
        value = value[1:]
    if not value or any(component in {"", ".", ".."} for component in value.split("/")):
        raise AlineaError(
            "INVALID_ELEMENT_REF",
            "part_uri must be a normalized package-relative OPC part name",
            status_code=422,
            details={"part_uri": part_uri},
        )
    if any(not _PART_COMPONENT_RE.fullmatch(component) for component in value.split("/")):
        raise AlineaError(
            "INVALID_ELEMENT_REF", "part_uri contains invalid characters", status_code=422
        )
    return "/" + posixpath.normpath(value)


def part_name(part_uri: str) -> str:
    return normalize_part_uri(part_uri)[1:]


def find_fresh_ref(snapshot: DocumentSnapshot, target: ElementRef) -> ElementRef:
    target_part = normalize_part_uri(target.part_uri)
    matches: list[ElementRef] = []
    for paragraph in snapshot.paragraphs:
        ref = paragraph.element_ref
        if (
            ref.kind == target.kind
            and normalize_part_uri(ref.part_uri) == target_part
            and ref.paragraph_ordinal == target.paragraph_ordinal
        ):
            matches.append(ref)
    for section in snapshot.sections:
        ref = section.element_ref
        if (
            ref.kind == target.kind
            and normalize_part_uri(ref.part_uri) == target_part
            and ref.paragraph_ordinal == target.paragraph_ordinal
        ):
            matches.append(ref)
    if len(matches) != 1:
        raise AlineaError(
            "STALE_REPAIR_PLAN",
            "The repair target is absent or ambiguous in the base snapshot",
            status_code=409,
            details={
                "part_uri": target_part,
                "paragraph_ordinal": target.paragraph_ordinal,
                "kind": target.kind,
                "matches": len(matches),
            },
        )
    fresh = matches[0]
    if fresh.kind == "paragraph" and target.run_range is not None:
        if fresh.run_range is not None and fresh.run_range != target.run_range:
            raise AlineaError(
                "STALE_REPAIR_PLAN",
                "The requested run range conflicts with the fresh snapshot anchor",
                status_code=409,
            )
        return fresh.model_copy(update={"run_range": target.run_range.model_copy(deep=True)})
    return fresh


def find_snapshot_node(snapshot: DocumentSnapshot, ref: ElementRef) -> ParagraphNode | SectionNode:
    normalized = normalize_part_uri(ref.part_uri)
    matches: list[ParagraphNode | SectionNode] = [
        *(
            paragraph
            for paragraph in snapshot.paragraphs
            if normalize_part_uri(paragraph.element_ref.part_uri) == normalized
            and paragraph.element_ref.paragraph_ordinal == ref.paragraph_ordinal
            and paragraph.element_ref.kind == ref.kind
        ),
        *(
            section
            for section in snapshot.sections
            if normalize_part_uri(section.element_ref.part_uri) == normalized
            and section.element_ref.paragraph_ordinal == ref.paragraph_ordinal
            and section.element_ref.kind == ref.kind
        ),
    ]
    if len(matches) != 1:
        raise AlineaError(
            "STALE_REPAIR_PLAN",
            "The snapshot node for a repair target is absent or ambiguous",
            status_code=409,
            details={"part_uri": normalized, "paragraph_ordinal": ref.paragraph_ordinal},
        )
    return matches[0]
