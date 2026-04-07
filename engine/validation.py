"""Cambrian adoption 재검증 레이어.

현재 latest adoption에 대해 기존 scenario/snapshot 자산을 재사용해
fresh run을 실행하고, verdict(healthy/watch/regressed/inconclusive/error)를 산출한다.
adoption state는 절대 수정하지 않는다.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

REGRESSION_THRESHOLD: float = 0.15
WATCH_THRESHOLD: float = 0.05


class ValidationError(Exception):
    """재검증 실행 중 복구 불가 오류."""

    pass


def load_comparison_basis(adoption: dict, adoptions_dir: str = "adoptions") -> dict:
    """adoption record에서 comparison basis를 탐색한다.

    Priority 1: eval_snapshot_path → 파일 존재 + metrics 파싱
    Priority 2: decision_ref → decision JSON → champion metrics
    Priority 3: inline metrics 필드
    Priority 4: source="none"

    Args:
        adoption: adoption record dict
        adoptions_dir: adoption record 디렉토리

    Returns:
        {"source": str, "ref_path": str|None, "basis_metrics": dict}
    """
    adopt_dir = Path(adoptions_dir)

    # Priority 1: eval_snapshot_path
    snap_path = adoption.get("eval_snapshot_path")
    if snap_path:
        p = Path(snap_path)
        if not p.is_absolute():
            p = adopt_dir / p
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                metrics = _extract_metrics_from_snapshot(data)
                if metrics:
                    return {
                        "source": "eval_snapshot",
                        "ref_path": str(p),
                        "basis_metrics": metrics,
                    }
            except Exception:
                pass

    # Priority 2: decision_ref
    dec_ref = adoption.get("decision_ref") or (
        (adoption.get("decision_provenance") or {}).get("decision_file")
    )
    if dec_ref:
        p = Path(dec_ref)
        if not p.is_absolute():
            p = adopt_dir / p
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                metrics = _extract_metrics_from_decision(data)
                if metrics:
                    return {
                        "source": "decision_ref",
                        "ref_path": str(p),
                        "basis_metrics": metrics,
                    }
            except Exception:
                pass

    # Priority 3: inline metrics
    inline = adoption.get("metrics")
    if isinstance(inline, dict) and inline:
        return {
            "source": "inline_metrics",
            "ref_path": None,
            "basis_metrics": inline,
        }

    # Priority 4: 없음
    return {"source": "none", "ref_path": None, "basis_metrics": {}}


def _extract_metrics_from_snapshot(data: dict) -> dict:
    """snapshot/report에서 핵심 metrics를 추출한다.

    Args:
        data: snapshot 또는 eval 결과 dict

    Returns:
        metrics dict (비어있으면 {})
    """
    metrics: dict = {}
    if "success_rate" in data:
        metrics["success_rate"] = float(data["success_rate"])
    if "avg_execution_ms" in data:
        metrics["avg_execution_ms"] = float(data["avg_execution_ms"])
    if "pass_rate" in data:
        metrics["pass_rate"] = float(data["pass_rate"])
    # eval_result 중첩 확인
    eval_r = data.get("eval_result")
    if isinstance(eval_r, dict) and "pass_rate" in eval_r:
        metrics["eval_pass_rate"] = float(eval_r["pass_rate"])
    return metrics


def _extract_metrics_from_decision(data: dict) -> dict:
    """decision JSON에서 champion metrics를 추출한다.

    Args:
        data: decision dict

    Returns:
        metrics dict
    """
    champion = data.get("champion")
    if not isinstance(champion, dict):
        return {}
    metrics: dict = {}
    if "success_rate" in champion:
        metrics["success_rate"] = float(champion["success_rate"])
    if "eval_pass_rate" in champion:
        metrics["eval_pass_rate"] = float(champion["eval_pass_rate"])
    if "avg_execution_ms" in champion:
        metrics["avg_execution_ms"] = float(champion["avg_execution_ms"])
    return metrics


def run_fresh_validation(
    scenario_ref: str | None,
    spec_override: str | None,
    skill_name: str,
    engine: object | None = None,
) -> dict:
    """기존 scenario runner를 재사용해 fresh run을 실행한다.

    Args:
        scenario_ref: 원본 scenario spec 경로
        spec_override: CLI --spec으로 지정된 override 경로
        skill_name: 대상 스킬 이름
        engine: CambrianEngine 인스턴스 (None이면 생성 시도)

    Returns:
        {"run_id": str, "report_path": str|None, "fresh_metrics": dict}

    Raises:
        ValidationError: scenario run 실패 시
    """
    spec_path = spec_override or scenario_ref
    if not spec_path:
        raise ValidationError(
            "scenario spec을 찾을 수 없음 (--spec으로 지정하라)"
        )

    path = Path(spec_path)
    if not path.exists():
        raise ValidationError(f"scenario spec 파일 없음: {spec_path}")

    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValidationError(f"scenario spec 파싱 실패: {exc}") from exc

    if engine is None:
        raise ValidationError("engine이 제공되지 않음")

    from engine.scenario import ScenarioRunner

    runner = ScenarioRunner(engine)
    report = runner.run_scenario(spec, scenario_path=str(path))

    if not report.get("success", False):
        errors = report.get("errors", [])
        raise ValidationError(
            f"scenario run 실패: {'; '.join(errors) if errors else 'unknown'}"
        )

    import uuid
    run_id = f"reval-{uuid.uuid4().hex[:8]}"
    fresh_metrics = _extract_metrics_from_snapshot(report)

    return {
        "run_id": run_id,
        "report_path": None,
        "fresh_metrics": fresh_metrics,
    }


def compute_verdict(
    basis_metrics: dict,
    fresh_metrics: dict,
    regression_threshold: float = REGRESSION_THRESHOLD,
    watch_threshold: float = WATCH_THRESHOLD,
    policy: dict | None = None,
) -> dict:
    """basis와 fresh metrics를 비교하여 verdict를 산출한다.

    policy가 제공되면 validation 섹션의 threshold를 사용한다.

    Args:
        basis_metrics: 채택 당시 metrics
        fresh_metrics: fresh run metrics
        regression_threshold: 회귀 판정 임계값 (기본 0.15)
        watch_threshold: 관찰 판정 임계값 (기본 0.05)

    Returns:
        {"metric_deltas": dict, "verdict": str, "verdict_reason": str,
         "recommended_action": str}
    """
    # policy 기반 threshold override
    if policy is not None:
        val_policy = policy.get("validation", {})
        if "regressed_degradation_pct" in val_policy:
            regression_threshold = val_policy["regressed_degradation_pct"]
        if "watch_degradation_pct" in val_policy:
            watch_threshold = val_policy["watch_degradation_pct"]

    if not basis_metrics or not fresh_metrics:
        return {
            "metric_deltas": {},
            "verdict": "inconclusive",
            "verdict_reason": (
                "comparison basis or fresh metrics unavailable"
            ),
            "recommended_action": "investigate",
            "applied_thresholds": {
                "watch_degradation_pct": watch_threshold,
                "regressed_degradation_pct": regression_threshold,
            },
        }

    # latency류: 높아지면 악화 (inverted)
    inverted_metrics = {"avg_execution_ms", "latency_ms", "error_rate"}

    metric_deltas: dict = {}
    worst_verdict = "healthy"
    worst_reason = ""

    all_keys = set(basis_metrics.keys()) | set(fresh_metrics.keys())
    for key in sorted(all_keys):
        basis_val = basis_metrics.get(key)
        fresh_val = fresh_metrics.get(key)

        if basis_val is None or fresh_val is None:
            metric_deltas[key] = {
                "basis": basis_val,
                "fresh": fresh_val,
                "delta_pct": 0.0,
                "direction": "unknown",
            }
            continue

        basis_f = float(basis_val)
        fresh_f = float(fresh_val)
        delta_pct = (fresh_f - basis_f) / max(abs(basis_f), 1e-9)

        # 방향 판정
        if key in inverted_metrics:
            # 높아지면 악화
            if delta_pct > 0:
                direction = "worse"
            elif delta_pct < 0:
                direction = "better"
            else:
                direction = "neutral"
        else:
            # 낮아지면 악화
            if delta_pct < 0:
                direction = "worse"
            elif delta_pct > 0:
                direction = "better"
            else:
                direction = "neutral"

        metric_deltas[key] = {
            "basis": basis_f,
            "fresh": fresh_f,
            "delta_pct": round(delta_pct, 4),
            "direction": direction,
        }

        # worst-case verdict
        if direction == "worse":
            abs_delta = abs(delta_pct)
            if abs_delta >= regression_threshold:
                if worst_verdict != "regressed":
                    worst_verdict = "regressed"
                    worst_reason = (
                        f"{key} {abs_delta * 100:.1f}% 악화 "
                        f"(임계값 {regression_threshold * 100:.0f}% 초과)"
                    )
            elif abs_delta >= watch_threshold:
                if worst_verdict == "healthy":
                    worst_verdict = "watch"
                    worst_reason = (
                        f"{key} {abs_delta * 100:.1f}% 악화 "
                        f"(관찰 필요)"
                    )

    if worst_verdict == "healthy":
        worst_reason = "모든 metric이 임계값 이내"

    action_map = {
        "healthy": "maintain",
        "watch": "re-experiment",
        "regressed": "consider-rollback",
        "inconclusive": "investigate",
        "error": "investigate",
    }

    return {
        "metric_deltas": metric_deltas,
        "verdict": worst_verdict,
        "verdict_reason": worst_reason,
        "recommended_action": action_map.get(worst_verdict, "investigate"),
        "applied_thresholds": {
            "watch_degradation_pct": watch_threshold,
            "regressed_degradation_pct": regression_threshold,
        },
    }


def save_validation_record(record: dict, out_dir: str = "adoptions/validations") -> str:
    """validation record를 JSON 파일로 저장한다.

    Args:
        record: validation record dict
        out_dir: 저장 디렉토리

    Returns:
        저장된 파일 절대 경로
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    skill_name = record.get("skill_name", "unknown")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"validation_{skill_name}_{ts}.json"
    filepath = out / filename

    filepath.write_text(
        json.dumps(record, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return str(filepath.resolve())
