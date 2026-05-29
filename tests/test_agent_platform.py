import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
PLATFORM = WEB / "platform" / "index.html"
RUNNER = WEB / "runner" / "index.html"
PLATFORM_DOC = ROOT / "docs" / "platform" / "00_AGENT_PLATFORM_FOUNDATION.md"
TEN_YEAR_DOC = ROOT / "docs" / "product" / "42_TEN_YEAR_ARCHITECTURE.md"
CONSTITUTION_DOC = ROOT / "docs" / "product" / "14_PRODUCT_CONSTITUTION.md"
AGENT_CONTRACT_SCHEMA = ROOT / "schemas" / "agent_contract_v0_1.schema.json"
AGENT_PACK_BUNDLE_SCHEMA = ROOT / "schemas" / "agent_pack_bundle_v0_1.schema.json"
SAMPLE_PACK = WEB / "assets" / "document-organizer.agent-pack.json"
BROWSER_FLOW_WRAPPER = ROOT / "scripts" / "verify_agent_platform_browser_flow.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_agent_platform_browser_flow_wrapper_runs_optional_playwright_lane() -> None:
    script = _read(BROWSER_FLOW_WRAPPER)

    for phrase in [
        "CAMBRIAN_BROWSER_NODE_MODULES",
        "C:/tmp/cambrian-playwright-deps",
        "npm install --prefix",
        "playwright",
        "tests/test_agent_platform_browser_flow.py",
        "test_builder_conversation_recommends_template_and_updates_workspace",
        "Agent Platform browser flow smoke passed",
    ]:
        assert phrase in script


def test_agent_platform_builder_exists_and_is_linked_from_home() -> None:
    home = _read(WEB / "index.html")

    assert PLATFORM.exists()
    assert "platform/index.html" in home
    assert "Open Agent Platform Builder" in home
    assert RUNNER.exists()
    assert "runner/index.html" in home
    assert "Open Local Runner" in home


def test_agent_marketplace_home_prioritizes_simple_market_builder_workspace_flow() -> None:
    home = _read(WEB / "index.html")

    for phrase in [
        "Cambrian Agent Market",
        "AI Agent Marketplace",
        "필요한 AI 직원을 찾고",
        "대화로 만들고",
        "가상 워크스페이스에서 먼저 돌려보세요",
        "Demo Video Preview",
        "추천 보기",
        "Verified Agent Cards",
        "문서 정리 에이전트",
        "회의록 정리 에이전트",
        "가져간다",
        "AI Worker Installer",
    ]:
        assert phrase in home


def test_agent_platform_builder_adds_conversation_and_virtual_workspace_layer() -> None:
    html = _read(PLATFORM)

    for phrase in [
        "대화로 만들고, 보기에서 고르기",
        "만들고 싶은 일",
        "builderIntentInput",
        "builderFollowupInput",
        "generateSuggestionsButton",
        "buildConversationAgentButton",
        "downloadConversationPackButton",
        "runConversationAgentButton",
        "conversationBuildStatus",
        "applyConversationToBuilder",
        "buildConversationAgent",
        "downloadConversationPack",
        "runConversationAgent",
        "shortConversationText",
        "CONVERSATION_READINESS_CHECKS",
        "evaluateConversationReadiness",
        "conversationReadinessText",
        "refreshConversationReadinessStatus",
        "conversationReadinessValidationLines",
        "followupChoiceRow",
        "FOLLOWUP_CHOICE_SETS",
        "followupChoicesForReadiness",
        "renderFollowupChoices",
        "appendFollowupChoice",
        "conversationDraftText",
        "outputFormatFromConversation",
        "syncConversationOutputFormat",
        "conversationWorkspaceSample",
        "syncConversationDraftSurface",
        "workspaceFormatLines",
        "선택 형식:",
        "workspaceSampleTouched",
        "상태: 계약 준비도 완료",
        "샘플 입력:",
        "updateConversationCtaState",
        "ensureConversationReadyForExport",
        "dataset.followupChoice",
        "readinessStatus",
        "먼저 추가 질문에 답하면 다운로드하거나 실행할 수 있습니다.",
        "다운로드 잠금",
        "초안 생성",
        "추가 질문 빠른 선택",
        "계약 준비도",
        "needs_more_detail",
        "ready_to_build",
        "readiness_snapshot",
        "followup_answer",
        "inferTemplateFromIntent",
        "recommendTemplateFromConversation",
        "conversationStatus",
        "AI가 다음 질문을 정리합니다",
        "AI 연결 상태와 제안 로그",
        "focus-pill",
        "card-meta",
        "AI Builder Gateway",
        "aiGatewayStatus",
        "AI_BUILDER_API_CONTRACT",
        "server_gateway_optional",
        "gateway_enabled_by_default",
        "timeout_ms",
        "failure_mode",
        "validated_local_fallback",
        "/api/builder/guide",
        "provider API key",
        "buildAiBuilderRequest",
        "renderAiGatewayStatus",
        "local_template_recommendation",
        "aiGatewayQuestion",
        "aiGatewaySuggestions",
        "aiGatewayPatchStatus",
        "buildLocalAiBuilderResponse",
        "validateAiBuilderResponse",
        "renderAiBuilderGuidance",
        "refreshAiBuilderGuidance",
        "isAiBuilderGatewayEnabled",
        "fetchAiBuilderGateway",
        "requestAiBuilderGuidance",
        "buildFallbackAiBuilderResponse",
        "AI Builder Gateway 호출 중",
        "AI Builder Gateway 요청 실패",
        "allowed_contract_patch_fields",
        "forbidden_patch_tokens",
        "contract_patch 검증 통과",
        "contract_patch 차단",
        "추천 에이전트 보기",
        "data-template-choice",
        "updateBuilderExperience",
        "가상환경에서 먼저 돌려보기",
        "workspaceAgentName",
        "workspaceRunSummary",
        "Virtual Run · preview only",
        "workspaceSampleInput",
        "simulateWorkspaceButton",
        "workspaceSimulationStatus",
        "workspaceSimulationOutput",
        "workspaceSimulationTrace",
        "workspaceResultCards",
        "workspace-result-card",
        "renderWorkspaceResultCards",
        "전체 결과 보기",
        "안전하게 미리보기",
        "안전 로그",
        "가상 실행 결과",
        "sampleInputForTemplate",
        "simulatedWorkspaceOutput",
        "renderWorkspaceSimulation",
        "no_runtime_evidence",
        "quickSaveHubButton",
        "quickSendRunnerButton",
        "사용자용 에이전트 결과 카드",
        "plainAgentName",
        "plainPermissionList",
        "plainSafetyList",
        "Workspace 실행 미리보기",
        "renderPlainPackageReview",
        "고급 패키지 파일 보기",
    ]:
        assert phrase in html


def test_agent_platform_is_not_cambrian_required() -> None:
    html = _read(PLATFORM)

    for phrase in [
        "platform-first",
        "Defensible Alpha",
        "AI 직원을 만들고 내 PC에 설치",
        "audit lineage",
        "cambrian_required",
        "false",
        "cambrian_compatible",
        "planned",
        "Cambrian 없이도 사용할 수 있습니다",
    ]:
        assert phrase in html


def test_agent_platform_generates_downloadable_agent_pack_contract() -> None:
    html = _read(PLATFORM)

    for phrase in [
        "contract_schema",
        "agent_contract_v0_1",
        "agent_pack_bundle_v0_1",
        "agent.json",
        "agent_card.json",
        "instructions.md",
        "run_local.md",
        "legal_notice.md",
        "preflight_report.json",
        "marketplace_review.json",
        "manifest.json",
        "agent_pack_bundle",
        ".agent-pack.json",
        "downloadPackage",
    ]:
        assert phrase in html


def test_agent_platform_shows_builder_golden_path_before_deep_audit_flow() -> None:
    html = _read(PLATFORM)

    for phrase in [
        "Builder Golden Path",
        "Cambrian 없이 생성, 검증, 다운로드, 수동 실행",
        "Green 템플릿 선택",
        "Agent Contract 생성",
        "Risk and Legal Gate preflight",
        "agent pack private download",
        "Private Download Hub와 .agent-pack.json",
        "manual_no_api Local Runner",
        "single-use handoff, manual_run_receipt와 evolution suggestion 초안",
        "Local Runner로 보내기",
        "RUNNER_HANDOFF_STORAGE_KEY",
        "agent-platform-runner-handoff-v0-1",
        "agent_platform_runner_handoff_v0_1",
        "builder_to_manual_runner",
        "private_download_hub_to_manual_runner",
        "sendCurrentPackageToRunner",
        "sendHubRecordToRunner",
        "data-hub-run",
        "Runner로 실행",
    ]:
        assert phrase in html


def test_agent_platform_green_templates_fill_contract_inputs() -> None:
    html = _read(PLATFORM)

    for phrase in [
        "Green 템플릿",
        "GREEN_TEMPLATES",
        "applyTemplate",
        "document_organizer",
        "meeting_notes",
        "email_draft",
        "checklist_maker",
        "회의록 정리 에이전트",
        "이메일 초안 에이전트",
        "체크리스트 생성 에이전트",
        "낮은 위험 업무만 제공한다",
        "의료, 법률, 투자, 채용 판단 템플릿은 만들지 않는다",
    ]:
        assert phrase in html


def test_agent_platform_generates_private_agent_card() -> None:
    html = _read(PLATFORM)
    doc = _read(PLATFORM_DOC)

    for phrase in [
        "agentCard",
        "agent_card.json",
        "private_agent_card",
        "agent_card_matches_contract",
        "agent_card_private_preview",
        "sale_ready: false",
        "proof_claim_allowed",
    ]:
        assert phrase in html

    for phrase in [
        "private preview card",
        "visibility: private",
        "sale_ready: false",
        "proof_claim_allowed: false",
    ]:
        assert phrase in doc


def test_agent_platform_generates_marketplace_review_gate() -> None:
    html = _read(PLATFORM)
    doc = _read(PLATFORM_DOC)

    for phrase in [
        "marketplaceReview",
        "marketplace_review.json",
        "private_marketplace_review",
        "marketplace_review_matches_card",
        "marketplace_review_not_ready",
        "status: \"not_ready\"",
        "required_before_public_listing",
    ]:
        assert phrase in html

    for phrase in [
        "marketplace_review.json",
        "private_marketplace_review",
        "not_ready",
        "runtime evidence",
    ]:
        assert phrase in doc


def test_agent_platform_risk_gate_blocks_red_and_warns_no_fake_proof() -> None:
    html = _read(PLATFORM)

    for phrase in [
        "riskReport",
        "Green",
        "Yellow",
        "Red",
        "차단 대상",
        "의료 결정",
        "법률 결정",
        "투자·금융 결정",
        "채용·해고 판단",
        "no_runtime_evidence",
        "실제 성공률은 실행 데이터가 생긴 뒤에만 표시",
    ]:
        assert phrase in html


def test_agent_platform_private_download_hub_is_local_only() -> None:
    html = _read(PLATFORM)

    for phrase in [
        "Private Download Hub",
        "agent-platform-download-hub-v0-1",
        "PROMOTION_AUDIT_STORAGE_KEY",
        "agent-platform-promotion-audit-v0-1",
        "HUB_HANDOFF_STORAGE_KEY",
        "agent-platform-hub-handoff-v0-1",
        "localStorage",
        "본문 해시까지 맞을 때만 verified linked",
        "saveCurrentPackage",
        "downloadHubRecord",
        "deleteHubRecord",
        "clearHub",
        "importPromotionRecordInput",
        "promotionAuditList",
        "promotionAuditCount",
        "readPromotionAuditRecords",
        "writePromotionAuditRecords",
        "validatePromotionRecord",
        "validateHubHandoffEnvelope",
        "savePromotedHandoffToHub",
        "loadHubHandoff",
        "agent_platform_hub_handoff_v0_1",
        "evolution_review_to_private_download_hub",
        "evolutionCountFromBundle",
        "evolutionCountLabel",
        "evolution_count",
        "evolution_count_label",
        "data-evolution-count",
        "lineageCardForHubRecord",
        "private_hub_lineage_card_v0_1",
        "data-hub-lineage",
        "data-hub-lineage-download",
        "lineage 보기",
        "lineage 다운로드",
        "verifyLineageCardInput",
        "validateLineageCardShape",
        "verifyLineageCardAgainstHub",
        "lineageVerifierReportChecksum",
        "lineageVerifierReportPayload",
        "verifyLineageReportInput",
        "downloadVerificationReportButton",
        "downloadGoldPathReceiptButton",
        "lineageVerifierReportWithoutReceiptChecksum",
        "verifyLineageVerifierReportReceipt",
        "lineageReportReceiptVerifierPayload",
        "currentVerificationReportPayload",
        "downloadCurrentVerificationReport",
        "lineageVerificationReportIsPass",
        "currentPassingLineageVerificationReport",
        "builderGoldPathReceiptState",
        "renderBuilderGoldPathReceiptSummary",
        "downloadBuilderGoldPathShareReceipt",
        "BUILDER_GOLD_PATH_SHARE_RECEIPT_SCHEMA",
        "external_alpha_builder_gold_path_share_receipt_v0_1",
        "external_alpha_builder_gold_path_share_receipt.json",
        "gold path receipt 다운로드",
        "Builder Golden Path receipt 요약",
        "browser_share_safe_summary_v0_1",
        "raw_browser_storage_excluded",
        "raw_browser_storage_included",
        "candidate_diff_report_created",
        "promoted_private_version_created",
        "promotion_audit_record_created",
        "private_hub_lineage_verified",
        "verifyLineageReportFile",
        "verifyLineageCardFile",
        "private_hub_lineage_card_verifier_report_v0_1",
        "private_hub_lineage_report_receipt_verifier_report_v0_1",
        "report_kind",
        "report_version",
        "report_privacy",
        "report_provenance",
        "receipt_checksum",
        "receipt_checksum_algorithm",
        "receipt_checksum_scope",
        "receipt_checksum_matches_report",
        "stores_raw_card",
        "stores_raw_report",
        "echoes_non_lineage_identity",
        "echoes_non_report_identity",
        "private_hub_lineage_card_verifier_v0_1",
        "private_hub_lineage_report_receipt_verifier_v0_1",
        "lineage report receipt 검증 완료",
        "lineage report receipt 검증 실패",
        "verification report 다운로드",
        "lineage-verifier-report.json",
        "lineage card 검증 완료",
        "lineage card 검증 실패",
        "effect: \"report_only\"",
        "hub_storage_write",
        "promotion_audit_storage_write",
        "runner_handoff_write",
        "installs_or_runs_agent",
        "JSON 파일을 읽거나 해석하지 못했습니다",
        "content_hash_matches_hub",
        "fingerprint_matches_hub",
        "evolution_count_matches_hub",
        "privacy_boundary_blocked",
        "audit_link_matches_hub",
        "private_download_hub_to_manual_runner",
        "sendHubRecordToRunner",
        "data-hub-run",
        "Runner로 실행",
        "savePromotionRecordToAudit",
        "sha256PayloadHash",
        "content_hash",
        "promotionAuditMatchesHubRecord",
        "promotionAuditLinkLabel",
        "promotionAuditsForHubRecord",
        "linkedHubRecordForPromotionAudit",
        "viewPromotionAuditRecord",
        "downloadPromotionAuditRecord",
        "deletePromotionAuditRecord",
        "data-audit-view",
        "data-audit-download",
        "data-audit-delete",
        "candidate_promotion_record_v0_1",
        "gate.output_overwrite_blocked",
        "승격 기록 가져오기 완료",
        "auditBadgeLabel",
        "audit 1",
        "verified linked",
        "promoted hash mismatch",
        "waiting promoted pack",
        "promotion audit verified",
        "promotion audit",
        "version_label",
        "revision",
        "fingerprint",
        "change_summary",
        "input_provenance",
        "bundleFingerprint",
        "describeBundleChange",
        "agentPackLifecycle",
        "lifecycle_stage",
        "hub-lifecycle",
        "builder_private_draft",
        "candidate_not_applied",
        "promoted_private_version",
        "Promoted private",
        "Candidate review",
        "proof blocked",
        "sale blocked",
        "stores_raw_inputs: false",
        "stores_secrets: false",
        "서버 계정, 공개 마켓, Cambrian Runtime으로 전송하지 않습니다",
        "private local browser",
        "Private Download Hub와 promotion audit records를 비웠습니다",
        "Evolution handoff를 Hub에 저장했습니다",
    ]:
        assert phrase in html


def test_agent_platform_private_download_hub_keeps_version_history() -> None:
    html = _read(PLATFORM)
    doc = _read(PLATFORM_DOC)

    for phrase in [
        "nextHubRevision",
        "이전 버전과 내용 변화 없음",
        "초기 저장",
        "계약 세부값 변경",
        "agent_id-version_label.agent-pack.json",
        "${record.agent_id || \"agent\"}-${record.version_label || \"v1\"}.agent-pack.json",
    ]:
        assert phrase in html or phrase in doc

    for phrase in [
        "revision",
        "version_label",
        "fingerprint",
        "change_summary",
        "input_provenance",
        "원문 문서, 사용자 입력 파일 내용, secret 값 자체는 저장하지 않는다",
        "같은 `agent_id`의 최신 레코드를 기준으로 다음 `revision`을 계산한다",
        "builder_private_draft",
        "candidate_not_applied",
        "promoted_private_version",
        "proof blocked",
        "sale blocked",
        "새 `Builder draft`로 저장된다",
        "promoted private version 가져오기",
        "promotion audit record",
        "agent-platform-promotion-audit-v0-1",
        "agent-platform-hub-handoff-v0-1",
        "promotion audit records",
        "JSON 보기",
        "다시 다운로드",
        "개별 삭제",
        "audit 보기/다운로드/삭제",
    ]:
        assert phrase in doc


def test_agent_platform_private_download_hub_restores_and_compares_versions() -> None:
    html = _read(PLATFORM)
    doc = _read(PLATFORM_DOC)

    for phrase in [
        "hubDiff",
        "restoreBuilderFromBundle",
        "restoreHubRecord",
        "compareHubRecord",
        "describeBundleDiff",
        "previousHubRecord",
        "data-hub-restore",
        "data-hub-compare",
        "data-hub-lineage",
        "data-hub-lineage-download",
        "복원 실패",
        "Builder 초안으로 복원했습니다",
        "저장하면 새 Builder draft로 저장됩니다",
        "비교할 이전 버전이 없습니다",
    ]:
        assert phrase in html

    for phrase in [
        "저장된 버전은 client preflight를 다시 통과한 뒤 Builder 입력값으로 복원할 수 있다",
        "같은 `agent_id`의 이전 버전과 이름, 역할, 목표, 출력, 권한, 금지 행동, 검증 기준, 위험 등급, 템플릿, 카드 요약 차이를 비교할 수 있다",
        "저장된 버전을 Builder로 복원하기 전 `clientPreflightBundle`을 다시 실행한다",
        "버전 비교는 같은 `agent_id`의 직전 저장 레코드와 계약 핵심 필드 차이만 보여준다",
        "브라우저 smoke 검증은 독립 브라우저 context에서 저장, 수정, 재저장, 비교, 복원 흐름을 확인한다",
        "evolution_signal.eligible_for_suggestion: true",
        "생성된 suggestion의 `source_receipt`에도 이 두 신호를 다시 남겨",
        "source_receipt_eligible_for_suggestion: true",
        "모든 recommendation_id에는 정확히 하나의 decision이 있어야 하며",
        "빈 문자열이 아닌 `reviewer_note`",
        "approved` decision이 하나도 없으면 후보 pack을 생성하지 않는다",
        "candidate_metadata.apply_status: candidate_not_applied",
        "candidate_metadata.auto_apply: false",
        "candidate_metadata.auto_promote: false",
        "candidate_metadata.requires_user_final_review: true",
        "promote_candidate_pack.py",
        "promotion_metadata.promotion_status: promoted_private_version",
        "promotion_metadata.user_command_required: true",
        "promotion_metadata.auto_promote: false",
        "promotion_metadata.proof_claim_allowed: false",
        "candidate_promotion_record_v0_1",
        "validate_candidate_promotion_record.py",
        "verify_promotion_audit_link.py",
        "gate.output_overwrite_blocked: true",
        "Private Download Hub의 새 private version 후보",
        "Private Hub로 보내기는 promoted pack과 promotion record를 함께 저장하되",
        "Hub에 저장된 버전은 `private_download_hub_to_manual_runner` handoff로 Local Runner에 바로 보낼 수 있다",
        "Hub에서 다시 실행한 promoted pack은 `promoted_private_version` source로 2회차 Evolution 재검토가 가능하다",
        "2회차 candidate 생성 시 이전 `promotion_metadata`는 제거되고 diff report에는 허용된 removal로만 남는다",
        "Private Download Hub는 저장된 버전에 `진화 N회` 배지를 표시하되",
        "lineage card도 proof나 성공률 주장이 아니라 private audit lineage다",
        "lineage card 검증 완료와 실패는 모두 Hub storage, promotion audit storage, Runner handoff를 변경하지 않는다",
        "lineage verifier report는 `effect: report_only`와 `side_effects.hub_storage_write: false`",
        "lineage verifier report는 `report_kind: private_hub_lineage_card_verifier_report_v0_1`",
        "malformed JSON lineage card도 `private_hub_lineage_card_verifier_v0_1` fail report로 표시하고 이전 report를 그대로 남기지 않는다",
        "agent pack처럼 lineage card가 아닌 valid JSON도 `card_kind` mismatch fail report로 표시하고 Hub/Runner 상태를 변경하지 않는다",
        "lineage card가 아닌 JSON의 agent_id, version_label, raw content는 verifier report/status에 echo하지 않고 `unknown`으로 표시한다",
        "배열이나 문자열 같은 non-object JSON도 `lineage card 객체` fail report로 표시하고 원문 값을 echo하지 않는다",
        "변조된 lineage card는 content hash, fingerprint, evolution count, audit link 중 하나라도 맞지 않으면 fail로 표시한다",
        "lineage card가 원문 입력, 원문 결과, secret을 저장한다고 주장하도록 변조되어도 `privacy_boundary_blocked` fail로 표시한다",
        "lineage card가 proof claim, success rate claim, sale ready를 주장하도록 변조되어도 fail로 표시한다",
        "lineage card가 `verified linked`를 주장해도 audit fingerprint와 promoted pack hash가 Hub audit과 맞지 않으면 fail로 표시한다",
        "audit import 전에 받은 stale `not linked` lineage card는 Hub에 verified audit이 생긴 뒤 fail로 표시한다",
    ]:
        assert phrase in doc


def test_agent_platform_imports_agent_pack_with_client_preflight() -> None:
    html = _read(PLATFORM)

    for phrase in [
        "importHubInput",
        "패키지 가져오기",
        "clientPreflightBundle",
        "importHubFile",
        "가져온 패키지는 브라우저 안에서 client preflight 검증 후 저장됩니다",
        "bundle_schema가 agent_pack_bundle_v0_1이 아닙니다",
        "preflight status가 risk blocks와 일치하지 않습니다",
        "candidate_metadata가 필요합니다",
        "promotion_metadata가 필요합니다",
        "promoted pack은 candidate_metadata를 포함할 수 없습니다",
        "promotion auto_promote는 false여야 합니다",
        "promotion marketplace_sale_ready는 false여야 합니다",
        "record.lifecycle_label",
        "saveBundleToHub(bundle, \"import\", { contentHash })",
    ]:
        assert phrase in html


def test_platform_foundation_doc_names_defensible_alpha_boundary() -> None:
    doc = _read(PLATFORM_DOC)

    for phrase in [
        "Platform-first",
        "Cambrian Runtime을 필수 조건으로 만들지 않는다",
        "MVP가 아니라 Defensible Alpha다",
        "방어 가능한 첫 시스템",
        "한국 시장",
        "단순 에이전트 쇼핑몰 UI가 아니다",
        "계약·검증·감사·진화 표준",
        "문서 정리 에이전트",
        "Risk and Legal Gate",
        "Package Builder",
        "Download Hub",
        "Future Cambrian Adapter",
        "고정 계획",
        "법률과 위험 게이트",
        "Marketplace는 proof 이후에만 연다",
    ]:
        assert phrase in doc

    assert "## 4. MVP 범위" not in doc


def test_platform_foundation_locks_next_task_to_builder_golden_path() -> None:
    doc = _read(PLATFORM_DOC)

    for phrase in [
        "2026-05-11 Task Direction Lock",
        "판정: 방향은 맞지만 다음 우선순위는 Builder Golden Path다.",
        "Green:",
        "Yellow:",
        "Red line:",
        "다음 단계는 Builder Golden Path Lock이다.",
        "Green 템플릿 선택",
        "Agent Contract 생성",
        "Risk and Legal Gate 확인",
        "agent pack private download",
        "Local Runner로 보내기",
        "manual_no_api Local Runner 열기",
        "manual_run_receipt 내보내기",
        "Evolution으로 보내기",
        "evolution suggestion 초안 생성",
        "사용자가 recommendation 검토",
        "후보 pack 내보내기",
        "diff report 내보내기",
        "promoted pack 내보내기",
        "promotion record 내보내기",
        "Private Hub로 보내기",
        "Hub가 promoted pack + promotion audit verified linked 표시",
        "Hub 저장 버전 Runner로 실행",
        "agent-platform-runner-handoff-v0-1",
        "Builder handoff는 `agent-platform-runner-handoff-v0-1`에 한 번만 저장되고 Runner가 읽은 뒤 제거한다",
        "agent-platform-evolution-handoff-v0-1",
        "Evolution handoff는 `agent-platform-evolution-handoff-v0-1`에 한 번만 저장되고 Evolution Review Gate가 읽은 뒤 제거한다",
        "source_bundle",
        "candidate pack은 자동 적용이 아니라 `candidate_not_applied` preview/export로만 표시된다",
        "diff report는 자동 승격이 아니라 `review_pass_not_promoted` review gate로만 표시된다",
        "promoted pack은 공개 배포가 아니라 `promoted_private_version` private export로만 표시된다",
        "promotion record는 promoted pack hash까지 연결하는 audit record로만 표시된다",
        "Cambrian Runtime을 platform-first 알파의 필수 조건으로 바꾸지 않는다",
        "provider API key, secret, 비밀번호를 수집하지 않는다",
        "공개 마켓, 결제, 판매 가능 배지, 성공률, proof claim을 먼저 만들지 않는다",
        "receipt는 proof가 아니라 `manual_review_only` metadata로만 표시된다",
        "Private Download Hub의 promoted private version도 `proof blocked`, `sale blocked`를 유지한다",
    ]:
        assert phrase in doc


def test_agent_platform_text_is_readable_korean_not_mojibake() -> None:
    combined = _read(PLATFORM) + "\n" + _read(PLATFORM_DOC)

    for marker in ["濡", "먯", "꾪", "�"]:
        assert marker not in combined


def test_platform_first_plan_is_locked_into_core_architecture_docs() -> None:
    foundation = _read(PLATFORM_DOC)
    ten_year = _read(TEN_YEAR_DOC)
    constitution = _read(CONSTITUTION_DOC)

    for phrase in [
        "agent contract",
        "downloadable agent pack",
        "preflight validation",
        "optional Cambrian adapter",
        "trusted marketplace",
    ]:
        assert phrase in ten_year

    for phrase in [
        "Platform-first creates portable AI agent contracts.",
        "Local Cambrian Runtime turns those contracts into execution, validation, evidence, proof, and evolution.",
        "claim proof, performance, or success rate without runtime evidence",
        "collect passwords, tokens, or personal API keys by default",
    ]:
        assert phrase in constitution

    assert "Cambrian adapter는 이 4단계가 안정화된 뒤에 시작한다" in foundation
    assert "이 문서는 법률 자문이 아니다" in foundation
    assert "실제 실행 evidence가 없으면 proof, 성능, 성공률을 주장하지 않는다" in ten_year


def test_agent_contract_schema_exists_and_requires_platform_first_boundary() -> None:
    schema = json.loads(_read(AGENT_CONTRACT_SCHEMA))

    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["runtime"]["properties"]["cambrian_required"]["const"] is False
    assert schema["properties"]["data_policy"]["properties"]["default_visibility"]["const"] == "private"
    assert "agent_contract_v0_1" == schema["properties"]["contract_schema"]["const"]


def test_agent_pack_bundle_schema_exists_and_blocks_fake_marketplace_readiness() -> None:
    schema = json.loads(_read(AGENT_PACK_BUNDLE_SCHEMA))

    Draft202012Validator.check_schema(schema)
    required_preflight_checks = set(schema["x-required_preflight_checks"])
    marketplace = schema["$defs"]["manifest"]["properties"]["marketplace"]["properties"]
    assert marketplace["visibility"]["const"] == "private"
    assert marketplace["public_listing_allowed"]["const"] is False
    assert marketplace["sale_ready"]["const"] is False
    assert marketplace["proof_claim_allowed"]["const"] is False
    assert schema["properties"]["bundle_schema"]["const"] == "agent_pack_bundle_v0_1"
    assert "runner_names_cambrian_optional" in required_preflight_checks
    assert "runner_names_manual_runner" in required_preflight_checks
    assert "proof_claim_blocked" in required_preflight_checks
    assert "embedded_preflight_checks_complete" not in required_preflight_checks
    assert "candidate_metadata" in schema["properties"]
    assert "promotion_metadata" in schema["properties"]
    assert "tools/promote_candidate_pack.py" in schema["properties"]["generated_by"]["enum"]
    assert schema["$defs"]["candidate_metadata"]["properties"]["apply_status"]["const"] == "candidate_not_applied"
    assert schema["$defs"]["candidate_metadata"]["properties"]["auto_apply"]["const"] is False
    assert schema["$defs"]["candidate_metadata"]["properties"]["auto_promote"]["const"] is False
    assert schema["$defs"]["promotion_metadata"]["properties"]["promotion_status"]["const"] == "promoted_private_version"
    assert schema["$defs"]["promotion_metadata"]["properties"]["auto_promote"]["const"] is False
    assert schema["$defs"]["promotion_metadata"]["properties"]["marketplace_sale_ready"]["const"] is False


def test_document_organizer_sample_pack_validates_agent_contract() -> None:
    schema = json.loads(_read(AGENT_CONTRACT_SCHEMA))
    sample = json.loads(_read(SAMPLE_PACK))
    agent_contract = sample["files"]["agent.json"]

    Draft202012Validator(schema).validate(agent_contract)
    assert sample["package_kind"] == "agent_pack_bundle"
    assert sample["platform_track"] == "platform-first"
    assert sample["files"]["manifest.json"]["agent_contract_schema"] == "agent_contract_v0_1"
    assert agent_contract["runtime"]["cambrian_required"] is False
    assert agent_contract["risk_level"] == "green"


def test_document_organizer_sample_pack_validates_full_bundle_contract() -> None:
    schema = json.loads(_read(AGENT_PACK_BUNDLE_SCHEMA))
    sample = json.loads(_read(SAMPLE_PACK))

    Draft202012Validator(schema).validate(sample)
    manifest = sample["files"]["manifest.json"]
    required_preflight_checks = set(schema["x-required_preflight_checks"])
    embedded_preflight_checks = {
        check["name"] for check in sample["files"]["preflight_report.json"]["checks"]
    }
    assert sample["bundle_schema"] == "agent_pack_bundle_v0_1"
    assert manifest["schema_ref"]["bundle"] == "schemas/agent_pack_bundle_v0_1.schema.json"
    assert manifest["schema_ref"]["agent_contract"] == "schemas/agent_contract_v0_1.schema.json"
    assert "agent_card.json" in manifest["files"]
    assert "preflight_report.json" in manifest["files"]
    assert "marketplace_review.json" in manifest["files"]
    assert sample["files"]["agent_card.json"]["card_kind"] == "private_agent_card"
    assert sample["files"]["agent_card.json"]["marketplace"]["sale_ready"] is False
    assert sample["files"]["agent_card.json"]["marketplace"]["proof_claim_allowed"] is False
    assert sample["files"]["marketplace_review.json"]["review_kind"] == "private_marketplace_review"
    assert sample["files"]["marketplace_review.json"]["status"] == "not_ready"
    assert sample["files"]["marketplace_review.json"]["sale_ready"] is False
    assert sample["files"]["marketplace_review.json"]["proof_claim_allowed"] is False
    assert sample["files"]["preflight_report.json"]["validator"] == "agent_pack_preflight_v0_1"
    assert sample["files"]["preflight_report.json"]["status"] == "pass"
    assert required_preflight_checks.issubset(embedded_preflight_checks)
    assert manifest["evidence_status"] == "no_runtime_evidence"
    assert manifest["marketplace"]["visibility"] == "private"
    assert manifest["marketplace"]["sale_ready"] is False
    assert manifest["marketplace"]["proof_claim_allowed"] is False


def test_agent_platform_links_manual_no_api_local_runner() -> None:
    html = _read(PLATFORM)
    runner = _read(RUNNER)
    doc = _read(PLATFORM_DOC)

    for phrase in [
        "../runner/index.html",
        "web/runner/index.html",
        "manual_no_api",
        "runner_names_manual_runner",
        "Local Runner로 보내기",
        "agent-platform-runner-handoff-v0-1",
        "agent_platform_runner_handoff_v0_1",
        "builder_to_manual_runner",
        "private_download_hub_to_manual_runner",
        "sendCurrentPackageToRunner",
        "sendHubRecordToRunner",
    ]:
        assert phrase in html

    for phrase in [
        "Agent Pack Local Runner",
        "https://cambrian.local/schemas/manual_run_receipt_v0_1.schema.json",
        "manual_no_api",
        "agent-platform-manual-runner-v0-1",
        "agent-platform-runner-handoff-v0-1",
        "Builder handoff",
        "Private Download Hub handoff",
        "Builder handoff 불러오기",
        "validateBuilderHandoff",
        "loadBuilderHandoff",
        "currentLoadSource",
        "runnerSourceLabel",
        "runnerNextStepText",
        "파일 로드 실패:",
        "다음: 작업 입력을 붙이고 실행 프롬프트 생성을 누르세요.",
        "작업 입력 → 실행 프롬프트 생성 → AI 결과 붙여넣기 → 검토 완료 + 영수증",
        "handoff_schema가 agent_platform_runner_handoff_v0_1",
        "handoff_kind가 builder_to_manual_runner",
        "private_download_hub_to_manual_runner",
        "api_key_collected: false",
        "single_use: true",
        "localStorage에서 제거했습니다",
        "Evolution으로 보내기",
        "EVOLUTION_HANDOFF_STORAGE_KEY",
        "agent-platform-evolution-handoff-v0-1",
        "agent_platform_evolution_handoff_v0_1",
        "manual_runner_to_evolution_review",
        "source_bundle: currentBundle",
        "buildEvolutionSuggestionDraft",
        "validateEvolutionSuggestionDraft",
        "sendEvolutionHandoff",
        "AI 결과를 붙여 넣은 receipt만 evolution suggestion으로 보낼 수 있습니다.",
        "validateBundle",
        "buildManualPrompt",
        "contractOutputs",
        "contractOutputReviewCriteria",
        "manualReviewCriteria",
        "formatSignalForOutput",
        "manualReviewMeta",
        "formatSignalSummary",
        "formatSignalSummaryText",
        "형식 신호 감지:",
        "형식 신호 ${summary.found}/${summary.total} 감지",
        "manual_check_count",
        "format_signal_total",
        "format_signal_found",
        "format_signal_missing",
        "계약 출력 형식 신호를 instructions에 고정",
        "formatSummary.missing",
        "부족 형식은 ${formatSummary.missing.join",
        "원문 결과를 저장하지 않고 수동 검토 메타데이터만 사용한다.",
        "proof가 아니라 수동 검토 보조입니다.",
        "AI 결과를 붙여 넣으면 계약 출력 형식 신호를 함께 확인합니다.",
        "buildManualRunReceipt",
        "completeRunButton",
        "completeManualRunAndExportReceipt",
        "검토 완료 + 영수증",
        "AI 결과를 먼저 붙여 넣어야 실행 영수증을 만들 수 있습니다.",
        "outputs: ${outputs.join",
        "계약 출력 형식",
        "계약 출력 형식(${output})을 결과가 지켰는지 확인",
        "manual_run_receipt_v0_1",
        "exportManualRunReceipt",
        "manual-run-receipt.json",
        "no_runtime_evidence",
        "proof_claim_allowed: false",
        "success_rate_claim_allowed: false",
        "marketplace_sale_ready: false",
        "secret_collection: forbidden_by_default",
        "stores_raw_inputs: false",
        "stores_raw_outputs: false",
        "api_key_collected: false",
        "Red 위험 항목이 있어 실행 프롬프트 생성을 막았습니다.",
    ]:
        assert phrase in runner

    for phrase in [
        "web/runner/index.html",
        "builder handoff key: agent-platform-runner-handoff-v0-1",
        "evolution handoff key: agent-platform-evolution-handoff-v0-1",
        "runner_mode: manual_no_api",
        "API 키를 받지 않고",
        "agent_platform_runner_handoff_v0_1",
        "builder_to_manual_runner",
        "private_download_hub_to_manual_runner",
        "agent_platform_evolution_handoff_v0_1",
        "manual_runner_to_evolution_review",
        "source_bundle",
        "candidate_agent_pack_metadata_v0_1",
        "candidate_not_applied",
        "original_pack_preserved",
        "single_use: true",
        "Runner는 `?handoff=builder`로 열릴 때 handoff를 자동으로 읽고",
        "Evolution Review Gate는 `?handoff=runner`로 열릴 때 이 handoff를 자동으로 읽고",
        "manual_review_only",
        "manual_run_receipt_v0_1",
        "proof_boundary",
        "evolution_signal",
        "success_rate_claim_allowed: false",
    ]:
        assert phrase in doc
