from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_pack_template_benchmark_slice_ready_doc_exists_and_names_scope() -> None:
    text = _read("docs/release/PACK_TEMPLATE_BENCHMARK_SLICE_READY.md")

    for phrase in [
        "Pack Template Benchmark Slice Readiness",
        "engine/project_pack_*",
        "engine/project_template_*",
        "engine/project_benchmark*",
        "Do Not Include",
    ]:
        assert phrase in text


def test_pack_template_benchmark_slice_ready_records_split_validation_results() -> None:
    text = _read("docs/release/PACK_TEMPLATE_BENCHMARK_SLICE_READY.md")

    for phrase in [
        "Pack chunk 1: 74 passed",
        "Pack total:",
        "251 passed",
        "Template chunk 1: 62 passed",
        "Template total:",
        "185 passed",
        "47 passed in 41.65s",
        "483 passed",
        "GO for review/staging as Slice 4",
    ]:
        assert phrase in text


def test_pack_template_benchmark_slice_ready_records_product_boundaries() -> None:
    text = _read("docs/release/PACK_TEMPLATE_BENCHMARK_SLICE_READY.md")

    for phrase in [
        "advanced surfaces",
        "not become the default launch path",
        "not fake public proof claims",
        "does not call provider APIs",
        "apply source patches by itself",
        "split-run validation evidence",
    ]:
        assert phrase in text


def test_rc_checklist_links_pack_template_benchmark_slice_gate() -> None:
    checklist = _read("docs/release/RC_CHECKLIST.md")

    for phrase in [
        "Pack Template Benchmark Slice Gate",
        "docs/release/PACK_TEMPLATE_BENCHMARK_SLICE_READY.md",
        "pack/template/benchmark split-run test gate is PASS",
        "staged diff contains only Slice 4 files",
    ]:
        assert phrase in checklist
