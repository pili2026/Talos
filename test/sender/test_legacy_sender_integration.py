import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from util.time_util import TIMEZONE_INFO


class TestLegacySenderIntegration:
    """Integration test for complete flow"""

    @pytest.mark.asyncio
    async def test_complete_startup_flow_with_delayed_resend(self, sender_adapter):
        """Test complete startup: warmup → scheduler → delayed resend"""
        sender_adapter.resend_start_delay_sec = 0.5

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = Mock()
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = '{"result": "00000"}'
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            snapshot = {
                "device_id": "test_device",
                "model": "TECO_VFD",
                "slave_id": "1",
                "type": "inverter",
                "sampling_ts": datetime.now(TIMEZONE_INFO),
                "values": {"HZ": 50.0},
            }

            await sender_adapter.start()
            await sender_adapter.handle_snapshot(snapshot)
            await asyncio.sleep(2)
            await asyncio.sleep(1)

            assert sender_adapter._resend_task is not None
            assert sender_adapter.last_post_ok_at is not None

            await sender_adapter.stop()
