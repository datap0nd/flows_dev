# flows_dev

Development home for Metronome Flow engines that download portal reports through the portal's backend instead of
driving its UI. There is one module per portal, and **ASAP** (MicroStrategy) is the first. Modules are built and proven
here on the work PC without Metronome releases, then moved into Metronome (`datap0nd/data_governance`).

> **Status: installer only.** No module is built yet. An install today gives you the portable runtime, the settings and
> `flows_dev.py --check`. `flows_dev.py asap` exits with "not built yet".

## Work PC (install and update)

Same model as Wizard: **only `setup.ps1` is needed**. Save it in an empty folder (for example `C:\flows_dev`) and run
it. No admin rights, git or pip.

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/datap0nd/flows_dev/main/setup.ps1 -OutFile setup.ps1
.\setup.ps1
```

If PowerShell refuses to run the script, use `powershell -ExecutionPolicy Bypass -File .\setup.ps1`.

`setup.ps1` downloads the exact commit of `main` plus a portable Python 3.13 and the locked libraries, and checks every
archive's SHA-256. It then installs a clean release under `releases\` and runs a check. It only switches to the new
release if the check passes, and keeps the three newest releases. **To update, run `.\setup.ps1` again.**

The libraries are the same versions as Metronome's Flow worker (Playwright 1.62.0, httpx 0.28.1, openpyxl 3.1.5 and
truststore), so a module can move into Metronome unchanged. Downloads come from `api.github.com` (this repository),
`www.python.org` and `files.pythonhosted.org`, the same hosts Metronome's installer uses.

## Settings

The settings use Metronome's variable names. A value comes from the process environment first, then `.env` in the
install folder, then Metronome's own `.env`.

| Variable | Meaning |
| --- | --- |
| `DG_GITHUB_TOKEN` | Optional GitHub token for `setup.ps1`, the same one Metronome uses. It avoids GitHub's anonymous limit on a shared office IP. |
| `DG_ENV_FILE` | Metronome's settings file. `setup.ps1` finds it through the `MXAnalytics` service and writes it into `.env`. `DG_ENV_FILE=` (empty) ignores Metronome's settings. |
| `METRONOME_FLOW_PROFILE` | Metronome's Flow browser profile: signed-in portal sessions and the DPAPI-protected `.asap_credentials`. Defaults to `%USERPROFILE%\.metronome-flow-browser`, as in Metronome. |

New settings reuse a Metronome name whenever Metronome already has one.

## Running it

```powershell
& "<install>\runtime\python-3.13.15-amd64\python.exe" "<install>\flows_dev.py" --check
& "<install>\runtime\python-3.13.15-amd64\python.exe" "<install>\flows_dev.py" asap [arguments]
```

`setup.ps1` prints the exact command at the end. `flows_dev.py` is a small launcher that starts the selected release
with its own portable Python. It works under any Python 3, so a Metronome Python-script Flow can point at
`<install>\flows_dev.py` directly, with arguments that start with the module name. In "Produce a file or SQL table"
mode Metronome adds `--output <path>` and the `METRONOME_FLOW_*` variables (see Metronome's
`docs/python_script_flows.md`); every module must honour both.

## Modules

| Module | Portal | State |
| --- | --- | --- |
| `asap` | ASAP (MicroStrategy) | Planned: backend execution and export with typed filters |

A module lives in `flows_dev/<name>/`. It is ready when it exposes `main(argv, settings)` that returns an exit code.
To add a module, also add its name to `MODULES` in `run.py`.

## Install folder

| Path | Contents |
| --- | --- |
| `.env` | Your settings. Never overwritten; setup only adds missing keys. |
| `current.json`, `previous.json` | The selected release and the one before it. |
| `releases\` | Installed releases (the three newest). |
| `runtime\` | Portable Python. |
| `dependencies\`, `.downloads\` | Unpacked libraries and verified archives, reused between updates. |
| `setup.ps1`, `flows_dev.py` | The installer and the launcher, refreshed on every update. |

## Maintainers

- Change runtime libraries in `pyproject.toml`, run `python scripts/lock_dependencies.py`, and commit the lock files.
  `--publish` also creates a GitHub release mirror (needs the `gh` CLI), for PCs that cannot reach PyPI.
- Keep `setup.ps1` ASCII-only and compatible with Windows PowerShell 5.1.
- This repository is public. See [AGENTS.md](AGENTS.md) for what must never be committed.
