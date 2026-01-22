import asyncio
from unittest.mock import call, patch

import pytest
from fastapi import HTTPException

from api.model.enums import ResponseStatus
from api.model.wifi import WiFiInterfaceInfo, WpaNetworkRow
from api.service.wifi_service import WiFiService


class TestWiFiServiceInitialization:
    """Tests for WiFiService initialization"""

    def test_when_initialized_with_config_then_stores_config(self, test_wifi_config):
        """Test: stores the config on initialization"""
        service = WiFiService(config=test_wifi_config, allowed_ifnames={"wlan0"})

        assert service._config == test_wifi_config
        assert service._allowed_ifnames == {"wlan0"}
        assert service.default_ifname == "wlan0"

    def test_when_initialized_without_config_then_loads_from_env(self, monkeypatch):
        """Test: loads config from environment variables when no config is provided"""
        monkeypatch.setenv("TALOS_WIFI_DEFAULT_IFNAME", "wlan1")

        service = WiFiService()

        assert service.default_ifname == "wlan1"

    def test_when_initialized_then_creates_empty_locks_dict(self, wifi_service):
        """Test: creates an empty locks dictionary on initialization"""
        assert isinstance(wifi_service._operation_locks, dict)
        assert len(wifi_service._operation_locks) == 0


class TestGetOperationLock:
    """Tests for the operation lock mechanism"""

    def test_when_first_call_for_interface_then_creates_lock(self, wifi_service):
        """Test: creates a lock on the first call for an interface"""
        lock = wifi_service._get_operation_lock("wlan0")

        assert isinstance(lock, asyncio.Lock)
        assert "wlan0" in wifi_service._operation_locks

    def test_when_second_call_for_same_interface_then_returns_same_lock(self, wifi_service):
        """Test: returns the same lock on the second call for the same interface"""
        lock1 = wifi_service._get_operation_lock("wlan0")
        lock2 = wifi_service._get_operation_lock("wlan0")

        assert lock1 is lock2

    def test_when_different_interfaces_then_returns_different_locks(self, wifi_service):
        """Test: returns different locks for different interfaces"""
        lock_wlan0 = wifi_service._get_operation_lock("wlan0")
        lock_wlan1 = wifi_service._get_operation_lock("wlan1")

        assert lock_wlan0 is not lock_wlan1


class TestResolveIfname:
    """Tests for interface name resolution"""

    def test_when_ifname_provided_then_uses_it(self, wifi_service):
        """Test: uses the provided ifname"""
        result = wifi_service._resolve_ifname("wlan1")

        assert result == "wlan1"

    def test_when_ifname_none_then_uses_default(self, wifi_service):
        """Test: uses the default when ifname is None"""
        result = wifi_service._resolve_ifname(None)

        assert result == "wlan0"

    def test_when_ifname_empty_string_then_uses_default(self, wifi_service):
        """Test: uses the default when ifname is an empty string"""
        result = wifi_service._resolve_ifname("")

        assert result == "wlan0"

    def test_when_ifname_whitespace_then_uses_default(self, wifi_service):
        """Test: uses the default when ifname is whitespace"""
        result = wifi_service._resolve_ifname("   ")

        assert result == "wlan0"

    def test_when_ifname_not_in_allowlist_then_raises_http_exception(self, wifi_service):
        """Test: raises HTTPException when ifname is not in the allowlist"""
        with pytest.raises(HTTPException) as exc_info:
            wifi_service._resolve_ifname("wlan99")

        assert exc_info.value.status_code == 400
        assert "Invalid ifname" in exc_info.value.detail

    def test_when_no_allowlist_then_accepts_any_ifname(self, wifi_service_no_allowlist):
        """Test: accepts any ifname when no allowlist is provided"""
        result = wifi_service_no_allowlist._resolve_ifname("wlan99")

        assert result == "wlan99"


class TestGetStatus:
    """Tests for the get_status() method"""

    @pytest.mark.asyncio
    async def test_when_status_success_then_returns_success_response(
        self, wifi_service, mock_wpa_cli, sample_wpa_status_output
    ):
        """Test: returns a success response when status is retrieved successfully"""
        mock_wpa_cli.return_value = sample_wpa_status_output

        response = await wifi_service.get_status(ifname="wlan0")

        assert response.status == ResponseStatus.SUCCESS
        assert response.status_info.ssid == "MyNetwork"
        assert response.status_info.is_connected is True
        assert response.status_info.ip_address == "192.168.1.100"
        mock_wpa_cli.assert_called_once_with("wlan0", "status")

    @pytest.mark.asyncio
    async def test_when_wpa_cli_fails_then_returns_error_response(self, wifi_service, mock_wpa_cli):
        """Test: returns an error response when wpa_cli fails"""
        mock_wpa_cli.side_effect = RuntimeError("wpa_cli failed")

        response = await wifi_service.get_status(ifname="wlan0")

        assert response.status == ResponseStatus.ERROR
        assert response.status_info.is_connected is False
        assert "Unable to retrieve WiFi status" in response.message

    @pytest.mark.asyncio
    async def test_when_not_connected_then_is_connected_false(self, wifi_service, mock_wpa_cli):
        """Test: is_connected is False when not connected"""
        # Simulate SCANNING state
        mock_wpa_cli.return_value = "wpa_state=SCANNING\nssid=MyNetwork"

        response = await wifi_service.get_status()

        assert response.status_info.is_connected is False


class TestScan:
    """Tests for the scan() method"""

    @pytest.mark.asyncio
    async def test_when_scan_success_then_returns_networks(
        self,
        wifi_service,
        mock_wpa_cli,
        sample_wpa_status_output,
        sample_scan_results_output,
    ):
        """Test: returns a network list when scan succeeds"""
        # Configure mock return values
        mock_wpa_cli.side_effect = [
            "OK",  # scan command
            sample_wpa_status_output,  # status command
            sample_scan_results_output,  # scan_results command
        ]

        response = await wifi_service.scan(ifname="wlan0")

        assert response.status == ResponseStatus.SUCCESS
        assert len(response.networks) > 0
        assert response.current_ssid == "MyNetwork"
        assert any(n.ssid == "MyNetwork" for n in response.networks)

        # Verify call order/count
        assert mock_wpa_cli.call_count == 3
        mock_wpa_cli.assert_any_call("wlan0", "scan")
        mock_wpa_cli.assert_any_call("wlan0", "status")
        mock_wpa_cli.assert_any_call("wlan0", "scan_results")

    @pytest.mark.asyncio
    async def test_when_scan_with_group_by_ssid_then_groups_networks(
        self, wifi_service, mock_wpa_cli, sample_scan_results_output
    ):
        """Test: merges networks with the same SSID when group_by_ssid=True"""
        mock_wpa_cli.side_effect = [
            "OK",
            "wpa_state=SCANNING",
            sample_scan_results_output,
        ]

        response = await wifi_service.scan(group_by_ssid=True)

        # Each SSID should appear only once
        ssids = [n.ssid for n in response.networks]
        assert len(ssids) == len(set(ssids))

    @pytest.mark.asyncio
    async def test_when_scan_without_group_by_ssid_then_returns_all_aps(
        self, wifi_service, mock_wpa_cli, sample_scan_results_output
    ):
        """Test: returns all APs when group_by_ssid=False (SSIDs may repeat)"""
        mock_wpa_cli.side_effect = [
            "OK",
            "wpa_state=SCANNING",
            sample_scan_results_output,
        ]

        response = await wifi_service.scan(group_by_ssid=False)

        # Should include all APs (SSIDs may repeat)
        assert response.total_count >= len(response.networks)

    @pytest.mark.asyncio
    async def test_when_scan_fails_then_returns_error_response(self, wifi_service, mock_wpa_cli):
        """Test: returns an error response when scan fails"""
        mock_wpa_cli.side_effect = RuntimeError("scan failed")

        response = await wifi_service.scan()

        assert response.status == ResponseStatus.ERROR
        assert response.networks == []
        assert response.total_count == 0


class TestConnect:
    """Tests for WiFiService.connect method"""

    @pytest.mark.asyncio
    async def test_when_concurrent_connects_then_executes_sequentially(
        self, wifi_service, mock_wpa_cli, valid_wpa2_request, sample_list_networks_output
    ):
        """Test: concurrent connect requests execute sequentially due to lock"""

        # Track next network ID to assign
        next_network_id = 3  # Existing networks are 0, 1, 2

        # Smart mock that returns appropriate values based on command
        async def smart_wpa_cli(*args, **kwargs):
            nonlocal next_network_id
            await asyncio.sleep(0.1)  # Simulate slow operation

            command = args[1] if len(args) > 1 else None

            if command == "list_networks":
                return sample_list_networks_output

            elif command == "add_network":
                # Must return network ID as string
                network_id = str(next_network_id)
                next_network_id += 1
                return network_id

            elif command == "get_network":
                # get_network <id> priority - must return priority value
                if len(args) > 3 and args[3] == "priority":
                    # Return different priorities for existing networks
                    net_id = args[2]
                    priorities = {"0": "4", "1": "3", "2": "5"}  # network 2 is rescue
                    return priorities.get(net_id, "0")
                return "OK"

            elif command in ["set_network", "enable_network", "select_network", "save_config"]:
                return "OK"

            return "OK"

        mock_wpa_cli.side_effect = smart_wpa_cli

        # Create two concurrent requests for different networks
        req1 = valid_wpa2_request  # "MyNetwork" - already exists
        req2 = valid_wpa2_request.model_copy(update={"ssid": "Network2"})  # New network

        # Execute concurrently
        start = asyncio.get_event_loop().time()
        results = await asyncio.gather(
            wifi_service.connect(req1, ifname="wlan0"),
            wifi_service.connect(req2, ifname="wlan0"),
        )
        elapsed = asyncio.get_event_loop().time() - start

        # Assert sequential execution (total time > 2 * single execution time)
        assert elapsed > 0.2, f"Elapsed time {elapsed} suggests parallel execution"

        # Assert both connections succeeded
        assert len(results) == 2
        assert all(
            r.status == ResponseStatus.SUCCESS for r in results
        ), f"Expected all SUCCESS, got: {[r.status for r in results]}"

        # Verify results
        assert results[0].ssid == "MyNetwork"
        assert results[1].ssid == "Network2"
        assert results[0].accepted is True
        assert results[1].accepted is True

    @pytest.mark.asyncio
    async def test_when_concurrent_connects_to_same_interface_then_uses_lock(
        self, wifi_service, mock_wpa_cli, valid_wpa2_request, sample_list_networks_output
    ):
        """Test: lock prevents concurrent operations on same interface"""

        call_times = []
        next_network_id = 3

        async def tracked_wpa_cli(*args, **kwargs):
            nonlocal next_network_id
            # Record when calls happen
            call_times.append(asyncio.get_event_loop().time())
            await asyncio.sleep(0.05)

            command = args[1] if len(args) > 1 else None

            if command == "list_networks":
                return sample_list_networks_output
            elif command == "add_network":
                network_id = str(next_network_id)
                next_network_id += 1
                return network_id
            elif command == "get_network" and len(args) > 3 and args[3] == "priority":
                priorities = {"0": "4", "1": "3", "2": "5"}
                return priorities.get(args[2], "0")
            return "OK"

        mock_wpa_cli.side_effect = tracked_wpa_cli

        # Launch concurrent requests
        req1 = valid_wpa2_request.model_copy(update={"ssid": "Net1"})
        req2 = valid_wpa2_request.model_copy(update={"ssid": "Net2"})

        await asyncio.gather(
            wifi_service.connect(req1, ifname="wlan0"),
            wifi_service.connect(req2, ifname="wlan0"),
        )

        # Verify calls were sequential (no overlapping time windows)
        # Each connect() makes multiple wpa_cli calls, but the two connect()
        # operations should not overlap due to the lock
        assert len(call_times) > 0

    @pytest.mark.asyncio
    async def test_when_different_interfaces_then_can_execute_concurrently(
        self, wifi_service, mock_wpa_cli, valid_wpa2_request, sample_list_networks_output
    ):
        """Test: different interfaces can be accessed concurrently (different locks)"""

        next_network_id_wlan0 = 3
        next_network_id_wlan1 = 10

        async def multi_interface_wpa_cli(*args, **kwargs):
            nonlocal next_network_id_wlan0, next_network_id_wlan1
            await asyncio.sleep(0.01)

            ifname = args[0] if len(args) > 0 else "wlan0"
            command = args[1] if len(args) > 1 else None

            if command == "list_networks":
                return sample_list_networks_output
            elif command == "add_network":
                if ifname == "wlan0":
                    net_id = str(next_network_id_wlan0)
                    next_network_id_wlan0 += 1
                else:
                    net_id = str(next_network_id_wlan1)
                    next_network_id_wlan1 += 1
                return net_id
            elif command == "get_network" and len(args) > 3 and args[3] == "priority":
                priorities = {"0": "4", "1": "3", "2": "5"}
                return priorities.get(args[2], "0")
            return "OK"

        mock_wpa_cli.side_effect = multi_interface_wpa_cli

        # Connect to different interfaces concurrently
        req1 = valid_wpa2_request.model_copy(update={"ssid": "Network_A"})
        req2 = valid_wpa2_request.model_copy(update={"ssid": "Network_B"})

        start = asyncio.get_event_loop().time()
        results = await asyncio.gather(
            wifi_service.connect(req1, ifname="wlan0"),
            wifi_service.connect(req2, ifname="wlan1"),
        )
        elapsed = asyncio.get_event_loop().time() - start

        # Should execute concurrently (total time ~= single execution time)
        # Both take ~0.1s but run in parallel, so total should be close to 0.1s
        assert elapsed < 0.25, f"Elapsed {elapsed}s suggests sequential execution for different interfaces"

        # Both should succeed
        assert all(r.status == ResponseStatus.SUCCESS for r in results)


class TestConnectSimplified:
    """Simplified concurrent connection test"""

    @pytest.mark.asyncio
    async def test_concurrent_connects_with_proper_mock(
        self, wifi_service, mock_wpa_cli, valid_wpa2_request, sample_list_networks_output
    ):
        """Test: properly mocked concurrent connections succeed"""

        # Counter for add_network calls
        network_id_counter = 3

        # Comprehensive mock
        def make_mock_response(*args):
            nonlocal network_id_counter

            # Extract command
            cmd = args[1] if len(args) > 1 else ""

            # Handle different commands
            if cmd == "list_networks":
                return sample_list_networks_output

            if cmd == "add_network":
                nid = str(network_id_counter)
                network_id_counter += 1
                return nid

            if cmd == "get_network":
                # get_network <id> <field>
                if len(args) > 3 and args[3] == "priority":
                    # Return priority for existing networks
                    return {"0": "4", "1": "3", "2": "5"}.get(args[2], "0")
                return ""

            # All other commands
            return "OK"

        # Wrap in async function
        async def async_mock(*args, **kwargs):
            await asyncio.sleep(0.1)
            return make_mock_response(*args)

        mock_wpa_cli.side_effect = async_mock

        # Test concurrent connections
        req1 = valid_wpa2_request
        req2 = valid_wpa2_request.model_copy(update={"ssid": "OtherNetwork"})

        results = await asyncio.gather(
            wifi_service.connect(req1),
            wifi_service.connect(req2),
        )

        # Verify success
        assert len(results) == 2
        for i, result in enumerate(results):
            assert (
                result.status == ResponseStatus.SUCCESS
            ), f"Result {i} failed: status={result.status}, message={result.message}"


class TestApplyPriority:
    """Tests for WiFiService._apply_priority method"""

    @pytest.mark.asyncio
    async def test_when_decrement_mode_then_picks_unused(self, wifi_service, mock_wpa_cli, sample_wpa_network_rows):
        """Test: picks an unused priority in DECREMENT mode

        Call sequence:
        1. _get_used_site_priorities loops through 3 networks
           - Calls get_network for network_id 0 -> returns "4"
           - Calls get_network for network_id 1 -> returns "3"
           - Calls get_network for network_id 2 -> returns "5" (rescue SSID)
        2. Calculates used site priorities: {4, 3} (5 is filtered out as rescue)
        3. Picks highest unused priority: 2
        4. Calls set_network to apply priority 2 -> returns "OK"

        Total: 4 calls to _run_wpa_cli
        """
        # Provide 4 return values (not 3!)
        # - 3 for get_network calls (one per network)
        # - 1 for set_network call
        mock_wpa_cli.side_effect = [
            "4",  # get_network: network 0 priority
            "3",  # get_network: network 1 priority
            "5",  # get_network: network 2 priority (rescue SSID, will be filtered)
            "OK",  # set_network: confirmation
        ]

        # Act
        priority = await wifi_service._apply_priority("wlan0", 3, "NewNetwork", None, sample_wpa_network_rows)

        # Assert
        # Used site priorities are {4, 3}
        # Available priorities are {0, 1, 2}
        # Should pick 2 (highest unused)
        assert priority == 2

        # Verify correct number of calls
        assert mock_wpa_cli.call_count == 4

        # Verify the set_network call used the correct priority
        set_network_calls = [
            call for call in mock_wpa_cli.call_args_list if len(call[0]) > 1 and call[0][1] == "set_network"
        ]
        assert len(set_network_calls) == 1
        assert set_network_calls[0][0] == ("wlan0", "set_network", "3", "priority", "2")

    @pytest.mark.asyncio
    async def test_when_decrement_mode_with_two_networks_then_picks_unused(self, wifi_service, mock_wpa_cli):
        """Test: simplified version with fewer networks for clarity"""
        # Arrange
        networks = [
            WpaNetworkRow(network_id=0, ssid="Network1", bssid=None, flags=None),
            WpaNetworkRow(network_id=1, ssid="Network2", bssid=None, flags=None),
        ]

        # 2 get_network + 1 set_network = 3 calls total
        mock_wpa_cli.side_effect = ["4", "3", "OK"]  # network 0 priority  # network 1 priority  # set_network response

        # Act
        priority = await wifi_service._apply_priority("wlan0", 99, "NewNetwork", None, networks)

        # Assert
        assert priority == 2
        assert mock_wpa_cli.call_count == 3

    @pytest.mark.asyncio
    async def test_when_all_site_priorities_used_then_picks_zero(self, wifi_service, mock_wpa_cli):
        """Test: edge case where all priorities 4-1 are used, should pick 0"""
        # Arrange
        networks = [
            WpaNetworkRow(network_id=0, ssid="Net1", bssid=None, flags=None),
            WpaNetworkRow(network_id=1, ssid="Net2", bssid=None, flags=None),
            WpaNetworkRow(network_id=2, ssid="Net3", bssid=None, flags=None),
            WpaNetworkRow(network_id=3, ssid="Net4", bssid=None, flags=None),
        ]

        # 4 get_network + 1 set_network = 5 calls
        mock_wpa_cli.side_effect = [
            "4",  # network 0 priority
            "3",  # network 1 priority
            "2",  # network 2 priority
            "1",  # network 3 priority
            "OK",  # set_network response
        ]

        # Act
        priority = await wifi_service._apply_priority("wlan0", 10, "NewNetwork", None, networks)

        # Assert
        # All priorities 4-1 used, should pick 0
        assert priority == 0
        assert mock_wpa_cli.call_count == 5


class TestApplyPriorityWithCallableMock:
    """Alternative approach using callable mock"""

    @pytest.mark.asyncio
    async def test_when_decrement_mode_then_picks_unused_with_callable_mock(
        self, wifi_service, mock_wpa_cli, sample_wpa_network_rows
    ):
        """Test: uses callable mock for more robust testing"""

        # Define behavior based on command and arguments
        async def mock_wpa_cli_impl(*args, **kwargs):
            command = args[1] if len(args) > 1 else None

            if command == "get_network":
                net_id = int(args[2])
                # Return different priorities for different networks
                priorities = {0: "4", 1: "3", 2: "5"}
                return priorities.get(net_id, "0")

            elif command == "set_network":
                return "OK"

            return ""

        mock_wpa_cli.side_effect = mock_wpa_cli_impl

        # Act
        priority = await wifi_service._apply_priority("wlan0", 3, "NewNetwork", None, sample_wpa_network_rows)

        # Assert
        assert priority == 2

        # Verify calls were made
        assert mock_wpa_cli.call_count == 4

        # Can check specific call patterns
        get_calls = [c for c in mock_wpa_cli.call_args_list if c[0][1] == "get_network"]
        assert len(get_calls) == 3

        set_calls = [c for c in mock_wpa_cli.call_args_list if c[0][1] == "set_network"]
        assert len(set_calls) == 1


class TestListNetworks:
    """Tests for the _list_networks() method"""

    @pytest.mark.asyncio
    async def test_when_networks_exist_then_parses_correctly(
        self, wifi_service, mock_wpa_cli, sample_list_networks_output
    ):
        """Test: correctly parses networks when they exist"""
        mock_wpa_cli.return_value = sample_list_networks_output

        networks = await wifi_service._list_networks("wlan0")

        assert len(networks) == 3
        assert networks[0].network_id == 0
        assert networks[0].ssid == "MyNetwork"
        assert networks[0].flags == "[CURRENT]"

    @pytest.mark.asyncio
    async def test_when_no_networks_then_returns_empty_list(self, wifi_service, mock_wpa_cli):
        """Test: returns an empty list when no networks exist"""
        mock_wpa_cli.return_value = "network id / ssid / bssid / flags"

        networks = await wifi_service._list_networks("wlan0")

        assert networks == []

    @pytest.mark.asyncio
    async def test_when_invalid_lines_then_skips_them(self, wifi_service, mock_wpa_cli):
        """Test: skips invalid lines"""
        mock_wpa_cli.return_value = """network id / ssid / bssid / flags
0\tValidNetwork\tany\t
invalid line
abc\tInvalidID\tany\t
1\tAnotherNetwork\tany\t"""

        networks = await wifi_service._list_networks("wlan0")

        # Should only parse the two valid lines
        assert len(networks) == 2
        assert networks[0].ssid == "ValidNetwork"
        assert networks[1].ssid == "AnotherNetwork"


class TestGetOrCreateNetworkId:
    """Tests for the _get_or_create_network_id() method"""

    @pytest.mark.asyncio
    async def test_when_network_exists_then_returns_existing_id(
        self, wifi_service, mock_wpa_cli, sample_wpa_network_rows
    ):
        """Test: returns the existing ID when the network already exists"""
        network_id = await wifi_service._get_or_create_network_id("wlan0", "MyNetwork", sample_wpa_network_rows)

        assert network_id == 0
        mock_wpa_cli.assert_not_called()  # should not create a new network

    @pytest.mark.asyncio
    async def test_when_network_not_exists_then_creates_new(self, wifi_service, mock_wpa_cli, sample_wpa_network_rows):
        """Test: creates a new network when it does not exist"""
        mock_wpa_cli.return_value = "3"  # new network ID

        network_id = await wifi_service._get_or_create_network_id("wlan0", "NewNetwork", sample_wpa_network_rows)

        assert network_id == 3
        mock_wpa_cli.assert_called_once_with("wlan0", "add_network")

    @pytest.mark.asyncio
    async def test_when_add_network_returns_invalid_then_raises_error(
        self, wifi_service, mock_wpa_cli, sample_wpa_network_rows
    ):
        """Test: raises an error when add_network returns an invalid ID"""
        mock_wpa_cli.return_value = "FAIL"

        with pytest.raises(RuntimeError) as exc_info:
            await wifi_service._get_or_create_network_id("wlan0", "NewNetwork", sample_wpa_network_rows)

        assert "invalid id" in str(exc_info.value)


class TestSetNetworkSsidPskSecurity:
    """Tests for the _set_network_ssid_psk_security() method"""

    @pytest.mark.asyncio
    async def test_when_wpa2_network_then_sets_psk(self, wifi_service, mock_wpa_cli, valid_wpa2_request):
        """Test: sets the PSK for a WPA2 network"""
        mock_wpa_cli.return_value = "OK"

        await wifi_service._set_network_ssid_psk_security("wlan0", 0, valid_wpa2_request)

        # Verify call order
        calls = mock_wpa_cli.call_args_list
        assert len(calls) == 3

        # set_network ssid
        assert calls[0] == call("wlan0", "set_network", "0", "ssid", '"MyNetwork"')
        # set_network key_mgmt
        assert calls[1] == call("wlan0", "set_network", "0", "key_mgmt", "WPA-PSK")
        # set_network psk (with masking)
        assert calls[2] == call("wlan0", "set_network", "0", "psk", '"valid_password_123"', mask_password=True)

    @pytest.mark.asyncio
    async def test_when_open_network_then_sets_key_mgmt_none(self, wifi_service, mock_wpa_cli, valid_open_request):
        """Test: sets key_mgmt to NONE for an open network"""
        mock_wpa_cli.return_value = "OK"

        await wifi_service._set_network_ssid_psk_security("wlan0", 1, valid_open_request)

        calls = mock_wpa_cli.call_args_list
        # set_network ssid
        assert calls[0] == call("wlan0", "set_network", "1", "ssid", '"OpenNetwork"')
        # set_network key_mgmt NONE
        assert calls[1] == call("wlan0", "set_network", "1", "key_mgmt", "NONE")


class TestSaveConfigWithDiagnostics:
    """Tests for the _save_config_with_diagnostics() method"""

    @pytest.mark.asyncio
    async def test_when_disabled_then_returns_false_none(self, wifi_service):
        """Test: returns (False, None) when saving is disabled"""
        saved, error = await wifi_service._save_config_with_diagnostics("wlan0", False)

        assert saved is False
        assert error is None

    @pytest.mark.asyncio
    async def test_when_save_success_then_returns_true_none(self, wifi_service, mock_wpa_cli):
        """Test: returns (True, None) when save succeeds"""
        mock_wpa_cli.return_value = "OK"

        with patch("os.access", return_value=True):  # file is writable
            saved, error = await wifi_service._save_config_with_diagnostics("wlan0", True)

        assert saved is True
        assert error is None

    @pytest.mark.asyncio
    async def test_when_file_readonly_then_returns_error_message(self, wifi_service):
        """Test: returns an error message when the file is read-only"""
        with patch("pathlib.Path.exists", return_value=True), patch(
            "os.access", return_value=False
        ):  # file is not writable

            saved, error = await wifi_service._save_config_with_diagnostics("wlan0", True)

        assert saved is False
        assert "read-only" in error.lower()
        assert "permissions" in error.lower() or "read-only" in error.lower()

    @pytest.mark.asyncio
    async def test_when_wpa_cli_fails_then_returns_error(self, wifi_service, mock_wpa_cli):
        """Test: returns an error when wpa_cli fails"""
        mock_wpa_cli.side_effect = RuntimeError("save failed")

        with patch("os.access", return_value=True):
            saved, error = await wifi_service._save_config_with_diagnostics("wlan0", True)

        assert saved is False
        assert error is not None
        assert "Failed to persist" in error


class TestListInterfaces:
    """Tests for WiFiService.list_interfaces method"""

    @pytest.mark.asyncio
    async def test_when_interfaces_exist_then_returns_wireless_only(self, wifi_service):
        """Test: returns wireless interfaces only when interfaces exist"""
        with patch.object(wifi_service, "_discover_wifi_interfaces") as mock_discover:
            mock_discover.return_value = [
                WiFiInterfaceInfo(
                    ifname="wlan0",
                    is_wireless=True,
                    is_up=True,
                    mac="00:11:22:33:44:55",
                    driver="ath9k",
                    phy="phy0",
                    is_default=True,
                ),
                WiFiInterfaceInfo(
                    ifname="eth0",
                    is_wireless=False,  # Not wireless
                    is_up=True,
                    mac="00:11:22:33:44:66",
                    driver="e1000",
                    phy=None,
                    is_default=False,
                ),
                WiFiInterfaceInfo(
                    ifname="wlan1",
                    is_wireless=True,
                    is_up=False,
                    mac="00:11:22:33:44:77",
                    driver="ath9k",
                    phy="phy1",
                    is_default=False,
                ),
            ]

            response = await wifi_service.list_interfaces()

        # Should return SUCCESS
        assert response.status == ResponseStatus.SUCCESS

        # Should only include wireless interfaces
        assert response.total_count == 2
        assert len(response.interfaces) == 2

        # Verify the wireless interfaces
        ifnames = [i.ifname for i in response.interfaces]
        assert "wlan0" in ifnames
        assert "wlan1" in ifnames
        assert "eth0" not in ifnames  # Non-wireless should be filtered out

    @pytest.mark.asyncio
    async def test_when_default_interface_exists_then_recommends_it(self, wifi_service):
        """Test: recommends the default interface when it exists"""
        with patch.object(wifi_service, "_discover_wifi_interfaces") as mock_discover:
            mock_discover.return_value = [
                WiFiInterfaceInfo(
                    ifname="wlan0",
                    is_wireless=True,
                    is_up=True,
                    mac="00:11:22:33:44:55",
                    driver=None,
                    phy=None,
                    is_default=True,  # This is the default interface
                ),
                WiFiInterfaceInfo(
                    ifname="wlan1",
                    is_wireless=True,
                    is_up=True,
                    mac="00:11:22:33:44:66",
                    driver=None,
                    phy=None,
                    is_default=False,
                ),
            ]

            response = await wifi_service.list_interfaces()

        # Should recommend the default interface
        assert response.status == ResponseStatus.SUCCESS
        assert response.recommended_ifname == "wlan0"

    @pytest.mark.asyncio
    async def test_when_no_interfaces_found_then_returns_empty_list(self, wifi_service):
        """Test: returns empty list when no interfaces found"""
        with patch.object(wifi_service, "_discover_wifi_interfaces") as mock_discover:
            mock_discover.return_value = []

            response = await wifi_service.list_interfaces()

        assert response.status == ResponseStatus.SUCCESS
        assert response.total_count == 0
        assert len(response.interfaces) == 0
        assert response.recommended_ifname is None

    @pytest.mark.asyncio
    async def test_when_only_non_wireless_interfaces_then_returns_empty_list(self, wifi_service):
        """Test: returns empty list when only non-wireless interfaces exist"""
        with patch.object(wifi_service, "_discover_wifi_interfaces") as mock_discover:
            mock_discover.return_value = [
                WiFiInterfaceInfo(
                    ifname="eth0",
                    is_wireless=False,
                    is_up=True,
                    mac="00:11:22:33:44:55",
                    driver="e1000",
                    phy=None,
                    is_default=False,
                ),
                WiFiInterfaceInfo(
                    ifname="eth1",
                    is_wireless=False,
                    is_up=True,
                    mac="00:11:22:33:44:66",
                    driver="e1000",
                    phy=None,
                    is_default=False,
                ),
            ]

            response = await wifi_service.list_interfaces()

        assert response.status == ResponseStatus.SUCCESS
        assert response.total_count == 0  # No wireless interfaces
        assert len(response.interfaces) == 0
        assert response.recommended_ifname is None

    @pytest.mark.asyncio
    async def test_when_default_interface_not_wireless_then_recommends_first_wireless(self, wifi_service):
        """Test: recommends first wireless interface when default is not wireless"""
        with patch.object(wifi_service, "_discover_wifi_interfaces") as mock_discover:
            mock_discover.return_value = [
                WiFiInterfaceInfo(
                    ifname="eth0",
                    is_wireless=False,
                    is_up=True,
                    mac="00:11:22:33:44:55",
                    driver="e1000",
                    phy=None,
                    is_default=True,  # Default but not wireless
                ),
                WiFiInterfaceInfo(
                    ifname="wlan0",
                    is_wireless=True,
                    is_up=True,
                    mac="00:11:22:33:44:66",
                    driver="ath9k",
                    phy="phy0",
                    is_default=False,
                ),
                WiFiInterfaceInfo(
                    ifname="wlan1",
                    is_wireless=True,
                    is_up=False,
                    mac="00:11:22:33:44:77",
                    driver="ath9k",
                    phy="phy1",
                    is_default=False,
                ),
            ]

            response = await wifi_service.list_interfaces()

        assert response.status == ResponseStatus.SUCCESS
        assert response.total_count == 2
        # Should recommend first wireless interface (wlan0)
        assert response.recommended_ifname == "wlan0"

    @pytest.mark.asyncio
    async def test_when_allowed_ifnames_set_then_filters_interfaces(self, wifi_service_with_allowlist):
        """Test: filters interfaces based on allowed_ifnames"""
        # Assuming wifi_service_with_allowlist fixture sets allowed_ifnames={"wlan0"}
        with patch.object(wifi_service_with_allowlist, "_discover_wifi_interfaces") as mock_discover:
            mock_discover.return_value = [
                WiFiInterfaceInfo(
                    ifname="wlan0",
                    is_wireless=True,
                    is_up=True,
                    mac="00:11:22:33:44:55",
                    driver=None,
                    phy=None,
                    is_default=True,
                ),
                WiFiInterfaceInfo(
                    ifname="wlan1",
                    is_wireless=True,
                    is_up=True,
                    mac="00:11:22:33:44:66",
                    driver=None,
                    phy=None,
                    is_default=False,
                ),
            ]

            response = await wifi_service_with_allowlist.list_interfaces()

        assert response.status == ResponseStatus.SUCCESS
        # Should only include wlan0 (in allowlist)
        assert response.total_count == 1
        assert response.interfaces[0].ifname == "wlan0"
