from __future__ import annotations

from alinea_contracts.models import DocumentSnapshot

from .indexing import DocumentIndexer
from .ooxml import OoxmlPackage
from .security import DocxSource, SecurityLimits


class DocxParser:
    def __init__(self, *, limits: SecurityLimits | None = None) -> None:
        self.limits = limits or SecurityLimits()

    def parse(self, source: DocxSource, *, revision_id: str | None = None) -> DocumentSnapshot:
        package = OoxmlPackage.from_source(source, limits=self.limits)
        return DocumentIndexer(package).build_snapshot(revision_id=revision_id)

    def parse_package(
        self, package: OoxmlPackage, *, revision_id: str | None = None
    ) -> DocumentSnapshot:
        return DocumentIndexer(package).build_snapshot(revision_id=revision_id)


def parse_docx(
    source: DocxSource,
    *,
    revision_id: str | None = None,
    limits: SecurityLimits | None = None,
) -> DocumentSnapshot:
    return DocxParser(limits=limits).parse(source, revision_id=revision_id)


def parse_document(
    source: DocxSource,
    *,
    revision_id: str | None = None,
    limits: SecurityLimits | None = None,
) -> DocumentSnapshot:
    return parse_docx(source, revision_id=revision_id, limits=limits)


__all__ = ["DocxParser", "parse_docx", "parse_document"]
