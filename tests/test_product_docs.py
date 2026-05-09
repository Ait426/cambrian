from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_DOCS = ROOT / "docs" / "product"

REQUIRED_PRODUCT_DOCS = [
    "00_INDEX.md",
    "01_PRODUCT_THESIS.md",
    "02_PRODUCT_DEFINITION.md",
    "03_WIN_LANE.md",
    "04_SYSTEM_ARCHITECTURE.md",
    "05_RUNTIME_STATE_MODEL.md",
    "06_PACKS_AND_INSTALL.md",
    "07_EXECUTION_LOOPS.md",
    "08_METRICS_AND_PROOF.md",
    "09_WEB_CONTROL_PLANE.md",
    "10_GLOSSARY.md",
    "11_ARCHITECTURE_INVENTORY.md",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _combined_product_docs() -> str:
    return "\n".join(_read(PRODUCT_DOCS / name) for name in REQUIRED_PRODUCT_DOCS)


def test_task_132_product_docs_exist() -> None:
    for name in REQUIRED_PRODUCT_DOCS:
        assert (PRODUCT_DOCS / name).exists(), f"docs/product/{name} 문서가 없습니다."


def test_task_132_product_doctrine_terms_are_fixed() -> None:
    combined = _combined_product_docs()

    for phrase in [
        "AI Worker Installer",
        "AI 인력 설치기",
        "AI 작업반 설치 시스템",
        "local-first",
        "evidence-based",
        "evidence-based harness engineering runtime",
        "Web Control Plane",
        "Local Cambrian Runtime",
        "validated_proposal_rate",
    ]:
        assert phrase in combined


def test_task_132_strongest_lane_and_pack_taxonomy_are_fixed() -> None:
    combined = _combined_product_docs()

    assert "Python + pytest + narrow auth/login bug fix" in combined
    assert "Python + pytest + auth/login narrow bug fix" in combined

    for phrase in [
        "auth-bug-team",
        "auth-bug-template",
        "auth-bug-workset",
        "test-first",
        "narrow-scope",
        "review-support",
        "outside-lane",
        "worker pack",
        "team pack",
        "template pack",
        "lane pack",
        "auth-bug-core",
    ]:
        assert phrase in combined


def test_task_132_architecture_and_web_runtime_boundary_are_fixed() -> None:
    architecture = _read(PRODUCT_DOCS / "04_SYSTEM_ARCHITECTURE.md")
    web = _read(PRODUCT_DOCS / "09_WEB_CONTROL_PLANE.md")
    readme = _read(ROOT / "README.md")
    commands = _read(ROOT / "docs" / "COMMANDS.md")

    for phrase in [
        "Web Control Plane",
        "Local Cambrian Runtime",
        "AI Bridge",
        "Evidence & Proof",
        "Evolution & Governance",
    ]:
        assert phrase in architecture

    for text in [web, readme, commands]:
        assert "control plane" in text
        assert "runtime" in text

    assert "source code execution" in web
    assert "cloud patch/apply" in web


def test_task_132_state_model_and_metrics_are_fixed() -> None:
    state_model = _read(PRODUCT_DOCS / "05_RUNTIME_STATE_MODEL.md")
    metrics = _read(PRODUCT_DOCS / "08_METRICS_AND_PROOF.md")

    for phrase in [
        "source-of-truth",
        "derived artifact",
        "Current runtime state",
        "Future default state",
        "current runtime과 future default를 분리한다",
    ]:
        assert phrase in state_model

    for metric in [
        "validated_proposal_rate",
        "adoption_rate",
        "regression_free_apply_rate",
        "median_time_to_validated_proposal",
        "human_intervention_rate",
        "validation_autonomy_rate",
        "lead_agent_hit_rate",
        "team_template_recommendation_hit_rate",
        "reuse_lift",
        "repeat_task_improvement_rate",
    ]:
        assert metric in metrics

    lower_metrics = metrics.lower()
    for proof_term in [
        "weekly metrics",
        "benchmark",
        "workset",
        "baseline compare",
        "replay",
        "autonomy board",
        "bottleneck",
        "proof pack",
        "canary ledger",
        "canary outcome attribution",
        "qualification",
        "challenge matrix",
    ]:
        assert proof_term in lower_metrics


def test_task_132_existing_docs_are_aligned_to_product_doctrine() -> None:
    for relative_path in [
        "README.md",
        "docs/FIRST_RUN_DEMO.md",
        "docs/ALPHA_INSTALL.md",
        "docs/COMMANDS.md",
    ]:
        text = _read(ROOT / relative_path)
        assert "project-specific harness" in text or "custom AI harness" in text
        assert "source" in text
        assert "explicit apply" in text or "explicit apply/adoption" in text


def test_task_133_architecture_inventory_classifies_code_to_doctrine_alignment() -> None:
    inventory = _read(PRODUCT_DOCS / "11_ARCHITECTURE_INVENTORY.md")

    for phrase in [
        "Architecture Inventory",
        "Layer Inventory",
        "Command Inventory",
        "Artifact Inventory",
        "Doctrine Consistency",
        "Critical Architecture Gaps",
        "Recommended Next Tasks",
        "implemented",
        "partial",
        "planned",
        "drift",
        "Web Control Plane",
        "Local Cambrian Runtime",
        "AI Bridge",
        "Evidence & Proof",
        "Evolution & Governance",
    ]:
        assert phrase in inventory


def test_task_134_pack_install_docs_match_local_manifest_v1() -> None:
    packs = _read(PRODUCT_DOCS / "06_PACKS_AND_INSTALL.md")
    inventory = _read(PRODUCT_DOCS / "11_ARCHITECTURE_INVENTORY.md")

    implemented_manifest_command = "cambrian install manifest ./packs/auth-bug-core.cambrian-pack.yaml"
    assert implemented_manifest_command in packs

    for phrase in [
        "cambrian install list",
        "cambrian install show",
        "cambrian install doctor",
        "local manifest",
    ]:
        assert phrase in packs

    assert "| `cambrian install manifest` | implemented |" in inventory


def test_task_135_pack_catalog_docs_match_local_catalog_v1() -> None:
    packs = _read(PRODUCT_DOCS / "06_PACKS_AND_INSTALL.md")
    loops = _read(PRODUCT_DOCS / "07_EXECUTION_LOOPS.md")
    web = _read(PRODUCT_DOCS / "09_WEB_CONTROL_PLANE.md")
    inventory = _read(PRODUCT_DOCS / "11_ARCHITECTURE_INVENTORY.md")
    readme = _read(ROOT / "README.md")

    for text in [packs, loops, readme]:
        assert "cambrian pack show auth-bug-core" in text
        assert "cambrian install pack auth-bug-core" in text

    for phrase in [
        "cambrian pack list",
        "cambrian pack show <pack-id-or-name>",
        "cambrian pack recommend",
        "local catalog",
    ]:
        assert phrase in packs

    assert "cambrian registry add local-web web/assets/catalog.json" in packs
    assert "cambrian install pack auth-bug-core --registry local-web" in web
    assert "| `cambrian install pack` | implemented |" in inventory


def test_task_136_web_catalog_docs_match_static_hiring_desk_v1() -> None:
    packs = _read(PRODUCT_DOCS / "06_PACKS_AND_INSTALL.md")
    web = _read(PRODUCT_DOCS / "09_WEB_CONTROL_PLANE.md")
    inventory = _read(PRODUCT_DOCS / "11_ARCHITECTURE_INVENTORY.md")
    readme = _read(ROOT / "README.md")

    for phrase in [
        "web/",
        "web/assets/catalog.json",
        "web/assets/auth-bug-core.cambrian-pack.yaml",
        "python tools/generate_web_catalog.py",
        "packs/catalog.yaml",
    ]:
        assert phrase in web

    assert "static Web Pack Catalog MVP" in packs
    assert "Web Pack Catalog MVP" in readme
    assert "hiring desk" in readme
    assert "| Web Control Plane | partial |" in inventory
    assert "static web hiring desk" in inventory


def test_task_137_pack_lifecycle_docs_match_local_lifecycle_v1() -> None:
    packs = _read(PRODUCT_DOCS / "06_PACKS_AND_INSTALL.md")
    loops = _read(PRODUCT_DOCS / "07_EXECUTION_LOOPS.md")
    web = _read(PRODUCT_DOCS / "09_WEB_CONTROL_PLANE.md")
    inventory = _read(PRODUCT_DOCS / "11_ARCHITECTURE_INVENTORY.md")
    readme = _read(ROOT / "README.md")

    for text in [packs, loops, readme]:
        assert "cambrian install diff auth-bug-core" in text
        assert "cambrian install update auth-bug-core" in text
        assert "cambrian uninstall pack auth-bug-core" in text

    for phrase in [
        "preview-first",
        "--confirm",
        "local derivatives",
        "historical proof",
    ]:
        assert phrase in packs or phrase in loops or phrase in web

    for phrase in [
        "| `cambrian install diff` | implemented |",
        "| `cambrian install update` | implemented |",
        "| `cambrian uninstall pack` | implemented |",
        "local pack lifecycle",
    ]:
        assert phrase in inventory

    assert "remote/web registry update is still planned" in web


def test_task_138_pack_trust_docs_match_local_integrity_v1() -> None:
    packs = _read(PRODUCT_DOCS / "06_PACKS_AND_INSTALL.md")
    web = _read(PRODUCT_DOCS / "09_WEB_CONTROL_PLANE.md")
    inventory = _read(PRODUCT_DOCS / "11_ARCHITECTURE_INVENTORY.md")
    readme = _read(ROOT / "README.md")

    for text in [packs, readme]:
        assert "cambrian pack verify auth-bug-core" in text
        assert "cambrian install verify" in text

    for phrase in [
        "SHA-256",
        ".cambrian/install/pack_lock.yaml",
        "--require-trusted",
        "cryptographic signing",
        "planned future",
    ]:
        assert phrase in packs or phrase in web or phrase in readme

    for phrase in [
        "| `cambrian pack verify` | implemented |",
        "| `cambrian install verify` | implemented |",
        "local pack trust/verify",
        "pack_lock.yaml",
    ]:
        assert phrase in inventory


def test_task_139_pack_authoring_docs_match_local_publish_v1() -> None:
    packs = _read(PRODUCT_DOCS / "06_PACKS_AND_INSTALL.md")
    loops = _read(PRODUCT_DOCS / "07_EXECUTION_LOOPS.md")
    web = _read(PRODUCT_DOCS / "09_WEB_CONTROL_PLANE.md")
    inventory = _read(PRODUCT_DOCS / "11_ARCHITECTURE_INVENTORY.md")
    readme = _read(ROOT / "README.md")

    for text in [packs, loops, readme]:
        assert "cambrian pack draft auth-bug-core-local" in text
        assert "cambrian pack build" in text
        assert "cambrian pack publish-local" in text

    for phrase in [
        ".cambrian/packs/drafts",
        ".cambrian/packs/builds",
        ".cambrian/packs/publishes",
        "packs/generated",
        "packs/catalog.yaml",
        "remote/web publish remains future/planned",
    ]:
        assert phrase in packs or phrase in loops or phrase in web or phrase in readme

    for phrase in [
        "| `cambrian pack draft` | implemented |",
        "| `cambrian pack validate` | implemented |",
        "| `cambrian pack build` | implemented |",
        "| `cambrian pack publish-local` | implemented |",
        "project_pack_authoring.py",
    ]:
        assert phrase in inventory


def test_task_140_pack_release_docs_match_proof_backed_web_sync_v1() -> None:
    packs = _read(PRODUCT_DOCS / "06_PACKS_AND_INSTALL.md")
    metrics = _read(PRODUCT_DOCS / "08_METRICS_AND_PROOF.md")
    web = _read(PRODUCT_DOCS / "09_WEB_CONTROL_PLANE.md")
    inventory = _read(PRODUCT_DOCS / "11_ARCHITECTURE_INVENTORY.md")
    readme = _read(ROOT / "README.md")

    for text in [packs, web, readme]:
        assert "cambrian pack release-check" in text
        assert "cambrian pack web-sync" in text
        assert "--require-proof" in text

    for phrase in [
        "maturity",
        "proof_status",
        "known_limits",
        "local proof required",
        "fake proof",
    ]:
        assert phrase in packs or phrase in metrics or phrase in web

    for phrase in [
        "| `cambrian pack release-check` | implemented |",
        "| `cambrian pack web-sync` | implemented |",
        "project_pack_release.py",
        ".cambrian/packs/releases/",
        ".cambrian/packs/web_sync/",
    ]:
        assert phrase in inventory


def test_task_141_registry_docs_match_static_pull_v1() -> None:
    packs = _read(PRODUCT_DOCS / "06_PACKS_AND_INSTALL.md")
    web = _read(PRODUCT_DOCS / "09_WEB_CONTROL_PLANE.md")
    inventory = _read(PRODUCT_DOCS / "11_ARCHITECTURE_INVENTORY.md")
    readme = _read(ROOT / "README.md")

    for text in [packs, web, readme]:
        assert "cambrian registry add local-web web/assets/catalog.json" in text
        assert "cambrian registry sync local-web" in text
        assert "cambrian pack search auth --registry local-web" in text
        assert "cambrian install pack auth-bug-core --registry local-web" in text

    for phrase in [
        "static pull",
        "manifest digest",
        "no login",
        "no payment",
        "no cloud execution",
        "source upload",
    ]:
        assert phrase in packs or phrase in web or phrase in readme

    for phrase in [
        "| `cambrian registry add/list/sync` | implemented |",
        "| `cambrian pack search` | implemented |",
        "| `cambrian pack show --registry` | implemented |",
        "| `cambrian install pack --registry` | implemented |",
        "project_pack_registry.py",
        ".cambrian/registries/",
    ]:
        assert phrase in inventory


def test_task_142_pack_dependency_docs_match_resolver_v1() -> None:
    packs = _read(PRODUCT_DOCS / "06_PACKS_AND_INSTALL.md")
    web = _read(PRODUCT_DOCS / "09_WEB_CONTROL_PLANE.md")
    inventory = _read(PRODUCT_DOCS / "11_ARCHITECTURE_INVENTORY.md")
    readme = _read(ROOT / "README.md")

    for text in [packs, web, readme]:
        assert "cambrian install plan cambrian/auth-bug-core@0.2.0 --registry official" in text
        assert "cambrian install pack cambrian/auth-bug-core@0.2.0 --registry official --confirm-deps" in text

    for phrase in [
        "namespace",
        "version",
        "dependencies",
        "pack_lock.yaml",
        ".cambrian/install/graphs/",
        "complex npm-style semver",
        "dependency auto-update cascade",
    ]:
        assert phrase in packs or phrase in web or phrase in readme or phrase in inventory

    for phrase in [
        "| `cambrian install plan` | implemented |",
        "| `cambrian install pack --confirm-deps` | implemented |",
        "project_pack_dependencies.py",
        "namespace / version pinning / dependency resolver",
    ]:
        assert phrase in inventory


def test_task_143_pack_activation_docs_match_first_job_v1() -> None:
    packs = _read(PRODUCT_DOCS / "06_PACKS_AND_INSTALL.md")
    loops = _read(PRODUCT_DOCS / "07_EXECUTION_LOOPS.md")
    readme = _read(ROOT / "README.md")

    for text in [packs, loops, readme]:
        assert "cambrian pack activate auth-bug-core" in text
        assert "cambrian pack next" in text

    for phrase in [
        "pack activate",
        "source code",
        "template apply",
        "bootstrap",
        "soft work context",
        "first job",
    ]:
        assert phrase in packs or phrase in loops or phrase in readme
