# Installs a downloaded upgrade, then starts Karaoke again. Run by Karaoke.cmd from a copy in %TEMP%, because the
# installer replaces the install folder this script came from.
param(
    [Parameter(Mandatory)] [string] $Installer,
    [Parameter(Mandatory)] [string] $Version,
    [Parameter(Mandatory)] [string] $AppDir
)

$Host.UI.RawUI.WindowTitle = "Karaoke upgrade"
Write-Host "Installing Karaoke $Version. Karaoke starts again by itself when it is done..."

# Wait for the old app to let go of the install folder (Karaoke.cmd and the tools in bin\).
$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    $busy = Get-CimInstance Win32_Process | Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($AppDir, [StringComparison]::OrdinalIgnoreCase)) -or
        ($_.CommandLine -and $_.CommandLine -match 'karaoke(\.exe)?\W+serve')
    }
    if (-not $busy) { break }
    Start-Sleep -Milliseconds 500
}
Start-Sleep -Seconds 1

$code = 1
try {
    $p = Start-Process -FilePath $Installer -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOCANCEL' `
        -Wait -PassThru
    $code = $p.ExitCode
} catch {
    Write-Host "The installer could not start: $_"
}

$launcher = Join-Path $AppDir 'Karaoke.cmd'
if ($code -eq 0) {
    Remove-Item -LiteralPath $Installer -ErrorAction SilentlyContinue
    Start-Process -FilePath $launcher
} else {
    Write-Host "The installer exited with code $code. Starting the current version again."
    Start-Process -FilePath $launcher -ArgumentList '--upgrade-failed', $Version
}
