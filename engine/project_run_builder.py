"""Cambrian 프로젝트 모드용 실행 TaskSpec 빌더."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from engine.brain.models import TaskSpec


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하며 중복을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


@dataclass
class DiagnoseBuildResult:
    """진단 실행용 TaskSpec 빌드 결과."""

    task_spec: TaskSpec
    selected_sources: list[str]
    selected_tests: list[str]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class DiagnoseTaskSpecBuilder:
    """문맥 스캔 결과를 읽기 전용 진단 TaskSpec으로 변환한다."""

    def build_from_context(
        self,
        *,
        user_request: str,
        context_scan: dict,
        selected_sources: list[str],
        selected_tests: list[str],
        request_id: str,
        project_config: dict,
    ) -> DiagnoseBuildResult:
        """선택된 source/test 후보로 diagnose-only TaskSpec을 만든다."""
        deduped_sources = _dedupe([str(item) for item in selected_sources if item])
        deduped_tests = _dedupe([str(item) for item in selected_tests if item])
        warnings: list[str] = []

        if not deduped_sources:
            warnings.append("진단 실행에 사용할 source 파일이 없습니다.")

        task_spec = TaskSpec(
            task_id=f"task-diagnose-{request_id}",
            goal=f"Diagnose request before patching: {user_request}",
            scope=[
                "Inspect selected source files",
                "Run selected related tests",
                "Collect evidence before proposing a patch",
            ],
            acceptance_criteria=[
                "Selected source files are inspected",
                "Related tests are executed if provided",
                "No source files are modified",
            ],
            related_files=list(deduped_sources),
            related_tests=list(deduped_tests),
            output_paths=[],
            actions=[
                {
                    "type": "inspect_files",
                    "target_paths": list(deduped_sources),
                    "max_bytes_per_file": 12000,
                },
            ]
            if deduped_sources else None,
            hypothesis={
                "id": f"hyp-diagnose-{request_id}",
                "statement": (
                    "Inspecting the selected source files and running related tests "
                    "should collect evidence without modifying the project."
                ),
                "predicts": {
                    "tests": {
                        "failed_max": 999,
                    }
                },
            },
            competitive={"enabled": False},
            generation_seed=None,
            selection_pressure=None,
        )

        return DiagnoseBuildResult(
            task_spec=task_spec,
            selected_sources=deduped_sources,
            selected_tests=deduped_tests,
            warnings=warnings,
        )
