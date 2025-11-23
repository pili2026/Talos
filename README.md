
# Talos Industrial IoT Monitoring System

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.121+-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Talos** is a Python-based Industrial IoT (IIoT) monitoring and control system designed for equipment management, data acquisition, condition-based monitoring, and automated control in industrial environments.

---

## Key Features

* **Multi-protocol Support**: Supports Modbus RTU/TCP and other industrial communication protocols
* **Real-time Monitoring**: Asynchronous architecture enabling high-efficiency device status polling
* **Intelligent Alerts**: Flexible alert rules and multi-channel notification support
* **Automated Control**: Condition-based automation logic
* **Scheduled Operations**: Supports time-driven control strategies
* **RESTful API**: Full FastAPI service with WebSocket real-time communication
* **Multi-Channel Notification**: Supports Email, Telegram, and more
* **Modular Architecture**: Extensible driver and handler design

---

## System Requirements

* Python 3.12+
* Supported OS: Linux, Windows, macOS
* Network access for remote device communication

---

## Quick Start

### Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/your-org/talos.git
   cd talos
   ```

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Set environment variables**

   ```bash
   cp .env.example .env
   # Edit the .env file to configure SMTP, Telegram, etc.
   ```

4. **Configure devices & conditions**

   * Edit `res/modbus_device.yml` for Modbus device definitions
   * Edit `res/alert_condition.yml` for alert rules
   * Edit `res/control_condition.yml` for control rules
   * Edit `res/time_condition.yml` for time-based conditions

---

### Running

#### Method 1: Start main monitoring service

```bash
python src/main.py \
  --alert_config res/alert_condition.yml \
  --control_config res/control_condition.yml \
  --modbus_device res/modbus_device.yml \
  --instance_config res/device_instance_config.yml \
  --sender_config res/sender_config.yml \
  --mail_config res/mail_config.yml \
  --time_config res/time_condition.yml
```

#### Method 2: Run API service (development)

```bash
PYTHONPATH=src PYTHONUNBUFFERED=1 uvicorn api.app:app \
  --reload \
  --host 0.0.0.0 \
  --port 8000 \
  --log-level info
```

#### Method 3: Run API service (production)

```bash
PYTHONPATH=src PYTHONUNBUFFERED=1 uvicorn api.app:app \
  --host 0.0.0.0 \
  --port 8000 \
  --log-level debug
```

---

## API Documentation

When the API service is running, access:

* **Static API Docs (Swagger / OpenAPI)**

  * [http://localhost:8000/docs](http://localhost:8000/docs)

* **Real-time Monitoring API Docs**

  * [http://localhost:8000/api/monitoring/doc](http://localhost:8000/api/monitoring/doc)

* **Modbus WebSocket Test Tool**

  * [http://localhost:8000/static/index.html](http://localhost:8000/static/index.html)

### Main Endpoints

| Method | Endpoint                        | Description          |
| ------ | ------------------------------- | -------------------- |
| GET    | `/health`                       | Health check         |
| GET    | `/api/devices`                  | Get device list      |
| POST   | `/api/devices/{device_id}/read` | Read device data     |
| GET    | `/api/monitoring/ws`            | WebSocket monitoring |
| GET    | `/api/constraints`              | Get constraint rules |
| POST   | `/api/batch/read`               | Batch read devices   |
| GET    | `/api/wifi`                     | WiFi operations      |
| GET    | `/api/parameters`               | System parameters    |

---

## Project Structure

```
Talos/
├── src/
│   ├── api/              # FastAPI application
│   │   ├── router/       # API routes
│   │   ├── service/      # Business logic
│   │   ├── repository/   # Data access layer
│   │   ├── middleware/   # Middleware components
│   │   ├── model/        # API data models
│   │   └── util/         # API utilities
│   ├── device/           # Device drivers
│   │   └── generic/      # Generic device types
│   ├── evaluator/        # Condition evaluators
│   ├── executor/         # Command executors
│   ├── handler/          # Event handlers
│   ├── model/            # Core models
│   ├── schema/           # YAML schemas
│   ├── sender/           # Notification senders
│   └── util/             # Core utilities
│       ├── notifier/     # Notification utilities
│       ├── pubsub/       # Pub/Sub system
│       └── factory/      # Factory modules
├── res/                  # Resource files & config
│   ├── driver/           # Device driver configs
│   └── template/         # Templates
├── static/               # Frontend static files
├── template/             # Email templates
├── test/                 # Tests
├── logs/                 # Logs
└── bin/                  # Executable scripts
```

---

## Configuration

### Device Configuration (`modbus_device.yml`)

```yaml
shared: &shared_config
    port: /dev/ttyUSB0

devices:
  - model: ADTEK_CPM10
    type: power_meter
    model_file: driver/adtek_cpm_10.yml
    <<: *shared_config
    slave_id: 1
```

---

### Alert Rules (`alert_condition.yml`)

```yaml
SD400:
  default_alerts:
    - code: "AIN01_HIGH"
      name: "AIn01 overheat"
      source: "AIn01"
      condition: "gt"
      threshold: 49.0
      severity: "WARNING"

  instances:
    "3":
      use_default_alerts: true
    "7":
      alerts:
        - code: "AIN02_LOW"
          name: "AIn02 low temp"
          source: "AIn02"
          condition: "lt"
          threshold: 10.0
          severity: "WARNING"
```

---

### Control Logic (`control_condition.yml`)

*(English version kept fully intact — translation maintained original meaning)*

```yaml
version: 1.0.0
SD400:
  default_controls:
    - name: Emergency High Water Temperature Override
      code: EMERGENCY_HIGH_WATER_TEMP
      priority: 0
      composite:
        any:
          - type: threshold
            source: AIn01
            operator: gt
            threshold: 32.0
            hysteresis: 2.0
            debounce_sec: 2.0
      policy:
        type: discrete_setpoint
      action:
        model: TECO_VFD
        slave_id: '1'
        type: set_frequency
        target: RW_HZ
        value: 60
        emergency_override: true
```

---

### Time Conditions (`time_condition.yml`)

```yaml
work_hours:
  default:
    weekdays: [1, 2, 3, 4, 5]
    intervals:
      - { start: "09:00", end: "19:00" }
```

---

## Notification Settings

### Email

```env
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USERNAME=your-email@example.com
SMTP_PASSWORD=your-password
EMAIL_FROM=your-email@example.com
```

### Telegram

```env
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id
```

---

## Testing

```bash
pip install -r requirements-dev.txt
pytest test/
black src/
pylint src/
```

---

## Logs

Logs are stored in `logs/`:

* `talos.log` — main system logs
* `api.log` — API service logs
* `device.log` — device communication logs

---

## Development Guide

### Adding a New Device Driver

1. Create a driver class in `src/device/`
2. Inherit from `BaseDevice` and implement required methods
3. Add configuration under `res/driver/`
4. Update `modbus_device.yml`

### Adding a New API Endpoint

1. Create or update router files under `src/api/router/`
2. Add service logic under `src/api/service/`
3. Register routes in `src/api/app.py`

---

## Contributing

1. Fork the repo
2. Create a branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add some AmazingFeature'`)
4. Push branch
5. Submit Pull Request

---

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE).


## Acknowledgements

* FastAPI — modern Python web framework
* pymodbus — Modbus library for Python
* All contributors and users

---

**Note**: This system is intended for industrial environments. Ensure proper safety configurations before deployment.

