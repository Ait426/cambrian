import json
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_pack_install import SCHEMA_VERSION, _now, _relative
from engine.project_pack_jobs import PackJob, PackJobStore, default_pack_job_path
from engine.project_pack_proof import PackProofBuilder
from engine.project_pack_retrospective import (
    PackJobRetrospectiveBuilder,
    PackRetrospectiveSummaryBuilder,
    latest_pack_retro_summary,
    save_pack_job_retrospective,
    save_pack_retro_summary,
)


def _cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def _job(tmp_path: Path, suffix: str = "ok", **overrides: object) -> PackJob:
    job = PackJob(
        schema_version=SCHEMA_VERSION,
        job_id=f"job-{suffix}",
        created_at=_now(),
        updated_at=None,
        pack_ref="auth-bug-core@0.1.0",
        pack_id="auth-bug-core",
        pack_name="Auth Bug Core",
        pack_kind="team",
        namespace=None,
        version="0.1.0",
        request="로그인 에러 수정해",
        request_class="auth_login_bug",
        lane_id="auth-login",
        lane_label="Python + pytest + auth/login bug fixes",
        readiness_status="ready",
        readiness_ref=None,
        setup_plan_ref=None,
        entry_mode="bridge_prepare",
        linked_bridge_packet_ref=".cambrian/bridge_packets/packet.yaml",
        linked_session_id=None,
        linked_session_ref=".cambrian/sessions/session.yaml",
        linked_request_ref=None,
        active_team="auth-bug-team",
        active_template="auth-bug-template",
        active_workset="auth-bug-workset",
        status="adopted",
        next_command=None,
        next_actions=[],
        usage_event_ref=".cambrian/packs/usage/events/event.yaml",
        linked_bridge_reply_ref=".cambrian/bridge_replies/reply.yaml",
        linked_patch_intent_ref=".cambrian/patch_intents/intent.yaml",
        linked_proposal_ref=".cambrian/patches/proposal.yaml",
        reply_kind="patch_candidate",
        validation_status="validated",
        outcome_snapshot={
            "validated_proposal": True,
            "human_intervention": False,
            "validation_autonomy": True,
            "duration_seconds": 12,
        },
        linked_apply_record_ref=None,
        linked_adoption_record_ref=None,
        apply_status="applied",
        adoption_status="accepted",
        final_status="adopted",
        final_outcome_snapshot={
            "validated_proposal": True,
            "applied": True,
            "adoption_succeeded": True,
            "regression_free_apply": True,
            "human_intervention": False,
            "validation_autonomy": True,
            "duration_seconds": 12,
            "adoption_reason": "validated and applied cleanly",
        },
        closed_at=_now(),
    )
    for key, value in overrides.items():
        setattr(job, key, value)
    saved = PackJobStore().save(job, default_pack_job_path(tmp_path, job))
    PackJobStore().save(job, tmp_path / ".cambrian" / "packs" / "jobs" / "latest.yaml")
    if job.linked_adoption_record_ref is None and job.adoption_status in {"accepted", "rejected", "skipped"}:
        decision = job.adoption_status
        reason = job.final_outcome_snapshot.get("adoption_reason") or job.final_outcome_snapshot.get("rejection_reason")
        adoption = {
            "schema_version": SCHEMA_VERSION,
            "adoption_id": f"adoption-{job.job_id}",
            "created_at": _now(),
            "job_id": job.job_id,
            "job_ref": _relative(saved, tmp_path),
            "pack_id": job.pack_id,
            "proposal_ref": job.linked_proposal_ref,
            "apply_record_ref": job.linked_apply_record_ref,
            "decision": decision,
            "reason": reason,
            "adoption_succeeded": True if decision == "accepted" else False if decision == "rejected" else None,
            "regression_free_apply": job.final_outcome_snapshot.get("regression_free_apply"),
            "warnings": [],
            "errors": [],
        }
        adoption_dir = tmp_path / ".cambrian" / "packs" / "jobs" / "adoptions"
        adoption_dir.mkdir(parents=True, exist_ok=True)
        adoption_path = adoption_dir / f"adoption-{job.job_id}.yaml"
        adoption_path.write_text(yaml.safe_dump(adoption, allow_unicode=True, sort_keys=False), encoding="utf-8")
        job.linked_adoption_record_ref = _relative(adoption_path, tmp_path)
        PackJobStore().save(job, saved)
        PackJobStore().save(job, tmp_path / ".cambrian" / "packs" / "jobs" / "latest.yaml")
    return job


def test_retro_worked_well(tmp_path: Path) -> None:
    job = _job(tmp_path, "worked")

    retro = PackJobRetrospectiveBuilder().build(tmp_path, job.job_id)

    assert "worked_well" in retro.outcome_classification
    assert any(signal.kind == "validation_quality" and signal.status == "positive" for signal in retro.signals)
    assert any(signal.kind == "adoption_quality" and signal.status == "positive" for signal in retro.signals)


def test_retro_validated_but_rejected(tmp_path: Path) -> None:
    job = _job(
        tmp_path,
        "rejected",
        status="rejected",
        adoption_status="rejected",
        final_status="rejected",
        apply_status=None,
        final_outcome_snapshot={
            "validated_proposal": True,
            "applied": False,
            "adoption_succeeded": False,
            "regression_free_apply": None,
            "human_intervention": False,
            "validation_autonomy": True,
            "rejection_reason": "patch too broad",
        },
    )

    retro = PackJobRetrospectiveBuilder().build(tmp_path, job.job_id)

    assert "validated_but_not_adopted" in retro.outcome_classification
    assert any(signal.kind == "adoption_quality" and signal.status == "negative" for signal in retro.signals)


def test_retro_applied_but_rejected(tmp_path: Path) -> None:
    job = _job(
        tmp_path,
        "applied-rejected",
        status="rejected",
        adoption_status="rejected",
        final_status="rejected",
        final_outcome_snapshot={
            "validated_proposal": True,
            "applied": True,
            "adoption_succeeded": False,
            "regression_free_apply": True,
            "human_intervention": False,
            "validation_autonomy": True,
            "rejection_reason": "not needed",
        },
    )

    retro = PackJobRetrospectiveBuilder().build(tmp_path, job.job_id)

    assert "applied_but_rejected" in retro.outcome_classification


def test_retro_regression_issue(tmp_path: Path) -> None:
    job = _job(
        tmp_path,
        "regression",
        final_outcome_snapshot={
            "validated_proposal": True,
            "applied": True,
            "adoption_succeeded": False,
            "regression_free_apply": False,
            "human_intervention": True,
            "validation_autonomy": False,
            "rejection_reason": "regression risk",
        },
    )

    retro = PackJobRetrospectiveBuilder().build(tmp_path, job.job_id)

    assert "regression_or_safety_issue" in retro.outcome_classification
    assert any(signal.kind == "safety_risk" and signal.status == "negative" for signal in retro.signals)


def test_retro_blocked_before_validation(tmp_path: Path) -> None:
    job = _job(
        tmp_path,
        "blocked",
        status="blocked",
        validation_status="blocked",
        apply_status=None,
        adoption_status=None,
        final_status="blocked",
        outcome_snapshot={},
        final_outcome_snapshot={"validated_proposal": False},
    )

    retro = PackJobRetrospectiveBuilder().build(tmp_path, job.job_id)

    assert "blocked_before_validation" in retro.outcome_classification


def test_suggestions_from_negative_context(tmp_path: Path) -> None:
    job = _job(
        tmp_path,
        "outside",
        readiness_status="unsupported",
        warnings=["outside-lane caution"],
        final_outcome_snapshot={"validated_proposal": False, "human_intervention": True},
        validation_status="blocked",
        status="blocked",
        adoption_status=None,
    )

    retro = PackJobRetrospectiveBuilder().build(tmp_path, job.job_id)

    assert any(signal.kind == "context_fit" and signal.status == "negative" for signal in retro.signals)
    assert any(suggestion.kind == "strengthen_context_hints" for suggestion in retro.suggestions)


def test_retro_summary_aggregates(tmp_path: Path) -> None:
    for suffix in ["one", "two"]:
        retro = PackJobRetrospectiveBuilder().build(tmp_path, _job(tmp_path, suffix).job_id)
        save_pack_job_retrospective(tmp_path, retro)
    rejected = PackJobRetrospectiveBuilder().build(
        tmp_path,
        _job(
            tmp_path,
            "three",
            adoption_status="rejected",
            final_status="rejected",
            final_outcome_snapshot={"validated_proposal": True, "applied": True, "adoption_succeeded": False, "regression_free_apply": True, "rejection_reason": "too broad"},
        ).job_id,
    )
    save_pack_job_retrospective(tmp_path, rejected)

    summary = PackRetrospectiveSummaryBuilder().build(tmp_path, "auth-bug-core")

    assert summary.total_retrospectives == 3
    assert summary.outcome_counts["worked_well"] >= 2
    assert summary.signal_counts["adoption_quality"]["positive"] >= 2


def test_pack_proof_consumes_retro_summary(tmp_path: Path) -> None:
    retro = PackJobRetrospectiveBuilder().build(
        tmp_path,
        _job(
            tmp_path,
            "proof-weak",
            readiness_status="unsupported",
            adoption_status="rejected",
            final_status="rejected",
            final_outcome_snapshot={"validated_proposal": True, "applied": True, "adoption_succeeded": False, "regression_free_apply": True, "rejection_reason": "patch too broad"},
            warnings=["outside-lane caution"],
        ).job_id,
    )
    save_pack_job_retrospective(tmp_path, retro)
    summary = PackRetrospectiveSummaryBuilder().build(tmp_path, "auth-bug-core")
    save_pack_retro_summary(tmp_path, summary)

    card = PackProofBuilder().build(tmp_path, "auth-bug-core")
    weak_text = "\n".join([*card.where_weak, *card.known_limits])

    assert "retrospective" in weak_text


def test_pack_job_adopt_suggests_retro(tmp_path: Path) -> None:
    _job(tmp_path, "cli-adopt", status="validated", adoption_status=None, final_status="validated", apply_status=None)

    result = _cli(tmp_path, "pack", "job-adopt", "latest", "--accepted", "--reason", "ok")

    assert result.returncode == 0, result.stderr
    assert "pack job-retro" in result.stdout


def test_source_immutability(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 'unchanged'\n", encoding="utf-8")
    before = source.read_text(encoding="utf-8")
    job = _job(tmp_path, "immutability")

    result = _cli(tmp_path, "pack", "job-retro", job.job_id)
    summary = _cli(tmp_path, "pack", "retro-summary", "auth-bug-core", "--save")

    assert result.returncode == 0, result.stderr
    assert summary.returncode == 0, summary.stderr
    assert source.read_text(encoding="utf-8") == before
    assert latest_pack_retro_summary(tmp_path, "auth-bug-core") is not None
