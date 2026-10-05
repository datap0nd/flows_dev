"""Settings for flows_dev, using Metronome's variable names. Standard library only.

A value comes from, in order: the process environment, the install folder's ``.env``, then Metronome's own settings
file (``DG_ENV_FILE``, which setup.ps1 finds through the MXAnalytics service). A name that is present but empty in the
environment or ``.env`` still wins, so ``DG_ENV_FILE=`` in ``.env`` ignores Metronome's settings entirely. Messages
carry names, paths and line numbers, never values.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Metronome's default Flow browser profile: signed-in portal sessions and the DPAPI-protected ASAP credentials
# (.asap_credentials, see app/flow_credentials.py).
DEFAULT_FLOW_PROFILE = Path.home() / ".metronome-flow-browser"


def read_env_file(path: Path) -> dict[str, str]:
    """``KEY=value`` lines, read with the same rules as Metronome's app/env_file.py (a later line wins).

    Unlike Metronome, empty values are kept so that an explicit ``KEY=`` can override a lower layer.
    """
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].strip()
        if "=" not in stripped:
            continue
        name, value = (part.strip() for part in stripped.split("=", 1))
        if not NAME_RE.fullmatch(name):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name] = value
    return values


@dataclass(frozen=True)
class Settings:
    home: Path | None
    env_file: Path | None
    metronome_env_file: Path | None
    metronome_env_status: str
    local: dict[str, str] = field(default_factory=dict, repr=False)
    metronome: dict[str, str] = field(default_factory=dict, repr=False)

    def get(self, name: str, default: str | None = None) -> str | None:
        if name in os.environ:
            return os.environ[name]
        if name in self.local:
            return self.local[name]
        value = self.metronome.get(name)
        return value if value else default

    @property
    def flow_profile(self) -> Path:
        value = self.get("METRONOME_FLOW_PROFILE")
        return Path(value) if value else DEFAULT_FLOW_PROFILE


def load_settings(home: Path | None) -> Settings:
    env_file = home / ".env" if home else None
    local = read_env_file(env_file) if env_file and env_file.is_file() else {}
    metronome_path = os.environ.get("DG_ENV_FILE", local.get("DG_ENV_FILE", ""))
    metronome: dict[str, str] = {}
    if not metronome_path:
        status = "not set"
    elif not Path(metronome_path).is_file():
        status = "missing"
    else:
        try:
            metronome = read_env_file(Path(metronome_path))
            status = "loaded"
        except (OSError, UnicodeError) as exc:
            status = f"unreadable ({type(exc).__name__})"
    return Settings(home=home, env_file=env_file, metronome_env_file=Path(metronome_path) if metronome_path else None,
                    metronome_env_status=status, local=local, metronome=metronome)
