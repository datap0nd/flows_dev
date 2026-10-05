"""Entry point of an installed flows_dev release (portable Python, see setup.ps1) or a development checkout.

  python run.py --home <install folder> --check                validate the installation and settings
  python run.py --home <install folder> --version              print the installed revision
  python run.py --home <install folder> <module> [arguments]   run a Flow module, e.g. asap

On a work PC, run it through the launcher setup.ps1 puts in the install folder: flows_dev.py.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# The portable Python's ._pth file fixes sys.path, so the release and its locked libraries are added explicitly.
for entry in (ROOT, ROOT / "vendor"):
    sys.path.insert(0, str(entry))

# One Flow module per portal: flows_dev/<name>/. A module is ready when it exposes main(argv, settings) -> exit code.
MODULES = ("asap",)


def revision(home: Path | None) -> str:
    pointer = home / "current.json" if home else None
    if pointer and pointer.is_file():
        current = json.loads(pointer.read_text(encoding="utf-8-sig"))
        if Path(current.get("release", "")).resolve() == ROOT:
            return f"{current.get('commit', 'unknown')} ({ROOT.name})"
    return f"development checkout ({ROOT})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flows_dev", description=__doc__, allow_abbrev=False,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--home", type=Path, default=None, help="install folder holding .env (default: none)")
    parser.add_argument("--check", action="store_true", help="validate the installation and exit")
    parser.add_argument("--version", action="store_true", help="print the installed revision and exit")
    args, rest = parser.parse_known_args(argv)
    # The module is the first remaining argument; everything after it (including Metronome's --output) is its own.
    module = rest[0] if rest and not rest[0].startswith("-") else None
    module_args = rest[1:] if module else rest

    from flows_dev.settings import load_settings
    settings = load_settings(args.home)
    if args.version:
        print(revision(args.home))
        return 0
    if args.check:
        from flows_dev.check import run_checks
        return run_checks(settings)
    if module not in MODULES:
        problem = f"Unknown Flow module '{module}'." if module else "No Flow module given."
        print(f"{problem} Available: {', '.join(MODULES)}. Run with --check to validate the installation.",
              file=sys.stderr)
        return 2
    entry = getattr(importlib.import_module(f"flows_dev.{module}"), "main", None)
    if entry is None:
        print(f"The {module} module is not built yet: this release installs the runtime and settings only.",
              file=sys.stderr)
        return 2
    return entry(module_args, settings)


if __name__ == "__main__":
    sys.exit(main())
