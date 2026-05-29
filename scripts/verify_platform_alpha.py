"""외부 알파용 Agent Platform RC 자체 검증 스크립트."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VALIDATOR_IMPORT_ERROR: ImportError | None = None

try:
    from tools.validate_agent_pack import validate_agent_pack
    from tools.validate_candidate_diff_report import validate_candidate_diff_report
    from tools.validate_candidate_promotion_record import validate_candidate_promotion_record
    from tools.validate_evolution_review_decision import validate_evolution_review_decision
    from tools.validate_evolution_suggestion import validate_evolution_suggestion
    from tools.validate_manual_run_receipt import validate_manual_run_receipt
except ImportError as exc:
    VALIDATOR_IMPORT_ERROR = exc


Check = tuple[str, Callable[[], None]]


def main() -> int:
    """필수 파일, 샘플 계약, 브라우저 표면을 검증한다."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    if VALIDATOR_IMPORT_ERROR is not None:
        print(f"[FAIL] dependencies: {VALIDATOR_IMPORT_ERROR}")
        print("검증 의존성이 없으면 `python -m pip install -e .`를 먼저 실행하세요.")
        return 1

    checks: list[Check] = [
        ("required_files", _check_required_files),
        ("agent_pack_samples", _check_agent_pack_samples),
        ("sidecar_samples", _check_sidecar_samples),
        ("web_surface", _check_web_surface),
        ("direction_lock", _check_direction_lock),
        ("release_docs", _check_release_docs),
        ("readable_text", _check_readable_text),
    ]
    failures: list[tuple[str, str]] = []

    for name, check in checks:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - 외부 알파 검증은 실패 항목을 끝까지 모아 보여준다.
            failures.append((name, str(exc)))
            print(f"[FAIL] {name}: {exc}")
        else:
            print(f"[PASS] {name}")

    if failures:
        print("")
        print("Cambrian Agent Platform alpha verification failed.")
        print("실패 항목을 고친 뒤 다시 실행하세요.")
        return 1

    print("")
    print("Cambrian Agent Platform alpha verification passed.")
    print(f"시작 파일: {ROOT / 'START_CAMBRIAN_AGENT_PLATFORM.bat'}")
    print(f"Builder   : {ROOT / 'web' / 'platform' / 'index.html'}")
    print(f"Runner    : {ROOT / 'web' / 'runner' / 'index.html'}")
    return 0


def _check_required_files() -> None:
    """외부 알파 배포에 필요한 파일이 있는지 확인한다."""
    required = [
        "QUICKSTART_EXTERNAL_ALPHA.md",
        "START_HERE_EXTERNAL_ALPHA.md",
        "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
        "EXTERNAL_ALPHA_SUPPORT_PACKET.md",
        "START_CAMBRIAN_AGENT_PLATFORM.bat",
        "VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat",
        "COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat",
        "docs/release/EXTERNAL_ALPHA_RELEASE_MANIFEST.md",
        "docs/launch/PILOT_ISSUE_INTAKE.md",
        "docs/launch/PILOT_FEEDBACK_FORM.md",
        "web/platform/index.html",
        "web/runner/index.html",
        "web/evolution/index.html",
        "web/assets/document-organizer.agent-pack.json",
        "web/assets/document-organizer.candidate.agent-pack.json",
        "web/assets/document-organizer.candidate-diff-report.json",
        "web/assets/document-organizer.promoted.agent-pack.json",
        "web/assets/document-organizer.candidate-promotion-record.json",
        "docs/platform/00_AGENT_PLATFORM_FOUNDATION.md",
        "docs/release/RC_INSTALL_GUIDE.md",
        "scripts/build_external_alpha_release.py",
        "scripts/verify_external_alpha_release.py",
        "scripts/verify_agent_platform_browser_flow.py",
        "scripts/smoke_external_alpha_release_bundle.py",
        "scripts/smoke_external_alpha_post_send_checkpoint.py",
        "scripts/smoke_external_alpha_pilot_learning_loop.py",
        "scripts/prepare_external_alpha_operator_dispatch_packet.py",
        "scripts/prepare_external_alpha_handoff.py",
        "scripts/check_external_alpha_send_ready.py",
        "scripts/check_external_alpha_pilot_ready.py",
        "scripts/check_external_alpha_dispatch_record.py",
        "scripts/check_external_alpha_recipient_checkpoint.py",
        "scripts/check_external_alpha_pilot_review.py",
        "scripts/check_external_alpha_pilot_evidence.py",
        "scripts/check_external_alpha_pilot_decision.py",
        "scripts/check_external_alpha_pilot_iteration.py",
        "scripts/audit_external_alpha_send_chain.py",
        "scripts/collect_external_alpha_diagnostics.py",
    ]
    missing = [path for path in required if not (ROOT / path).exists()]
    if missing:
        raise AssertionError(f"필수 파일 누락: {', '.join(missing)}")


def _check_agent_pack_samples() -> None:
    """Builder, candidate, promoted pack 샘플이 검증기를 통과하는지 확인한다."""
    sample_paths = [
        ROOT / "web" / "assets" / "document-organizer.agent-pack.json",
        ROOT / "web" / "assets" / "document-organizer.candidate.agent-pack.json",
        ROOT / "web" / "assets" / "document-organizer.promoted.agent-pack.json",
    ]
    for path in sample_paths:
        report = validate_agent_pack(path)
        _assert_report_pass(path, report)


def _check_sidecar_samples() -> None:
    """receipt, suggestion, decision, diff, promotion record 샘플이 검증기를 통과하는지 확인한다."""
    checks = [
        (
            ROOT / "web" / "assets" / "document-organizer.manual-run-receipt.json",
            validate_manual_run_receipt,
        ),
        (
            ROOT / "web" / "assets" / "document-organizer.evolution-suggestion.json",
            validate_evolution_suggestion,
        ),
        (
            ROOT / "web" / "assets" / "document-organizer.evolution-review-decision.json",
            validate_evolution_review_decision,
        ),
        (
            ROOT / "web" / "assets" / "document-organizer.candidate-diff-report.json",
            validate_candidate_diff_report,
        ),
        (
            ROOT / "web" / "assets" / "document-organizer.candidate-promotion-record.json",
            validate_candidate_promotion_record,
        ),
    ]
    for path, validator in checks:
        report = validator(path)
        _assert_report_pass(path, report)


def _check_web_surface() -> None:
    """브라우저 표면이 외부 알파 핵심 흐름을 노출하는지 확인한다."""
    platform = _read_text(ROOT / "web" / "platform" / "index.html")
    runner = _read_text(ROOT / "web" / "runner" / "index.html")
    for phrase in [
        "Defensible Alpha",
        "AI 직원을 만들고 내 PC에 설치",
        "Builder Golden Path",
        "Green 템플릿 선택",
        "Agent Contract 생성",
        "agent pack private download",
        "manual_no_api Local Runner",
        "Local Runner로 보내기",
        "RUNNER_HANDOFF_STORAGE_KEY",
        "agent-platform-runner-handoff-v0-1",
        "agent_platform_runner_handoff_v0_1",
        "builder_to_manual_runner",
        "private_download_hub_to_manual_runner",
        "sendHubRecordToRunner",
        "Runner로 실행",
        "audit lineage",
        "verified linked",
        "Private Download Hub",
        "패키지 가져오기",
        "승격 기록 가져오기",
        "Promoted private",
        "proof blocked",
        "sale blocked",
        "agent-platform-promotion-audit-v0-1",
        "agent-platform-hub-handoff-v0-1",
        "loadHubHandoff",
        "validateHubHandoffEnvelope",
        "savePromotedHandoffToHub",
        "evolution_review_to_private_download_hub",
        "evolutionCountFromBundle",
        "evolutionCountLabel",
        "evolution_count",
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
        "browser_share_safe_summary_v0_1",
        "raw_browser_storage_excluded",
        "candidate_diff_report_created",
        "promoted_private_version_created",
        "promotion_audit_record_created",
        "private_hub_lineage_verified",
        "verifyLineageReportFile",
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
        "card_kind",
        "content_hash_matches_hub",
        "fingerprint_matches_hub",
        "evolution_count_matches_hub",
        "privacy_boundary_blocked",
        "audit_link_matches_hub",
        "clientPreflightBundle",
    ]:
        if phrase not in platform:
            raise AssertionError(f"Platform UI 문구 누락: {phrase}")
    for phrase in [
        "Agent Pack Local Runner",
        "manual_no_api",
        "api_key_collected: false",
        "manual_run_receipt_v0_1",
        "Builder handoff",
        "Private Download Hub handoff",
        "agent-platform-runner-handoff-v0-1",
        "private_download_hub_to_manual_runner",
        "validateBuilderHandoff",
        "loadBuilderHandoff",
        "Evolution으로 보내기",
        "EVOLUTION_HANDOFF_STORAGE_KEY",
        "agent-platform-evolution-handoff-v0-1",
        "agent_platform_evolution_handoff_v0_1",
        "manual_runner_to_evolution_review",
        "source_bundle: currentBundle",
        "buildEvolutionSuggestionDraft",
        "sendEvolutionHandoff",
    ]:
        if phrase not in runner:
            raise AssertionError(f"Runner UI 문구 누락: {phrase}")
    for phrase in [
        "Evolution Review Gate",
        "Runner handoff",
        "agent-platform-evolution-handoff-v0-1",
        "agent_platform_evolution_handoff_v0_1",
        "manual_runner_to_evolution_review",
        "validateEvolutionHandoff",
        "loadEvolutionHandoff",
        "source_bundle",
        "후보 pack 내보내기",
        "diff report 내보내기",
        "promoted pack 내보내기",
        "promotion record 내보내기",
        "Private Hub로 보내기",
        "agent-platform-hub-handoff-v0-1",
        "agent_platform_hub_handoff_v0_1",
        "evolution_review_to_private_download_hub",
        "buildCandidatePackAfterUserCommand",
        "buildCandidateDiffReportAfterUserCommand",
        "buildPromotionOutputsAfterUserCommand",
        "sendPromotionOutputsToHub",
        "sourceBundleLifecycleStage",
        "source_lifecycle",
        "candidate 원본은 Builder pack 또는 promoted_private_version이어야 합니다",
        "promoted_private_version을 새 candidate review 초안으로 만들기 위해 이전 promotion_metadata를 제거한다.",
        "candidate_agent_pack_metadata_v0_1",
        "candidate_diff_report_v0_1",
        "candidate_promotion_record_v0_1",
        "candidate_not_applied",
        "promoted_private_version",
        "promoted_agent_pack_metadata_v0_1",
        "review_pass_not_promoted",
        "automatic_candidate_promotion",
        "user_command_required",
        "original_pack_preserved",
        "localStorage에서 제거했습니다",
    ]:
        if phrase not in _read_text(ROOT / "web" / "evolution" / "index.html"):
            raise AssertionError(f"Evolution UI 문구 누락: {phrase}")


def _check_direction_lock() -> None:
    """현재 제품 방향과 다음 우선순위가 문서에 고정되어 있는지 확인한다."""
    platform_doc = _read_text(ROOT / "docs" / "platform" / "00_AGENT_PLATFORM_FOUNDATION.md")
    for phrase in [
        "2026-05-11 Task Direction Lock",
        "판정: 방향은 맞지만 다음 우선순위는 Builder Golden Path다.",
        "Green:",
        "Yellow:",
        "Red line:",
        "다음 단계는 Builder Golden Path Lock이다.",
        "manual_no_api Local Runner",
        "agent-platform-runner-handoff-v0-1",
        "Builder handoff는 `agent-platform-runner-handoff-v0-1`에 한 번만 저장되고 Runner가 읽은 뒤 제거한다.",
        "agent-platform-evolution-handoff-v0-1",
        "Evolution handoff는 `agent-platform-evolution-handoff-v0-1`에 한 번만 저장되고 Evolution Review Gate가 읽은 뒤 제거한다.",
        "Hub handoff는 `agent-platform-hub-handoff-v0-1`에 한 번만 저장되고 Private Download Hub가 읽은 뒤 제거한다.",
        "Hub에 저장된 버전은 `private_download_hub_to_manual_runner` handoff로 Local Runner에 바로 보낼 수 있다.",
        "Hub에서 다시 실행한 promoted pack은 `promoted_private_version` source로 2회차 Evolution 재검토가 가능하다.",
        "2회차 candidate 생성 시 이전 `promotion_metadata`는 제거되고 diff report에는 허용된 removal로만 남는다.",
        "candidate pack은 자동 적용이 아니라 `candidate_not_applied` preview/export로만 표시된다.",
        "diff report는 자동 승격이 아니라 `review_pass_not_promoted` review gate로만 표시된다.",
        "promoted pack은 공개 배포가 아니라 `promoted_private_version` private export로만 표시된다.",
        "promotion record는 promoted pack hash까지 연결하는 audit record로만 표시된다.",
        "Private Hub로 보내기는 promoted pack과 promotion record를 함께 저장하되, 검증 연결 실패 시 Hub에 verified linked badge를 붙이지 않는다.",
        "Private Download Hub는 저장된 버전에 `진화 N회` 배지를 표시하되, 이 값은 proof가 아니라 `evolution_promoted` provenance count다.",
        "lineage card도 proof나 성공률 주장이 아니라 private audit lineage다.",
        "lineage card 검증 결과는 `private_hub_lineage_card_verifier_v0_1`이며, 검증 실패 시 저장이나 실행을 진행하지 않고 오류만 표시한다.",
        "lineage card 검증 완료와 실패는 모두 Hub storage, promotion audit storage, Runner handoff를 변경하지 않는다.",
        "변조된 lineage card는 content hash, fingerprint, evolution count, audit link 중 하나라도 맞지 않으면 fail로 표시한다.",
        "lineage card가 원문 입력, 원문 결과, secret을 저장한다고 주장하도록 변조되어도 `privacy_boundary_blocked` fail로 표시한다.",
        "lineage card가 proof claim, success rate claim, sale ready를 주장하도록 변조되어도 fail로 표시한다.",
        "lineage card가 `verified linked`를 주장해도 audit fingerprint와 promoted pack hash가 Hub audit과 맞지 않으면 fail로 표시한다.",
        "audit import 전에 받은 stale `not linked` lineage card는 Hub에 verified audit이 생긴 뒤 fail로 표시한다.",
        "Builder Golden Path 완료 receipt는 `external_alpha_builder_gold_path_share_receipt.json`으로 내려받을 수 있으며",
        "receipt는 proof가 아니라 `manual_review_only` metadata로만 표시된다.",
        "Cambrian Runtime을 platform-first 알파의 필수 조건으로 바꾸지 않는다.",
        "provider API key, secret, 비밀번호를 수집하지 않는다.",
        "공개 마켓, 결제, 판매 가능 배지, 성공률, proof claim을 먼저 만들지 않는다.",
    ]:
        if phrase not in platform_doc:
            raise AssertionError(f"방향 고정 문구 누락: {phrase}")


    _check_non_lineage_json_direction(platform_doc)
    _check_lineage_report_contract_direction(platform_doc)


def _check_non_lineage_json_direction(platform_doc: str) -> None:
    """lineage card가 아닌 JSON 업로드 경계 문구를 확인한다."""
    phrase = "agent pack처럼 lineage card가 아닌 valid JSON도 `card_kind` mismatch fail report로 표시하고 Hub/Runner 상태를 변경하지 않는다."
    if phrase not in platform_doc:
        raise AssertionError(f"lineage card 경계 문구 누락: {phrase}")
    phrase = "lineage card가 아닌 JSON의 agent_id, version_label, raw content는 verifier report/status에 echo하지 않고 `unknown`으로 표시한다."
    if phrase not in platform_doc:
        raise AssertionError(f"lineage card 비노출 문구 누락: {phrase}")
    phrase = "배열이나 문자열 같은 non-object JSON도 `lineage card 객체` fail report로 표시하고 원문 값을 echo하지 않는다."
    if phrase not in platform_doc:
        raise AssertionError(f"lineage card non-object 문구 누락: {phrase}")
    phrase = "lineage verifier report는 `effect: report_only`와 `side_effects.hub_storage_write: false`"
    if phrase not in platform_doc:
        raise AssertionError(f"lineage card report-only 문구 누락: {phrase}")


def _check_lineage_report_contract_direction(platform_doc: str) -> None:
    """lineage verifier report 계약 문구를 확인한다."""
    phrase = "lineage verifier report는 `report_kind: private_hub_lineage_card_verifier_report_v0_1`"
    if phrase not in platform_doc:
        raise AssertionError(f"lineage card report contract 문구 누락: {phrase}")


def _check_release_docs() -> None:
    """외부 알파 시작 문서와 RC 문서가 사용 경로를 설명하는지 확인한다."""
    quickstart = _read_text(ROOT / "QUICKSTART_EXTERNAL_ALPHA.md")
    start = _read_text(ROOT / "START_HERE_EXTERNAL_ALPHA.md")
    support_packet = _read_text(ROOT / "EXTERNAL_ALPHA_SUPPORT_PACKET.md")
    guide = _read_text(ROOT / "docs" / "release" / "RC_INSTALL_GUIDE.md")
    release_manifest = _read_text(ROOT / "docs" / "release" / "EXTERNAL_ALPHA_RELEASE_MANIFEST.md")
    for phrase in [
        "Cambrian External Alpha Quickstart",
        "START_CAMBRIAN_AGENT_PLATFORM.bat",
        "Builder Golden Path",
        "external_alpha_builder_gold_path_share_receipt.json",
        "safe_to_share: true",
        "Do not send",
    ]:
        if phrase not in quickstart:
            raise AssertionError(f"QUICKSTART phrase missing: {phrase}")
    for phrase in [
        "QUICKSTART_EXTERNAL_ALPHA.md",
    ]:
        if phrase not in start:
            raise AssertionError(f"START_HERE quickstart phrase missing: {phrase}")
    for phrase in [
        "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
        "START_CAMBRIAN_AGENT_PLATFORM.bat",
        "VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat",
        "COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat",
        "Builder Golden Path",
        "Green 템플릿",
        "manual_no_api",
        "manual_run_receipt_v0_1",
        "manual_review_only",
        "Local Runner로 보내기",
        "agent-platform-runner-handoff-v0-1",
        "single-use handoff",
        "Evolution으로 보내기",
        "agent-platform-evolution-handoff-v0-1",
        "후보 pack 내보내기",
        "candidate_not_applied",
        "diff report 내보내기",
        "review_pass_not_promoted",
        "promoted pack 내보내기",
        "promotion record 내보내기",
        "Private Hub로 보내기",
        "agent-platform-hub-handoff-v0-1",
        "Hub 저장 버전 Runner로 실행",
        "2회차 Evolution 재검토",
        "진화 1회",
        "private_hub_lineage_card_v0_1",
        "private_hub_lineage_card_verifier_v0_1",
        "lineage card 검증 실패",
        "Hub storage, promotion audit storage, Runner handoff",
        "effect: report_only",
        "side_effects.*: false",
        "report_kind: private_hub_lineage_card_verifier_report_v0_1",
        "report_privacy.*: false",
        "깨진 JSON lineage card",
        "card_kind",
        "raw content",
        "non-object JSON",
        "privacy_boundary_blocked",
        "proof claim, success rate claim, sale ready",
        "audit fingerprint",
        "stale `not linked` lineage card",
        "promoted_private_version",
        "python scripts/build_external_alpha_release.py",
        "python scripts/verify_external_alpha_release.py",
        "python scripts/smoke_external_alpha_release_bundle.py",
        "python scripts/smoke_external_alpha_post_send_checkpoint.py",
        "python scripts/smoke_external_alpha_pilot_learning_loop.py",
        "python scripts/prepare_external_alpha_operator_dispatch_packet.py",
        "python scripts/prepare_external_alpha_handoff.py",
        "python scripts/check_external_alpha_send_ready.py",
        "python scripts/check_external_alpha_pilot_ready.py",
        "cambrian-agent-platform-external-alpha-pilot-dispatch.md",
        "python scripts/check_external_alpha_dispatch_record.py",
        "cambrian-agent-platform-external-alpha-dispatch-record.md",
        "python scripts/check_external_alpha_recipient_checkpoint.py",
        "cambrian-agent-platform-external-alpha-recipient-checkpoint.md",
        "python scripts/check_external_alpha_pilot_review.py",
        "cambrian-agent-platform-external-alpha-pilot-review.md",
        "python scripts/check_external_alpha_pilot_evidence.py",
        "cambrian-agent-platform-external-alpha-pilot-evidence.md",
        "python scripts/check_external_alpha_pilot_decision.py",
        "cambrian-agent-platform-external-alpha-pilot-decision.md",
        "python scripts/check_external_alpha_pilot_iteration.py",
        "cambrian-agent-platform-external-alpha-pilot-iteration.md",
        "python scripts/smoke_external_alpha_release_bundle.py",
        "python scripts/smoke_external_alpha_post_send_checkpoint.py",
        "python scripts/smoke_external_alpha_pilot_learning_loop.py",
        "python scripts/prepare_external_alpha_operator_dispatch_packet.py",
        "python scripts/audit_external_alpha_send_chain.py",
        "python scripts/collect_external_alpha_diagnostics.py",
        "python scripts/verify_agent_platform_browser_flow.py",
        "npm install --prefix C:\\tmp\\cambrian-playwright-deps playwright",
        "Defensible Alpha",
        "한국 시장",
        "단순 MVP",
        "web/assets/document-organizer.promoted.agent-pack.json",
        "web/assets/document-organizer.candidate-promotion-record.json",
        "proof, 성능, 성공률 주장",
    ]:
        if phrase not in start:
            raise AssertionError(f"START_HERE 문구 누락: {phrase}")
    if "Agent Platform External Alpha" not in guide:
        raise AssertionError("RC 설치 가이드에 Agent Platform External Alpha 섹션이 필요합니다.")
    for phrase in [
        "External Alpha Support Packet",
        "external_alpha_release_verification_receipt.json",
        "external_alpha_diagnostics.json",
        "safe_to_share: true",
        "redaction_checks",
        "docs/launch/PILOT_ISSUE_INTAKE.md",
        "docs/launch/PILOT_FEEDBACK_FORM.md",
        "Do Not Send",
        "raw AI reply",
    ]:
        if phrase not in support_packet:
            raise AssertionError(f"지원 패킷 문구 누락: {phrase}")
    for phrase in [
        "Defensible Alpha",
        "promotion audit lineage",
        "proof boundary",
        "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
        "python scripts/check_external_alpha_dispatch_record.py",
        "cambrian-agent-platform-external-alpha-dispatch-record.md",
        "python scripts/check_external_alpha_recipient_checkpoint.py",
        "cambrian-agent-platform-external-alpha-recipient-checkpoint.md",
        "python scripts/check_external_alpha_pilot_review.py",
        "cambrian-agent-platform-external-alpha-pilot-review.md",
        "python scripts/check_external_alpha_pilot_evidence.py",
        "cambrian-agent-platform-external-alpha-pilot-evidence.md",
        "python scripts/check_external_alpha_pilot_decision.py",
        "cambrian-agent-platform-external-alpha-pilot-decision.md",
        "python scripts/check_external_alpha_pilot_iteration.py",
        "cambrian-agent-platform-external-alpha-pilot-iteration.md",
        "python scripts/smoke_external_alpha_release_bundle.py",
        "python scripts/smoke_external_alpha_post_send_checkpoint.py",
        "python scripts/smoke_external_alpha_pilot_learning_loop.py",
        "python scripts/prepare_external_alpha_operator_dispatch_packet.py",
        "python scripts/audit_external_alpha_send_chain.py",
        "python scripts/verify_agent_platform_browser_flow.py",
    ]:
        if phrase not in guide:
            raise AssertionError(f"RC 설치 가이드 문구 누락: {phrase}")
    for phrase in [
        "External Alpha Release Manifest",
        "dist/cambrian-agent-platform-external-alpha.zip",
        "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
        "python scripts/check_external_alpha_pilot_review.py",
        "cambrian-agent-platform-external-alpha-pilot-review.json",
        "python scripts/check_external_alpha_pilot_evidence.py",
        "cambrian-agent-platform-external-alpha-pilot-evidence.json",
        "python scripts/check_external_alpha_pilot_decision.py",
        "cambrian-agent-platform-external-alpha-pilot-decision.json",
        "python scripts/check_external_alpha_dispatch_record.py",
        "cambrian-agent-platform-external-alpha-dispatch-record.json",
        "python scripts/check_external_alpha_recipient_checkpoint.py",
        "cambrian-agent-platform-external-alpha-recipient-checkpoint.json",
        "python scripts/check_external_alpha_pilot_iteration.py",
        "cambrian-agent-platform-external-alpha-pilot-iteration.json",
        "python scripts/smoke_external_alpha_release_bundle.py",
        "python scripts/smoke_external_alpha_post_send_checkpoint.py",
        "python scripts/smoke_external_alpha_pilot_learning_loop.py",
        "python scripts/prepare_external_alpha_operator_dispatch_packet.py",
        "python scripts/audit_external_alpha_send_chain.py",
        "scripts/verify_agent_platform_browser_flow.py",
        "EXTERNAL_ALPHA_BUNDLE_MANIFEST.json",
        ".env",
        ".cambrian",
    ]:
        if phrase not in release_manifest:
            raise AssertionError(f"릴리즈 매니페스트 문구 누락: {phrase}")


def _check_readable_text() -> None:
    """주요 파일에 깨진 인코딩 표식이 없는지 확인한다."""
    paths = [
        ROOT / "QUICKSTART_EXTERNAL_ALPHA.md",
        ROOT / "START_HERE_EXTERNAL_ALPHA.md",
        ROOT / "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
        ROOT / "web" / "platform" / "index.html",
        ROOT / "docs" / "platform" / "00_AGENT_PLATFORM_FOUNDATION.md",
    ]
    markers = ["濡", "먯", "꾪", "�"]
    for path in paths:
        text = _read_text(path)
        found = [marker for marker in markers if marker in text]
        if found:
            raise AssertionError(f"{path.name} 인코딩 의심 표식: {', '.join(found)}")


def _check_release_docs() -> None:
    """Verify the external-recipient docs describe the first-use path in readable text."""
    quickstart = _read_text(ROOT / "QUICKSTART_EXTERNAL_ALPHA.md")
    start = _read_text(ROOT / "START_HERE_EXTERNAL_ALPHA.md")
    prompt = _read_text(ROOT / "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md")
    support_packet = _read_text(ROOT / "EXTERNAL_ALPHA_SUPPORT_PACKET.md")
    guide = _read_text(ROOT / "docs" / "release" / "RC_INSTALL_GUIDE.md")
    release_manifest = _read_text(ROOT / "docs" / "release" / "EXTERNAL_ALPHA_RELEASE_MANIFEST.md")

    required_by_file = {
        "QUICKSTART_EXTERNAL_ALPHA.md": [
            "Cambrian External Alpha Quickstart",
            "START_CAMBRIAN_AGENT_PLATFORM.bat",
            "Builder Golden Path",
            "external_alpha_builder_gold_path_share_receipt.json",
            "safe_to_share: true",
            "Do not send",
        ],
        "START_HERE_EXTERNAL_ALPHA.md": [
            "Cambrian Agent Platform External Alpha",
            "QUICKSTART_EXTERNAL_ALPHA.md",
            "Defensible Alpha",
            "Builder Golden Path",
            "manual_no_api",
            "manual_run_receipt_v0_1",
            "promotion audit record",
            "private_download_hub_to_manual_runner",
            "external_alpha_builder_gold_path_share_receipt.json",
            "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
            "EXTERNAL_ALPHA_SUPPORT_PACKET.md",
            "CHECK_RELEASE_CHAIN",
            "release_sources_match_current_manifest",
            "python scripts/audit_external_alpha_send_chain.py",
            "python scripts/check_external_alpha_first_recipient_operator_status.py",
            "CONFIRMED",
        ],
        "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md": [
            "Cambrian Agent Platform Prompt For Codex/Claude",
            "QUICKSTART_EXTERNAL_ALPHA.md",
            ".venv\\Scripts\\python.exe scripts/verify_platform_alpha.py",
            "START_CAMBRIAN_AGENT_PLATFORM.bat",
            "Builder Golden Path",
            "external_alpha_diagnostics.json",
            "CONFIRMED",
            "Do not ask for API keys",
        ],
        "EXTERNAL_ALPHA_SUPPORT_PACKET.md": [
            "External Alpha Support Packet",
            "external_alpha_release_verification_receipt.json",
            "external_alpha_diagnostics.json",
            "external_alpha_builder_gold_path_share_receipt.json",
            "safe_to_share: true",
            "redaction_checks",
            "docs/launch/PILOT_ISSUE_INTAKE.md",
            "docs/launch/PILOT_FEEDBACK_FORM.md",
            "Do Not Send",
            "raw AI replies",
        ],
    }
    texts = {
        "QUICKSTART_EXTERNAL_ALPHA.md": quickstart,
        "START_HERE_EXTERNAL_ALPHA.md": start,
        "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md": prompt,
        "EXTERNAL_ALPHA_SUPPORT_PACKET.md": support_packet,
    }
    for name, phrases in required_by_file.items():
        text = texts[name]
        for phrase in phrases:
            if phrase not in text:
                raise AssertionError(f"{name} phrase missing: {phrase}")

    for phrase in [
        "Agent Platform External Alpha",
        "Defensible Alpha",
        "promotion audit lineage",
        "proof boundary",
        "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
        "python scripts/check_external_alpha_dispatch_record.py",
        "python scripts/check_external_alpha_recipient_checkpoint.py",
        "python scripts/audit_external_alpha_send_chain.py",
        "python scripts/verify_agent_platform_browser_flow.py",
    ]:
        if phrase not in guide:
            raise AssertionError(f"RC install guide phrase missing: {phrase}")

    for phrase in [
        "External Alpha Release Manifest",
        "dist/cambrian-agent-platform-external-alpha.zip",
        "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
        "python scripts/check_external_alpha_dispatch_record.py",
        "python scripts/check_external_alpha_recipient_checkpoint.py",
        "python scripts/check_external_alpha_pilot_iteration.py",
        "scripts/verify_agent_platform_browser_flow.py",
        "EXTERNAL_ALPHA_BUNDLE_MANIFEST.json",
        ".env",
        ".cambrian",
    ]:
        if phrase not in release_manifest:
            raise AssertionError(f"release manifest phrase missing: {phrase}")


def _check_readable_text() -> None:
    """Verify first-recipient entry docs are ASCII and free of common mojibake tokens."""
    user_entry_docs = [
        ROOT / "QUICKSTART_EXTERNAL_ALPHA.md",
        ROOT / "START_HERE_EXTERNAL_ALPHA.md",
        ROOT / "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
        ROOT / "EXTERNAL_ALPHA_SUPPORT_PACKET.md",
    ]
    mojibake_markers = [
        "占",
        "嚥",
        "癒",
        "袁",
        "筌",
        "吏",
        "留",
        "?쒓",
        "?몃",
        "?꾨",
        "?뚰",
        "?뺤",
        "?ㅼ",
    ]
    for path in user_entry_docs:
        text = _read_text(path)
        if not text.isascii():
            raise AssertionError(f"{path.name} must stay ASCII for first-recipient readability")
        found = [marker for marker in mojibake_markers if marker in text]
        if found:
            raise AssertionError(f"{path.name} contains mojibake markers: {', '.join(found)}")


def _assert_report_pass(path: Path, report: dict[str, Any]) -> None:
    """검증 리포트가 pass인지 확인한다."""
    if report.get("status") != "pass":
        errors = json.dumps(report.get("errors", []), ensure_ascii=False)
        raise AssertionError(f"{path.name} 검증 실패: {report.get('status')} {errors}")


def _read_text(path: Path) -> str:
    """UTF-8 텍스트 파일을 읽는다."""
    return path.read_text(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
