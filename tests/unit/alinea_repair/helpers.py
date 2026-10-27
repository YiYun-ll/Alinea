from __future__ import annotations

import copy
import hashlib
import io
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alinea_contracts.models import (
    DocumentSnapshot,
    ElementRef,
    FormatProperty,
    FormatRule,
    Issue,
    LocationMapping,
    ParagraphNode,
    PartDescriptor,
    RepairEligibility,
    RepairPlan,
    ResolvedProperty,
    RuleSet,
    RunNode,
    RunRange,
    SectionNode,
    SourceRef,
    ValueEvidence,
)
from alinea_repair import create_repair_plan
from alinea_repair._util import sha256_file, sha256_text
from alinea_repair.ooxml import W14_NS, W_NS, parse_xml
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.shared import Emu
from lxml import etree

NOW = datetime(2026, 1, 1, tzinfo=UTC)
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63606060f80f0001040100b5471c3a0000000049454e44ae426082"
)


@dataclass
class Spec:
    issue_id: str
    prop: FormatProperty
    before: object
    after: object
    target: str = "p0:r0"
    detection_status: str = "CONFIRMED_VIOLATION"
    eligibility: str = "SAFE_SINGLE_TARGET"


@dataclass
class Case:
    base_path: Path
    snapshot: DocumentSnapshot
    issues: list[Issue]
    rule_set: RuleSet

    def plan(
        self,
        selected: list[str] | None = None,
        *,
        approved: bool = True,
        actor: str | None = None,
    ) -> RepairPlan:
        return create_repair_plan(
            self.snapshot,
            self.issues,
            self.rule_set,
            selected,
            plan_id="rp_test",
            status="APPROVED" if approved else "DRAFT",
            approved_at=NOW if approved else None,
            approved_actor=actor,
        )


def read_parts(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {
            info.filename: archive.read(info) for info in archive.infolist() if not info.is_dir()
        }


def write_parts(path: Path, parts: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path) as source:
        infos = source.infolist()
        comment = source.comment
    temporary = path.with_suffix(".rewrite.docx")
    with zipfile.ZipFile(temporary, "w") as destination:
        destination.comment = comment
        for info in infos:
            if info.is_dir():
                destination.writestr(copy.copy(info), b"")
            elif info.filename in parts:
                destination.writestr(copy.copy(info), parts[info.filename])
    temporary.replace(path)


def mutate_xml(path: Path, part: str, mutator: Callable[[etree._Element], None]) -> None:
    parts = read_parts(path)
    tree = parse_xml(parts[part])
    mutator(tree.getroot())
    parts[part] = etree.tostring(tree, encoding="UTF-8", xml_declaration=True, standalone=True)
    write_parts(path, parts)


def _xml_path(element: etree._Element) -> str:
    steps: list[str] = []
    current: etree._Element | None = element
    while current is not None:
        parent = current.getparent()
        qname = etree.QName(current)
        if qname.namespace != W_NS:
            raise ValueError(f"test helper only supports w paths: {current.tag}")
        index = 1
        if parent is not None:
            index += sum(
                sibling.tag == current.tag for sibling in current.itersiblings(preceding=True)
            )
        steps.append(f"w:{qname.localname}[{index}]")
        current = parent
    return "/" + "/".join(reversed(steps))


def _text(element: etree._Element) -> str:
    return "".join(item.text or "" for item in element.iter(f"{{{W_NS}}}t"))


def _add_hyperlink(document: Document) -> None:
    paragraph = document.add_paragraph()
    relationship_id = paragraph.part.relate_to(
        "https://example.com/a-b", RT.HYPERLINK, is_external=True
    )
    hyperlink = etree.Element(f"{{{W_NS}}}hyperlink")
    hyperlink.set(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id",
        relationship_id,
    )
    run = etree.SubElement(hyperlink, f"{{{W_NS}}}r")
    text = etree.SubElement(run, f"{{{W_NS}}}t")
    text.text = "External-Link"
    paragraph._p.append(hyperlink)


def _construct_docx(path: Path, specs: list[Spec], complex_document: bool) -> None:
    document = Document()
    paragraph_indices = [
        int(spec.target[1:].split(":", 1)[0]) for spec in specs if spec.target.startswith("p")
    ]
    for paragraph_index in range(max(paragraph_indices, default=0) + 1):
        paragraph = document.add_paragraph()
        paragraph.add_run(f"Hello-{paragraph_index} ")
        emphasized = paragraph.add_run("世界")
        emphasized.bold = True
        if paragraph_index == 0:
            paragraph._p.set(f"{{{W14_NS}}}paraId", "00AB12CD")
    if complex_document:
        table = document.add_table(rows=1, cols=1)
        table.cell(0, 0).text = "Table-Text"
        picture_paragraph = document.add_paragraph()
        picture_paragraph.add_run().add_picture(io.BytesIO(PNG_1X1), width=Emu(12700))
        _add_hyperlink(document)
        document.sections[0].header.paragraphs[0].text = "Header-Text"
        document.sections[0].footer.paragraphs[0].text = "Footer-Text"
    document.save(path)


def _paragraph_nodes(parts: dict[str, bytes]) -> list[ParagraphNode]:
    nodes: list[ParagraphNode] = []
    part_names = ["word/document.xml"]
    part_names.extend(
        sorted(
            name
            for name in parts
            if name.startswith(("word/header", "word/footer")) and name.endswith(".xml")
        )
    )
    for part_name in part_names:
        root = parse_xml(parts[part_name]).getroot()
        paragraphs = list(root.iter(f"{{{W_NS}}}p"))
        refs: list[ElementRef] = []
        for ordinal, paragraph in enumerate(paragraphs):
            text = _text(paragraph)
            refs.append(
                ElementRef(
                    revision_id="rev_base",
                    part_uri="/" + part_name,
                    kind="paragraph",
                    xml_path=_xml_path(paragraph),
                    paragraph_ordinal=ordinal,
                    para_id=paragraph.get(f"{{{W14_NS}}}paraId"),
                    text_sha256=sha256_text(text),
                    text_excerpt=text[:40],
                )
            )
        for ordinal, (paragraph, ref) in enumerate(zip(paragraphs, refs, strict=True)):
            ref = ref.model_copy(
                update={
                    "context_before_sha256": refs[ordinal - 1].text_sha256 if ordinal else None,
                    "context_after_sha256": refs[ordinal + 1].text_sha256
                    if ordinal + 1 < len(refs)
                    else None,
                }
            )
            runs = [
                RunNode(index=index, text=_text(run))
                for index, run in enumerate(paragraph.iter(f"{{{W_NS}}}r"))
            ]
            nodes.append(
                ParagraphNode(
                    element_ref=ref,
                    text=_text(paragraph),
                    normalized_text=_text(paragraph),
                    semantic_role="unknown",
                    role_confidence=0,
                    inside_table=bool(list(paragraph.iterancestors(f"{{{W_NS}}}tc"))),
                    runs=runs,
                )
            )
    return nodes


def build_case(
    path: Path,
    specs: list[Spec],
    *,
    complex_document: bool = False,
    mutator: Callable[[Path], None] | None = None,
) -> Case:
    _construct_docx(path, specs, complex_document)
    if mutator is not None:
        mutator(path)
    parts = read_parts(path)
    paragraphs = _paragraph_nodes(parts)
    document_paragraphs = [
        node for node in paragraphs if node.element_ref.part_uri == "/word/document.xml"
    ]
    section_element = (
        parse_xml(parts["word/document.xml"]).getroot().find(f"{{{W_NS}}}body/{{{W_NS}}}sectPr")
    )
    assert section_element is not None
    section_ref = ElementRef(
        revision_id="rev_base",
        part_uri="/word/document.xml",
        kind="section",
        xml_path=_xml_path(section_element),
        paragraph_ordinal=0,
        section_ordinal=0,
        text_sha256="sha256:"
        + hashlib.sha256(etree.tostring(section_element, encoding="utf-8", with_tail=False)).hexdigest(),
    )
    section = SectionNode(element_ref=section_ref)
    issues: list[Issue] = []
    rules: list[FormatRule] = []
    for spec in specs:
        if spec.target == "section":
            fresh = section_ref
            target_node = section
        else:
            paragraph_index = int(spec.target[1:].split(":", 1)[0])
            target_node = document_paragraphs[paragraph_index]
            fresh = target_node.element_ref
            if ":r" in spec.target:
                run_index = int(spec.target.rsplit(":r", 1)[1])
                fresh = fresh.model_copy(
                    update={"run_range": RunRange(start=run_index, end=run_index + 1)}
                )
        resolved = ResolvedProperty(
            property=spec.prop, value=spec.before, status="RESOLVED", origin="DIRECT"
        )
        if spec.target == "section":
            section.effective[spec.prop] = resolved
        elif ":r" in spec.target:
            run_index = int(spec.target.rsplit(":r", 1)[1])
            assert isinstance(target_node, ParagraphNode)
            target_node.runs[run_index].effective[spec.prop] = resolved
        else:
            assert isinstance(target_node, ParagraphNode)
            target_node.effective[spec.prop] = resolved
        source = SourceRef(source_type="manual", reference=f"test:{spec.issue_id}")
        issues.append(
            Issue(
                issue_id=spec.issue_id,
                inspection_id="inspection_test",
                revision_id="rev_base",
                rule_id=f"rule_{spec.issue_id}",
                element_ref=fresh,
                property=spec.prop,
                actual=ValueEvidence(value=spec.before),
                expected=ValueEvidence(value=spec.after),
                detection_status=spec.detection_status,
                severity="ERROR",
                repair=RepairEligibility(eligibility=spec.eligibility),
                location=LocationMapping(
                    issue_id=spec.issue_id,
                    revision_id="rev_base",
                    status="LOCATED",
                ),
                source=source,
                fingerprint=hashlib.sha256(spec.issue_id.encode()).hexdigest(),
            )
        )
        rules.append(
            FormatRule(
                rule_id=f"rule_{spec.issue_id}",
                selector="section" if spec.target == "section" else "body",
                property=spec.prop,
                expected=spec.after,
                source=source,
            )
        )
    descriptors = [
        PartDescriptor(
            part_uri="/" + name,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )
        for name, data in parts.items()
    ]
    snapshot = DocumentSnapshot(
        revision_id="rev_base",
        sha256=sha256_file(path),
        parts=descriptors,
        paragraphs=paragraphs,
        sections=[section],
        styles={},
    )
    rule_set = RuleSet(
        rule_set_id="rules_test",
        project_id="project_test",
        version=3,
        name="test rules",
        status="APPROVED",
        digest=sha256_text("rule-set-v3"),
        rules=rules,
    )
    return Case(path, snapshot, issues, rule_set)


def gate(result, name: str):
    return next(item for item in result.gates if item.gate == name)
