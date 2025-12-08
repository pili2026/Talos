#!/bin/bash
set -euo pipefail

echo "[ENTRYPOINT] Starting Talos container..."

if [ -e /tmp/ttyV0 ]; then
  echo "[TALOS] Using RTU port: /tmp/ttyV0"
else
  echo "[TALOS] WARNING: /tmp/ttyV0 not found, RTU may not work"
  echo "[TALOS] Current /tmp contents:"
  ls -l /tmp || true
fi

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
