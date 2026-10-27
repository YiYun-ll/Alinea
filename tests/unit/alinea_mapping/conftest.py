from __future__ import annotations

import hashlib

import pytest
from alinea_contracts import (
    DocumentSnapshot,
    ElementRef,
    Issue,
    LocationMapping,
    ParagraphNode,
    RepairEligibility,
    SourceRef,
    ValueEvidence,
)


def make_paragraph(text: str, ordinal: int = 0, revision_id: str = "rev-1") -> ParagraphNode:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    ref = ElementRef(
        revision_id=revision_id,
        part_uri="/word/document.xml",
        kind="paragraph",
        xml_path=f"/w:document/w:body/w:p[{ordinal}]",
        paragraph_ordinal=ordinal,
        text_sha256=digest,
        text_excerpt=text[:120],
    )
    return ParagraphNode(
        element_ref=ref,
        text=text,
        normalized_text=" ".join(text.split()),
        semantic_role="body",
        role_confidence=1.0,
    )


def make_snapshot(
    paragraphs: list[ParagraphNode],
    revision_id: str = "rev-1",
) -> DocumentSnapshot:
    return DocumentSnapshot(
        revision_id=revision_id,
        sha256="snapshot-sha",
        parts=[],
        paragraphs=paragraphs,
        sections=[],
        styles={},
    )


def make_issue(paragraph: ParagraphNode, issue_id: str = "issue-1") -> Issue:
    return Issue(
        issue_id=issue_id,
        inspection_id="inspection-1",
        revision_id=paragraph.element_ref.revision_id,
        rule_id="rule-1",
        element_ref=paragraph.element_ref,
        property="font.size_pt",
        actual=ValueEvidence(value=10, unit="pt"),
        expected=ValueEvidence(value=12, unit="pt"),
        detection_status="CONFIRMED_VIOLATION",
        severity="ERROR",
        repair=RepairEligibility(eligibility="NEEDS_REVIEW"),
        location=LocationMapping(
            revision_id=paragraph.element_ref.revision_id,
            status="PENDING",
        ),
        source=SourceRef(source_type="manual", reference="unit-test"),
        fingerprint="fingerprint-1",
    )


@pytest.fixture
def paragraph_factory():
    return make_paragraph


@pytest.fixture
def snapshot_factory():
    return make_snapshot


@pytest.fixture
def issue_factory():
    return make_issue
