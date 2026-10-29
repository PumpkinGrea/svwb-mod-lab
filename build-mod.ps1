$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$buildPython = Join-Path $PSScriptRoot "tools/build-env/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $buildPython)) {
    py -3 -m venv tools/build-env
    if ($LASTEXITCODE -ne 0) { throw "Failed to create build environment" }
}
& $buildPython -m pip install -r requirements-mod.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
if (-not (Test-Path -LiteralPath "local-keys/bundle-base.bin")) { throw "Local bundle base is required" }
New-Item -ItemType Directory -Path "input/mod-build-data" -Force | Out-Null
New-Item -ItemType Directory -Path "input/mod-app-data" -Force | Out-Null
Copy-Item -LiteralPath "local-keys/bundle-base.bin" -Destination "input/mod-app-data/bundle-base.bin"
Copy-Item -LiteralPath "local-keys/bundle-base.bin" -Destination "input/mod-build-data/bundle-base.bin"
Copy-Item -LiteralPath "THIRD_PARTY_NOTICES.md" -Destination "input/mod-build-data/THIRD_PARTY_NOTICES.md"
Copy-Item -LiteralPath "USER_GUIDE.md" -Destination "input/mod-build-data/USER_GUIDE.md"
& $buildPython collect-mod-licenses.py
if ($LASTEXITCODE -ne 0) { throw "License collection failed" }
$bundleData = Join-Path $PSScriptRoot "input/mod-build-data"
# Do not collect unrelated DLLs from ambient tools (e.g. Poppler's incompatible ICU).
# Qt expects Windows' system ICU exports, not the version-suffixed third-party ICU.
$originalBuildPath = $env:PATH
try {
    $env:PATH = @((Split-Path $buildPython -Parent), [Environment]::SystemDirectory, $env:SystemRoot) -join ';'
    & $buildPython -m PyInstaller --noconfirm --clean --onedir --windowed --name SVWBCardMod --distpath dist --workpath build --specpath build --add-data "$bundleData/bundle-base.bin;app-data" --add-data "$bundleData/USER_GUIDE.md;app-data" --add-data "$bundleData/THIRD_PARTY_NOTICES.md;app-data" --add-data "$bundleData/licenses;app-data/licenses" --collect-all UnityPy --collect-all etcpak --collect-all astc_encoder --collect-all texture2ddecoder --collect-all fmod_toolkit --collect-all archspec mod-entry.py
    if ($LASTEXITCODE -ne 0) { throw "Executable build failed" }
} finally {
    $env:PATH = $originalBuildPath
}
Copy-Item -LiteralPath "USER_GUIDE.md" -Destination "dist/SVWBCardMod/USER_GUIDE.md"
Copy-Item -LiteralPath "THIRD_PARTY_NOTICES.md" -Destination "dist/SVWBCardMod/THIRD_PARTY_NOTICES.md"
$buildSmokeReport = Join-Path $PSScriptRoot 'input/mod-build-data/startup-smoke.json'
$buildSmokeExe = Join-Path $PSScriptRoot 'dist/SVWBCardMod/SVWBCardMod.exe'
$buildSmoke = Start-Process -FilePath $buildSmokeExe -ArgumentList @('--smoke-test', ('"' + $buildSmokeReport + '"')) -WindowStyle Hidden -PassThru
$buildSmokeHandle = $buildSmoke.Handle
if (-not $buildSmoke.WaitForExit(60000)) { throw 'Packaged startup check timed out; build not verified' }
if ($buildSmoke.ExitCode -ne 0) { throw "Packaged startup check failed; see $buildSmokeReport" }
$smokeResult = Get-Content -LiteralPath $buildSmokeReport -Raw -Encoding UTF8 | ConvertFrom-Json
if ($smokeResult.error) { throw "Packaged startup check failed: $($smokeResult.error)" }
Write-Host "Windows test build: dist/SVWBCardMod/SVWBCardMod.exe"
Write-Host "Offline build: no bundled search catalog or online updater. Bundle base and dependency notices are included."
