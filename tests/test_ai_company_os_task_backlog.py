from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_DOCS = ROOT / "docs" / "product"
BACKLOG = PRODUCT_DOCS / "45_AI_COMPANY_OS_TASK_BACKLOG.md"
INDEX = PRODUCT_DOCS / "00_INDEX.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _task_section(text: str, task_id: str) -> str:
    marker = f"### {task_id}"
    start = text.index(marker)
    next_start = text.find("\n### OS-", start + len(marker))
    if next_start == -1:
        return text[start:]
    return text[start:next_start]


def _first_pending_task_id(text: str) -> str:
    pattern = re.compile(r"^### (OS-\d{2})\s+[^\n]+\n(?P<body>.*?)(?=^### OS-\d{2}\s+|\Z)", re.M | re.S)
    for match in pattern.finditer(text):
        if re.search(r"^status:\s*pending\s*$", match.group("body"), re.M):
            return match.group(1)
    return "none"


def test_ai_company_os_task_backlog_is_indexed_as_next_step_source() -> None:
    backlog = _read(BACKLOG)
    index = _read(INDEX)

    assert "# AI Company OS Task Backlog" in backlog
    assert "next_step_rule:" in backlog
    assert "source_of_truth: docs/product/45_AI_COMPANY_OS_TASK_BACKLOG.md" in backlog
    assert "select the first task with status: pending" in backlog
    assert f"current_next_task: {_first_pending_task_id(backlog)}" in backlog

    assert "45_AI_COMPANY_OS_TASK_BACKLOG.md" in index
    assert "Next-step task source-of-truth:" in index
    assert index.index("42_TEN_YEAR_ARCHITECTURE.md") < index.index("45_AI_COMPANY_OS_TASK_BACKLOG.md")


def test_ai_company_os_task_backlog_tasks_keep_required_contract() -> None:
    text = _read(BACKLOG)
    required_fields = [
        "status:",
        "why:",
        "goal:",
        "implementation:",
        "completion_criteria:",
        "tests:",
        "evidence:",
        "next_task:",
    ]

    for task_number in range(1, 14):
        task_id = f"OS-{task_number:02d}"
        section = _task_section(text, task_id)
        for field in required_fields:
            assert field in section, f"{task_id} is missing {field}"

    assert text.index("OS-01 Mission Control") < text.index("OS-02 24H Auto Completion Loop")
    assert text.index("OS-09 Relearning / Promotion Gate") < text.index(
        "OS-10 Company Snapshot / Marketplace-Ready Artifact"
    )
    assert text.index("OS-10 Company Snapshot / Marketplace-Ready Artifact") < text.index(
        "OS-11 First External Recipient Proof"
    )
    assert text.index("OS-11 First External Recipient Proof") < text.index("OS-12 One Good Harness Generalization")
    assert text.index("OS-12 One Good Harness Generalization") < text.index(
        "OS-13 Docs Authority / Scanner Truth Hardening"
    )
    assert "current_next_task: OS-11" in text

    os11 = _task_section(text, "OS-11")
    assert "cambrian mcp verify --receipt dist/mcp_operability_receipt.json" in os11
    assert "python scripts/verify_mcp_operability.py --receipt dist/mcp_operability_receipt.json" in os11
    assert "docs/release/MCP_EXTERNAL_CLIENT_CONNECT.md" in os11
    assert "freshly installed `cambrian-mcp` entry point" in os11
    assert "no arbitrary shell" in os11
    assert "operator_launch_snapshot" in os11
    assert "cambrian-install-kit-first-recipient-operator-status.md" in os11
    assert "controlled command use order" in os11
    assert "post-send recipient checkpoint command" in os11
    assert "workspace and operator status body hashes now exclude `generated_at`" in os11
    assert "handoff, send-ready, dispatch-record, recipient-checkpoint" in os11
    assert "fixed synthetic `sent_at_utc`" in os11
    assert "private runbook now names the operator status board" in os11
    assert "current status remains `FILL_PRIVATE_FIELDS`" in os11
    assert "current first-recipient pre-send sequence remains safely blocked" in os11
    assert "controlled `human_next_steps`" in os11
    assert "current first-recipient post-send sequence remains safely blocked" in os11
    assert "25 passed, 78 deselected" in os11
    assert "104 passed" in os11
    assert "operator-facing recipient checkpoint commands now omit `--skip-verify`" in os11
    assert "`--skip-verify` is reserved for synthetic regression tests" in os11
    assert "install-kit synthetic recipient checkpoints now carry the same rehearsal boundary" in os11
    assert "external alpha synthetic recipient checkpoints now carry the same rehearsal boundary" in os11
    assert "requires `synthetic_dispatch_not_standalone_proof`" in os11
    assert "release docs and RC checklist now explicitly state" in os11
    assert "local validation evidence only, not public proof" in os11
    assert "standalone bundle verifier now require the recipient-facing claim-boundary lines" in os11
    assert "handoff and send-ready copy-paste messages now carry the same claim boundary" in os11
    assert "standalone bundle verifier now also require the handoff/send-ready copy-paste claim boundary" in os11
    assert "release bundle sha256 `ba629ea6a4db04c43b7f7e1cc7128952b3a1ab3f59805cdc68af25314477bfd9`" in os11
    assert "dispatch-record now preserves a hashed copy-paste message policy" in os11
    assert "recipient-checkpoint now preserves the dispatch copy-paste boundary" in os11
    assert "first-recipient post-send sequence now mirrors a recorded recipient-checkpoint copy-paste boundary" in os11
    assert "install-kit dispatch-record is `READY_TO_SEND_ONE`" in os11
    assert "install-kit recipient-checkpoint remains `WAITING_FOR_RECIPIENT`" in os11
    assert "`blocking_summary.missing_evidence`" in os11
    assert "`SENT_ONE_RECORDED dispatch record` is the first missing proof" in os11
    assert "pending real first-recipient MCP operability receipt" in os11
    assert "Marketplace" in text
