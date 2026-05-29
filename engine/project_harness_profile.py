from __future__ import annotations

import re
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
    ".pytest_tmp",
    ".launch_runs",
    "__pycache__",
    ".next",
    ".turbo",
    ".cache",
    ".temp",
    "node_modules",
    "venv",
    ".venv",
    "dist",
    "build",
    "coverage",
    "tmp",
    "temp",
    "logs",
    "archive",
    "archives",
    "processed_inputs",
    "raw_inputs",
    "corpus",
    "dataset",
    "datasets",
    "scraped",
    "scrapes",
    "reddit",
    "errors",
    "dropzones",
    "demo",
    "examples",
    "fixtures",
    "sample",
    "samples",
    "skill_pool",
}
_SKIP_DIR_PREFIXES = (
    ".pytest",
    ".launch_runs",
)
_SNIFF_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".sql"}
_SENSITIVE_FILE_NAMES = {".env", ".env.local", ".env.production", ".npmrc"}
_CONTENT_SNIFF_LIMIT_BYTES = 120_000
_DOMAIN_KEYWORDS = {
    "auth": ["auth", "jwt", "bearer", "session", "login"],
    "login": ["login", "session"],
    "ddmq": ["ddmq"],
    "stage_pipeline": ["stage1", "stage2", "stage3", "stage4", "stage5", "stage_", "stage pipeline"],
    "schema_validation": ["schema_registry", "schema_validator", "schema validation", "json schema", "validator"],
    "llm_api": ["anthropic", "claude api", "llm api", "rate limit", "model error"],
    "webhook": ["webhook", "svix", "hmac", "signature"],
    "suppression": ["suppression", "suppressionlist", "unsubscribe", "do_not_contact", "do-not-contact", "blocked recipient"],
    "send": ["send", "sendcampaign", "send_campaign", "delivery", "mailer", "resend", "smtp"],
    "pipeline": ["pipeline", "orchestrator", "queue", "worker", "cron", "retry"],
    "outbound": ["outbound", "campaign", "recipient"],
    "scoring": ["score", "scorecustomer", "score_customer", "scorecard", "scoring", "qualification"],
    "supabase": ["supabase", "@supabase"],
    "migration": ["migration", "create table", "alter table", "policy", "rls"],
    "customer": ["customer", "icp", "ideal customer", "account"],
}
_IDENTITY_FILE_CANDIDATES = [
    "CONTEXT_INDEX.md",
    "PROJECT_BRIEF.md",
    "PRODUCT_CONSTITUTION.md",
    "ROADMAP.md",
    "DECISION_LOG.md",
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "TODO.md",
    "package.json",
    "pyproject.toml",
    "index.html",
    "web/index.html",
]
_IDENTITY_READ_LIMIT_BYTES = 120_000
_PLATFORM_IDENTITY_KEYWORDS = [
    "ai 에이전트",
    "에이전트",
    "agent pack",
    "agent-pack",
    ".agent-pack",
]
_CAMBRIAN_BRIDGE_KEYWORDS = [
    "cambrian-local",
    "cambrian local",
    "local bridge",
    "로컬 브릿지",
    "선택형 런타임",
    "runtime adapter",
]
_DOMAIN_IDENTITY_KEYWORDS = {
    "ddmq": ["ddmq"],
    "stage_pipeline": ["stage pipeline", "stage1", "stage2", "stage3", "stage4", "stage5"],
    "schema_validation": ["schema registry", "schema validator", "schema validation"],
    "llm_api": ["anthropic", "claude api", "llm api"],
    "pipeline_automation": ["pipeline automation", "orchestrator", "stage pipeline"],
    "website": ["website", "web site", "homepage", "landing page", "웹사이트", "홈페이지", "랜딩페이지"],
    "hotel_site": ["hotel", "lodging", "accommodation", "guest room", "room booking", "hospitality", "호텔", "숙박", "객실", "체크인"],
    "auth": ["auth", "login", "인증", "로그인", "세션"],
    "webhook": ["webhook", "hmac", "signature", "서명"],
    "suppression": ["suppression", "unsubscribe", "차단 수신자"],
    "send_pipeline": ["send pipeline", "delivery", "발송", "큐", "재시도"],
    "outbound": ["outbound", "campaign", "recipient"],
    "scoring": ["scorecard", "scoring", "점수", "스코어"],
    "supabase": ["supabase", "rls", "migration", "마이그레이션"],
    "customer": ["customer", "icp", "고객"],
    "api": ["api", "endpoint", "server"],
}
_APP_SOURCE_PREFIXES = ("src/", "app/", "backend/", "frontend/", "web/", "pages/", "lib/", "server/", "core/", "plugins/")
_WEAK_SIGNAL_PREFIXES = ("tools/", "docs/", "scripts/")
_RISK_KEYWORDS = {
    ".env": [".env", "secret", "시크릿", "api key"],
    "git_push": ["git push"],
    "package_install": ["pip install", "npm install", "패키지 설치"],
    "auto_apply": ["auto_apply", "자동 적용", "자동 수정"],
    "migration": ["migration", "마이그레이션"],
    "external_api": ["api gateway", "외부 api", "결제", "payment"],
}
_DOCUMENT_AUTHORITY_POLICY = {
    "source_of_truth": [
        "root identity docs such as README.md, AGENTS.md, CLAUDE.md, PROJECT_BRIEF.md, CONTEXT_INDEX.md",
        "explicit product, architecture, release, or decision docs named by the project",
        "code, config, and validation files observed in app source paths",
    ],
    "weak_without_code_support": [
        "docs/",
        "scripts/",
        "tools/",
        "demo/",
        "examples/",
        "fixtures/",
        "sample skills",
    ],
    "excluded_generated_artifacts": [
        ".cambrian/",
        ".pytest*/",
        ".launch_runs/",
        "archive/",
        "demo/",
        "examples/",
        "dist/",
        "build/",
        "fixtures/",
        "logs/",
        "sample/",
        "samples/",
        "skill_pool/",
        "tmp/",
    ],
    "promotion_rule": "generated, demo, sample, and weak documentation signals cannot become project domain identity without app-source or explicit identity evidence",
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
    evidence_card: dict[str, Any] = field(default_factory=dict)
    domain_confidence: dict[str, Any] = field(default_factory=dict)
    evidence_graph: dict[str, Any] = field(default_factory=dict)
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
            evidence_card=dict(payload.get("evidence_card", {})) if isinstance(payload.get("evidence_card"), dict) else {},
            domain_confidence=dict(payload.get("domain_confidence", {})) if isinstance(payload.get("domain_confidence"), dict) else {},
            evidence_graph=dict(payload.get("evidence_graph", {})) if isinstance(payload.get("evidence_graph"), dict) else {},
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
        evidence_card = _build_evidence_card(root, paths, detected_files, languages, test_frameworks)
        domain_confidence = _build_domain_confidence(paths, evidence_card)
        evidence_graph = _build_project_evidence_graph(evidence_card, domain_confidence)
        domains = _effective_domains(domain_confidence)
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
            evidence_card=evidence_card,
            domain_confidence=domain_confidence,
            evidence_graph=evidence_graph,
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
        "ddmq": [],
        "stage_pipeline": [],
        "schema_validation": [],
        "llm_api": [],
        "webhook": [],
        "suppression": [],
        "send": [],
        "pipeline": [],
        "outbound": [],
        "scoring": [],
        "supabase": [],
        "migration": [],
        "customer": [],
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
        if any(_is_skipped_path_part(part) for part in rel_parts):
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
        signal_text = _domain_signal_text(path, lower)
        if signal_text:
            content_signal_text = _read_sniff_text(path)
            for bucket, keywords in _DOMAIN_KEYWORDS.items():
                source_text = content_signal_text if bucket in {"auth", "login"} else signal_text
                if _contains_any(source_text, keywords):
                    buckets[bucket].append(rel)
        if lower.endswith("package.json"):
            buckets["package_json"].append(rel)
        if lower.endswith("tsconfig.json"):
            buckets["tsconfig"].append(rel)
        if Path(lower).name.startswith("jest.config."):
            buckets["jest_config"].append(rel)
        if lower.endswith(("pyproject.toml", "requirements.txt", "package.json", "pytest.ini", "tsconfig.json")) or Path(lower).name.startswith("jest.config."):
            buckets["config"].append(rel)
    return {key: values[:20] for key, values in buckets.items()}


def _read_sniff_text(path: Path) -> str:
    if path.suffix.lower() not in _SNIFF_SUFFIXES:
        return ""
    if path.name.lower() in _SENSITIVE_FILE_NAMES:
        return ""
    try:
        if path.stat().st_size > _CONTENT_SNIFF_LIMIT_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return ""


def _domain_signal_text(path: Path, lower_path: str) -> str:
    if path.suffix.lower() not in _SNIFF_SUFFIXES:
        return ""
    content = _read_sniff_text(path)
    path_with_separators = lower_path.replace("/", " ").replace("\\", " ").replace("-", " ").replace("_", " ")
    camel_split_path = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", path.as_posix()).lower()
    return f"{lower_path}\n{path_with_separators}\n{camel_split_path}\n{content}"


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(_contains_keyword(text, keyword) for keyword in keywords)


def _contains_keyword(text: str, keyword: str) -> bool:
    """부분 문자열 오탐을 줄이기 위해 ASCII 단어는 단어 경계로만 매칭한다."""
    key = str(keyword or "").lower()
    if not key:
        return False
    if re.fullmatch(r"[a-z0-9_]+", key):
        return re.search(rf"(?<![a-z0-9_]){re.escape(key)}(?![a-z0-9_])", text) is not None
    return key in text


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
            if any(_is_skipped_path_part(part) for part in rel_parts):
                continue
            rel = _relative(path, root)
            _append_unique(buckets[bucket], rel)
            _append_unique(buckets["config"], rel)
            if len(buckets[bucket]) >= 20:
                break


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _is_skipped_path_part(part: str) -> bool:
    """Generated/runtime directories are never allowed to shape project identity."""
    text = str(part or "")
    if text in _SKIP_DIRS:
        return True
    return any(text.startswith(prefix) for prefix in _SKIP_DIR_PREFIXES)


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
    if paths.get("ddmq"):
        domains.append("ddmq")
    if paths.get("stage_pipeline"):
        domains.append("stage_pipeline")
    if paths.get("schema_validation"):
        domains.append("schema_validation")
    if paths.get("llm_api"):
        domains.append("llm_api")
    if paths.get("suppression"):
        domains.append("suppression")
    if paths.get("webhook"):
        domains.append("webhook")
    if paths.get("pipeline"):
        domains.append("pipeline_automation")
    if paths.get("send") or paths.get("pipeline"):
        domains.append("send_pipeline")
    if paths.get("outbound"):
        domains.append("outbound")
    if paths.get("scoring"):
        domains.append("scoring")
    if paths.get("supabase"):
        domains.append("supabase")
    if paths.get("customer"):
        domains.append("customer")
    if paths.get("tests"):
        domains.append("tests")
    if any("api" in path.lower() or "server" in path.lower() for group in paths.values() for path in group):
        domains.append("api")
    return _dedupe(domains)


def _build_evidence_card(
    root: Path,
    paths: dict[str, list[str]],
    detected_files: dict[str, bool],
    languages: list[str],
    test_frameworks: list[str],
) -> dict[str, Any]:
    """프로젝트 정체성, 코드, 검증, 위험 신호를 한 장의 evidence card로 요약한다."""
    identity_evidence = _identity_evidence(root)
    validation_evidence = _validation_evidence(paths, detected_files, test_frameworks)
    code_evidence = _code_evidence(paths)
    risk_evidence = _risk_evidence(identity_evidence)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "available",
        "source": "project_scan",
        "identity_evidence": identity_evidence,
        "code_evidence": code_evidence,
        "validation_evidence": validation_evidence,
        "risk_evidence": risk_evidence,
        "noise_filter": {
            "excluded_dirs": sorted(_SKIP_DIRS),
            "excluded_dir_prefixes": list(_SKIP_DIR_PREFIXES),
            "weak_signal_prefixes": list(_WEAK_SIGNAL_PREFIXES),
            "policy": "single keyword hits in tools/docs/scripts stay weak unless supported by identity or app source evidence",
        },
        "document_authority": dict(_DOCUMENT_AUTHORITY_POLICY),
        "detected_files": dict(detected_files),
        "languages": list(languages),
    }


def _build_project_evidence_graph(evidence_card: dict[str, Any], domain_confidence: dict[str, Any]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    for item in evidence_card.get("identity_evidence", []) if isinstance(evidence_card.get("identity_evidence"), list) else []:
        if not isinstance(item, dict):
            continue
        node_id = f"identity:{item.get('path')}"
        nodes.append(
            {
                "id": node_id,
                "kind": "identity",
                "path": item.get("path"),
                "signals": _dedupe([str(signal) for signal in item.get("signals", []) if signal]),
                "confidence": "source",
            }
        )
    for item in evidence_card.get("code_evidence", []) if isinstance(evidence_card.get("code_evidence"), list) else []:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "")
        node_id = f"code:{domain}"
        paths = _dedupe([str(path) for path in item.get("paths", []) if path])
        nodes.append({"id": node_id, "kind": "code", "domain": domain, "paths": paths, "confidence": "source"})
        for path in paths[:8]:
            edges.append({"from": node_id, "to": f"path:{path}", "relation": "observed_in"})
    candidates = domain_confidence.get("candidates", {}) if isinstance(domain_confidence.get("candidates"), dict) else {}
    for domain, candidate in candidates.items():
        if not isinstance(candidate, dict):
            continue
        node_id = f"domain:{domain}"
        nodes.append(
            {
                "id": node_id,
                "kind": "domain",
                "domain": str(domain),
                "confidence": str(candidate.get("confidence") or "weak"),
                "evidence": _dedupe([str(ref) for ref in candidate.get("evidence", []) if ref])[:12],
                "usable_for_harness_core": bool(candidate.get("usable_for_harness_core")),
            }
        )
        for ref in _dedupe([str(ref) for ref in candidate.get("evidence", []) if ref])[:8]:
            edges.append({"from": f"evidence:{ref}", "to": node_id, "relation": "supports"})
    validation = evidence_card.get("validation_evidence", {}) if isinstance(evidence_card.get("validation_evidence"), dict) else {}
    risk = evidence_card.get("risk_evidence", {}) if isinstance(evidence_card.get("risk_evidence"), dict) else {}
    nodes.append(
        {
            "id": "validation:project",
            "kind": "validation",
            "frameworks": _dedupe([str(item) for item in validation.get("frameworks", []) if item]),
            "test_paths": _dedupe([str(item) for item in validation.get("test_paths", []) if item])[:12],
        }
    )
    nodes.append(
        {
            "id": "risk:project",
            "kind": "risk",
            "signals": _dedupe([str(item) for item in risk.get("signals", []) if item]),
            "default_forbidden": _dedupe([str(item) for item in risk.get("default_forbidden", []) if item]),
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "available",
        "source": "project_scan",
        "graph_policy": "identity, code, validation, and risk evidence are separated before company compilation",
        "nodes": nodes,
        "edges": edges,
        "confidence_summary": {
            "confirmed": _dedupe([str(item) for item in domain_confidence.get("confirmed", []) if item]),
            "suspected": _dedupe([str(item) for item in domain_confidence.get("suspected", []) if item]),
            "weak": _dedupe([str(item) for item in domain_confidence.get("weak", []) if item]),
        },
        "noise_boundary": {
            "weak_domains_not_core": True,
            "cambrian_process_noise_excluded": True,
            "missing_paths_not_promoted": True,
        },
    }


def _identity_evidence(root: Path) -> list[dict[str, Any]]:
    """프로젝트 정체성을 알려주는 문서와 엔트리포인트 evidence를 수집한다."""
    evidence: list[dict[str, Any]] = []
    for ref in _IDENTITY_FILE_CANDIDATES:
        path = root / ref
        if not path.is_file():
            continue
        text = _read_identity_text(path)
        signals = _identity_signals(text, ref)
        if signals or ref in {
            "CONTEXT_INDEX.md",
            "PROJECT_BRIEF.md",
            "PRODUCT_CONSTITUTION.md",
            "ROADMAP.md",
            "DECISION_LOG.md",
            "AGENTS.md",
            "CLAUDE.md",
            "README.md",
            "TODO.md",
            "package.json",
            "pyproject.toml",
        }:
            evidence.append(
                {
                    "path": ref.replace("\\", "/"),
                    "signals": signals,
                    "bytes_read": min(path.stat().st_size, _IDENTITY_READ_LIMIT_BYTES),
                }
            )
    return evidence[:12]


def _read_identity_text(path: Path) -> str:
    """정체성 evidence용 파일을 안전한 크기 안에서 읽는다."""
    try:
        if path.name.lower() in _SENSITIVE_FILE_NAMES:
            return ""
        if path.stat().st_size > _IDENTITY_READ_LIMIT_BYTES:
            return path.read_text(encoding="utf-8", errors="ignore")[:_IDENTITY_READ_LIMIT_BYTES].lower()
        return path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return ""


def _identity_signals(text: str, ref: str = "") -> list[str]:
    """문서 텍스트에서 제품 정체성 신호를 뽑는다."""
    signals: list[str] = []
    if str(ref).replace("\\", "/").lower().endswith("claude.md"):
        return signals
    if _contains_any(text, _PLATFORM_IDENTITY_KEYWORDS):
        signals.append("agent_marketplace_platform")
    if _contains_any(text, _CAMBRIAN_BRIDGE_KEYWORDS):
        signals.append("cambrian_local_bridge")
    for domain, keywords in _DOMAIN_IDENTITY_KEYWORDS.items():
        if _identity_domain_match(domain, text, keywords):
            signals.append(domain)
    return _dedupe(signals)


def _identity_domain_match(domain: str, text: str, keywords: list[str]) -> bool:
    if domain == "hotel_site":
        return _contains_hotel_site_identity(text)
    return _contains_any(text, keywords)


def _contains_hotel_site_identity(text: str) -> bool:
    strong_terms = ["hotel", "lodging", "accommodation", "hospitality", "호텔", "숙박", "객실", "체크인"]
    booking_terms = ["room booking", "booking engine", "booking site", "reservation page", "예약 페이지", "객실 예약"]
    return _contains_any(text, strong_terms) or _contains_any(text, booking_terms)


def _validation_evidence(
    paths: dict[str, list[str]],
    detected_files: dict[str, bool],
    test_frameworks: list[str],
) -> dict[str, Any]:
    """테스트/검증 관련 evidence를 정리한다."""
    return {
        "frameworks": list(test_frameworks),
        "config_paths": _dedupe(
            [
                *paths.get("package_json", []),
                *paths.get("tsconfig", []),
                *paths.get("jest_config", []),
                *paths.get("config", []),
            ]
        )[:12],
        "test_paths": _dedupe(paths.get("tests", []))[:12],
        "detected_test_dirs": {
            "tests_dir": bool(detected_files.get("tests_dir")),
            "backend_tests_dir": bool(detected_files.get("backend_tests_dir")),
        },
    }


def _code_evidence(paths: dict[str, list[str]]) -> list[dict[str, Any]]:
    """도메인 후보별 코드 경로 evidence를 정리한다."""
    evidence: list[dict[str, Any]] = []
    for domain in _detect_domains(paths):
        refs = _domain_refs(paths, domain)
        if refs:
            evidence.append({"domain": domain, "paths": refs[:12]})
    return evidence


def _risk_evidence(identity_evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """정책 문서에서 위험 경계 신호를 추출한다."""
    signals: list[str] = []
    refs: list[str] = []
    for item in identity_evidence:
        ref = str(item.get("path") or "")
        path_signals = [str(signal) for signal in item.get("signals", []) if signal]
        if ref:
            refs.append(ref)
        joined = " ".join(path_signals).lower()
        for risk_id, keywords in _RISK_KEYWORDS.items():
            if any(keyword.lower() in joined for keyword in keywords):
                signals.append(risk_id)
    return {
        "policy_refs": _dedupe(refs),
        "signals": _dedupe(signals),
        "default_forbidden": [".env", "secrets", "git push", "unapproved package install", "automatic source mutation"],
    }


def _build_domain_confidence(paths: dict[str, list[str]], evidence_card: dict[str, Any]) -> dict[str, Any]:
    """도메인 후보를 confirmed/suspected/weak로 분류한다."""
    candidates: dict[str, dict[str, Any]] = {}
    identity_by_signal = _identity_refs_by_signal(evidence_card)
    if identity_by_signal.get("agent_marketplace_platform"):
        candidates["agent_marketplace_platform"] = _domain_candidate(
            "agent_marketplace_platform",
            "confirmed",
            identity_by_signal["agent_marketplace_platform"],
            "project identity documents describe an AI agent builder/download platform",
        )
    if identity_by_signal.get("cambrian_local_bridge"):
        candidates["cambrian_local_bridge"] = _domain_candidate(
            "cambrian_local_bridge",
            "confirmed",
            identity_by_signal["cambrian_local_bridge"],
            "project identity documents describe Cambrian as a local bridge/runtime option",
        )
    for domain in _DOMAIN_IDENTITY_KEYWORDS:
        if domain in candidates:
            continue
        identity_refs = identity_by_signal.get(domain, [])
        if identity_refs:
            candidates[domain] = _domain_candidate(
                domain,
                "confirmed",
                identity_refs,
                "project identity documents name this product domain",
            )
    for domain in _detect_domains(paths):
        refs = _domain_refs(paths, domain)
        identity_refs = identity_by_signal.get(domain, [])
        confidence = _classify_domain_confidence(domain, refs, identity_refs)
        reason = _domain_confidence_reason(domain, confidence, refs, identity_refs)
        candidates[domain] = _domain_candidate(domain, confidence, _dedupe([*identity_refs, *refs])[:12], reason)
    return {
        "schema_version": SCHEMA_VERSION,
        "policy": "confirmed and suspected domains may shape harnesses; weak domains stay as references only",
        "candidates": candidates,
        "confirmed": sorted([domain for domain, item in candidates.items() if item.get("confidence") == "confirmed"]),
        "suspected": sorted([domain for domain, item in candidates.items() if item.get("confidence") == "suspected"]),
        "weak": sorted([domain for domain, item in candidates.items() if item.get("confidence") == "weak"]),
    }


def _identity_refs_by_signal(evidence_card: dict[str, Any]) -> dict[str, list[str]]:
    """identity evidence를 signal별 path 목록으로 뒤집는다."""
    refs: dict[str, list[str]] = {}
    for item in evidence_card.get("identity_evidence", []) if isinstance(evidence_card.get("identity_evidence"), list) else []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        for signal in item.get("signals", []) if isinstance(item.get("signals"), list) else []:
            refs.setdefault(str(signal), [])
            if path and path not in refs[str(signal)]:
                refs[str(signal)].append(path)
    return refs


def _domain_refs(paths: dict[str, list[str]], domain: str) -> list[str]:
    """도메인 이름에 해당하는 scan bucket 경로를 반환한다."""
    bucket_by_domain = {
        "website": ["typescript", "python"],
        "hotel_site": [],
        "auth": ["auth", "login"],
        "login": ["login"],
        "ddmq": ["ddmq"],
        "stage_pipeline": ["stage_pipeline"],
        "schema_validation": ["schema_validation"],
        "llm_api": ["llm_api"],
        "pipeline_automation": ["pipeline"],
        "suppression": ["suppression"],
        "webhook": ["webhook"],
        "send_pipeline": ["send", "pipeline"],
        "outbound": ["outbound"],
        "scoring": ["scoring"],
        "supabase": ["supabase"],
        "customer": ["customer"],
        "tests": ["tests"],
        "api": ["typescript", "python"],
    }
    refs: list[str] = []
    for bucket in bucket_by_domain.get(domain, [domain]):
        refs.extend(paths.get(bucket, []))
    if domain == "api":
        refs = [
            ref
            for ref in refs
            if "/api/" in ref.lower().replace("\\", "/")
            or ref.lower().replace("\\", "/").endswith("/api")
            or "routes" in ref.lower()
            or "route." in ref.lower()
            or "server" in ref.lower()
        ]
    if domain in {"auth", "login"}:
        refs = [
            ref
            for ref in refs
            if _is_auth_domain_path(ref)
        ]
    return _dedupe(refs)


def _is_auth_domain_path(ref: str) -> bool:
    lower = str(ref or "").lower().replace("\\", "/")
    path_text = lower.replace("/", " ").replace("-", " ").replace("_", " ")
    return any(
        _contains_keyword(path_text, token)
        for token in ["auth", "login", "session", "jwt", "middleware"]
    )


def _classify_domain_confidence(domain: str, refs: list[str], identity_refs: list[str]) -> str:
    """도메인 후보의 신뢰도를 단순하고 보수적으로 판정한다."""
    if identity_refs:
        return "confirmed"
    if domain == "tests" and refs:
        return "suspected"
    if not refs:
        return "weak"
    if any(_is_app_source_ref(ref) for ref in refs):
        return "suspected"
    if len(refs) >= 2 and not all(_is_weak_signal_ref(ref) for ref in refs):
        return "suspected"
    return "weak"


def _domain_confidence_reason(domain: str, confidence: str, refs: list[str], identity_refs: list[str]) -> str:
    """도메인 신뢰도 판정 이유를 사람이 읽을 수 있게 만든다."""
    if confidence == "confirmed":
        return "identity evidence names this domain" if identity_refs else "project evidence confirms this domain"
    if confidence == "suspected":
        return "code evidence points to this domain, but identity evidence does not explicitly confirm it"
    if refs:
        return "only weak keyword evidence was found; do not create domain-specific workforce from this alone"
    return "no concrete code evidence was found"


def _domain_candidate(domain: str, confidence: str, evidence: list[str], reason: str) -> dict[str, Any]:
    """도메인 후보 payload를 만든다."""
    return {
        "name": domain,
        "confidence": confidence,
        "evidence": _dedupe(evidence)[:12],
        "reason": reason,
        "usable_for_harness_core": confidence in {"confirmed", "suspected"},
    }


def _effective_domains(domain_confidence: dict[str, Any]) -> list[str]:
    """weak 도메인을 제외한 하네스 생성용 도메인 목록을 반환한다."""
    candidates = domain_confidence.get("candidates", {}) if isinstance(domain_confidence.get("candidates"), dict) else {}
    ordered: list[str] = []
    for confidence in ["confirmed", "suspected"]:
        for domain, candidate in candidates.items():
            if isinstance(candidate, dict) and candidate.get("confidence") == confidence:
                ordered.append(str(domain))
    return _dedupe(ordered)


def _is_app_source_ref(ref: str) -> bool:
    """도메인 근거가 실제 앱/서비스 코드 경로인지 판단한다."""
    lower = str(ref or "").lower().replace("\\", "/")
    return lower.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".sql", ".html")) and lower.startswith(_APP_SOURCE_PREFIXES)


def _is_weak_signal_ref(ref: str) -> bool:
    """도구/문서/스크립트 경로의 단독 키워드 신호를 약한 근거로 본다."""
    lower = str(ref or "").lower().replace("\\", "/")
    return lower.startswith(_WEAK_SIGNAL_PREFIXES)


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
