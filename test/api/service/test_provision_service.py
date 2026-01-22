import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from api.model.provision import ProvisionCurrentConfig
from api.model.provision_config import ProvisionConfig
from api.service.provision_service import ProvisionService

# ===== Test Fixtures =====


@pytest.fixture
def mock_config():
    """Provide test config with sudo disabled"""
    return ProvisionConfig(use_sudo=False, timeout_sec=5.0)


@pytest.fixture
def service_no_sudo(mock_config):
    """Provide ProvisionService with sudo disabled for testing"""
    return ProvisionService(config=mock_config)


# ===== Test Classes =====


class TestProvisionServiceInit:
    """Test ProvisionService initialization"""

    def test_when_no_args_then_loads_from_env(self):
        """Test initialization with default config"""
        service = ProvisionService()
        # Note: This reads from env, so use_sudo may vary
        assert service._config.timeout_sec == 10.0
        assert service._lock is not None

    def test_when_custom_config_then_uses_it(self):
        """Test initialization with custom config"""
        config = ProvisionConfig(use_sudo=False, timeout_sec=5.0)
        service = ProvisionService(config=config)
        assert service._config.use_sudo is False
        assert service._config.timeout_sec == 5.0

    def test_when_no_system_config_then_warns(self, caplog, mock_config):
        """Test warning when system_config not provided"""
        service = ProvisionService(config=mock_config, system_config=None)
        assert "fallback port will default to 8600" in caplog.text


class TestGetCurrentConfig:
    """Test get_current_config method"""

    @patch.object(ProvisionService, "_read_hostname", return_value="talos000001")
    @patch.object(ProvisionService, "_read_reverse_port", return_value=(8621, "service"))
    def test_when_read_success_then_returns_current_config(self, mock_port, mock_hostname, mock_config):
        """Test successful config read"""
        service = ProvisionService(config=mock_config)
        result = service.get_current_config()

        assert isinstance(result, ProvisionCurrentConfig)
        assert result.hostname == "talos000001"
        assert result.reverse_port == 8621
        assert result.port_source == "service"


class TestSetConfig:
    """Test set_config method"""

    @pytest.mark.asyncio
    async def test_when_no_changes_then_returns_no_changes_message(self, service_no_sudo):
        """Test when config already matches"""
        with patch.object(service_no_sudo, "_read_hostname", return_value="talos000001"):
            with patch.object(service_no_sudo, "_read_reverse_port", return_value=(8621, "service")):
                result = await service_no_sudo.set_config("talos000001", 8621)

        assert result.success is True
        assert result.requires_reboot is False
        assert result.changes == []
        assert "already matches" in result.message

    @pytest.mark.asyncio
    async def test_when_hostname_changes_then_updates_and_requires_reboot(self, service_no_sudo):
        """Test hostname update requires reboot"""
        with patch.object(service_no_sudo, "_read_hostname", return_value="talos000001"):
            with patch.object(service_no_sudo, "_read_reverse_port", return_value=(8621, "service")):
                with patch.object(service_no_sudo, "_set_hostname", new_callable=AsyncMock):
                    with patch.object(service_no_sudo, "_update_hosts_file", new_callable=AsyncMock):
                        result = await service_no_sudo.set_config("talos000002", 8621)

        assert result.success is True
        assert result.requires_reboot is True
        assert "hostname" in result.changes
        assert "reverse_port" not in result.changes

    @pytest.mark.asyncio
    async def test_when_port_changes_then_updates_and_restarts_service(self, service_no_sudo):
        """Test port update restarts service"""
        with patch.object(service_no_sudo, "_read_hostname", return_value="talos000001"):
            with patch.object(service_no_sudo, "_read_reverse_port", return_value=(8621, "service")):
                with patch.object(service_no_sudo, "_update_service_port", new_callable=AsyncMock):
                    with patch.object(service_no_sudo, "_reload_and_restart_service", new_callable=AsyncMock):
                        result = await service_no_sudo.set_config("talos000001", 8622)

        assert result.success is True
        assert result.requires_reboot is False
        assert "reverse_port" in result.changes
        assert "hostname" not in result.changes

    @pytest.mark.asyncio
    async def test_when_both_change_then_updates_both(self, service_no_sudo):
        """Test updating both hostname and port"""
        with patch.object(service_no_sudo, "_read_hostname", return_value="talos000001"):
            with patch.object(service_no_sudo, "_read_reverse_port", return_value=(8621, "service")):
                with patch.object(service_no_sudo, "_set_hostname", new_callable=AsyncMock):
                    with patch.object(service_no_sudo, "_update_hosts_file", new_callable=AsyncMock):
                        with patch.object(service_no_sudo, "_update_service_port", new_callable=AsyncMock):
                            with patch.object(service_no_sudo, "_reload_and_restart_service", new_callable=AsyncMock):
                                result = await service_no_sudo.set_config("talos000002", 8622)

        assert result.success is True
        assert result.requires_reboot is True
        assert "hostname" in result.changes
        assert "reverse_port" in result.changes


class TestValidation:
    """Test input validation"""

    @pytest.mark.asyncio
    async def test_when_hostname_empty_then_raises_value_error(self, service_no_sudo):
        """Test empty hostname validation"""
        with pytest.raises(ValueError, match="cannot be empty"):
            await service_no_sudo.set_config("", 8621)

    @pytest.mark.asyncio
    async def test_when_hostname_too_short_then_raises_value_error(self, service_no_sudo):
        """Test hostname length validation (too short)"""
        with pytest.raises(ValueError, match="must be exactly 11 characters"):
            await service_no_sudo.set_config("short", 8621)

    @pytest.mark.asyncio
    async def test_when_hostname_too_long_then_raises_value_error(self, service_no_sudo):
        """Test hostname length validation (too long)"""
        with pytest.raises(ValueError, match="must be exactly 11 characters"):
            await service_no_sudo.set_config("toolongnameXX", 8621)  # 13 characters

    @pytest.mark.asyncio
    async def test_when_hostname_has_hyphen_then_raises_value_error(self, service_no_sudo):
        """Test hostname character validation (hyphen)"""
        with pytest.raises(ValueError, match="can only contain letters and numbers"):
            await service_no_sudo.set_config("talos-00001", 8621)

    @pytest.mark.asyncio
    async def test_when_hostname_has_underscore_then_raises_value_error(self, service_no_sudo):
        """Test hostname character validation (underscore)"""
        with pytest.raises(ValueError, match="can only contain letters and numbers"):
            await service_no_sudo.set_config("talos_00001", 8621)

    @pytest.mark.asyncio
    async def test_when_hostname_has_space_then_raises_value_error(self, service_no_sudo):
        """Test hostname character validation (space)"""
        with pytest.raises(ValueError, match="can only contain letters and numbers"):
            await service_no_sudo.set_config("talos 00001", 8621)

    @pytest.mark.asyncio
    async def test_when_port_too_low_then_raises_value_error(self, service_no_sudo):
        """Test port range validation (too low)"""
        with pytest.raises(ValueError, match="must be between 1024 and 65535"):
            await service_no_sudo.set_config("talos000001", 1023)

    @pytest.mark.asyncio
    async def test_when_port_too_high_then_raises_value_error(self, service_no_sudo):
        """Test port range validation (too high)"""
        with pytest.raises(ValueError, match="must be between 1024 and 65535"):
            await service_no_sudo.set_config("talos000001", 65536)

    @pytest.mark.asyncio
    async def test_when_port_at_minimum_then_accepts(self, service_no_sudo):
        """Test port minimum boundary (1024)"""
        with patch.object(service_no_sudo, "_read_hostname", return_value="talos000001"):
            with patch.object(service_no_sudo, "_read_reverse_port", return_value=(8621, "service")):
                with patch.object(service_no_sudo, "_update_service_port", new_callable=AsyncMock):
                    with patch.object(service_no_sudo, "_reload_and_restart_service", new_callable=AsyncMock):
                        result = await service_no_sudo.set_config("talos000001", 1024)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_when_port_at_maximum_then_accepts(self, service_no_sudo):
        """Test port maximum boundary (65535)"""
        with patch.object(service_no_sudo, "_read_hostname", return_value="talos000001"):
            with patch.object(service_no_sudo, "_read_reverse_port", return_value=(8621, "service")):
                with patch.object(service_no_sudo, "_update_service_port", new_callable=AsyncMock):
                    with patch.object(service_no_sudo, "_reload_and_restart_service", new_callable=AsyncMock):
                        result = await service_no_sudo.set_config("talos000001", 65535)

        assert result.success is True


class TestConcurrencyControl:
    """Test concurrent access protection"""

    @pytest.mark.asyncio
    async def test_when_concurrent_calls_then_sequential_execution(self, service_no_sudo):
        """Test that concurrent calls are serialized by lock"""
        execution_order = []

        async def mock_set_hostname(hostname):
            execution_order.append(f"start_{hostname}")
            await asyncio.sleep(0.05)  # Simulate slow operation
            execution_order.append(f"end_{hostname}")

        with patch.object(service_no_sudo, "_read_hostname", return_value="talos000000"):
            with patch.object(service_no_sudo, "_read_reverse_port", return_value=(8620, "service")):
                with patch.object(service_no_sudo, "_set_hostname", side_effect=mock_set_hostname):
                    with patch.object(service_no_sudo, "_update_hosts_file", new_callable=AsyncMock):
                        # Launch two concurrent updates
                        task1 = asyncio.create_task(service_no_sudo.set_config("talos000001", 8620))
                        task2 = asyncio.create_task(service_no_sudo.set_config("talos000002", 8620))

                        await asyncio.gather(task1, task2)

        # Verify sequential execution (one completes before next starts)
        assert execution_order == [
            "start_talos000001",
            "end_talos000001",
            "start_talos000002",
            "end_talos000002",
        ]


class TestReadReversePort:
    """Test _read_reverse_port method"""

    def test_when_service_file_exists_then_parses_port(self, tmp_path, mock_config):
        """Test parsing port from service file"""
        service_file = tmp_path / "connectserver.service"
        service_file.write_text("[Service]\n" "ExecStart=/usr/bin/python3 /path/to/connect_server.pyc 8621 debug\n")

        service = ProvisionService(config=mock_config)
        service.SERVICE_FILE_PATH = service_file

        port, source = service._read_reverse_port()
        assert port == 8621
        assert source == "service"

    def test_when_service_file_has_quotes_then_parses_port(self, tmp_path, mock_config):
        """Test parsing port with quotes"""
        service_file = tmp_path / "connectserver.service"
        service_file.write_text("[Service]\n" 'ExecStart=/usr/bin/python3 /path/to/connect_server.pyc "8621" debug\n')

        service = ProvisionService(config=mock_config)
        service.SERVICE_FILE_PATH = service_file

        port, source = service._read_reverse_port()
        assert port == 8621
        assert source == "service"

    def test_when_service_file_missing_then_uses_fallback(self, mock_config):
        """Test fallback to system_config when service file missing"""
        service = ProvisionService(config=mock_config)
        service.SERVICE_FILE_PATH = Path("/nonexistent/path")

        port, source = service._read_reverse_port()
        assert port == 8600  # Default fallback
        assert source == "config"


class TestUpdateHostsFile:
    """Test _update_hosts_file method"""

    @pytest.mark.asyncio
    async def test_when_127_0_1_1_exists_then_updates_line(self, tmp_path, service_no_sudo):
        """Test updating existing 127.0.1.1 line"""
        hosts_file = tmp_path / "hosts"
        hosts_file.write_text("127.0.0.1    localhost\n127.0.1.1    oldname\n")

        service_no_sudo.HOSTS_FILE_PATH = hosts_file

        with patch.object(service_no_sudo, "_run_command", new_callable=AsyncMock) as mock_run:
            with patch.object(service_no_sudo, "_write_file_with_sudo", new_callable=AsyncMock) as mock_write:
                await service_no_sudo._update_hosts_file("newname")

        # Verify backup was created
        mock_run.assert_called_once_with("cp", str(hosts_file), str(hosts_file.with_suffix(".bak")))

        # Verify content update
        call_args = mock_write.call_args[0]
        assert "127.0.1.1    newname" in call_args[1]
        assert "127.0.1.1    oldname" not in call_args[1]

    @pytest.mark.asyncio
    async def test_when_127_0_1_1_missing_then_adds_line(self, tmp_path, service_no_sudo):
        """Test adding 127.0.1.1 line when missing"""
        hosts_file = tmp_path / "hosts"
        hosts_file.write_text("127.0.0.1    localhost\n")

        service_no_sudo.HOSTS_FILE_PATH = hosts_file

        with patch.object(service_no_sudo, "_run_command", new_callable=AsyncMock):
            with patch.object(service_no_sudo, "_write_file_with_sudo", new_callable=AsyncMock) as mock_write:
                await service_no_sudo._update_hosts_file("newname")

        # Verify line was added
        call_args = mock_write.call_args[0]
        assert "127.0.1.1    newname" in call_args[1]

    @pytest.mark.asyncio
    async def test_when_update_fails_then_restores_backup(self, tmp_path, service_no_sudo):
        """Test backup restoration on failure"""
        hosts_file = tmp_path / "hosts"
        hosts_file.write_text("127.0.0.1    localhost\n127.0.1.1    oldname\n")

        service_no_sudo.HOSTS_FILE_PATH = hosts_file

        async def mock_write_fail(*args):
            raise RuntimeError("Write failed")

        restore_calls = []

        async def mock_restore(*args):
            restore_calls.append(args)

        with patch.object(service_no_sudo, "_run_command", side_effect=mock_restore) as mock_run:
            with patch.object(service_no_sudo, "_write_file_with_sudo", side_effect=mock_write_fail):
                with pytest.raises(RuntimeError, match="Write failed"):
                    await service_no_sudo._update_hosts_file("newname")

        # Verify restore was attempted
        # First call: backup, Second call: restore
        assert mock_run.call_count == 2
        restore_call = mock_run.call_args_list[1][0]
        assert restore_call[0] == "cp"
        assert "hosts.bak" in restore_call[1]


class TestTriggerReboot:
    """Test trigger_reboot method"""

    @pytest.mark.asyncio
    async def test_when_reboot_succeeds_then_returns_success(self, service_no_sudo):
        """Test successful reboot trigger"""
        with patch.object(service_no_sudo, "_run_command", new_callable=AsyncMock):
            result = await service_no_sudo.trigger_reboot()

        assert result.success is True
        assert "initiated" in result.message

    @pytest.mark.asyncio
    async def test_when_reboot_fails_then_raises_exception(self, service_no_sudo):
        """Test reboot failure handling"""

        async def mock_fail(*args):
            raise RuntimeError("Reboot failed")

        with patch.object(service_no_sudo, "_run_command", side_effect=mock_fail):
            with pytest.raises(RuntimeError, match="Reboot failed"):
                await service_no_sudo.trigger_reboot()
