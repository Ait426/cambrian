"""간단한 TODO CLI 유틸리티.

테스트, 린트, 타입체킹, CI, 문서가 모두 없는 상태로
Cambrian scan이 capability gap을 올바르게 감지하는지 검증하기 위한 샘플.
"""

import json
import sys
from pathlib import Path

DB_FILE = "todos.json"


def load_todos() -> list[dict]:
    """할 일 목록을 파일에서 로드한다."""
    if Path(DB_FILE).exists():
        return json.loads(Path(DB_FILE).read_text(encoding="utf-8"))
    return []


def save_todos(todos: list[dict]) -> None:
    """할 일 목록을 파일에 저장한다."""
    Path(DB_FILE).write_text(
        json.dumps(todos, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def add_todo(title: str) -> None:
    """새 할 일을 추가한다."""
    todos = load_todos()
    todos.append({"title": title, "done": False})
    save_todos(todos)
    print(f"Added: {title}")


def complete_todo(index: int) -> None:
    """할 일을 완료 처리한다."""
    todos = load_todos()
    if 0 <= index < len(todos):
        todos[index]["done"] = True
        save_todos(todos)
        print(f"Completed: {todos[index]['title']}")
    else:
        print(f"Error: invalid index {index}")


def list_todos() -> None:
    """할 일 목록을 출력한다."""
    todos = load_todos()
    if not todos:
        print("No todos yet.")
        return
    for i, t in enumerate(todos):
        status = "[x]" if t["done"] else "[ ]"
        print(f"{i+1}. {status} {t['title']}")


def main() -> None:
    """CLI 진입점."""
    if len(sys.argv) < 2:
        list_todos()
    elif sys.argv[1] == "add" and len(sys.argv) > 2:
        add_todo(" ".join(sys.argv[2:]))
    elif sys.argv[1] == "list":
        list_todos()
    elif sys.argv[1] == "done" and len(sys.argv) > 2:
        complete_todo(int(sys.argv[2]) - 1)
    else:
        print(f"Usage: {sys.argv[0]} [add <title> | list | done <num>]")


if __name__ == "__main__":
    main()
