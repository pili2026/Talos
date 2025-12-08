#!/bin/bash
set -euo pipefail

echo "[ENTRYPOINT] Starting Talos..."

# Detect mode based on MODBUS_PORT
if [ -n "${MODBUS_PORT:-}" ]; then
  echo "[TALOS] Detected production mode (MODBUS_PORT is set)"
  echo "[TALOS] Real serial device: ${MODBUS_PORT}"

  # Create logical port for Talos (/tmp/ttyV0) pointing to real device
  echo "[TALOS] Mapping /tmp/ttyV0 -> ${MODBUS_PORT}"
  ln -sf "${MODBUS_PORT}" /tmp/ttyV0

  if [ ! -e "${MODBUS_PORT}" ]; then
    echo "[TALOS] WARNING: Device ${MODBUS_PORT} does not exist inside container"
  fi
else
  echo "[TALOS] Detected development mode (MODBUS_PORT is NOT set)"
  echo "[TALOS] Expecting /tmp/ttyV0 to be created by socat on the host and mounted via volume"
fi

echo "[TALOS] Current /tmp contents:"
ls -l /tmp || true

echo "[TALOS] Config paths:"
echo "  MODBUS_DEVICE           = ${MODBUS_DEVICE:-res/modbus_device.yml}"
echo "  INSTANCE_CONFIG         = ${INSTANCE_CONFIG:-res/device_instance_config.yml}"
echo "  ALERT_CONFIG            = ${ALERT_CONFIG:-res/alert_condition.yml}"
echo "  CONTROL_CONFIG          = ${CONTROL_CONFIG:-res/control_condition.yml}"
echo "  SNAPSHOT_STORAGE_CONFIG = ${SNAPSHOT_STORAGE_CONFIG:-res/snapshot_storage.yml}"
echo "  SYSTEM_CONFIG           = ${SYSTEM_CONFIG:-res/system_config.yml}"
echo "  TIME_CONFIG             = ${TIME_CONFIG:-res/time_condition.yml}"
echo "  SENDER_CONFIG           = ${SENDER_CONFIG:-res/sender_config.yml}"
echo "  NOTIFIER_CONFIG         = ${NOTIFIER_CONFIG:-res/notifier_config.yml}"
echo "  API_HOST                = ${API_HOST:-0.0.0.0}"
echo "  API_PORT                = ${API_PORT:-8000}"
echo "  LOG_LEVEL               = ${LOG_LEVEL:-INFO}"

echo "[TALOS] Launching main_with_api.py ..."

python src/main_with_api.py \
  --modbus_device "${MODBUS_DEVICE:-res/modbus_device.yml}" \
  --instance_config "${INSTANCE_CONFIG:-res/device_instance_config.yml}" \
  --alert_config "${ALERT_CONFIG:-res/alert_condition.yml}" \
  --control_config "${CONTROL_CONFIG:-res/control_condition.yml}" \
  --snapshot_storage_config "${SNAPSHOT_STORAGE_CONFIG:-res/snapshot_storage.yml}" \
  --system_config "${SYSTEM_CONFIG:-res/system_config.yml}" \
  --time_config "${TIME_CONFIG:-res/time_condition.yml}" \
  --sender_config "${SENDER_CONFIG:-res/sender_config.yml}" \
  --notifier_config "${NOTIFIER_CONFIG:-res/notifier_config.yml}" \
  --api-host "${API_HOST:-0.0.0.0}" \
  --api-port "${API_PORT:-8000}" \
  --log-level "${LOG_LEVEL:-INFO}"
