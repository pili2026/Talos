"""
Device Service Layer Tests

Tests for DeviceService business logic, focusing on:
- Device list retrieval with/without status check
- Single device retrieval with/without status check
- Connectivity check behavior
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pymodbus.exceptions import ModbusException

from api.model.enums import DeviceConnectionStatus
from api.model.responses import DeviceInfo
from api.service.device_service import DeviceService
from exception import DeviceConfigError, DeviceConnectionError, DeviceNotFoundError, ParameterError


@pytest.fixture
def mock_device_manager():
    """Mock AsyncDeviceManager"""
    manager = AsyncMock()
    manager.test_device_connection = AsyncMock(return_value=True)
    return manager


@pytest.fixture
def mock_config_repo():
    """Mock ConfigRepository with sample device configurations"""
    repo = MagicMock()

    # Sample device configurations
    sample_configs = {
        "TECO_VFD_1": {
            "device_id": "TECO_VFD_1",
            "model": "TECO_VFD",
            "slave_id": "1",
            "available_parameters": ["Hz", "KW", "RPM"],
        },
        "SD400_3": {
            "device_id": "SD400_3",
            "model": "SD400",
            "slave_id": "3",
            "available_parameters": ["AIn01", "AIn02"],
        },
        "ADAM_4117_12": {
            "device_id": "ADAM_4117_12",
            "model": "ADAM-4117",
            "slave_id": "12",
            "available_parameters": ["AIn01", "AIn02", "AIn03"],
        },
    }

    repo.get_all_device_configs.return_value = sample_configs
    repo.get_device_config.side_effect = lambda device_id: sample_configs.get(device_id)

    return repo


@pytest.fixture
def device_service(mock_device_manager, mock_config_repo):
    """Create DeviceService instance with mocked dependencies"""
    return DeviceService(mock_device_manager, mock_config_repo)


class TestGetAllDevices:
    """Test suite for get_all_devices method"""

    @pytest.mark.asyncio
    async def test_when_include_status_false_then_should_not_check_connectivity(
        self, device_service, mock_device_manager
    ):
        """
        GIVEN include_status=False
        WHEN get_all_devices is called
        THEN should NOT check device connectivity
        AND all devices should have UNKNOWN status
        """
        # Act
        devices = await device_service.get_all_devices(include_status=False)

        # Assert
        assert len(devices) == 3
        assert all(isinstance(d, DeviceInfo) for d in devices)
        assert all(d.connection_status == DeviceConnectionStatus.UNKNOWN.value for d in devices)

        # Critical: should NOT call test_device_connection
        mock_device_manager.test_device_connection.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_include_status_true_then_should_check_all_devices(self, device_service, mock_device_manager):
        """
        GIVEN include_status=True
        WHEN get_all_devices is called
        THEN should check connectivity for ALL devices
        AND all devices should have ONLINE status (mocked)
        """
        # Act
        devices = await device_service.get_all_devices(include_status=True)

        # Assert
        assert len(devices) == 3
        assert mock_device_manager.test_device_connection.call_count == 3
        assert all(d.connection_status == DeviceConnectionStatus.ONLINE.value for d in devices)

        # Verify it checked all device IDs
        called_device_ids = [call.args[0] for call in mock_device_manager.test_device_connection.call_args_list]
        assert set(called_device_ids) == {"TECO_VFD_1", "SD400_3", "ADAM_4117_12"}

    @pytest.mark.asyncio
    async def test_when_default_parameter_then_should_not_check_connectivity(self, device_service, mock_device_manager):
        """
        GIVEN no include_status parameter (default)
        WHEN get_all_devices is called
        THEN should NOT check connectivity (default behavior)
        """
        # Act
        devices = await device_service.get_all_devices()

        # Assert
        mock_device_manager.test_device_connection.assert_not_called()
        assert all(d.connection_status == DeviceConnectionStatus.UNKNOWN.value for d in devices)

    @pytest.mark.asyncio
    async def test_when_device_offline_then_should_return_offline_status(self, device_service, mock_device_manager):
        """
        GIVEN a device is offline
        WHEN get_all_devices with include_status=True
        THEN should return OFFLINE status for that device
        """

        # Arrange: Make specific device offline
        async def mock_connectivity(device_id):
            return device_id != "SD400_3"  # SD400_3 is offline

        mock_device_manager.test_device_connection.side_effect = mock_connectivity

        # Act
        devices = await device_service.get_all_devices(include_status=True)

        # Assert
        sd400_device = next(d for d in devices if d.device_id == "SD400_3")
        assert sd400_device.connection_status == DeviceConnectionStatus.OFFLINE.value

        teco_device = next(d for d in devices if d.device_id == "TECO_VFD_1")
        assert teco_device.connection_status == DeviceConnectionStatus.ONLINE.value

    @pytest.mark.asyncio
    async def test_when_connectivity_check_raises_parameter_error_then_skip_device(
        self, device_service, mock_device_manager, mock_config_repo
    ):
        """
        GIVEN connectivity check raises ParameterError for one device
        WHEN get_all_devices with include_status=True
        THEN should skip that device and return others
        """

        # Arrange: ParameterError will propagate and cause device to be skipped
        async def mock_test_connection(device_id):
            if device_id == "SD400_3":
                raise ParameterError(f"Invalid device_id format: {device_id}")
            return True

        mock_device_manager.test_device_connection.side_effect = mock_test_connection

        # Act
        devices = await device_service.get_all_devices(include_status=True)

        # Assert: SD400_3 should be skipped due to ParameterError
        assert len(devices) == 2
        device_ids = [d.device_id for d in devices]
        assert "TECO_VFD_1" in device_ids
        assert "ADAM_4117_12" in device_ids
        assert "SD400_3" not in device_ids

    @pytest.mark.asyncio
    async def test_when_connectivity_check_fails_then_return_with_error_status(
        self, device_service, mock_device_manager, mock_config_repo
    ):
        """
        GIVEN connectivity check raises exception for one device
        WHEN get_all_devices with include_status=True
        THEN should return all devices with ERROR status for failed device
        """
        # Arrange
        mock_config_repo.get_all_device_configs.return_value = {
            "TECO_VFD_1": {
                "device_id": "TECO_VFD_1",
                "model": "TECO_VFD",
                "slave_id": "1",
                "available_parameters": ["Hz"],
            },
            "SD400_3": {
                "device_id": "SD400_3",
                "model": "SD400",
                "slave_id": "3",
                "available_parameters": ["AIn01"],
            },
            "ADAM_4117_12": {
                "device_id": "ADAM_4117_12",
                "model": "ADAM-4117",
                "slave_id": "12",
                "available_parameters": ["AIn01"],
            },
        }

        async def mock_test_connection(device_id):
            if device_id == "SD400_3":
                raise Exception("Unexpected network error")
            return True

        mock_device_manager.test_device_connection.side_effect = mock_test_connection

        # Act
        devices = await device_service.get_all_devices(include_status=True)

        # Assert: All devices should be returned
        assert len(devices) == 3

        # SD400_3 should have ERROR status
        sd400_device = next(d for d in devices if d.device_id == "SD400_3")
        assert sd400_device.connection_status == DeviceConnectionStatus.ERROR.value

        # Other devices should be ONLINE
        teco_device = next(d for d in devices if d.device_id == "TECO_VFD_1")
        assert teco_device.connection_status == DeviceConnectionStatus.ONLINE.value

        adam_device = next(d for d in devices if d.device_id == "ADAM_4117_12")
        assert adam_device.connection_status == DeviceConnectionStatus.ONLINE.value

    @pytest.mark.asyncio
    async def test_when_no_devices_configured_then_should_return_empty_list(self, device_service, mock_config_repo):
        """
        GIVEN no devices are configured
        WHEN get_all_devices is called
        THEN should return empty list
        """
        # Arrange
        mock_config_repo.get_all_device_configs.return_value = {}

        # Act
        devices = await device_service.get_all_devices(include_status=False)

        # Assert
        assert devices == []

    @pytest.mark.asyncio
    async def test_when_called_then_should_return_correct_device_info(self, device_service):
        """
        GIVEN valid device configurations
        WHEN get_all_devices is called
        THEN should return DeviceInfo with correct fields
        """
        # Act
        devices = await device_service.get_all_devices(include_status=False)

        # Assert
        teco_device = next(d for d in devices if d.device_id == "TECO_VFD_1")
        assert teco_device.device_id == "TECO_VFD_1"
        assert teco_device.model == "TECO_VFD"
        assert teco_device.slave_id == "1"
        assert set(teco_device.available_parameters) == {"Hz", "KW", "RPM"}


class TestGetDeviceById:
    """Test suite for get_device_by_id method"""

    @pytest.mark.asyncio
    async def test_when_include_status_true_then_should_check_connectivity(self, device_service, mock_device_manager):
        """
        GIVEN include_status=True
        WHEN get_device_by_id is called
        THEN should check device connectivity
        AND return ONLINE status
        """
        # Act
        device = await device_service.get_device_by_id("TECO_VFD_1", include_status=True)

        # Assert
        assert device is not None
        assert device.device_id == "TECO_VFD_1"
        assert device.connection_status == DeviceConnectionStatus.ONLINE.value
        mock_device_manager.test_device_connection.assert_called_once_with("TECO_VFD_1")

    @pytest.mark.asyncio
    async def test_when_include_status_false_then_should_not_check_connectivity(
        self, device_service, mock_device_manager
    ):
        """
        GIVEN include_status=False
        WHEN get_device_by_id is called
        THEN should NOT check device connectivity
        AND return UNKNOWN status
        """
        # Act
        device = await device_service.get_device_by_id("TECO_VFD_1", include_status=False)

        # Assert
        assert device is not None
        assert device.connection_status == DeviceConnectionStatus.UNKNOWN.value
        mock_device_manager.test_device_connection.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_default_parameter_then_should_check_connectivity(self, device_service, mock_device_manager):
        """
        GIVEN no include_status parameter (default=True for single device)
        WHEN get_device_by_id is called
        THEN should check connectivity
        """
        # Act
        device = await device_service.get_device_by_id("SD400_3")

        # Assert
        mock_device_manager.test_device_connection.assert_called_once_with("SD400_3")

    @pytest.mark.asyncio
    async def test_when_device_not_found_then_should_return_none(self, device_service, mock_device_manager):
        """
        GIVEN device does not exist
        WHEN get_device_by_id is called
        THEN should return None
        AND should NOT attempt connectivity check
        """
        # Act
        device = await device_service.get_device_by_id("NOT_EXIST", include_status=True)

        # Assert
        assert device is None
        mock_device_manager.test_device_connection.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_device_offline_then_should_return_offline_status(self, device_service, mock_device_manager):
        """
        GIVEN device is offline
        WHEN get_device_by_id with include_status=True
        THEN should return OFFLINE status
        """
        # Arrange
        mock_device_manager.test_device_connection.return_value = False

        # Act
        device = await device_service.get_device_by_id("SD400_3", include_status=True)

        # Assert
        assert device.connection_status == DeviceConnectionStatus.OFFLINE.value

    @pytest.mark.asyncio
    async def test_when_connectivity_check_returns_online_then_status_is_online(
        self, device_service, mock_device_manager
    ):
        """
        GIVEN device is online
        WHEN get_device_by_id with include_status=True
        THEN should return device with ONLINE status
        """
        # Arrange
        mock_device_manager.test_device_connection.return_value = True

        # Act
        device = await device_service.get_device_by_id("ADAM_4117_12", include_status=True)

        # Assert
        assert device.connection_status == DeviceConnectionStatus.ONLINE.value

    @pytest.mark.asyncio
    async def test_when_connectivity_check_raises_modbus_error_then_status_is_error(
        self, device_service, mock_device_manager
    ):
        """
        GIVEN connectivity check raises ModbusException
        WHEN get_device_by_id with include_status=True
        THEN should return device with ERROR status
        """
        # Arrange
        mock_device_manager.test_device_connection.side_effect = ModbusException("Timeout")

        # Act
        device = await device_service.get_device_by_id("ADAM_4117_12", include_status=True)

        # Assert
        assert device.connection_status == DeviceConnectionStatus.ERROR.value

    @pytest.mark.asyncio
    async def test_when_connectivity_check_raises_device_not_found_then_status_is_not_found(
        self, device_service, mock_device_manager
    ):
        """
        GIVEN device not found in device manager
        WHEN get_device_by_id with include_status=True
        THEN should return device with NOT_FOUND status
        """
        # Arrange
        mock_device_manager.test_device_connection.side_effect = DeviceNotFoundError(
            "Device not found", device_id="ADAM_4117_12"
        )

        # Act
        device = await device_service.get_device_by_id("ADAM_4117_12", include_status=True)

        # Assert
        assert device.connection_status == DeviceConnectionStatus.NOT_FOUND.value


class TestCheckDeviceConnectivity:
    """Test suite for check_device_connectivity method"""

    @pytest.mark.asyncio
    async def test_when_device_online_then_should_return_online_status(self, device_service, mock_device_manager):
        """
        GIVEN device responds successfully
        WHEN check_device_connectivity is called
        THEN should return ONLINE status
        """
        # Arrange
        mock_device_manager.test_device_connection.return_value = True

        # Act
        status = await device_service.check_device_connectivity("TECO_VFD_1")

        # Assert
        assert status == DeviceConnectionStatus.ONLINE

    @pytest.mark.asyncio
    async def test_when_device_offline_then_should_return_offline_status(self, device_service, mock_device_manager):
        """
        GIVEN device does not respond
        WHEN check_device_connectivity is called
        THEN should return OFFLINE status
        """
        # Arrange
        mock_device_manager.test_device_connection.return_value = False

        # Act
        status = await device_service.check_device_connectivity("SD400_3")

        # Assert
        assert status == DeviceConnectionStatus.OFFLINE

    @pytest.mark.asyncio
    async def test_when_modbus_exception_raised_then_return_error_status(self, device_service, mock_device_manager):
        """
        GIVEN test_device_connection raises ModbusException
        WHEN check_device_connectivity is called
        THEN should return ERROR status
        """
        # Arrange: Known Modbus communication error
        mock_device_manager.test_device_connection.side_effect = ModbusException("Connection timeout")

        # Act
        status = await device_service.check_device_connectivity("ADAM_4117_12")

        # Assert
        assert status == DeviceConnectionStatus.ERROR

    @pytest.mark.asyncio
    async def test_when_device_connection_error_raised_then_return_error_status(
        self, device_service, mock_device_manager
    ):
        """
        GIVEN test_device_connection raises DeviceConnectionError
        WHEN check_device_connectivity is called
        THEN should return ERROR status
        """
        # Arrange
        mock_device_manager.test_device_connection.side_effect = DeviceConnectionError(
            "Modbus communication failed", device_id="ADAM_4117_12"
        )

        # Act
        status = await device_service.check_device_connectivity("ADAM_4117_12")

        # Assert
        assert status == DeviceConnectionStatus.ERROR

    @pytest.mark.asyncio
    async def test_when_device_not_found_then_return_not_found_status(self, device_service, mock_device_manager):
        """
        GIVEN device not found in device manager
        WHEN check_device_connectivity is called
        THEN should return NOT_FOUND status
        """
        # Arrange
        mock_device_manager.test_device_connection.side_effect = DeviceNotFoundError(
            "Device not found", device_id="ADAM_4117_12"
        )

        # Act
        status = await device_service.check_device_connectivity("ADAM_4117_12")

        # Assert
        assert status == DeviceConnectionStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_when_device_misconfigured_then_return_misconfigured_status(
        self, device_service, mock_device_manager
    ):
        """
        GIVEN device has configuration error
        WHEN check_device_connectivity is called
        THEN should return MISCONFIGURED status
        """
        # Arrange
        mock_device_manager.test_device_connection.side_effect = DeviceConfigError(
            "No register map configured", device_id="ADAM_4117_12"
        )

        # Act
        status = await device_service.check_device_connectivity("ADAM_4117_12")

        # Assert
        assert status == DeviceConnectionStatus.MISCONFIGURED

    @pytest.mark.asyncio
    async def test_when_parameter_error_then_should_raise(self, device_service, mock_device_manager):
        """
        GIVEN invalid device_id format
        WHEN check_device_connectivity is called
        THEN should raise ParameterError
        """
        # Arrange: Parameter error should propagate
        mock_device_manager.test_device_connection.side_effect = ParameterError("Invalid device_id format")

        # Act & Assert
        with pytest.raises(ParameterError):
            await device_service.check_device_connectivity("ADAM_4117_12")

    @pytest.mark.asyncio
    async def test_when_unexpected_exception_then_should_return_error_status(self, device_service, mock_device_manager):
        """
        GIVEN test_device_connection raises unexpected exception
        WHEN check_device_connectivity is called
        THEN should return ERROR status
        """
        # Arrange: Unexpected error also returns ERROR
        mock_device_manager.test_device_connection.side_effect = Exception("Unexpected error")

        # Act
        status = await device_service.check_device_connectivity("ADAM_4117_12")

        # Assert
        assert status == DeviceConnectionStatus.ERROR


class TestGetAllDeviceModels:
    """Test suite for get_all_device_models method"""

    def test_when_models_exist_then_should_return_model_list(self, device_service, mock_config_repo):
        """
        GIVEN device models are configured
        WHEN get_all_device_models is called
        THEN should return list of model information
        """
        # Arrange
        model_definitions = {
            "TECO_VFD": {
                "description": "TECO Variable Frequency Drive",
                "manufacturer": "TECO",
                "register_map": {
                    "Hz": {"readable": True, "writable": True},
                    "KW": {"readable": True, "writable": False},
                },
            },
            "SD400": {
                "description": "SD400 Analog Input Module",
                "manufacturer": "Unknown",
                "register_map": {"AIn01": {"readable": True, "writable": False}},
            },
        }
        mock_config_repo.get_all_models.return_value = ["TECO_VFD", "SD400"]
        mock_config_repo.get_model_definition.side_effect = lambda model: model_definitions.get(model)

        # Act
        models = device_service.get_all_device_models()

        # Assert
        assert len(models) == 2

        teco_model = next(m for m in models if m["model"] == "TECO_VFD")
        assert teco_model["description"] == "TECO Variable Frequency Drive"
        assert teco_model["manufacturer"] == "TECO"
        assert set(teco_model["available_parameters"]) == {"Hz", "KW"}
        assert teco_model["parameter_count"] == 2
        assert teco_model["supports_read"] is True
        assert teco_model["supports_write"] is True
