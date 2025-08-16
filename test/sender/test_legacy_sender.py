import os
import tempfile
from unittest.mock import AsyncMock, patch

import aiofiles
import pytest

from sender.legacy.legacy_sender import LegacySenderAdapter


@pytest.mark.asyncio
async def test_when_resend_success_then_delete_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "resend_test.json")
        async with aiofiles.open(test_file, "w") as f:
            await f.write('{"mock": "data"}')

        adapter = LegacySenderAdapter(
            {
                "gateway_id": "TESTGW",
                "resend_dir": tmpdir,
                "cloud": {"ima_url": "https://fake.url"},
                "send_interval_sec": 60,
            },
            device_manager=None,
        )

        mock_resp = AsyncMock()
        mock_resp.text = "00000"

        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            await adapter._resend_failed_files()

        assert not os.path.exists(test_file)


@pytest.mark.asyncio
async def test_when_resend_fail_then_rename_to_retry():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "resend_test.json")
        async with aiofiles.open(test_file, "w") as f:
            await f.write('{"mock": "data"}')

        adapter = LegacySenderAdapter(
            {
                "gateway_id": "TESTGW",
                "resend_dir": tmpdir,
                "cloud": {"ima_url": "https://fake.url"},
                "send_interval_sec": 60,
            },
            device_manager=None,
        )

        mock_resp = AsyncMock()
        mock_resp.text = "99999"  # simulate failure

        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            await adapter._resend_failed_files()

        retry_files = [f for f in os.listdir(tmpdir) if f.endswith(".retry1.json")]
        assert len(retry_files) == 1


@pytest.mark.asyncio
async def test_when_resend_reaches_max_retry_then_rename_to_fail():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "resend_test.retry3.json")
        async with aiofiles.open(test_file, "w") as f:
            await f.write('{"mock": "data"}')

        adapter = LegacySenderAdapter(
            {
                "gateway_id": "TESTGW",
                "resend_dir": tmpdir,
                "cloud": {"ima_url": "https://fake.url"},
                "send_interval_sec": 60,
            },
            device_manager=None,
        )

        mock_resp = AsyncMock()
        mock_resp.text = "fail"

        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            await adapter._resend_failed_files()

        files = os.listdir(tmpdir)
        assert "resend_test.fail" in files
