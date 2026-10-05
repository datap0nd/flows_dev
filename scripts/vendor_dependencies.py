"""Unpack the locked wheels into <release>/vendor (stdlib only; runs on the portable Python during setup).

Copied from Wizard (itself adapted from the B2B installer): every archive is verified against dependencies.lock.json,
unpacked once into a shared store keyed by its SHA-256, and hard-linked (or copied) into a fresh vendor folder, so
unchanged packages are reused and removed packages cannot linger. Offline: setup.ps1 has already fetched and verified
the archives. Playwright ships as a py3-none-win_amd64 wheel, so platform-specific pure-Python wheels are allowed."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_WHEEL_SUFFIXES = ("-none-any.whl", "-none-win_amd64.whl", "-cp313-cp313-win_amd64.whl", "-abi3-win_amd64.whl")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def contained(root: Path, relative: str | Path) -> Path:
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("Invalid archive or cache path.")
    return path


def cached_package(store: Path, package: dict) -> tuple[Path, dict] | None:
    index = store / (package["sha256"] + ".json")
    try:
        record = json.loads(index.read_text(encoding="utf-8"))
        directory = contained(store, record["directory"])
        if record["archive_sha256"] != package["sha256"]:
            return None
        for name, expected in record["files"].items():
            path = contained(directory, name)
            if not path.is_file() or digest(path) != expected:
                return None
        return directory, record["files"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def unpack(store: Path, package: dict, wheel: Path) -> tuple[Path, dict]:
    directory = store / (package["sha256"] + "-" + uuid.uuid4().hex)
    directory.mkdir()
    files = {}
    with ZipFile(wheel) as archive:
        for member in archive.infolist():
            contained(directory, member.filename)
            parts = Path(member.filename).parts
            if parts and parts[0].endswith(".data"):
                if len(parts) < 3:
                    continue
                relative = Path(*parts[2:]) if parts[1] in ("purelib", "platlib") else Path("_wheel_data", package["name"], *parts[1:])
            else:
                relative = Path(member.filename)
            path = contained(directory, relative)
            if member.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, path.open("wb") as output:
                shutil.copyfileobj(source, output)
            files[relative.as_posix()] = digest(path)
    record = {"archive_sha256": package["sha256"], "directory": directory.name, "files": files}
    pending = store / (package["sha256"] + "-" + uuid.uuid4().hex + ".json")
    pending.write_text(json.dumps(record), encoding="utf-8")
    os.replace(pending, store / (package["sha256"] + ".json"))
    return directory, files


def vendor(cache: Path, store: Path, target: Path, lock: Path) -> dict:
    packages = json.loads(lock.read_text(encoding="utf-8-sig"))["packages"]
    target = target.absolute()
    store.mkdir(parents=True, exist_ok=True)
    staging = target.parent / ("vendor.staging." + uuid.uuid4().hex)
    staging.mkdir(parents=True)
    counts = {"unpacked": 0, "reused": 0}
    for package in packages:
        filename = package["filename"]
        if Path(filename).name != filename or not filename.endswith(ALLOWED_WHEEL_SUFFIXES):
            raise ValueError("Only pure-Python or CPython 3.13 Windows x64 wheels are allowed: " + filename)
        cached = cached_package(store, package)
        if cached:
            counts["reused"] += 1
        else:
            wheel = cache / filename
            if not wheel.is_file() or digest(wheel) != package["sha256"]:
                raise ValueError("Missing or invalid downloaded archive: " + filename)
            cached = unpack(store, package, wheel)
            counts["unpacked"] += 1
        directory, files = cached
        for name, expected in files.items():
            source, path = contained(directory, name), contained(staging, name)
            if path.exists():
                if digest(path) == expected:
                    continue
                raise ValueError("Conflicting files in dependency wheels: " + name)
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(source, path)
            except OSError:
                shutil.copyfile(source, path)
    if target.exists():
        target.rename(target.parent / ("vendor.previous." + uuid.uuid4().hex))
    staging.rename(target)
    print(f"Libraries: {counts['reused']} reused, {counts['unpacked']} unpacked.", flush=True)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True, help="folder holding the downloaded wheel archives")
    parser.add_argument("--store", type=Path, required=True, help="shared unpacked-package store (kept between updates)")
    parser.add_argument("--target", type=Path, default=ROOT / "vendor")
    parser.add_argument("--lock", type=Path, default=ROOT / "dependencies.lock.json")
    args = parser.parse_args()
    try:
        vendor(args.cache.resolve(), args.store.resolve(), args.target, args.lock)
    except ValueError as error:
        print(f"Dependency setup failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
