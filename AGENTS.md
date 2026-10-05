# Working in this repository

flows_dev is where Metronome Flow engines are built and proven before they move into Metronome
(`datap0nd/data_governance`). Each engine downloads one portal's reports through the portal's backend instead of its UI.
There is one module per portal under `flows_dev/<portal>/`, and ASAP is the first. It is installed on the work PC with
`setup.ps1` (the Wizard model).

## Never

- Never commit portal hostnames or URLs, cookies, tokens, passwords, credentials, report data, downloaded files, HAR
  captures or trace files. This repository is public. Keep internal report, filter and measure names out of it too, and
  refer to live evidence by an opaque label.
- Never return a file whose filters, columns or headers cannot be confirmed. A wrong or stale ID can silently produce
  an unfiltered or wrong report, so a module must fail closed rather than save a file it cannot verify.
- Never write to a portal: no saved reports, subscriptions or settings. Live portal runs happen only when the owner
  asks.

## Conventions

- Settings use Metronome's variable names (`DG_*`, `METRONOME_*`). Add a new name only when Metronome has none.
- Runtime libraries stay at the versions Metronome's Flow worker uses. After changing `pyproject.toml`, run
  `python scripts/lock_dependencies.py` and commit the lock files.
- `setup.ps1` stays ASCII-only and compatible with Windows PowerShell 5.1.
- Every module honours Metronome's Python-script Flow contract: write exactly the `--output` path, and exit non-zero
  with a useful message on failure.
- A module exposes `main(argv, settings)` and is listed in `MODULES` in `run.py`.
