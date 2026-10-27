from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cached_property

from alinea_contracts.errors import AlineaError
from alinea_contracts.models import PartDescriptor
from lxml import etree

from .security import DocxSource, SafeDocxPackage, SecurityLimits, parse_xml_bytes, read_secure_docx

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W_STRICT_NS = "http://purl.oclc.org/ooxml/wordprocessingml/main"
W_NAMESPACES = frozenset({W_NS, W_STRICT_NS})
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
R_STRICT_NS = "http://purl.oclc.org/ooxml/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"w": W_NS, "r": R_NS, "a": A_NS, "m": M_NS, "w14": W14_NS}

STORY_RELATIONSHIP_KINDS = ("header", "footer", "footnotes", "endnotes", "comments")


@dataclass(frozen=True, slots=True)
class Relationship:
    id: str
    type: str
    target: str
    target_mode: str
    source_part: str
    part_uri: str
    resolved_target: str | None = None

    @property
    def kind(self) -> str:
        return self.type.rsplit("/", 1)[-1]

    @property
    def target_part_uri(self) -> str | None:
        return f"/{self.resolved_target}" if self.resolved_target else None


@dataclass(frozen=True, slots=True)
class StoryPart:
    part_uri: str
    kind: str


class OoxmlPackage:
    def __init__(self, safe_package: SafeDocxPackage) -> None:
        self.safe_package = safe_package
        self.sha256 = safe_package.sha256
        self.report = safe_package.report
        self.main_part_uri = safe_package.report.main_part_uri
        self._names = {part.part_uri.lstrip("/") for part in self.parts}
        self._xml_cache: dict[str, etree._Element | None] = {}

    @classmethod
    def from_source(
        cls, source: DocxSource, *, limits: SecurityLimits | None = None
    ) -> OoxmlPackage:
        return cls(read_secure_docx(source, limits=limits))

    @property
    def data(self) -> bytes:
        return self.safe_package.data

    @property
    def parts(self) -> list[PartDescriptor]:
        return self.report.parts

    def has_part(self, part_uri: str) -> bool:
        return normalize_part_uri(part_uri).lstrip("/") in self._names

    def read_part(self, part_uri: str) -> bytes:
        normalized = normalize_part_uri(part_uri)
        name = normalized.lstrip("/")
        if name not in self._names:
            raise AlineaError(
                "DOCX_MISSING_PART",
                "The requested OPC part is not present",
                details={"part_uri": normalized},
            )
        try:
            with zipfile.ZipFile(io.BytesIO(self.data), mode="r") as archive:
                return archive.read(name)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
            raise AlineaError(
                "DOCX_INVALID_ZIP",
                "A validated DOCX part could not be reopened",
                details={"part_uri": normalized},
            ) from exc

    def get_xml(self, part_uri: str, *, required: bool = False) -> etree._Element | None:
        normalized = normalize_part_uri(part_uri)
        if normalized not in self._xml_cache:
            if not self.has_part(normalized):
                self._xml_cache[normalized] = None
            else:
                self._xml_cache[normalized] = parse_xml_bytes(
                    self.read_part(normalized), part_uri=normalized
                )
        root = self._xml_cache[normalized]
        if root is None and required:
            raise AlineaError(
                "DOCX_MISSING_PART",
                "A required DOCX XML part is missing",
                details={"part_uri": normalized},
            )
        return root

    @cached_property
    def main_root(self) -> etree._Element:
        root = self.get_xml(self.main_part_uri, required=True)
        assert root is not None
        return root

    def relationships_for(self, source_part: str) -> list[Relationship]:
        source = normalize_part_uri(source_part)
        records = []
        for item in self.report.relationships:
            if item["source_part"] != source:
                continue
            records.append(
                Relationship(
                    id=item["id"],
                    type=item["type"],
                    target=item["target"],
                    target_mode=item["target_mode"],
                    source_part=source,
                    part_uri=item["part_uri"],
                    resolved_target=item.get("resolved_target"),
                )
            )
        return records

    def related_parts(self, source_part: str, kind: str) -> list[str]:
        return [
            target
            for relationship in self.relationships_for(source_part)
            if relationship.kind == kind
            and relationship.target_mode.casefold() == "internal"
            and (target := relationship.target_part_uri) is not None
        ]

    def related_part(self, source_part: str, kind: str) -> str | None:
        targets = self.related_parts(source_part, kind)
        return targets[0] if targets else None

    def story_parts(self) -> list[StoryPart]:
        result = [StoryPart(self.main_part_uri, "document")]
        for kind in STORY_RELATIONSHIP_KINDS:
            targets = sorted(set(self.related_parts(self.main_part_uri, kind)))
            result.extend(StoryPart(target, kind) for target in targets)
        return result

    def related_xml(self, source_part: str, kind: str) -> tuple[str, etree._Element] | None:
        target = self.related_part(source_part, kind)
        if target is None:
            return None
        root = self.get_xml(target, required=True)
        assert root is not None
        return target, root


def parse_xml(data: bytes, *, part_uri: str = "<xml>") -> etree._Element:
    return parse_xml_bytes(data, part_uri=part_uri)


def normalize_part_uri(part_uri: str) -> str:
    return part_uri if part_uri.startswith("/") else f"/{part_uri}"


def qn(name: str) -> str:
    if ":" in name:
        prefix, local = name.split(":", 1)
        namespace = NS.get(prefix)
        if namespace is None:
            raise ValueError(f"Unknown OOXML namespace prefix: {prefix}")
        return f"{{{namespace}}}{local}"
    return f"{{{W_NS}}}{name}"


def local_name(element: etree._Element) -> str:
    return etree.QName(element).localname


def is_w(element: etree._Element, name: str | None = None) -> bool:
    if not isinstance(element.tag, str):
        return False
    qname = etree.QName(element)
    return qname.namespace in W_NAMESPACES and (name is None or qname.localname == name)


def w_attr(element: etree._Element, name: str, default: str | None = None) -> str | None:
    for namespace in W_NAMESPACES:
        value = element.get(f"{{{namespace}}}{name}")
        if value is not None:
            return value
    return default


def w_children(element: etree._Element, name: str) -> Iterator[etree._Element]:
    return (child for child in element if is_w(child, name))


def w_first(element: etree._Element, name: str) -> etree._Element | None:
    return next(w_children(element, name), None)


def w_descendants(element: etree._Element, name: str) -> Iterator[etree._Element]:
    return (descendant for descendant in element.iter() if is_w(descendant, name))


def nearest_paragraph(element: etree._Element) -> etree._Element | None:
    current: etree._Element | None = element
    while current is not None:
        if is_w(current, "p"):
            return current
        current = current.getparent()
    return None


def paragraph_runs(paragraph: etree._Element) -> list[etree._Element]:
    return [
        run
        for run in w_descendants(paragraph, "r")
        if nearest_paragraph(run) is paragraph
    ]


def run_text(run: etree._Element) -> str:
    pieces: list[str] = []
    owner = nearest_paragraph(run)
    for element in run.iter():
        if not is_w(element):
            continue
        if nearest_paragraph(element) is not owner:
            continue
        local = local_name(element)
        if local == "t":
            pieces.append(element.text or "")
        elif local == "tab":
            pieces.append("\t")
        elif local in {"br", "cr"}:
            pieces.append("\n")
        elif local == "noBreakHyphen":
            pieces.append("‑")
        elif local == "softHyphen":
            pieces.append("­")
    return "".join(pieces)


def paragraph_text(paragraph: etree._Element) -> str:
    return "".join(run_text(run) for run in paragraph_runs(paragraph))


def xml_path(element: etree._Element) -> str:
    segments: list[str] = []
    current: etree._Element | None = element
    while current is not None:
        qname = etree.QName(current)
        prefix = _namespace_prefix(current, qname.namespace)
        segment = f"{prefix}:{qname.localname}"
        parent = current.getparent()
        if parent is not None:
            position = 1
            for sibling in current.itersiblings(preceding=True):
                if not isinstance(sibling.tag, str):
                    continue
                sibling_qname = etree.QName(sibling)
                if (sibling_qname.namespace, sibling_qname.localname) == (
                    qname.namespace,
                    qname.localname,
                ):
                    position += 1
            segment = f"{segment}[{position}]"
        segments.append(segment)
        current = parent
    return "/" + "/".join(reversed(segments))


def _namespace_prefix(element: etree._Element, namespace: str | None) -> str:
    if namespace in W_NAMESPACES:
        return "w"
    known = {
        R_NS: "r",
        R_STRICT_NS: "r",
        A_NS: "a",
        M_NS: "m",
        W14_NS: "w14",
        XML_NS: "xml",
    }
    if namespace in known:
        return known[namespace]
    return element.prefix or "ns"
