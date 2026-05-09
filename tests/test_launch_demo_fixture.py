from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "auth_bug_demo"
REPLY = DEMO / "fixtures" / "ai_reply_patch_candidate.yaml"
CLI_TIMEOUT_SECONDS = 20


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(_read(path)) or {}


def _cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=CLI_TIMEOUT_SECONDS,
        check=False,
    )


def _run_python(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(cwd) if not previous else f"{cwd}{os.pathsep}{previous}"
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=CLI_TIMEOUT_SECONDS,
        check=False,
    )


def _debug(result: subprocess.CompletedProcess[str], cwd: Path) -> str:
    return (
        f"command={result.args}\n"
        f"cwd={cwd}\n"
        f"returncode={result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def _copy_demo(tmp_path: Path) -> Path:
    target = tmp_path / "auth_bug_demo"
    shutil.copytree(DEMO, target)
    return target


def test_demo_fixture_exists() -> None:
    for path in [
        DEMO / "README.md",
        DEMO / "pyproject.toml",
        DEMO / "src" / "auth.py",
        DEMO / "tests" / "test_auth.py",
        DEMO / "fixtures" / "request.txt",
        REPLY,
        DEMO / "fixtures" / "expected_demo_output.md",
    ]:
        assert path.exists()


def test_pytest_fixture_collects_and_shows_real_bug(tmp_path: Path) -> None:
    demo = _copy_demo(tmp_path)

    collected = _run_python(demo, "-m", "pytest", "--collect-only", "-q")
    assert collected.returncode == 0, _debug(collected, demo)
    assert "test_auth.py" in collected.stdout

    before_patch = _run_python(demo, "-m", "pytest", "-q")
    combined = f"{before_patch.stdout}\n{before_patch.stderr}"
    assert before_patch.returncode != 0
    assert "ModuleNotFoundError" not in combined
    assert "ImportError" not in combined
    assert "FAILED" in combined or "failed" in combined.lower()


def test_canned_reply_matches_source_and_patch_passes(tmp_path: Path) -> None:
    demo = _copy_demo(tmp_path)
    reply = _read_yaml(demo / "fixtures" / "ai_reply_patch_candidate.yaml")
    target = demo / str(reply["target_path"])
    source = _read(target)

    assert reply["response_kind"] == "patch_candidate"
    assert target.exists()
    assert reply["old_text"] in source
    assert str(reply["new_text"]).strip()

    target.write_text(source.replace(reply["old_text"], reply["new_text"], 1), encoding="utf-8")
    patched = _run_python(demo, "-m", "pytest", "-q")

    assert patched.returncode == 0, _debug(patched, demo)


def test_demo_runbook_documents_actual_commands() -> None:
    runbook = _read(ROOT / "docs" / "launch" / "DEMO_RUNBOOK.md")
    readme = _read(ROOT / "README.md")

    for command in [
        "cd examples/auth_bug_demo",
        "cambrian pack show auth-bug-core",
        "cambrian install pack auth-bug-core",
        "cambrian pack activate auth-bug-core",
        'cambrian pack start "로그인 에러 수정해"',
        "cambrian pack job-ingest latest fixtures/ai_reply_patch_candidate.yaml",
        "cambrian pack job-validate latest",
        "cambrian pack proof auth-bug-core",
    ]:
        assert command in runbook

    for command in [
        "cambrian project scan",
        "cambrian harness plan",
        "cambrian harness install",
        "cambrian agent dispatch",
        "cambrian job ingest",
        "cambrian job validate",
    ]:
        assert command in readme


def test_demo_docs_require_no_fake_ai_call_or_key() -> None:
    combined = "\n".join(
        [
            _read(ROOT / "README.md"),
            _read(ROOT / "docs" / "launch" / "DEMO_RUNBOOK.md"),
            _read(DEMO / "README.md"),
            _read(WEB_PAGE := ROOT / "web" / "packs" / "auth-bug-core.html"),
        ]
    ).lower()

    assert WEB_PAGE.exists()
    assert "canned ai reply" in combined
    assert "실제 ai 호출 대신 준비된 ai 답변 fixture" in combined
    assert "api key가 필요 없습니다" in combined or "api key는 필요 없다" in combined
    assert "export openai_api_key" not in combined
    assert "export anthropic_api_key" not in combined


def test_demo_docs_make_no_fake_proof_claims() -> None:
    combined = "\n".join(
        [
            _read(ROOT / "docs" / "launch" / "DEMO_RUNBOOK.md"),
            _read(DEMO / "fixtures" / "expected_demo_output.md"),
            _read(ROOT / "web" / "index.html"),
            _read(ROOT / "web" / "packs" / "auth-bug-core.html"),
        ]
    ).lower()

    for forbidden in [
        "guaranteed",
        "fully autonomous",
        "proven best",
        "72% validated proposal rate",
        "validated_proposal_rate: 1",
        "100% success",
    ]:
        assert forbidden not in combined

    assert "fake" in combined
    assert "does not claim public outcome metrics" in combined


def test_golden_path_smoke_with_canned_reply(tmp_path: Path) -> None:
    demo = _copy_demo(tmp_path)

    show = _cli(demo, "pack", "show", "auth-bug-core")
    assert show.returncode == 0, _debug(show, demo)
    assert "auth-bug-core" in show.stdout

    install = _cli(demo, "install", "pack", "auth-bug-core")
    assert install.returncode == 0, _debug(install, demo)

    activate = _cli(demo, "pack", "activate", "auth-bug-core")
    assert activate.returncode == 0, _debug(activate, demo)

    start = _cli(demo, "pack", "start", "로그인 에러 수정해", "--json")
    assert start.returncode == 0, _debug(start, demo)
    job = json.loads(start.stdout)["job"]
    assert job["status"] == "waiting_for_ai_reply"

    ingest = _cli(demo, "pack", "job-ingest", "latest", "fixtures/ai_reply_patch_candidate.yaml", "--json")
    assert ingest.returncode == 0, _debug(ingest, demo)
    routed = json.loads(ingest.stdout)
    assert routed["reply_kind"] == "patch_candidate"
    assert routed["status"] == "validation_ready"

    validate = _cli(demo, "pack", "job-validate", "latest", "--json")
    assert validate.returncode == 0, _debug(validate, demo)
    result = json.loads(validate.stdout)
    assert result["validation_status"] == "validated"
    assert result["proposal_ref"]

    proof = _cli(demo, "pack", "proof", "auth-bug-core")
    assert proof.returncode == 0, _debug(proof, demo)
    assert "auth-bug-core" in proof.stdout
