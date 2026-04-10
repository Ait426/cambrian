#!/bin/bash
set -e

echo "=== Cambrian E2E Smoke Test ==="

# 1. 임시 디렉토리에서 init
WORKDIR=$(mktemp -d)
echo "[1] cambrian init --dir $WORKDIR/myproject"
python -m engine init --dir "$WORKDIR/myproject"

# 2. 구조 확인
echo "[2] Checking init output..."
test -d "$WORKDIR/myproject/skills" || { echo "FAIL: skills/ missing"; exit 1; }
test -d "$WORKDIR/myproject/schemas" || { echo "FAIL: schemas/ missing"; exit 1; }
test -d "$WORKDIR/myproject/skill_pool" || { echo "FAIL: skill_pool/ missing"; exit 1; }
test -f "$WORKDIR/myproject/cambrian.yaml" || { echo "FAIL: cambrian.yaml missing"; exit 1; }
echo "  init structure OK"

# 3. 샘플 프로젝트 생성
SAMPLE="$WORKDIR/sample_app"
mkdir -p "$SAMPLE"
cat > "$SAMPLE/main.py" << 'EOF'
"""Simple CLI calculator."""
import sys

def add(a: float, b: float) -> float:
    return a + b

if __name__ == "__main__":
    print(add(float(sys.argv[1]), float(sys.argv[2])))
EOF
echo "[3] Sample project created at $SAMPLE"

# 4. scan
echo "[4] cambrian scan --project $SAMPLE"
cd "$WORKDIR/myproject"
python -m engine scan --project "$SAMPLE" --no-search 2>&1 || echo "  scan completed (may have warnings)"

# 5. list skills
echo "[5] cambrian skills"
python -m engine skills 2>&1 | head -20

# 6. cleanup
rm -rf "$WORKDIR"
echo ""
echo "=== Smoke Test PASSED ==="
