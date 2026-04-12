#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: ./scripts/restore_aurora.sh <backup-tar.gz>" >&2
  exit 1
fi

ARCHIVE_PATH="$1"
if [[ ! -f "$ARCHIVE_PATH" ]]; then
  echo "Backup archive not found: $ARCHIVE_PATH" >&2
  exit 1
fi

tar -xzf "$ARCHIVE_PATH"
echo "Restored backup from: $ARCHIVE_PATH"
