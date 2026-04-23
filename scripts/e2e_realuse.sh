#!/bin/bash
set -e

echo "=== Cambrian 실사용 E2E 검증 ==="

WORKDIR=$(mktemp -d)
SAMPLE="$WORKDIR/todo_cli"

# 0. 샘플 프로젝트 생성
mkdir -p "$SAMPLE"
cat > "$SAMPLE/main.py" << 'PYEOF'
"""간단한 CLI TODO 유틸리티."""
import json, sys
from pathlib import Path

DB = "todos.json"

def load(): return json.loads(Path(DB).read_text()) if Path(DB).exists() else []
def save(t): Path(DB).write_text(json.dumps(t, indent=2))
def add(title):
    t = load(); t.append({"title": title, "done": False}); save(t); print(f"Added: {title}")
def ls():
    t = load()
    for i, x in enumerate(t): print(f"{i+1}. {'[x]' if x['done'] else '[ ]'} {x['title']}")

if __name__ == "__main__":
    if len(sys.argv) < 2: ls()
    elif sys.argv[1] == "add": add(" ".join(sys.argv[2:]))
    else: print(f"Usage: {sys.argv[0]} [add <title> | list]")
PYEOF

cat > "$SAMPLE/utils.py" << 'PYEOF'
from datetime import datetime
def format_date(dt): return dt.strftime("%Y-%m-%d %H:%M")
def truncate(text, n=50): return text[:n-3]+"..." if len(text)>n else text
PYEOF

echo "[0] 샘플 프로젝트 생성 완료: $SAMPLE"

# 1. init
cambrian init --dir "$WORKDIR/project"
echo "[1] init 완료"

# 2. scan (no-search)
cd "$WORKDIR/project"
echo "[2] scan 실행 (no-search):"
cambrian scan --project "$SAMPLE" --no-search 2>&1 || true
echo ""

# 3. skills
echo "[3] skills 목록:"
cambrian skills 2>&1 | head -20
echo ""

# 4. search
echo "[4] search 'testing':"
cambrian search "testing unit test" 2>&1 || true
echo ""

# 5. run (Mode B)
echo "[5] run hello_world:"
cambrian run --domain utility --tags test greeting \
  -i '{"text": "Cambrian E2E"}' 2>&1 || true
echo ""

# 6. scan with search
echo "[6] scan with search:"
cambrian scan --project "$SAMPLE" 2>&1 || true

# cleanup
rm -rf "$WORKDIR"
echo ""
echo "=== E2E 검증 완료 ==="
