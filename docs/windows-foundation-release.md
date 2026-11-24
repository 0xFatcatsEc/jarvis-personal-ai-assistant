# Install the Windows Foundation release offline

The release folder contains the dedicated Windows x64 CPython interpreter, SQLite, headless Ollama, the M0 assets, the application wheel, and its locked dependency wheels. Copy the whole folder when moving the release. Keep it on a local disk with room for the bundle and one extracted installation. Personal settings, chat databases and diagnostic logs belong to the Windows profile.

## Install

The qualified MSI build is under `%LOCALAPPDATA%\StylusJarvis-Releases\foundation-0.1.0`. Its bundle manifest SHA-256 is `7963de8e8cd8efc8cc58dc93c443e6bf0ded7e2af92710bc512ff6bd7651215c`. The [release inventory](evidence/1.3.2.1/bundle.json) lists payload fingerprints and schema checksums.

Use ordinary Windows PowerShell under the account that will run the desktop. Start in the bundle directory. Use the SHA-256 of the reviewed release manifest from the release evidence. Authenticate the installer before executing it.

```powershell
$pin = Read-Host 'Paste the published bundle.json SHA-256'
if ((Get-FileHash -LiteralPath .\bundle.json).Hash -ne $pin) { throw 'Manifest mismatch' }
$manifest = Get-Content -LiteralPath .\bundle.json -Raw | ConvertFrom-Json
if ((Get-FileHash -LiteralPath .\install-release.ps1).Hash -ne $manifest.files.'install-release.ps1') { throw 'Installer mismatch' }
.\install-release.ps1 -ManifestSha256 $pin
```

The installer requires an unused `%LOCALAPPDATA%\StylusJarvis` directory. For a parallel acceptance installation on the development MSI, append `-Rehearsal`. Its dedicated directory is `%LOCALAPPDATA%\StylusJarvis-Rehearsal`. The installer validates all listed files before extraction. It installs the verified wheels using the bundled interpreter with the package index disabled. If extraction or wheel installation fails, inspect the sibling staging directory and retry from the bundle.

In administrator Windows PowerShell under the same account, enter the installed directory and run `.\launch-release.ps1 -Component InstallRules`. This installs the program-specific outbound blocks for the installed binaries. Use ordinary PowerShell for both launches. Run `.\launch-release.ps1 -Component Model` in one terminal and `.\launch-release.ps1` in another. Both commands use the installed interpreter and local models. If the default port is occupied, choose a free loopback port in `config\settings.toml` before starting either component.

## Upgrade and rollback

Close the desktop and stop its model server before switching installations. Retain the entire earlier profile under a sibling backup name on the same disk. Install the new release at the canonical path. While both applications are closed, copy the earlier profile's configuration and complete data directory, including any WAL files and recovery records, into the new profile. Keep the earlier copy intact. Start the new desktop and reopen the sample conversation. Migrations keep a separate SQLite backup before each upgrade. For a binary and data rollback, close both components, move the candidate profile aside, restore the earlier profile to its original path, and verify its firewall rules before launching it. Changes made after the backup remain in the candidate profile.

## Build and verify on the MSI

From the repository root, build from the provisioned private runtime and hash-verified M0 store. Assembly requires uv, the pinned setuptools build backend, and access to any dependency wheels missing from the local cache. Release installation reads only local files.

```powershell
$base = [Environment]::GetFolderPath('LocalApplicationData')
$releases = Join-Path $base 'StylusJarvis-Releases'
$env:UV_CACHE_DIR = (Resolve-Path '.uv-cache').Path
& "$base\StylusJarvis\runtime\python\python.exe" -B packaging/windows/build_release.py "$releases\foundation-0.1.0" --wheel-cache "$releases\wheel-cache"
```

Builds require a fresh output directory. Keep the printed manifest fingerprint with that build. After installing with `-Rehearsal` and installing its rules, run the following from the repository root in ordinary PowerShell. The desktop rehearsal creates a sample project in the new profile and requires a fresh database. It uses a private loopback port and a real Qwen response. The second rehearsal uses the schema-1 application code from local Git history, upgrades a disposable database, restores the pre-upgrade backup, and reads the same history with the earlier code.

```powershell
$python = Join-Path $env:LOCALAPPDATA 'StylusJarvis-Rehearsal\runtime\python\python.exe'
& $python -I -B packaging/windows/qualify_release.py
& $python -I -B packaging/windows/qualify_upgrade.py
& $python -I -B -m unittest discover -s tests -p test_local_store.py -v
```
