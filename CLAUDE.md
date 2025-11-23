# CLAUDE.md - AI Assistant Guide for Talos

> **Last Updated:** 2025-11-23
> **Version:** Based on commit 3e6c471 (AT-32)

This document provides comprehensive guidance for AI assistants working with the Talos codebase. It covers project structure, architecture patterns, development workflows, and conventions.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Repository Structure](#repository-structure)
3. [Architecture & Design Patterns](#architecture--design-patterns)
4. [Development Workflows](#development-workflows)
5. [Code Conventions](#code-conventions)
6. [Configuration Management](#configuration-management)
7. [Testing Guidelines](#testing-guidelines)
8. [API Development](#api-development)
9. [Device Integration](#device-integration)
10. [Common Tasks](#common-tasks)
11. [Important Notes](#important-notes)

---

## Project Overview

### What is Talos?

Talos is an **industrial IoT device management and control platform** designed for Modbus-based industrial automation. It provides:

- **Device Communication:** Point-to-point Modbus RTU over RS-485 serial connections
- **Real-time Monitoring:** Continuous polling and state tracking of industrial devices
- **Automated Control:** Condition-based control automation with priority-based execution
- **Alert Management:** Intelligent alerting with multi-channel notifications (Email, SMS, Telegram, Webhooks)
- **Data Persistence:** Cloud integration and local data storage
- **RESTful API:** FastAPI-based REST and WebSocket endpoints for device management

### Core Problem

Managing heterogeneous industrial devices (VFDs, power meters, I/O modules, sensors) across serial/Modbus networks with:
- Dynamic automation and safety constraints
- Intelligent notifications and alerting
- Automated responses to device state changes
- Eliminating manual monitoring

### Technology Stack

- **Language:** Python 3.x (async/await throughout)
- **Framework:** FastAPI (REST API), Uvicorn (ASGI server)
- **Protocol:** Modbus RTU via pymodbus 3.9.2
- **Validation:** Pydantic 2.11.5
- **Communication:** aiohttp, httpx, websockets
- **I/O:** aiofiles, pyserial, aiosmtplib
- **Configuration:** YAML (PyYAML)
- **Testing:** pytest, pytest-asyncio
- **Code Quality:** black (line-length: 120), isort, pylint

---

## Repository Structure

```
Talos/
├── src/                          # Main application source code
│   ├── main.py                   # Standalone application entry point
│   ├── device_manager.py         # AsyncDeviceManager - manages all devices
│   ├── device_monitor.py         # AsyncDeviceMonitor - polling loop
│   │
│   ├── api/                      # FastAPI REST & WebSocket service
│   │   ├── app.py                # FastAPI application factory
│   │   ├── dependency.py         # Dependency injection container
│   │   ├── lifecycle.py          # Startup/shutdown hooks
│   │   ├── router/               # API endpoints (devices, parameters, constraints, wifi, batch, monitoring)
│   │   ├── service/              # Business logic layer
│   │   ├── repository/           # Data access layer
│   │   ├── middleware/           # Middleware (error handlers, logging)
│   │   ├── model/                # API request/response models
│   │   └── util/                 # API-specific utilities
│   │
│   ├── device/                   # Device abstraction and drivers
│   │   └── generic/              # Generic Modbus device implementation
│   │       ├── generic_device.py        # AsyncGenericModbusDevice class
│   │       ├── modbus_bus.py            # Modbus protocol communication
│   │       ├── constraints_policy.py    # Per-device write constraints
│   │       ├── scales.py                # Value scaling (lookup tables, modes)
│   │       ├── hooks.py                 # Pre/post write hooks
│   │       └── computed_field_processor.py # Computed/derived fields
│   │
│   ├── evaluator/                # Condition evaluation engines
│   │   ├── alert_evaluator.py           # Alert rule evaluation
│   │   ├── alert_state_manager.py       # Alert state tracking (dedup/suppress)
│   │   ├── control_evaluator.py         # Control rule evaluation
│   │   ├── composite_evaluator.py       # Boolean logic evaluation (AND/OR/NOT)
│   │   ├── constraint_evaluator.py      # Constraint-based rules
│   │   └── time_evaluator.py            # Time-based controls
│   │
│   ├── executor/                 # Action execution engines
│   │   ├── control_executor.py          # Executes control actions
│   │   └── time_control_executor.py     # Executes time-based controls
│   │
│   ├── handler/                  # Event handlers
│   │   └── time_control_handler.py      # Time-based control orchestration
│   │
│   ├── sender/                   # Data persistence & cloud integration
│   │   ├── outbox_store.py              # Persistent queue management
│   │   ├── transport.py                 # Transport abstraction
│   │   └── legacy/                      # Legacy sender for cloud integration
│   │
│   ├── schema/                   # Pydantic data models for config validation
│   │   ├── alert_schema.py
│   │   ├── control_config_schema.py
│   │   ├── constraint_schema.py
│   │   ├── notifier_schema.py
│   │   ├── sender_schema.py
│   │   └── system_config_schema.py
│   │
│   ├── model/                    # Domain models & constants
│   │   ├── enum/                 # Enums (AlertSeverity, ControlActionType, etc.)
│   │   ├── control_composite.py  # Control composite expression tree
│   │   └── device_constant.py    # Device constants (register names, etc.)
│   │
│   └── util/                     # Shared utilities
│       ├── config_manager.py            # YAML config loading & parsing
│       ├── device_id_policy.py          # Device ID generation policy
│       ├── pubsub/                      # Pub/sub message broker
│       │   ├── in_memory_pubsub.py      # In-memory implementation
│       │   ├── subscriber/              # Subscriber implementations
│       │   └── pubsub_topic.py          # Topic definitions
│       ├── factory/                     # Factory functions for building components
│       ├── notifier/                    # Notification backends (email, SMS, Telegram, webhook)
│       ├── decorator/                   # Decorators (async_retry)
│       ├── system_info/                 # System utilities
│       └── register_formula.py          # Register value calculations
│
├── res/                          # Configuration files (YAML)
│   ├── alert_condition.yml       # Alert definitions per device model/instance
│   ├── control_condition.yml     # Control rules per device
│   ├── modbus_device.yml         # Physical device definitions
│   ├── device_instance_config.yml # Constraints per device instance
│   ├── sender_config.yml         # Data sender configuration
│   ├── notifier_config.yml       # Notification routing rules
│   ├── system_config.yml         # Global system settings
│   ├── time_condition.yml        # Time-based control rules
│   ├── driver/                   # Device driver definitions (YAML) - 13 drivers
│   └── template/                 # Email templates & Modbus device template
│
├── test/                         # Comprehensive test suite
│   ├── control/                  # Control evaluator & executor tests
│   ├── device/                   # Device and Modbus tests
│   ├── alert_evaluator/          # Alert evaluation tests
│   ├── constraint/               # Constraint policy tests
│   ├── sender/                   # Data sender tests
│   ├── util/                     # Utility function tests
│   └── time_control/             # Time-based control tests
│
├── static/                       # Frontend assets (Vue.js application)
├── template/                     # Email templates
├── bin/                          # Executable scripts
├── logs/                         # Runtime logs & state storage
├── doc/                          # Documentation
│   ├── asyncapi.yml             # WebSocket API specification
│   └── alert_state_schema.sql   # Alert state database schema
│
├── .env                          # Environment variables (secrets)
├── .gitignore                    # Git ignore patterns
├── .pylintrc                     # Pylint configuration
├── pyproject.toml                # Python project config (black, isort)
├── requirements.txt              # Production dependencies
├── requirements-dev.txt          # Development dependencies
└── README.md                     # Project README
```

---

## Architecture & Design Patterns

### Event-Driven Pub/Sub Architecture

Talos uses an **in-memory pub/sub broker** to decouple components:

```
┌─────────────────────────────────────────────────────────────────┐
│                   AsyncDeviceMonitor (Polling Loop)             │
│                   Publishes: DEVICE_SNAPSHOT                    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
            ┌───────────────▼────────────────┐
            │      InMemoryPubSub            │
            │                                │
            │  Topics:                       │
            │  • DEVICE_SNAPSHOT             │
            │  • ALERT_WARNING               │
            │  • CONTROL                     │
            │  • SNAPSHOT_ALLOWED            │
            └───────────┬────────────────────┘
                        │
        ┌───────┬───────┼───────┬────────┬──────────┐
        │       │       │       │        │          │
    ┌───▼──┐ ┌─▼───┐ ┌─▼────┐ ┌▼─────┐ ┌▼──────┐ ┌▼──────┐
    │CTRL  │ │ALERT│ │CONSTR│ │TIME  │ │SENDER │ │WS     │
    │EVAL  │ │EVAL │ │EVAL  │ │CTRL  │ │SUB    │ │SUB    │
    └───┬──┘ └──┬──┘ └──┬───┘ └┬─────┘ └───────┘ └───────┘
        │       │       │       │
    ┌───▼──┐ ┌──▼────┐ │       │
    │CTRL  │ │ALERT  │ │       │
    │EXEC  │ │NOTIFY │ │       │
    └───┬──┘ └───┬───┘ │       │
        │        │     │       │
        ▼        ▼     ▼       ▼
    ┌──────────────────────────────────┐
    │    AsyncDeviceManager            │
    │    (manages all devices)         │
    └──────────────────────────────────┘
```

### Key Design Patterns

#### 1. Pub/Sub (Event-Driven)
- **Location:** `src/util/pubsub/`
- **Topics:** DEVICE_SNAPSHOT, ALERT_WARNING, CONTROL, SNAPSHOT_ALLOWED
- **Subscribers:** Run as async tasks; can be enabled/disabled via system_config.yml
- **Implementation:** In-memory async queue-based delivery

#### 2. Factory Pattern
- **Location:** `src/util/factory/`
- **Purpose:** Encapsulate construction logic for complex components
- **Factories:** AlertFactory, ControlFactory, NotifierFactory, DeviceFactory
- **Usage:** Build evaluators, notifiers, and devices from configuration

#### 3. Dependency Injection (FastAPI)
- **Location:** `src/api/dependency.py`
- **Pattern:** Singleton for shared resources, request-scoped for per-request data
- **Injectables:** ConfigRepository, DeviceManager, WiFiService, ConstraintService

#### 4. State Management
- **AlertStateManager:** Tracks alert states (triggered/resolved) to deduplicate notifications
- **ControlExecutor:** Maintains priority-based execution state to prevent lower-priority overrides
- **OutboxStore:** Manages persistent queue for data sender retry logic

#### 5. Strategy Pattern
- **ControlPolicyType:** DISCRETE_SETPOINT, ABSOLUTE_LINEAR, INCREMENTAL_LINEAR
- **NotifierType:** Email, SMS, Telegram, Webhook
- **ScaleType:** Lookup tables, modes, formulas

#### 6. Composite Expression Tree
- **Location:** `src/model/control_composite.py`
- **Purpose:** Represent boolean logic (AND/OR/NOT) for control/alert conditions
- **Evaluator:** Recursive tree traversal in CompositeEvaluator

### Core Components

| Component | Responsibility | Location |
|-----------|----------------|----------|
| **AsyncDeviceManager** | Initialize and manage all Modbus devices; handle device lookup | `src/device_manager.py` |
| **AsyncDeviceMonitor** | Polling loop; read all device values; publish snapshots | `src/device_monitor.py` |
| **AsyncGenericModbusDevice** | Abstraction for a single Modbus device; read/write with scaling, constraints, hooks | `src/device/generic/generic_device.py` |
| **ControlEvaluator** | Evaluate control conditions; return prioritized action lists | `src/evaluator/control_evaluator.py` |
| **ControlExecutor** | Execute control actions with priority protection | `src/executor/control_executor.py` |
| **AlertEvaluator** | Evaluate alert thresholds; manage state transitions | `src/evaluator/alert_evaluator.py` |
| **AlertStateManager** | Track alert states to prevent duplicate notifications | `src/evaluator/alert_state_manager.py` |
| **AlertNotifierSubscriber** | Route alerts through notification channels; fallback chain | `src/util/pubsub/subscriber/alert_notifier_subscriber.py` |
| **ConstraintPolicy** | Validate write values against min/max constraints | `src/device/generic/constraints_policy.py` |
| **ConfigRepository** | Singleton; cache config in memory; provide synchronized access | `src/api/repository/config_repository.py` |

---

## Development Workflows

### Environment Setup

```bash
# Set PYTHONPATH
export PYTHONPATH=./src:./test:$PYTHONPATH
export PYTHONUNBUFFERED=1

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Configure environment variables
cp .env.example .env  # If exists
# Edit .env with your credentials
```

### Running the Application

#### Standalone Mode (main.py)

Runs the device monitor and control system without API:

```bash
python src/main.py \
  --alert_config res/alert_condition.yml \
  --control_config res/control_condition.yml \
  --modbus_device res/modbus_device.yml \
  --instance_config res/device_instance_config.yml \
  --sender_config res/sender_config.yml \
  --notifier_config res/notifier_config.yml \
  --system_config res/system_config.yml \
  --time_config res/time_condition.yml
```

#### API Server Mode (FastAPI)

**Development (with auto-reload):**
```bash
PYTHONPATH=src PYTHONUNBUFFERED=1 uvicorn api.app:app \
  --reload \
  --host 0.0.0.0 \
  --port 8000 \
  --log-level info
```

**Production (no reload):**
```bash
PYTHONPATH=src PYTHONUNBUFFERED=1 uvicorn api.app:app \
  --host 0.0.0.0 \
  --port 8000 \
  --log-level info
```

### API Documentation

- **Swagger UI:** http://0.0.0.0:8000/docs
- **ReDoc:** http://0.0.0.0:8000/redoc
- **AsyncAPI (WebSocket):** http://0.0.0.0:8000/api/monitoring/doc
- **Modbus Test Tool:** http://0.0.0.0:8000/static/index.html

### Testing

```bash
# Run all tests
pytest

# Run specific test directory
pytest test/control/evaluator/ -v

# Run with coverage
pytest --cov=src --cov-report=html

# Run async tests with verbose output
pytest test/device/ -v -m asyncio

# Run specific test file
pytest test/control/executor/test_control_executor.py -v
```

### Code Quality

**Formatting:**
```bash
# Format code with black (line-length: 120)
black src/ test/

# Sort imports with isort
isort src/ test/
```

**Linting:**
```bash
# Run pylint
pylint src/

# Run with custom config
pylint --rcfile=.pylintrc src/
```

**Pre-commit Hooks:**
```bash
# Install pre-commit hooks (if configured)
pre-commit install

# Run manually
pre-commit run --all-files
```

---

## Code Conventions

### Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| **Device IDs** | `{model}_{slave_id}` | `TECO_VFD_1`, `SD400_3` |
| **Classes** | PascalCase | `AsyncDeviceManager`, `AlertEvaluator` |
| **Functions/Methods** | snake_case | `read_value()`, `evaluate()` |
| **Constants** | UPPER_SNAKE_CASE | `DEFAULT_MISSING_VALUE`, `REG_RW_ON_OFF` |
| **Private Methods** | `_leading_underscore` | `_poll_once()`, `_validate_config()` |
| **Register Names** | Descriptive UPPER_CASE | `RW_HZ`, `RW_ON_OFF`, `AIn01` |
| **Config Keys** | snake_case or UPPER_CASE | `startup_frequency`, `MONITOR_INTERVAL_SECONDS` |
| **Log Messages** | `[CONTEXT] message` | `[EXEC] Device XYZ not found`, `[{device_id}] Status OK` |

### File Organization

#### Import Order
1. Standard library imports
2. Third-party imports
3. Local application imports

**Example:**
```python
import asyncio
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel

from device.generic.generic_device import AsyncGenericModbusDevice
from util.config_manager import ConfigManager
```

#### Class Structure
```python
class MyComponent:
    """
    Component description.

    Responsibilities:
    - Responsibility 1
    - Responsibility 2
    """

    def __init__(self, config: Dict):
        """Initialize component."""
        self.config = config
        self.logger = logging.getLogger(__name__)

    async def public_method(self, param: str) -> Dict:
        """Public method with docstring."""
        result = await self._private_method(param)
        return result

    async def _private_method(self, param: str) -> Dict:
        """Private method with leading underscore."""
        # Implementation
        pass
```

### Type Hints

- **Required:** All public functions and methods
- **Recommended:** Private methods, class attributes
- **Common Types:** `Dict`, `List`, `Optional`, `Union`, `Tuple`, `Any`
- **Async:** Use `async def` with proper return type hints

**Example:**
```python
async def read_device_value(
    device_id: str,
    register_name: str,
    timeout: Optional[float] = None
) -> Optional[float]:
    """Read a value from a device register."""
    pass
```

### Error Handling

```python
# Good: Log and handle specific exceptions
try:
    value = await device.read_value(register_name)
except ModbusException as e:
    self.logger.error(f"[{device_id}] Modbus error: {e}")
    return None
except Exception as e:
    self.logger.exception(f"[{device_id}] Unexpected error: {e}")
    raise

# Good: Use async context managers
async with aiofiles.open(file_path, 'r') as f:
    content = await f.read()
```

### Logging

```python
import logging

logger = logging.getLogger(__name__)

# Use appropriate log levels
logger.debug(f"[{device_id}] Reading register {register_name}")
logger.info(f"[{device_id}] Device initialized successfully")
logger.warning(f"[{device_id}] Connection timeout, retrying...")
logger.error(f"[{device_id}] Failed to write value: {error}")
logger.exception(f"[{device_id}] Critical error:")  # Includes traceback
```

---

## Configuration Management

### Configuration Hierarchy

**Loading Order (highest to lowest priority):**
1. Instance-level config (device_instance_config.yml)
2. Device-level config (modbus_device.yml)
3. Model-level config (driver/{model}.yml)
4. System-level config (system_config.yml)

### Configuration Files

#### system_config.yml
```yaml
MONITOR_INTERVAL_SECONDS: 1.0  # Polling interval
DEVICE_ID_POLICY: "MODEL_SLAVE"  # Device ID generation policy
SUBSCRIBERS:
  CONTROL_SUBSCRIBER: true
  ALERT_EVALUATOR_SUBSCRIBER: true
  ALERT_NOTIFIER_SUBSCRIBER: true
  # ... other subscribers
```

#### modbus_device.yml
```yaml
devices:
  - model: TECO_VFD
    port: /dev/ttyUSB0
    slave_id: 1
    baudrate: 9600
    parity: N
    stopbits: 1
    bytesize: 8
```

#### device_instance_config.yml
```yaml
constraints:
  TECO_VFD_1:
    RW_HZ:
      min: 0.0
      max: 60.0
    RW_ON_OFF:
      min: 0
      max: 1

startup_frequency:
  TECO_VFD_1: 30.0
```

#### alert_condition.yml
```yaml
model_level:
  TECO_VFD:
    - alert_code: TEMP_HIGH
      severity: WARNING
      operator: gt
      threshold: 50.0
      target_register: TEMPERATURE
      message: "Temperature exceeded threshold"

instance_level:
  TECO_VFD_1:
    - alert_code: CRITICAL_TEMP
      severity: CRITICAL
      operator: gt
      threshold: 70.0
      target_register: TEMPERATURE
      message: "Critical temperature!"
```

#### control_condition.yml
```yaml
- device_id: TECO_VFD_1
  priority: 1
  condition:
    type: THRESHOLD
    operator: gt
    threshold: 50.0
    target_register: TEMPERATURE
  action:
    action_type: SET_FREQUENCY
    target_register: RW_HZ
    value: 20.0
  policy_type: DISCRETE_SETPOINT
```

### Device Driver Structure

**Location:** `res/driver/{model}.yml`

```yaml
model: DEVICE_NAME
register_type: holding  # or input, discrete_input, discrete_output
type: inverter  # or power_meter, sensor, io_module

register_map:
  REGISTER_NAME:
    offset: 10
    format: u16  # u8, u16, u32, i16, i32, float, be32 (big-endian 32-bit)
    readable: true
    writable: false
    scale_from: index_table_name  # optional
    min: 0.0  # optional constraint
    max: 100.0  # optional constraint
    formula: "value * 100"  # optional calculation

tables:  # Lookup tables for scaling
  voltage_index:
    0: 120
    1: 240

modes:  # Mode-based configurations
  operation_mode:
    0: idle
    1: run

hooks:  # Pre/post write hooks
  pre_write:
    - register: RW_HZ
      hook: apply_pt_ct_ratio
  post_write:
    - register: RW_HZ
      hook: verify_write

computed_fields:  # Derived fields
  - name: POWER_KW
    formula: "VOLTAGE * CURRENT / 1000"
    depends_on: [VOLTAGE, CURRENT]
```

---

## Testing Guidelines

### Test Structure

**Mirror source structure:** `test/` parallels `src/`

```
test/
├── control/
│   ├── evaluator/
│   │   ├── test_control_evaluator.py
│   │   └── test_composite_evaluator.py
│   ├── executor/
│   │   └── test_control_executor.py
│   └── integration/
│       └── test_control_flow.py
├── device/
│   ├── test_generic_device.py
│   └── test_modbus_bus.py
└── conftest.py  # Shared fixtures
```

### Test Patterns

#### Basic Test Structure
```python
import pytest
from unittest.mock import Mock, AsyncMock

class TestComponent:
    def test_when_condition_then_behavior(self):
        # Arrange
        component = Component(config)

        # Act
        result = component.process(input_data)

        # Assert
        assert result == expected_output
```

#### Async Test
```python
@pytest.mark.asyncio
async def test_async_operation():
    # Arrange
    device = AsyncGenericModbusDevice(config)

    # Act
    value = await device.read_value("REGISTER_NAME")

    # Assert
    assert value == expected_value
```

#### Fixtures (conftest.py)
```python
import pytest

@pytest.fixture
def mock_device_config():
    return {
        "model": "TECO_VFD",
        "slave_id": 1,
        "port": "/dev/ttyUSB0"
    }

@pytest.fixture
async def device_manager(mock_device_config):
    manager = AsyncDeviceManager([mock_device_config])
    await manager.initialize()
    yield manager
    await manager.cleanup()
```

#### Mocking Modbus Communication
```python
@pytest.mark.asyncio
async def test_read_value_success(mocker):
    # Mock Modbus client
    mock_client = AsyncMock()
    mock_client.read_holding_registers.return_value = Mock(registers=[100])

    # Inject mock
    device = AsyncGenericModbusDevice(config)
    device.modbus_bus.client = mock_client

    # Test
    value = await device.read_value("RW_HZ")
    assert value == 50.0  # After scaling
```

### Test Categories

- **Unit Tests:** Test individual components in isolation
- **Integration Tests:** Test component interactions
- **End-to-End Tests:** Test complete workflows

### Running Specific Tests

```bash
# Run control evaluator tests
pytest test/control/evaluator/ -v

# Run a specific test class
pytest test/control/executor/test_control_executor.py::TestControlExecutor -v

# Run a specific test method
pytest test/control/executor/test_control_executor.py::TestControlExecutor::test_priority_protection -v

# Run with keyword matching
pytest -k "priority" -v
```

---

## API Development

### Router Structure

**Location:** `src/api/router/`

```python
from fastapi import APIRouter, Depends, HTTPException
from api.dependency import get_device_manager
from api.model.device_model import DeviceResponse

router = APIRouter(prefix="/api/devices", tags=["devices"])

@router.get("", response_model=list[DeviceResponse])
async def list_devices(
    device_manager: AsyncDeviceManager = Depends(get_device_manager)
):
    """List all devices."""
    devices = await device_manager.get_all_devices()
    return [DeviceResponse.from_device(d) for d in devices]
```

### Service Layer

**Location:** `src/api/service/`

```python
class DeviceService:
    """Business logic for device operations."""

    def __init__(self, device_manager: AsyncDeviceManager):
        self.device_manager = device_manager
        self.logger = logging.getLogger(__name__)

    async def test_device_connectivity(self, device_id: str) -> bool:
        """Test if device is reachable."""
        device = await self.device_manager.get_device(device_id)
        if not device:
            raise ValueError(f"Device {device_id} not found")

        try:
            await device.read_value("STATUS")
            return True
        except Exception as e:
            self.logger.error(f"Connectivity test failed: {e}")
            return False
```

### Dependency Injection

**Location:** `src/api/dependency.py`

```python
from fastapi import Depends

# Singleton dependencies
_config_repository = None
_device_manager = None

def get_config_repository() -> ConfigRepository:
    """Get singleton config repository."""
    global _config_repository
    if not _config_repository:
        _config_repository = ConfigRepository()
    return _config_repository

async def get_device_manager(
    config_repo: ConfigRepository = Depends(get_config_repository)
) -> AsyncDeviceManager:
    """Get device manager instance."""
    global _device_manager
    if not _device_manager:
        devices_config = config_repo.get_modbus_devices()
        _device_manager = AsyncDeviceManager(devices_config)
        await _device_manager.initialize()
    return _device_manager
```

### WebSocket Endpoints

**Location:** `src/api/router/monitoring.py`

```python
from fastapi import WebSocket, WebSocketDisconnect

@router.websocket("/ws/device/{device_id}")
async def monitor_device(
    websocket: WebSocket,
    device_id: str,
    device_manager: AsyncDeviceManager = Depends(get_device_manager)
):
    """Real-time device monitoring via WebSocket."""
    await websocket.accept()

    try:
        while True:
            snapshot = await device_manager.get_device_snapshot(device_id)
            await websocket.send_json(snapshot)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from {device_id}")
```

### Error Handling

**Location:** `src/api/middleware/error_handler.py`

```python
from fastapi import Request, status
from fastapi.responses import JSONResponse

@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc)}
    )

@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception:")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"}
    )
```

---

## Device Integration

### Supported Device Types

**Current Drivers (13):**
- **Inverters:** TECO_VFD
- **Power Meters:** ADTEK_CPM10, DAE_PM210, GTA_A26A
- **Sensors:** SD_400, SD_500, SO (oxygen sensor)
- **I/O Modules:** JY_DAM0816D, ADAM_4117
- **Others:** Custom industrial devices

### Adding a New Device Driver

#### 1. Create Driver YAML (`res/driver/new_device.yml`)

```yaml
model: NEW_DEVICE
register_type: holding
type: sensor

register_map:
  TEMPERATURE:
    offset: 0
    format: i16
    readable: true
    writable: false
    scale: 0.1

  HUMIDITY:
    offset: 1
    format: u16
    readable: true
    writable: false
    scale: 0.1

  SENSOR_STATUS:
    offset: 10
    format: u16
    readable: true
    writable: false
    scale_from: status_table

tables:
  status_table:
    0: "OK"
    1: "WARNING"
    2: "ERROR"
```

#### 2. Add Device to modbus_device.yml

```yaml
devices:
  - model: NEW_DEVICE
    port: /dev/ttyUSB2
    slave_id: 5
    baudrate: 9600
    parity: N
    stopbits: 1
    bytesize: 8
```

#### 3. Add Constraints (Optional)

```yaml
# In device_instance_config.yml
constraints:
  NEW_DEVICE_5:
    TEMPERATURE:
      min: -40.0
      max: 85.0
```

#### 4. Add Alerts (Optional)

```yaml
# In alert_condition.yml
model_level:
  NEW_DEVICE:
    - alert_code: TEMP_HIGH
      severity: WARNING
      operator: gt
      threshold: 70.0
      target_register: TEMPERATURE
      message: "Temperature too high"
```

### Device Read/Write Examples

```python
# Read a single value
value = await device.read_value("TEMPERATURE")

# Write a value
await device.write_value("SETPOINT", 25.0)

# Batch read
values = await device.read_multiple(["TEMPERATURE", "HUMIDITY", "PRESSURE"])

# With constraints check
try:
    await device.write_value("FREQUENCY", 75.0)
except ValueError as e:
    # Constraint violation (max: 60.0)
    logger.error(f"Write failed: {e}")
```

### Multi-Word Registers (32-bit)

**Format:** `be32` (big-endian 32-bit)

```yaml
POWER_TOTAL:
  offset: 40063
  format: be32
  readable: true
  writable: false
  scale: 0.01
```

**Implementation:** Reads two consecutive 16-bit registers and combines them.

---

## Common Tasks

### Task 1: Add a New Alert Rule

**Steps:**
1. Edit `res/alert_condition.yml`
2. Add alert definition under `model_level` or `instance_level`
3. Restart application or reload config

**Example:**
```yaml
model_level:
  TECO_VFD:
    - alert_code: LOW_FREQUENCY
      severity: INFO
      operator: lt
      threshold: 10.0
      target_register: RW_HZ
      message: "VFD frequency below 10 Hz"
```

### Task 2: Add a New Control Rule

**Steps:**
1. Edit `res/control_condition.yml`
2. Add control definition with condition and action
3. Restart application

**Example:**
```yaml
- device_id: TECO_VFD_1
  priority: 2
  condition:
    type: THRESHOLD
    operator: gt
    threshold: 60.0
    target_register: TEMPERATURE
  action:
    action_type: SET_FREQUENCY
    target_register: RW_HZ
    value: 15.0
  policy_type: DISCRETE_SETPOINT
```

### Task 3: Add a New API Endpoint

**Steps:**
1. Create router function in `src/api/router/{module}.py`
2. Define request/response models in `src/api/model/{module}_model.py`
3. Add business logic in `src/api/service/{module}_service.py` (if complex)
4. Register router in `src/api/app.py`

**Example:**
```python
# router/devices.py
@router.get("/{device_id}/status")
async def get_device_status(
    device_id: str,
    device_manager: AsyncDeviceManager = Depends(get_device_manager)
):
    device = await device_manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    status = await device.read_value("STATUS")
    return {"device_id": device_id, "status": status}
```

### Task 4: Add a New Notification Channel

**Steps:**
1. Create notifier class in `src/util/notifier/new_notifier.py`
2. Implement `send()` method
3. Register in `src/util/factory/notifier_factory.py`
4. Add config to `res/notifier_config.yml`

**Example:**
```python
# src/util/notifier/discord_notifier.py
class DiscordNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.logger = logging.getLogger(__name__)

    async def send(self, alert: Alert) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "content": f"**{alert.severity}**: {alert.message}"
                }
                async with session.post(self.webhook_url, json=payload) as resp:
                    return resp.status == 204
        except Exception as e:
            self.logger.error(f"Discord notification failed: {e}")
            return False
```

### Task 5: Debug Device Communication

**Steps:**
1. Enable debug logging: `--log-level debug`
2. Check device connectivity:
   ```bash
   # Via API
   curl http://localhost:8000/api/devices/{device_id}/test
   ```
3. Verify Modbus configuration (baudrate, parity, slave_id)
4. Check serial port permissions: `ls -l /dev/ttyUSB*`
5. Use Modbus test tool: http://localhost:8000/static/index.html

### Task 6: Add Computed Fields

**Steps:**
1. Edit driver YAML in `res/driver/{model}.yml`
2. Add `computed_fields` section
3. Restart application

**Example:**
```yaml
computed_fields:
  - name: POWER_KW
    formula: "VOLTAGE * CURRENT / 1000"
    depends_on: [VOLTAGE, CURRENT]

  - name: EFFICIENCY
    formula: "OUTPUT_POWER / INPUT_POWER * 100"
    depends_on: [OUTPUT_POWER, INPUT_POWER]
```

---

## Important Notes

### Critical Patterns

#### 1. Async/Await Everywhere
- **All I/O operations must be async:** Modbus, file, HTTP, database
- Use `asyncio.gather()` for concurrent operations
- Never use blocking calls (use `aiofiles`, `aiohttp`, `aiosmtplib`)

#### 2. Device ID Policy
- **Format:** `{MODEL}_{SLAVE_ID}` (e.g., `TECO_VFD_1`)
- Defined in `system_config.yml`: `DEVICE_ID_POLICY: "MODEL_SLAVE"`
- Used throughout codebase for device identification

#### 3. Priority Protection (Control Executor)
- Lower priority number = higher priority
- Higher priority actions cannot be overridden by lower priority
- Reset priority on device state change or timeout

#### 4. Alert Deduplication
- AlertStateManager tracks state transitions (triggered → resolved)
- Prevents repeated notifications for same alert
- Implements fallback chain (primary → secondary → tertiary notifiers)

#### 5. Configuration Validation
- All YAML configs validated against Pydantic schemas
- Application fails fast on invalid config (startup time)
- Use `ConfigManager.validate_config()` before deployment

#### 6. Error Recovery
- Modbus operations have retry logic via `@async_retry` decorator
- Failed sender operations queued in outbox for retry
- Device polling continues even if individual devices fail

### Security Considerations

#### 1. Environment Variables
- **Never commit `.env` to git** (already in `.gitignore`)
- Store secrets in `.env`: SMTP credentials, API tokens, passwords
- Use `python-dotenv` to load: `load_dotenv()`

#### 2. API Security
- **CORS:** Currently set to allow all origins (restrict in production)
- **Authentication:** Not implemented (add JWT/OAuth if needed)
- **Rate Limiting:** Not implemented (consider adding for production)

#### 3. Modbus Security
- **Serial ports:** Ensure proper permissions (usually require `dialout` group)
- **Device access:** Physical security required (no network isolation for Modbus RTU)

### Performance Considerations

#### 1. Polling Interval
- Default: 1 second (`MONITOR_INTERVAL_SECONDS: 1.0`)
- Lower interval = higher CPU/serial bus utilization
- Adjust based on number of devices and registers

#### 2. Concurrent Device Reads
- Devices polled sequentially (not parallel) to avoid serial bus contention
- Consider increasing interval if polling takes > interval time

#### 3. WebSocket Connections
- Each WebSocket maintains active connection
- Broadcasts happen per connection (not optimized for many clients)
- Consider Redis pub/sub for high-concurrency scenarios

### Debugging Tips

#### 1. Enable Debug Logging
```bash
uvicorn api.app:app --log-level debug
```

#### 2. Check Device Manager State
```python
# Via Python REPL or debugger
device_manager.devices  # All initialized devices
device_manager.get_device("TECO_VFD_1")  # Specific device
```

#### 3. Monitor Pub/Sub Messages
```python
# Add a debug subscriber
class DebugSubscriber:
    async def handle_message(self, message):
        print(f"[DEBUG] {message}")
```

#### 4. Check Alert State
```python
# Alert state is persisted in logs/
# Check alert_state_manager for current states
```

### Common Pitfalls

#### 1. Forgetting PYTHONPATH
**Error:** `ModuleNotFoundError: No module named 'api'`
**Fix:** `export PYTHONPATH=./src:$PYTHONPATH`

#### 2. Serial Port Permissions
**Error:** `Permission denied: '/dev/ttyUSB0'`
**Fix:** `sudo usermod -a -G dialout $USER` (logout/login required)

#### 3. Invalid Device ID Format
**Error:** Device not found
**Fix:** Ensure format matches policy: `{MODEL}_{SLAVE_ID}`

#### 4. Constraint Violations
**Error:** `ValueError: Value exceeds max constraint`
**Fix:** Check `device_instance_config.yml` for constraints; adjust limits or value

#### 5. Missing Dependencies
**Error:** `ImportError: cannot import name 'X'`
**Fix:** `pip install -r requirements.txt`

### Version Control

#### Branch Naming
- Feature branches: `claude/{feature-name}-{session-id}`
- Bug fixes: `fix/{bug-description}`
- Refactoring: `refactor/{component-name}`

#### Commit Messages
Follow conventional commits:
```
feat: Add new Discord notifier
fix: Correct alert deduplication logic
refactor: Extract control evaluation logic
docs: Update CLAUDE.md with new patterns
test: Add tests for constraint policy
```

#### Git Push Strategy
- Always push to feature branch: `git push -u origin claude/{branch-name}`
- Create PR to main branch (not specified, ask user)
- Include tests with feature changes

---

## Environment Variables Reference

**Location:** `.env`

```bash
# Application
PYTHONPATH=./src:./test:$PYTHONPATH
PYTHONUNBUFFERED=1

# Email (SMTP)
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USERNAME=email@example.com
SMTP_PASSWORD=password
EMAIL_FROM=noreply@example.com
EMAIL_TEMPLATE_PATH=./template/alert_email.html

# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# SMS (if configured)
SMS_API_KEY=your_api_key
SMS_API_URL=https://api.sms-provider.com/send

# Webhooks (if needed)
WEBHOOK_SECRET=your_secret
```

---

## Additional Resources

### Documentation
- **AsyncAPI Spec:** `doc/asyncapi.yml` (WebSocket API)
- **Alert State Schema:** `doc/alert_state_schema.sql`
- **README:** `README.md`

### External References
- **FastAPI:** https://fastapi.tiangolo.com/
- **Pydantic:** https://docs.pydantic.dev/
- **pymodbus:** https://pymodbus.readthedocs.io/
- **pytest-asyncio:** https://pytest-asyncio.readthedocs.io/

### Related Tools
- **Modbus Poll:** For testing Modbus communication
- **Postman:** For testing REST API endpoints
- **wscat:** For testing WebSocket endpoints

---

## Quick Reference: File Locations

| Task | File Path |
|------|-----------|
| **Add new device** | `res/modbus_device.yml` |
| **Create device driver** | `res/driver/{model}.yml` |
| **Add alert rule** | `res/alert_condition.yml` |
| **Add control rule** | `res/control_condition.yml` |
| **Set device constraints** | `res/device_instance_config.yml` |
| **Configure notifiers** | `res/notifier_config.yml` |
| **System settings** | `res/system_config.yml` |
| **Add API endpoint** | `src/api/router/{module}.py` |
| **Add business logic** | `src/api/service/{module}_service.py` |
| **Add test** | `test/{module}/test_{component}.py` |
| **Configure environment** | `.env` |

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2025-11-23 | 1.0 | Initial CLAUDE.md creation based on commit 3e6c471 |

---

**For questions or clarifications, refer to:**
- Project README: `README.md`
- API Documentation: http://localhost:8000/docs
- Codebase exploration tools: Grep, Glob, Read tools in Claude Code
