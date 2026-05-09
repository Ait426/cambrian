"""로컬 pack catalog 조회와 project fit 분석."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine._data_path import get_bundled_pack_catalog_path
from engine.project_pack_install import PackManifest, PackManifestLoader

logger = logging.getLogger(__name__)

CATALOG_SCHEMA_VERSION = "1.0"
FIT_RANK = {"strong": 4, "partial": 3, "weak": 2, "unknown": 1}


def _slug(value: str | None, fallback: str = "item") -> str:
    """문자열을 비교 가능한 slug로 바꾼다."""
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip().lower()).strip("-")
    return text or fallback


def _load_yaml(path: Path) -> dict[str, Any]:
    """YAML 파일을 dict로 읽는다."""
    target = Path(path).resolve()
    if not target.exists():
        return {}
    try:
        payload = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("pack catalog YAML load failed: %s (%s)", target, exc)
        raise ValueError(f"YAML을 읽을 수 없습니다: {target}") from exc
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML top level must be a mapping: {target}")
    return payload


def _as_list(value: Any) -> list[str]:
    """값을 문자열 리스트로 정규화한다."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _as_dict(value: Any) -> dict[str, Any]:
    """값이 dict이면 복사하고 아니면 빈 dict를 반환한다."""
    return dict(value) if isinstance(value, dict) else {}


def _lower_set(values: list[str]) -> set[str]:
    """문자열 리스트를 소문자 set으로 바꾼다."""
    return {str(value).strip().lower() for value in values if str(value).strip()}


def _relative(path: Path, root: Path) -> str:
    """root 기준 상대 경로를 반환한다."""
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve())).replace("\\", "/")
    except ValueError:
        return str(Path(path).resolve())


def _source_repo_root() -> Path:
    """현재 engine 패키지 위치에서 source tree 루트를 추정한다."""
    return Path(__file__).resolve().parents[1]


def resolve_pack_catalog_path(repo_root: Path | None = None, project_root: Path | None = None) -> Path:
    """source tree와 installed wheel 양쪽에서 pack catalog 경로를 찾는다."""
    candidates: list[Path] = []
    if project_root is not None:
        candidates.append(Path(project_root).resolve() / "packs" / "catalog.yaml")
    candidates.append(Path.cwd().resolve() / "packs" / "catalog.yaml")
    if repo_root is not None:
        candidates.append(Path(repo_root).resolve() / "packs" / "catalog.yaml")
    candidates.append(_source_repo_root() / "packs" / "catalog.yaml")
    candidates.append(get_bundled_pack_catalog_path())

    seen: set[Path] = set()
    ordered: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(resolved)
        if resolved.exists():
            return resolved
    return ordered[0] if ordered else (Path.cwd().resolve() / "packs" / "catalog.yaml")


def default_pack_catalog_path(repo_root: Path) -> Path:
    """기본 local/bundled pack catalog 경로를 반환한다."""
    return resolve_pack_catalog_path(repo_root=repo_root)


@dataclass
class PackCatalogEntry:
    """로컬 catalog에 등록된 pack 항목."""

    pack_id: str
    pack_name: str
    pack_kind: str
    version: str | None
    manifest_path: str
    description: str | None
    tags: list[str]
    compatibility: dict[str, Any]
    maturity: str | None
    namespace: str | None = None
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    manifest_sha256: str | None = None
    trust_level: str | None = None
    proof_status: str | None = None
    proof_refs: list[str] = field(default_factory=list)
    qualification_refs: list[str] = field(default_factory=list)
    canary_refs: list[str] = field(default_factory=list)
    known_limits: list[str] = field(default_factory=list)
    release_report_ref: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackCatalog:
    """local pack catalog."""

    schema_version: str
    updated_at: str | None
    source_kind: str
    entries: list[PackCatalogEntry]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "source_kind": self.source_kind,
            "entries": [entry.to_dict() for entry in self.entries],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass
class PackFitSummary:
    """현재 project와 pack compatibility 요약."""

    pack_id: str
    fit_status: str
    score: float
    reasons: list[str]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


class PackCatalogStore:
    """packs/catalog.yaml 저장소."""

    def load(self, path: Path) -> PackCatalog:
        """local catalog를 로드한다."""
        target = Path(path).resolve()
        if not target.exists():
            return PackCatalog(
                schema_version=CATALOG_SCHEMA_VERSION,
                updated_at=None,
                source_kind="local_seed",
                entries=[],
                errors=[f"pack catalog not found: {target}"],
            )
        payload = _load_yaml(target)
        entries = [
            _entry_from_dict(item)
            for item in payload.get("entries", []) or []
            if isinstance(item, dict)
        ]
        return PackCatalog(
            schema_version=str(payload.get("schema_version") or CATALOG_SCHEMA_VERSION),
            updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
            source_kind=str(payload.get("source_kind") or "local_seed"),
            entries=entries,
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )


class PackCatalogResolver:
    """catalog entry와 manifest path resolver."""

    def find_entry(self, catalog: PackCatalog, pack_id_or_name: str) -> PackCatalogEntry:
        """pack id 또는 name으로 catalog entry를 찾는다."""
        wanted = str(pack_id_or_name or "").strip()
        wanted_slug = _slug(wanted)
        for entry in catalog.entries:
            if entry.pack_id == wanted or entry.pack_name == wanted or _slug(entry.pack_name) == wanted_slug:
                return entry
        raise KeyError(wanted)

    def resolve_manifest_path(self, repo_root: Path, entry: PackCatalogEntry, catalog_path: Path | None = None) -> Path:
        """catalog entry의 manifest path를 실제 경로로 해석한다."""
        raw = Path(entry.manifest_path)
        if raw.is_absolute():
            return raw.resolve()
        catalog = Path(catalog_path).resolve() if catalog_path is not None else resolve_pack_catalog_path(repo_root=repo_root)
        catalog_dir = catalog.parent
        if raw.parts and raw.parts[0] == "packs":
            candidate = catalog_dir.parent / raw
            if candidate.exists():
                return candidate.resolve()
            return (catalog_dir / Path(*raw.parts[1:])).resolve()
        return (catalog_dir / raw).resolve()


class PackFitAnalyzer:
    """현재 project 신호로 pack fit을 계산한다."""

    def analyze(self, project_root: Path, entry: PackCatalogEntry) -> PackFitSummary:
        """compatibility와 project signal을 비교한다."""
        root = Path(project_root).resolve()
        signals = _collect_project_signals(root)
        compatibility = entry.compatibility
        compat_stacks = _lower_set(_as_list(compatibility.get("stacks") or compatibility.get("stack")))
        compat_tests = _lower_set(_as_list(compatibility.get("test_frameworks")))
        compat_lanes = _lower_set(_as_list(compatibility.get("lane_ids")))
        tags = _lower_set(entry.tags)

        detected_stacks = _lower_set(signals.get("stacks", []))
        detected_tests = _lower_set(signals.get("test_frameworks", []))
        detected_lanes = _lower_set(signals.get("lane_ids", []))
        detected_tags = _lower_set(signals.get("tags", []))

        reasons: list[str] = []
        warnings: list[str] = []
        known_signal = bool(detected_stacks or detected_tests or detected_lanes or detected_tags)
        if not known_signal:
            return PackFitSummary(
                pack_id=entry.pack_id,
                fit_status="unknown",
                score=0.0,
                reasons=["insufficient project signals"],
                warnings=["프로젝트 stack/test/lane 신호가 부족해 fit을 확정할 수 없습니다."],
            )

        stack_match = bool(compat_stacks and detected_stacks.intersection(compat_stacks))
        test_match = bool(compat_tests and detected_tests.intersection(compat_tests))
        lane_match = bool(
            (compat_lanes and detected_lanes.intersection(compat_lanes))
            or ({"auth", "login"} & tags and {"auth", "login", "account"} & detected_tags)
        )

        if stack_match:
            reasons.append(f"stack matches: {', '.join(sorted(detected_stacks.intersection(compat_stacks)))}")
        elif compat_stacks:
            warnings.append(f"stack mismatch: expected {', '.join(sorted(compat_stacks))}")

        if test_match:
            reasons.append(f"test framework matches: {', '.join(sorted(detected_tests.intersection(compat_tests)))}")
        elif compat_tests:
            warnings.append(f"test framework mismatch: expected {', '.join(sorted(compat_tests))}")

        if lane_match:
            reasons.append("lane/tags match auth/login strongest lane")
        elif compat_lanes or tags:
            warnings.append("strongest lane signal is weak or absent")

        if stack_match and test_match and lane_match:
            status = "strong"
            score = 0.95
        elif stack_match and (test_match or lane_match):
            status = "partial"
            score = 0.65
        elif stack_match or test_match or lane_match:
            status = "partial"
            score = 0.45
        else:
            status = "weak"
            score = 0.15
            if not warnings:
                warnings.append("catalog compatibility does not match detected project signals")

        return PackFitSummary(
            pack_id=entry.pack_id,
            fit_status=status,
            score=score,
            reasons=reasons or ["some project signals were detected, but fit is weak"],
            warnings=warnings,
        )


def load_default_catalog(repo_root: Path) -> PackCatalog:
    """기본 local catalog를 로드한다."""
    return PackCatalogStore().load(default_pack_catalog_path(repo_root))


def render_pack_list(entries: list[PackCatalogEntry], fits: dict[str, PackFitSummary]) -> str:
    """pack 목록을 사람이 읽기 좋게 렌더링한다."""
    lines = ["Available Packs", "==================================================", ""]
    if not entries:
        lines.append("none")
        return "\n".join(lines)
    for entry in entries:
        fit = fits.get(entry.pack_id)
        lines.extend(
            [
                f"- {entry.pack_id}",
                f"  namespace  : {entry.namespace or 'local'}",
                f"  kind       : {entry.pack_kind}",
                f"  version    : {entry.version or 'none'}",
                f"  fit        : {fit.fit_status if fit else 'unknown'}",
                f"  maturity   : {entry.maturity or 'unknown'}",
                f"  proof      : {entry.proof_status or 'unknown'}",
                f"  description: {entry.description or 'none'}",
            ]
        )
    return "\n".join(lines)


def render_pack_show(
    entry: PackCatalogEntry,
    manifest: PackManifest,
    fit: PackFitSummary,
    manifest_path: Path,
    repo_root: Path,
) -> str:
    """pack 상세를 렌더링한다."""
    lines = [
        "Pack",
        "==================================================",
        "",
        "Pack:",
        f"  id      : {entry.pack_id}",
        f"  namespace: {entry.namespace or 'local'}",
        f"  name    : {entry.pack_name}",
        f"  kind    : {entry.pack_kind}",
        f"  version : {entry.version or 'none'}",
        f"  maturity: {entry.maturity or 'unknown'}",
        f"  proof   : {entry.proof_status or 'unknown'}",
        "",
        "Description:",
        f"  {entry.description or 'none'}",
        "",
        "Manifest:",
        f"  {_relative(manifest_path, repo_root)}",
        "",
        "Fit:",
        f"  status: {fit.fit_status}",
        f"  score : {fit.score:.2f}",
    ]
    if fit.reasons:
        lines.extend(["", "Why:"])
        lines.extend([f"  - {item}" for item in fit.reasons])
    if fit.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in fit.warnings])
    if entry.known_limits:
        lines.extend(["", "Known limits:"])
        lines.extend([f"  - {item}" for item in entry.known_limits])
    if entry.proof_refs or entry.qualification_refs or entry.canary_refs:
        lines.extend(["", "Proof refs:"])
        for label, refs in [
            ("proof", entry.proof_refs),
            ("qualification", entry.qualification_refs),
            ("canary", entry.canary_refs),
        ]:
            if refs:
                lines.append(f"  {label}: {', '.join(refs)}")
    if entry.dependencies:
        lines.extend(["", "Dependencies:"])
        for dependency in entry.dependencies:
            pack_ref = dependency.get("pack_ref") or dependency.get("ref") or "unknown"
            constraint = dependency.get("version_constraint")
            suffix = f" ({constraint})" if constraint else ""
            optional = " optional" if dependency.get("optional") else ""
            lines.append(f"  - {pack_ref}{suffix}{optional}")
    lines.extend(
        [
            "",
            "Compatibility:",
            f"  stacks          : {', '.join(_as_list(entry.compatibility.get('stacks'))) or 'none'}",
            f"  test_frameworks : {', '.join(_as_list(entry.compatibility.get('test_frameworks'))) or 'none'}",
            f"  lane_ids        : {', '.join(_as_list(entry.compatibility.get('lane_ids'))) or 'none'}",
            "",
            "Includes:",
            f"  workers   : {len(manifest.workers)}",
            f"  teams     : {len(manifest.teams)}",
            f"  templates : {len(manifest.templates)}",
            f"  benchmarks: {len(manifest.benchmarks)}",
            "",
            "Install:",
            f"  cambrian install pack {entry.pack_id}",
        ]
    )
    return "\n".join(lines)


def render_pack_recommend(entry: PackCatalogEntry | None, fit: PackFitSummary | None) -> str:
    """pack 추천 결과를 렌더링한다."""
    lines = ["Recommended Pack", "==================================================", ""]
    if entry is None or fit is None:
        lines.extend(
            [
                "No local pack recommendation yet.",
                "",
                "Why:",
                "  - local catalog is empty or no pack could be scored",
            ]
        )
        return "\n".join(lines)
    if fit.fit_status == "unknown":
        lines.extend(["No strong recommendation yet.", ""])
    lines.extend([entry.pack_id, "", "Fit:", f"  {fit.fit_status} ({fit.score:.2f})"])
    if fit.reasons:
        lines.extend(["", "Why:"])
        lines.extend([f"  - {item}" for item in fit.reasons])
    if fit.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in fit.warnings])
    lines.extend(["", "Install:", f"  cambrian install pack {entry.pack_id}"])
    return "\n".join(lines)


def catalog_payload(
    catalog: PackCatalog,
    project_root: Path,
    repo_root: Path,
    kind: str | None = None,
) -> dict[str, Any]:
    """catalog와 fit을 JSON 출력용 payload로 만든다."""
    entries = _filter_entries(catalog.entries, kind)
    analyzer = PackFitAnalyzer()
    resolver = PackCatalogResolver()
    catalog_path = default_pack_catalog_path(repo_root)
    packs = []
    for entry in entries:
        fit = analyzer.analyze(project_root, entry)
        packs.append(
            {
                "entry": entry.to_dict(),
                "fit": fit.to_dict(),
                "manifest_path": _relative(resolver.resolve_manifest_path(repo_root, entry, catalog_path=catalog_path), repo_root),
            }
        )
    return {
        "catalog": catalog.to_dict(),
        "packs": packs,
    }


def best_recommendation(catalog: PackCatalog, project_root: Path) -> tuple[PackCatalogEntry | None, PackFitSummary | None]:
    """catalog에서 가장 fit이 좋은 pack을 고른다."""
    analyzer = PackFitAnalyzer()
    scored = [(entry, analyzer.analyze(project_root, entry)) for entry in catalog.entries]
    if not scored:
        return None, None
    scored.sort(key=lambda item: (FIT_RANK.get(item[1].fit_status, 0), item[1].score, item[0].pack_id), reverse=True)
    return scored[0]


def manifest_for_entry(repo_root: Path, entry: PackCatalogEntry) -> tuple[Path, PackManifest]:
    """entry가 가리키는 manifest path와 loaded manifest를 반환한다."""
    catalog_path = default_pack_catalog_path(repo_root)
    manifest_path = PackCatalogResolver().resolve_manifest_path(repo_root, entry, catalog_path=catalog_path)
    manifest = PackManifestLoader().load(manifest_path)
    return manifest_path, manifest


def local_catalog_source_ref(repo_root: Path, entry: PackCatalogEntry) -> str:
    """installed_packs provenance에 남길 local catalog ref를 반환한다."""
    return f"{_relative(default_pack_catalog_path(repo_root), repo_root)}#{entry.pack_id}"


def _entry_from_dict(payload: dict[str, Any]) -> PackCatalogEntry:
    """dict에서 catalog entry를 만든다."""
    missing = [
        key
        for key in ("pack_id", "pack_name", "pack_kind", "manifest_path")
        if not str(payload.get(key) or "").strip()
    ]
    if missing:
        raise ValueError(f"pack catalog entry missing required fields: {', '.join(missing)}")
    return PackCatalogEntry(
        pack_id=str(payload.get("pack_id")).strip(),
        pack_name=str(payload.get("pack_name")).strip(),
        pack_kind=str(payload.get("pack_kind")).strip(),
        version=str(payload.get("version")) if payload.get("version") is not None else None,
        manifest_path=str(payload.get("manifest_path")).strip(),
        description=str(payload.get("description")) if payload.get("description") is not None else None,
        tags=_as_list(payload.get("tags")),
        compatibility=_as_dict(payload.get("compatibility")),
        maturity=str(payload.get("maturity")) if payload.get("maturity") is not None else None,
        namespace=str(payload.get("namespace")).strip() if payload.get("namespace") is not None else None,
        dependencies=[
            dict(item)
            for item in payload.get("dependencies", []) or []
            if isinstance(item, dict)
        ],
        manifest_sha256=str(payload.get("manifest_sha256")).strip().lower()
        if payload.get("manifest_sha256") is not None
        else None,
        trust_level=str(payload.get("trust_level")).strip() if payload.get("trust_level") is not None else None,
        proof_status=str(payload.get("proof_status")).strip() if payload.get("proof_status") is not None else None,
        proof_refs=_as_list(payload.get("proof_refs")),
        qualification_refs=_as_list(payload.get("qualification_refs")),
        canary_refs=_as_list(payload.get("canary_refs")),
        known_limits=_as_list(payload.get("known_limits")),
        release_report_ref=str(payload.get("release_report_ref")).strip()
        if payload.get("release_report_ref") is not None
        else None,
        warnings=[str(item) for item in payload.get("warnings", []) if item],
    )


def _filter_entries(entries: list[PackCatalogEntry], kind: str | None) -> list[PackCatalogEntry]:
    """kind filter를 적용한다."""
    if not kind:
        return list(entries)
    return [entry for entry in entries if entry.pack_kind == kind]


def _collect_project_signals(root: Path) -> dict[str, list[str]]:
    """project 파일과 `.cambrian/` artifact에서 fit signal을 모은다."""
    stacks: list[str] = []
    tests: list[str] = []
    lanes: list[str] = []
    tags: list[str] = []

    try:
        from engine.project_harness_profile import ProjectHarnessScanner

        profile = ProjectHarnessScanner().scan(root)
        for item in [profile.language, *profile.languages]:
            text = str(item or "").lower()
            if text and text != "unknown":
                stacks.append(text)
        for item in [profile.test_framework, *profile.test_frameworks]:
            text = str(item or "").lower()
            if text and text not in {"unknown", "unknown-tests"}:
                tests.append(text)
        tags.extend([str(item).lower() for item in profile.domains if item])
        if "typescript" in stacks:
            stacks.append("javascript")
    except Exception as exc:
        logger.warning("project harness profile signal scan failed: %s", exc)

    for payload in _project_payloads(root):
        _collect_from_payload(payload, stacks, tests, lanes, tags)

    if _looks_like_python(root):
        stacks.append("python")
    if _looks_like_pytest(root):
        tests.append("pytest")
    if _has_auth_login_paths(root):
        tags.extend(["auth", "login"])

    return {
        "stacks": sorted(_lower_set(stacks)),
        "test_frameworks": sorted(_lower_set(tests)),
        "lane_ids": sorted(_lower_set(lanes)),
        "tags": sorted(_lower_set(tags)),
    }


def _project_payloads(root: Path) -> list[dict[str, Any]]:
    """fit 분석에 쓸 수 있는 project artifact들을 읽는다."""
    paths = [
        root / ".cambrian" / "profile.yaml",
        root / ".cambrian" / "project.yaml",
        root / ".cambrian" / "harness" / "profile.yaml",
        root / ".cambrian" / "lane" / "profile.yaml",
        root / ".cambrian" / "lane" / "playbook.yaml",
    ]
    payloads: list[dict[str, Any]] = []
    for path in paths:
        try:
            payload = _load_yaml(path)
        except ValueError:
            continue
        if payload:
            payloads.append(payload)
    return payloads


def _collect_from_payload(
    payload: dict[str, Any],
    stacks: list[str],
    tests: list[str],
    lanes: list[str],
    tags: list[str],
) -> None:
    """YAML payload에서 stack/test/lane/tag 신호를 추출한다."""
    stacks.extend(_as_list(payload.get("stack")))
    stacks.extend(_as_list(payload.get("language")))
    stacks.extend(_as_list(payload.get("languages")))
    project = _as_dict(payload.get("project"))
    stacks.extend(_as_list(project.get("stack")))

    test_command = str(payload.get("test_command") or "")
    test_meta = _as_dict(payload.get("test"))
    test_command = f"{test_command} {test_meta.get('command') or ''}".strip()
    if "pytest" in test_command.lower():
        tests.append("pytest")

    lane_id = payload.get("lane_id") or payload.get("default_lane")
    if lane_id:
        lanes.append(str(lane_id))
    lane = _as_dict(payload.get("lane"))
    if lane.get("lane_id"):
        lanes.append(str(lane.get("lane_id")))

    tags.extend(_as_list(payload.get("tags")))
    text = json.dumps(payload, ensure_ascii=False).lower()
    if "auth" in text:
        tags.append("auth")
    if "login" in text:
        tags.append("login")
    if "account" in text:
        tags.append("account")


def _looks_like_python(root: Path) -> bool:
    """프로젝트가 Python처럼 보이는지 가볍게 판정한다."""
    markers = ["pyproject.toml", "setup.py", "requirements.txt", "tox.ini"]
    if any((root / marker).exists() for marker in markers):
        return True
    for folder in ["src", "tests", "demo"]:
        target = root / folder
        if target.exists() and any(target.rglob("*.py")):
            return True
    return False


def _looks_like_pytest(root: Path) -> bool:
    """pytest 사용 가능성이 있는지 가볍게 판정한다."""
    markers = ["pytest.ini", "conftest.py"]
    if any((root / marker).exists() for marker in markers):
        return True
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            if "pytest" in pyproject.read_text(encoding="utf-8").lower():
                return True
        except OSError:
            return False
    tests_dir = root / "tests"
    return tests_dir.exists() and any(tests_dir.rglob("test_*.py"))


def _has_auth_login_paths(root: Path) -> bool:
    """auth/login/account 관련 파일명이 있는지 확인한다."""
    candidates: list[Path] = []
    for folder in ["src", "tests", "demo"]:
        target = root / folder
        if target.exists():
            candidates.extend(list(target.rglob("*.py"))[:200])
    haystack = " ".join(str(path).lower() for path in candidates)
    return any(token in haystack for token in ["auth", "login", "account"])
