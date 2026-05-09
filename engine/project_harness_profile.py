from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


SCHEMA_VERSION = "1.0.0"
_SKIP_DIRS = {
    ".cambrian",
    ".git",
    ".hg",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "dist",
    "build",
}


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


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML top level must be a mapping: {path}")
    return payload


def _relative(path: Path, root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve())).replace("\\", "/")
    except ValueError:
        return str(Path(path).resolve())


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def default_project_profile_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "project" / "profile.yaml"


@dataclass
class ProjectHarnessProfile:
    schema_version: str
    generated_at: str
    project_root: str
    project_name: str
    language: str
    languages: list[str]
    test_framework: str
    test_frameworks: list[str]
    detected_files: dict[str, bool]
    detected_paths: dict[str, list[str]]
    domains: list[str]
    recommended_harnesses: list[str]
    summary: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProjectHarnessProfileStore:
    def save(self, profile: ProjectHarnessProfile, path: Path) -> Path:
        return _save_yaml(path, profile.to_dict())

    def load(self, path: Path) -> ProjectHarnessProfile:
        payload = _load_yaml(path)
        return ProjectHarnessProfile(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(payload.get("generated_at", "")),
            project_root=str(payload.get("project_root", "")),
            project_name=str(payload.get("project_name", "")),
            language=str(payload.get("language", "unknown")),
            languages=[str(item) for item in payload.get("languages", []) if item],
            test_framework=str(payload.get("test_framework", "unknown")),
            test_frameworks=[str(item) for item in payload.get("test_frameworks", []) if item],
            detected_files=dict(payload.get("detected_files", {})) if isinstance(payload.get("detected_files"), dict) else {},
            detected_paths=dict(payload.get("detected_paths", {})) if isinstance(payload.get("detected_paths"), dict) else {},
            domains=[str(item) for item in payload.get("domains", []) if item],
            recommended_harnesses=[str(item) for item in payload.get("recommended_harnesses", []) if item],
            summary=[str(item) for item in payload.get("summary", []) if item],
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )


class ProjectHarnessScanner:
    def scan(self, project_root: Path) -> ProjectHarnessProfile:
        root = Path(project_root).resolve()
        paths = _collect_paths(root)
        detected_files = {
            "pyproject": (root / "pyproject.toml").exists(),
            "requirements": (root / "requirements.txt").exists(),
            "pytest_ini": (root / "pytest.ini").exists(),
            "package_json": bool(paths.get("package_json")),
            "tsconfig": bool(paths.get("tsconfig")),
            "jest_config": bool(paths.get("jest_config")),
            "tests_dir": (root / "tests").is_dir(),
            "backend_tests_dir": (root / "backend" / "tests").is_dir(),
        }
        languages = _detect_languages(root, paths, detected_files)
        test_frameworks = _detect_test_frameworks(root, paths, detected_files)
        domains = _detect_domains(paths)
        recommended = _recommend_harnesses(languages, test_frameworks, domains)
        primary_language = _primary_language(languages, paths)
        primary_test_framework = _primary_test_framework(test_frameworks, paths)
        warnings: list[str] = []
        if not recommended:
            warnings.append("No built-in harness preset matches this project yet.")
        if "typescript" in languages and "jest" not in test_frameworks:
            warnings.append("TypeScript project detected, but Jest test evidence was not found.")
        if "typescript" in languages and "jest" not in test_frameworks:
            warnings.append("Current built-in auth-bug-core preset is Python + pytest only.")
        summary = [
            f"language={primary_language}",
            f"test_framework={primary_test_framework}",
            f"domains={', '.join(domains) if domains else 'none'}",
            f"recommended_harnesses={', '.join(recommended) if recommended else 'none'}",
        ]
        return ProjectHarnessProfile(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            project_root=str(root),
            project_name=root.name,
            language=primary_language,
            languages=languages,
            test_framework=primary_test_framework,
            test_frameworks=test_frameworks,
            detected_files=detected_files,
            detected_paths=paths,
            domains=domains,
            recommended_harnesses=recommended,
            summary=summary,
            warnings=warnings,
            errors=[],
        )


def scan_and_save_project_profile(project_root: Path) -> tuple[ProjectHarnessProfile, Path]:
    root = Path(project_root).resolve()
    profile = ProjectHarnessScanner().scan(root)
    saved_path = ProjectHarnessProfileStore().save(profile, default_project_profile_path(root))
    return profile, saved_path


def render_project_harness_profile(profile: ProjectHarnessProfile, saved_path: Path | None = None) -> str:
    lines = [
        "Project Scan",
        "==================================================",
        "",
        "Project:",
        f"  {profile.project_name}",
        "",
        "Detected:",
        f"  language       : {profile.language}",
        f"  test framework : {profile.test_framework}",
        f"  domains        : {', '.join(profile.domains) if profile.domains else 'none'}",
        "",
        "Recommended harnesses:",
    ]
    lines.extend([f"  - {item}" for item in profile.recommended_harnesses] or ["  - none"])
    if profile.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in profile.warnings])
    lines.extend(["", "Next:", "  cambrian harness plan"])
    if saved_path:
        lines.extend(["", "Saved:", f"  {_relative(saved_path, Path(profile.project_root))}"])
    return "\n".join(lines)


def _collect_paths(root: Path) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {
        "python": [],
        "typescript": [],
        "tests": [],
        "auth": [],
        "login": [],
        "config": [],
        "package_json": [],
        "tsconfig": [],
        "jest_config": [],
    }
    _collect_config_paths(root, buckets)
    visited = 0
    for path in root.rglob("*"):
        if visited > 800:
            break
        try:
            rel_parts = path.relative_to(root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        if path.is_dir():
            continue
        visited += 1
        rel = _relative(path, root)
        lower = rel.lower()
        if path.suffix == ".py":
            buckets["python"].append(rel)
        if path.suffix in {".ts", ".tsx", ".js", ".jsx"}:
            buckets["typescript"].append(rel)
        if "test" in lower or "spec" in lower:
            buckets["tests"].append(rel)
        if "auth" in lower or "jwt" in lower:
            buckets["auth"].append(rel)
        if "login" in lower or "session" in lower:
            buckets["login"].append(rel)
        if lower.endswith("package.json"):
            buckets["package_json"].append(rel)
        if lower.endswith("tsconfig.json"):
            buckets["tsconfig"].append(rel)
        if Path(lower).name.startswith("jest.config."):
            buckets["jest_config"].append(rel)
        if lower.endswith(("pyproject.toml", "requirements.txt", "package.json", "pytest.ini", "tsconfig.json")) or Path(lower).name.startswith("jest.config."):
            buckets["config"].append(rel)
    return {key: values[:20] for key, values in buckets.items()}


def _collect_config_paths(root: Path, buckets: dict[str, list[str]]) -> None:
    for pattern, bucket in [
        ("package.json", "package_json"),
        ("tsconfig.json", "tsconfig"),
        ("jest.config.*", "jest_config"),
    ]:
        for path in root.rglob(pattern):
            try:
                rel_parts = path.relative_to(root).parts
            except ValueError:
                continue
            if any(part in _SKIP_DIRS for part in rel_parts):
                continue
            rel = _relative(path, root)
            _append_unique(buckets[bucket], rel)
            _append_unique(buckets["config"], rel)
            if len(buckets[bucket]) >= 20:
                break


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _detect_languages(root: Path, paths: dict[str, list[str]], detected_files: dict[str, bool]) -> list[str]:
    languages: list[str] = []
    if detected_files.get("pyproject") or detected_files.get("requirements") or paths.get("python"):
        languages.append("python")
    if detected_files.get("package_json") or detected_files.get("tsconfig") or paths.get("typescript"):
        languages.append("typescript")
    return _dedupe(languages) or ["unknown"]


def _detect_test_frameworks(root: Path, paths: dict[str, list[str]], detected_files: dict[str, bool]) -> list[str]:
    frameworks: list[str] = []
    if detected_files.get("pytest_ini") or any(path.endswith(".py") for path in paths.get("tests", [])):
        frameworks.append("pytest")
    for package_json_ref in paths.get("package_json", []):
        package_json = root / package_json_ref
        try:
            text = package_json.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            text = ""
        if "jest" in text or any(path.endswith((".test.ts", ".spec.ts")) for path in paths.get("tests", [])):
            frameworks.append("jest")
    if paths.get("jest_config"):
        frameworks.append("jest")
    if any(path.endswith((".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx")) for path in paths.get("tests", [])):
        frameworks.append("jest")
    if not frameworks and detected_files.get("tests_dir"):
        frameworks.append("unknown-tests")
    return _dedupe(frameworks) or ["unknown"]


def _detect_domains(paths: dict[str, list[str]]) -> list[str]:
    domains: list[str] = []
    if paths.get("auth"):
        domains.append("auth")
    if paths.get("login"):
        domains.append("login")
    if paths.get("tests"):
        domains.append("tests")
    if any("api" in path.lower() or "server" in path.lower() for group in paths.values() for path in group):
        domains.append("api")
    return _dedupe(domains)


def _recommend_harnesses(languages: list[str], test_frameworks: list[str], domains: list[str]) -> list[str]:
    if "typescript" in languages and "jest" in test_frameworks and {"auth", "tests"}.issubset(set(domains)):
        return ["typescript-jest-auth-core"]
    if "python" in languages and "pytest" in test_frameworks and {"auth", "tests"}.issubset(set(domains)):
        return ["auth-bug-core"]
    return []


def _primary(values: list[str]) -> str:
    return values[0] if values else "unknown"


def _primary_language(languages: list[str], paths: dict[str, list[str]]) -> str:
    if "typescript" in languages and (paths.get("auth") or paths.get("tests")):
        typed_hits = [
            path
            for path in [*paths.get("auth", []), *paths.get("tests", [])]
            if path.endswith((".ts", ".tsx", ".js", ".jsx"))
        ]
        if typed_hits:
            return "typescript"
    return _primary(languages)


def _primary_test_framework(test_frameworks: list[str], paths: dict[str, list[str]]) -> str:
    if "jest" in test_frameworks and any(path.endswith((".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx")) for path in paths.get("tests", [])):
        return "jest"
    return _primary(test_frameworks)
