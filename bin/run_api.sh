#!/bin/bash
set -Eeuo pipefail

# Get the project root directory
BASE_DIR="$(dirname "$(dirname "$(realpath "$0")")")"
cd "$BASE_DIR"

echo "[INFO] Starting Talos API Service..."
echo "[INFO] BASE_DIR: $BASE_DIR"

# Set PYTHONPATH (using an absolute path is safer)
export PYTHONPATH="$BASE_DIR/src"
echo "[INFO] PYTHONPATH: $PYTHONPATH"

# Activate virtual environment (if present)
if [ -d "venv" ]; then
  source venv/bin/activate
elif [ -d "../venv/talos" ]; then
  source ../venv/talos/bin/activate
fi

export PYTHONUNBUFFERED=1

# Start FastAPI
exec uvicorn api.app:app \
  --reload \
  --host 0.0.0.0 \
  --port 8000 \
  --log-level info
