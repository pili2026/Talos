#!/bin/bash
set -Eeuo pipefail

# Script to start Talos main_with_api.py (for Raspberry Pi)

# Locate the project root directory (/home/pi/talos)
BASE_DIR="$(dirname "$(dirname "$(realpath "$0")")")"

# Path to your Python virtual environment
VENV_PATH="/home/pi/py312-venv"

# Activate virtual environment
if [ -d "$VENV_PATH" ]; then
  echo "[INFO] Activating virtualenv at $VENV_PATH"
  source "$VENV_PATH/bin/activate"
else
  echo "[ERROR] Virtualenv not found at $VENV_PATH"
  exit 1
fi

# Set environment variables (force log to flush immediately)
export PYTHONUNBUFFERED=1

# Run Talos with configs
exec python "$BASE_DIR/src/main_service.py" \
  --modbus_device "$BASE_DIR/res/modbus_device.yml" \
  --instance_config "$BASE_DIR/res/device_instance_config.yml" \
  --alert_config "$BASE_DIR/res/alert_condition.yml" \
  --control_config "$BASE_DIR/res/control_condition.yml" \
  --snapshot_storage_config "$BASE_DIR/res/snapshot_storage.yml" \
  --system_config "$BASE_DIR/res/system_config.yml" \
  --time_config "$BASE_DIR/res/time_condition.yml" \
  --sender_config "$BASE_DIR/res/sender_config.yml" \
  --notifier_config "$BASE_DIR/res/notifier_config.yml" \
  --virtual_device_config "$BASE_DIR/res/virtual_device.yml" \
  --api-host "0.0.0.0" \
  --api-port "8000" \
  --log-level "INFO"
