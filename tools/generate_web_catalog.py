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
    assets_dir.mkdir(parents=True, exist_ok=True)
    packs_dir.mkdir(parents=True, exist_ok=True)

    catalog_asset = _catalog_asset(catalog_path, catalog, manifest_records)
    _write_text(assets_dir / "catalog.json", json.dumps(catalog_asset, indent=2, ensure_ascii=False) + "\n")
    for record in manifest_records:
        shutil.copyfile(record["manifest_path"], assets_dir / record["asset_name"])

    _write_text(out_dir / "index.html", _landing_html(catalog_asset))
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
    path.write_text(content, encoding="utf-8", newline="\n")


def _layout(title: str, body: str) -> str:
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
    @media (max-width: 780px) {{
      .split {{ grid-template-columns: 1fr; }}
      .nav {{ align-items: flex-start; flex-direction: column; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <nav class="nav">
      <div class="brand">Cambrian Hiring Desk</div>
      <div><a href="{_nav_prefix(title)}index.html">Home</a> · <a href="{_nav_prefix(title)}packs/index.html">Packs</a></div>
    </nav>
    {body}
  </main>
</body>
</html>
"""


def _nav_prefix(title: str) -> str:
    """detail page에서 상대 링크 prefix를 맞춘다."""
    return "../" if title.startswith("Auth Bug Core") else ""


def _landing_html(catalog: dict[str, Any]) -> str:
    """landing page HTML."""
    pack_count = len(catalog["packs"])
    body = f"""
    <section class="hero">
      <div class="eyebrow">AI Worker Installer · Local-first runtime</div>
      <h1>Install AI workers into the AI you already use.</h1>
      <p class="lead">이미 쓰는 AI에 검증된 AI 일꾼을 설치하세요. Cambrian lets you install worker packs into your local project, then keeps the actual install, validation, and proof inside your local Cambrian runtime.</p>
      <div class="cta-row">
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
    return _layout("Packs", body)


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
    return _layout(f"{entry.get('pack_name')}", body)


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
