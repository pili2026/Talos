FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends tzdata && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /tmp

EXPOSE 8000

# EntryPoint Description:
# 1. If /dev/ttyMODBUS0 exists, create /tmp/ttyV0 -> /dev/ttyMODBUS0.
# 2. Use environment variables (if any) to override the config path; otherwise, use the built-in res/*.yml.
# 3. Run src/main_with_api.py; api-host / api-port / log-level can also be modified using env.
ENTRYPOINT ["/bin/bash", "-c", "\
  set -euo pipefail; \
  if [ -e /dev/ttyMODBUS0 ]; then \
    ln -sf /dev/ttyMODBUS0 /tmp/ttyV0; \
    echo '[TALOS] /tmp/ttyV0 -> /dev/ttyMODBUS0'; \
  else \
    echo '[TALOS] WARNING: /dev/ttyMODBUS0 not found, RTU may not work'; \
  fi; \
  python src/main_with_api.py \
    --modbus_device \"${MODBUS_DEVICE:-res/modbus_device.yml}\" \
    --instance_config \"${INSTANCE_CONFIG:-res/device_instance_config.yml}\" \
    --alert_config \"${ALERT_CONFIG:-res/alert_condition.yml}\" \
    --control_config \"${CONTROL_CONFIG:-res/control_condition.yml}\" \
    --snapshot_storage_config \"${SNAPSHOT_STORAGE_CONFIG:-res/snapshot_storage.yml}\" \
    --system_config \"${SYSTEM_CONFIG:-res/system_config.yml}\" \
    --time_config \"${TIME_CONFIG:-res/time_condition.yml}\" \
    --sender_config \"${SENDER_CONFIG:-res/sender_config.yml}\" \
    --notifier_config \"${NOTIFIER_CONFIG:-res/notifier_config.yml}\" \
    --api-host \"${API_HOST:-0.0.0.0}\" \
    --api-port \"${API_PORT:-8000}\" \
    --log-level \"${LOG_LEVEL:-INFO}\" \
"]
