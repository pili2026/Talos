#!/bin/bash

# Script to start Talos main.py (for Raspberry Pi)

# Locate the project root directory (/home/pi/talos)
BASE_DIR="$(dirname "$(dirname "$(realpath "$0")")")"

# Set environment variables (force log to flush immediately)
export PYTHONUNBUFFERED=1

# Execute main.py with configs
python3.12 "$BASE_DIR/src/main.py" \
  --alert_config "$BASE_DIR/res/alert_condition.yml" \
  --control_config "$BASE_DIR/res/control_condition.yml" \
  --modbus_device "$BASE_DIR/res/modbus_device.yml" \
  --instance_config "$BASE_DIR/res/device_instance_config.yml" \
  --sender_config "$BASE_DIR/res/sender_config.yml" \
  --mail_config "$BASE_DIR/res/mail_config.yml" \
  --time_config "$BASE_DIR/res/time_condition.yml" \
  --system_config "$BASE_DIR/res/system_config.yml"
