"""
Unit tests for ConfigService
Tests the configuration management service layer
"""

import pytest

from api.model.enums import ResponseStatus
from api.model.modbus_config import ModbusBusCreateRequest, ModbusDeviceCreateRequest
from api.service.modbus_config_service import ModbusConfigService
from core.schema.config_metadata import ConfigSource
from core.schema.modbus_device_schema import ModbusBusConfig, ModbusDeviceConfig, ModbusDeviceFileConfig
from core.util.yaml_manager import YAMLManager


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create temporary config directory"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def yaml_manager(temp_config_dir):
    """Create YAMLManager instance"""
    return YAMLManager(temp_config_dir, backup_count=5)


@pytest.fixture
def config_service(yaml_manager):
    """Create ConfigService instance"""
    return ModbusConfigService(yaml_manager=yaml_manager)


@pytest.fixture
def initialized_config(yaml_manager):
    """Create initial config with one bus and device"""

    config = ModbusDeviceFileConfig(
        bus_dict={"rtu0": ModbusBusConfig(port="/dev/ttyUSB0", baudrate=9600, timeout=1.0)},
        device_list=[
            ModbusDeviceConfig(
                model="TECO_VFD", type="vfd", model_file="driver/teco_vfd.yml", slave_id=1, bus="rtu0", modes={}
            )
        ],
    )

    yaml_manager.update_config("modbus_device", config, config_source=ConfigSource.MANUAL, modified_by="test_fixture")

    return config


class TestConfigServiceMetadata:
    """Test metadata operations"""

    @pytest.mark.asyncio
    async def test_given_existing_config_when_getting_metadata_then_success_and_metadata_are_returned(
        self, config_service, initialized_config
    ):
        """Test getting metadata"""
        response = await config_service.get_metadata()

        assert response.status == ResponseStatus.SUCCESS
        assert response.metadata.generation >= 1
        assert response.metadata.source in ["manual", "edge", "cloud"]
        assert response.metadata.checksum is not None

    @pytest.mark.asyncio
    async def test_given_no_config_file_when_getting_metadata_then_not_found_is_raised(self, config_service):
        """Test metadata when file doesn't exist"""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await config_service.get_metadata()

        assert exc_info.value.status_code == 404


class TestConfigServiceConfig:
    """Test configuration operations"""

    @pytest.mark.asyncio
    async def test_given_existing_config_when_getting_config_then_full_config_is_returned(
        self, config_service, initialized_config
    ):
        """Test getting complete config"""
        response = await config_service.get_config()

        assert response.status == ResponseStatus.SUCCESS
        assert "rtu0" in response.buses
        assert len(response.devices) == 1
        assert response.devices[0].model == "TECO_VFD"
        assert response.devices[0].slave_id == 1

    @pytest.mark.asyncio
    async def test_given_existing_config_when_getting_config_then_metadata_is_included(
        self, config_service, initialized_config
    ):
        """Test that config includes metadata"""
        response = await config_service.get_config()

        assert response.metadata is not None
        assert response.metadata.generation >= 1


class TestConfigServiceBus:
    """Test bus operations"""

    @pytest.mark.asyncio
    async def test_given_new_bus_request_when_creating_or_updating_bus_then_success_and_generation_increases(
        self, config_service, initialized_config
    ):
        """Test creating a new bus"""
        bus_request = ModbusBusCreateRequest(port="/dev/ttyUSB1", baudrate=19200, timeout=1.5)

        response = await config_service.create_or_update_bus("rtu1", bus_request, "test_user")

        assert response.status == ResponseStatus.SUCCESS
        assert "created" in response.message.lower() or "updated" in response.message.lower()
        assert response.generation >= 2

    @pytest.mark.asyncio
    async def test_given_existing_bus_when_updating_bus_then_bus_settings_are_updated(
        self, config_service, initialized_config
    ):
        """Test updating an existing bus"""
        bus_request = ModbusBusCreateRequest(port="/dev/ttyUSB0", baudrate=19200, timeout=1.0)  # Changed

        response = await config_service.create_or_update_bus("rtu0", bus_request, "test_user")

        assert response.status == ResponseStatus.SUCCESS

        # Verify the change
        config = await config_service.get_config()
        assert config.buses["rtu0"].baudrate == 19200

    @pytest.mark.asyncio
    async def test_given_bus_is_in_use_when_deleting_bus_then_conflict_is_raised(
        self, config_service, initialized_config
    ):
        """Test deleting a bus that's in use"""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await config_service.delete_bus("rtu0", "test_user")

        assert exc_info.value.status_code == 409
        assert "in use" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_given_bus_is_unused_when_deleting_bus_then_success_is_returned(
        self, config_service, initialized_config
    ):
        """Test deleting an unused bus"""
        # First add a new bus
        bus_request = ModbusBusCreateRequest(port="/dev/ttyUSB1", baudrate=9600, timeout=1.0)
        await config_service.create_or_update_bus("rtu1", bus_request, "test_user")

        # Delete it
        response = await config_service.delete_bus("rtu1", "test_user")

        assert response.status == ResponseStatus.SUCCESS
        assert "deleted" in response.message.lower()


class TestConfigServiceDevice:
    """Test device operations"""

    @pytest.mark.asyncio
    async def test_given_new_device_request_when_creating_or_updating_device_then_device_is_created(
        self, config_service, initialized_config
    ):
        """Test creating a new device"""
        device_request = ModbusDeviceCreateRequest(
            model="ADAM_4117", type="analog_input", model_file="driver/adam_4117.yml", slave_id=2, bus="rtu0", modes={}
        )

        response = await config_service.create_or_update_device(device_request, "test_user")

        assert response.status == ResponseStatus.SUCCESS
        assert "created" in response.message.lower()

    @pytest.mark.asyncio
    async def test_given_invalid_bus_when_creating_device_then_bad_request_is_raised(
        self, config_service, initialized_config
    ):
        """Test creating device with invalid bus"""
        from fastapi import HTTPException

        device_request = ModbusDeviceCreateRequest(
            model="TEST_DEVICE", type="test", model_file="driver/test.yml", slave_id=99, bus="invalid_bus", modes={}
        )

        with pytest.raises(HTTPException) as exc_info:
            await config_service.create_or_update_device(device_request, "test_user")

        assert exc_info.value.status_code == 400
        assert "not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_given_existing_device_when_updating_device_then_device_is_updated(
        self, config_service, initialized_config
    ):
        """Test updating an existing device"""
        device_request = ModbusDeviceCreateRequest(
            model="TECO_VFD",
            type="vfd",
            model_file="driver/teco_vfd_v2.yml",  # Changed
            slave_id=1,
            bus="rtu0",
            modes={"special_mode": True},
        )

        response = await config_service.create_or_update_device(device_request, "test_user")

        assert response.status == ResponseStatus.SUCCESS
        assert "updated" in response.message.lower()

    @pytest.mark.asyncio
    async def test_given_existing_device_when_deleting_device_then_device_is_removed(
        self, config_service, initialized_config
    ):
        """Test deleting a device"""
        response = await config_service.delete_device("TECO_VFD", 1, "test_user")

        assert response.status == ResponseStatus.SUCCESS
        assert "deleted" in response.message.lower()

        # Verify deletion
        config = await config_service.get_config()
        assert len(config.devices) == 0

    @pytest.mark.asyncio
    async def test_given_nonexistent_device_when_deleting_device_then_not_found_is_raised(
        self, config_service, initialized_config
    ):
        """Test deleting a device that doesn't exist"""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await config_service.delete_device("NONEXISTENT", 999, "test_user")

        assert exc_info.value.status_code == 404


class TestConfigServiceBackup:
    """Test backup operations"""

    @pytest.mark.asyncio
    async def test_given_no_backups_when_listing_backups_then_empty_list_is_returned(
        self, config_service, initialized_config
    ):
        """Test listing backups when none exist"""
        response = await config_service.list_backups()

        assert response.status == ResponseStatus.SUCCESS
        assert response.total == 0
        assert len(response.backups) == 0

    @pytest.mark.asyncio
    async def test_given_updates_occur_when_listing_backups_then_backups_are_returned(
        self, config_service, initialized_config
    ):
        """Test listing backups after making updates"""
        # Make a change to trigger backup
        bus_request = ModbusBusCreateRequest(port="/dev/ttyUSB1", baudrate=9600, timeout=1.0)
        await config_service.create_or_update_bus("rtu1", bus_request, "test_user")

        response = await config_service.list_backups()

        assert response.status == ResponseStatus.SUCCESS
        assert response.total >= 1
        assert len(response.backups) >= 1

        # Check backup info
        backup = response.backups[0]
        assert backup.filename.endswith(".yml")
        assert backup.generation is not None
        assert backup.size_bytes > 0

    @pytest.mark.asyncio
    async def test_given_backup_filename_when_restoring_backup_then_restore_succeeds(
        self, config_service, initialized_config, yaml_manager
    ):
        """Test restoring from backup"""
        # Make changes
        await config_service.create_or_update_bus(
            "rtu1", ModbusBusCreateRequest(port="/dev/ttyUSB1", baudrate=9600, timeout=1.0), "test_user"
        )

        # Get backups
        backups_response = await config_service.list_backups()
        assert backups_response.total > 0

        # Restore
        backup_filename = backups_response.backups[0].filename
        response = await config_service.restore_backup(backup_filename, "test_user")

        assert response.status == ResponseStatus.SUCCESS
        assert "restored" in response.message.lower()


class TestConfigServiceVersioning:
    """Test version management"""

    @pytest.mark.asyncio
    async def test_given_config_updated_when_getting_metadata_then_generation_increments_by_one(
        self, config_service, initialized_config
    ):
        """Test that generation increments on each update"""
        initial_response = await config_service.get_metadata()
        initial_gen = initial_response.metadata.generation

        # Make a change
        await config_service.create_or_update_bus(
            "rtu1", ModbusBusCreateRequest(port="/dev/ttyUSB1", baudrate=9600, timeout=1.0), "test_user"
        )

        updated_response = await config_service.get_metadata()

        assert updated_response.metadata.generation == initial_gen + 1

    @pytest.mark.asyncio
    async def test_given_config_updated_when_getting_metadata_then_checksum_changes(
        self, config_service, initialized_config
    ):
        """Test that checksum changes on updates"""
        initial_response = await config_service.get_metadata()
        initial_checksum = initial_response.metadata.checksum

        # Make a change
        await config_service.create_or_update_bus(
            "rtu1", ModbusBusCreateRequest(port="/dev/ttyUSB1", baudrate=9600, timeout=1.0), "test_user"
        )

        updated_response = await config_service.get_metadata()

        assert updated_response.metadata.checksum != initial_checksum

    @pytest.mark.asyncio
    async def test_given_user_modifies_config_when_updating_then_last_modified_by_is_tracked(
        self, config_service, initialized_config
    ):
        """Test that user is tracked in metadata"""
        response = await config_service.create_or_update_bus(
            "rtu1", ModbusBusCreateRequest(port="/dev/ttyUSB1", baudrate=9600, timeout=1.0), "jeremy@example.com"
        )

        metadata_response = await config_service.get_metadata()

        assert metadata_response.metadata.last_modified_by == "jeremy@example.com"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
