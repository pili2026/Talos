import pytest
import yaml
from unittest.mock import Mock
from device_manager import AsyncDeviceManager
from schema.sender_schema import SenderModel
from sender.legacy.legacy_sender import LegacySenderAdapter


@pytest.fixture
def sender_config_minimal():
    """Minimal sender config for testing"""
    config_yaml = """
gateway_id: "test_gw_001"
resend_dir: "./test_resend"
cloud:
  ima_url: "http://test.example.com"
send_interval_sec: 60
anchor_offset_sec: 0
tick_grace_sec: 1
fresh_window_sec: 2
attempt_count: 2
max_retry: -1
last_known_ttl_sec: 0
resend_quota_mb: 256
fs_free_min_mb: 512
resend_cleanup_batch: 100
resend_protect_recent_sec: 300
resend_cleanup_enabled: false
fail_resend_enabled: true
fail_resend_interval_sec: 120
fail_resend_batch: 3
last_post_ok_within_sec: 300
resend_start_delay_sec: 180
"""
    config_dict = yaml.safe_load(config_yaml)
    return SenderModel.model_validate(config_dict)


@pytest.fixture
def mock_device_manager():
    """Mock device manager"""
    manager = Mock(spec=AsyncDeviceManager)
    manager.get_device_by_model_and_slave_id = Mock(return_value=None)
    return manager


@pytest.fixture
def sender_adapter(sender_config_minimal, mock_device_manager, tmp_path):
    """Create sender adapter with test config"""
    # Override resend_dir to use tmp_path
    sender_config_minimal.resend_dir = str(tmp_path / "resend")
    adapter = LegacySenderAdapter(sender_config_minimal, mock_device_manager)
    return adapter
