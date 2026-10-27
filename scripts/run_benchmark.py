from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import sys
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pdfplumber
from alinea_contracts import (
    AlineaError,
    DocumentSnapshot,
    FormatRule,
    InspectionResult,
    RuleSet,
)
from alinea_docx import parse_docx
from alinea_docx.inspector import inspect_document
from alinea_docx.rules import compute_ruleset_digest, validate_rule
from alinea_mapping import LibreOfficeRenderer, locate_issues

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
REPORTS = ROOT / "reports"


def build_ruleset(manifest: dict[str, Any]) -> RuleSet:
    rules: list[FormatRule] = []
    for selector, properties in manifest["rule_baseline"].items():
        for property_name, expected in properties.items():
            if property_name == "paragraph.line_spacing":
                expected = {"type": "MULTIPLE", "value": expected}
            rule_id = re.sub(
                "[^A-Za-z0-9_-]+", "_", f"golden_{selector}_{property_name}"
            ).strip("_")
            rules.append(
                validate_rule(
                    {
                        "rule_id": rule_id,
                        "selector": selector,
                        "property": property_name,
                        "expected": expected,
                        "source": {
                            "source_type": "preset",
                            "reference": "tests/fixtures/golden/manifest.json",
                            "quote": "KNOWN_GENERATOR_INPUT imaginary fixture baseline",
                        },
                    }
                )
            )
    return RuleSet(
        rule_set_id="golden-baseline",
        project_id="benchmark",
        version=1,
        name="Imaginary golden baseline",
        status="APPROVED",
        digest=compute_ruleset_digest(rules),
        rules=rules,
    )


def compact(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split())


def actual_matches(expected: Any, actual: Any, property_name: str) -> bool:
    if property_name == "paragraph.line_spacing" and isinstance(actual, dict):
        actual = actual.get("value")
    if property_name == "paragraph.alignment" and expected == "both":
        expected = "justify"
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) <= 0.05
    return expected == actual


def evaluate_sample(
    sample: dict[str, Any], ruleset: RuleSet
) -> tuple[dict[str, Any], DocumentSnapshot | None, InspectionResult | None]:
    path = FIXTURES / sample["file"]
    started = time.monotonic()
    record: dict[str, Any] = {
        "sample_id": sample["sample_id"],
        "category": sample["category"],
        "file": sample["file"],
        "expected_errors": sample["expected_errors"],
        "expected_issue_count": sample["expected_issue_count"],
        "expected_unverifiable_count": sample["expected_unverifiable_count"],
    }
    try:
        snapshot = parse_docx(path, revision_id=sample["sample_id"])
        inspection = inspect_document(snapshot, ruleset)
    except AlineaError as exc:
        record.update(
            {
                "blocked": True,
                "error_code": exc.code,
                "error_details": exc.details,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                "confirmed_count": 0,
                "unknown_count": 0,
                "matched_targets": [],
                "missed_targets": [],
                "false_positive_issue_ids": [],
                "automatic_repair_allowed": False,
            }
        )
        return record, None, None

    expectations = sample["expectations"]
    paragraphs = {
        (paragraph.element_ref.part_uri, paragraph.element_ref.paragraph_ordinal): paragraph
        for paragraph in snapshot.paragraphs
    }
    confirmed = [
        issue
        for issue in inspection.issues
        if issue.detection_status == "CONFIRMED_VIOLATION"
        and issue.property in sample["expected_supported_properties"]
    ]
    matched_issue_ids: set[str] = set()
    matched_targets: list[str] = []
    missed_targets: list[str] = []
    for expectation in expectations:
        if expectation["status"] != "VIOLATION":
            continue
        matched = None
        for issue in confirmed:
            if issue.issue_id in matched_issue_ids or issue.property != expectation["property"]:
                continue
            reference = issue.element_ref
            if expectation["selector"] == "section":
                anchor_matches = reference.kind == "section"
            else:
                paragraph = paragraphs.get((reference.part_uri, reference.paragraph_ordinal))
                anchor_matches = paragraph is not None and compact(
                    expectation["paragraph_text_anchor"]
                ) in compact(paragraph.text)
            run_index = expectation["run_index"]
            run_matches = (
                run_index is None
                or reference.run_range is not None
                and reference.run_range.start == run_index
            )
            if anchor_matches and run_matches and actual_matches(
                expectation["actual"], issue.actual.value, expectation["property"]
            ):
                matched = issue
                break
        if matched is None:
            missed_targets.append(expectation["target_id"])
        else:
            matched_issue_ids.add(matched.issue_id)
            matched_targets.append(expectation["target_id"])

    false_positives = [
        issue.issue_id for issue in confirmed if issue.issue_id not in matched_issue_ids
    ]
    unknown = [issue for issue in inspection.issues if issue.detection_status == "UNKNOWN"]
    automatic_allowed = bool(snapshot.package_inventory.get("automatic_repair_allowed", False))
    record.update(
        {
            "blocked": False,
            "error_code": None,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            "confirmed_count": len(confirmed),
            "unknown_count": len(unknown),
            "matched_targets": matched_targets,
            "missed_targets": missed_targets,
            "false_positive_issue_ids": false_positives,
            "automatic_repair_allowed": automatic_allowed,
            "safe_repair_issue_count": sum(
                issue.repair.eligibility == "SAFE_SINGLE_TARGET"
                for issue in inspection.issues
            ),
        }
    )
    return record, snapshot, inspection


def render_demo(
    snapshot: DocumentSnapshot,
    inspection: InspectionResult,
) -> dict[str, Any]:
    from app.config import get_settings

    settings = get_settings()
    work = ROOT / ".data" / "benchmark"
    render_dir = work / "render"
    render_dir.mkdir(parents=True, exist_ok=True)
    renderer = LibreOfficeRenderer(
        settings.soffice_path,
        timeout_seconds=settings.render_timeout_seconds,
        max_pages=settings.max_pages,
        cache_dir=work / "cache",
    )
    started = time.monotonic()
    artifact = renderer.render(ROOT / "examples" / "alinea-demo.docx", render_dir)
    elapsed = time.monotonic() - started
    mapped = locate_issues(
        snapshot,
        inspection.issues,
        artifact.pdf_path,
        artifact.pdf_sha256,
        artifact.render_profile_id,
    )
    with pdfplumber.open(artifact.pdf_path) as pdf:
        page_text = [compact(page.extract_text() or "") for page in pdf.pages]
    paragraphs = {
        (paragraph.element_ref.part_uri, paragraph.element_ref.paragraph_ordinal): paragraph
        for paragraph in snapshot.paragraphs
    }
    located = [issue for issue in mapped if issue.location.status == "LOCATED"]
    correct = 0
    location_records = []
    for issue in mapped:
        paragraph = paragraphs.get(
            (issue.element_ref.part_uri, issue.element_ref.paragraph_ordinal)
        )
        anchor = compact(paragraph.text) if paragraph is not None else ""
        verified = False
        if issue.location.status == "LOCATED" and anchor:
            verified = any(
                anchor in page_text[fragment.page_index]
                for fragment in issue.location.fragments
            )
        correct += int(verified)
        location_records.append(
            {
                "issue_id": issue.issue_id,
                "property": issue.property,
                "status": issue.location.status,
                "score": issue.location.score,
                "page_indices": [
                    fragment.page_index for fragment in issue.location.fragments
                ],
                "text_anchor_verified": verified,
            }
        )
    artifact_dir = REPORTS / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(artifact.pdf_path, artifact_dir / "alinea-demo-preview.pdf")
    violations = sum(
        issue.detection_status == "CONFIRMED_VIOLATION" for issue in inspection.issues
    )
    return {
        "page_count": artifact.page_count,
        "render_elapsed_seconds": round(elapsed, 3),
        "render_profile_id": artifact.render_profile_id,
        "preview_pdf_sha256": artifact.pdf_sha256,
        "violation_count": violations,
        "located_count": len(located),
        "location_accuracy": correct / len(located) if located else None,
        "location_coverage": len(located) / violations if violations else None,
        "verified_location_count": correct,
        "locations": location_records,
        "warnings": artifact.warnings,
    }


def write_reports(payload: dict[str, Any]) -> None:
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "golden-results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    metrics = payload["metrics"]

    def percent(value: float | None) -> str:
        return "未测量" if value is None else f"{value * 100:.2f}%"

    lines = [
        "# Alinea 实测基准报告",
        "",
        f"生成时间：{payload['generated_at']}",
        "",
        "本报告由 `scripts/run_benchmark.py` 从实际样本重新计算。"
        "样本是生成器已知输入，未经人工 Microsoft Word 核验；结果不能泛化到任意复杂 DOCX。",
        "",
        "## 环境",
        "",
        f"- OS：{payload['environment']['platform']}",
        f"- Python：{payload['environment']['python']}",
        f"- LibreOffice：{payload['environment'].get('libreoffice') or '未调用'}",
        "- Docker / 公网部署：未构建、未发布，因此不做容器或线上验收声明。",
        "",
        "## 静态检测与保护",
        "",
        f"- 样本：{payload['sample_count']}；演示目标：10。",
        f"- TP / FP / FN：{metrics['tp']} / {metrics['fp']} / {metrics['fn']}",
        f"- Precision：{percent(metrics['precision'])}；Recall：{percent(metrics['recall'])}。",
        f"- 高风险阻断：{metrics['high_risk_blocked']} / {metrics['high_risk_total']}。",
        f"- UNKNOWN：{metrics['unknown_count']}（不计入确定违规）。",
        "",
        "## 真实渲染与定位",
        "",
    ]
    if payload.get("render") is None:
        lines.append("本次未执行真实渲染；定位指标保持未测量。")
    else:
        render = payload["render"]
        lines.extend(
            [
                f"- 实际页数：{render['page_count']}；"
                f"转换耗时：{render['render_elapsed_seconds']} 秒。",
                f"- 高置信定位：{render['located_count']} / {render['violation_count']}。",
                f"- 文本锚点复核正确率：{percent(render['location_accuracy'])}；"
                f"覆盖率：{percent(render['location_coverage'])}。",
                "- 页数变化本身不作为失败；坐标仍需浏览器缩放/旋转和人工视觉复核。",
            ]
        )
    failures = [
        sample
        for sample in payload["samples"]
        if sample["category"] != "high_risk"
        and (sample["missed_targets"] or sample["false_positive_issue_ids"])
    ]
    lines.extend(["", "## 失败与限制", ""])
    if failures:
        for sample in failures:
            lines.append(
                f"- {sample['sample_id']}：漏检 {sample['missed_targets']}；"
                f"额外 Issue {sample['false_positive_issue_ids']}。"
            )
    else:
        lines.append("- 本轮受支持 golden 静态目标没有漏检或额外确定违规。")
    for sample in payload["samples"]:
        if sample["category"] == "high_risk" and sample["confirmed_count"]:
            lines.append(
                f"- {sample['sample_id']} 有 {sample['confirmed_count']} 条只读诊断；"
                "不计入检测指标，且没有安全自动修复入口。"
            )
    lines.extend(
        [
            "- 未进行人工 Microsoft Word 视觉核验、30 页 P95 性能测量或生产容器压测。",
            "- 复杂 OOXML、缺失字体和 Word/LibreOffice 分页差异仍按支持矩阵降级。",
            "",
        ]
    )
    (REPORTS / "benchmark.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((FIXTURES / "golden" / "manifest.json").read_text(encoding="utf-8"))
    ruleset = build_ruleset(manifest)
    records = []
    demo_snapshot = None
    demo_inspection = None
    for sample in manifest["samples"]:
        record, _, _ = evaluate_sample(sample, ruleset)
        records.append(record)
    demo = json.loads((ROOT / "examples" / "alinea-demo.golden.json").read_text(encoding="utf-8"))
    demo_sample = {
        "sample_id": "DEMO",
        "category": "golden_demo",
        "file": "../../examples/alinea-demo.docx",
        "expected_errors": [],
        "expected_issue_count": demo["expected_issue_count"],
        "expected_unverifiable_count": 0,
        "expected_supported_properties": sorted(
            {target["property"] for target in demo["targets"]}
        ),
        "expectations": demo["targets"],
    }
    demo_record, demo_snapshot, demo_inspection = evaluate_sample(demo_sample, ruleset)
    records.append(demo_record)

    evaluated = [record for record in records if record["category"] != "high_risk"]
    tp = sum(len(record["matched_targets"]) for record in evaluated)
    fp = sum(len(record["false_positive_issue_ids"]) for record in evaluated)
    fn = sum(len(record["missed_targets"]) for record in evaluated)
    high_risk = [record for record in records if record["category"] == "high_risk"]
    high_risk_blocked = sum(
        bool(record["blocked"]) or record["safe_repair_issue_count"] == 0
        for record in high_risk
    )
    external_renderer_blocked = False
    try:
        LibreOfficeRenderer(ROOT / ".data" / "missing-soffice").render(
            FIXTURES / "data" / "high_risk" / "h03-external-image.docx",
            ROOT / ".data" / "benchmark" / "external-guard",
        )
    except AlineaError as exc:
        external_renderer_blocked = exc.code == "DOCX_UNSAFE_EXTERNAL_RESOURCE"
    render_result = None
    if args.render:
        assert demo_snapshot is not None and demo_inspection is not None
        render_result = render_demo(demo_snapshot, demo_inspection)
    metrics = {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "high_risk_blocked": high_risk_blocked,
        "high_risk_total": len(high_risk),
        "external_renderer_blocked": external_renderer_blocked,
        "unknown_count": sum(record["unknown_count"] for record in records),
    }
    libreoffice = None
    if render_result is not None:
        renderer = LibreOfficeRenderer()
        libreoffice = renderer.describe_profile().renderer_version
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "libreoffice": libreoffice,
        },
        "sample_count": len(manifest["samples"]),
        "truth_scope": "KNOWN_GENERATOR_INPUT; no manual Microsoft Word verification",
        "metrics": metrics,
        "render": render_result,
        "samples": records,
    }
    write_reports(payload)
    print(json.dumps({"metrics": metrics, "render": render_result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
