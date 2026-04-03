"""실용 스킬 통합 테스트.

csv_to_chart, json_to_dashboard, landing_page 스킬은 mode "a" (LLM 기반)이므로
ANTHROPIC_API_KEY가 설정된 환경에서만 실행된다.
"""

import os
from pathlib import Path

import pytest

from engine.loop import CambrianEngine


requires_api_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — mode a skills require LLM",
)


@pytest.fixture
def engine(schemas_dir: Path, tmp_path: Path) -> CambrianEngine:
    """테스트용 CambrianEngine."""
    return CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir="skills",
        skill_pool_dir=tmp_path / "pool",
    )


# ---------------------------------------------------------------------------
# csv_to_chart
# ---------------------------------------------------------------------------

CSV_SAMPLE = "Month,Revenue,Cost\nJan,100,80\nFeb,120,90\nMar,150,100"


@requires_api_key
def test_csv_to_chart_basic(engine: CambrianEngine) -> None:
    """csv_to_chart가 Chart.js HTML을 반환한다."""
    result = engine.run_task(
        domain="data_visualization",
        tags=["csv", "chart"],
        input_data={"csv_data": CSV_SAMPLE},
    )

    assert result.success is True
    assert result.output is not None
    html = result.output.get("html", "")
    assert len(html) > 100


@requires_api_key
def test_csv_to_chart_labels(engine: CambrianEngine) -> None:
    """csv_to_chart가 row_count를 반환한다."""
    result = engine.run_task(
        domain="data_visualization",
        tags=["csv"],
        input_data={"csv_data": CSV_SAMPLE, "title": "Test Chart"},
    )

    assert result.success is True
    assert result.output is not None


@requires_api_key
def test_csv_to_chart_types(engine: CambrianEngine) -> None:
    """csv_to_chart가 다양한 차트 타입을 지원한다."""
    for chart_type in ("bar", "line", "pie", "doughnut"):
        result = engine.run_task(
            domain="data_visualization",
            tags=["csv", "chart"],
            input_data={"csv_data": CSV_SAMPLE, "chart_type": chart_type},
        )
        assert result.success is True, f"chart_type={chart_type} 실패"


# ---------------------------------------------------------------------------
# json_to_dashboard
# ---------------------------------------------------------------------------

DASHBOARD_INPUT = {
    "title": "Service Status",
    "metrics": [
        {"label": "DAU", "value": "12,430", "change": "+8.2%"},
        {"label": "Conversion", "value": "3.4%", "change": "-0.1%"},
        {"label": "Revenue", "value": "$5.2M", "change": "+12.3%"},
    ],
    "theme": "blue",
}


@requires_api_key
def test_json_to_dashboard_basic(engine: CambrianEngine) -> None:
    """json_to_dashboard가 대시보드 HTML을 반환한다."""
    result = engine.run_task(
        domain="data_visualization",
        tags=["json", "dashboard"],
        input_data=DASHBOARD_INPUT,
    )

    assert result.success is True
    assert result.output is not None
    assert "html" in result.output


@requires_api_key
def test_json_to_dashboard_metric_count(engine: CambrianEngine) -> None:
    """json_to_dashboard가 metric_count를 반환한다."""
    result = engine.run_task(
        domain="data_visualization",
        tags=["dashboard", "metrics"],
        input_data=DASHBOARD_INPUT,
    )

    assert result.success is True
    assert result.output is not None
    assert result.output.get("metric_count") == 3


@requires_api_key
def test_json_to_dashboard_themes(engine: CambrianEngine) -> None:
    """json_to_dashboard가 4개 테마를 지원한다."""
    for theme in ("blue", "green", "purple", "dark"):
        result = engine.run_task(
            domain="data_visualization",
            tags=["json", "dashboard"],
            input_data={**DASHBOARD_INPUT, "theme": theme},
        )
        assert result.success is True, f"theme={theme} 실패"


# ---------------------------------------------------------------------------
# landing_page
# ---------------------------------------------------------------------------

LANDING_INPUT = {
    "product_name": "Cambrian",
    "tagline": "AI that evolves itself",
    "description": "A self-evolving skill engine for AI agents",
    "features": [
        {"title": "Self-Evolution", "description": "Absorbs external skills automatically"},
        {"title": "Security Scan", "description": "AST-based code security scanning"},
        {"title": "Fitness Tracking", "description": "Continuously measures skill performance"},
    ],
    "cta_text": "Get Started",
    "color": "indigo",
}


@requires_api_key
def test_landing_page_basic(engine: CambrianEngine) -> None:
    """landing_page가 HTML을 반환한다."""
    result = engine.run_task(
        domain="design",
        tags=["landing", "html"],
        input_data=LANDING_INPUT,
    )

    assert result.success is True
    assert result.output is not None
    assert "html" in result.output
    html = result.output["html"]
    assert "Cambrian" in html


@requires_api_key
def test_landing_page_features(engine: CambrianEngine) -> None:
    """landing_page가 기능 섹션을 포함한다."""
    result = engine.run_task(
        domain="design",
        tags=["landing"],
        input_data=LANDING_INPUT,
    )

    assert result.success is True
    assert result.output is not None
    html = result.output["html"]
    assert len(html) > 500


@requires_api_key
def test_landing_page_colors(engine: CambrianEngine) -> None:
    """landing_page가 5개 색상을 지원한다."""
    for color in ("indigo", "blue", "green", "purple", "orange"):
        result = engine.run_task(
            domain="design",
            tags=["landing", "html"],
            input_data={**LANDING_INPUT, "color": color},
        )
        assert result.success is True, f"color={color} 실패"
