from unittest.mock import AsyncMock, Mock

import pytest

from core.device.generic.modbus_bus import ModbusBus
from core.model.device_constant import DEFAULT_MISSING_VALUE


class TestModbusBusErrorHandling:
    @pytest.mark.asyncio
    async def test_when_connection_failure_then_returns_missing_values(self):
        """Connection failue shoud return -1"""
        mock_client = Mock()
        mock_client.connected = False
        mock_client.connect = AsyncMock(return_value=False)

        bus = ModbusBus(mock_client, slave_id=1, register_type="holding")
        result = await bus.read_regs(offset=0, count=5)

        assert result == [DEFAULT_MISSING_VALUE] * 5
        assert result == [-1, -1, -1, -1, -1]

    @pytest.mark.asyncio
    async def test_when_modbus_error_response_then_returns_missing_values(self):
        """Modbus error response should return -1"""
        mock_client = Mock()
        mock_client.connected = True

        mock_response = Mock()
        mock_response.isError = Mock(return_value=True)
        mock_client.read_holding_registers = AsyncMock(return_value=mock_response)

        bus = ModbusBus(mock_client, slave_id=1, register_type="holding")
        result = await bus.read_regs(offset=0, count=3)

        assert result == [DEFAULT_MISSING_VALUE] * 3

    @pytest.mark.asyncio
    async def test_when_unsupported_register_type_then_returns_missing_values(self):
        """Unsupported register type should return -1"""
        mock_client = Mock()
        mock_client.connected = True

        bus = ModbusBus(mock_client, slave_id=1, register_type="invalid_type")
        result = await bus.read_regs(offset=0, count=2)

        assert result == [DEFAULT_MISSING_VALUE] * 2
