from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_harness_profile import (
    ProjectHarnessProfile,
    ProjectHarnessProfileStore,
    ProjectHarnessScanner,
    default_project_profile_path,
)
from engine.project_pack_catalog import PackCatalogResolver, PackCatalogStore, resolve_pack_catalog_path
from engine.project_pack_install import PackInstaller, PackManifestLoader


SCHEMA_VERSION = "1.0.0"


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
    _atomic_write_text(target, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return target


def _relative(path: Path, root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve())).replace("\\", "/")
    except ValueError:
        return str(Path(path).resolve())


def default_harness_plan_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "harness" / "plan.yaml"


@dataclass
class HarnessPlan:
    schema_version: str
    generated_at: str
    plan_type: str
    project_profile: dict[str, Any]
    selected_harness: str | None
    harness_id: str | None
    reason: str
    agents: list[str]
    status: str
    next_commands: list[str]
    seed_preset: str | None = None
    goal: str | None = None
    agent_specs: list[dict[str, Any]] = field(default_factory=list)
    validation: dict[str, Any] = field(default_factory=dict)
    install_preview: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    catalog_ref: str | None = None
    manifest_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.status in {"draft", "planned"}
        return payload


@dataclass
class HarnessInstallResult:
    schema_version: str
    generated_at: str
    status: str
    plan_type: str | None
    selected_harness: str | None
    harness_id: str | None
    agents: list[str]
    install_plan: dict[str, Any] | None
    active_harness: dict[str, Any] | None
    plan_ref: str | None
    next_commands: list[str]
    installed_files: list[str] = field(default_factory=list)
    workforce_id: str | None = None
    skills: list[str] = field(default_factory=list)
    authority_mode: str | None = None
    authority_ref: str | None = None
    no_agent_dispatched: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.status == "installed"
        if self.status == "confirmation_required":
            payload["error"] = "confirmation_required"
            payload["message"] = "Review the harness plan before installing."
            payload["next_command"] = "cambrian harness install --confirm --json"
        if self.status == "engineering_gate_not_passed":
            payload["error"] = "engineering_gate_not_passed"
            payload["message"] = "Run harness engineer review and dry-run before install."
            payload["next_command"] = "cambrian harness engineer review --json"
        return payload


class HarnessPlanner:
    def build(self, project_root: Path, seed_preset: str | None = None) -> HarnessPlan:
        root = Path(project_root).resolve()
        profile = _load_or_scan_profile(root)
        from engine.project_custom_harness import build_custom_harness_plan

        custom_plan = build_custom_harness_plan(root, seed_preset=seed_preset)
        if custom_plan is not None:
            agent_specs = [dict(item) for item in custom_plan.get("agents", []) if isinstance(item, dict)]
            agents = [str(item.get("id")) for item in agent_specs if item.get("id")]
            return HarnessPlan(
                schema_version=SCHEMA_VERSION,
                generated_at=_now(),
                plan_type="custom",
                project_profile=_profile_summary(profile),
                selected_harness=str(custom_plan.get("harness_id")),
                harness_id=str(custom_plan.get("harness_id")),
                reason="Custom harness plan generated from interview answers.",
                agents=agents,
                status="draft",
                next_commands=list(custom_plan.get("next_commands", [])),
                seed_preset=seed_preset,
                goal=str(custom_plan.get("goal") or ""),
                agent_specs=agent_specs,
                validation=dict(custom_plan.get("validation", {})) if isinstance(custom_plan.get("validation"), dict) else {},
                install_preview=list(custom_plan.get("install_preview", [])),
                warnings=list(custom_plan.get("warnings", [])),
                errors=list(custom_plan.get("errors", [])),
            )

        catalog_path = resolve_pack_catalog_path(project_root=root)
        catalog = PackCatalogStore().load(catalog_path)
        selected = seed_preset if seed_preset else None
        warnings = list(profile.warnings)
        errors = list(profile.errors)
        warnings.extend(_active_harness_warnings(root, profile, selected))
        if profile.recommended_harnesses:
            warnings.append("Built-in presets are optional seeds; Cambrian does not auto-install them.")
        agents: list[str] = []
        manifest_ref: str | None = None
        reason = "Custom harness interview answers are required before planning."
        if seed_preset:
            reason = f"Seed preset {seed_preset} was requested, but interview answers are still required."
            try:
                entry = PackCatalogResolver().find_entry(catalog, seed_preset)
                manifest_path = PackCatalogResolver().resolve_manifest_path(root, entry, catalog_path=catalog_path)
                manifest = PackManifestLoader().load(manifest_path)
                agents = [str(worker.get("id") or worker.get("name")) for worker in manifest.workers if isinstance(worker, dict)]
                manifest_ref = _relative(manifest_path, root)
                warnings.append(f"Seed preset {seed_preset} will be used only as custom harness reference material.")
            except (FileNotFoundError, KeyError, ValueError) as exc:
                errors.append(str(exc))
        return HarnessPlan(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            plan_type="interview_required",
            project_profile=_profile_summary(profile),
            selected_harness=selected,
            harness_id=None,
            reason=reason,
            agents=[item for item in agents if item],
            status="needs_interview",
            next_commands=_next_commands("needs_interview"),
            seed_preset=seed_preset,
            warnings=warnings,
            errors=errors,
            catalog_ref=_relative(catalog_path, root),
            manifest_ref=manifest_ref,
        )


class HarnessPlanStore:
    def save(self, plan: HarnessPlan, path: Path) -> Path:
        return _save_yaml(path, plan.to_dict())


class HarnessInstaller:
    def install(self, project_root: Path, confirm: bool = False, seed_preset: str | None = None) -> HarnessInstallResult:
        root = Path(project_root).resolve()
        from engine.project_custom_harness import install_custom_harness

        if confirm:
            from engine.project_harness_engineering import engineering_gate_status

            gate = engineering_gate_status(root)
            if not gate.get("ok"):
                return HarnessInstallResult(
                    schema_version=SCHEMA_VERSION,
                    generated_at=_now(),
                    status="engineering_gate_not_passed",
                    plan_type="custom",
                    selected_harness=None,
                    harness_id=None,
                    agents=[],
                    install_plan=None,
                    active_harness=None,
                    plan_ref=None,
                    next_commands=[str(gate.get("next_command") or "cambrian harness engineer review --json")],
                    warnings=[],
                    errors=[str(item) for item in gate.get("errors", [])],
                )

        custom_result = install_custom_harness(root, confirm=confirm, seed_preset=seed_preset)
        if custom_result.status in {"installed", "confirmation_required"}:
            return HarnessInstallResult(
                schema_version=SCHEMA_VERSION,
                generated_at=_now(),
                status=custom_result.status,
                plan_type="custom",
                selected_harness=custom_result.harness_id,
                harness_id=custom_result.harness_id,
                agents=list(custom_result.generated_agents),
                install_plan=None,
                active_harness=None,
                plan_ref=_relative(default_harness_plan_path(root), root) if default_harness_plan_path(root).exists() else None,
                next_commands=list(custom_result.next_commands),
                installed_files=list(custom_result.installed_files),
                workforce_id=custom_result.workforce_id,
                skills=list(custom_result.generated_skills),
                authority_mode=custom_result.authority_mode,
                authority_ref=custom_result.authority_ref,
                no_agent_dispatched=custom_result.no_agent_dispatched,
                warnings=list(custom_result.warnings),
                errors=list(custom_result.errors),
            )

        plan = HarnessPlanner().build(root, seed_preset=seed_preset)
        plan_path = HarnessPlanStore().save(plan, default_harness_plan_path(root))
        return HarnessInstallResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="blocked",
            plan_type=plan.plan_type,
            selected_harness=plan.selected_harness,
            harness_id=plan.harness_id,
            agents=list(plan.agents),
            install_plan=None,
            active_harness=None,
            plan_ref=_relative(plan_path, root),
            next_commands=list(plan.next_commands),
            warnings=list(plan.warnings),
            errors=list(plan.errors) or ["Custom harness plan is not ready."],
        )

    def install_seed_preset_for_legacy_tests(self, project_root: Path, seed_preset: str) -> HarnessInstallResult:
        root = Path(project_root).resolve()
        plan = _legacy_seed_plan(root, seed_preset)
        plan_path = HarnessPlanStore().save(plan, default_harness_plan_path(root))
        catalog_path = resolve_pack_catalog_path(project_root=root)
        catalog = PackCatalogStore().load(catalog_path)
        entry = PackCatalogResolver().find_entry(catalog, seed_preset)
        manifest_path = PackCatalogResolver().resolve_manifest_path(root, entry, catalog_path=catalog_path)
        install_plan = PackInstaller().install(
            root,
            manifest_path,
            allow_update=True,
            expected_sha256=entry.manifest_sha256,
            source_kind_override="local_catalog",
            source_ref_override=_relative(catalog_path, root),
        )
        from engine.project_pack_activation import PackActivator

        active_context = PackActivator().activate(root, seed_preset)
        return HarnessInstallResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="installed",
            plan_type=plan.plan_type,
            selected_harness=plan.selected_harness,
            harness_id=plan.harness_id,
            agents=list(plan.agents),
            install_plan=install_plan.to_dict(),
            active_harness=active_context.to_dict(),
            plan_ref=_relative(plan_path, root),
            next_commands=['cambrian agent dispatch "로그인 에러 수정해"'],
            warnings=list(plan.warnings),
            errors=[],
        )


def build_and_save_harness_plan(project_root: Path, seed_preset: str | None = None) -> tuple[HarnessPlan, Path]:
    root = Path(project_root).resolve()
    plan = HarnessPlanner().build(root, seed_preset=seed_preset)
    saved = HarnessPlanStore().save(plan, default_harness_plan_path(root))
    return plan, saved


def render_harness_plan(plan: HarnessPlan, saved_path: Path | None = None) -> str:
    lines = [
        "Harness Plan",
        "==================================================",
        "",
        "Project profile:",
        f"  language       : {plan.project_profile.get('language', 'unknown')}",
        f"  test framework : {plan.project_profile.get('test_framework', 'unknown')}",
        f"  domains        : {', '.join(plan.project_profile.get('domains', [])) or 'none'}",
        "",
        "Plan type:",
        f"  {plan.plan_type}",
        "",
        "Harness:",
        f"  {plan.harness_id or plan.selected_harness or 'none'}",
        "",
        "Reason:",
        f"  {plan.reason}",
        "",
        "Agents:",
    ]
    lines.extend([f"  - {agent}" for agent in plan.agents] or ["  - none"])
    if plan.validation:
        lines.extend(["", "Validation:"])
        for command in plan.validation.get("test_commands", []) if isinstance(plan.validation.get("test_commands"), list) else []:
            lines.append(f"  - {command}")
    if plan.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in plan.warnings])
    if plan.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in plan.errors])
    lines.extend(["", "Next:"])
    lines.extend([f"  {command}" for command in plan.next_commands] or ["  none"])
    if saved_path:
        lines.extend(["", "Saved:", f"  {_relative(saved_path, Path(plan.project_profile.get('project_root') or '.'))}"])
    return "\n".join(lines)


def render_harness_install_result(result: HarnessInstallResult) -> str:
    if result.status == "installed":
        title = "Custom Cambrian harness installed."
    elif result.status == "confirmation_required":
        title = "Project harness install requires confirmation."
    else:
        title = "Project harness install blocked."
    lines = [
        title,
        "",
        "Harness:",
        f"  {result.harness_id or result.selected_harness or 'none'}",
        "",
        "Plan type:",
        f"  {result.plan_type or 'unknown'}",
    ]
    if result.agents:
        lines.extend(["", "Generated agents:"])
        lines.extend([f"  - {agent}" for agent in result.agents])
    if result.skills:
        lines.extend(["", "Generated skills:"])
        lines.extend([f"  - {skill}" for skill in result.skills])
    if result.workforce_id:
        lines.extend(["", "Generated workforce:", f"  {result.workforce_id}"])
    if result.authority_mode:
        lines.extend(["", "Authority:", f"  {result.authority_mode}"])
    if result.no_agent_dispatched and result.status == "installed":
        lines.extend(["", "Dispatch:", "  No agent was dispatched."])
    if result.installed_files:
        lines.extend(["", "Installed files:"])
        lines.extend([f"  - {path}" for path in result.installed_files])
    if result.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in result.warnings])
    if result.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in result.errors])
    lines.extend(["", "Next:"])
    lines.extend([f"  {command}" for command in result.next_commands] or ["  none"])
    return "\n".join(lines)


def _load_or_scan_profile(root: Path) -> ProjectHarnessProfile:
    path = default_project_profile_path(root)
    if path.exists():
        return ProjectHarnessProfileStore().load(path)
    profile = ProjectHarnessScanner().scan(root)
    ProjectHarnessProfileStore().save(profile, path)
    return profile


def _profile_summary(profile: ProjectHarnessProfile) -> dict[str, Any]:
    return {
        "project_root": profile.project_root,
        "project_name": profile.project_name,
        "language": profile.language,
        "languages": list(profile.languages),
        "test_framework": profile.test_framework,
        "test_frameworks": list(profile.test_frameworks),
        "domains": list(profile.domains),
        "recommended_harnesses": list(profile.recommended_harnesses),
    }


def _next_commands(status: str) -> list[str]:
    if status == "draft":
        return ["cambrian workforce generate", "cambrian harness install --confirm"]
    return [
        "cambrian harness interview start",
        "cambrian harness interview answer --answers .cambrian/interview/answers.yaml",
    ]


def _active_harness_warnings(root: Path, profile: ProjectHarnessProfile, selected: str | None) -> list[str]:
    try:
        from engine.project_pack_activation import current_active_pack

        active = current_active_pack(root)
    except Exception:
        return []
    if active is None or not active.pack_id:
        return []
    if selected and active.pack_id == selected:
        return []
    if active.pack_id == "auth-bug-core" and profile.language == "typescript" and profile.test_framework == "jest":
        return [
            "Active preset auth-bug-core is incompatible with this project.",
            "Run: cambrian harness interview start",
        ]
    return []


def _legacy_seed_plan(root: Path, seed_preset: str) -> HarnessPlan:
    profile = _load_or_scan_profile(root)
    catalog_path = resolve_pack_catalog_path(project_root=root)
    catalog = PackCatalogStore().load(catalog_path)
    entry = PackCatalogResolver().find_entry(catalog, seed_preset)
    manifest_path = PackCatalogResolver().resolve_manifest_path(root, entry, catalog_path=catalog_path)
    manifest = PackManifestLoader().load(manifest_path)
    agents = [str(worker.get("id") or worker.get("name")) for worker in manifest.workers if isinstance(worker, dict)]
    return HarnessPlan(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        plan_type="preset_legacy",
        project_profile=_profile_summary(profile),
        selected_harness=seed_preset,
        harness_id=seed_preset,
        reason=f"Legacy preset install path for {seed_preset}.",
        agents=[item for item in agents if item],
        status="planned",
        next_commands=['cambrian agent dispatch "로그인 에러 수정해"'],
        seed_preset=seed_preset,
        warnings=["Preset install is legacy/internal. Default product flow is custom harness interview."],
        errors=[],
        catalog_ref=_relative(catalog_path, root),
        manifest_ref=_relative(manifest_path, root),
    )
