from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_pypi_release import (  # noqa: E402
    PYPI_LOCAL_WHEEL_INSTALL_RECEIPT_NAME,
    PYPI_PREFLIGHT_RECEIPT_SCHEMA_VERSION,
    PYPI_RECEIPT_NAME,
    TESTPYPI_INSTALL_RECEIPT_NAME,
    preflight_publish,
    verify_pypi_publish_preflight_receipt_file,
)


PYPI_PUBLISH_READY_SCHEMA_VERSION = "cambrian_pypi_publish_ready_v0_1"
PYPI_PUBLISH_READY_JSON_TEMPLATE = "pypi-publish-ready-{repository}.json"
PYPI_PUBLISH_READY_MD_TEMPLATE = "pypi-publish-ready-{repository}.md"
PYPI_PUBLISH_READY_PREFLIGHT_TEMPLATE = "pypi-publish-ready-preflight-{repository}.json"


def _repo_root() -> Path:
    return ROOT


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _safe_path(path: Path, *, root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return resolved.name


def check_pypi_publish_ready(
    *,
    repository: str,
    output_dir: Path | None = None,
    release_receipt: Path | None = None,
    local_install_receipt: Path | None = None,
    testpypi_install_receipt: Path | None = None,
    require_token_env: bool = False,
) -> dict[str, Any]:
    if repository not in {"testpypi", "pypi"}:
        raise ValueError("repository must be testpypi or pypi")
    root = _repo_root()
    dist = (output_dir or root / "dist").resolve()
    dist.mkdir(parents=True, exist_ok=True)

    release_path = release_receipt or root / "dist" / PYPI_RECEIPT_NAME
    local_install_path = local_install_receipt or root / "dist" / PYPI_LOCAL_WHEEL_INSTALL_RECEIPT_NAME
    testpypi_path = testpypi_install_receipt or root / "dist" / TESTPYPI_INSTALL_RECEIPT_NAME
    preflight_path = dist / PYPI_PUBLISH_READY_PREFLIGHT_TEMPLATE.format(repository=repository)

    try:
        preflight_publish(
            repository=repository,
            release_receipt=release_path,
            local_install_receipt=local_install_path,
            testpypi_install_receipt=testpypi_path,
            receipt_path=preflight_path,
            require_token_env=require_token_env,
        )
    except SystemExit:
        # A blocked preflight intentionally exits non-zero after writing a safe receipt.
        pass
    preflight = verify_pypi_publish_preflight_receipt_file(preflight_path)
    payload = _publish_ready_payload(
        repository=repository,
        preflight=preflight,
        preflight_path=preflight_path,
        release_path=release_path,
        local_install_path=local_install_path,
        testpypi_path=testpypi_path,
        require_token_env=require_token_env,
        root=root,
    )

    json_path = dist / PYPI_PUBLISH_READY_JSON_TEMPLATE.format(repository=repository)
    md_path = dist / PYPI_PUBLISH_READY_MD_TEMPLATE.format(repository=repository)
    _write_json(json_path, payload)
    md_path.write_text(_publish_ready_markdown(payload), encoding="utf-8")
    verify_pypi_publish_ready_file(json_path)
    return {
        "status": "prepared",
        "verdict": payload["verdict"],
        "repository": repository,
        "publish_ready_json": str(json_path),
        "publish_ready_md": str(md_path),
        "preflight_receipt": str(preflight_path),
        "publish_ready_body_sha256": payload["publish_ready_body_sha256"],
    }


def _publish_ready_payload(
    *,
    repository: str,
    preflight: dict[str, Any],
    preflight_path: Path,
    release_path: Path,
    local_install_path: Path,
    testpypi_path: Path,
    require_token_env: bool,
    root: Path,
) -> dict[str, Any]:
    status = str(preflight.get("status") or "")
    metadata = preflight.get("metadata") if isinstance(preflight.get("metadata"), dict) else {}
    checks = preflight.get("checks") if isinstance(preflight.get("checks"), dict) else {}
    verdict = _verdict_for_status(status)
    upload_env_gate = preflight.get("upload_env_gate") if isinstance(preflight.get("upload_env_gate"), dict) else {}
    next_commands = preflight.get("next_commands") if isinstance(preflight.get("next_commands"), dict) else {}
    payload: dict[str, Any] = {
        "schema_version": PYPI_PUBLISH_READY_SCHEMA_VERSION,
        "generated_at": _now(),
        "verdict": verdict,
        "safe_to_share": True,
        "repository": repository,
        "require_token_env": require_token_env,
        "package": {
            "name": metadata.get("name"),
            "version": metadata.get("version"),
            "wheel_sha256": preflight.get("wheel_sha256"),
        },
        "inputs": {
            "release_receipt": _safe_path(release_path, root=root),
            "local_install_receipt": _safe_path(local_install_path, root=root),
            "testpypi_install_receipt": _safe_path(testpypi_path, root=root) if repository == "pypi" else None,
            "preflight_receipt": _safe_path(preflight_path, root=root),
            "preflight_receipt_body_sha256": preflight.get("pypi_publish_preflight_receipt_body_sha256"),
        },
        "preflight": {
            "schema_version": preflight.get("schema_version"),
            "status": status,
            "blocking_checks": preflight.get("blocking_checks"),
            "checks": checks,
            "release_receipt_gate": preflight.get("release_receipt_gate"),
            "local_install_gate": preflight.get("local_install_gate"),
            "upload_env_gate": upload_env_gate,
            "testpypi_install_gate": preflight.get("testpypi_install_gate"),
        },
        "operator_steps": _operator_steps(repository),
        "next_commands": next_commands,
        "do_not_share": [
            "PyPI or TestPyPI API tokens",
            ".env files",
            "raw private project data",
            "terminal output that contains secrets",
        ],
        "privacy": {
            "absolute_paths_included": False,
            "command_output_text_included": False,
            "tokens_included": False,
        },
    }
    payload["checks"] = _publish_ready_business_checks(payload)
    payload["publish_ready_body_sha256"] = _publish_ready_body_sha256(payload)
    payload["publish_ready_checks"] = _publish_ready_checks(payload, root=root)
    return payload


def _verdict_for_status(status: str) -> str:
    if status.startswith("ready_to_upload_"):
        return "GO"
    if status.startswith("ready_for_") and status.endswith("_token"):
        return "WAITING_FOR_TOKEN"
    return "BLOCKED"


def _operator_steps(repository: str) -> list[str]:
    if repository == "testpypi":
        return [
            "Set TWINE_USERNAME=__token__ and TWINE_PASSWORD=<testpypi-token> in the local shell only.",
            "Run python scripts/prepare_pypi_release.py --preflight-upload testpypi --require-token-env.",
            "Run python scripts/prepare_pypi_release.py --upload testpypi --publish-ready-receipt dist/pypi-publish-ready-testpypi.json.",
            "Run python scripts/verify_pypi_install.py --repository testpypi --version 0.3.0 --receipt dist/pypi_testpypi_install_receipt.json.",
        ]
    return [
        "Verify dist/pypi_testpypi_install_receipt.json exists for the same package version.",
        "Set TWINE_USERNAME=__token__ and TWINE_PASSWORD=<pypi-token> in the local shell only.",
        "Run python scripts/prepare_pypi_release.py --preflight-upload pypi --testpypi-install-receipt dist/pypi_testpypi_install_receipt.json --require-token-env.",
        "Run python scripts/prepare_pypi_release.py --upload pypi --testpypi-install-receipt dist/pypi_testpypi_install_receipt.json --publish-ready-receipt dist/pypi-publish-ready-pypi.json.",
        "Run python scripts/verify_pypi_install.py --repository pypi --version 0.3.0.",
    ]


def _publish_ready_business_checks(payload: dict[str, Any]) -> dict[str, bool]:
    preflight = payload.get("preflight") if isinstance(payload.get("preflight"), dict) else {}
    checks = preflight.get("checks") if isinstance(preflight.get("checks"), dict) else {}
    upload_gate = preflight.get("upload_env_gate") if isinstance(preflight.get("upload_env_gate"), dict) else {}
    repository = payload.get("repository")
    verdict = payload.get("verdict")
    return {
        "release_receipt_ready": checks.get("release_receipt_ready") is True,
        "release_artifacts_verified": checks.get("release_receipt_artifacts_verified") is True,
        "local_install_verified": checks.get("local_install_receipt_verified") is True,
        "local_install_matches_release": checks.get("local_install_package_matched") is True
        and checks.get("local_install_version_matched") is True
        and checks.get("local_install_wheel_hash_matched") is True,
        "testpypi_gate_satisfied_or_not_required": repository != "pypi"
        or checks.get("testpypi_install_receipt_verified") is True,
        "token_value_not_recorded": upload_gate.get("twine_password_recorded") is False,
        "verdict_matches_preflight": verdict == _verdict_for_status(str(preflight.get("status") or "")),
    }


def _publish_ready_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"publish_ready_body_sha256", "publish_ready_checks"}
    }
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _publish_ready_checks(payload: dict[str, Any], *, root: Path) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    home = str(Path.home())
    body_hash = payload.get("publish_ready_body_sha256")
    publish_checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    preflight = payload.get("preflight") if isinstance(payload.get("preflight"), dict) else {}
    inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
    next_commands = payload.get("next_commands") if isinstance(payload.get("next_commands"), dict) else {}
    return {
        "schema_version_present": payload.get("schema_version") == PYPI_PUBLISH_READY_SCHEMA_VERSION,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "verdict_known": payload.get("verdict") in {"GO", "WAITING_FOR_TOKEN", "BLOCKED"},
        "preflight_schema_version_present": preflight.get("schema_version") == PYPI_PREFLIGHT_RECEIPT_SCHEMA_VERSION,
        "preflight_receipt_body_hash_present": _looks_like_sha256(inputs.get("preflight_receipt_body_sha256")),
        "publish_checks_present": bool(publish_checks),
        "operator_steps_present": bool(payload.get("operator_steps")),
        "next_commands_present": "upload" in next_commands and "install_verify" in next_commands,
        "do_not_share_guardrails_present": "PyPI or TestPyPI API tokens" in payload.get("do_not_share", [])
        and ".env files" in payload.get("do_not_share", []),
        "absolute_paths_omitted": str(root) not in serialized and (not home or home not in serialized),
        "tokens_omitted": "TWINE_PASSWORD=" not in serialized.replace("TWINE_PASSWORD=<testpypi-token>", "").replace(
            "TWINE_PASSWORD=<pypi-token>",
            "",
        ),
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _publish_ready_body_sha256(payload),
    }


def verify_pypi_publish_ready_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("PyPI publish-ready JSON object expected.")
    if payload.get("schema_version") != PYPI_PUBLISH_READY_SCHEMA_VERSION:
        raise ValueError("PyPI publish-ready schema_version mismatch.")
    checks = payload.get("publish_ready_checks") if isinstance(payload.get("publish_ready_checks"), dict) else {}
    if not checks:
        raise ValueError("PyPI publish-ready checks missing.")
    failed = [name for name, passed in checks.items() if passed is not True]
    if failed:
        raise ValueError("PyPI publish-ready verification failed: " + ", ".join(failed))
    if payload.get("publish_ready_body_sha256") != _publish_ready_body_sha256(payload):
        raise ValueError("PyPI publish-ready body hash mismatch.")
    return payload


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())


def _publish_ready_markdown(payload: dict[str, Any]) -> str:
    package = payload["package"]
    inputs = payload["inputs"]
    steps = "\n".join(f"{index}. {step}" for index, step in enumerate(payload["operator_steps"], start=1))
    do_not_share = "\n".join(f"- {item}" for item in payload["do_not_share"])
    return f"""# Cambrian PyPI Publish Ready

## Verdict

`{payload["verdict"]}`

## Target

- Repository: `{payload["repository"]}`
- Package: `{package["name"]}`
- Version: `{package["version"]}`
- Wheel sha256: `{package["wheel_sha256"]}`

## Evidence

- Release receipt: `{inputs["release_receipt"]}`
- Local install receipt: `{inputs["local_install_receipt"]}`
- TestPyPI install receipt: `{inputs["testpypi_install_receipt"]}`
- Preflight receipt: `{inputs["preflight_receipt"]}`
- Preflight body sha256: `{inputs["preflight_receipt_body_sha256"]}`

## Operator Steps

{steps}

## Do Not Share

{do_not_share}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or verify a safe Cambrian PyPI publish-ready handoff.")
    parser.add_argument("--repository", choices=["testpypi", "pypi"], default="testpypi")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--release-receipt", type=Path, default=None)
    parser.add_argument("--local-install-receipt", type=Path, default=None)
    parser.add_argument("--testpypi-install-receipt", type=Path, default=None)
    parser.add_argument("--require-token-env", action="store_true")
    parser.add_argument("--verify-ready", type=Path, default=None)
    args = parser.parse_args()
    if args.verify_ready:
        payload = verify_pypi_publish_ready_file(args.verify_ready)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    result = check_pypi_publish_ready(
        repository=args.repository,
        output_dir=args.output_dir,
        release_receipt=args.release_receipt,
        local_install_receipt=args.local_install_receipt,
        testpypi_install_receipt=args.testpypi_install_receipt,
        require_token_env=bool(args.require_token_env),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["verdict"] in {"GO", "WAITING_FOR_TOKEN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
