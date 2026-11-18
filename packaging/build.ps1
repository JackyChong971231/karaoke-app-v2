# Builds packaging\out\Karaoke-Setup-<version>.exe. Used by .github/workflows/release.yml and runnable locally:
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
# Needs: web\dist built (npm run build in web\), and Inno Setup 6 (ISCC.exe) on PATH or in its usual folders.
param([string] $Iscc = "")

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$here = $PSScriptRoot
$root = Split-Path $here -Parent

# Pinned tools. Bump deliberately and test.
$UvVersion = '0.13.7'
$DenoVersion = '2.9.8'
$FfmpegVersion = '8.0'

$version = (Select-String -Path "$root\server\pyproject.toml" -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
Write-Host "Karaoke $version"
if (-not (Test-Path "$root\web\dist\index.html")) { throw 'web\dist is not built. Run npm run build in web\ first.' }

$out = Join-Path $here 'out'
$stage = Join-Path $out 'stage'
$cache = Join-Path $out 'downloads'
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force $stage, $cache, "$stage\bin", "$stage\server", "$stage\web" | Out-Null

function Get-Zip([string] $url, [string] $name) {
    $zip = Join-Path $cache $name
    if (-not (Test-Path $zip)) {
        Write-Host "Downloading $url"
        Invoke-WebRequest -Uri $url -OutFile "$zip.part"
        Move-Item "$zip.part" $zip
    }
    $dir = Join-Path $cache ([IO.Path]::GetFileNameWithoutExtension($name))
    if (-not (Test-Path $dir)) { Expand-Archive -Path $zip -DestinationPath $dir }
    return $dir
}

$uv = Get-Zip "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-x86_64-pc-windows-msvc.zip" "uv-$UvVersion.zip"
Copy-Item "$uv\uv.exe", "$uv\uvx.exe" "$stage\bin"
$deno = Get-Zip "https://github.com/denoland/deno/releases/download/v$DenoVersion/deno-x86_64-pc-windows-msvc.zip" "deno-$DenoVersion.zip"
Copy-Item "$deno\deno.exe" "$stage\bin"
$ff = Get-Zip "https://github.com/GyanD/codexffmpeg/releases/download/$FfmpegVersion/ffmpeg-$FfmpegVersion-essentials_build.zip" "ffmpeg-$FfmpegVersion.zip"
Get-ChildItem $ff -Recurse -Include ffmpeg.exe, ffprobe.exe | Copy-Item -Destination "$stage\bin"

Copy-Item "$root\server\pyproject.toml", "$root\server\uv.lock" "$stage\server"
Copy-Item "$root\server\src" "$stage\server\src" -Recurse
Get-ChildItem "$stage\server\src" -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
Copy-Item "$root\web\dist" "$stage\web\dist" -Recurse
Copy-Item "$here\Karaoke.cmd", "$here\upgrade.ps1" $stage

if (-not $Iscc) {
    $found = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    $candidates = @(
        $(if ($found) { $found.Source }),
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }
    if (-not $candidates) { throw 'ISCC.exe (Inno Setup 6) was not found.' }
    $Iscc = @($candidates)[0]
}
& $Iscc "/DAppVersion=$version" "$here\karaoke.iss"
if ($LASTEXITCODE -ne 0) { throw "ISCC failed with exit code $LASTEXITCODE" }
Write-Host "Built $out\Karaoke-Setup-$version.exe"
