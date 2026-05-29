from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "web" / "platform" / "index.html"
RUNNER = ROOT / "web" / "runner" / "index.html"
SAMPLE_PROMOTED = ROOT / "web" / "assets" / "document-organizer.promoted.agent-pack.json"
SAMPLE_PROMOTION_RECORD = ROOT / "web" / "assets" / "document-organizer.candidate-promotion-record.json"


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path and path.exists():
            return path
    return None


def _node_path() -> Path | None:
    env_path = os.environ.get("CAMBRIAN_BROWSER_NODE")
    candidates = [
        Path(env_path) if env_path else None,
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "bin"
        / ("node.exe" if os.name == "nt" else "node"),
    ]
    found = _first_existing([path for path in candidates if path is not None])
    if found:
        return found
    node = shutil.which("node")
    return Path(node) if node else None


def _node_modules_path() -> Path | None:
    env_path = os.environ.get("CAMBRIAN_BROWSER_NODE_MODULES")
    return _first_existing(
        [
            Path(env_path) if env_path else None,
            Path.home()
            / ".cache"
            / "codex-runtimes"
            / "codex-primary-runtime"
            / "dependencies"
            / "node"
            / "node_modules",
        ]
    )


def _chrome_path() -> Path | None:
    env_path = os.environ.get("CAMBRIAN_BROWSER_CHROME")
    program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
    program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    return _first_existing(
        [
            Path(env_path) if env_path else None,
            program_files / "Google" / "Chrome" / "Application" / "chrome.exe",
            program_files_x86 / "Google" / "Chrome" / "Application" / "chrome.exe",
            local_app_data / "Google" / "Chrome" / "Application" / "chrome.exe",
            program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            program_files_x86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            local_app_data / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ]
    )


def _playwright_available(node: Path, node_modules: Path | None) -> bool:
    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    result = subprocess.run(
        [str(node), "-e", "require('playwright')"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    return result.returncode == 0


def _assert_lineage_verifier_receipt_contract(report: dict) -> None:
    assert report["receipt_checksum_algorithm"] == "fnv1a32-stable-json"
    assert report["receipt_checksum_scope"] == "lineage_verifier_report_without_receipt_checksum"
    assert report["receipt_checksum"].startswith("lvr-")
    assert len(report["receipt_checksum"]) == len("lvr-00000000")
    assert report["report_provenance"] == {
        "generated_by": "web/platform/index.html",
        "verifier_input": "uploaded_lineage_card_file",
        "hub_scope": "local_private_download_hub_snapshot",
        "promotion_audit_scope": "local_promotion_audit_snapshot",
        "stores_or_echoes_raw_content": False,
    }


def _assert_lineage_report_receipt_verifier_contract(report: dict) -> None:
    assert report["report_kind"] == "private_hub_lineage_report_receipt_verifier_report_v0_1"
    assert report["report_version"] == "0.1"
    assert report["verifier"] == "private_hub_lineage_report_receipt_verifier_v0_1"
    assert report["effect"] == "report_only"
    assert report["side_effects"] == {
        "hub_storage_write": False,
        "promotion_audit_storage_write": False,
        "runner_handoff_write": False,
        "installs_or_runs_agent": False,
    }
    assert report["report_privacy"] == {
        "stores_raw_report": False,
        "stores_raw_card": False,
        "stores_raw_inputs": False,
        "stores_raw_outputs": False,
        "stores_secrets": False,
        "echoes_non_report_identity": False,
    }
    assert report["report_provenance"] == {
        "generated_by": "web/platform/index.html",
        "verifier_input": "uploaded_lineage_verifier_report_file",
        "hub_scope": "not_read",
        "promotion_audit_scope": "not_read",
        "stores_or_echoes_raw_content": False,
    }


def test_builder_conversation_recommends_template_and_updates_workspace() -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")

    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#builderIntentInput').fill('회의 메모에서 결정사항과 담당자별 할 일을 뽑아줘');
  await page.locator('#generateSuggestionsButton').click();

  const templateValue = await page.locator('#templatePicker').inputValue();
  const agentName = await page.locator('#agentName').inputValue();
  const workspaceAgentName = await page.locator('#workspaceAgentName').innerText();
  const plainAgentName = await page.locator('#plainAgentName').innerText();
  const conversationStatus = await page.locator('#conversationStatus').innerText();
  const aiGatewayStatus = await page.locator('#aiGatewayStatus').evaluate((node) => node.textContent);
  const aiGatewayQuestion = await page.locator('#aiGatewayQuestion').innerText();
  const aiGatewaySuggestions = await page.locator('#aiGatewaySuggestions').evaluate((node) => node.textContent);
  const aiGatewayPatchStatus = await page.locator('#aiGatewayPatchStatus').evaluate((node) => node.textContent);
  const conversationBuildStatus = await page.locator('#conversationBuildStatus').innerText();
  const firstFollowupChoiceBefore = await page.locator('#followupChoiceRow button').first().innerText();
  const buildButtonTextBeforeChoice = await page.locator('#buildConversationAgentButton').innerText();
  const downloadDisabledBeforeChoice = await page.locator('#downloadConversationPackButton').isDisabled();
  const runDisabledBeforeChoice = await page.locator('#runConversationAgentButton').isDisabled();
  const sparseReadiness = await page.evaluate(() => evaluateConversationReadiness('document_organizer', '정리해줘', ''));
  const readyReadiness = await page.evaluate(() => evaluateConversationReadiness(
    'meeting_notes',
    '회의 메모에서 결정사항과 담당자별 할 일을 뽑아줘',
    '팀 공유용 Markdown 회의록으로, 결정 사항과 담당자별 할 일을 먼저 보여줘. 마감일은 확인 필요로 표시해줘.'
  ));
  const buildRequest = await page.evaluate(() => buildAiBuilderRequest('meeting_notes'));
  await page.locator('#followupChoiceRow button').filter({{ hasText: 'Markdown' }}).click();
  const followupAfterChoice = await page.locator('#builderFollowupInput').inputValue();
  const buildStatusAfterChoice = await page.locator('#conversationBuildStatus').innerText();
  const buildButtonTextAfterChoice = await page.locator('#buildConversationAgentButton').innerText();
  const downloadDisabledAfterChoice = await page.locator('#downloadConversationPackButton').isDisabled();
  const runDisabledAfterChoice = await page.locator('#runConversationAgentButton').isDisabled();
  const workspaceSampleAfterChoice = await page.locator('#workspaceSampleInput').inputValue();
  const workspaceStatusAfterChoice = await page.locator('#workspaceSimulationStatus').innerText();
  const plainGoalAfterChoice = await page.locator('#plainAgentGoal').innerText();
  const plainSummaryAfterChoice = await page.locator('#plainAgentSummary').innerText();
  const outputFormatAfterChoice = await page.locator('#outputFormat').inputValue();
  await page.locator('#simulateWorkspaceButton').click();
  const workspaceOutputAfterChoice = await page.locator('#workspaceSimulationOutput').evaluate((node) => node.textContent);
  const workspaceCardsAfterChoice = await page.locator('#workspaceResultCards').innerText();
  const choiceLabelsAfterReady = await page.locator('#followupChoiceRow button').evaluateAll((nodes) => nodes.map((node) => node.textContent));
  const requestAfterChoice = await page.evaluate(() => buildAiBuilderRequest('meeting_notes'));
  const blockedPatch = await page.evaluate(() => validateAiBuilderResponse({{
    contract_patch: {{
      permissions: ['network_send'],
      proof_claim_allowed: true,
    }},
  }}));
  const selected = await page.locator('[data-template-choice="meeting_notes"]').getAttribute('aria-pressed');
  const role = await page.locator('#role').inputValue();

  await browser.close();
  console.log(JSON.stringify({{
    templateValue,
    agentName,
    workspaceAgentName,
    plainAgentName,
    conversationStatus,
    aiGatewayStatus,
    aiGatewayQuestion,
    aiGatewaySuggestions,
    aiGatewayPatchStatus,
    conversationBuildStatus,
    firstFollowupChoiceBefore,
    buildButtonTextBeforeChoice,
    downloadDisabledBeforeChoice,
    runDisabledBeforeChoice,
    sparseReadiness,
    readyReadiness,
    buildRequest,
    followupAfterChoice,
    buildStatusAfterChoice,
    buildButtonTextAfterChoice,
    downloadDisabledAfterChoice,
    runDisabledAfterChoice,
    workspaceSampleAfterChoice,
    workspaceStatusAfterChoice,
    plainGoalAfterChoice,
    plainSummaryAfterChoice,
    outputFormatAfterChoice,
    workspaceOutputAfterChoice,
    workspaceCardsAfterChoice,
    choiceLabelsAfterReady,
    requestAfterChoice,
    blockedPatch,
    selected,
    role,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["templateValue"] == "meeting_notes"
    assert payload["agentName"] == "회의록 정리 에이전트"
    assert payload["workspaceAgentName"] == "회의록 정리 에이전트"
    assert payload["plainAgentName"] == "회의록 정리 에이전트"
    assert "회의록 정리 에이전트" in payload["conversationStatus"]
    assert "/api/builder/guide" in payload["aiGatewayStatus"]
    assert "키는 브라우저에 저장하지 않음" in payload["aiGatewayStatus"]
    assert "local_template_recommendation" in payload["aiGatewayStatus"]
    assert "회의록 정리 에이전트" in payload["aiGatewayQuestion"]
    assert "추천 보기: 회의록 정리 에이전트" in payload["aiGatewaySuggestions"]
    assert "위험 경고" in payload["aiGatewaySuggestions"]
    assert "다음 선택" in payload["aiGatewaySuggestions"]
    assert "contract_patch 검증 통과" in payload["aiGatewayPatchStatus"]
    assert "계약 준비도" in payload["conversationBuildStatus"]
    assert payload["firstFollowupChoiceBefore"] == "Markdown"
    assert payload["buildButtonTextBeforeChoice"] == "초안 생성"
    assert payload["downloadDisabledBeforeChoice"] is True
    assert payload["runDisabledBeforeChoice"] is True
    assert payload["sparseReadiness"]["status"] == "needs_more_detail"
    assert "사용처" in payload["sparseReadiness"]["missing_labels"]
    assert payload["readyReadiness"]["status"] == "ready_to_build"
    assert payload["readyReadiness"]["score"] == payload["readyReadiness"]["total"]
    assert payload["buildRequest"]["followup_answer"]
    assert payload["buildRequest"]["readiness_snapshot"]["status"] == "needs_more_detail"
    assert "결과 형식" in payload["buildRequest"]["readiness_snapshot"]["missing_labels"]
    assert "결과 형식은 Markdown" in payload["followupAfterChoice"]
    assert "계약 준비도 5/5" in payload["buildStatusAfterChoice"]
    assert payload["buildButtonTextAfterChoice"] == "에이전트 생성"
    assert payload["downloadDisabledAfterChoice"] is False
    assert payload["runDisabledAfterChoice"] is False
    assert "선택 답변:" in payload["workspaceSampleAfterChoice"]
    assert "결과 형식은 Markdown" in payload["workspaceSampleAfterChoice"]
    assert "출력 형식: Markdown 요약" in payload["workspaceSampleAfterChoice"]
    assert "계약 준비도 완료" in payload["workspaceSampleAfterChoice"]
    assert payload["workspaceStatusAfterChoice"] == "샘플 준비"
    assert "결과 형식은 Markdown" in payload["plainGoalAfterChoice"]
    assert "생성 준비가 끝났습니다" in payload["plainSummaryAfterChoice"]
    assert payload["outputFormatAfterChoice"] == "markdown_summary"
    assert "선택 형식: Markdown 요약" in payload["workspaceOutputAfterChoice"]
    assert "## 결정 사항" in payload["workspaceOutputAfterChoice"]
    assert "출력 형식" in payload["workspaceCardsAfterChoice"]
    assert "Markdown 요약" in payload["workspaceCardsAfterChoice"]
    assert "샘플 실행" in payload["choiceLabelsAfterReady"]
    assert payload["requestAfterChoice"]["readiness_snapshot"]["status"] == "ready_to_build"
    assert payload["blockedPatch"]["status"] == "blocked"
    assert any("permissions" in error for error in payload["blockedPatch"]["errors"])
    assert any("network_send" in error for error in payload["blockedPatch"]["errors"])
    assert any("proof_claim_allowed" in error for error in payload["blockedPatch"]["errors"])
    assert payload["selected"] == "true"
    assert "회의" in payload["role"]


def test_conversation_builder_creates_and_downloads_agent_pack() -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")

    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');
const fs = require('fs');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const context = await browser.newContext({{ acceptDownloads: true }});
  const page = await context.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#builderIntentInput').fill('회의 메모에서 결정사항과 담당자별 할 일을 뽑아줘');
  await page.locator('#generateSuggestionsButton').click();
  await page.locator('#builderFollowupInput').fill('팀 공유용 Markdown 회의록으로, 결정 사항과 담당자별 할 일을 먼저 보여줘');
  await page.locator('#buildConversationAgentButton').click();

  const buildStatus = await page.locator('#conversationBuildStatus').innerText();
  const goal = await page.locator('#goal').inputValue();
  const validation = await page.locator('#validation').inputValue();
  const downloadPromise = page.waitForEvent('download');
  await page.locator('#downloadConversationPackButton').click();
  const download = await downloadPromise;
  const downloadPath = await download.path();
  const bundle = JSON.parse(fs.readFileSync(downloadPath, 'utf8'));

  await browser.close();
  console.log(JSON.stringify({{
    suggestedFilename: download.suggestedFilename(),
    buildStatus,
    goal,
    validation,
    bundleSchema: bundle.bundle_schema,
    agentName: bundle.files['agent.json'].name,
    agentId: bundle.files['agent.json'].agent_id,
    downloadedOutputs: bundle.files['agent.json'].outputs,
    downloadedGoal: bundle.files['agent.json'].goals.join('\\n'),
    downloadedValidation: bundle.files['agent.json'].validation_criteria.join('\\n'),
    cambrianRequired: bundle.files['manifest.json'].runtime.cambrian_required,
    proofClaimAllowed: bundle.files['manifest.json'].marketplace.proof_claim_allowed,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["suggestedFilename"] == "meeting-notes-organizer.agent-pack.json"
    assert "회의록 정리 에이전트 생성 완료" in payload["buildStatus"]
    assert "계약 준비도" in payload["buildStatus"]
    assert payload["bundleSchema"] == "agent_pack_bundle_v0_1"
    assert payload["agentName"] == "회의록 정리 에이전트"
    assert payload["agentId"] == "meeting-notes-organizer"
    assert payload["downloadedOutputs"] == ["markdown_summary"]
    assert "팀 공유용 Markdown 회의록" in payload["goal"]
    assert "팀 공유용 Markdown 회의록" in payload["downloadedGoal"]
    assert "계약 준비도: 5/5" in payload["goal"]
    assert "계약 준비도: 5/5" in payload["downloadedGoal"]
    assert "사용자 의도와 다른 사실은 확인 필요" in payload["validation"]
    assert "사용자 의도와 다른 사실은 확인 필요" in payload["downloadedValidation"]
    assert "추가 확인: 없음" in payload["downloadedValidation"]
    assert payload["cambrianRequired"] is False
    assert payload["proofClaimAllowed"] is False


def test_downloaded_conversation_pack_reopens_in_runner_file_loader(tmp_path: Path) -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")

    saved_pack = tmp_path / "meeting-notes-organizer.agent-pack.json"
    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const context = await browser.newContext({{ acceptDownloads: true }});
  const builder = await context.newPage();
  await builder.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await builder.locator('#builderIntentInput').fill('회의 메모에서 결정사항과 담당자별 할 일을 뽑아줘');
  await builder.locator('#generateSuggestionsButton').click();
  await builder.locator('#followupChoiceRow button').filter({{ hasText: '표' }}).click();
  await builder.locator('#buildConversationAgentButton').click();
  const downloadPromise = builder.waitForEvent('download');
  await builder.locator('#downloadConversationPackButton').click();
  const download = await downloadPromise;
  await download.saveAs({json.dumps(str(saved_pack))});

  const runner = await context.newPage();
  await runner.goto(pathToFileURL({json.dumps(str(RUNNER))}).href);
  await runner.locator('#packInput').setInputFiles({json.dumps(str(saved_pack))});
  await runner.waitForFunction(() => document.querySelector('#loadStatus').innerText.includes('client preflight: pass'));

  const loadStatus = await runner.locator('#loadStatus').innerText();
  const summary = await runner.locator('#packSummary').innerText();
  const fileSummary = await runner.locator('#handoffSummary').innerText();
  const gateStatus = await runner.locator('#gateStatus').innerText();
  const buildPromptDisabled = await runner.locator('#buildPromptButton').isDisabled();
  await runner.locator('#taskInput').fill('회의 메모를 표로 정리해줘.');
  await runner.locator('#buildPromptButton').click();
  const prompt = await runner.locator('#promptOutput').inputValue();
  await runner.locator('#resultInput').fill('결정 사항은 베타 안내 문서 정리입니다. 담당자는 민수입니다.');
  await runner.locator('#reviewButton').click();
  const missingGateStatus = await runner.locator('#gateStatus').innerText();
  const missingCheckList = await runner.locator('#checkList').innerText();
  await runner.locator('#resultInput').fill('| 구분 | 내용 | 확인 |\\n| --- | --- | --- |\\n| 결정 사항 | 베타 안내 문서 정리 | 통과 |');
  await runner.locator('#reviewButton').click();
  const checkList = await runner.locator('#checkList').innerText();
  const reviewGateStatus = await runner.locator('#gateStatus').innerText();
  await runner.locator('#saveRunButton').click();
  const historyList = await runner.locator('#historyList').innerText();
  const historyRecord = await runner.evaluate(() => JSON.parse(localStorage.getItem('agent-platform-manual-runner-v0-1'))[0]);

  await browser.close();
  console.log(JSON.stringify({{
    suggestedFilename: download.suggestedFilename(),
    loadStatus,
    summary,
    fileSummary,
    gateStatus,
    buildPromptDisabled,
    prompt,
    missingGateStatus,
    missingCheckList,
    checkList,
    reviewGateStatus,
    historyList,
    historyRecord,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["suggestedFilename"] == "meeting-notes-organizer.agent-pack.json"
    assert "meeting-notes-organizer.agent-pack.json" in payload["loadStatus"]
    assert "client preflight: pass" in payload["loadStatus"]
    assert "다음: 작업 입력을 붙이고 실행 프롬프트 생성을 누르세요." in payload["loadStatus"]
    assert "source" in payload["summary"]
    assert "meeting-notes-organizer.agent-pack.json" in payload["summary"]
    assert "next" in payload["summary"]
    assert "작업 입력 → 실행 프롬프트 생성 → AI 결과 붙여넣기 → 검토 완료 + 영수증" in payload["summary"]
    assert "Agent pack" in payload["fileSummary"]
    assert "meeting-notes-organizer.agent-pack.json" in payload["fileSummary"]
    assert "client preflight" in payload["fileSummary"]
    assert "pass" in payload["fileSummary"]
    assert "manual_no_api" in payload["fileSummary"]
    assert "generated_by" in payload["fileSummary"]
    assert "web/platform/index.html" in payload["fileSummary"]
    assert "builder_private_draft" in payload["fileSummary"]
    assert "cambrian_required false" in payload["fileSummary"]
    assert "forbidden_by_default" in payload["fileSummary"]
    assert "api key" in payload["fileSummary"]
    assert "false" in payload["fileSummary"]
    assert "no_runtime_evidence" in payload["fileSummary"]
    assert "proof false" in payload["fileSummary"]
    assert "sale false" in payload["fileSummary"]
    assert "수동 실행 가능 상태" in payload["gateStatus"]
    assert payload["buildPromptDisabled"] is False
    assert "outputs: table" in payload["prompt"]
    assert "계약 출력 형식: table" in payload["prompt"]
    assert "계약 출력 형식(table)을 결과가 지켰는지 확인" in payload["checkList"]
    assert "형식 신호 부족: table" in payload["missingCheckList"]
    assert "형식 신호 0/1 감지, 부족: table" in payload["missingGateStatus"]
    assert "형식 신호 감지: table" in payload["checkList"]
    assert "proof 아님" in payload["checkList"]
    assert "형식 신호 1/1 감지" in payload["reviewGateStatus"]
    assert "proof가 아니라 수동 검토 보조" in payload["reviewGateStatus"]
    assert "format 1/1" in payload["historyList"]
    assert payload["historyRecord"]["format_signal_total"] == 1
    assert payload["historyRecord"]["format_signal_found"] == 1
    assert payload["historyRecord"]["format_signal_missing"] == []
    assert payload["historyRecord"]["stores_raw_outputs"] is False


def test_runner_evolution_suggests_instruction_fix_when_output_format_signal_is_missing() -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")

    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#builderIntentInput').fill('회의 메모에서 결정사항과 담당자별 할 일을 뽑아줘');
  await page.locator('#generateSuggestionsButton').click();
  await page.locator('#followupChoiceRow button').filter({{ hasText: '표' }}).click();
  await page.locator('#runConversationAgentButton').click();
  await page.waitForURL(/runner\\/index\\.html\\?handoff=builder/);
  await page.waitForFunction(() => document.querySelector('#loadStatus').innerText.includes('Builder handoff'));

  await page.locator('#taskInput').fill('회의 메모를 표 형식으로 정리해줘.');
  await page.locator('#buildPromptButton').click();
  await page.locator('#resultInput').fill('SHOULD_NOT_ECHO_FORMAT_RAW_11d3 결정 사항은 베타 안내 문서 정리입니다. 담당자는 민수입니다.');
  await page.locator('#sendEvolutionButton').click();

  await page.waitForURL(/evolution\\/index\\.html\\?handoff=runner/);
  await page.waitForFunction(() => document.querySelector('#loadStatus').innerText.includes('Runner handoff'));
  const loadStatus = await page.locator('#loadStatus').innerText();
  const summary = await page.locator('#summaryList').innerText();
  const runnerHandoffSummary = await page.locator('#runnerHandoffSummary').innerText();
  const recommendations = await page.locator('#recommendationList').innerText();
  const handoffLeft = await page.evaluate(() => localStorage.getItem('agent-platform-evolution-handoff-v0-1'));
  const noteCount = await page.locator('[data-note]').count();
  for (let index = 0; index < noteCount; index += 1) {{
    await page.locator('[data-note]').nth(index).fill(`형식 신호 부족 추천 검토 ${{index + 1}}`);
  }}
  await page.waitForFunction(() => document.querySelector('#candidatePreview').innerText.includes('승인 연결'));
  const livePreviewStatus = await page.locator('#candidateStatus').innerText();
  const livePreviewInitial = await page.locator('#candidatePreview').innerText();
  const formatCard = page.locator('.recommendation').filter({{ hasText: '계약 출력 형식 신호를 instructions에 고정' }});
  await formatCard.locator('[data-decision]').selectOption('rejected');
  await page.waitForFunction(() => !document.querySelector('#candidatePreview').innerText.includes('계약 출력 형식 신호를 instructions에 고정'));
  const livePreviewAfterReject = await page.locator('#candidatePreview').innerText();
  await formatCard.locator('[data-decision]').selectOption('approved');
  await page.waitForFunction(() => document.querySelector('#candidatePreview').innerText.includes('계약 출력 형식 신호를 instructions에 고정'));
  const livePreviewAfterApprove = await page.locator('#candidatePreview').innerText();
  const downloadPromise = page.waitForEvent('download');
  await page.locator('#exportCandidateButton').click();
  const download = await downloadPromise;
  const candidate = JSON.parse(require('fs').readFileSync(await download.path(), 'utf8'));
  const candidateStatus = await page.locator('#candidateStatus').innerText();
  const candidatePreview = await page.locator('#candidatePreview').innerText();
  const candidateInstructions = candidate.files['instructions.md'];

  await browser.close();
  console.log(JSON.stringify({{
    loadStatus,
    summary,
    runnerHandoffSummary,
    recommendations,
    handoffLeft,
    livePreviewStatus,
    livePreviewInitial,
    livePreviewAfterReject,
    livePreviewAfterApprove,
    candidateStatus,
    candidatePreview,
    candidateInstructions,
    candidateApprovedRecommendations: candidate.candidate_metadata.approved_recommendation_ids,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    combined = f"{payload['summary']}\n{payload['recommendations']}"
    assert "Runner handoff를 불러왔습니다" in payload["loadStatus"]
    assert "meeting-notes-organizer" in payload["summary"]
    assert "Runner handoff" in payload["runnerHandoffSummary"]
    assert "manual_runner_to_evolution_review" in payload["runnerHandoffSummary"]
    assert "single use" in payload["runnerHandoffSummary"]
    assert "true" in payload["runnerHandoffSummary"]
    assert "server sync" in payload["runnerHandoffSummary"]
    assert "runtime send" in payload["runnerHandoffSummary"]
    assert "false" in payload["runnerHandoffSummary"]
    assert "api key" in payload["runnerHandoffSummary"]
    assert "secrets" in payload["runnerHandoffSummary"]
    assert "raw inputs" in payload["runnerHandoffSummary"]
    assert "raw outputs" in payload["runnerHandoffSummary"]
    assert "no_runtime_evidence" in payload["runnerHandoffSummary"]
    assert "proof false" in payload["runnerHandoffSummary"]
    assert "success rate false" in payload["runnerHandoffSummary"]
    assert "sale false" in payload["runnerHandoffSummary"]
    assert "manual_no_api" in payload["runnerHandoffSummary"]
    assert "user approval true" in payload["runnerHandoffSummary"]
    assert "계약 출력 형식 신호를 instructions에 고정" in payload["recommendations"]
    assert "부족 형식은 table" in payload["recommendations"]
    assert "원문 결과를 저장하지 않고 수동 검토 메타데이터만 사용" in payload["recommendations"]
    assert "SHOULD_NOT_ECHO_FORMAT_RAW_11d3" not in combined
    assert payload["handoffLeft"] is None
    assert "승인 연결" in payload["livePreviewInitial"]
    assert "계약 출력 형식 신호를 instructions에 고정" in payload["livePreviewInitial"]
    assert "현재 리뷰 결정으로 candidate preview를 갱신" in payload["livePreviewStatus"]
    assert "계약 출력 형식 신호를 instructions에 고정" not in payload["livePreviewAfterReject"]
    assert "계약 출력 형식 신호를 instructions에 고정" in payload["livePreviewAfterApprove"]
    assert "candidate agent pack을 내보냈습니다" in payload["candidateStatus"]
    assert "전후 비교" in payload["candidatePreview"]
    assert "승인 연결" in payload["candidatePreview"]
    assert "evo_3" in payload["candidatePreview"]
    assert "계약 출력 형식 신호를 instructions에 고정" in payload["candidatePreview"]
    assert "instructions.md" in payload["candidatePreview"]
    assert "diff pending" in payload["candidatePreview"]
    assert "diff report 생성 전입니다" in payload["candidatePreview"]
    assert "automatic_candidate_promotion" in payload["candidatePreview"]
    assert "SHOULD_NOT_ECHO_FORMAT_RAW_11d3" not in payload["candidatePreview"]
    assert "## 승인된 instructions 진화 제안" in payload["candidateInstructions"]
    assert "계약 출력 형식 신호를 instructions에 고정" in payload["candidateInstructions"]
    assert "table 출력 형식을 시작 구조와 예시로 고정" in payload["candidateInstructions"]
    assert "SHOULD_NOT_ECHO_FORMAT_RAW_11d3" not in payload["candidateInstructions"]
    assert "evo_3" in payload["candidateApprovedRecommendations"]


def test_conversation_builder_sends_generated_agent_to_runner() -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")

    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#builderIntentInput').fill('회의 메모에서 결정사항과 담당자별 할 일을 뽑아줘');
  await page.locator('#generateSuggestionsButton').click();
  await page.locator('#builderFollowupInput').fill('팀 공유용 Markdown 회의록으로, 결정 사항과 담당자별 할 일을 먼저 보여줘');
  await page.locator('#runConversationAgentButton').click();
  await page.waitForURL(/runner\\/index\\.html\\?handoff=builder/);
  await page.waitForFunction(() => document.querySelector('#loadStatus').innerText.includes('Builder handoff'));

  const url = page.url();
  const loadStatus = await page.locator('#loadStatus').innerText();
  const summary = await page.locator('#packSummary').innerText();
  const handoffLeft = await page.evaluate(() => localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const buildPromptDisabled = await page.locator('#buildPromptButton').isDisabled();
  await page.locator('#taskInput').fill('회의 메모를 팀 공유용으로 정리해줘.');
  await page.locator('#buildPromptButton').click();
  const prompt = await page.locator('#promptOutput').inputValue();

  await browser.close();
  console.log(JSON.stringify({{
    url,
    loadStatus,
    summary,
    handoffLeft,
    buildPromptDisabled,
    prompt,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert "runner/index.html?handoff=builder" in payload["url"]
    assert "Builder handoff를 불러왔습니다" in payload["loadStatus"]
    assert "meeting-notes-organizer" in payload["summary"]
    assert payload["handoffLeft"] is None
    assert payload["buildPromptDisabled"] is False
    assert "팀 공유용 Markdown 회의록" in payload["prompt"]
    assert "outputs: markdown_summary" in payload["prompt"]
    assert "계약 출력 형식: markdown_summary" in payload["prompt"]
    assert "runner_mode: manual_no_api" in payload["prompt"]
    assert "proof_claim_allowed: false" in payload["prompt"]


def test_conversation_output_choices_reach_pack_and_runner_prompt() -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")

    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');
const fs = require('fs');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const context = await browser.newContext({{ acceptDownloads: true }});
  const cases = [
    {{
      choice: '표',
      expectedOutput: 'table',
      expectedLabel: '표 형식',
      expectedLine: '| 구분 | 내용 | 확인 |',
    }},
    {{
      choice: '체크리스트',
      expectedOutput: 'checklist',
      expectedLabel: '체크리스트',
      expectedLine: '- [ ] 결정 사항 확인',
    }},
  ];
  const results = [];

  for (const item of cases) {{
    const page = await context.newPage();
    await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);
    await page.locator('#builderIntentInput').fill('회의 메모에서 결정사항과 담당자별 할 일을 뽑아줘');
    await page.locator('#generateSuggestionsButton').click();
    await page.locator('#followupChoiceRow button').filter({{ hasText: item.choice }}).click();

    const outputFormat = await page.locator('#outputFormat').inputValue();
    const workspaceSample = await page.locator('#workspaceSampleInput').inputValue();
    await page.locator('#simulateWorkspaceButton').click();
    const workspaceOutput = await page.locator('#workspaceSimulationOutput').evaluate((node) => node.textContent);
    const workspaceCards = await page.locator('#workspaceResultCards').innerText();

    await page.locator('#buildConversationAgentButton').click();
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#downloadConversationPackButton').click();
    const download = await downloadPromise;
    const bundle = JSON.parse(fs.readFileSync(await download.path(), 'utf8'));

    await page.locator('#runConversationAgentButton').click();
    await page.waitForURL(/runner\\/index\\.html\\?handoff=builder/);
    await page.waitForFunction(() => document.querySelector('#loadStatus').innerText.includes('Builder handoff'));
    await page.locator('#taskInput').fill('회의 메모를 팀 공유용으로 정리해줘.');
    await page.locator('#buildPromptButton').click();
    const prompt = await page.locator('#promptOutput').inputValue();

    results.push({{
      choice: item.choice,
      expectedOutput: item.expectedOutput,
      expectedLabel: item.expectedLabel,
      expectedLine: item.expectedLine,
      outputFormat,
      workspaceSample,
      workspaceOutput,
      workspaceCards,
      downloadedOutputs: bundle.files['agent.json'].outputs,
      prompt,
    }});
    await page.close();
  }}

  await browser.close();
  console.log(JSON.stringify(results));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert len(payload) == 2
    for item in payload:
        assert item["outputFormat"] == item["expectedOutput"]
        assert item["downloadedOutputs"] == [item["expectedOutput"]]
        assert f"출력 형식: {item['expectedLabel']}" in item["workspaceSample"]
        assert f"선택 형식: {item['expectedLabel']}" in item["workspaceOutput"]
        assert item["expectedLine"] in item["workspaceOutput"]
        assert "출력 형식" in item["workspaceCards"]
        assert item["expectedLabel"] in item["workspaceCards"]
        assert f"outputs: {item['expectedOutput']}" in item["prompt"]
        assert f"계약 출력 형식: {item['expectedOutput']}" in item["prompt"]


def test_conversation_runner_completes_manual_result_receipt_download() -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")

    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');
const fs = require('fs');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const context = await browser.newContext({{ acceptDownloads: true }});
  const page = await context.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#builderIntentInput').fill('회의 메모에서 결정사항과 담당자별 할 일을 뽑아줘');
  await page.locator('#generateSuggestionsButton').click();
  await page.locator('#builderFollowupInput').fill('팀 공유용 Markdown 회의록으로, 결정 사항과 담당자별 할 일을 먼저 보여줘');
  await page.locator('#runConversationAgentButton').click();
  await page.waitForURL(/runner\\/index\\.html\\?handoff=builder/);
  await page.waitForFunction(() => document.querySelector('#loadStatus').innerText.includes('Builder handoff'));

  const completeRunDisabled = await page.locator('#completeRunButton').isDisabled();
  await page.locator('#taskInput').fill('회의 메모를 팀 공유용으로 정리해줘.');
  await page.locator('#buildPromptButton').click();
  await page.locator('#resultInput').fill('결정 사항: SHOULD_NOT_STORE_RAW_RESULT_7f9a\\n담당자: 민수, 지연\\n확인 필요: 마감일');

  const downloadPromise = page.waitForEvent('download');
  await page.locator('#completeRunButton').click();
  const download = await downloadPromise;
  const receiptPath = await download.path();
  const receipt = JSON.parse(fs.readFileSync(receiptPath, 'utf8'));
  const gateStatus = await page.locator('#gateStatus').innerText();
  const checkList = await page.locator('#checkList').innerText();
  const historyList = await page.locator('#historyList').innerText();
  const historyRaw = await page.evaluate(() => localStorage.getItem('agent-platform-manual-runner-v0-1'));
  const historyRecord = JSON.parse(historyRaw)[0];

  await browser.close();
  console.log(JSON.stringify({{
    completeRunDisabled,
    suggestedFilename: download.suggestedFilename(),
    gateStatus,
    checkList,
    historyList,
    historyRaw,
    historyRecord,
    receipt,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    receipt = payload["receipt"]
    assert payload["completeRunDisabled"] is False
    assert payload["suggestedFilename"] == "meeting-notes-organizer-manual-run-receipt.json"
    assert "manual_run_receipt_v0_1" in payload["gateStatus"]
    assert "manual_check_1" in payload["checkList"]
    assert "계약 출력 형식(markdown_summary)을 결과가 지켰는지 확인" in payload["checkList"]
    assert "meeting-notes-organizer" in payload["historyList"]
    assert "checks " in payload["historyList"]
    assert "format 0/1 missing markdown_summary" in payload["historyList"]
    assert "SHOULD_NOT_STORE_RAW_RESULT_7f9a" not in payload["historyRaw"]
    assert receipt["receipt_kind"] == "manual_run_receipt_v0_1"
    assert receipt["runner_mode"] == "manual_no_api"
    assert receipt["agent_id"] == "meeting-notes-organizer"
    assert receipt["result_status"] == "result_pasted_for_manual_review"
    assert receipt["prompt_status"] == "prompt_generated"
    assert receipt["input_summary"]["stores_raw_input"] is False
    assert receipt["output_summary"]["stores_raw_output"] is False
    assert receipt["output_summary"]["output_length"] > 0
    assert receipt["manual_checks"][0]["id"] == "manual_check_1"
    assert receipt["manual_checks"][0]["criterion"] == "계약 출력 형식(markdown_summary)을 결과가 지켰는지 확인"
    assert receipt["manual_checks"][0]["status"] == "user_review_required"
    assert payload["historyRecord"]["manual_check_count"] == len(receipt["manual_checks"])
    assert payload["historyRecord"]["criteria_count"] == len(receipt["manual_checks"])
    assert payload["historyRecord"]["format_signal_total"] == 1
    assert payload["historyRecord"]["format_signal_found"] == 0
    assert payload["historyRecord"]["format_signal_missing"] == ["markdown_summary"]
    assert payload["historyRecord"]["stores_raw_outputs"] is False
    assert receipt["proof_boundary"]["proof_claim_allowed"] is False
    assert receipt["evolution_signal"]["eligible_for_suggestion"] is True


def test_ai_builder_gateway_client_uses_server_when_enabled_and_falls_back_safely() -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")

    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.evaluate(() => {{
    window.CAMBRIAN_AI_BUILDER_GATEWAY_ENABLED = true;
    window.__builderGatewayCalls = [];
    window.fetch = async (url, options) => {{
      window.__builderGatewayCalls.push({{
        url,
        method: options.method,
        body: JSON.parse(options.body),
      }});
      return {{
        ok: true,
        status: 200,
        json: async () => ({{
          assistant_question: '서버 gateway 질문: 어떤 결과 형식을 원하나요?',
          template_recommendations: [
            {{ template_id: 'meeting_notes', reason: '회의 의도와 담당자 추출이 감지되었습니다.' }},
          ],
          contract_patch: {{
            role: '회의 메모를 결정 사항과 담당자별 할 일로 정리한다.',
            goal: '사용자가 검토할 수 있는 회의록 초안을 만든다.',
            output_format: 'meeting_minutes',
            validation: '담당자와 마감일이 불명확하면 확인 필요로 표시한다.',
          }},
          risk_warnings: ['서버 응답도 자동 실행과 proof 주장을 허용하지 않습니다.'],
          next_action_choices: ['워크스페이스에서 샘플 실행'],
        }}),
      }};
    }};
  }});

  await page.locator('#builderIntentInput').fill('회의 메모에서 결정사항과 담당자별 할 일을 뽑아줘');
  await page.locator('#generateSuggestionsButton').click();
  await page.waitForFunction(() => document.querySelector('#aiGatewayQuestion').innerText.includes('서버 gateway 질문'));

  const gatewayCall = await page.evaluate(() => window.__builderGatewayCalls[0]);
  const gatewayStatus = await page.locator('#aiGatewayStatus').evaluate((node) => node.textContent);
  const gatewayQuestion = await page.locator('#aiGatewayQuestion').innerText();
  const gatewaySuggestions = await page.locator('#aiGatewaySuggestions').evaluate((node) => node.textContent);
  const gatewayPatchStatus = await page.locator('#aiGatewayPatchStatus').evaluate((node) => node.textContent);

  const blockedResult = await page.evaluate(async () => {{
    window.fetch = async () => ({{
      ok: true,
      status: 200,
      json: async () => ({{
        contract_patch: {{
          permissions: ['network_send'],
          proof_claim_allowed: true,
        }},
      }}),
    }});
    return requestAiBuilderGuidance('document_organizer', {{ forceGateway: true }});
  }});
  const blockedPatchStatus = await page.locator('#aiGatewayPatchStatus').evaluate((node) => node.textContent);

  const fallbackResult = await page.evaluate(async () => {{
    window.fetch = async () => {{
      throw new Error('offline');
    }};
    return requestAiBuilderGuidance('document_organizer', {{ forceGateway: true }});
  }});
  const fallbackPatchStatus = await page.locator('#aiGatewayPatchStatus').evaluate((node) => node.textContent);
  const fallbackSuggestions = await page.locator('#aiGatewaySuggestions').evaluate((node) => node.textContent);

  await browser.close();
  console.log(JSON.stringify({{
    gatewayCall,
    gatewayStatus,
    gatewayQuestion,
    gatewaySuggestions,
    gatewayPatchStatus,
    blockedResult,
    blockedPatchStatus,
    fallbackResult,
    fallbackPatchStatus,
    fallbackSuggestions,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["gatewayCall"]["url"] == "/api/builder/guide"
    assert payload["gatewayCall"]["method"] == "POST"
    assert payload["gatewayCall"]["body"]["safety_boundary"]["browser_provider_api_key_storage"] == "forbidden"
    assert payload["gatewayCall"]["body"]["safety_boundary"]["external_tool_execution"] is False
    assert "server gateway enabled" in payload["gatewayStatus"]
    assert "서버 gateway 질문" in payload["gatewayQuestion"]
    assert "서버 응답도 자동 실행" in payload["gatewaySuggestions"]
    assert "contract_patch 검증 통과" in payload["gatewayPatchStatus"]
    assert payload["blockedResult"]["source"] == "server_gateway"
    assert payload["blockedResult"]["validation"]["status"] == "blocked"
    assert "contract_patch 차단" in payload["blockedPatchStatus"]
    assert any("network_send" in error for error in payload["blockedResult"]["validation"]["errors"])
    assert any("proof_claim_allowed" in error for error in payload["blockedResult"]["validation"]["errors"])
    assert payload["fallbackResult"]["source"] == "validated_local_fallback"
    assert "validated_local_fallback" in payload["fallbackPatchStatus"]
    assert "gateway fallback: request_failed" in payload["fallbackSuggestions"]


def test_builder_workspace_simulation_uses_selected_agent_template() -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")

    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#builderIntentInput').fill('회의 메모에서 결정사항과 담당자별 할 일을 뽑아줘');
  await page.locator('#generateSuggestionsButton').click();
  await page.locator('#workspaceSampleInput').fill('회의 메모: 민수는 고객 질문을 정리하고 지연은 다운로드 흐름을 점검한다. 마감일은 아직 미정이다.');
  await page.locator('#simulateWorkspaceButton').click();

  const templateValue = await page.locator('#templatePicker').inputValue();
  const status = await page.locator('#workspaceSimulationStatus').innerText();
  const output = await page.locator('#workspaceSimulationOutput').evaluate((node) => node.textContent);
  const resultCards = await page.locator('#workspaceResultCards').innerText();
  const trace = await page.locator('#workspaceSimulationTrace').evaluate((node) => node.textContent);

  await browser.close();
  console.log(JSON.stringify({{
    templateValue,
    status,
    output,
    resultCards,
    trace,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["templateValue"] == "meeting_notes"
    assert payload["status"] == "가상 실행 완료"
    assert "결정 사항" in payload["output"]
    assert "담당자별 할 일" in payload["output"]
    assert "확인 필요" in payload["output"]
    assert "결정 사항" in payload["resultCards"]
    assert "담당자" in payload["resultCards"]
    assert "확인 필요" in payload["resultCards"]
    assert "외부 전송 없음" in payload["trace"]
    assert "자동 실행 없음" in payload["trace"]
    assert "no_runtime_evidence" in payload["trace"]


def test_private_download_hub_browser_save_compare_restore_flow() -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")

    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');
const fs = require('fs');
const crypto = require('crypto');

function sortedJsonValue(value) {{
  if (Array.isArray(value)) return value.map(sortedJsonValue);
  if (value && typeof value === 'object') {{
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortedJsonValue(value[key])]));
  }}
  return value;
}}

function sha256Payload(value) {{
  return 'sha256:' + crypto.createHash('sha256').update(JSON.stringify(sortedJsonValue(value)), 'utf8').digest('hex');
}}

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const context = await browser.newContext({{ acceptDownloads: true }});
  const page = await context.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#saveHubButton').click();
  await page.locator('#agentName').fill('Document Organizer v2');
  await page.locator('#saveHubButton').click();
  const saveSummary = await page.locator('#hubVerificationSummary').innerText();
  await page.locator('[data-hub-compare="0"]').click();

  const compareSummary = await page.locator('#hubVerificationSummary').innerText();
  const diff = await page.locator('#hubDiff').innerText();
  await page.locator('[data-hub-restore="0"]').click();
  const restoreSummary = await page.locator('#hubVerificationSummary').innerText();
  const restored = await page.locator('#agentName').inputValue();
  const status = await page.locator('#hubImportStatus').innerText();
  const count = await page.locator('#hubCount').innerText();

  await browser.close();
  console.log(JSON.stringify({{ diff, restored, status, count, saveSummary, compareSummary, restoreSummary }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["count"] == "2"
    assert payload["restored"] == "Document Organizer v2"
    assert payload["status"].startswith("v2")
    assert "Builder" in payload["status"]
    assert "Hub pack import" in payload["saveSummary"]
    assert "builder_save" in payload["saveSummary"]
    assert "client preflight pass" in payload["saveSummary"]
    assert "local only true" in payload["saveSummary"]
    assert "server sync false" in payload["saveSummary"]
    assert "runtime send false" in payload["saveSummary"]
    assert "proof false" in payload["saveSummary"]
    assert "sale false" in payload["saveSummary"]
    assert "no_runtime_evidence" in payload["saveSummary"]
    assert "Hub compare" in payload["compareSummary"]
    assert "report only true" in payload["compareSummary"]
    assert "storage write false" in payload["compareSummary"]
    assert "runtime send false" in payload["compareSummary"]
    assert "runner handoff false" in payload["compareSummary"]
    assert "proof false" in payload["compareSummary"]
    assert "sale false" in payload["compareSummary"]
    assert "v2" in payload["compareSummary"]
    assert "v1" in payload["compareSummary"]
    assert "Hub restore" in payload["restoreSummary"]
    assert "builder draft only true" in payload["restoreSummary"]
    assert "storage write false" in payload["restoreSummary"]
    assert "runtime send false" in payload["restoreSummary"]
    assert "runner handoff false" in payload["restoreSummary"]
    assert "proof false" in payload["restoreSummary"]
    assert "sale false" in payload["restoreSummary"]
    assert "cambrian_required false" in payload["restoreSummary"]
    assert "client preflight pass" in payload["restoreSummary"]
    assert "v2" in payload["restoreSummary"]
    assert "- " in payload["diff"]
    assert "+ " in payload["diff"]
    assert "Document Organizer v2" in payload["diff"]


def test_builder_handoff_opens_local_runner_and_consumes_local_storage() -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")

    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');
const fs = require('fs');
const crypto = require('crypto');

function sortedJsonValue(value) {{
  if (Array.isArray(value)) return value.map(sortedJsonValue);
  if (value && typeof value === 'object') {{
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortedJsonValue(value[key])]));
  }}
  return value;
}}

function sha256Payload(value) {{
  return 'sha256:' + crypto.createHash('sha256').update(JSON.stringify(sortedJsonValue(value)), 'utf8').digest('hex');
}}

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const context = await browser.newContext({{ acceptDownloads: true }});
  const page = await context.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#sendRunnerButton').click();
  await page.waitForURL(/runner\\/index\\.html\\?handoff=builder/);
  await page.waitForFunction(() => document.querySelector('#loadStatus').innerText.includes('Builder handoff'));

  const url = page.url();
  const loadStatus = await page.locator('#loadStatus').innerText();
  const summary = await page.locator('#packSummary').innerText();
  const handoffLeft = await page.evaluate(() => localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const buildPromptDisabled = await page.locator('#buildPromptButton').isDisabled();

  await page.locator('#taskInput').fill('테스트 문서를 요약하고 후속 작업을 정리해줘.');
  await page.locator('#buildPromptButton').click();
  const prompt = await page.locator('#promptOutput').inputValue();

  await browser.close();
  console.log(JSON.stringify({{
    url,
    loadStatus,
    summary,
    handoffLeft,
    buildPromptDisabled,
    prompt,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert "runner/index.html?handoff=builder" in payload["url"]
    assert "Builder handoff를 불러왔습니다" in payload["loadStatus"]
    assert "document-organizer" in payload["summary"]
    assert payload["handoffLeft"] is None
    assert payload["buildPromptDisabled"] is False
    assert "runner_mode: manual_no_api" in payload["prompt"]
    assert "proof_claim_allowed: false" in payload["prompt"]


def test_runner_handoff_opens_evolution_review_and_consumes_local_storage() -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")

    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');
const fs = require('fs');
const crypto = require('crypto');

function sortedJsonValue(value) {{
  if (Array.isArray(value)) return value.map(sortedJsonValue);
  if (value && typeof value === 'object') {{
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortedJsonValue(value[key])]));
  }}
  return value;
}}

function sha256Payload(value) {{
  return 'sha256:' + crypto.createHash('sha256').update(JSON.stringify(sortedJsonValue(value)), 'utf8').digest('hex');
}}

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#sendRunnerButton').click();
  await page.waitForURL(/runner\\/index\\.html\\?handoff=builder/);
  await page.waitForFunction(() => document.querySelector('#loadStatus').innerText.includes('Builder handoff'));
  await page.locator('#taskInput').fill('테스트 문서를 요약하고 후속 작업을 정리해줘.');
  await page.locator('#buildPromptButton').click();
  await page.locator('#resultInput').fill('요약: 테스트 문서입니다. 후속 작업: 검증 기준을 확인합니다.');
  await page.locator('#sendEvolutionButton').click();

  await page.waitForURL(/evolution\\/index\\.html\\?handoff=runner/);
  await page.waitForFunction(() => document.querySelector('#loadStatus').innerText.includes('Runner handoff'));

  const url = page.url();
  const loadStatus = await page.locator('#loadStatus').innerText();
  const summary = await page.locator('#summaryList').innerText();
  const recommendations = await page.locator('#recommendationList').innerText();
  const handoffLeft = await page.evaluate(() => localStorage.getItem('agent-platform-evolution-handoff-v0-1'));
  const exportDisabled = await page.locator('#exportDecisionButton').isDisabled();
  const candidateDisabled = await page.locator('#exportCandidateButton').isDisabled();

  const noteCount = await page.locator('[data-note]').count();
  for (let index = 0; index < noteCount; index += 1) {{
    await page.locator('[data-note]').nth(index).fill(`검토 메모 ${{index + 1}}: 후보 pack 생성 전 확인했습니다.`);
  }}
  const downloadPromise = page.waitForEvent('download');
  await page.locator('#exportCandidateButton').click();
  const download = await downloadPromise;
  const candidatePath = await download.path();
  const candidate = JSON.parse(fs.readFileSync(candidatePath, 'utf8'));
  const candidateStatus = await page.locator('#candidateStatus').innerText();
  const previewDiffDisabled = await page.locator('#previewDiffButton').isDisabled();
  await page.locator('#previewDiffButton').click();
  await page.waitForFunction(() => document.querySelector('#candidateStatus').innerText.includes('미리보기'));
  const diffPreviewStatus = await page.locator('#candidateStatus').innerText();
  const candidatePreviewAfterDiffPreview = await page.locator('#candidatePreview').innerText();
  const promotedDisabledAfterDiffPreview = await page.locator('#exportPromotedButton').isDisabled();
  const promotionPreviewDisabledAfterDiffPreview = await page.locator('#previewPromotionButton').isDisabled();
  await page.locator('#previewPromotionButton').click();
  await page.waitForFunction(() => document.querySelector('#promotionPreview').innerText.includes('promotion 미리보기'));
  const promotionPreviewStatus = await page.locator('#candidateStatus').innerText();
  const promotionPreview = await page.locator('#promotionPreview').innerText();
  const diffDownloadPromise = page.waitForEvent('download');
  await page.locator('#exportDiffButton').click();
  const diffDownload = await diffDownloadPromise;
  const diffPath = await diffDownload.path();
  const diff = JSON.parse(fs.readFileSync(diffPath, 'utf8'));
  const diffStatus = await page.locator('#candidateStatus').innerText();
  const candidatePreviewAfterDiff = await page.locator('#candidatePreview').innerText();
  const promotedDownloadPromise = page.waitForEvent('download');
  await page.locator('#exportPromotedButton').click();
  const promotedDownload = await promotedDownloadPromise;
  const promotedPath = await promotedDownload.path();
  const promoted = JSON.parse(fs.readFileSync(promotedPath, 'utf8'));
  const promotedStatus = await page.locator('#candidateStatus').innerText();
  const recordDownloadPromise = page.waitForEvent('download');
  await page.locator('#exportPromotionRecordButton').click();
  const recordDownload = await recordDownloadPromise;
  const recordPath = await recordDownload.path();
  const record = JSON.parse(fs.readFileSync(recordPath, 'utf8'));
  const recordStatus = await page.locator('#candidateStatus').innerText();
  const hubPreviewDisabled = await page.locator('#previewHubButton').isDisabled();
  await page.locator('#previewHubButton').click();
  await page.waitForFunction(() => document.querySelector('#hubPreview').innerText.includes('Private Hub handoff 미리보기'));
  const hubPreviewStatus = await page.locator('#candidateStatus').innerText();
  const hubPreview = await page.locator('#hubPreview').innerText();
  const hubHandoffBeforeSend = await page.evaluate(() => localStorage.getItem('agent-platform-hub-handoff-v0-1'));
  await page.locator('#sendHubButton').click();
  await page.waitForURL(/platform\\/index\\.html\\?handoff=evolution/);
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('Evolution handoff를 Hub에 저장했습니다'));
  const hubUrl = page.url();
  const hubStatus = await page.locator('#hubImportStatus').innerText();
  const hubVerificationSummary = await page.locator('#hubVerificationSummary').innerText();
  const hubCount = await page.locator('#hubCount').innerText();
  const hubAuditCount = await page.locator('#promotionAuditCount').innerText();
  const hubLifecycleStage = await page.locator('.hub-lifecycle').first().getAttribute('data-lifecycle-stage');
  const hubEvolutionCount = await page.locator('[data-evolution-count]').first().getAttribute('data-evolution-count');
  const hubLifecycleText = await page.locator('.hub-lifecycle').first().innerText();
  const hubDetail = await page.locator('.hub-meta').first().innerText();
  const hubAuditText = await page.locator('#promotionAuditList').innerText();
  const hubHandoffLeft = await page.evaluate(() => localStorage.getItem('agent-platform-hub-handoff-v0-1'));
  await page.locator('[data-hub-lineage="0"]').click();
  const hubLineagePreview = await page.locator('#hubDiff').innerText();
  const lineageDownloadPromise = page.waitForEvent('download');
  await page.locator('[data-hub-lineage-download="0"]').click();
  const lineageDownload = await lineageDownloadPromise;
  const lineageDownloadName = lineageDownload.suggestedFilename();
  const lineageDownloadPath = await lineageDownload.path();
  await page.locator('#verifyLineageCardInput').setInputFiles(lineageDownloadPath);
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('lineage card 검증 완료'));
  const lineageVerifyStatus = await page.locator('#hubImportStatus').innerText();
  const lineageVerifyReport = await page.locator('#hubDiff').innerText();
  await page.locator('[data-hub-run="0"]').click();
  await page.waitForURL(/runner\\/index\\.html\\?handoff=hub/);
  await page.waitForFunction(() => document.querySelector('#loadStatus').innerText.includes('Private Download Hub handoff'));
  const hubRunnerUrl = page.url();
  const hubRunnerStatus = await page.locator('#loadStatus').innerText();
  const hubRunnerHandoffSummary = await page.locator('#handoffSummary').innerText();
  const hubRunnerSummary = await page.locator('#packSummary').innerText();
  const runnerHandoffLeftAfterHubRun = await page.evaluate(() => localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  await page.locator('#taskInput').fill('Hub에 저장된 promoted private version을 다시 실행하고 검토해줘.');
  await page.locator('#buildPromptButton').click();
  await page.locator('#resultInput').fill('요약: Hub 저장 버전을 다시 실행했습니다. 후속 작업: promoted source에서 재진화 후보를 검토합니다.');
  await page.locator('#sendEvolutionButton').click();
  await page.waitForURL(/evolution\\/index\\.html\\?handoff=runner/);
  await page.waitForFunction(() => document.querySelector('#loadStatus').innerText.includes('Runner handoff'));
  const secondEvolutionUrl = page.url();
  const secondEvolutionStatus = await page.locator('#loadStatus').innerText();
  const secondEvolutionSummary = await page.locator('#summaryList').innerText();
  const secondEvolutionHandoffSummary = await page.locator('#runnerHandoffSummary').innerText();
  const secondEvolutionHandoffLeft = await page.evaluate(() => localStorage.getItem('agent-platform-evolution-handoff-v0-1'));
  const secondCandidateDisabled = await page.locator('#exportCandidateButton').isDisabled();
  const secondNoteCount = await page.locator('[data-note]').count();
  for (let index = 0; index < secondNoteCount; index += 1) {{
    await page.locator('[data-note]').nth(index).fill(`2회차 검토 메모 ${{index + 1}}: promoted source에서 후보 pack을 검토했습니다.`);
  }}
  const secondCandidateDownloadPromise = page.waitForEvent('download');
  await page.locator('#exportCandidateButton').click();
  const secondCandidateDownload = await secondCandidateDownloadPromise;
  const secondCandidatePath = await secondCandidateDownload.path();
  const secondCandidate = JSON.parse(fs.readFileSync(secondCandidatePath, 'utf8'));
  const secondDiffDownloadPromise = page.waitForEvent('download');
  await page.locator('#exportDiffButton').click();
  const secondDiffDownload = await secondDiffDownloadPromise;
  const secondDiffPath = await secondDiffDownload.path();
  const secondDiff = JSON.parse(fs.readFileSync(secondDiffPath, 'utf8'));
  const secondDiffStatusText = await page.locator('#candidateStatus').innerText();

  await browser.close();
  console.log(JSON.stringify({{
    url,
    loadStatus,
    summary,
    recommendations,
    handoffLeft,
    exportDisabled,
    candidateDisabled,
    candidateStatus,
    candidateGeneratedBy: candidate.generated_by,
    candidateApplyStatus: candidate.candidate_metadata.apply_status,
    candidateAutoApply: candidate.candidate_metadata.auto_apply,
    candidateAutoPromote: candidate.candidate_metadata.auto_promote,
    candidateOriginalPreserved: candidate.candidate_metadata.original_pack_preserved,
    candidateProofClaimAllowed: candidate.files['manifest.json'].marketplace.proof_claim_allowed,
    candidateSaleReady: candidate.files['manifest.json'].marketplace.sale_ready,
    previewDiffDisabled,
    diffPreviewStatus,
    candidatePreviewAfterDiffPreview,
    promotedDisabledAfterDiffPreview,
    promotionPreviewDisabledAfterDiffPreview,
    promotionPreviewStatus,
    promotionPreview,
    diffStatusText: diffStatus,
    diffReportKind: diff.report_kind,
    diffReviewStatus: diff.diff_status,
    diffUnexpectedCount: diff.unexpected_changes.length,
    diffAutoPromote: diff.approval_gate.auto_promote,
    diffBlocked: diff.next_step.blocked,
    diffCandidateHashMatched: diff.source.candidate_pack_hash === sha256Payload(candidate),
    candidatePreviewAfterDiff,
    promotedStatusText: promotedStatus,
    promotedGeneratedBy: promoted.generated_by,
    promotedStatus: promoted.promotion_metadata.promotion_status,
    promotedAutoPromote: promoted.promotion_metadata.auto_promote,
    promotedCandidateMetadataRemoved: !('candidate_metadata' in promoted),
    promotedProofClaimAllowed: promoted.promotion_metadata.proof_claim_allowed,
    promotedSaleReady: promoted.promotion_metadata.marketplace_sale_ready,
    promotedCandidateHashMatched: promoted.promotion_metadata.promoted_from_candidate_hash === sha256Payload(candidate),
    promotedDiffHashMatched: promoted.promotion_metadata.diff_report_hash === sha256Payload(diff),
    recordStatusText: recordStatus,
    recordKind: record.record_kind,
    recordPromotionStatus: record.promotion_status,
    recordAutoPromote: record.gate.auto_promote,
    recordPromotedHashMatched: record.source.promoted_pack_hash === sha256Payload(promoted),
    recordCandidateHashMatched: record.source.candidate_pack_hash === sha256Payload(candidate),
    recordDiffHashMatched: record.source.diff_report_hash === sha256Payload(diff),
    hubPreviewDisabled,
    hubPreviewStatus,
    hubPreview,
    hubHandoffBeforeSend,
    hubUrl,
    hubStatus,
    hubVerificationSummary,
    hubCount,
    hubAuditCount,
    hubLifecycleStage,
    hubEvolutionCount,
    hubLifecycleText,
    hubDetail,
    hubAuditText,
    hubHandoffLeft,
    hubLineagePreview,
    lineageDownloadName,
    lineageVerifyStatus,
    lineageVerifyReport,
    hubRunnerUrl,
    hubRunnerStatus,
    hubRunnerHandoffSummary,
    hubRunnerSummary,
    runnerHandoffLeftAfterHubRun,
    secondEvolutionUrl,
    secondEvolutionStatus,
    secondEvolutionSummary,
    secondEvolutionHandoffSummary,
    secondEvolutionHandoffLeft,
    secondCandidateDisabled,
    secondCandidateGeneratedBy: secondCandidate.generated_by,
    secondCandidateHasPromotionMetadata: 'promotion_metadata' in secondCandidate,
    secondCandidateHasCandidateMetadata: 'candidate_metadata' in secondCandidate,
    secondDiffStatusText,
    secondDiffReviewStatus: secondDiff.diff_status,
    secondDiffUnexpectedCount: secondDiff.unexpected_changes.length,
    secondDiffAllowedPromotionRemoval: secondDiff.allowed_changes.some((item) => item.path.startsWith('promotion_metadata.') && item.change_type === 'removed'),
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert "evolution/index.html?handoff=runner" in payload["url"]
    assert "Runner handoff를 불러왔습니다" in payload["loadStatus"]
    assert "document-organizer" in payload["summary"]
    assert "draft_requires_user_approval" in payload["summary"]
    assert "수동 검증 체크리스트" in payload["recommendations"]
    assert "known limits" in payload["recommendations"]
    assert payload["handoffLeft"] is None
    assert payload["exportDisabled"] is False
    assert payload["candidateDisabled"] is False
    assert "candidate agent pack을 내보냈습니다" in payload["candidateStatus"]
    assert payload["candidateGeneratedBy"] == "tools/generate_candidate_pack.py"
    assert payload["candidateApplyStatus"] == "candidate_not_applied"
    assert payload["candidateAutoApply"] is False
    assert payload["candidateAutoPromote"] is False
    assert payload["candidateOriginalPreserved"] is True
    assert payload["candidateProofClaimAllowed"] is False
    assert payload["candidateSaleReady"] is False
    assert payload["previewDiffDisabled"] is False
    assert "candidate_diff_report_v0_1 미리보기를 만들었습니다" in payload["diffPreviewStatus"]
    assert "review_pass_not_promoted" in payload["candidatePreviewAfterDiffPreview"]
    assert "승인 연결" in payload["candidatePreviewAfterDiffPreview"]
    assert "automatic_candidate_promotion" in payload["candidatePreviewAfterDiffPreview"]
    assert payload["promotedDisabledAfterDiffPreview"] is False
    assert payload["promotionPreviewDisabledAfterDiffPreview"] is False
    assert "promotion 미리보기를 만들었습니다" in payload["promotionPreviewStatus"]
    assert "promotion 미리보기" in payload["promotionPreview"]
    assert "promoted_private_version" in payload["promotionPreview"]
    assert "candidate_promotion_record_v0_1" in payload["promotionPreview"]
    assert "removed" in payload["promotionPreview"]
    assert "hash link" in payload["promotionPreview"]
    assert "linked" in payload["promotionPreview"]
    assert "candidate_diff_report_v0_1을 내보냈습니다" in payload["diffStatusText"]
    assert payload["diffReportKind"] == "candidate_diff_report_v0_1"
    assert payload["diffReviewStatus"] == "review_pass_not_promoted"
    assert payload["diffUnexpectedCount"] == 0
    assert payload["diffAutoPromote"] is False
    assert payload["diffBlocked"] == "automatic_candidate_promotion"
    assert payload["diffCandidateHashMatched"] is True
    assert "전후 비교" in payload["candidatePreviewAfterDiff"]
    assert "review_pass_not_promoted" in payload["candidatePreviewAfterDiff"]
    assert "승인 연결" in payload["candidatePreviewAfterDiff"]
    assert "승인된 instructions.md 진화 제안을 반영한다" in payload["candidatePreviewAfterDiff"]
    assert "unexpected" in payload["candidatePreviewAfterDiff"]
    assert "0" in payload["candidatePreviewAfterDiff"]
    assert "automatic_candidate_promotion" in payload["candidatePreviewAfterDiff"]
    assert "promoted private version pack을 내보냈습니다" in payload["promotedStatusText"]
    assert payload["promotedGeneratedBy"] == "tools/promote_candidate_pack.py"
    assert payload["promotedStatus"] == "promoted_private_version"
    assert payload["promotedAutoPromote"] is False
    assert payload["promotedCandidateMetadataRemoved"] is True
    assert payload["promotedProofClaimAllowed"] is False
    assert payload["promotedSaleReady"] is False
    assert payload["promotedCandidateHashMatched"] is True
    assert payload["promotedDiffHashMatched"] is True
    assert "candidate_promotion_record_v0_1을 내보냈습니다" in payload["recordStatusText"]
    assert payload["recordKind"] == "candidate_promotion_record_v0_1"
    assert payload["recordPromotionStatus"] == "promoted_private_version"
    assert payload["recordAutoPromote"] is False
    assert payload["recordPromotedHashMatched"] is True
    assert payload["recordCandidateHashMatched"] is True
    assert payload["recordDiffHashMatched"] is True
    assert payload["hubPreviewDisabled"] is False
    assert "Private Hub handoff 미리보기를 만들었습니다" in payload["hubPreviewStatus"]
    assert "Private Hub handoff 미리보기" in payload["hubPreview"]
    assert "evolution_review_to_private_download_hub" in payload["hubPreview"]
    assert "server sync" in payload["hubPreview"]
    assert "false" in payload["hubPreview"]
    assert "no_runtime_evidence" in payload["hubPreview"]
    assert "promoted_private_version" in payload["hubPreview"]
    assert payload["hubHandoffBeforeSend"] is None
    assert "platform/index.html?handoff=evolution" in payload["hubUrl"]
    assert "Evolution handoff를 Hub에 저장했습니다" in payload["hubStatus"]
    assert "Evolution handoff 검증 요약" in payload["hubVerificationSummary"]
    assert "verified linked" in payload["hubVerificationSummary"]
    assert "single use true" in payload["hubVerificationSummary"]
    assert "server sync false" in payload["hubVerificationSummary"]
    assert "proof false" in payload["hubVerificationSummary"]
    assert "sale false" in payload["hubVerificationSummary"]
    assert "no_runtime_evidence" in payload["hubVerificationSummary"]
    assert payload["hubCount"] == "1"
    assert payload["hubAuditCount"] == "1"
    assert payload["hubLifecycleStage"] == "promoted_private_version"
    assert payload["hubEvolutionCount"] == "1"
    assert "Promoted private" in payload["hubLifecycleText"]
    assert "진화 1회" in payload["hubLifecycleText"]
    assert "audit 1" in payload["hubLifecycleText"]
    assert "진화 1회" in payload["hubDetail"]
    assert "promotion audit verified" in payload["hubDetail"]
    assert "verified linked" in payload["hubAuditText"]
    assert payload["hubHandoffLeft"] is None
    assert "private_hub_lineage_card_v0_1" in payload["hubLineagePreview"]
    assert "proof_claim_allowed" in payload["hubLineagePreview"]
    assert "verified linked" in payload["hubLineagePreview"]
    assert payload["lineageDownloadName"].endswith(".private-hub-lineage-card.json")
    assert "lineage card 검증 완료" in payload["lineageVerifyStatus"]
    assert "private_hub_lineage_card_verifier_v0_1" in payload["lineageVerifyReport"]
    assert '"status": "pass"' in payload["lineageVerifyReport"]
    assert "runner/index.html?handoff=hub" in payload["hubRunnerUrl"]
    assert "Private Download Hub handoff를 불러왔습니다" in payload["hubRunnerStatus"]
    assert "Private Download Hub handoff 검증 요약" in payload["hubRunnerHandoffSummary"]
    assert "private_download_hub_to_manual_runner" in payload["hubRunnerHandoffSummary"]
    assert "single use" in payload["hubRunnerHandoffSummary"]
    assert "true" in payload["hubRunnerHandoffSummary"]
    assert "server sync" in payload["hubRunnerHandoffSummary"]
    assert "false" in payload["hubRunnerHandoffSummary"]
    assert "no_runtime_evidence" in payload["hubRunnerHandoffSummary"]
    assert "promoted_private_version" in payload["hubRunnerHandoffSummary"]
    assert "문서 정리 에이전트" in payload["hubRunnerSummary"]
    assert payload["runnerHandoffLeftAfterHubRun"] is None
    assert "evolution/index.html?handoff=runner" in payload["secondEvolutionUrl"]
    assert "Runner handoff를 불러왔습니다" in payload["secondEvolutionStatus"]
    assert "source_lifecycle" in payload["secondEvolutionSummary"]
    assert "promoted_private_version" in payload["secondEvolutionSummary"]
    assert "Runner handoff" in payload["secondEvolutionHandoffSummary"]
    assert "manual_runner_to_evolution_review" in payload["secondEvolutionHandoffSummary"]
    assert "single use" in payload["secondEvolutionHandoffSummary"]
    assert "server sync" in payload["secondEvolutionHandoffSummary"]
    assert "runtime send" in payload["secondEvolutionHandoffSummary"]
    assert "no_runtime_evidence" in payload["secondEvolutionHandoffSummary"]
    assert "proof false" in payload["secondEvolutionHandoffSummary"]
    assert "success rate false" in payload["secondEvolutionHandoffSummary"]
    assert "sale false" in payload["secondEvolutionHandoffSummary"]
    assert "manual_no_api" in payload["secondEvolutionHandoffSummary"]
    assert "user approval true" in payload["secondEvolutionHandoffSummary"]
    assert payload["secondEvolutionHandoffLeft"] is None
    assert payload["secondCandidateDisabled"] is False
    assert payload["secondCandidateGeneratedBy"] == "tools/generate_candidate_pack.py"
    assert payload["secondCandidateHasPromotionMetadata"] is False
    assert payload["secondCandidateHasCandidateMetadata"] is True
    assert "candidate_diff_report_v0_1을 내보냈습니다" in payload["secondDiffStatusText"]
    assert payload["secondDiffReviewStatus"] == "review_pass_not_promoted"
    assert payload["secondDiffUnexpectedCount"] == 0
    assert payload["secondDiffAllowedPromotionRemoval"] is True


def test_private_download_hub_imports_promoted_private_version() -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")

    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#saveHubButton').click();
  await page.locator('#importHubInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTED))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('가져오기 완료'));
  const importSummary = await page.locator('#hubVerificationSummary').innerText();
  await page.locator('#importPromotionRecordInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTION_RECORD))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('승격 기록 가져오기 완료'));
  const auditSummary = await page.locator('#hubVerificationSummary').innerText();

  const count = await page.locator('#hubCount').innerText();
  const auditCount = await page.locator('#promotionAuditCount').innerText();
  const auditStatus = await page.locator('#hubImportStatus').innerText();
  const lifecycleStage = await page.locator('.hub-lifecycle').first().getAttribute('data-lifecycle-stage');
  const evolutionCount = await page.locator('[data-evolution-count]').first().getAttribute('data-evolution-count');
  const lifecycleText = await page.locator('.hub-lifecycle').first().innerText();
  const detail = await page.locator('.hub-meta').first().innerText();
  const auditText = await page.locator('#promotionAuditList').innerText();

  await page.locator('[data-audit-view="0"]').click();
  const auditPreview = await page.locator('#hubDiff').innerText();
  const downloadPromise = page.waitForEvent('download');
  await page.locator('[data-audit-download="0"]').click();
  const download = await downloadPromise;
  const downloadName = download.suggestedFilename();
  await page.locator('[data-hub-lineage="0"]').click();
  const lineagePreview = await page.locator('#hubDiff').innerText();
  const lineageDownloadPromise = page.waitForEvent('download');
  await page.locator('[data-hub-lineage-download="0"]').click();
  const lineageDownload = await lineageDownloadPromise;
  const lineageDownloadName = lineageDownload.suggestedFilename();
  const lineageDownloadPath = await lineageDownload.path();
  await page.locator('#verifyLineageCardInput').setInputFiles(lineageDownloadPath);
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('lineage card 검증 완료'));
  const lineageVerifyStatus = await page.locator('#hubImportStatus').innerText();
  const lineageVerifyReport = await page.locator('#hubDiff').innerText();
  const lineageVerifySummary = await page.locator('#hubVerificationSummary').innerText();

  await page.locator('[data-hub-restore="0"]').click();
  const restoreStatus = await page.locator('#hubImportStatus').innerText();
  const restoredName = await page.locator('#agentName').inputValue();

  await page.locator('[data-audit-delete="0"]').click();
  const auditCountAfterDelete = await page.locator('#promotionAuditCount').innerText();
  const auditListAfterDelete = await page.locator('#promotionAuditList').innerText();
  const lifecycleTextAfterDelete = await page.locator('.hub-lifecycle').first().innerText();

  await browser.close();
  console.log(JSON.stringify({{
    count,
    auditCount,
    auditStatus,
    importSummary,
    auditSummary,
    lifecycleStage,
    evolutionCount,
    lifecycleText,
    detail,
    auditText,
    auditPreview,
    downloadName,
    lineagePreview,
    lineageDownloadName,
    lineageVerifyStatus,
    lineageVerifyReport,
    lineageVerifySummary,
    restoreStatus,
    restoredName,
    auditCountAfterDelete,
    auditListAfterDelete,
    lifecycleTextAfterDelete,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["count"] == "2"
    assert payload["auditCount"] == "1"
    assert "Hub pack import" in payload["importSummary"]
    assert "file_import" in payload["importSummary"]
    assert "client preflight pass" in payload["importSummary"]
    assert "local only true" in payload["importSummary"]
    assert "server sync false" in payload["importSummary"]
    assert "runtime send false" in payload["importSummary"]
    assert "proof false" in payload["importSummary"]
    assert "sale false" in payload["importSummary"]
    assert "promoted_private_version" in payload["importSummary"]
    assert "sha256:" in payload["importSummary"]
    assert "no_runtime_evidence" in payload["importSummary"]
    assert "Promotion audit import" in payload["auditSummary"]
    assert "verified linked v2" in payload["auditSummary"]
    assert "local only true" in payload["auditSummary"]
    assert "server sync false" in payload["auditSummary"]
    assert "runtime send false" in payload["auditSummary"]
    assert "proof false" in payload["auditSummary"]
    assert "sale false" in payload["auditSummary"]
    assert "user command true" in payload["auditSummary"]
    assert "promoted_private_version" in payload["auditSummary"]
    assert "candidate sha256:" in payload["auditSummary"]
    assert "diff sha256:" in payload["auditSummary"]
    assert "promoted sha256:" in payload["auditSummary"]
    assert payload["lifecycleStage"] == "promoted_private_version"
    assert payload["evolutionCount"] == "1"
    assert "Promoted private" in payload["lifecycleText"]
    assert "진화 1회" in payload["lifecycleText"]
    assert "audit 1" in payload["lifecycleText"]
    assert "proof blocked" in payload["lifecycleText"]
    assert "sale blocked" in payload["lifecycleText"]
    assert "sha256:" in payload["detail"]
    assert "content sha256:" in payload["detail"]
    assert "linked v2" in payload["auditText"]
    assert "candidate sha256:" in payload["auditText"]
    assert "promoted sha256:" in payload["auditText"]
    assert "promotion audit verified" in payload["detail"]
    assert "candidate_promotion_record_v0_1" in payload["auditPreview"]
    assert "gate" in payload["auditPreview"]
    assert payload["downloadName"].endswith(".candidate-promotion-record.json")
    assert "private_hub_lineage_card_v0_1" in payload["lineagePreview"]
    assert "진화 1회" in payload["lineagePreview"]
    assert "verified linked" in payload["lineagePreview"]
    assert payload["lineageDownloadName"].endswith(".private-hub-lineage-card.json")
    assert "lineage card 검증 완료" in payload["lineageVerifyStatus"]
    assert "private_hub_lineage_card_verifier_v0_1" in payload["lineageVerifyReport"]
    assert '"status": "pass"' in payload["lineageVerifyReport"]
    assert "Lineage card" in payload["lineageVerifySummary"]
    assert "status pass" in payload["lineageVerifySummary"]
    assert "report only true" in payload["lineageVerifySummary"]
    assert "side effects false" in payload["lineageVerifySummary"]
    assert "proof false" in payload["lineageVerifySummary"]
    assert "sale false" in payload["lineageVerifySummary"]
    assert "raw inputs false" in payload["lineageVerifySummary"]
    assert "raw outputs false" in payload["lineageVerifySummary"]
    assert "secrets false" in payload["lineageVerifySummary"]
    assert "audit verified linked" in payload["lineageVerifySummary"]
    assert "hub v2" in payload["lineageVerifySummary"]
    assert "checks 7/7" in payload["lineageVerifySummary"]
    assert "승격 기록 가져오기 완료" in payload["auditStatus"]
    assert "v2에 검증 연결했습니다" in payload["auditStatus"]
    assert "Builder 초안" in payload["restoreStatus"]
    assert "새 Builder draft" in payload["restoreStatus"]
    assert payload["restoredName"] == "문서 정리 에이전트"
    assert payload["auditCountAfterDelete"] == "0"
    assert "아직 가져온 promotion audit record가 없습니다" in payload["auditListAfterDelete"]
    assert "audit 1" not in payload["lifecycleTextAfterDelete"]


def test_private_download_hub_rejects_tampered_lineage_card(tmp_path: Path) -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")

    tampered_lineage = tmp_path / "tampered.private-hub-lineage-card.json"
    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const fs = require('fs');
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#importHubInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTED))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('가져오기 완료'));
  await page.locator('#importPromotionRecordInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTION_RECORD))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('승격 기록 가져오기 완료'));

  const lineageDownloadPromise = page.waitForEvent('download');
  await page.locator('[data-hub-lineage-download="0"]').click();
  const lineageDownload = await lineageDownloadPromise;
  const lineageDownloadPath = await lineageDownload.path();
  const lineage = JSON.parse(fs.readFileSync(lineageDownloadPath, 'utf8'));
  lineage.fingerprint = 'tampered-fingerprint';
  fs.writeFileSync({json.dumps(str(tampered_lineage))}, JSON.stringify(lineage, null, 2), 'utf8');

  await page.locator('#verifyLineageCardInput').setInputFiles({json.dumps(str(tampered_lineage))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('lineage card 검증 실패'));
  const status = await page.locator('#hubImportStatus').innerText();
  const report = await page.locator('#hubDiff').innerText();
  const summary = await page.locator('#hubVerificationSummary').innerText();

  await browser.close();
  console.log(JSON.stringify({{ status, report, summary }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert "lineage card 검증 실패" in payload["status"]
    assert "lineage fingerprint" in payload["status"]
    assert "private_hub_lineage_card_verifier_v0_1" in payload["report"]
    assert '"status": "fail"' in payload["report"]
    assert '"name": "fingerprint_matches_hub"' in payload["report"]
    assert '"name": "content_hash_matches_hub"' in payload["report"]
    assert "Lineage card" in payload["summary"]
    assert "status fail" in payload["summary"]
    assert "report only true" in payload["summary"]
    assert "side effects false" in payload["summary"]
    assert "proof false" in payload["summary"]
    assert "sale false" in payload["summary"]
    assert "audit verified linked" in payload["summary"]
    assert "hub v1" in payload["summary"]
    assert "checks 6/7" in payload["summary"]
    assert "errors 1" in payload["summary"]


def test_private_download_hub_rejects_lineage_card_with_claim_boundary_tampering(tmp_path: Path) -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")

    tampered_lineage = tmp_path / "claim-boundary-tampered.private-hub-lineage-card.json"
    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const fs = require('fs');
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#importHubInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTED))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('가져오기 완료'));
  await page.locator('#importPromotionRecordInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTION_RECORD))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('승격 기록 가져오기 완료'));

  const lineageDownloadPromise = page.waitForEvent('download');
  await page.locator('[data-hub-lineage-download="0"]').click();
  const lineageDownload = await lineageDownloadPromise;
  const lineageDownloadPath = await lineageDownload.path();
  const lineage = JSON.parse(fs.readFileSync(lineageDownloadPath, 'utf8'));
  lineage.claim_boundary = {{
    proof_claim_allowed: true,
    success_rate_claim_allowed: true,
    marketplace_sale_ready: true,
  }};
  fs.writeFileSync({json.dumps(str(tampered_lineage))}, JSON.stringify(lineage, null, 2), 'utf8');

  await page.locator('#verifyLineageCardInput').setInputFiles({json.dumps(str(tampered_lineage))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('lineage card 검증 실패'));
  const status = await page.locator('#hubImportStatus').innerText();
  const report = await page.locator('#hubDiff').innerText();

  await browser.close();
  console.log(JSON.stringify({{ status, report }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert "lineage card 검증 실패" in payload["status"]
    assert "proof claim" in payload["status"]
    assert "private_hub_lineage_card_verifier_v0_1" in payload["report"]
    assert '"status": "fail"' in payload["report"]
    assert '"name": "proof_boundary_blocked"' in payload["report"]
    assert '"name": "sale_boundary_blocked"' in payload["report"]


def test_private_download_hub_rejects_lineage_card_with_privacy_boundary_tampering(tmp_path: Path) -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")

    tampered_lineage = tmp_path / "privacy-boundary-tampered.private-hub-lineage-card.json"
    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const fs = require('fs');
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#importHubInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTED))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('가져오기 완료'));
  await page.locator('#importPromotionRecordInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTION_RECORD))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('승격 기록 가져오기 완료'));

  const lineageDownloadPromise = page.waitForEvent('download');
  await page.locator('[data-hub-lineage-download="0"]').click();
  const lineageDownload = await lineageDownloadPromise;
  const lineageDownloadPath = await lineageDownload.path();
  const lineage = JSON.parse(fs.readFileSync(lineageDownloadPath, 'utf8'));
  lineage.privacy = {{
    stores_raw_inputs: true,
    stores_raw_outputs: true,
    stores_secrets: true,
  }};
  fs.writeFileSync({json.dumps(str(tampered_lineage))}, JSON.stringify(lineage, null, 2), 'utf8');

  await page.locator('#verifyLineageCardInput').setInputFiles({json.dumps(str(tampered_lineage))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('lineage card 검증 실패'));
  const status = await page.locator('#hubImportStatus').innerText();
  const report = await page.locator('#hubDiff').innerText();

  await browser.close();
  console.log(JSON.stringify({{ status, report }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    report = json.loads(payload["report"])
    checks = {check["name"]: check["status"] for check in report["checks"]}
    assert "lineage card 검증 실패" in payload["status"]
    assert "원문 입력" in payload["status"]
    assert "secret" in payload["status"]
    assert report["verifier"] == "private_hub_lineage_card_verifier_v0_1"
    assert report["status"] == "fail"
    assert checks["content_hash_matches_hub"] == "pass"
    assert checks["fingerprint_matches_hub"] == "pass"
    assert checks["privacy_boundary_blocked"] == "fail"


def test_private_download_hub_rejects_lineage_card_with_audit_link_tampering(tmp_path: Path) -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")

    tampered_lineage = tmp_path / "audit-link-tampered.private-hub-lineage-card.json"
    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const fs = require('fs');
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#importHubInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTED))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('가져오기 완료'));
  await page.locator('#importPromotionRecordInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTION_RECORD))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('승격 기록 가져오기 완료'));

  const lineageDownloadPromise = page.waitForEvent('download');
  await page.locator('[data-hub-lineage-download="0"]').click();
  const lineageDownload = await lineageDownloadPromise;
  const lineageDownloadPath = await lineageDownload.path();
  const lineage = JSON.parse(fs.readFileSync(lineageDownloadPath, 'utf8'));
  lineage.promotion_audit.record_fingerprint = 'tampered-audit-fingerprint';
  fs.writeFileSync({json.dumps(str(tampered_lineage))}, JSON.stringify(lineage, null, 2), 'utf8');

  await page.locator('#verifyLineageCardInput').setInputFiles({json.dumps(str(tampered_lineage))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('lineage card 검증 실패'));
  const status = await page.locator('#hubImportStatus').innerText();
  const report = await page.locator('#hubDiff').innerText();

  await browser.close();
  console.log(JSON.stringify({{ status, report }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    report = json.loads(payload["report"])
    checks = {check["name"]: check["status"] for check in report["checks"]}
    assert "lineage card 검증 실패" in payload["status"]
    assert "verified linked" in payload["status"]
    assert "audit" in payload["status"]
    assert report["verifier"] == "private_hub_lineage_card_verifier_v0_1"
    assert report["status"] == "fail"
    assert checks["content_hash_matches_hub"] == "pass"
    assert checks["fingerprint_matches_hub"] == "pass"
    assert checks["audit_link_matches_hub"] == "fail"


def test_private_download_hub_rejects_stale_not_linked_lineage_card_after_audit_import(tmp_path: Path) -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")

    stale_lineage = tmp_path / "stale-not-linked.private-hub-lineage-card.json"
    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const fs = require('fs');
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#importHubInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTED))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('가져오기 완료'));

  const lineageDownloadPromise = page.waitForEvent('download');
  await page.locator('[data-hub-lineage-download="0"]').click();
  const lineageDownload = await lineageDownloadPromise;
  const lineageDownloadPath = await lineageDownload.path();
  const lineage = JSON.parse(fs.readFileSync(lineageDownloadPath, 'utf8'));
  fs.writeFileSync({json.dumps(str(stale_lineage))}, JSON.stringify(lineage, null, 2), 'utf8');

  await page.locator('#importPromotionRecordInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTION_RECORD))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('승격 기록 가져오기 완료'));

  await page.locator('#verifyLineageCardInput').setInputFiles({json.dumps(str(stale_lineage))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('lineage card 검증 실패'));
  const status = await page.locator('#hubImportStatus').innerText();
  const report = await page.locator('#hubDiff').innerText();

  await browser.close();
  console.log(JSON.stringify({{
    initialLinkStatus: lineage.promotion_audit.link_status,
    status,
    report,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    report = json.loads(payload["report"])
    checks = {check["name"]: check["status"] for check in report["checks"]}
    assert payload["initialLinkStatus"] == "not linked"
    assert "lineage card 검증 실패" in payload["status"]
    assert "verified audit" in payload["status"]
    assert report["verifier"] == "private_hub_lineage_card_verifier_v0_1"
    assert report["status"] == "fail"
    assert checks["content_hash_matches_hub"] == "pass"
    assert checks["fingerprint_matches_hub"] == "pass"
    assert checks["audit_link_matches_hub"] == "fail"


def test_private_download_hub_failed_lineage_verification_has_no_storage_side_effects(
    tmp_path: Path,
) -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")

    tampered_lineage = tmp_path / "no-side-effect-tampered.private-hub-lineage-card.json"
    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const fs = require('fs');
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#importHubInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTED))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('가져오기 완료'));
  await page.locator('#importPromotionRecordInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTION_RECORD))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('승격 기록 가져오기 완료'));

  const lineageDownloadPromise = page.waitForEvent('download');
  await page.locator('[data-hub-lineage-download="0"]').click();
  const lineageDownload = await lineageDownloadPromise;
  const lineageDownloadPath = await lineageDownload.path();
  const lineage = JSON.parse(fs.readFileSync(lineageDownloadPath, 'utf8'));
  lineage.fingerprint = 'tampered-no-side-effect-fingerprint';
  fs.writeFileSync({json.dumps(str(tampered_lineage))}, JSON.stringify(lineage, null, 2), 'utf8');

  const hubBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-download-hub-v0-1'));
  const auditBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-promotion-audit-v0-1'));
  const runnerHandoffBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const hubCountBefore = await page.locator('#hubCount').innerText();
  const auditCountBefore = await page.locator('#promotionAuditCount').innerText();

  await page.locator('#verifyLineageCardInput').setInputFiles({json.dumps(str(tampered_lineage))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('lineage card 검증 실패'));

  const status = await page.locator('#hubImportStatus').innerText();
  const report = await page.locator('#hubDiff').innerText();
  const hubAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-download-hub-v0-1'));
  const auditAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-promotion-audit-v0-1'));
  const runnerHandoffAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const hubCountAfter = await page.locator('#hubCount').innerText();
  const auditCountAfter = await page.locator('#promotionAuditCount').innerText();

  await browser.close();
  console.log(JSON.stringify({{
    status,
    report,
    hubStorageUnchanged: hubBefore === hubAfter,
    auditStorageUnchanged: auditBefore === auditAfter,
    runnerHandoffBefore,
    runnerHandoffAfter,
    hubCountBefore,
    hubCountAfter,
    auditCountBefore,
    auditCountAfter,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    report = json.loads(payload["report"])
    assert "lineage card 검증 실패" in payload["status"]
    assert report["report_kind"] == "private_hub_lineage_card_verifier_report_v0_1"
    assert report["report_version"] == "0.1"
    assert report["status"] == "fail"
    assert report["effect"] == "report_only"
    assert report["side_effects"] == {
        "hub_storage_write": False,
        "promotion_audit_storage_write": False,
        "runner_handoff_write": False,
        "installs_or_runs_agent": False,
    }
    assert report["report_privacy"] == {
        "stores_raw_card": False,
        "stores_raw_inputs": False,
        "stores_raw_outputs": False,
        "stores_secrets": False,
        "echoes_non_lineage_identity": False,
    }
    _assert_lineage_verifier_receipt_contract(report)
    assert payload["hubStorageUnchanged"] is True
    assert payload["auditStorageUnchanged"] is True
    assert payload["runnerHandoffBefore"] is None
    assert payload["runnerHandoffAfter"] is None
    assert payload["hubCountBefore"] == payload["hubCountAfter"]
    assert payload["auditCountBefore"] == payload["auditCountAfter"]


def test_private_download_hub_passed_lineage_verification_has_no_storage_side_effects(
    tmp_path: Path,
) -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")

    lineage_card = tmp_path / "pass-no-side-effect.private-hub-lineage-card.json"
    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const fs = require('fs');
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#importHubInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTED))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('가져오기 완료'));
  await page.locator('#importPromotionRecordInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTION_RECORD))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('승격 기록 가져오기 완료'));

  const lineageDownloadPromise = page.waitForEvent('download');
  await page.locator('[data-hub-lineage-download="0"]').click();
  const lineageDownload = await lineageDownloadPromise;
  const lineageDownloadPath = await lineageDownload.path();
  fs.copyFileSync(lineageDownloadPath, {json.dumps(str(lineage_card))});

  const hubBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-download-hub-v0-1'));
  const auditBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-promotion-audit-v0-1'));
  const runnerHandoffBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const hubCountBefore = await page.locator('#hubCount').innerText();
  const auditCountBefore = await page.locator('#promotionAuditCount').innerText();

  await page.locator('#verifyLineageCardInput').setInputFiles({json.dumps(str(lineage_card))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('lineage card 검증 완료'));

  const status = await page.locator('#hubImportStatus').innerText();
  const report = await page.locator('#hubDiff').innerText();
  const hubAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-download-hub-v0-1'));
  const auditAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-promotion-audit-v0-1'));
  const runnerHandoffAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const hubCountAfter = await page.locator('#hubCount').innerText();
  const auditCountAfter = await page.locator('#promotionAuditCount').innerText();

  await browser.close();
  console.log(JSON.stringify({{
    status,
    report,
    hubStorageUnchanged: hubBefore === hubAfter,
    auditStorageUnchanged: auditBefore === auditAfter,
    runnerHandoffBefore,
    runnerHandoffAfter,
    hubCountBefore,
    hubCountAfter,
    auditCountBefore,
    auditCountAfter,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    report = json.loads(payload["report"])
    assert "lineage card 검증 완료" in payload["status"]
    assert report["report_kind"] == "private_hub_lineage_card_verifier_report_v0_1"
    assert report["report_version"] == "0.1"
    assert report["status"] == "pass"
    assert report["effect"] == "report_only"
    assert report["side_effects"] == {
        "hub_storage_write": False,
        "promotion_audit_storage_write": False,
        "runner_handoff_write": False,
        "installs_or_runs_agent": False,
    }
    assert report["report_privacy"] == {
        "stores_raw_card": False,
        "stores_raw_inputs": False,
        "stores_raw_outputs": False,
        "stores_secrets": False,
        "echoes_non_lineage_identity": False,
    }
    _assert_lineage_verifier_receipt_contract(report)
    assert payload["hubStorageUnchanged"] is True
    assert payload["auditStorageUnchanged"] is True
    assert payload["runnerHandoffBefore"] is None
    assert payload["runnerHandoffAfter"] is None
    assert payload["hubCountBefore"] == payload["hubCountAfter"]
    assert payload["auditCountBefore"] == payload["auditCountAfter"]


def test_private_download_hub_verifies_lineage_report_receipt_checksum(
    tmp_path: Path,
) -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node ?ㅽ뻾 ?뚯씪??李얠쓣 ???놁뼱 釉뚮씪?곗? ?먮룞 ?뚯뒪?몃? 嫄대꼫?곷땲??")
    if not chrome:
        pytest.skip("Chrome ?먮뒗 Edge ?ㅽ뻾 ?뚯씪??李얠쓣 ???놁뼱 釉뚮씪?곗? ?먮룞 ?뚯뒪?몃? 嫄대꼫?곷땲??")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright ?⑦궎吏瑜?李얠쓣 ???놁뼱 釉뚮씪?곗? ?먮룞 ?뚯뒪?몃? 嫄대꼫?곷땲??")

    lineage_card = tmp_path / "receipt-source.private-hub-lineage-card.json"
    receipt_report = tmp_path / "lineage-verifier-receipt-report.json"
    tampered_report = tmp_path / "tampered-lineage-verifier-receipt-report.json"
    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const fs = require('fs');
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#importHubInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTED))});
  await page.waitForFunction(() => document.querySelector('#hubCount').innerText !== '0');
  await page.locator('#importPromotionRecordInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTION_RECORD))});
  await page.waitForFunction(() => document.querySelector('#promotionAuditCount').innerText !== '0');

  const lineageDownloadPromise = page.waitForEvent('download');
  await page.locator('[data-hub-lineage-download="0"]').click();
  const lineageDownload = await lineageDownloadPromise;
  const lineageDownloadPath = await lineageDownload.path();
  fs.copyFileSync(lineageDownloadPath, {json.dumps(str(lineage_card))});

  await page.locator('#verifyLineageCardInput').setInputFiles({json.dumps(str(lineage_card))});
  await page.waitForFunction(() => document.querySelector('#hubDiff').innerText.includes('private_hub_lineage_card_verifier_report_v0_1'));
  const lineageVerifierReport = JSON.parse(await page.locator('#hubDiff').innerText());
  fs.writeFileSync({json.dumps(str(receipt_report))}, JSON.stringify(lineageVerifierReport, null, 2), 'utf8');

  const tamperedReport = {{ ...lineageVerifierReport, status: 'tampered-pass' }};
  fs.writeFileSync({json.dumps(str(tampered_report))}, JSON.stringify(tamperedReport, null, 2), 'utf8');

  const hubBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-download-hub-v0-1'));
  const auditBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-promotion-audit-v0-1'));
  const runnerHandoffBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const hubCountBefore = await page.locator('#hubCount').innerText();
  const auditCountBefore = await page.locator('#promotionAuditCount').innerText();

  await page.locator('#verifyLineageReportInput').setInputFiles({json.dumps(str(receipt_report))});
  await page.waitForFunction(() => {{
    const text = document.querySelector('#hubDiff').innerText;
    return text.includes('private_hub_lineage_report_receipt_verifier_report_v0_1') && JSON.parse(text).status === 'pass';
  }});
  const passReceiptReport = JSON.parse(await page.locator('#hubDiff').innerText());
  const passSummary = await page.locator('#hubVerificationSummary').innerText();
  const hubAfterPass = await page.evaluate(() => window.localStorage.getItem('agent-platform-download-hub-v0-1'));
  const auditAfterPass = await page.evaluate(() => window.localStorage.getItem('agent-platform-promotion-audit-v0-1'));
  const runnerHandoffAfterPass = await page.evaluate(() => window.localStorage.getItem('agent-platform-runner-handoff-v0-1'));

  await page.locator('#verifyLineageReportInput').setInputFiles({json.dumps(str(tampered_report))});
  await page.waitForFunction(() => {{
    const text = document.querySelector('#hubDiff').innerText;
    return text.includes('private_hub_lineage_report_receipt_verifier_report_v0_1') && JSON.parse(text).status === 'fail';
  }});
  const tamperReceiptReport = JSON.parse(await page.locator('#hubDiff').innerText());
  const tamperSummary = await page.locator('#hubVerificationSummary').innerText();
  const hubAfterTamper = await page.evaluate(() => window.localStorage.getItem('agent-platform-download-hub-v0-1'));
  const auditAfterTamper = await page.evaluate(() => window.localStorage.getItem('agent-platform-promotion-audit-v0-1'));
  const runnerHandoffAfterTamper = await page.evaluate(() => window.localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const hubCountAfter = await page.locator('#hubCount').innerText();
  const auditCountAfter = await page.locator('#promotionAuditCount').innerText();

  await browser.close();
  console.log(JSON.stringify({{
    originalReceiptChecksum: lineageVerifierReport.receipt_checksum,
    passReceiptReport,
    passSummary,
    tamperReceiptReport,
    tamperSummary,
    hubStorageUnchanged: hubBefore === hubAfterPass && hubAfterPass === hubAfterTamper,
    auditStorageUnchanged: auditBefore === auditAfterPass && auditAfterPass === auditAfterTamper,
    runnerHandoffBefore,
    runnerHandoffAfterPass,
    runnerHandoffAfterTamper,
    hubCountBefore,
    hubCountAfter,
    auditCountBefore,
    auditCountAfter,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    pass_report = payload["passReceiptReport"]
    tamper_report = payload["tamperReceiptReport"]
    _assert_lineage_report_receipt_verifier_contract(pass_report)
    _assert_lineage_report_receipt_verifier_contract(tamper_report)
    assert pass_report["status"] == "pass"
    assert pass_report["source_report_kind"] == "private_hub_lineage_card_verifier_report_v0_1"
    assert pass_report["source_receipt_checksum"] == payload["originalReceiptChecksum"]
    pass_checks = {check["name"]: check["status"] for check in pass_report["checks"]}
    assert pass_checks["receipt_checksum_matches_report"] == "pass"
    assert "Lineage report receipt" in payload["passSummary"]
    assert "status pass" in payload["passSummary"]
    assert "report only true" in payload["passSummary"]
    assert "side effects false" in payload["passSummary"]
    assert "storage write false" in payload["passSummary"]
    assert "runner handoff false" in payload["passSummary"]
    assert "installs false" in payload["passSummary"]
    assert "raw report false" in payload["passSummary"]
    assert "proof false" in payload["passSummary"]
    assert "sale false" in payload["passSummary"]
    assert "private_hub_lineage_card_verifier_report_v0_1" in payload["passSummary"]
    assert payload["originalReceiptChecksum"] in payload["passSummary"]
    assert "checks 5/5" in payload["passSummary"]
    assert "errors 0" in payload["passSummary"]
    assert tamper_report["status"] == "fail"
    assert tamper_report["source_report_kind"] == "private_hub_lineage_card_verifier_report_v0_1"
    assert tamper_report["source_receipt_checksum"] == payload["originalReceiptChecksum"]
    tamper_checks = {check["name"]: check["status"] for check in tamper_report["checks"]}
    assert tamper_checks["receipt_checksum_matches_report"] == "fail"
    assert "receipt_checksum" in " / ".join(tamper_report["errors"])
    assert "Lineage report receipt" in payload["tamperSummary"]
    assert "status fail" in payload["tamperSummary"]
    assert "report only true" in payload["tamperSummary"]
    assert "side effects false" in payload["tamperSummary"]
    assert "storage write false" in payload["tamperSummary"]
    assert "runner handoff false" in payload["tamperSummary"]
    assert "proof false" in payload["tamperSummary"]
    assert "sale false" in payload["tamperSummary"]
    assert payload["originalReceiptChecksum"] in payload["tamperSummary"]
    assert "checks 4/5" in payload["tamperSummary"]
    assert "errors 1" in payload["tamperSummary"]
    assert payload["hubStorageUnchanged"] is True
    assert payload["auditStorageUnchanged"] is True
    assert payload["runnerHandoffBefore"] is None
    assert payload["runnerHandoffAfterPass"] is None
    assert payload["runnerHandoffAfterTamper"] is None
    assert payload["hubCountBefore"] == payload["hubCountAfter"]
    assert payload["auditCountBefore"] == payload["auditCountAfter"]


def test_private_download_hub_downloads_current_lineage_verification_report(
    tmp_path: Path,
) -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node ?ㅽ뻾 ?뚯씪??李얠쓣 ???놁뼱 釉뚮씪?곗? ?먮룞 ?뚯뒪?몃? 嫄대꼫?곷땲??")
    if not chrome:
        pytest.skip("Chrome ?먮뒗 Edge ?ㅽ뻾 ?뚯씪??李얠쓣 ???놁뼱 釉뚮씪?곗? ?먮룞 ?뚯뒪?몃? 嫄대꼫?곷땲??")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright ?⑦궎吏瑜?李얠쓣 ???놁뼱 釉뚮씪?곗? ?먮룞 ?뚯뒪?몃? 嫄대꼫?곷땲??")

    lineage_card = tmp_path / "download-report-source.private-hub-lineage-card.json"
    downloaded_report = tmp_path / "downloaded-lineage-verifier-report.json"
    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const fs = require('fs');
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#importHubInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTED))});
  await page.waitForFunction(() => document.querySelector('#hubCount').innerText !== '0');
  await page.locator('#importPromotionRecordInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTION_RECORD))});
  await page.waitForFunction(() => document.querySelector('#promotionAuditCount').innerText !== '0');

  const lineageDownloadPromise = page.waitForEvent('download');
  await page.locator('[data-hub-lineage-download="0"]').click();
  const lineageDownload = await lineageDownloadPromise;
  const lineageDownloadPath = await lineageDownload.path();
  fs.copyFileSync(lineageDownloadPath, {json.dumps(str(lineage_card))});

  await page.locator('#verifyLineageCardInput').setInputFiles({json.dumps(str(lineage_card))});
  await page.waitForFunction(() => document.querySelector('#hubDiff').innerText.includes('private_hub_lineage_card_verifier_report_v0_1'));
  const originalReport = JSON.parse(await page.locator('#hubDiff').innerText());

  const hubBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-download-hub-v0-1'));
  const auditBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-promotion-audit-v0-1'));
  const runnerHandoffBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const hubCountBefore = await page.locator('#hubCount').innerText();
  const auditCountBefore = await page.locator('#promotionAuditCount').innerText();

  const reportDownloadPromise = page.waitForEvent('download');
  await page.locator('#downloadVerificationReportButton').click();
  const reportDownload = await reportDownloadPromise;
  const suggestedFilename = reportDownload.suggestedFilename();
  const reportDownloadPath = await reportDownload.path();
  fs.copyFileSync(reportDownloadPath, {json.dumps(str(downloaded_report))});
  const downloadedReport = JSON.parse(fs.readFileSync({json.dumps(str(downloaded_report))}, 'utf8'));

  await page.locator('#verifyLineageReportInput').setInputFiles({json.dumps(str(downloaded_report))});
  await page.waitForFunction(() => {{
    const text = document.querySelector('#hubDiff').innerText;
    return text.includes('private_hub_lineage_report_receipt_verifier_report_v0_1') && JSON.parse(text).status === 'pass';
  }});
  const receiptVerifierReport = JSON.parse(await page.locator('#hubDiff').innerText());
  const receiptVerifierSummary = await page.locator('#hubVerificationSummary').innerText();

  const hubAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-download-hub-v0-1'));
  const auditAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-promotion-audit-v0-1'));
  const runnerHandoffAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const hubCountAfter = await page.locator('#hubCount').innerText();
  const auditCountAfter = await page.locator('#promotionAuditCount').innerText();

  await browser.close();
  console.log(JSON.stringify({{
    originalReport,
    downloadedReport,
    receiptVerifierReport,
    receiptVerifierSummary,
    suggestedFilename,
    hubStorageUnchanged: hubBefore === hubAfter,
    auditStorageUnchanged: auditBefore === auditAfter,
    runnerHandoffBefore,
    runnerHandoffAfter,
    hubCountBefore,
    hubCountAfter,
    auditCountBefore,
    auditCountAfter,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    original_report = payload["originalReport"]
    downloaded = payload["downloadedReport"]
    receipt_report = payload["receiptVerifierReport"]
    _assert_lineage_verifier_receipt_contract(downloaded)
    _assert_lineage_report_receipt_verifier_contract(receipt_report)
    assert downloaded == original_report
    assert payload["suggestedFilename"].endswith(".lineage-verifier-report.json")
    assert downloaded["receipt_checksum"] in payload["suggestedFilename"]
    assert receipt_report["status"] == "pass"
    assert receipt_report["source_receipt_checksum"] == downloaded["receipt_checksum"]
    assert "Lineage report receipt" in payload["receiptVerifierSummary"]
    assert "status pass" in payload["receiptVerifierSummary"]
    assert "report only true" in payload["receiptVerifierSummary"]
    assert "side effects false" in payload["receiptVerifierSummary"]
    assert "storage write false" in payload["receiptVerifierSummary"]
    assert "runner handoff false" in payload["receiptVerifierSummary"]
    assert "raw report false" in payload["receiptVerifierSummary"]
    assert "proof false" in payload["receiptVerifierSummary"]
    assert "sale false" in payload["receiptVerifierSummary"]
    assert downloaded["receipt_checksum"] in payload["receiptVerifierSummary"]
    assert "checks 5/5" in payload["receiptVerifierSummary"]
    assert "errors 0" in payload["receiptVerifierSummary"]
    assert payload["hubStorageUnchanged"] is True
    assert payload["auditStorageUnchanged"] is True
    assert payload["runnerHandoffBefore"] is None
    assert payload["runnerHandoffAfter"] is None
    assert payload["hubCountBefore"] == payload["hubCountAfter"]
    assert payload["auditCountBefore"] == payload["auditCountAfter"]


def test_private_download_hub_rejects_bad_lineage_report_receipts_without_echo_or_side_effects(
    tmp_path: Path,
) -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node ?ㅽ뻾 ?뚯씪??李얠쓣 ???놁뼱 釉뚮씪?곗? ?먮룞 ?뚯뒪?몃? 嫄대꼫?곷땲??")
    if not chrome:
        pytest.skip("Chrome ?먮뒗 Edge ?ㅽ뻾 ?뚯씪??李얠쓣 ???놁뼱 釉뚮씪?곗? ?먮룞 ?뚯뒪?몃? 嫄대꼫?곷땲??")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright ?⑦궎吏瑜?李얠쓣 ???놁뼱 釉뚮씪?곗? ?먮룞 ?뚯뒪?몃? 嫄대꼫?곷땲??")

    malformed_report = tmp_path / "malformed-lineage-verifier-report.json"
    non_report = tmp_path / "non-lineage-verifier-report.json"
    malformed_report.write_text("{ not valid report json", encoding="utf-8")
    non_report.write_text(
        json.dumps(
            {
                "report_kind": "private_customer_invoice_v9",
                "agent_id": "sensitive-agent-id",
                "version_label": "sensitive-version-label",
                "source_report_kind": "sensitive-source-kind",
                "source_receipt_checksum": "lvr-sensitive-checksum",
                "raw_report": "do-not-echo-raw-report",
                "raw_inputs": "do-not-echo-inputs",
                "raw_outputs": "do-not-echo-outputs",
                "secret": "do-not-echo-secret",
                "receipt_checksum": "lvr-sensitive-checksum",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#importHubInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTED))});
  await page.waitForFunction(() => document.querySelector('#hubCount').innerText !== '0');
  await page.locator('#importPromotionRecordInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTION_RECORD))});
  await page.waitForFunction(() => document.querySelector('#promotionAuditCount').innerText !== '0');

  const hubBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-download-hub-v0-1'));
  const auditBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-promotion-audit-v0-1'));
  const runnerHandoffBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const hubCountBefore = await page.locator('#hubCount').innerText();
  const auditCountBefore = await page.locator('#promotionAuditCount').innerText();

  await page.locator('#verifyLineageReportInput').setInputFiles({json.dumps(str(malformed_report))});
  await page.waitForFunction(() => {{
    const text = document.querySelector('#hubDiff').innerText;
    return text.includes('private_hub_lineage_report_receipt_verifier_report_v0_1') && JSON.parse(text).status === 'fail';
  }});
  const malformedReceiptReport = JSON.parse(await page.locator('#hubDiff').innerText());

  await page.locator('#verifyLineageReportInput').setInputFiles({json.dumps(str(non_report))});
  await page.waitForFunction(() => {{
    const text = document.querySelector('#hubDiff').innerText;
    if (!text.includes('private_hub_lineage_report_receipt_verifier_report_v0_1')) return false;
    const report = JSON.parse(text);
    return report.status === 'fail' && report.errors.join(' / ').includes('report_kind');
  }});
  const nonReportReceiptReportText = await page.locator('#hubDiff').innerText();
  const nonReportReceiptReport = JSON.parse(nonReportReceiptReportText);

  const hubAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-download-hub-v0-1'));
  const auditAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-promotion-audit-v0-1'));
  const runnerHandoffAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const hubCountAfter = await page.locator('#hubCount').innerText();
  const auditCountAfter = await page.locator('#promotionAuditCount').innerText();

  await browser.close();
  console.log(JSON.stringify({{
    malformedReceiptReport,
    nonReportReceiptReport,
    nonReportReceiptReportText,
    hubStorageUnchanged: hubBefore === hubAfter,
    auditStorageUnchanged: auditBefore === auditAfter,
    runnerHandoffBefore,
    runnerHandoffAfter,
    hubCountBefore,
    hubCountAfter,
    auditCountBefore,
    auditCountAfter,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    malformed = payload["malformedReceiptReport"]
    non_report_result = payload["nonReportReceiptReport"]
    non_report_text = payload["nonReportReceiptReportText"]
    _assert_lineage_report_receipt_verifier_contract(malformed)
    _assert_lineage_report_receipt_verifier_contract(non_report_result)
    assert malformed["status"] == "fail"
    assert malformed["source_report_kind"] == "unknown"
    assert malformed["source_receipt_checksum"] == "unknown"
    assert malformed["checks"] == []
    assert non_report_result["status"] == "fail"
    assert non_report_result["source_report_kind"] == "unknown"
    assert non_report_result["source_receipt_checksum"] == "unknown"
    checks = {check["name"]: check["status"] for check in non_report_result["checks"]}
    assert checks["report_kind_matches_lineage_verifier_report"] == "fail"
    assert checks["receipt_checksum_matches_report"] == "fail"
    for forbidden in [
        "sensitive-agent-id",
        "sensitive-version-label",
        "sensitive-source-kind",
        "lvr-sensitive-checksum",
        "do-not-echo-raw-report",
        "do-not-echo-inputs",
        "do-not-echo-outputs",
        "do-not-echo-secret",
    ]:
        assert forbidden not in non_report_text
    assert payload["hubStorageUnchanged"] is True
    assert payload["auditStorageUnchanged"] is True
    assert payload["runnerHandoffBefore"] is None
    assert payload["runnerHandoffAfter"] is None
    assert payload["hubCountBefore"] == payload["hubCountAfter"]
    assert payload["auditCountBefore"] == payload["auditCountAfter"]


def test_private_download_hub_malformed_lineage_card_reports_fail_without_side_effects(
    tmp_path: Path,
) -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")

    malformed_lineage = tmp_path / "malformed.private-hub-lineage-card.json"
    malformed_lineage.write_text("{ not valid lineage json", encoding="utf-8")
    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#importHubInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTED))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('가져오기 완료'));
  await page.locator('#importPromotionRecordInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTION_RECORD))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('승격 기록 가져오기 완료'));

  await page.locator('[data-hub-lineage="0"]').click();
  const previousReport = await page.locator('#hubDiff').innerText();

  const hubBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-download-hub-v0-1'));
  const auditBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-promotion-audit-v0-1'));
  const runnerHandoffBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const hubCountBefore = await page.locator('#hubCount').innerText();
  const auditCountBefore = await page.locator('#promotionAuditCount').innerText();

  await page.locator('#verifyLineageCardInput').setInputFiles({json.dumps(str(malformed_lineage))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('lineage card 검증 실패'));

  const status = await page.locator('#hubImportStatus').innerText();
  const report = await page.locator('#hubDiff').innerText();
  const hubAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-download-hub-v0-1'));
  const auditAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-promotion-audit-v0-1'));
  const runnerHandoffAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const hubCountAfter = await page.locator('#hubCount').innerText();
  const auditCountAfter = await page.locator('#promotionAuditCount').innerText();

  await browser.close();
  console.log(JSON.stringify({{
    previousReport,
    status,
    report,
    hubStorageUnchanged: hubBefore === hubAfter,
    auditStorageUnchanged: auditBefore === auditAfter,
    runnerHandoffBefore,
    runnerHandoffAfter,
    hubCountBefore,
    hubCountAfter,
    auditCountBefore,
    auditCountAfter,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    report = json.loads(payload["report"])
    assert "private_hub_lineage_card_v0_1" in payload["previousReport"]
    assert "lineage card 검증 실패" in payload["status"]
    assert "JSON 파일을 읽거나 해석하지 못했습니다" in payload["status"]
    assert report["report_kind"] == "private_hub_lineage_card_verifier_report_v0_1"
    assert report["report_version"] == "0.1"
    assert report["verifier"] == "private_hub_lineage_card_verifier_v0_1"
    assert report["status"] == "fail"
    assert report["effect"] == "report_only"
    assert report["side_effects"] == {
        "hub_storage_write": False,
        "promotion_audit_storage_write": False,
        "runner_handoff_write": False,
        "installs_or_runs_agent": False,
    }
    assert report["report_privacy"] == {
        "stores_raw_card": False,
        "stores_raw_inputs": False,
        "stores_raw_outputs": False,
        "stores_secrets": False,
        "echoes_non_lineage_identity": False,
    }
    _assert_lineage_verifier_receipt_contract(report)
    assert report["agent_id"] == "unknown"
    assert report["version_label"] == "unknown"
    assert report["checks"] == []
    assert "JSON 파일을 읽거나 해석하지 못했습니다." in report["errors"]
    assert payload["hubStorageUnchanged"] is True
    assert payload["auditStorageUnchanged"] is True
    assert payload["runnerHandoffBefore"] is None
    assert payload["runnerHandoffAfter"] is None
    assert payload["hubCountBefore"] == payload["hubCountAfter"]
    assert payload["auditCountBefore"] == payload["auditCountAfter"]


def test_private_download_hub_rejects_non_lineage_json_without_side_effects() -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")

    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#importHubInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTED))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('가져오기 완료'));
  await page.locator('#importPromotionRecordInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTION_RECORD))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('승격 기록 가져오기 완료'));

  const hubBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-download-hub-v0-1'));
  const auditBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-promotion-audit-v0-1'));
  const runnerHandoffBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const hubCountBefore = await page.locator('#hubCount').innerText();
  const auditCountBefore = await page.locator('#promotionAuditCount').innerText();

  await page.locator('#verifyLineageCardInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTED))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('lineage card 검증 실패'));

  const status = await page.locator('#hubImportStatus').innerText();
  const report = await page.locator('#hubDiff').innerText();
  const hubAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-download-hub-v0-1'));
  const auditAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-promotion-audit-v0-1'));
  const runnerHandoffAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const hubCountAfter = await page.locator('#hubCount').innerText();
  const auditCountAfter = await page.locator('#promotionAuditCount').innerText();

  await browser.close();
  console.log(JSON.stringify({{
    status,
    report,
    hubStorageUnchanged: hubBefore === hubAfter,
    auditStorageUnchanged: auditBefore === auditAfter,
    runnerHandoffBefore,
    runnerHandoffAfter,
    hubCountBefore,
    hubCountAfter,
    auditCountBefore,
    auditCountAfter,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    report = json.loads(payload["report"])
    errors = " / ".join(report["errors"])
    assert "lineage card 검증 실패" in payload["status"]
    assert report["report_kind"] == "private_hub_lineage_card_verifier_report_v0_1"
    assert report["report_version"] == "0.1"
    assert report["verifier"] == "private_hub_lineage_card_verifier_v0_1"
    assert report["status"] == "fail"
    assert report["effect"] == "report_only"
    assert report["side_effects"] == {
        "hub_storage_write": False,
        "promotion_audit_storage_write": False,
        "runner_handoff_write": False,
        "installs_or_runs_agent": False,
    }
    assert report["report_privacy"] == {
        "stores_raw_card": False,
        "stores_raw_inputs": False,
        "stores_raw_outputs": False,
        "stores_secrets": False,
        "echoes_non_lineage_identity": False,
    }
    _assert_lineage_verifier_receipt_contract(report)
    assert report["agent_id"] == "unknown"
    assert report["version_label"] == "unknown"
    assert report["checks"] == []
    assert "card_kind" in errors
    assert "agent_id" in errors
    assert "Hub" in errors
    assert payload["hubStorageUnchanged"] is True
    assert payload["auditStorageUnchanged"] is True
    assert payload["runnerHandoffBefore"] is None
    assert payload["runnerHandoffAfter"] is None
    assert payload["hubCountBefore"] == payload["hubCountAfter"]
    assert payload["auditCountBefore"] == payload["auditCountAfter"]


def test_private_download_hub_non_lineage_json_does_not_echo_sensitive_fields(
    tmp_path: Path,
) -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")

    sensitive_marker = "SHOULD_NOT_ECHO_SECRET_9f7c"
    non_lineage_json = tmp_path / "sensitive-non-lineage.json"
    non_lineage_json.write_text(
        json.dumps(
            {
                "card_kind": "agent_pack_bundle_v0_1",
                "agent_id": sensitive_marker,
                "version_label": f"{sensitive_marker}_version",
                "files": {
                    "instructions.md": f"raw user text {sensitive_marker}",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#importHubInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTED))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('가져오기 완료'));
  await page.locator('#importPromotionRecordInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTION_RECORD))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('승격 기록 가져오기 완료'));

  const hubBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-download-hub-v0-1'));
  const auditBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-promotion-audit-v0-1'));
  const runnerHandoffBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const hubCountBefore = await page.locator('#hubCount').innerText();
  const auditCountBefore = await page.locator('#promotionAuditCount').innerText();

  await page.locator('#verifyLineageCardInput').setInputFiles({json.dumps(str(non_lineage_json))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('lineage card 검증 실패'));

  const status = await page.locator('#hubImportStatus').innerText();
  const report = await page.locator('#hubDiff').innerText();
  const hubAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-download-hub-v0-1'));
  const auditAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-promotion-audit-v0-1'));
  const runnerHandoffAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const hubCountAfter = await page.locator('#hubCount').innerText();
  const auditCountAfter = await page.locator('#promotionAuditCount').innerText();

  await browser.close();
  console.log(JSON.stringify({{
    status,
    report,
    hubStorageUnchanged: hubBefore === hubAfter,
    auditStorageUnchanged: auditBefore === auditAfter,
    runnerHandoffBefore,
    runnerHandoffAfter,
    hubCountBefore,
    hubCountAfter,
    auditCountBefore,
    auditCountAfter,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    report = json.loads(payload["report"])
    combined_output = f"{payload['status']}\n{payload['report']}"
    assert "lineage card 검증 실패" in payload["status"]
    assert report["status"] == "fail"
    assert report["agent_id"] == "unknown"
    assert report["version_label"] == "unknown"
    assert sensitive_marker not in combined_output
    assert payload["hubStorageUnchanged"] is True
    assert payload["auditStorageUnchanged"] is True
    assert payload["runnerHandoffBefore"] is None
    assert payload["runnerHandoffAfter"] is None
    assert payload["hubCountBefore"] == payload["hubCountAfter"]
    assert payload["auditCountBefore"] == payload["auditCountAfter"]


def test_private_download_hub_rejects_non_object_json_without_side_effects(
    tmp_path: Path,
) -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 자동 테스트를 건너뜁니다.")

    array_json = tmp_path / "array-lineage-input.json"
    string_json = tmp_path / "string-lineage-input.json"
    array_json.write_text(json.dumps(["SHOULD_NOT_ECHO_ARRAY_SECRET"], indent=2) + "\n", encoding="utf-8")
    string_json.write_text(json.dumps("SHOULD_NOT_ECHO_STRING_SECRET") + "\n", encoding="utf-8")

    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#importHubInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTED))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('가져오기 완료'));
  await page.locator('#importPromotionRecordInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTION_RECORD))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('승격 기록 가져오기 완료'));

  const hubBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-download-hub-v0-1'));
  const auditBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-promotion-audit-v0-1'));
  const runnerHandoffBefore = await page.evaluate(() => window.localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const hubCountBefore = await page.locator('#hubCount').innerText();
  const auditCountBefore = await page.locator('#promotionAuditCount').innerText();

  await page.locator('#verifyLineageCardInput').setInputFiles({json.dumps(str(array_json))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('lineage card 검증 실패'));
  const arrayStatus = await page.locator('#hubImportStatus').innerText();
  const arrayReport = await page.locator('#hubDiff').innerText();

  await page.locator('#verifyLineageCardInput').setInputFiles({json.dumps(str(string_json))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('lineage card 검증 실패'));
  const stringStatus = await page.locator('#hubImportStatus').innerText();
  const stringReport = await page.locator('#hubDiff').innerText();

  const hubAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-download-hub-v0-1'));
  const auditAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-promotion-audit-v0-1'));
  const runnerHandoffAfter = await page.evaluate(() => window.localStorage.getItem('agent-platform-runner-handoff-v0-1'));
  const hubCountAfter = await page.locator('#hubCount').innerText();
  const auditCountAfter = await page.locator('#promotionAuditCount').innerText();

  await browser.close();
  console.log(JSON.stringify({{
    arrayStatus,
    arrayReport,
    stringStatus,
    stringReport,
    hubStorageUnchanged: hubBefore === hubAfter,
    auditStorageUnchanged: auditBefore === auditAfter,
    runnerHandoffBefore,
    runnerHandoffAfter,
    hubCountBefore,
    hubCountAfter,
    auditCountBefore,
    auditCountAfter,
  }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    array_report = json.loads(payload["arrayReport"])
    string_report = json.loads(payload["stringReport"])
    combined_output = "\n".join(
        [
            payload["arrayStatus"],
            payload["arrayReport"],
            payload["stringStatus"],
            payload["stringReport"],
        ]
    )
    assert "lineage card 검증 실패" in payload["arrayStatus"]
    assert "lineage card 검증 실패" in payload["stringStatus"]
    assert array_report["status"] == "fail"
    assert string_report["status"] == "fail"
    assert array_report["agent_id"] == "unknown"
    assert string_report["agent_id"] == "unknown"
    assert array_report["checks"] == []
    assert string_report["checks"] == []
    assert "lineage card 객체" in " / ".join(array_report["errors"])
    assert "lineage card 객체" in " / ".join(string_report["errors"])
    assert "SHOULD_NOT_ECHO_ARRAY_SECRET" not in combined_output
    assert "SHOULD_NOT_ECHO_STRING_SECRET" not in combined_output
    assert payload["hubStorageUnchanged"] is True
    assert payload["auditStorageUnchanged"] is True
    assert payload["runnerHandoffBefore"] is None
    assert payload["runnerHandoffAfter"] is None
    assert payload["hubCountBefore"] == payload["hubCountAfter"]
    assert payload["auditCountBefore"] == payload["auditCountAfter"]


def test_private_download_hub_does_not_link_mismatched_promotion_record(tmp_path: Path) -> None:
    node = _node_path()
    node_modules = _node_modules_path()
    chrome = _chrome_path()
    if not node:
        pytest.skip("Node 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not chrome:
        pytest.skip("Chrome 또는 Edge 실행 파일을 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")
    if not _playwright_available(node, node_modules):
        pytest.skip("playwright 패키지를 찾을 수 없어 브라우저 흐름 테스트를 건너뜁니다.")

    mismatched = json.loads(SAMPLE_PROMOTION_RECORD.read_text(encoding="utf-8"))
    mismatched["source"]["promoted_pack_hash"] = "sha256:" + "0" * 64
    mismatched_record = tmp_path / "mismatched.candidate-promotion-record.json"
    mismatched_record.write_text(json.dumps(mismatched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    env = dict(os.environ)
    if node_modules:
        env["NODE_PATH"] = str(node_modules)
    script = f"""
const {{ chromium }} = require('playwright');
const {{ pathToFileURL }} = require('url');

(async () => {{
  const browser = await chromium.launch({{
    executablePath: {json.dumps(str(chrome))},
    headless: true,
    args: ['--no-sandbox'],
  }});
  const page = await browser.newPage();
  await page.goto(pathToFileURL({json.dumps(str(PLATFORM))}).href);

  await page.locator('#importHubInput').setInputFiles({json.dumps(str(SAMPLE_PROMOTED))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('가져오기 완료'));
  await page.locator('#importPromotionRecordInput').setInputFiles({json.dumps(str(mismatched_record))});
  await page.waitForFunction(() => document.querySelector('#hubImportStatus').innerText.includes('승격 기록 가져오기 완료'));

  const auditStatus = await page.locator('#hubImportStatus').innerText();
  const lifecycleText = await page.locator('.hub-lifecycle').first().innerText();
  const auditText = await page.locator('#promotionAuditList').innerText();
  const detail = await page.locator('.hub-meta').first().innerText();
  const auditSummary = await page.locator('#hubVerificationSummary').innerText();

  await browser.close();
  console.log(JSON.stringify({{ auditStatus, lifecycleText, auditText, detail, auditSummary }}));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        [str(node), "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert "promoted pack 해시가 일치하는 Hub 패키지" in payload["auditStatus"]
    assert "Promotion audit import" in payload["auditSummary"]
    assert "promoted hash mismatch" in payload["auditSummary"]
    assert "local only true" in payload["auditSummary"]
    assert "server sync false" in payload["auditSummary"]
    assert "runtime send false" in payload["auditSummary"]
    assert "proof false" in payload["auditSummary"]
    assert "sale false" in payload["auditSummary"]
    assert "user command true" in payload["auditSummary"]
    assert "promoted_private_version" in payload["auditSummary"]
    assert "promoted sha256:" in payload["auditSummary"]
    assert "promoted hash mismatch" in payload["auditText"]
    assert "audit 1" not in payload["lifecycleText"]
    assert "promotion audit verified" not in payload["detail"]
