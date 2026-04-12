#!/usr/bin/env bash
set -euo pipefail

TIMESTAMP="${1:-$(date +%Y%m%d-%H%M%S)}"
ARCHIVE_DIR="${2:-backups}"
ARCHIVE_PATH="${ARCHIVE_DIR}/aurora-backup-${TIMESTAMP}.tar.gz"

mkdir -p "$ARCHIVE_DIR"
tar -czf "$ARCHIVE_PATH" data db logs quarantine
echo "Created backup: $ARCHIVE_PATH"
