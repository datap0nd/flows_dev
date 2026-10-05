"""Run the selected flows_dev release with its own portable Python.

setup.ps1 copies this file into the install folder as flows_dev.py. Point a command line or a Metronome
Python-script Flow at that copy. It works under any Python 3, including Metronome's worker Python, because it only
starts the selected release's portable Python with the same arguments and returns its exit code.

  <install folder>\\flows_dev.py --check
  <install folder>\\flows_dev.py asap [arguments]
"""
import json
import subprocess
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parent


def main():
    pointer = HOME / "current.json"
    if not pointer.is_file():
        print("No installed release in %s. Run setup.ps1 in that folder first." % HOME, file=sys.stderr)
        return 2
    current = json.loads(pointer.read_text(encoding="utf-8-sig"))
    python = Path(current["python"])
    run = Path(current["release"]) / "run.py"
    for path in (python, run):
        if not path.is_file():
            print("The selected release is incomplete (%s is missing). Run setup.ps1 again." % path, file=sys.stderr)
            return 2
    return subprocess.call([str(python), str(run), "--home", str(HOME)] + sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
