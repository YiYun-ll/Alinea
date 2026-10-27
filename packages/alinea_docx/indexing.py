from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

from alinea_contracts.errors import AlineaError
from alinea_contracts.models import (
    DocumentSnapshot,
    ElementRef,
    ParagraphNode,
    RunNode,
    RunRange,
    SectionNode,
)
from lxml import etree

from .ooxml import (
    W14_NS,
    OoxmlPackage,
    StoryPart,
    local_name,
    paragraph_runs,
    paragraph_text,
    run_text,
    w_attr,
    w_children,
    w_first,
    xml_path,
)
from .resolver import EffectiveStyleResolver

_WHITESPACE_RE = re.compile(r"\s+")
_NUMBERED_HEADING_RE = re.compile(r"^\s*(\d+(?:\.\d+){0,2})(?:\.\s+|、\s*|\s+)(\S.{0,150}?)\s*$")
_CHINESE_HEADING_RE = re.compile(
    r"^\s*第[一二三四五六七八九十百千万0-9]+([章节条])(?:\s+|[、：:]|$)"
)
_CAPTION_RE = re.compile(
    r"^\s*(?:图|表|figure|table|fig\.?)\s*[0-9一二三四五六七八九十]+(?:\s*[-–—.]\s*[0-9]+)*",
    re.IGNORECASE,
)
_REFERENCE_RE = re.compile(r"^\s*(?:\[\d+\]|［\d+］|【\d+】)\s*")
_REFERENCE_HEADING_RE = re.compile(r"^\s*(?:参考文献|references|bibliography)\s*$", re.IGNORECASE)
_HEADING_STYLE_RE = re.compile(r"heading\s*([1-3])(?:\D|$)", re.IGNORECASE)
_CHINESE_HEADING_STYLE_RE = re.compile(r"标题\s*([1-3一二三])(?:\D|$)")

_FEATURE_ELEMENTS = {
    "ins": "track_changes",
    "del": "track_changes",
    "moveFrom": "track_changes",
    "moveTo": "track_changes",
    "trackRevisions": "track_changes",
    "object": "ole_object",
    "OLEObject": "ole_object",
    "control": "active_x",
    "oMath": "equation",
    "oMathPara": "equation",
    "fldSimple": "field",
    "fldChar": "field",
    "instrText": "field",
    "txbxContent": "text_box",
    "textbox": "text_box",
}


@dataclass(slots=True)
class _RunRefRecord:
    part_uri: str
    paragraph_ordinal: int
    run_index: int
    element_ref: ElementRef


@dataclass(slots=True)
class _IndexState:
    paragraphs: list[ParagraphNode] = field(default_factory=list)
    sections: list[SectionNode] = field(default_factory=list)
    part_paragraphs: dict[str, list[ParagraphNode]] = field(
        default_factory=lambda: defaultdict(list)
    )
    run_refs: list[_RunRefRecord] = field(default_factory=list)
    features: set[str] = field(default_factory=set)
    main_paragraph_count: int = 0
    table_count: int = 0


class DocumentIndexer:
    def __init__(
        self, package: OoxmlPackage, *, resolver: EffectiveStyleResolver | None = None
    ) -> None:
        self.package = package
        self.resolver = resolver or EffectiveStyleResolver(package)

    def build_snapshot(self, *, revision_id: str | None = None) -> DocumentSnapshot:
        resolved_revision = revision_id or f"rev_{self.package.sha256[:24]}"
        state = _IndexState()
        story_inventory: list[dict[str, object]] = []

        for story in self.package.story_parts():
            before = len(state.paragraphs)
            self._index_story_part(story, resolved_revision, state)
            story_inventory.append(
                {
                    "part_uri": story.part_uri,
                    "kind": story.kind,
                    "paragraph_count": len(state.paragraphs) - before,
                }
            )

        self._add_context_hashes(state)
        fingerprints = self._fingerprints(state)
        inventory = self.package.report.package_inventory()
        inventory.update(
            {
                "story_parts": story_inventory,
                "main_document_paragraph_count": state.main_paragraph_count,
                "table_count": state.table_count,
                "run_element_refs": [
                    {
                        "part_uri": record.part_uri,
                        "paragraph_ordinal": record.paragraph_ordinal,
                        "run_index": record.run_index,
                        "element_ref": record.element_ref.model_dump(mode="json"),
                    }
                    for record in state.run_refs
                ],
            }
        )
        features = sorted(set(self.package.report.unsupported_features) | state.features)
        inventory["unsupported_features"] = features
        return DocumentSnapshot(
            revision_id=resolved_revision,
            sha256=self.package.sha256,
            parts=list(self.package.parts),
            paragraphs=state.paragraphs,
            sections=state.sections,
            styles=self.resolver.styles,
            unsupported_features=features,
            fingerprints=fingerprints,
            package_inventory=inventory,
        )

    def index(self, *, revision_id: str | None = None) -> DocumentSnapshot:
        return self.build_snapshot(revision_id=revision_id)

    def _index_story_part(
        self, story: StoryPart, revision_id: str, state: _IndexState
    ) -> None:
        root = self.package.get_xml(story.part_uri, required=True)
        if root is None:
            raise AlineaError(
                "DOCX_MISSING_PART",
                "A story part could not be loaded",
                details={"part_uri": story.part_uri},
            )
        if story.kind == "document":
            body = w_first(root, "body")
            if body is None:
                raise AlineaError(
                    "DOCX_INVALID_OPC",
                    "The main document part has no w:body",
                    details={"part_uri": story.part_uri},
                )
            self._walk_blocks(
                body,
                story.part_uri,
                ["body"],
                revision_id,
                state,
                main_document=True,
            )
            return
        if story.kind in {"footnotes", "endnotes"}:
            note_name = "footnote" if story.kind == "footnotes" else "endnote"
            for index, note in enumerate(w_children(root, note_name)):
                note_type = w_attr(note, "type")
                if note_type in {"separator", "continuationSeparator"}:
                    continue
                note_id = w_attr(note, "id") or str(index)
                self._walk_blocks(
                    note,
                    story.part_uri,
                    [f"{note_name}:{note_id}"],
                    revision_id,
                    state,
                )
            return
        if story.kind == "comments":
            for index, comment in enumerate(w_children(root, "comment")):
                comment_id = w_attr(comment, "id") or str(index)
                self._walk_blocks(
                    comment,
                    story.part_uri,
                    [f"comment:{comment_id}"],
                    revision_id,
                    state,
                )
            return
        self._walk_blocks(root, story.part_uri, [story.kind], revision_id, state)

    def _walk_blocks(
        self,
        parent: etree._Element,
        part_uri: str,
        container_path: list[str],
        revision_id: str,
        state: _IndexState,
        *,
        main_document: bool = False,
    ) -> None:
        counters: dict[str, int] = defaultdict(int)
        for child in parent:
            if not isinstance(child.tag, str):
                continue
            local = local_name(child)
            if local == "p":
                ordinal = self._index_paragraph(
                    child, part_uri, container_path, revision_id, state
                )
                if main_document:
                    state.main_paragraph_count += 1
                    p_pr = w_first(child, "pPr")
                    section = w_first(p_pr, "sectPr") if p_pr is not None else None
                    if section is not None:
                        self._index_section(
                            section,
                            part_uri,
                            container_path,
                            ordinal,
                            revision_id,
                            state,
                        )
                continue
            if local == "tbl":
                table_index = counters["tbl"]
                counters["tbl"] += 1
                state.table_count += 1
                self._walk_table(
                    child,
                    part_uri,
                    [*container_path, f"tbl:{table_index}"],
                    revision_id,
                    state,
                    main_document=main_document,
                )
                continue
            if local == "sectPr" and main_document and local_name(parent) == "body":
                self._index_section(
                    section=child,
                    part_uri=part_uri,
                    container_path=container_path,
                    paragraph_ordinal=max(state.main_paragraph_count - 1, 0),
                    revision_id=revision_id,
                    state=state,
                )
                continue
            if local in {"del", "moveFrom"}:
                continue
            if local in {"sdt", "sdtContent", "customXml", "ins", "moveTo", "smartTag"}:
                wrapper_index = counters[local]
                counters[local] += 1
                self._walk_blocks(
                    child,
                    part_uri,
                    [*container_path, f"{local}:{wrapper_index}"],
                    revision_id,
                    state,
                    main_document=main_document,
                )

    def _walk_table(
        self,
        table: etree._Element,
        part_uri: str,
        container_path: list[str],
        revision_id: str,
        state: _IndexState,
        *,
        main_document: bool,
    ) -> None:
        for row_index, row in enumerate(w_children(table, "tr")):
            for cell_index, cell in enumerate(w_children(row, "tc")):
                self._walk_blocks(
                    cell,
                    part_uri,
                    [*container_path, f"tr:{row_index}", f"tc:{cell_index}"],
                    revision_id,
                    state,
                    main_document=main_document,
                )

    def _index_paragraph(
        self,
        paragraph: etree._Element,
        part_uri: str,
        container_path: list[str],
        revision_id: str,
        state: _IndexState,
    ) -> int:
        ordinal = len(state.paragraphs)
        text = paragraph_text(paragraph)
        normalized = normalize_text(text)
        runs = paragraph_runs(paragraph)
        style_id = self.resolver.paragraph_style_id(paragraph)
        inside_table = any(segment.startswith("tbl:") for segment in container_path)
        features = _features_for(paragraph)
        state.features.update(features)
        style_name = (
            self.resolver.styles[style_id].name if style_id in self.resolver.styles else None
        )
        role, confidence = classify_paragraph(
            text=text,
            style_id=style_id,
            style_name=style_name,
            outline_level=self.resolver.paragraph_outline_level(paragraph),
            inside_table=inside_table,
        )
        element_ref = ElementRef(
            revision_id=revision_id,
            part_uri=part_uri,
            kind="paragraph",
            xml_path=xml_path(paragraph),
            container_path=list(container_path),
            paragraph_ordinal=ordinal,
            run_range=RunRange(start=0, end=len(runs)),
            para_id=paragraph.get(f"{{{W14_NS}}}paraId"),
            text_sha256=text_sha256(text),
            text_excerpt=normalized[:160],
        )
        paragraph_node = ParagraphNode(
            element_ref=element_ref,
            text=text,
            normalized_text=normalized,
            p_style_id=style_id,
            semantic_role=role,
            role_confidence=confidence,
            inside_table=inside_table,
            effective=self.resolver.resolve_paragraph(paragraph, inside_table=inside_table),
            unsupported_features=sorted(features),
        )
        for run_index, run in enumerate(runs):
            current_text = run_text(run)
            run_features = set(_features_for(run))
            ancestor = run.getparent()
            while ancestor is not None and ancestor is not paragraph:
                feature = _FEATURE_ELEMENTS.get(local_name(ancestor))
                if feature:
                    run_features.add(feature)
                ancestor = ancestor.getparent()
            state.features.update(run_features)
            paragraph_node.runs.append(
                RunNode(
                    index=run_index,
                    text=current_text,
                    character_style_id=self.resolver.character_style_id(run),
                    effective=self.resolver.resolve_run(
                        run, paragraph, inside_table=inside_table
                    ),
                    unsupported_features=sorted(run_features),
                )
            )
            state.run_refs.append(
                _RunRefRecord(
                    part_uri=part_uri,
                    paragraph_ordinal=ordinal,
                    run_index=run_index,
                    element_ref=ElementRef(
                        revision_id=revision_id,
                        part_uri=part_uri,
                        kind="paragraph",
                        xml_path=xml_path(run),
                        container_path=list(container_path),
                        paragraph_ordinal=ordinal,
                        run_range=RunRange(start=run_index, end=run_index + 1),
                        para_id=element_ref.para_id,
                        text_sha256=text_sha256(current_text),
                        text_excerpt=normalize_text(current_text)[:160],
                    ),
                )
            )
        state.paragraphs.append(paragraph_node)
        state.part_paragraphs[part_uri].append(paragraph_node)
        return ordinal

    def _index_section(
        self,
        section: etree._Element,
        part_uri: str,
        container_path: list[str],
        paragraph_ordinal: int,
        revision_id: str,
        state: _IndexState,
    ) -> None:
        section_ordinal = len(state.sections)
        section_bytes = etree.tostring(section, encoding="utf-8", with_tail=False)
        state.sections.append(
            SectionNode(
                element_ref=ElementRef(
                    revision_id=revision_id,
                    part_uri=part_uri,
                    kind="section",
                    xml_path=xml_path(section),
                    container_path=list(container_path),
                    paragraph_ordinal=paragraph_ordinal,
                    section_ordinal=section_ordinal,
                    text_sha256="sha256:" + hashlib.sha256(section_bytes).hexdigest(),
                ),
                effective=self.resolver.resolve_section(section),
            )
        )

    def _add_context_hashes(self, state: _IndexState) -> None:
        paragraph_refs = {
            paragraph.element_ref.paragraph_ordinal: paragraph.element_ref
            for paragraph in state.paragraphs
        }
        for paragraphs in state.part_paragraphs.values():
            for index, paragraph in enumerate(paragraphs):
                before = paragraphs[index - 1].text if index else None
                after = paragraphs[index + 1].text if index + 1 < len(paragraphs) else None
                paragraph.element_ref.context_before_sha256 = (
                    text_sha256(before) if before is not None else None
                )
                paragraph.element_ref.context_after_sha256 = (
                    text_sha256(after) if after is not None else None
                )
        for record in state.run_refs:
            paragraph_ref = paragraph_refs[record.paragraph_ordinal]
            record.element_ref.context_before_sha256 = paragraph_ref.context_before_sha256
            record.element_ref.context_after_sha256 = paragraph_ref.context_after_sha256

    def _fingerprints(self, state: _IndexState) -> dict[str, str]:
        fingerprints = {"document_sha256": f"sha256:{self.package.sha256}"}
        structure_pieces: list[str] = []
        for part_uri, paragraphs in state.part_paragraphs.items():
            raw_sequence = "\x1e".join(paragraph.text for paragraph in paragraphs)
            normalized_sequence = "\x1e".join(
                paragraph.normalized_text for paragraph in paragraphs
            )
            fingerprints[f"part_text_raw:{part_uri}"] = text_sha256(raw_sequence)
            fingerprints[f"part_text_normalized:{part_uri}"] = text_sha256(normalized_sequence)
            structure_pieces.extend(
                f"{paragraph.element_ref.part_uri}|{paragraph.element_ref.xml_path}|"
                f"{paragraph.element_ref.text_sha256}"
                for paragraph in paragraphs
            )
        fingerprints["structure"] = text_sha256("\n".join(structure_pieces))
        return fingerprints


def index_document(
    package: OoxmlPackage, *, revision_id: str | None = None
) -> DocumentSnapshot:
    return DocumentIndexer(package).build_snapshot(revision_id=revision_id)


def normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def text_sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def classify_paragraph(
    *,
    text: str,
    style_id: str | None,
    style_name: str | None,
    outline_level: int | None,
    inside_table: bool,
) -> tuple[str, float]:
    style_values = " ".join(value for value in (style_id, style_name) if value)
    heading_match = _HEADING_STYLE_RE.search(style_values)
    chinese_heading_match = _CHINESE_HEADING_STYLE_RE.search(style_values)
    if heading_match:
        return f"heading_{heading_match.group(1)}", 0.99
    if chinese_heading_match:
        numeral = {"一": "1", "二": "2", "三": "3"}.get(
            chinese_heading_match.group(1), chinese_heading_match.group(1)
        )
        return f"heading_{numeral}", 0.99
    if outline_level is not None and 0 <= outline_level <= 2:
        return f"heading_{outline_level + 1}", 0.98
    folded_style = style_values.casefold().replace("_", " ")
    if "caption" in folded_style or "题注" in folded_style:
        return "caption", 0.98
    if any(value in folded_style for value in ("bibliography", "reference", "参考文献")):
        return "reference", 0.95

    stripped = text.strip()
    if not stripped:
        return "unknown", 0.2
    if _REFERENCE_HEADING_RE.fullmatch(stripped):
        return "reference", 0.9
    chinese_heading = _CHINESE_HEADING_RE.match(stripped)
    if chinese_heading:
        level = {"章": 1, "节": 2, "条": 3}[chinese_heading.group(1)]
        return f"heading_{level}", 0.86
    numbered_heading = _NUMBERED_HEADING_RE.match(stripped)
    if numbered_heading:
        level = numbered_heading.group(1).count(".") + 1
        return f"heading_{level}", 0.84
    if _CAPTION_RE.match(stripped):
        return "caption", 0.84
    if _REFERENCE_RE.match(stripped):
        return "reference", 0.85
    if inside_table:
        return "table_text", 0.9
    if folded_style and any(
        value in folded_style for value in ("normal", "body text", "bodytext", "正文")
    ):
        return "body", 0.9
    return "body", 0.55


def _features_for(element: etree._Element) -> list[str]:
    features = {
        feature
        for descendant in element.iter()
        if isinstance(descendant.tag, str)
        and (feature := _FEATURE_ELEMENTS.get(local_name(descendant))) is not None
    }
    return sorted(features)
