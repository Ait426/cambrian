"""로컬 pack catalog를 정적 Web Hiring Desk로 생성한다."""

from __future__ import annotations

import argparse
import html
import json
import shutil
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "packs" / "catalog.yaml"
DEFAULT_WEB = ROOT / "web"


def main() -> None:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="Cambrian static web pack catalog generator")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG), help="packs/catalog.yaml 경로")
    parser.add_argument("--out", default=str(DEFAULT_WEB), help="web output directory")
    args = parser.parse_args()

    catalog_path = Path(args.catalog).resolve()
    out_dir = Path(args.out).resolve()
    generate(catalog_path, out_dir)
    print(f"web catalog generated: {out_dir}")


def generate(catalog_path: Path, out_dir: Path) -> None:
    """catalog와 manifest를 읽어 정적 web asset을 생성한다."""
    catalog = _read_yaml(catalog_path)
    entries = [entry for entry in catalog.get("entries", []) if isinstance(entry, dict)]
    manifest_records = []
    for entry in entries:
        manifest_path = _resolve_manifest_path(catalog_path, entry)
        manifest = _read_yaml(manifest_path)
        manifest_records.append(
            {
                "entry": entry,
                "manifest": manifest,
                "manifest_path": manifest_path,
                "asset_name": manifest_path.name,
            }
        )

    assets_dir = out_dir / "assets"
    packs_dir = out_dir / "packs"
    studio_dir = out_dir / "studio"
    assets_dir.mkdir(parents=True, exist_ok=True)
    packs_dir.mkdir(parents=True, exist_ok=True)
    studio_dir.mkdir(parents=True, exist_ok=True)

    catalog_asset = _catalog_asset(catalog_path, catalog, manifest_records)
    _write_text(assets_dir / "catalog.json", json.dumps(catalog_asset, indent=2, ensure_ascii=False) + "\n")
    for record in manifest_records:
        shutil.copyfile(record["manifest_path"], assets_dir / record["asset_name"])

    _write_text(out_dir / "index.html", _landing_html(catalog_asset))
    _write_text(studio_dir / "index.html", _studio_html())
    _write_text(packs_dir / "index.html", _packs_index_html(catalog_asset))
    for record in manifest_records:
        pack_id = str(record["entry"].get("pack_id"))
        _write_text(packs_dir / f"{pack_id}.html", _pack_detail_html(record, catalog_asset))


def _read_yaml(path: Path) -> dict[str, Any]:
    """YAML 파일을 읽는다."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _resolve_manifest_path(catalog_path: Path, entry: dict[str, Any]) -> Path:
    """catalog entry의 manifest path를 해석한다."""
    raw = Path(str(entry.get("manifest_path") or ""))
    if raw.is_absolute():
        return raw.resolve()
    return (catalog_path.parent / raw).resolve()


def _catalog_asset(catalog_path: Path, catalog: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """web용 catalog JSON payload를 만든다."""
    packs = []
    for record in records:
        entry = record["entry"]
        manifest = record["manifest"]
        pack_id = str(entry.get("pack_id") or "")
        public_proof = _proof_export_for_pack(catalog_path, pack_id)
        packs.append(
            {
                "pack_id": entry.get("pack_id"),
                "pack_name": entry.get("pack_name"),
                "pack_kind": entry.get("pack_kind"),
                "version": entry.get("version"),
                "maturity": entry.get("maturity"),
                "proof_status": entry.get("proof_status") or "Seed pack. Local proof required.",
                "proof_refs": entry.get("proof_refs") or [],
                "qualification_refs": entry.get("qualification_refs") or [],
                "canary_refs": entry.get("canary_refs") or [],
                "known_limits": entry.get("known_limits") or entry.get("warnings") or [],
                "manifest_sha256": entry.get("manifest_sha256"),
                "trust_level": entry.get("trust_level"),
                "description": entry.get("description"),
                "tags": entry.get("tags") or [],
                "compatibility": entry.get("compatibility") or {},
                "warnings": entry.get("warnings") or [],
                "manifest_asset": f"assets/{record['asset_name']}",
                "detail_path": f"packs/{entry.get('pack_id')}.html",
                "install_command": f"cambrian install pack {entry.get('pack_id')}",
                "manifest_install_command": f"cambrian install manifest ./packs/{record['asset_name']}",
                "proof": public_proof,
                "includes": {
                    "workers": _names(manifest.get("workers"), "id"),
                    "teams": _names(manifest.get("teams"), "name"),
                    "templates": _names(manifest.get("templates"), "name"),
                    "benchmarks": _names(manifest.get("benchmarks"), "name"),
                },
            }
        )
    return {
        "schema_version": "1.0",
        "source_kind": catalog.get("source_kind") or "local_seed",
        "updated_at": catalog.get("updated_at"),
        "packs": packs,
        "boundary": {
            "web": "hiring desk / control plane",
            "local_runtime": "install, job handoff, validation, and proof",
        },
    }


def _names(items: Any, key: str) -> list[str]:
    """manifest list에서 이름/id를 추출한다."""
    if not isinstance(items, list):
        return []
    return [str(item.get(key) or item.get("name") or item.get("id")) for item in items if isinstance(item, dict)]


def _proof_export_for_pack(catalog_path: Path, pack_id: str) -> dict[str, Any] | None:
    """packs/proof_exports의 public-safe proof export를 web payload로 축약한다."""
    if not pack_id:
        return None
    exports_dir = catalog_path.parent / "proof_exports"
    if not exports_dir.exists():
        return None
    candidates = [
        exports_dir / f"{pack_id}.public-proof.yaml",
        exports_dir / f"{pack_id}.public-proof.yml",
        exports_dir / f"{pack_id}.public-proof.json",
    ]
    candidates.extend(sorted(exports_dir.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True))
    candidates.extend(sorted(exports_dir.glob("*.yml"), key=lambda item: item.stat().st_mtime, reverse=True))
    candidates.extend(sorted(exports_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True))
    seen: set[Path] = set()
    for candidate in candidates:
        path = candidate.resolve()
        if path in seen or not path.exists():
            continue
        seen.add(path)
        payload = _read_public_proof(path)
        if str(payload.get("pack_id") or "") != pack_id:
            continue
        if payload.get("privacy_classification") != "public_safe":
            continue
        return _public_proof_payload(payload)
    return None


def _read_public_proof(path: Path) -> dict[str, Any]:
    """public proof YAML/JSON을 읽는다."""
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, yaml.YAMLError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _public_proof_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """web catalog에 안전하게 넣을 proof 필드만 남긴다."""
    metrics: dict[str, Any] = {}
    for item in payload.get("public_metrics", []) or []:
        if not isinstance(item, dict) or not item.get("public_safe", True):
            continue
        key = str(item.get("key") or "")
        if not key or key in {"used_count", "outcome_linked_count"}:
            continue
        metrics[key] = item.get("value")
    return {
        "source": "local_public_export",
        "proof_status": payload.get("proof_status"),
        "reputation_verdict": payload.get("reputation_verdict"),
        "sample_size": payload.get("sample_size") or {},
        "metrics": metrics,
        "caveats": payload.get("caveats") or [],
        "known_limits": payload.get("known_limits") or [],
        "web_summary": payload.get("web_summary"),
        "privacy_classification": payload.get("privacy_classification"),
    }


def _write_text(path: Path, content: str) -> None:
    """UTF-8 텍스트를 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = "\n".join(line.rstrip() for line in content.splitlines()) + "\n"
    path.write_text(normalized, encoding="utf-8", newline="\n")


def _layout(title: str, body: str, nav_prefix: str = "") -> str:
    """공통 HTML layout."""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_e(title)} · Cambrian</title>
  <style>
    :root {{
      --ink: #18211f;
      --paper: #f4efe2;
      --paper-strong: #fff8e8;
      --moss: #40594b;
      --copper: #b95f37;
      --blueprint: #1d4f67;
      --line: rgba(24, 33, 31, 0.18);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      font-family: "Aptos", "Trebuchet MS", sans-serif;
      background:
        radial-gradient(circle at 12% 18%, rgba(185, 95, 55, 0.18), transparent 26rem),
        radial-gradient(circle at 88% 8%, rgba(29, 79, 103, 0.20), transparent 22rem),
        linear-gradient(135deg, #f7f0df 0%, #e8ddc2 48%, #d7e2d1 100%);
      min-height: 100vh;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image: linear-gradient(var(--line) 1px, transparent 1px), linear-gradient(90deg, var(--line) 1px, transparent 1px);
      background-size: 44px 44px;
      mask-image: linear-gradient(to bottom, rgba(0,0,0,.25), transparent 72%);
    }}
    a {{ color: var(--blueprint); }}
    .shell {{ width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 28px 0 64px; }}
    .nav {{ display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 42px; }}
    .brand {{ font-family: Georgia, serif; font-weight: 700; font-size: 1.35rem; letter-spacing: -0.03em; }}
    .nav a {{ text-decoration: none; font-weight: 800; }}
    .hero, .panel, .card {{
      background: rgba(255, 248, 232, 0.78);
      border: 1px solid rgba(24, 33, 31, 0.16);
      box-shadow: 0 24px 80px rgba(31, 42, 37, 0.14);
      backdrop-filter: blur(10px);
    }}
    .hero {{ padding: clamp(28px, 5vw, 64px); border-radius: 34px; position: relative; overflow: hidden; }}
    .eyebrow {{ color: var(--copper); font-weight: 900; text-transform: uppercase; letter-spacing: 0.12em; font-size: 0.78rem; }}
    h1 {{ font-family: Georgia, serif; font-size: clamp(3rem, 9vw, 6.8rem); line-height: 0.88; letter-spacing: -0.075em; margin: 14px 0 20px; max-width: 920px; }}
    h2 {{ font-family: Georgia, serif; font-size: clamp(2rem, 4vw, 3.4rem); line-height: .95; letter-spacing: -0.055em; margin: 0 0 18px; }}
    h3 {{ margin: 0 0 10px; font-size: 1.05rem; }}
    p {{ font-size: 1.04rem; line-height: 1.7; }}
    .lead {{ font-size: clamp(1.08rem, 2vw, 1.35rem); max-width: 760px; }}
    .cta-row {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 26px; }}
    .button {{ display: inline-flex; align-items: center; gap: 8px; padding: 13px 18px; border-radius: 999px; text-decoration: none; font-weight: 900; border: 1px solid var(--ink); background: var(--ink); color: var(--paper); }}
    .button.alt {{ background: transparent; color: var(--ink); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 18px; margin-top: 22px; }}
    .panel, .card {{ border-radius: 26px; padding: 24px; }}
    .section {{ margin-top: 26px; }}
    .badge-row {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0; }}
    .badge {{ border: 1px solid rgba(24,33,31,.22); border-radius: 999px; padding: 7px 10px; background: rgba(255,255,255,.36); font-size: .86rem; font-weight: 800; }}
    pre {{ white-space: pre-wrap; overflow-x: auto; background: #17211f; color: #f7f0df; border-radius: 18px; padding: 18px; font-size: .95rem; line-height: 1.55; }}
    ul {{ padding-left: 1.1rem; }}
    li {{ margin: 7px 0; }}
    .split {{ display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(280px, .85fr); gap: 18px; }}
    .warning {{ border-left: 5px solid var(--copper); }}
    .small {{ color: rgba(24,33,31,.72); font-size: .93rem; }}
    .builder-grid {{ display: grid; grid-template-columns: minmax(280px, .95fr) minmax(0, 1.05fr); gap: 18px; align-items: start; }}
    .field {{ display: grid; gap: 7px; margin-bottom: 14px; }}
    label {{ font-weight: 900; }}
    input, textarea, select {{
      width: 100%;
      border: 1px solid rgba(24,33,31,.22);
      border-radius: 14px;
      background: rgba(255,255,255,.54);
      color: var(--ink);
      font: inherit;
      padding: 11px 12px;
    }}
    textarea {{ min-height: 86px; resize: vertical; }}
    .score-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; }}
    .score {{ border: 1px solid rgba(24,33,31,.16); border-radius: 18px; padding: 14px; background: rgba(255,255,255,.34); }}
    .score strong {{ display: block; font-size: 1.45rem; }}
    .ok {{ color: var(--moss); font-weight: 900; }}
    .risk {{ color: var(--copper); font-weight: 900; }}
    @media (max-width: 780px) {{
      .split {{ grid-template-columns: 1fr; }}
      .builder-grid {{ grid-template-columns: 1fr; }}
      .nav {{ align-items: flex-start; flex-direction: column; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <nav class="nav">
      <div class="brand">Cambrian Hiring Desk</div>
      <div><a href="{nav_prefix}index.html">Home</a> · <a href="{nav_prefix}studio/index.html">Studio</a> · <a href="{nav_prefix}packs/index.html">Packs</a></div>
    </nav>
    {body}
  </main>
</body>
</html>
"""


def _landing_html(catalog: dict[str, Any]) -> str:
    """landing page HTML."""
    pack_count = len(catalog["packs"])
    body = f"""
    <section class="hero">
      <div class="eyebrow">AI Worker Installer · Local-first runtime</div>
      <h1>Install AI workers into the AI you already use.</h1>
      <p class="lead">이미 쓰는 AI에 검증된 AI 일꾼을 설치하세요. Cambrian lets you install worker packs into your local project, then keeps the actual install, validation, and proof inside your local Cambrian runtime.</p>
      <div class="cta-row">
        <a class="button" href="studio/index.html">Open Cambrian Studio</a>
        <a class="button" href="packs/index.html">Browse Packs</a>
        <a class="button alt" href="packs/auth-bug-core.html">Start with Auth Bug Core</a>
        <a class="button alt" href="assets/catalog.json">View catalog JSON</a>
        <a class="button alt" href="../docs/launch/DEMO_SCRIPT.md">View product walkthrough</a>
        <a class="button alt" href="../docs/launch/LAUNCH_GOLDEN_PATH.md">Run reproducible product run</a>
      </div>
    </section>
    <section class="grid section">
      <article class="panel">
        <h2>Hiring desk, not runtime.</h2>
        <p>The web page is the hiring desk.</p>
        <p>The web catalog is the hiring desk. Your local Cambrian runtime does the actual install, job handoff, validation, and proof.</p>
        <p>This page does not execute code or mutate `.cambrian/` state.</p>
        <p>웹은 고용/선택 화면이고, 실제 설치·검증·진화는 로컬 Cambrian runtime에서 수행됩니다.</p>
      </article>
      <article class="panel">
        <h2>Start with Auth Bug Core</h2>
        <p>The MVP starts with <strong>auth-bug-core</strong>, Cambrian's strongest lane pack for Python + pytest + narrow auth/login bug fixes.</p>
        <pre>cambrian pack show auth-bug-core
cambrian install pack auth-bug-core</pre>
      </article>
    </section>
    """
    return _layout("AI Worker Installer", body)


def _studio_html() -> str:
    """Cambrian Studio builder page HTML."""
    body = """
    <section class="hero">
      <div class="eyebrow">Cambrian Studio · Agent Contract Builder</div>
      <h1>Build an AI agent contract.</h1>
      <p class="lead">비개발자도 문서 정리 에이전트를 만들고, Cambrian Runtime에 설치할 수 있는 pack manifest로 내보낼 수 있습니다. Studio는 클라우드 실행기가 아니라 로컬 Cambrian Runtime을 조종하는 제작 화면입니다.</p>
      <div class="cta-row">
        <a class="button alt" href="../packs/index.html">Browse existing packs</a>
        <a class="button alt" href="../assets/catalog.json">Inspect catalog JSON</a>
      </div>
    </section>
    <section class="builder-grid section">
      <form class="panel" id="studio-form">
        <h2>Document agent</h2>
        <div class="field">
          <label for="agent-name">에이전트 이름</label>
          <input id="agent-name" value="Document Organizer Agent" />
        </div>
        <div class="field">
          <label for="author">제작자</label>
          <input id="author" value="local-author" />
        </div>
        <div class="field">
          <label for="mission">맡길 일</label>
          <textarea id="mission">문서를 주제별로 분류하고, 중복 파일 후보와 정리 제안을 만든다.</textarea>
        </div>
        <div class="field">
          <label for="doc-types">문서 유형</label>
          <input id="doc-types" value="pdf, docx, txt, markdown" />
        </div>
        <div class="field">
          <label for="output-format">결과물 형식</label>
          <select id="output-format">
            <option value="markdown_report">Markdown report</option>
            <option value="csv_index">CSV index</option>
            <option value="checklist">Checklist</option>
          </select>
        </div>
        <div class="field">
          <label for="forbidden">금지 행동</label>
          <textarea id="forbidden">원본 파일 삭제
외부 서비스로 문서 업로드
사용자 승인 없는 파일 이동</textarea>
        </div>
        <div class="field">
          <label for="approval">승인 필요한 행동</label>
          <textarea id="approval">파일 이름 변경
폴더 이동
중복 후보 격리</textarea>
        </div>
        <div class="field">
          <label for="validation">검증 기준</label>
          <textarea id="validation">원본 파일을 변경하지 않았는지 확인
분류 기준과 예외 파일 목록을 결과에 포함
중복 후보는 근거와 함께 표시</textarea>
        </div>
        <div class="field">
          <label for="known-limits">Known limits</label>
          <textarea id="known-limits">암호화된 문서는 사용자가 직접 해제해야 한다.
OCR이 필요한 스캔 PDF는 별도 도구가 필요할 수 있다.</textarea>
        </div>
        <div class="cta-row">
          <button class="button" id="download-pack" type="button">Download pack</button>
          <button class="button alt" id="reset-builder" type="reset">Reset</button>
        </div>
      </form>
      <aside class="panel">
        <h2>Preflight proof</h2>
        <p class="small">실제 성능 proof는 로컬 job 실행 후에만 생성됩니다. 이 리포트는 설치 전 계약 완성도와 위험도를 보여줍니다.</p>
        <div class="score-row">
          <div class="score"><span>완성도</span><strong id="completion-score">0%</strong></div>
          <div class="score"><span>위험도</span><strong id="risk-level">unknown</strong></div>
          <div class="score"><span>Proof</span><strong>preflight_only</strong></div>
        </div>
        <h3>검증 결과</h3>
        <ul id="preflight-list"></ul>
        <h3>Install command</h3>
        <pre id="install-command"></pre>
        <h3>Start command</h3>
        <pre id="start-command"></pre>
        <h3>Pack preview</h3>
        <pre id="yaml-preview"></pre>
      </aside>
    </section>
    <section class="grid section">
      <article class="panel">
        <h2>Runtime boundary</h2>
        <p>Studio는 에이전트 계약과 pack manifest를 만듭니다. 실제 설치, job start, validation, proof, evolution은 로컬 Cambrian Runtime이 담당합니다.</p>
      </article>
      <article class="panel warning">
        <h2>No fake proof</h2>
        <p>이 화면은 실행 전 성공률을 주장하지 않습니다. 성공률, 사용자 수정률, 검증 통과율은 로컬 evidence가 생긴 뒤에만 표시합니다.</p>
      </article>
    </section>
    <script>
      const fields = [
        "agent-name",
        "author",
        "mission",
        "doc-types",
        "output-format",
        "forbidden",
        "approval",
        "validation",
        "known-limits"
      ];

      function text(id) {
        return document.getElementById(id).value.trim();
      }

      function slug(value) {
        const safe = value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
        return safe || "document-organizer-agent";
      }

      function items(value) {
        return value.split(/[\\n,]/).map((item) => item.trim()).filter(Boolean);
      }

      function q(value) {
        return `"${String(value).replace(/\\\\/g, "\\\\\\\\").replace(/"/g, "\\\\\\"").replace(/\\n/g, " ")}"`;
      }

      function listBlock(values, indent) {
        if (!values.length) {
          return `${" ".repeat(indent)}[]`;
        }
        return values.map((value) => `${" ".repeat(indent)}- ${q(value)}`).join("\\n");
      }

      function buildYaml() {
        const name = text("agent-name") || "Document Organizer Agent";
        const packId = slug(name);
        const author = text("author") || "local-author";
        const mission = text("mission") || "문서를 정리한다.";
        const docTypes = items(text("doc-types"));
        const forbidden = items(text("forbidden"));
        const approval = items(text("approval"));
        const validation = items(text("validation"));
        const limits = items(text("known-limits"));
        const format = text("output-format") || "markdown_report";

        return `schema_version: "1.0"
pack_id: ${packId}
pack_name: ${q(name)}
pack_kind: agent
version: "0.1.0"

description: >
  ${mission}

source:
  kind: cambrian_studio
  registry: local
  author: ${q(author)}
  origin_ref: web/studio
  provenance: studio_generated
  public_visibility: private
  signature_status: unsigned_local

compatibility:
  stacks:
    - local_files
  request_classes:
    - document_organization
  domains:
    - documents
    - knowledge_management

workers:
  - id: ${packId}
    name: ${q(name)}
    capabilities:
      - document classification
      - duplicate candidate detection
      - organization report drafting
    tags:
      - documents
      - organizer
      - studio_generated

teams:
  - name: ${packId}-team
    lead_agent_id: ${packId}
    supporting_agent_ids: []
    tags:
      - documents
      - organizer

templates:
  - name: ${packId}-template
    template_kind: agent_contract
    description: ${q(mission)}
    tags:
      - documents
      - organizer
      - studio_generated
    project_defaults:
      stack:
        - local_files
      primary_use_cases:
        - document_organization
      output_format: ${q(format)}
      document_types:
${listBlock(docTypes, 8)}
    safety_defaults:
      explicit_adoption_only: true
      preserve_source_artifacts: true
      no_external_upload: true
      approval_required_actions:
${listBlock(approval, 8)}
      forbidden_actions:
${listBlock(forbidden, 8)}
    policy_defaults:
      read_only_first: true
      draft_outputs_only: true
      require_user_approval_for_file_moves: true
    validation_defaults:
      proof_status: preflight_only
      runtime_evidence: none
      success_metrics_available: false
      validation_criteria:
${listBlock(validation, 8)}
    evolution_defaults:
      track_signals:
        - user_correction_required
        - validation_gap_found
        - forbidden_action_blocked
        - organization_rule_changed
    fit_hints:
      - strongest for local document organization and draft reports

benchmarks:
  - name: ${packId}-preflight-workset
    description: Preflight checklist for document organization agents
    tags:
      - documents
      - preflight

proof_seed:
  status: preflight_only
  runtime_evidence: none
  success_rate: null
  human_intervention_rate: null
  validation_pass_rate: null
  notes:
    - Actual performance proof is generated only after local Cambrian runtime jobs.

marketplace:
  license: personal_local
  checksum: pending_after_export
  signature: unsigned_local
  evolution_lineage: []
  known_limits:
${listBlock(limits, 4)}

install:
  install_as_library: true
  auto_apply: false
  auto_bootstrap: false
  auto_promote: false
  auto_canary: false

warnings:
  - Generated by Cambrian Studio preflight. Local runtime evidence is required before public proof claims.
  - Do not expose private source documents or secrets in public proof exports.
`;
      }

      function preflight() {
        const checks = [];
        const required = ["agent-name", "mission", "forbidden", "approval", "validation"];
        const filled = required.filter((id) => text(id).length > 0).length;
        const completion = Math.round((filled / required.length) * 100);
        const forbidden = items(text("forbidden")).join(" ").toLowerCase();
        const approval = items(text("approval")).join(" ").toLowerCase();
        const riskyWords = ["delete", "삭제", "send", "발송", "upload", "업로드", "move", "이동"];
        const riskHits = riskyWords.filter((word) => `${forbidden} ${approval}`.includes(word)).length;
        const risk = riskHits >= 4 ? "high" : riskHits >= 2 ? "medium" : "low";

        checks.push(text("mission") ? "역할과 목표가 정의됨" : "역할과 목표 확인 필요");
        checks.push(text("validation") ? "검증 기준이 존재함" : "검증 기준 확인 필요");
        checks.push(text("forbidden") ? "금지 행동이 명시됨" : "금지 행동 확인 필요");
        checks.push(text("approval") ? "승인 필요 행동이 명시됨" : "승인 필요 행동 확인 필요");
        checks.push("실제 성능 proof는 아직 없음");

        document.getElementById("completion-score").textContent = `${completion}%`;
        document.getElementById("risk-level").textContent = risk;
        document.getElementById("risk-level").className = risk === "low" ? "ok" : "risk";
        document.getElementById("preflight-list").innerHTML = checks.map((item) => `<li>${item}</li>`).join("");
        const fileName = `${slug(text("agent-name")) || "document-organizer-agent"}.cambrian-pack.yaml`;
        const packId = slug(text("agent-name")) || "document-organizer-agent";
        document.getElementById("install-command").textContent = `cambrian install manifest ./${fileName}`;
        document.getElementById("start-command").textContent = `cambrian job start --pack ${packId} "문서 폴더를 주제별로 정리해줘"`;
        document.getElementById("yaml-preview").textContent = buildYaml();
      }

      function downloadPack() {
        const fileName = `${slug(text("agent-name")) || "document-organizer-agent"}.cambrian-pack.yaml`;
        const blob = new Blob([buildYaml()], { type: "text/yaml;charset=utf-8" });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = fileName;
        link.click();
        URL.revokeObjectURL(link.href);
      }

      fields.forEach((id) => document.getElementById(id).addEventListener("input", preflight));
      document.getElementById("output-format").addEventListener("change", preflight);
      document.getElementById("download-pack").addEventListener("click", downloadPack);
      document.getElementById("studio-form").addEventListener("reset", () => setTimeout(preflight, 0));
      preflight();
    </script>
    """
    return _layout("Cambrian Studio", body, nav_prefix="../")


def _packs_index_html(catalog: dict[str, Any]) -> str:
    """pack catalog page HTML."""
    cards = []
    for pack in catalog["packs"]:
        cards.append(
            f"""
      <article class="card">
        <div class="eyebrow">{_e(pack.get("pack_kind"))} pack · {_e(pack.get("maturity"))}</div>
        <h2>{_e(pack.get("pack_name"))}</h2>
        <p>{_e(pack.get("description"))}</p>
        <div class="badge-row">{_badges(pack.get("tags", []))}</div>
        <p><strong>Best for:</strong> Python + pytest + auth/login bug fixes</p>
        <pre>{_e(pack.get("install_command"))}</pre>
        <a class="button" href="{_e(pack.get("detail_path"))}">Inspect pack</a>
      </article>
            """
        )
    body = f"""
    <section class="hero">
      <div class="eyebrow">Pack catalog</div>
      <h1>Choose an AI work crew.</h1>
      <p class="lead">Browse local seed packs, inspect what they include, then run the install command in your project. This page does not execute code or mutate `.cambrian/` state.</p>
    </section>
    <section class="grid section">
      {''.join(cards)}
    </section>
    """
    return _layout("Packs", body, nav_prefix="../")


def _pack_detail_html(record: dict[str, Any], catalog: dict[str, Any]) -> str:
    """pack detail HTML."""
    entry = record["entry"]
    manifest = record["manifest"]
    pack_id = str(entry.get("pack_id"))
    asset_name = record["asset_name"]
    includes = {
        "Workers": _names(manifest.get("workers"), "id"),
        "Team": _names(manifest.get("teams"), "name"),
        "Template": _names(manifest.get("templates"), "name"),
        "Benchmark": _names(manifest.get("benchmarks"), "name"),
    }
    include_html = "".join(
        f"<h3>{_e(kind)}</h3><ul>{''.join(f'<li>{_e(item)}</li>' for item in items)}</ul>"
        for kind, items in includes.items()
    )
    warnings = entry.get("warnings") or manifest.get("warnings") or []
    known_limits = entry.get("known_limits") or warnings or []
    proof_status = entry.get("proof_status") or "Seed pack. Local proof required."
    proof_refs = entry.get("proof_refs") or []
    qualification_refs = entry.get("qualification_refs") or []
    canary_refs = entry.get("canary_refs") or []
    asset_pack = _asset_pack(catalog, pack_id)
    public_proof = asset_pack.get("proof") if isinstance(asset_pack.get("proof"), dict) else None
    public_proof_html = _public_proof_html(public_proof)
    proof_lines = [f"Proof status: {proof_status}"]
    if proof_refs:
        proof_lines.append(f"Proof refs: {', '.join(str(item) for item in proof_refs)}")
    if qualification_refs:
        proof_lines.append(f"Qualification refs: {', '.join(str(item) for item in qualification_refs)}")
    if canary_refs:
        proof_lines.append(f"Canary refs: {', '.join(str(item) for item in canary_refs)}")
    body = f"""
    <section class="hero">
      <div class="eyebrow">Lane Pack · {_e(entry.get("maturity"))}</div>
      <h1>{_e(entry.get("pack_name"))}</h1>
      <p class="lead">Best for <strong>Python + pytest + narrow auth/login bug fixes</strong>. This is Cambrian's first representative worker/lane pack.</p>
      <div class="badge-row">{_badges(entry.get("tags", []))}</div>
    </section>
    <section class="split section">
      <article class="panel">
        <h2>Includes</h2>
        {include_html}
      </article>
      <aside class="panel">
        <h2>Install locally</h2>
        <p>This page does not install anything by itself.</p>
        <p>This web page does not install the pack directly. Run the install command in your local project.</p>
        <pre>cambrian install pack {pack_id}
cambrian pack activate {pack_id}
cambrian pack start "로그인 에러 수정해"
cambrian install doctor</pre>
        <p class="small">Manifest fallback:</p>
        <pre>cambrian install manifest ./packs/{_e(asset_name)}</pre>
        <p class="small">Trust: {_e(entry.get("trust_level") or "unknown")}</p>
        <p class="small">SHA-256: {_e(entry.get("manifest_sha256") or "not declared")}</p>
        <pre>cambrian pack verify {pack_id}
cambrian install verify {pack_id}</pre>
        <p><a class="button alt" href="../assets/{_e(asset_name)}" download>Download manifest</a></p>
      </aside>
    </section>
    <section class="grid section">
      <article class="panel warning">
        <h2>Known limits</h2>
        <ul>{''.join(f'<li>{_e(item)}</li>' for item in known_limits)}</ul>
      </article>
      <article class="panel">
        <h2>Proof status</h2>
        <p><strong>{_e(proof_status)}</strong></p>
        {public_proof_html}
        <ul>{''.join(f'<li>{_e(item)}</li>' for item in proof_lines[1:])}</ul>
        <p>Generate local proof after real usage.</p>
        <p>Generate or refresh proof inside your project after install:</p>
        <pre>cambrian pack proof {pack_id}</pre>
        <p class="small">This static page does not claim public outcome metrics.</p>
        <p class="small">No public validated proposal rate is claimed on this static page.</p>
      </article>
      <article class="panel">
        <h2>Runtime boundary</h2>
        <p>The web page is the hiring desk.</p>
        <p>The web catalog is the hiring desk. Your local Cambrian runtime does the actual install, job handoff, validation, and proof.</p>
        <p>This page does not execute code or mutate `.cambrian/` state.</p>
        <p>웹은 고용/선택 화면이고, 실제 설치·검증·진화는 로컬 Cambrian runtime에서 수행됩니다.</p>
      </article>
    </section>
    """
    return _layout(f"{entry.get('pack_name')}", body, nav_prefix="../")


def _asset_pack(catalog: dict[str, Any], pack_id: str) -> dict[str, Any]:
    """catalog asset에서 pack payload를 찾는다."""
    for pack in catalog.get("packs", []):
        if isinstance(pack, dict) and str(pack.get("pack_id") or "") == pack_id:
            return pack
    return {}


def _public_proof_html(proof: dict[str, Any] | None) -> str:
    """public proof export HTML 조각을 만든다."""
    if not proof:
        return ""
    metrics = proof.get("metrics") if isinstance(proof.get("metrics"), dict) else {}
    metric_lines = "".join(f"<li>{_e(key)}: {_e(value)}</li>" for key, value in metrics.items() if value is not None)
    caveats = proof.get("caveats") if isinstance(proof.get("caveats"), list) else []
    caveat_lines = "".join(f"<li>{_e(item)}</li>" for item in caveats)
    return f"""
        <h3>Local proof export:</h3>
        <p><strong>{_e(proof.get("proof_status"))}</strong> 쨌 verdict: {_e(proof.get("reputation_verdict"))}</p>
        <p class="small">{_e(proof.get("web_summary") or "Local public proof export. Aggregate metrics only.")}</p>
        <ul>{metric_lines}</ul>
        <p class="small">Caveat: Local evidence. Not uploaded automatically.</p>
        <ul>{caveat_lines}</ul>
    """


def _badges(values: list[Any]) -> str:
    """badge HTML을 만든다."""
    return "".join(f'<span class="badge">{_e(value)}</span>' for value in values)


def _e(value: Any) -> str:
    """HTML escape."""
    return html.escape(str(value if value is not None else ""))


if __name__ == "__main__":
    main()
