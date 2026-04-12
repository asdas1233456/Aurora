$ErrorActionPreference = "Stop"

$timestamp = if ($args.Count -ge 1) { $args[0] } else { Get-Date -Format "yyyyMMdd-HHmmss" }
$archiveDir = if ($args.Count -ge 2) { $args[1] } else { "backups" }
$archivePath = Join-Path $archiveDir "aurora-backup-$timestamp.zip"

New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
Compress-Archive -Path @("data", "db", "logs", "quarantine") -DestinationPath $archivePath -Force
Write-Host "Created backup: $archivePath"
