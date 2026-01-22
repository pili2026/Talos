from unittest.mock import AsyncMock, patch

import pytest

from api.model.enum.wifi import SecurityType, SitePriorityMode
from api.model.wifi import WiFiConnectRequest, WpaNetworkRow
from api.model.wifi_config import WiFiConfig
from api.service.wifi_service import WiFiService


@pytest.fixture
def test_wifi_config():
    return WiFiConfig(
        default_ifname="wlan0",
        use_sudo=False,
        timeout_sec=1.0,
        scan_wait_sec=0.1,
        rescue_ssids={"test_rescue", "office_backup"},
        site_priority_mode=SitePriorityMode.DECREMENT,
    )


@pytest.fixture
def wifi_service(test_wifi_config):
    return WiFiService(
        config=test_wifi_config,
        allowed_ifnames={"wlan0", "wlan1"},
    )


@pytest.fixture
def wifi_service_no_allowlist(test_wifi_config):
    return WiFiService(config=test_wifi_config, allowed_ifnames=None)


@pytest.fixture
def sample_scan_results_output():
    return """bssid / frequency / signal level / flags / ssid
00:11:22:33:44:55	2437	-45	[WPA2-PSK-CCMP][ESS]	MyNetwork
11:22:33:44:55:66	2462	-67	[WPA2-PSK-CCMP][WPS][ESS]	Office-WiFi
22:33:44:55:66:77	5180	-52	[WPA2-PSK-CCMP][ESS]	FastNet-5G
33:44:55:66:77:88	2437	-80	[ESS]	OpenNetwork"""


@pytest.fixture
def sample_wpa_status_output():
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
def mock_wpa_cli():
    with patch.object(WiFiService, "_run_wpa_cli", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def valid_wpa2_request():
    return WiFiConnectRequest(
        ssid="MyNetwork",
        security=SecurityType.WPA2,
        psk="valid_password_123",
        save_config=True,
    )


@pytest.fixture
def sample_list_networks_output():
    return """network id / ssid / bssid / flags
0	MyNetwork	any	[CURRENT]
1	Office-WiFi	any	
2	test_rescue	any	[DISABLED]"""


@pytest.fixture
def invalid_open_with_psk_request():
    return WiFiConnectRequest(
        ssid="OpenNetwork",
        security=SecurityType.OPEN,
        psk="should_not_have_password",
    )


@pytest.fixture
def sample_wpa_network_rows():
    return [
        WpaNetworkRow(network_id=0, ssid="MyNetwork", bssid=None, flags="[CURRENT]"),
        WpaNetworkRow(network_id=1, ssid="Office-WiFi", bssid=None, flags=None),
        WpaNetworkRow(network_id=2, ssid="test_rescue", bssid=None, flags="[DISABLED]"),
    ]


@pytest.fixture
def valid_open_request():
    return WiFiConnectRequest(
        ssid="OpenNetwork",
        security=SecurityType.OPEN,
        psk=None,
        save_config=False,
    )


@pytest.fixture
def wifi_service_with_allowlist(test_wifi_config):
    service = WiFiService(config=test_wifi_config, allowed_ifnames={"wlan0"})
    service._run_wpa_cli = AsyncMock()
    return service
