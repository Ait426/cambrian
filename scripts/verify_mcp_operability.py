from __future__ import annotations

import sys

from engine.project_mcp_verify import CODE_ROOT, main


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--source-tree-mode" not in argv and "--installed-wheel-mode" not in argv:
        argv = ["--source-tree-mode", *argv]
    raise SystemExit(main(argv, receipt_base=CODE_ROOT))
