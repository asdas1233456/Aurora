$ErrorActionPreference = "Stop"

if ($args.Count -lt 1) {
  throw "Usage: .\\scripts\\restore_aurora.ps1 <backup-zip>"
}

$archivePath = $args[0]
if (-not (Test-Path $archivePath)) {
  throw "Backup archive not found: $archivePath"
}

Expand-Archive -Path $archivePath -DestinationPath "." -Force
Write-Host "Restored backup from: $archivePath"
