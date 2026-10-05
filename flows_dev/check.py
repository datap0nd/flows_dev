"""Installation check run by setup.ps1 before it selects a new release, and by ``flows_dev.py --check``.

Exit codes follow Wizard's setup contract: 0 ready, 1 usable with warnings, 2 broken (setup keeps the previous release).
The check reads names, paths and versions only; it never prints a setting's value or opens the ASAP portal.
"""
from __future__ import annotations

import importlib
import importlib.metadata
import os
import platform
import ssl
import sys
from pathlib import Path

from flows_dev.settings import Settings

REQUIRED_MODULES = (("playwright", "playwright.sync_api"), ("httpx", "httpx"), ("openpyxl", "openpyxl"),
                    ("truststore", "truststore"))


def _browser_candidates() -> dict[str, list[Path]]:
    roots = {name: os.environ.get(name, "") for name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")}
    def under(*parts: str) -> list[Path]:
        return [Path(root, *parts) for root in roots.values() if root]
    return {"msedge": under("Microsoft", "Edge", "Application", "msedge.exe"),
            "chrome": under("Google", "Chrome", "Application", "chrome.exe")}


def run_checks(settings: Settings) -> int:
    failures = warnings = 0

    def report(level: str, message: str) -> None:
        nonlocal failures, warnings
        failures += level == "FAIL"
        warnings += level == "WARN"
        print(f"  [{level:<4}] {message}", flush=True)

    print("flows_dev installation check")
    windows = platform.system() == "Windows"
    version = ".".join(map(str, sys.version_info[:3]))
    report("OK" if sys.version_info[:2] == (3, 13) else "WARN", f"Python {version} ({sys.executable})")
    if not windows:
        report("WARN", "Not Windows: the credential and browser checks below are informational only.")

    for distribution, module in REQUIRED_MODULES:
        try:
            loaded = importlib.import_module(module)
            report("OK", f"{distribution} {importlib.metadata.version(distribution)} from "
                         f"{Path(loaded.__file__).parent}")
        except Exception as exc:  # noqa: BLE001 - any import failure makes the release unusable
            report("FAIL", f"{distribution} cannot be imported ({type(exc).__name__}: {exc})")
    try:
        import truststore
        truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        report("OK", "HTTPS certificates are checked against the operating system store (truststore)")
    except Exception as exc:  # noqa: BLE001
        report("WARN", f"truststore could not create a TLS context ({type(exc).__name__})")

    if settings.env_file:
        report("OK" if settings.env_file.is_file() else "WARN",
               f"Settings file {settings.env_file}" + ("" if settings.env_file.is_file() else " does not exist"))
    status = settings.metronome_env_status
    if status == "loaded":
        report("OK", f"Metronome settings (DG_ENV_FILE) loaded from {settings.metronome_env_file}")
    elif status == "not set":
        report("WARN", "DG_ENV_FILE is not set: Metronome's settings are not shared with this install")
    else:
        report("WARN", f"Metronome settings file {settings.metronome_env_file} is {status}")

    profile = settings.flow_profile
    if profile.is_dir():
        report("OK", f"Metronome Flow browser profile (METRONOME_FLOW_PROFILE): {profile}")
        credentials = profile / ".asap_credentials"
        report("OK" if credentials.is_file() else "WARN",
               f"ASAP credentials file {'found' if credentials.is_file() else 'not found'}: {credentials}")
    else:
        report("WARN", f"Metronome Flow browser profile (METRONOME_FLOW_PROFILE) not found: {profile}")

    browsers = [name for name, paths in _browser_candidates().items() if any(path.is_file() for path in paths)]
    report("OK" if browsers else "WARN",
           f"Browsers for Playwright channels: {', '.join(browsers)}" if browsers
           else "Neither Microsoft Edge nor Google Chrome was found in the standard install folders")

    print(f"  {failures} failed, {warnings} warning(s).")
    return 2 if failures else 1 if warnings else 0
