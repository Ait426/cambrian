from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_pack_install import SCHEMA_VERSION, _relative


PROPOSAL_ONLY = "proposal_only"
FULL_AUTHORITY = "full_authority"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        handle.write(content)
        tmp_path = Path(handle.name)
    tmp_path.replace(path)


def _save_yaml(path: Path, payload: dict[str, Any]) -> Path:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(target, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return target


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML top level must be a mapping: {path}")
    return payload


def default_authority_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "authority.yaml"


def default_authority_log_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "evidence" / "authority_log.yaml"


def normalize_authority_mode(mode: str | None) -> str:
    value = str(mode or "").strip().replace("-", "_")
    if value in {"", PROPOSAL_ONLY}:
        return PROPOSAL_ONLY
    if value == FULL_AUTHORITY:
        return FULL_AUTHORITY
    raise ValueError("authority mode must be proposal-only or full-authority")


def default_authority_profile(mode: str = PROPOSAL_ONLY) -> dict[str, Any]:
    normalized = normalize_authority_mode(mode)
    if normalized == FULL_AUTHORITY:
        permissions = {
            "filesystem_read": True,
            "filesystem_write": True,
            "command_exec": True,
            "package_install": True,
            "test_run": True,
            "git_branch": True,
            "git_commit": True,
            "git_tag": True,
            "build_artifact": True,
            "deploy": False,
            "external_network": True,
            "secret_access": "explicit",
        }
        safety = {
            "audit_log": True,
            "rollback_required": True,
            "kill_switch_enabled": True,
            "require_confirm_for_destructive_actions": True,
            "require_confirm_for_deploy": True,
            "require_confirm_for_secret_access": True,
        }
    else:
        permissions = {
            "filesystem_read": True,
            "filesystem_write": False,
            "command_exec": False,
            "package_install": False,
            "test_run": True,
            "git_branch": False,
            "git_commit": False,
            "git_tag": False,
            "build_artifact": False,
            "deploy": False,
            "external_network": False,
            "secret_access": False,
        }
        safety = {
            "require_confirm_for_destructive_actions": True,
            "require_confirm_for_deploy": True,
            "require_confirm_for_secret_access": True,
            "audit_log": True,
            "rollback_required": True,
            "kill_switch_enabled": True,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _now(),
        "mode": normalized,
        "scope": {"project_root": "."},
        "permissions": permissions,
        "safety": safety,
    }


def load_authority_profile(project_root: Path) -> dict[str, Any]:
    path = default_authority_path(project_root)
    if not path.exists():
        return default_authority_profile(PROPOSAL_ONLY)
    profile = _load_yaml(path)
    mode = normalize_authority_mode(str(profile.get("mode") or PROPOSAL_ONLY))
    default = default_authority_profile(mode)
    default.update(profile)
    default["mode"] = mode
    default["permissions"] = {**default_authority_profile(mode)["permissions"], **dict(profile.get("permissions") or {})}
    default["safety"] = {**default_authority_profile(mode)["safety"], **dict(profile.get("safety") or {})}
    return default


def authority_status(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    path = default_authority_path(root)
    profile = load_authority_profile(root)
    return {
        "ok": True,
        "mode": profile["mode"],
        "permissions": profile["permissions"],
        "safety": profile["safety"],
        "authority_ref": _relative(path, root) if path.exists() else None,
        "defaulted": not path.exists(),
        "next_command": "cambrian authority grant --mode full-authority --json",
    }


def init_authority(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    profile = default_authority_profile(PROPOSAL_ONLY)
    saved = _save_yaml(default_authority_path(root), profile)
    append_authority_log(
        root,
        command="cambrian authority init",
        mode=PROPOSAL_ONLY,
        result="initialized",
        changed_files=[_relative(saved, root)],
        rollback_hint="Run: cambrian authority revoke --json",
    )
    return {
        "ok": True,
        "mode": PROPOSAL_ONLY,
        "permissions": profile["permissions"],
        "authority_ref": _relative(saved, root),
        "next_command": "cambrian auto init --goal \"제품 목표\" --json",
    }


def grant_authority(project_root: Path, mode: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    normalized = normalize_authority_mode(mode)
    profile = default_authority_profile(normalized)
    saved = _save_yaml(default_authority_path(root), profile)
    append_authority_log(
        root,
        command=f"cambrian authority grant --mode {mode}",
        mode=normalized,
        result="granted",
        changed_files=[_relative(saved, root)],
        rollback_hint="Run: cambrian authority revoke --json",
    )
    return {
        "ok": True,
        "mode": normalized,
        "permissions": profile["permissions"],
        "safety": profile["safety"],
        "authority_ref": _relative(saved, root),
        "next_command": "cambrian auto init --goal \"제품 목표\" --json",
    }


def revoke_authority(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    profile = default_authority_profile(PROPOSAL_ONLY)
    saved = _save_yaml(default_authority_path(root), profile)
    append_authority_log(
        root,
        command="cambrian authority revoke",
        mode=PROPOSAL_ONLY,
        result="revoked_to_proposal_only",
        changed_files=[_relative(saved, root)],
        rollback_hint="Run: cambrian authority grant --mode full-authority --json",
    )
    return {
        "ok": True,
        "mode": PROPOSAL_ONLY,
        "permissions": profile["permissions"],
        "authority_ref": _relative(saved, root),
        "next_command": "cambrian authority status --json",
    }


def append_authority_log(
    project_root: Path,
    *,
    command: str,
    mode: str,
    result: str,
    changed_files: list[str] | None = None,
    rollback_hint: str = "No source files were changed.",
) -> Path:
    root = Path(project_root).resolve()
    path = default_authority_log_path(root)
    payload = _load_yaml(path) if path.exists() else {"schema_version": SCHEMA_VERSION, "events": []}
    events = payload.get("events", [])
    if not isinstance(events, list):
        events = []
    events.append(
        {
            "executed_at": _now(),
            "mode": normalize_authority_mode(mode),
            "command": command,
            "working_directory": ".",
            "changed_files": changed_files or [],
            "result": result,
            "rollback_hint": rollback_hint,
        }
    )
    payload["schema_version"] = SCHEMA_VERSION
    payload["updated_at"] = _now()
    payload["events"] = events
    return _save_yaml(path, payload)


def render_authority_result(payload: dict[str, Any]) -> str:
    lines = [
        "Authority Profile",
        "",
        f"Mode: {payload.get('mode')}",
    ]
    permissions = payload.get("permissions") or {}
    if isinstance(permissions, dict):
        lines.append("")
        lines.append("Permissions:")
        for key, value in permissions.items():
            lines.append(f"  {key}: {value}")
    if payload.get("authority_ref"):
        lines.append("")
        lines.append(f"Saved: {payload['authority_ref']}")
    if payload.get("next_command"):
        lines.append("")
        lines.append("Next:")
        lines.append(f"  {payload['next_command']}")
    return "\n".join(lines)
