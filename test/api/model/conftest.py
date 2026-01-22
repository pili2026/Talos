import pytest

from api.model.enum.wifi import SecurityType
from api.model.wifi import WiFiConnectRequest, WpaNetworkRow


@pytest.fixture
def sample_wpa_network_rows():
    """模擬 WpaNetworkRow 清單"""
    return [
        WpaNetworkRow(network_id=0, ssid="MyNetwork", bssid=None, flags="[CURRENT]"),
        WpaNetworkRow(network_id=1, ssid="Office-WiFi", bssid=None, flags=None),
        WpaNetworkRow(network_id=2, ssid="test_rescue", bssid=None, flags="[DISABLED]"),
    ]


@pytest.fixture
def sample_wpa_status_output():
    """Simulate wpa_cli status output"""
    return """bssid=00:11:22:33:44:55
freq=2437
ssid=MyNetwork
id=0
mode=station
pairwise_cipher=CCMP
group_cipher=CCMP
key_mgmt=WPA2-PSK
wpa_state=COMPLETED
ip_address=192.168.1.100
address=aa:bb:cc:dd:ee:ff
uuid=12345678-1234-5678-1234-567812345678"""


@pytest.fixture
def valid_wpa2_request():
    return WiFiConnectRequest(
        ssid="MyNetwork",
        security=SecurityType.WPA2,
        psk="valid_password_123",
        save_config=True,
    )


@pytest.fixture
def valid_open_request():
    return WiFiConnectRequest(
        ssid="OpenNetwork",
        security=SecurityType.OPEN,
        psk=None,
        save_config=False,
    )


@pytest.fixture
def invalid_open_with_psk_request():
    return WiFiConnectRequest(
        ssid="OpenNetwork",
        security=SecurityType.OPEN,
        psk="should_not_have_password",
    )


@pytest.fixture
def invalid_wpa2_no_psk_request():
    return WiFiConnectRequest(
        ssid="SecureNetwork",
        security=SecurityType.WPA2,
        psk=None,
    )
