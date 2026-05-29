import json
from pathlib import Path

from scripts.check_github_release_ready import (
    GITHUB_RELEASE_READY_SCHEMA_VERSION,
    _github_release_ready_payload,
    _public_text_scan,
    verify_github_release_ready_file,
)


ROOT = Path(__file__).resolve().parents[1]


def _ready_payload(tmp_path: Path, *, remote_is_github: bool = True) -> dict:
    return _github_release_ready_payload(
        root=tmp_path,
        remote={
            "status": "present",
            "url": "https://github.com/Ait426/cambrian.git" if remote_is_github else "https://example.com/Ait426/cambrian.git",
            "repo_slug": "Ait426/cambrian" if remote_is_github else "",
            "is_github": remote_is_github,
            "has_embedded_credentials": False,
        },
        readme_checks={
            "readme_present": True,
            "names_installable_ai_company_runtime": True,
            "states_every_project_becomes_ai_company": True,
            "github_release_asset_is_default": True,
            "standalone_bundle_install_command_present": True,
            "gold_path_runner_present": True,
            "pypi_lane_deferred": True,
            "supervised_boundary_present": True,
            "no_fake_autonomy_claim": True,
        },
        gitignore_checks={
            "gitignore_has_dist_": True,
            "gitignore_has_build_": True,
            "gitignore_has_dotenv": True,
            "gitignore_has_dotenvdot*": True,
            "gitignore_has_dotcambrian_": True,
            "gitignore_has_docs_release_NEXT_SESSION_HANDOFFdotmd": True,
        },
        public_text_scan={
            "scanned_files": ["README.md"],
            "finding_count": 0,
            "findings": [],
            "findings_truncated": False,
        },
        release_bundle_gate={
            "status": "verified",
            "file": "cambrian-install-kit-release-bundle.zip",
            "sha256": "a" * 64,
            "file_count": 10,
            "safe_to_share": True,
            "payload_checks_true": True,
            "current_artifact_checks_true": True,
        },
        send_ready_gate={
            "status": "verified",
            "file": "cambrian-install-kit-send-ready.json",
            "verdict": "GO",
            "safe_to_share": True,
            "body_sha256": "b" * 64,
            "checks_true": True,
        },
        staging_gate={
            "status": "verified",
            "file": "final-commit-staging-receipt.json",
            "body_sha256": "c" * 64,
            "total_candidate_paths": 2,
            "current_status": "receipt_current",
            "pathspec_status": "receipt_pathspec_files_current",
        },
        require_staging_current=True,
    )


def test_github_release_ready_payload_go_is_safe_and_manual(tmp_path: Path) -> None:
    payload = _ready_payload(tmp_path)

    assert payload["schema_version"] == GITHUB_RELEASE_READY_SCHEMA_VERSION
    assert payload["verdict"] == "GO"
    assert payload["blocking_checks"] == []
    assert payload["execution_policy"]["script_pushes_to_github"] is False
    assert payload["execution_policy"]["script_creates_github_release"] is False
    assert payload["execution_policy"]["script_uploads_release_asset"] is False
    assert payload["execution_policy"]["operator_must_upload_release_asset"] is True
    assert payload["github_release_ready_checks"]["body_hash_matched"] is True


def test_github_release_ready_payload_blocks_non_github_remote(tmp_path: Path) -> None:
    payload = _ready_payload(tmp_path, remote_is_github=False)

    assert payload["verdict"] == "BLOCKED"
    assert "git_remote_origin_is_github" in payload["blocking_checks"]
    assert payload["github_release_ready_checks"]["blocking_checks_match_checks"] is True


def test_github_release_ready_receipt_verifies_blocked_state(tmp_path: Path) -> None:
    payload = _ready_payload(tmp_path, remote_is_github=False)
    path = tmp_path / "github-release-ready.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verified = verify_github_release_ready_file(path)

    assert verified["verdict"] == "BLOCKED"
    assert verified["blocking_checks"] == ["git_remote_origin_is_github"]


def test_public_text_scan_finds_private_local_markers(tmp_path: Path) -> None:
    (tmp_path / "docs" / "release").mkdir(parents=True)
    (tmp_path / "docs" / "product").mkdir(parents=True)
    (tmp_path / "README.md").write_text("private path C:\\Users\\user\\Desktop\\cambrain\n", encoding="utf-8")

    scan = _public_text_scan(tmp_path)

    assert scan["finding_count"] == 2
    assert {finding["marker"] for finding in scan["findings"]} == {"C:\\Users\\user", "Desktop\\cambrain"}


def test_public_text_scan_allows_token_environment_placeholders(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("TWINE_PASSWORD=<pypi-token>\n", encoding="utf-8")

    scan = _public_text_scan(tmp_path)

    assert scan["finding_count"] == 0


def test_readme_points_to_github_release_asset_not_pypi_default() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "GitHub Release asset `cambrian-install-kit-release-bundle.zip`" in text
    assert "PyPI remains a deferred distribution lane" in text
    assert "not the current external-user release path" in text


def test_rc_checklist_names_github_release_ready_gate() -> None:
    text = (ROOT / "docs" / "release" / "RC_CHECKLIST.md").read_text(encoding="utf-8")

    for phrase in [
        "GitHub Release Ready Gate",
        "docs/release/GITHUB_RELEASE_RUNBOOK.md",
        "docs/release/GITHUB_RELEASE_NOTES_0_3_0.md",
        "python scripts/check_github_release_ready.py",
        "dist/github-release-ready.json",
        "cambrian-install-kit-release-bundle.zip",
        "README points to the GitHub Release asset path",
        "the script does not push to GitHub",
    ]:
        assert phrase in text


def test_github_release_runbook_records_public_release_path() -> None:
    text = (ROOT / "docs" / "release" / "GITHUB_RELEASE_RUNBOOK.md").read_text(encoding="utf-8")

    for phrase in [
        "Cambrian GitHub Release Runbook",
        "visibility: PUBLIC",
        "no GitHub Releases are currently published",
        "python scripts/check_github_release_ready.py",
        "git add --pathspec-from-file=dist/final-commit-staging-pathspecs/<slice_id>.pathspec",
        "git push origin master",
        "gh release create v0.3.0 dist/cambrian-install-kit-release-bundle.zip",
        "Do not upload the entire `dist/` directory.",
        "gh release view v0.3.0",
    ]:
        assert phrase in text


def test_github_release_notes_are_external_user_safe() -> None:
    text = (ROOT / "docs" / "release" / "GITHUB_RELEASE_NOTES_0_3_0.md").read_text(encoding="utf-8")

    for phrase in [
        "Cambrian 0.3.0",
        "cambrian-install-kit-release-bundle.zip",
        "INSTALL_CAMBRIAN_FROM_BUNDLE.py",
        "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py",
        "PyPI is not the current release lane",
        "does not run unsupervised",
    ]:
        assert phrase in text
    assert "C:\\Users\\user" not in text
    assert "TWINE_PASSWORD" not in text


def test_github_release_ready_script_does_not_contain_remote_mutation_commands() -> None:
    text = (ROOT / "scripts" / "check_github_release_ready.py").read_text(encoding="utf-8")

    assert "git push" not in text
    assert "gh release create" not in text
    assert "gh release upload" not in text
