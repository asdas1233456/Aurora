#!/usr/bin/env bash

set -euo pipefail

PORT="${1:-8000}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_ROOT="$PROJECT_ROOT/frontend"

cd "$PROJECT_ROOT"

echo
echo "Aurora starting..."
echo "Project root: $PROJECT_ROOT"

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js was not found. Please install Node.js 20+ first."
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm was not found. Please install npm first."
  exit 1
fi

if ! command -v python >/dev/null 2>&1; then
  echo "Python was not found. Please install Python 3.11+ first."
  exit 1
fi

if [ ! -d "$FRONTEND_ROOT" ]; then
  echo "frontend directory was not found."
  exit 1
fi

if [ ! -f ".venv/bin/python" ]; then
  echo "Creating virtual environment..."
  python -m venv .venv
fi

if [ ! -f ".env" ]; then
  echo "Creating .env file..."
  cp .env.example .env
fi

if [ ! -f ".venv/bin/uvicorn" ]; then
  echo "Installing backend dependencies..."
  .venv/bin/python -m pip install -r requirements.txt
fi

if [ ! -d "$FRONTEND_ROOT/node_modules" ]; then
  echo "Installing frontend dependencies..."
  cd "$FRONTEND_ROOT"
  npm install
  cd "$PROJECT_ROOT"
fi

echo "Building React frontend..."
cd "$FRONTEND_ROOT"
npm run build
cd "$PROJECT_ROOT"

echo
echo "Starting FastAPI app with built frontend..."
echo "Open: http://127.0.0.1:${PORT}"
echo

export API_PORT="${PORT}"
.venv/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port "${PORT}"
