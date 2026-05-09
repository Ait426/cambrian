from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_pack_proof import PackProofBuilder, PackProofStore, latest_pack_proof_card
from engine.project_pack_release import PackReleaseChecker
from engine.project_pack_usage import record_pack_usage_event


ROOT = Path(__file__).resolve().parents[1]
SEED_MANIFEST = ROOT / "packs" / "auth-bug-core.cambrian-pack.yaml"


def _cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _install_seed_pack(tmp_path: Path) -> None:
    result = _cli(tmp_path, "install", "pack", "auth-bug-core")
    assert result.returncode == 0, result.stderr


def _activate_seed_pack(tmp_path: Path) -> None:
    result = _cli(tmp_path, "pack", "activate", "auth-bug-core")
    assert result.returncode == 0, result.stderr


def _write_session(
    project_root: Path,
    index: int,
    *,
    validated: bool,
    adopted: bool = False,
    apply_passed: bool = False,
    human: bool = False,
    duration_seconds: int = 120,
) -> str:
    session_ref = f".cambrian/sessions/do_session_do-proof-{index}.yaml"
    path = project_root / session_ref
    path.parent.mkdir(parents=True, exist_ok=True)
    start_minute = index
    end_minute = index + max(1, duration_seconds // 60)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "session_id": f"do-proof-{index}",
                "created_at": f"2026-05-03T00:{start_minute:02d}:00+00:00",
                "updated_at": f"2026-05-03T00:{end_minute:02d}:00+00:00",
                "user_request": "fix auth login",
                "status": "ready",
                "current_stage": "patch_proposal_validated" if validated else "diagnosed",
                "artifacts": {"patch_proposal_path": f".cambrian/proposals/proposal-{index}.yaml"},
                "metrics_context": {
                    "active_pack_id": "auth-bug-core",
                    "active_pack_ref": "auth-bug-core@0.1.0",
                    "active_pack_namespace": "local",
                    "active_pack_version": "0.1.0",
                    "active_pack_lane": "python-pytest-auth-bug-core",
                    "reused_context": {"pack": True},
                    "results": {
                        "validated_proposal": validated,
                        "adoption_succeeded": adopted,
                        "apply_tests_passed": apply_passed,
                    },
                    "human_interventions": {
                        "manual_patch_selection": human,
                    },
                    "milestones": {
                        "request_started_at": f"2026-05-03T00:{start_minute:02d}:00+00:00",
                        "proposal_validated_at": f"2026-05-03T00:{end_minute:02d}:00+00:00",
                    },
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return session_ref


def _record_use(
    project_root: Path,
    index: int,
    *,
    validated: bool,
    adopted: bool = False,
    apply_passed: bool = False,
    human: bool = False,
) -> None:
    session_ref = _write_session(
        project_root,
        index,
        validated=validated,
        adopted=adopted,
        apply_passed=apply_passed,
        human=human,
    )
    record_pack_usage_event(
        project_root,
        event_kind="used",
        surface_kind="do",
        request="fix auth login",
        request_class="bug_fix",
        linked_session_id=f"do-proof-{index}",
        linked_session_ref=session_ref,
    )


def _metric(card, key: str):
    return next(metric.value for metric in card.key_metrics if metric.key == key)


def test_proof_insufficient_data(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)

    card = PackProofBuilder().build(tmp_path, "auth-bug-core")

    assert card.reputation_verdict == "insufficient_data"
    assert card.used_count == 0
    assert _metric(card, "validated_proposal_rate") is None


def test_proof_promising(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    _record_use(tmp_path, 1, validated=True, adopted=False, apply_passed=False, human=False)

    card = PackProofBuilder().build(tmp_path, "auth-bug-core")

    assert card.reputation_verdict == "promising"
    assert _metric(card, "validated_proposal_rate") == 1.0


def test_proof_useful(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    _record_use(tmp_path, 1, validated=True, adopted=True, apply_passed=True, human=False)
    _record_use(tmp_path, 2, validated=True, adopted=False, apply_passed=False, human=False)
    _record_use(tmp_path, 3, validated=False, adopted=False, apply_passed=False, human=True)

    card = PackProofBuilder().build(tmp_path, "auth-bug-core")

    assert card.reputation_verdict == "useful"
    assert card.outcome_linked_count == 3
    assert card.why_useful


def test_proof_strong(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    for index in range(1, 5):
        _record_use(tmp_path, index, validated=True, adopted=True, apply_passed=True, human=False)
    _record_use(tmp_path, 5, validated=False, adopted=False, apply_passed=False, human=True)

    card = PackProofBuilder().build(tmp_path, "auth-bug-core")

    assert card.reputation_verdict == "strong"
    assert _metric(card, "validation_autonomy_rate") == 0.8


def test_proof_regressed(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    for index in range(1, 4):
        _record_use(tmp_path, index, validated=False, adopted=False, apply_passed=False, human=True)

    card = PackProofBuilder().build(tmp_path, "auth-bug-core")

    assert card.reputation_verdict == "regressed"
    assert any("caution" in item for item in card.known_limits)


def test_proof_save_yaml_and_markdown(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    _record_use(tmp_path, 1, validated=True, adopted=True, apply_passed=True, human=False)

    result = _cli(tmp_path, "pack", "proof", "auth-bug-core", "--save")

    assert result.returncode == 0, result.stderr
    assert "Pack Proof Card" in result.stdout
    assert (tmp_path / ".cambrian" / "packs" / "proof" / "latest.yaml").exists()
    assert list((tmp_path / ".cambrian" / "packs" / "proof").glob("proof_auth-bug-core_*.yaml"))
    assert list((tmp_path / ".cambrian" / "packs" / "proof").glob("proof_auth-bug-core_*.md"))


def test_proof_show_works(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    _record_use(tmp_path, 1, validated=True, adopted=True, apply_passed=True, human=False)
    saved = _cli(tmp_path, "pack", "proof", "auth-bug-core", "--save", "--json")
    assert saved.returncode == 0, saved.stderr
    payload = json.loads(saved.stdout)
    proof_path = payload["saved_paths"]["yaml"]

    shown = _cli(tmp_path, "pack", "proof-show", proof_path)

    assert shown.returncode == 0, shown.stderr
    assert "Verdict:" in shown.stdout
    assert "validated proposal rate" in shown.stdout


def test_pack_show_and_status_surface_proof(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    _record_use(tmp_path, 1, validated=True, adopted=True, apply_passed=True, human=False)
    assert _cli(tmp_path, "pack", "proof", "auth-bug-core", "--save").returncode == 0

    show = _cli(tmp_path, "pack", "show", "auth-bug-core")
    status = _cli(tmp_path, "status")

    assert show.returncode == 0, show.stderr
    assert "Local proof:" in show.stdout
    assert status.returncode == 0, status.stderr
    assert "Local proof:" in status.stdout


def test_release_check_consumes_proof_card(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    for index in range(1, 6):
        _record_use(tmp_path, index, validated=True, adopted=True, apply_passed=True, human=False)
    result = _cli(tmp_path, "pack", "proof", "auth-bug-core", "--save")
    assert result.returncode == 0, result.stderr

    report = PackReleaseChecker().check(tmp_path, str(SEED_MANIFEST), require_proof=True)

    assert report.safe_to_publish is True
    assert report.proof_summary.proof_status == "strong"
    assert report.maturity in {"verified", "recommended"}


def test_no_fake_proof_when_metrics_missing(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)

    card = PackProofBuilder().build(tmp_path, "auth-bug-core")
    rendered = yaml.safe_dump(card.to_dict(), allow_unicode=True, sort_keys=False)

    assert card.reputation_verdict == "insufficient_data"
    assert _metric(card, "validated_proposal_rate") is None
    assert "validated_proposal_rate" in rendered
    assert "0.72" not in rendered


def test_latest_pack_proof_loader(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    _record_use(tmp_path, 1, validated=True, adopted=True, apply_passed=True, human=False)
    assert _cli(tmp_path, "pack", "proof", "auth-bug-core", "--save").returncode == 0

    card = latest_pack_proof_card(tmp_path, "auth-bug-core")

    assert card is not None
    assert PackProofStore().load_yaml(tmp_path / ".cambrian" / "packs" / "proof" / "latest.yaml").pack_id == "auth-bug-core"


def test_proof_surfaces_do_not_mutate_project_source_files(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    test_file = tmp_path / "tests" / "test_auth.py"
    source.parent.mkdir(parents=True)
    test_file.parent.mkdir(parents=True)
    source.write_text("def normalize_username(value):\n    return value\n", encoding="utf-8")
    test_file.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    before_source = source.read_text(encoding="utf-8")
    before_test = test_file.read_text(encoding="utf-8")

    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    _record_use(tmp_path, 1, validated=True, adopted=True, apply_passed=True, human=False)
    proof = _cli(tmp_path, "pack", "proof", "auth-bug-core", "--save")
    assert proof.returncode == 0, proof.stderr
    assert _cli(tmp_path, "pack", "proof-show", "latest").returncode == 0
    assert _cli(tmp_path, "pack", "show", "auth-bug-core").returncode == 0
    assert _cli(tmp_path, "status").returncode == 0

    assert source.read_text(encoding="utf-8") == before_source
    assert test_file.read_text(encoding="utf-8") == before_test
