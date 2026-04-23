"""Cambrian project mode 다음 명령 도우미."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class NextCommand:
    """복사 가능한 다음 명령 하나를 표현한다."""

    label: str
    command: str
    reason: str
    stage: str | None = None
    primary: bool = False
    requires_user_input: bool = False

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


def quote_cli_arg(value: str) -> str:
    """CLI 인자를 단순하게 감싼다."""
    text = str(value)
    if not text:
        return '""'
    needs_quote = any(char.isspace() for char in text) or any(char in text for char in ['"', "'"])
    if not needs_quote:
        return text
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def extract_copyable_command(action: str) -> str | None:
    """설명 문자열에서 실행 가능한 cambrian 명령만 뽑는다."""
    text = str(action or "").strip()
    if not text:
        return None
    if text.startswith("cambrian "):
        return text
    if text.startswith("Run `") and text.endswith("`"):
        candidate = text[5:-1].strip()
        return candidate if candidate.startswith("cambrian ") else None
    if text.startswith("Run "):
        candidate = text[4:].strip()
        return candidate if candidate.startswith("cambrian ") else None
    return None


def _requires_user_input(command: str) -> bool:
    """명령이 추가 사용자 입력을 요구하는지 추정한다."""
    placeholders = ("...", "<", "path/to/", "describe", "next request")
    lowered = command.lower()
    return any(token in lowered for token in placeholders)


def _label_for_command(command: str, stage: str | None, index: int) -> str:
    """명령 문자열로 기본 라벨을 만든다."""
    lowered = command.lower()
    if " init " in f" {lowered} " or lowered.startswith("cambrian init"):
        return "프로젝트 하네스 초기화"
    if "demo create" in lowered:
        return "demo 프로젝트 만들기"
    if "do --continue --use-suggestion" in lowered:
        return "상단 제안으로 진단 시작"
    if "do --continue --execute" in lowered:
        return "진단 실행"
    if "patch intent-fill" in lowered:
        return "patch intent 채우기"
    if "patch propose" in lowered:
        return "patch proposal 만들기"
    if "patch apply" in lowered:
        return "검증된 patch 적용"
    if "memory rebuild" in lowered:
        return "project memory 다시 만들기"
    if lowered.startswith("cambrian status"):
        return "현재 상태 보기"
    if lowered.startswith("cambrian clarify"):
        return "clarification 답변"
    if lowered.startswith("cambrian do --continue"):
        return "현재 작업 계속하기"
    if lowered.startswith("cambrian do "):
        return "새 요청 시작하기"
    if lowered.startswith("cambrian run "):
        return "요청 준비하기"
    if lowered.startswith("cambrian brain run"):
        return "생성된 작업 실행"
    if index == 0 and stage:
        return f"{stage} 다음 단계"
    return f"다음 명령 {index + 1}"


def _reason_for_stage(stage: str | None) -> str:
    """stage별 기본 이유를 만든다."""
    mapping = {
        "initialized_required": "프로젝트가 아직 Cambrian에 맞춰지지 않았습니다.",
        "clarification_open": "관련 source와 test 후보가 준비되어 있습니다.",
        "needs_context": "작업 전에 source나 test 문맥이 더 필요합니다.",
        "diagnose_ready": "diagnose-only 작업이 준비되었습니다.",
        "diagnosed": "진단이 끝나 다음 patch 단계로 넘어갈 수 있습니다.",
        "patch_intent_draft": "바꿀 old_text와 new_text를 채우면 proposal을 만들 수 있습니다.",
        "patch_intent_ready": "patch intent가 준비되어 proposal 생성이 가능합니다.",
        "patch_proposal_ready": "proposal이 있어 검증 단계로 이어갈 수 있습니다.",
        "patch_proposal_validated": "검증된 proposal을 명시적으로 적용할 수 있습니다.",
        "adopted": "최근 작업이 끝났고 상태를 확인하면 됩니다.",
    }
    return mapping.get(stage or "", "현재 단계에서 이어갈 수 있는 명령입니다.")


class NextCommandBuilder:
    """문자열 next action을 구조화된 next command로 바꾼다."""

    @classmethod
    def from_actions(
        cls,
        actions: list[str],
        *,
        stage: str | None = None,
        primary_index: int = 0,
    ) -> list[dict]:
        """설명/명령 목록에서 copyable next command 배열을 만든다."""
        commands: list[dict] = []
        seen: set[str] = set()
        for index, action in enumerate(actions):
            command = extract_copyable_command(action)
            if not command or command in seen:
                continue
            seen.add(command)
            entry = NextCommand(
                label=_label_for_command(command, stage, index),
                command=command,
                reason=_reason_for_stage(stage),
                stage=stage,
                primary=len(commands) == primary_index,
                requires_user_input=_requires_user_input(command),
            )
            commands.append(entry.to_dict())
        if commands:
            commands[0]["primary"] = True
        return commands

    @classmethod
    def for_init_completed(cls) -> list[dict]:
        """init 완료 직후 기본 명령."""
        return cls.from_actions(
            [
                'cambrian do "fix a small bug"',
                "cambrian status",
            ],
            stage="initialized",
        )

    @classmethod
    def for_not_initialized(cls) -> list[dict]:
        """초기화 전 기본 명령."""
        return cls.from_actions(
            ["cambrian init --wizard"],
            stage="initialized_required",
        )

    @classmethod
    def for_status_default(cls, request: str) -> list[dict]:
        """active session이 없을 때 기본 요청 명령."""
        return cls.from_actions(
            [f"cambrian do {quote_cli_arg(request)}"],
            stage="idle",
        )


def primary_next_command(next_commands: list[dict]) -> dict | None:
    """primary next command 하나를 고른다."""
    if not next_commands:
        return None
    for item in next_commands:
        if isinstance(item, dict) and item.get("primary"):
            return dict(item)
    first = next_commands[0]
    return dict(first) if isinstance(first, dict) else None
