"""Maintainer tool: pin the portable Windows runtime that setup.ps1 installs on work PCs.

Adapted from Wizard's scripts/lock_portable.py. Work PCs get no pip: setup.ps1 downloads
  - the official Python embeddable zip (runtime.lock.json)
  - every runtime wheel for CPython 3.13 / Windows x64 (dependencies.lock.json)
and verifies each SHA-256 before use. By default it downloads them from the pinned python.org and
files.pythonhosted.org URLs in the locks, the same hosts Metronome's installer uses. If a work PC cannot reach those,
publish a GitHub release mirror with --publish (needs the gh CLI); setup.ps1 then prefers the release.

  python scripts/lock_dependencies.py            # resolve, download, hash, write runtime and dependency locks
  python scripts/lock_dependencies.py --publish  # also write portable_assets.lock.json and create the release

Needs only a Python 3.11+ with pip. Existing pins are kept as constraints: adding a dependency never silently upgrades
the others (pass --upgrade to re-resolve everything). Re-run after changing dependencies in pyproject.toml, then commit
the lock files."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "artifacts" / "portable"
REPOSITORY = "datap0nd/flows_dev"
PYTHON_VERSION = "3.13.15"
PYTHON_ZIP = f"python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{PYTHON_ZIP}"
PLATFORM = ["--platform", "win_amd64", "--python-version", "3.13", "--implementation", "cp", "--abi", "cp313",
            "--abi", "abi3", "--abi", "none", "--only-binary=:all:"]


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


def pip(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "pip", *args, "--disable-pip-version-check"], check=True, cwd=ROOT)


def resolve(upgrade: bool) -> list[tuple[str, str]]:
    """Pins for CPython 3.13 / Windows x64, resolved by pip for that target (not for this machine)."""
    requirements = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    with tempfile.TemporaryDirectory() as scratch:
        constraints = Path(scratch) / "constraints.txt"
        current = ROOT / "dependencies.lock.json"
        pinned = [] if upgrade or not current.is_file() else json.loads(current.read_text(encoding="utf-8"))["packages"]
        constraints.write_text("".join(f"{p['name']}=={p['version']}\n" for p in pinned), encoding="utf-8")
        report = Path(scratch) / "report.json"
        pip("install", "--dry-run", "--ignore-installed", "--quiet", "--report", str(report), "--target",
            str(Path(scratch) / "target"), *PLATFORM, "-c", str(constraints), *requirements)
        installs = json.loads(report.read_text(encoding="utf-8"))["install"]
    return sorted((i["metadata"]["name"], i["metadata"]["version"]) for i in installs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--publish", action="store_true", help="also publish the archives as a GitHub release mirror")
    parser.add_argument("--upgrade", action="store_true", help="re-resolve every pin instead of keeping current ones")
    args = parser.parse_args()
    pins = resolve(args.upgrade)
    wheels = WORK / "wheels"
    shutil.rmtree(WORK, ignore_errors=True)
    wheels.mkdir(parents=True)

    packages = []
    for name, version in pins:
        pip("download", f"{name}=={version}", "--no-deps", *PLATFORM, "-d", str(wheels), "-q")
    for wheel in sorted(wheels.glob("*.whl")):
        project, version = wheel.name.split("-")[:2]
        with urllib.request.urlopen(f"https://pypi.org/pypi/{project}/{version}/json", timeout=60) as response:
            url = next(u["url"] for u in json.load(response)["urls"] if u["filename"] == wheel.name)
        packages.append({"name": project.replace("_", "-").lower(), "version": version, "filename": wheel.name,
                         "url": url, "sha256": sha256(wheel)})

    # The embeddable zip for a given version never changes, so an existing pin is kept unless publishing needs the file.
    python_zip = WORK / PYTHON_ZIP
    runtime_lock = ROOT / "runtime.lock.json"
    runtime = json.loads(runtime_lock.read_text(encoding="utf-8")) if runtime_lock.is_file() else {}
    if args.publish or runtime.get("version") != PYTHON_VERSION:
        urllib.request.urlretrieve(PYTHON_URL, python_zip)  # noqa: S310 - fixed python.org URL
        if runtime.get("version") == PYTHON_VERSION and runtime.get("sha256") != sha256(python_zip):
            raise SystemExit(f"{PYTHON_ZIP} no longer matches its pinned SHA-256; refusing to re-pin it silently.")
        runtime = {"version": PYTHON_VERSION, "filename": PYTHON_ZIP, "url": PYTHON_URL, "sha256": sha256(python_zip)}
    write_json(runtime_lock, runtime)
    write_json(ROOT / "dependencies.lock.json",
               {"format": 2, "platform": "win_amd64", "python_tag": "cp313", "packages": packages})
    print(f"Locked Python {PYTHON_VERSION} and {len(packages)} wheels.")

    if args.publish:
        runtime_hash = sha256(ROOT / "runtime.lock.json")
        dependency_hash = sha256(ROOT / "dependencies.lock.json")
        tag = "portable-cp313-win_amd64-" + hashlib.sha256((runtime_hash + dependency_hash).encode()).hexdigest()[:20]
        exists = subprocess.run(["gh", "release", "view", tag, "--repo", REPOSITORY], capture_output=True).returncode == 0
        if exists:
            print(f"Release {tag} already exists; nothing to publish.")
        else:
            files = [str(python_zip), *[str(w) for w in sorted(wheels.glob("*.whl"))]]
            subprocess.run(["gh", "release", "create", tag, "--repo", REPOSITORY, "--title", f"Portable runtime {tag}",
                            "--notes", "Portable Python and locked wheels for work-PC installs (setup.ps1). Do not delete.",
                            "--latest=false", *files], check=True)
            print(f"Published {len(files)} archives to {REPOSITORY} release {tag}.")
        write_json(ROOT / "portable_assets.lock.json", {"format": 1, "release_tag": tag,
                   "dependency_lock_sha256": dependency_hash, "runtime_lock_sha256": runtime_hash})
    return 0


if __name__ == "__main__":
    sys.exit(main())
