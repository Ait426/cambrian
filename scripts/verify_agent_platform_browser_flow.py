"""Run the optional Agent Platform browser flow smoke tests.

This wrapper keeps browser automation out of the Python package surface. It can
use a temporary Playwright install outside the repository, then runs the existing
pytest browser-flow tests with CAMBRIAN_BROWSER_NODE_MODULES set.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEPS_ROOT = Path("C:/tmp/cambrian-playwright-deps") if os.name == "nt" else Path("/tmp/cambrian-playwright-deps")
DEFAULT_BASETEMP = ROOT / ".pytest-basetemp-browser-flow-wrapper"
FULL_BROWSER_TEST = "tests/test_agent_platform_browser_flow.py"
SINGLE_GOLDEN_PATH_TEST = (
    "tests/test_agent_platform_browser_flow.py::"
    "test_builder_conversation_recommends_template_and_updates_workspace"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run optional Cambrian Agent Platform browser smoke tests.")
    parser.add_argument(
        "--deps-root",
        default=str(DEFAULT_DEPS_ROOT),
        help="Directory where temporary Playwright dependencies are installed.",
    )
    parser.add_argument(
        "--node-modules",
        default=None,
        help="Existing node_modules directory that contains playwright. Overrides --deps-root/node_modules.",
    )
    parser.add_argument(
        "--install-deps",
        action="store_true",
        help="Install playwright into --deps-root before running tests.",
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help="Run only the main builder conversation golden path browser smoke.",
    )
    parser.add_argument(
        "--basetemp",
        default=str(DEFAULT_BASETEMP),
        help="Pytest basetemp path for this browser smoke run.",
    )
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    deps_root = Path(args.deps_root).resolve()
    node_modules = Path(args.node_modules).resolve() if args.node_modules else deps_root / "node_modules"

    if args.install_deps:
        result = _install_playwright(deps_root)
        if result != 0:
            return result

    if not _node_available():
        print("[FAIL] Node.js is required for browser smoke tests.")
        return 1
    if not _playwright_available(node_modules):
        print("[FAIL] Playwright is not available.")
        print(f"Run: npm install --prefix {deps_root} playwright")
        print(f"Then: python scripts/verify_agent_platform_browser_flow.py --node-modules {node_modules}")
        return 1

    test_target = SINGLE_GOLDEN_PATH_TEST if args.single else FULL_BROWSER_TEST
    env = dict(os.environ)
    env["CAMBRIAN_BROWSER_NODE_MODULES"] = str(node_modules)

    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--basetemp",
        str(Path(args.basetemp)),
        test_target,
    ]
    print(f"[RUN] {' '.join(command)}")
    print(f"[INFO] CAMBRIAN_BROWSER_NODE_MODULES={node_modules}")
    result = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if result.returncode == 0:
        print("[PASS] Agent Platform browser flow smoke passed.")
    else:
        print("[FAIL] Agent Platform browser flow smoke failed.")
    return int(result.returncode)


def _node_available() -> bool:
    return shutil.which("node") is not None


def _install_playwright(deps_root: Path) -> int:
    if shutil.which("npm") is None:
        print("[FAIL] npm is required to install Playwright.")
        return 1
    deps_root.mkdir(parents=True, exist_ok=True)
    command = ["npm", "install", "--prefix", str(deps_root), "playwright"]
    print(f"[RUN] {' '.join(command)}")
    result = subprocess.run(command, cwd=ROOT, check=False)
    return int(result.returncode)


def _playwright_available(node_modules: Path) -> bool:
    env = dict(os.environ)
    env["NODE_PATH"] = str(node_modules)
    result = subprocess.run(
        ["node", "-e", "require('playwright')"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    return result.returncode == 0


if __name__ == "__main__":
    raise SystemExit(main())
