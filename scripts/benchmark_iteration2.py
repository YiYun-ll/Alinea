from __future__ import annotations

import hashlib
import json
import platform
import shutil
import time
from collections.abc import Callable
from pathlib import Path

from alinea_mapping.renderer import LibreOfficeRenderer

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".data" / "iteration2-benchmark"


def elapsed[T](action: Callable[[], T]) -> tuple[T, float]:
    started = time.perf_counter()
    result = action()
    return result, round(time.perf_counter() - started, 6)


def main() -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    source = ROOT / "examples" / "alinea-demo.docx"
    cache = WORK / "render-cache"
    renderer = LibreOfficeRenderer(timeout_seconds=120, cache_dir=cache)
    profile, profile_first = elapsed(renderer.describe_profile)
    _, profile_same_instance = elapsed(renderer.describe_profile)
    cached_renderer = LibreOfficeRenderer(timeout_seconds=120, cache_dir=cache)
    _, profile_cached_environment = elapsed(cached_renderer.describe_profile)
    first, pdf_first = elapsed(lambda: renderer.render(source, WORK / "first"))
    second, pdf_cached = elapsed(lambda: cached_renderer.render(source, WORK / "cached"))
    second_cache = WORK / "render-cache-second"
    repeat_renderer = LibreOfficeRenderer(timeout_seconds=120, cache_dir=second_cache)
    third, pdf_empty_repeat = elapsed(lambda: repeat_renderer.render(source, WORK / "second-empty"))
    fourth, pdf_cached_repeat = elapsed(lambda: repeat_renderer.render(source, WORK / "second-cached"))
    assert first.pdf_sha256 == second.pdf_sha256
    assert third.pdf_sha256 == fourth.pdf_sha256
    assert first.page_count == second.page_count == third.page_count == fourth.page_count
    result = {
        "measured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "source": "examples/alinea-demo.docx",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "renderer": profile.renderer_version,
        "render_profile_id": profile.profile_id,
        "font_environment_sha256": profile.font_environment_sha256,
        "page_count": first.page_count,
        "cache_hit_pdf_sha256_identical": True,
        "independent_pdf_sha256_identical": first.pdf_sha256 == third.pdf_sha256,
        "seconds": {
            "profile_first_this_process": profile_first,
            "profile_same_renderer": profile_same_instance,
            "profile_cached_environment_new_renderer": profile_cached_environment,
            "pdf_empty_cache_initial": pdf_first,
            "pdf_empty_cache_repeat": pdf_empty_repeat,
            "pdf_populated_cache_new_renderer": pdf_cached,
            "pdf_populated_cache_repeat": pdf_cached_repeat,
        },
        "notes": [
            "Wall-clock timings on this workstation; not a service-level objective.",
            "Two independent empty PDF caches are measured without discarding outliers.",
            "Warm profile measurements cover the same renderer and shared process environment caches.",
            "Cache hits preserve PDF SHA-256; independent exports need not have identical hashes.",
            "No Microsoft Word comparison, concurrency, remote deployment, or multi-machine benchmark is claimed.",
        ],
    }
    destination = WORK / "results.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
