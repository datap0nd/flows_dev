# Install or refresh flows_dev in this folder from GitHub. No admin rights, git or pip needed.
# Only this file is needed on a work PC: save it as setup.ps1 in an empty folder (e.g. C:\flows_dev) and run .\setup.ps1.
# Same model as Wizard: downloads the exact commit of `main`, a portable Python and locked libraries (each SHA-256
# verified), installs a clean release under releases\, keeps .env, checks the new release before selecting it, and keeps
# the three newest releases. Run it again to update.
#
# Settings use Metronome's variable names:
#   DG_GITHUB_TOKEN         optional GitHub token (avoids the anonymous API limit on shared office IPs): the environment
#                           variable, a DG_GITHUB_TOKEN=<token> line in .env here, or the same line in Metronome's .env
#   DG_ENV_FILE             Metronome's settings file; found through the MXAnalytics service when not set
#   METRONOME_FLOW_PROFILE  Metronome's Flow browser profile: portal sessions and .asap_credentials (Metronome's default if not set)
#
#   .\setup.ps1             first install or update
[CmdletBinding()]
param(
    [string]$InstallDir,
    [string]$Repository = 'datap0nd/flows_dev',
    [string]$Ref = 'main',
    [string]$LocalSource,
    [ValidatePattern('^(local|[a-f0-9]{40})$')][string]$SourceCommit = 'local',
    [string]$DownloadCache,
    [switch]$SkipCheck
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Read-EnvFile([string]$Path, [switch]$Lenient) {
    # Lenient reads Metronome's file with Metronome's rules (export prefix allowed, invalid lines skipped).
    $values = @{}
    if (Test-Path -LiteralPath $Path) {
        foreach ($raw in [IO.File]::ReadAllLines($Path)) {
            $line = $raw.Trim()
            if (-not $line -or $line.StartsWith('#')) { continue }
            if ($Lenient -and $line.StartsWith('export ')) { $line = $line.Substring(7).Trim() }
            if ($line -notmatch '^([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
                if ($Lenient) { continue }
                throw "Invalid line in ${Path}: '$line'. Use KEY=value lines."
            }
            $key = $Matches[1]; $value = $Matches[2].Trim()
            if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) { $value = $value.Substring(1, $value.Length - 2) }
            $values[$key] = $value
        }
    }
    return $values
}
function Setting([string]$Key, [hashtable]$Values) {
    if (Test-Path -LiteralPath "Env:$Key") { return [Environment]::GetEnvironmentVariable($Key) }
    return $Values[$Key]
}
function Find-MetronomeEnvFile([hashtable]$Values) {
    # Metronome's own variable for its settings file wins; DG_ENV_FILE= (empty) in .env ignores Metronome.
    if (Test-Path -LiteralPath 'Env:DG_ENV_FILE') { return [Environment]::GetEnvironmentVariable('DG_ENV_FILE') }
    if ($Values.ContainsKey('DG_ENV_FILE')) { return $Values['DG_ENV_FILE'] }
    # Otherwise find the installed Metronome the way its update_app.ps1 does: through the MXAnalytics service.
    try {
        $service = Get-CimInstance Win32_Service -Filter "Name='MXAnalytics'" -ErrorAction Stop
        if ($service -and $service.PathName -match '"?([^"]*?nssm\.exe)') {
            $codeDir = Split-Path (Split-Path $Matches[1])
            if (Test-Path -LiteralPath (Join-Path $codeDir 'app\main.py')) {
                $candidate = Join-Path (Split-Path $codeDir) '.env'
                if (Test-Path -LiteralPath $candidate) { return $candidate }
            }
        }
    } catch { }
    return ''
}

$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } elseif ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { (Get-Location).Path }
if (-not $InstallDir) { $InstallDir = $scriptRoot }
if (-not [IO.Path]::IsPathRooted($InstallDir)) { $InstallDir = Join-Path $scriptRoot $InstallDir }
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

$envPath = Join-Path $InstallDir '.env'
$localValues = Read-EnvFile $envPath
$metronomeEnv = Find-MetronomeEnvFile $localValues
$metronomeValues = @{}
if ($metronomeEnv) {
    try { $metronomeValues = Read-EnvFile $metronomeEnv -Lenient }
    catch { Write-Host "Metronome's settings file $metronomeEnv could not be read ($($_.Exception.Message)); continuing without it." -ForegroundColor Yellow }
}
# Same GitHub token the data-governance, Wizard and B2B installers use (Contents: read is enough for a public repository).
$githubToken = Setting 'DG_GITHUB_TOKEN' $localValues
if (-not $githubToken) { $githubToken = $metronomeValues['DG_GITHUB_TOKEN'] }
$githubHeaders = @{ 'User-Agent' = 'flows_dev-Setup'; 'Accept' = 'application/vnd.github+json'; 'X-GitHub-Api-Version' = '2022-11-28' }
if ($githubToken) { $githubHeaders['Authorization'] = "Bearer $githubToken" }
if (-not $DownloadCache) { $DownloadCache = Join-Path $InstallDir '.downloads' }
$DownloadCache = [IO.Path]::GetFullPath($DownloadCache)
New-Item -ItemType Directory -Force -Path $DownloadCache | Out-Null
$script:releaseTag = $null
$script:releaseAssets = $null
$script:downloads = 0
$script:reused = 0
$setupLock = $null
$extracted = $null

function Download-File([string]$Url, [string]$Path, [hashtable]$Headers) {
    for ($attempt = 1; $attempt -le 8; $attempt++) {
        try {
            Invoke-WebRequest -Uri $Url -OutFile $Path -Headers $Headers -UseBasicParsing -TimeoutSec 300
            return
        } catch {
            if ($attempt -eq 8) { throw "Download failed after 8 attempts ($($_.Exception.Message)). Check the corporate proxy and DG_GITHUB_TOKEN." }
            $wait = [Math]::Min(30, $attempt * 3)
            Write-Host "  Download attempt $attempt failed: $($_.Exception.Message). Retrying in $wait seconds."
            Start-Sleep -Seconds $wait
        }
    }
}
function Expand-CheckedArchive([string]$Archive, [string]$Target) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $prefix = [IO.Path]::GetFullPath($Target).TrimEnd('\') + '\'
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        foreach ($entry in $zip.Entries) {
            $resolved = [IO.Path]::GetFullPath((Join-Path $Target $entry.FullName))
            if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid path in downloaded archive.' }
        }
    } finally { $zip.Dispose() }
    [IO.Compression.ZipFile]::ExtractToDirectory($Archive, $Target)
}
function Get-LockedArchive($Item) {
    # Every archive is pinned by SHA-256. Source: the repository's GitHub release mirror when portable_assets.lock.json
    # names one, otherwise the pinned python.org / files.pythonhosted.org link (the hosts Metronome's installer uses).
    if ([IO.Path]::GetFileName($Item.filename) -ne $Item.filename -or $Item.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Invalid archive lock entry.' }
    $archivePath = Join-Path $DownloadCache $Item.filename
    if ((Test-Path -LiteralPath $archivePath) -and (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash -eq $Item.sha256) {
        $script:reused++
        return $archivePath
    }
    $asset = $null
    if ($script:releaseTag) {
        if ($null -eq $script:releaseAssets) {
            try { $script:releaseAssets = @((Invoke-RestMethod -Uri "https://api.github.com/repos/$Repository/releases/tags/$($script:releaseTag)" -Headers $githubHeaders -TimeoutSec 60).assets) }
            catch {
                Write-Host "  Release mirror $($script:releaseTag) is unavailable ($($_.Exception.Message)); using the pinned links."
                $script:releaseAssets = @()
            }
        }
        $asset = @($script:releaseAssets | Where-Object { $_.name -ceq $Item.filename -and $_.state -eq 'uploaded' }) | Select-Object -First 1
    }
    Write-Host "Downloading $($Item.filename)"
    if ($asset -and $githubToken) {
        $binaryHeaders = $githubHeaders.Clone(); $binaryHeaders['Accept'] = 'application/octet-stream'
        Download-File "https://api.github.com/repos/$Repository/releases/assets/$($asset.id)" $archivePath $binaryHeaders
    } elseif ($asset) {
        # Anonymous: the public download link does not count against GitHub's per-IP API limit.
        Download-File $asset.browser_download_url $archivePath @{ 'User-Agent' = 'flows_dev-Setup' }
    } elseif ($Item.url -match '^https://(www\.python\.org|files\.pythonhosted\.org)/') {
        Download-File $Item.url $archivePath @{ 'User-Agent' = 'flows_dev-Setup' }
    } else {
        throw "No download source for $($Item.filename)."
    }
    if ((Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash -ne $Item.sha256) {
        Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue
        throw "Checksum mismatch for $($Item.filename)."
    }
    $script:downloads++
    return $archivePath
}
function Copy-Tree([string]$From, [string]$To) {
    # robocopy skips developer-only folders; exit codes below 8 mean success.
    & robocopy $From $To /E /NFL /NDL /NJH /NJS /NP /XD .git .github .venv var artifacts node_modules __pycache__ .pytest_cache .mypy_cache .ruff_cache .claude /XF .env | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Copying $From failed (robocopy $LASTEXITCODE)." }
    $global:LASTEXITCODE = 0
}
function Set-EnvDefault([string]$Key, [string]$Value, [string]$Comment) {
    if (-not $Value) { return }
    $current = Read-EnvFile $envPath
    if ($current.ContainsKey($Key)) { return }
    $text = ''
    if (Test-Path -LiteralPath $envPath) { $text = [IO.File]::ReadAllText($envPath); if ($text -and -not $text.EndsWith("`n")) { $text += "`r`n" } }
    if ($Comment) { $text += "# $Comment`r`n" }
    $text += "$Key=$Value`r`n"
    [IO.File]::WriteAllText($envPath, $text, $utf8)
    Write-Host "  .env: $Key=$Value"
}
function Add-EnvPlaceholder([string]$Key, [string]$Example, [string]$Comment) {
    # A commented-out line you fill in yourself; added once, never when the key is already mentioned.
    $text = ''
    if (Test-Path -LiteralPath $envPath) { $text = [IO.File]::ReadAllText($envPath) }
    if ($text -match "(?m)^\s*#?\s*$([regex]::Escape($Key))\s*=") { return }
    if ($text -and -not $text.EndsWith("`n")) { $text += "`r`n" }
    $text += "# $Comment`r`n# $Key=$Example`r`n"
    [IO.File]::WriteAllText($envPath, $text, $utf8)
    Write-Host "  .env: added a commented $Key line"
}

try {
    if ($Repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw 'Repository must use owner/name format.' }
    $setupLock = [IO.File]::Open((Join-Path $InstallDir '.setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $installId = [guid]::NewGuid().ToString('N').Substring(0, 8)
    if ($LocalSource) {
        $source = [IO.Path]::GetFullPath($LocalSource)
        $commit = $SourceCommit
    } else {
        $encodedRef = [uri]::EscapeDataString($Ref)
        $commit = $null
        for ($attempt = 1; $attempt -le 4 -and -not $commit; $attempt++) {
            try { $commit = (Invoke-RestMethod -Uri "https://api.github.com/repos/$Repository/commits/${encodedRef}?cache=$installId$attempt" -Headers $githubHeaders -TimeoutSec 60).sha }
            catch {
                $lookupError = $_
                $code = 0; try { $code = [int]$_.Exception.Response.StatusCode } catch { }
                if ($code -in 401, 404 -or $attempt -eq 4) { break }
                Write-Host "GitHub lookup attempt $attempt failed ($($_.Exception.Message)); retrying."
                Start-Sleep -Seconds ($attempt * 3)
            }
        }
        if (-not $commit) {
            $status = ''; try { $status = [int]$lookupError.Exception.Response.StatusCode } catch { }
            $tokenState = if (-not $githubToken) { "No DG_GITHUB_TOKEN is set (optional: an environment variable, or the line DG_GITHUB_TOKEN=<token> in $envPath)." } else { "A token was found ($($githubToken.Length) characters)." }
            $hint = switch ($status) {
                401 { 'The token is invalid or expired.' }
                404 { "The token cannot see $Repository. Add this repository to the token (fine-grained: Contents read-only), or use a token with the repo scope." }
                403 { 'The token was refused: check SSO authorization and rate limits.' }
                default { 'api.github.com is unreachable: check the proxy, TLS inspection and firewall.' }
            }
            if (-not $githubToken -and $status -in 401, 404) { $hint = '' }
            if (-not $githubToken -and $status -eq 403) { $hint = "GitHub's hourly limit for anonymous requests from this network was reached. Add a token as described, or try again later." }
            throw "Cannot read $Ref of $Repository (HTTP $status). $tokenState $hint"
        }
        Write-Host "Installing flows_dev $($commit.Substring(0, 12)) from $Repository"
        $archive = Join-Path $DownloadCache "source-$installId.zip"
        Download-File "https://api.github.com/repos/$Repository/zipball/$commit" $archive $githubHeaders
        $extracted = Join-Path $DownloadCache "source-$installId"
        Expand-CheckedArchive $archive $extracted
        Remove-Item -LiteralPath $archive -Force
        $folders = @(Get-ChildItem -LiteralPath $extracted -Directory)
        if ($folders.Count -ne 1) { throw 'Unexpected repository archive layout.' }
        $source = $folders[0].FullName
        # Installer fixes in the new revision apply to this same update.
        $freshSetup = Join-Path $source 'setup.ps1'
        if ($PSCommandPath -and (Get-FileHash -LiteralPath $freshSetup).Hash -ne (Get-FileHash -LiteralPath $PSCommandPath).Hash) {
            $setupLock.Dispose(); $setupLock = $null
            Write-Host 'Continuing with the newly downloaded setup.ps1.'
            $fresh = @{ InstallDir = $InstallDir; Repository = $Repository; LocalSource = $source; SourceCommit = $commit; DownloadCache = $DownloadCache }
            if ($SkipCheck) { $fresh.SkipCheck = $true }
            & $freshSetup @fresh
            $freshCode = $LASTEXITCODE
            Remove-Item -LiteralPath $extracted -Recurse -Force -ErrorAction SilentlyContinue
            exit $freshCode
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $source 'run.py'))) { throw "$source is not a flows_dev source folder (run.py missing)." }

    $short = if ($commit -match '^[a-f0-9]{40}$') { $commit.Substring(0, 12) } else { 'local' }
    $release = Join-Path $InstallDir "releases\$short-$installId"
    Copy-Tree $source $release
    if ($extracted) { Remove-Item -LiteralPath $extracted -Recurse -Force -ErrorAction SilentlyContinue }

    # Portable Python and libraries, verified against the release's own locks.
    $runtime = Get-Content -LiteralPath (Join-Path $release 'runtime.lock.json') -Raw | ConvertFrom-Json
    $dependencies = Get-Content -LiteralPath (Join-Path $release 'dependencies.lock.json') -Raw | ConvertFrom-Json
    $assetsLock = Join-Path $release 'portable_assets.lock.json'
    if (Test-Path -LiteralPath $assetsLock) {
        $assets = Get-Content -LiteralPath $assetsLock -Raw | ConvertFrom-Json
        if ($assets.release_tag -notmatch '^portable-[A-Za-z0-9_.-]+$' -or $assets.format -ne 1) { throw 'Invalid portable_assets.lock.json.' }
        if ((Get-FileHash -LiteralPath (Join-Path $release 'runtime.lock.json')).Hash -ne $assets.runtime_lock_sha256 -or
            (Get-FileHash -LiteralPath (Join-Path $release 'dependencies.lock.json')).Hash -ne $assets.dependency_lock_sha256) { throw 'Runtime locks do not match the portable release.' }
        $script:releaseTag = $assets.release_tag
    }
    $pythonZip = Get-LockedArchive $runtime
    $runtimeDir = Join-Path $InstallDir "runtime\python-$($runtime.version)-amd64"
    $python = Join-Path $runtimeDir 'python.exe'
    $ready = Join-Path $runtimeDir '.ready'
    $runtimeValid = (Test-Path -LiteralPath $ready) -and (Test-Path -LiteralPath $python) -and ((Get-Content -LiteralPath $ready -Raw).Trim() -eq $runtime.sha256)
    if ($runtimeValid) { & $python -c 'import sqlite3, ssl, ctypes' 2>$null; $runtimeValid = $LASTEXITCODE -eq 0 }
    if (-not $runtimeValid) {
        if (Test-Path -LiteralPath $runtimeDir) { $runtimeDir = "$runtimeDir-$installId"; $python = Join-Path $runtimeDir 'python.exe' }
        Expand-CheckedArchive $pythonZip $runtimeDir
        & $python -c 'import sqlite3, ssl, ctypes; print(''Portable Python ready'')'
        if ($LASTEXITCODE -ne 0) { throw 'Portable Python could not start on this PC.' }
        Set-Content -LiteralPath (Join-Path $runtimeDir '.ready') -Value $runtime.sha256
    } else { Write-Host 'Reusing portable Python.' }
    foreach ($package in $dependencies.packages) { $null = Get-LockedArchive $package }
    Write-Host "Archives: $script:reused reused, $script:downloads downloaded."
    & $python (Join-Path $release 'scripts\vendor_dependencies.py') --cache $DownloadCache --store (Join-Path $InstallDir 'dependencies') --target (Join-Path $release 'vendor') --lock (Join-Path $release 'dependencies.lock.json')
    if ($LASTEXITCODE -ne 0) { throw 'Library installation failed.' }

    # First-run settings: only missing keys are added; your values are never changed. Names match Metronome's.
    if (-not (Test-Path -LiteralPath $envPath)) {
        [IO.File]::WriteAllText($envPath, "# flows_dev settings for this PC. Names match Metronome's; see .env.example in the release.`r`n", $utf8)
    }
    if ($metronomeEnv -and -not (Test-Path -LiteralPath 'Env:DG_ENV_FILE')) {
        Set-EnvDefault 'DG_ENV_FILE' $metronomeEnv "Metronome's settings file, found through the MXAnalytics service. Leave the value empty to ignore Metronome's settings."
    }
    if (-not $metronomeEnv) { Write-Host "Metronome's settings file was not found (no MXAnalytics service). Set DG_ENV_FILE in $envPath to share it." -ForegroundColor Yellow }
    Add-EnvPlaceholder 'METRONOME_FLOW_PROFILE' (Join-Path $env:USERPROFILE '.metronome-flow-browser') "Metronome's Flow browser profile (portal sessions and .asap_credentials). This is the default; remove the # only for another folder."
    if (-not $githubToken) { Add-EnvPlaceholder 'DG_GITHUB_TOKEN' '<token>' 'Optional GitHub token for setup.ps1 (same as Metronome). Avoids the anonymous limit on a shared office IP.' }

    # Check before selecting the release: a release that cannot start never replaces a working one.
    $checkCode = 0
    if (-not $SkipCheck) {
        Write-Host ''
        & $python (Join-Path $release 'run.py') --home $InstallDir --check
        $checkCode = $LASTEXITCODE
        if ($checkCode -ge 2) { throw "The new release failed its check (above); the previous release is still selected. Fix the named problem and run setup.ps1 again." }
    }
    $pointer = @{ release = $release; python = $python; commit = $commit; installed_at = [DateTime]::UtcNow.ToString('o') } | ConvertTo-Json
    $pending = Join-Path $InstallDir "current-$installId.json"
    [IO.File]::WriteAllText($pending, $pointer, $utf8)
    $current = Join-Path $InstallDir 'current.json'
    if (Test-Path -LiteralPath $current) { [IO.File]::Replace($pending, $current, (Join-Path $InstallDir 'previous.json')) } else { [IO.File]::Move($pending, $current) }
    Copy-Item -LiteralPath (Join-Path $release 'setup.ps1') -Destination (Join-Path $InstallDir 'setup.ps1') -Force
    Copy-Item -LiteralPath (Join-Path $release 'launcher.py') -Destination (Join-Path $InstallDir 'flows_dev.py') -Force

    # Keep the three newest releases (the selected and previous ones are always kept).
    $keep = @($release)
    $previous = Join-Path $InstallDir 'previous.json'
    if (Test-Path -LiteralPath $previous) { $keep += (Get-Content -LiteralPath $previous -Raw | ConvertFrom-Json).release }
    $old = @(Get-ChildItem -LiteralPath (Join-Path $InstallDir 'releases') -Directory | Sort-Object LastWriteTime -Descending | Select-Object -Skip 3)
    foreach ($dir in $old) { if ($keep -notcontains $dir.FullName) { Remove-Item -LiteralPath $dir.FullName -Recurse -Force -ErrorAction SilentlyContinue } }

    $launcher = Join-Path $InstallDir 'flows_dev.py'
    Write-Host ''
    Write-Host "flows_dev is installed in $InstallDir" -ForegroundColor Green
    Write-Host "Active release: $release"
    if ($checkCode -eq 1) { Write-Host 'Some checks need attention (see the warnings above).' -ForegroundColor Yellow }
    Write-Host "Check again: & '$python' '$launcher' --check"
    Write-Host "Metronome Python-script Flow: script $launcher, arguments starting with the module name (e.g. asap)"
    Write-Host 'Update: run .\setup.ps1 again.'
} catch {
    Write-Host "Setup failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    if ($setupLock) { $setupLock.Dispose() }
}
exit 0
